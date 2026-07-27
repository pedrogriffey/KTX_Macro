from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from supabase import Client


class MonitorJobError(RuntimeError):
    """사용자에게 표시할 모니터링 작업 저장·관리 오류입니다."""


ALLOWED_SEAT_CLASSES = {
    "general",
    "special",
    "any",
}

ALLOWED_USER_STATUSES = {
    "draft",
    "paused",
}

MIN_INTERVAL_SECONDS = 3
MAX_INTERVAL_SECONDS = 3600
KST = ZoneInfo("Asia/Seoul")


def _to_kst_iso(value: str) -> str:
    """화면의 YYYY-MM-DD HH:MM 값을 KST timestamptz 문자열로 변환합니다."""

    text = str(value).strip()

    try:
        parsed = datetime.strptime(
            text,
            "%Y-%m-%d %H:%M",
        )
    except ValueError as exc:
        raise MonitorJobError(
            f"열차 시각 형식을 처리하지 못했습니다: {text}"
        ) from exc

    return parsed.replace(tzinfo=KST).isoformat()


def format_job_datetime(value: Any) -> str:
    if not value:
        return "-"

    text = str(value).strip()

    try:
        parsed = datetime.fromisoformat(
            text.replace("Z", "+00:00")
        )
    except ValueError:
        return text

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)

    return parsed.astimezone(KST).strftime(
        "%Y-%m-%d %H:%M"
    )


def list_monitor_jobs(
    client: Client,
    user_id: str,
) -> list[dict[str, Any]]:
    try:
        response = (
            client.table("monitor_jobs")
            .select(
                "id,user_id,status,"
                "departure_station_id,departure_station_name,"
                "arrival_station_id,arrival_station_name,"
                "travel_date,train_type,train_no,"
                "departure_planned_at,arrival_planned_at,"
                "seat_class,check_interval_seconds,is_enabled,"
                "last_checked_at,last_result,last_error,"
                "alert_sent_at,created_at,updated_at"
            )
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        raise MonitorJobError(
            "저장된 모니터링 작업을 불러오지 못했습니다. "
            "monitor_jobs 테이블과 RLS 정책을 확인하세요."
        ) from exc

    data = response.data or []

    if not isinstance(data, list):
        return []

    return [
        row
        for row in data
        if isinstance(row, dict)
    ]


def create_monitor_job(
    client: Client,
    *,
    user_id: str,
    departure_station_id: str,
    departure_station_name: str,
    arrival_station_id: str,
    arrival_station_name: str,
    travel_date: str,
    train_type: str,
    train_no: str,
    departure_planned_at: str,
    arrival_planned_at: str,
    seat_class: str,
    check_interval_seconds: int,
) -> dict[str, Any]:
    if seat_class not in ALLOWED_SEAT_CLASSES:
        raise MonitorJobError(
            "지원하지 않는 좌석 조건입니다."
        )

    interval = int(check_interval_seconds)

    if not (
        MIN_INTERVAL_SECONDS
        <= interval
        <= MAX_INTERVAL_SECONDS
    ):
        raise MonitorJobError(
            "조회 간격은 3초 이상 3,600초 이하로 설정하세요."
        )

    if departure_station_id == arrival_station_id:
        raise MonitorJobError(
            "출발역과 도착역은 서로 달라야 합니다."
        )

    payload = {
        "user_id": user_id,
        "status": "draft",
        "departure_station_id": departure_station_id,
        "departure_station_name": departure_station_name,
        "arrival_station_id": arrival_station_id,
        "arrival_station_name": arrival_station_name,
        "travel_date": travel_date,
        "train_type": train_type,
        "train_no": train_no,
        "departure_planned_at": _to_kst_iso(
            departure_planned_at
        ),
        "arrival_planned_at": _to_kst_iso(
            arrival_planned_at
        ),
        "seat_class": seat_class,
        "check_interval_seconds": interval,
        # Worker 연결 전에는 절대 자동 실행하지 않습니다.
        "is_enabled": False,
    }

    try:
        response = (
            client.table("monitor_jobs")
            .insert(payload)
            .execute()
        )
    except Exception as exc:
        message = str(exc).lower()

        if (
            "23505" in message
            or "duplicate key" in message
            or "monitor_jobs_user_target_unique_idx"
            in message
        ):
            raise MonitorJobError(
                "같은 날짜·열차·구간·좌석 조건의 작업이 이미 저장돼 있습니다."
            ) from exc

        if (
            "check_interval_seconds" in message
            or "check constraint" in message
            or "23514" in message
        ):
            raise MonitorJobError(
                "Supabase의 조회 간격 제한이 아직 3초로 변경되지 않았습니다. "
                "Step 6B SQL 패치를 먼저 실행하세요."
            ) from exc

        raise MonitorJobError(
            "모니터링 작업을 저장하지 못했습니다."
        ) from exc

    rows = response.data or []

    if isinstance(rows, list) and rows:
        return rows[0]

    return payload


def update_monitor_job_status(
    client: Client,
    *,
    user_id: str,
    job_id: str,
    status: str,
) -> None:
    if status not in ALLOWED_USER_STATUSES:
        raise MonitorJobError(
            "사용자가 변경할 수 없는 작업 상태입니다."
        )

    try:
        (
            client.table("monitor_jobs")
            .update(
                {
                    "status": status,
                    # Worker 연결 전에는 항상 비활성 상태를 유지합니다.
                    "is_enabled": False,
                }
            )
            .eq("id", job_id)
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as exc:
        raise MonitorJobError(
            "모니터링 작업 상태를 변경하지 못했습니다."
        ) from exc


def delete_monitor_job(
    client: Client,
    *,
    user_id: str,
    job_id: str,
) -> None:
    try:
        (
            client.table("monitor_jobs")
            .delete()
            .eq("id", job_id)
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as exc:
        raise MonitorJobError(
            "모니터링 작업을 삭제하지 못했습니다."
        ) from exc
