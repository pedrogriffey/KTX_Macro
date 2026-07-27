from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import os
import signal
import sys
import time
import uuid
from typing import Any

from provider_contract import (
    SeatAvailability,
    SeatProviderTemporaryError,
    SeatProviderUnavailableError,
)
from provider_registry import get_provider
from telegram_link import TelegramError, send_message
from worker_rest_client import (
    SupabaseWorkerClient,
    WorkerAPIError,
)


WORKER_VERSION = "10A.2-no9A"
STOP_REQUESTED = False


def configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv(
            "LOG_LEVEL",
            "INFO",
        ).upper(),
        format=(
            "%(asctime)s | %(levelname)s | "
            "%(message)s"
        ),
    )


def request_stop(
    signum: int,
    frame: Any,
) -> None:
    del frame
    global STOP_REQUESTED
    STOP_REQUESTED = True
    logging.info(
        "종료 신호를 받았습니다: %s",
        signum,
    )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(
        timezone.utc
    ).isoformat()


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            str(value).replace(
                "Z",
                "+00:00",
            )
        )
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(timezone.utc)


def build_alert_message(
    job: dict[str, Any],
    check_count: int,
) -> str:
    seat_labels = {
        "general": "일반실",
        "special": "특실",
        "any": "일반실 또는 특실",
    }

    seat_label = seat_labels.get(
        str(job.get("seat_class", "")),
        str(job.get("seat_class", "")),
    )

    provider_name = str(
        job.get("provider") or "simulation"
    )

    if provider_name == "korail_web":
        return (
            "🚨 KTX 잔여좌석 발견\n\n"
            f"구간: "
            f"{job.get('departure_station_name', '')}"
            f" → "
            f"{job.get('arrival_station_name', '')}\n"
            f"열차: {job.get('train_type', '')} "
            f"{job.get('train_no', '')}\n"
            f"출발: {job.get('departure_planned_at', '')}\n"
            f"좌석 조건: {seat_label}\n"
            f"확인 횟수: {check_count}회\n\n"
            "코레일 공개 승차권 예매페이지에서 "
            "예약 가능 표시를 확인했습니다.\n"
            "실제 예매 시점에는 좌석상태가 달라질 수 있습니다.\n"
            "https://www.korail.com/ticket/search"
        )

    return (
        "🚨 KTX 백그라운드 빈자리 발견 테스트\n\n"
        f"구간: "
        f"{job.get('departure_station_name', '')}"
        f" → "
        f"{job.get('arrival_station_name', '')}\n"
        f"열차: {job.get('train_type', '')} "
        f"{job.get('train_no', '')}\n"
        f"출발: {job.get('departure_planned_at', '')}\n"
        f"좌석 조건: {seat_label}\n"
        f"조회 횟수: {check_count}회\n\n"
        "현재 좌석 발견 결과는 연습용 시뮬레이션입니다."
    )


def process_job(
    api: SupabaseWorkerClient,
    bot_token: str,
    worker_id: str,
    job: dict[str, Any],
) -> None:
    job_id = str(job.get("id", ""))
    lock_token = str(job.get("lock_token", ""))

    if not job_id or lock_token != worker_id:
        logging.warning(
            "유효하지 않은 작업 또는 lock token: %s",
            job_id,
        )
        return

    departure_at = parse_datetime(
        job.get("departure_planned_at")
    )

    if (
        departure_at is not None
        and departure_at <= utc_now()
    ):
        api.update_job(
            job_id,
            lock_token,
            {
                "status": "completed",
                "is_enabled": False,
                "completed_reason": "train_departed",
                "last_result": "train_departed",
                "last_error": None,
                "next_check_at": None,
                "locked_at": None,
                "lock_token": None,
                "worker_version": WORKER_VERSION,
            },
        )
        logging.info(
            "출발시간 경과로 작업 종료: %s",
            job_id,
        )
        return

    profile = api.get_profile(
        str(job.get("user_id", ""))
    )

    chat_id = (
        str(
            (profile or {}).get(
                "telegram_chat_id"
            )
            or ""
        ).strip()
    )

    if not chat_id:
        api.update_job(
            job_id,
            lock_token,
            {
                "status": "error",
                "is_enabled": False,
                "last_error": (
                    "Telegram Chat ID가 없습니다."
                ),
                "completed_reason": (
                    "telegram_not_connected"
                ),
                "next_check_at": None,
                "locked_at": None,
                "lock_token": None,
                "worker_version": WORKER_VERSION,
            },
        )
        logging.error(
            "Telegram 미연결 작업 중지: %s",
            job_id,
        )
        return

    provider = get_provider(
        str(job.get("provider") or "simulation")
    )

    api.insert_monitor_event(
        {
            "job_id": job_id,
            "user_id": str(job.get("user_id", "")),
            "event_type": "check_started",
            "provider": provider.name,
            "detail": {
                "worker_version": WORKER_VERSION,
                "current_count": int(
                    job.get("worker_check_count") or 0
                ),
            },
        }
    )

    result = provider.check(job)
    checked_at = utc_now()

    if result.availability == SeatAvailability.AVAILABLE:
        send_message(
            bot_token,
            chat_id,
            build_alert_message(
                job,
                result.next_check_count,
            ),
        )

        api.update_job(
            job_id,
            lock_token,
            {
                "status": "completed",
                "is_enabled": False,
                "worker_check_count": (
                    result.next_check_count
                ),
                "last_checked_at": iso_utc(
                    checked_at
                ),
                "last_result": result.result_code,
                "last_error": None,
                "alert_sent_at": iso_utc(
                    checked_at
                ),
                "completed_reason": result.result_code,
                "next_check_at": None,
                "locked_at": None,
                "lock_token": None,
                "worker_version": WORKER_VERSION,
            },
        )

        api.insert_monitor_event(
            {
                "job_id": job_id,
                "user_id": str(job.get("user_id", "")),
                "event_type": "alert_sent",
                "provider": result.provider_name,
                "result_code": result.result_code,
                "detail": {
                    "check_count": result.next_check_count,
                    "channel": "telegram",
                },
            }
        )

        logging.info(
            "좌석 알림 전송 완료: %s | provider=%s",
            job_id,
            result.provider_name,
        )
        return

    minimum_interval = 3

    interval = max(
        minimum_interval,
        min(
            int(
                job.get(
                    "check_interval_seconds"
                )
                or 5
            ),
            3600,
        ),
    )

    next_check_at = (
        checked_at
        + timedelta(seconds=interval)
    )

    api.insert_monitor_event(
        {
            "job_id": job_id,
            "user_id": str(job.get("user_id", "")),
            "event_type": "check_completed",
            "provider": result.provider_name,
            "result_code": result.result_code,
            "detail": {
                "check_count": result.next_check_count,
                "availability": result.availability.value,
            },
        }
    )

    api.update_job(
        job_id,
        lock_token,
        {
            "status": "active",
            "is_enabled": True,
            "worker_check_count": (
                result.next_check_count
            ),
            "last_checked_at": iso_utc(
                checked_at
            ),
            "last_result": result.result_code,
            "last_error": None,
            "next_check_at": iso_utc(
                next_check_at
            ),
            "locked_at": None,
            "lock_token": None,
            "worker_version": WORKER_VERSION,
        },
    )

    logging.info(
        "좌석 미발견: %s | provider=%s | 다음 조회 %s초 후",
        job_id,
        result.provider_name,
        interval,
    )



def reschedule_temporary_provider_error(
    api: SupabaseWorkerClient,
    worker_id: str,
    job: dict[str, Any],
    error: Exception,
) -> None:
    job_id = str(job.get("id", ""))
    lock_token = str(job.get("lock_token", ""))

    if not job_id or lock_token != worker_id:
        return

    current_interval = int(
        job.get("check_interval_seconds") or 30
    )

    retry_seconds = max(
        60,
        min(
            current_interval * 2,
            600,
        ),
    )

    next_check_at = (
        utc_now()
        + timedelta(seconds=retry_seconds)
    )

    api.insert_monitor_event(
        {
            "job_id": job_id,
            "user_id": str(job.get("user_id", "")),
            "event_type": "provider_temporary_error",
            "provider": str(job.get("provider") or ""),
            "result_code": "provider_temporary_error",
            "detail": {
                "message": str(error)[:600],
                "retry_seconds": retry_seconds,
            },
        }
    )

    api.update_job(
        job_id,
        lock_token,
        {
            "status": "active",
            "is_enabled": True,
            "last_error": str(error)[:800],
            "last_result": "provider_temporary_error",
            "next_check_at": iso_utc(next_check_at),
            "locked_at": None,
            "lock_token": None,
            "worker_version": WORKER_VERSION,
        },
    )


def mark_job_error(
    api: SupabaseWorkerClient,
    worker_id: str,
    job: dict[str, Any],
    error: Exception,
) -> None:
    job_id = str(job.get("id", ""))
    lock_token = str(job.get("lock_token", ""))

    if not job_id or lock_token != worker_id:
        return

    try:
        api.update_job(
            job_id,
            lock_token,
            {
                "status": "error",
                "is_enabled": False,
                "last_error": str(error)[:800],
                "completed_reason": "worker_error",
                "next_check_at": None,
                "locked_at": None,
                "lock_token": None,
                "worker_version": WORKER_VERSION,
            },
        )
    except Exception:
        logging.exception(
            "작업 오류 상태 저장에도 실패했습니다: %s",
            job_id,
        )


def main() -> int:
    configure_logging()

    signal.signal(
        signal.SIGTERM,
        request_stop,
    )
    signal.signal(
        signal.SIGINT,
        request_stop,
    )

    supabase_url = os.getenv(
        "SUPABASE_URL",
        "",
    ).strip()
    secret_key = os.getenv(
        "SUPABASE_SECRET_KEY",
        "",
    ).strip()
    bot_token = os.getenv(
        "TELEGRAM_BOT_TOKEN",
        "",
    ).strip()

    poll_seconds = max(
        1.0,
        float(
            os.getenv(
                "WORKER_POLL_SECONDS",
                "1",
            )
        ),
    )
    batch_size = max(
        1,
        min(
            int(
                os.getenv(
                    "WORKER_BATCH_SIZE",
                    "20",
                )
            ),
            100,
        ),
    )
    heartbeat_seconds = max(
        5,
        int(
            os.getenv(
                "WORKER_HEARTBEAT_SECONDS",
                "15",
            )
        ),
    )

    missing = [
        name
        for name, value in (
            ("SUPABASE_URL", supabase_url),
            (
                "SUPABASE_SECRET_KEY",
                secret_key,
            ),
            (
                "TELEGRAM_BOT_TOKEN",
                bot_token,
            ),
        )
        if not value
    ]

    if missing:
        logging.error(
            "필수 환경변수가 없습니다: %s",
            ", ".join(missing),
        )
        return 1

    worker_id = str(uuid.uuid4())
    started_at = utc_now()

    api = SupabaseWorkerClient(
        supabase_url=supabase_url,
        secret_key=secret_key,
    )
    last_heartbeat_at: datetime | None = None

    logging.info(
        "KTX Worker 시작 | id=%s | version=%s",
        worker_id,
        WORKER_VERSION,
    )

    while not STOP_REQUESTED:
        now = utc_now()

        if (
            last_heartbeat_at is None
            or (
                now - last_heartbeat_at
            ).total_seconds()
            >= heartbeat_seconds
        ):
            try:
                api.upsert_heartbeat(
                    {
                        "worker_id": worker_id,
                        "service_name": (
                            "ktx-seat-worker"
                        ),
                        "worker_version": (
                            WORKER_VERSION
                        ),
                        "started_at": iso_utc(
                            started_at
                        ),
                        "last_seen_at": iso_utc(
                            now
                        ),
                        "metadata": {
                            "provider_mode": (
                                "registry"
                            ),
                            "poll_seconds": (
                                poll_seconds
                            ),
                            "batch_size": (
                                batch_size
                            ),
                        },
                    }
                )
                last_heartbeat_at = now
            except WorkerAPIError:
                logging.exception(
                    "Worker heartbeat 저장 실패"
                )

        try:
            jobs = api.rpc(
                "claim_due_monitor_jobs",
                {
                    "p_worker_id": worker_id,
                    "p_limit": batch_size,
                },
            )
        except WorkerAPIError:
            logging.exception(
                "실행 대상 작업 선점 실패"
            )
            time.sleep(
                min(
                    10.0,
                    poll_seconds * 2,
                )
            )
            continue

        if not jobs:
            time.sleep(poll_seconds)
            continue

        for job in jobs:
            if STOP_REQUESTED:
                break

            try:
                process_job(
                    api=api,
                    bot_token=bot_token,
                    worker_id=worker_id,
                    job=job,
                )
            except SeatProviderTemporaryError as exc:
                logging.warning(
                    "좌석 공급자 일시 오류: %s | %s",
                    job.get("id"),
                    exc,
                )

                try:
                    reschedule_temporary_provider_error(
                        api=api,
                        worker_id=worker_id,
                        job=job,
                        error=exc,
                    )
                except WorkerAPIError:
                    logging.exception(
                        "공급자 일시 오류 재예약 실패"
                    )
                    mark_job_error(
                        api,
                        worker_id,
                        job,
                        exc,
                    )
            except SeatProviderUnavailableError as exc:
                logging.error(
                    "좌석 공급자 사용 불가: %s",
                    job.get("id"),
                )

                try:
                    api.insert_monitor_event(
                        {
                            "job_id": str(job.get("id", "")),
                            "user_id": str(job.get("user_id", "")),
                            "event_type": "provider_unavailable",
                            "provider": str(
                                job.get("provider") or ""
                            ),
                            "result_code": "provider_unavailable",
                            "detail": {
                                "message": str(exc),
                            },
                        }
                    )
                except WorkerAPIError:
                    logging.exception(
                        "공급자 오류 이벤트 저장 실패"
                    )

                mark_job_error(
                    api,
                    worker_id,
                    job,
                    exc,
                )
            except (
                WorkerAPIError,
                TelegramError,
                ValueError,
            ) as exc:
                logging.exception(
                    "작업 처리 실패: %s",
                    job.get("id"),
                )
                mark_job_error(
                    api,
                    worker_id,
                    job,
                    exc,
                )
            except Exception as exc:
                logging.exception(
                    "예상하지 못한 작업 오류: %s",
                    job.get("id"),
                )
                mark_job_error(
                    api,
                    worker_id,
                    job,
                    exc,
                )
    logging.info("KTX Worker 종료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
