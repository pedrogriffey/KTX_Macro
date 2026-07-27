from __future__ import annotations

from typing import Any

from playwright.sync_api import (
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

from korail_web_provider_v5 import KorailWebSeatProviderV5
from provider_contract import (
    SeatProviderTemporaryError,
    SeatProviderUnavailableError,
)


class KorailWebSeatProviderV6(KorailWebSeatProviderV5):
    """코레일 접근 제한 응답을 감지하고 반복 요청을 중지합니다."""

    name = "korail_web"

    def _wait_for_results(
        self,
        page: Page,
        job: dict[str, Any],
    ) -> None:
        train_no = self._normalize_train_no(
            str(job.get("train_no") or "")
        )
        departure_dt = self._parse_job_datetime(
            job.get("departure_planned_at")
        )
        departure_time = departure_dt.strftime("%H:%M")
        requested_date = departure_dt.strftime("%Y-%m-%d")

        try:
            wait_result = page.wait_for_function(
                """
                ({ trainNo, departureTime }) => {
                  const text = document.body?.innerText || '';
                  const normalizedTrain =
                    trainNo.replace(/^0+/, '');

                  const blocked = (
                    text.includes('CODE : -8003') ||
                    text.includes('CODE: -8003') ||
                    text.includes('미허가 도구') ||
                    text.includes('매크로 등') ||
                    text.includes('이용이 제한될 수 있습니다')
                  );

                  if (blocked) return 'blocked';

                  const noSchedule =
                    text.includes('해당 스케줄에 운행하는 열차가 없습니다');

                  if (noSchedule) return 'no_schedule';

                  const hasTrain = (
                    text.includes(trainNo) ||
                    (
                      normalizedTrain &&
                      text.includes(normalizedTrain)
                    )
                  );

                  const hasTime = text.includes(departureTime);
                  const hasSeatResult = (
                    text.includes('일반실') ||
                    text.includes('특실') ||
                    text.includes('매진')
                  );

                  if ((hasTrain || hasTime) && hasSeatResult) {
                    return 'ready';
                  }

                  return false;
                }
                """,
                arg={
                    "trainNo": train_no,
                    "departureTime": departure_time,
                },
                timeout=self.timeout_ms,
            )

            status = wait_result.json_value()

            try:
                body = self._normalize_text(
                    page.locator("body").inner_text(
                        timeout=3_000
                    )
                )
            except Exception:
                body = "본문 확인 불가"

            if status == "blocked":
                raise SeatProviderUnavailableError(
                    "코레일이 서버 자동 조회를 제한했습니다"
                    "(CODE -8003). 반복 조회를 중지합니다. "
                    f"요청일={requested_date}, "
                    f"요청시각={departure_time}, "
                    f"현재 페이지={page.url}"
                )

            if status == "no_schedule":
                raise SeatProviderTemporaryError(
                    "코레일 조회 화면에 운행 열차 없음이 표시됐습니다. "
                    "요청한 날짜·시각이 페이지 상태에 정상 반영되지 않았을 "
                    "가능성이 있습니다. "
                    f"요청일={requested_date}, "
                    f"요청시각={departure_time}, "
                    f"현재 페이지={page.url}, "
                    f"문맥={body[:700]}"
                )

        except SeatProviderUnavailableError:
            raise
        except SeatProviderTemporaryError:
            raise
        except PlaywrightTimeoutError as exc:
            try:
                body = self._normalize_text(
                    page.locator("body").inner_text(
                        timeout=3_000
                    )
                )
            except Exception:
                body = "본문 확인 불가"

            if any(
                marker in body
                for marker in (
                    "CODE : -8003",
                    "CODE: -8003",
                    "미허가 도구",
                    "매크로 등",
                    "이용이 제한될 수 있습니다",
                )
            ):
                raise SeatProviderUnavailableError(
                    "코레일이 서버 자동 조회를 제한했습니다"
                    "(CODE -8003). 반복 조회를 중지합니다. "
                    f"요청일={requested_date}, "
                    f"요청시각={departure_time}, "
                    f"현재 페이지={page.url}"
                ) from exc

            raise SeatProviderTemporaryError(
                "열차 조회 결과가 나타나지 않았습니다. "
                f"현재 페이지={page.url}, "
                f"열차번호={train_no}, "
                f"요청일={requested_date}, "
                f"출발시각={departure_time}, "
                f"문맥={body[:700]}"
            ) from exc
