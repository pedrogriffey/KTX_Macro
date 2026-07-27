from __future__ import annotations

from typing import Any

from playwright.sync_api import (
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

from korail_web_provider_v4 import KorailWebSeatProviderV4
from provider_contract import SeatProviderTemporaryError


class KorailWebSeatProviderV5(KorailWebSeatProviderV4):
    """Playwright 결과 대기 함수의 keyword-only arg 호출을 수정합니다."""

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

        try:
            page.wait_for_function(
                """
                ({ trainNo, departureTime }) => {
                  const text = document.body?.innerText || '';
                  const normalizedTrain =
                    trainNo.replace(/^0+/, '');

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

                  return (
                    (hasTrain || hasTime) &&
                    hasSeatResult
                  );
                }
                """,
                arg={
                    "trainNo": train_no,
                    "departureTime": departure_time,
                },
                timeout=self.timeout_ms,
            )
        except PlaywrightTimeoutError as exc:
            try:
                body = self._normalize_text(
                    page.locator("body").inner_text(
                        timeout=3_000
                    )
                )
            except Exception:
                body = "본문 확인 불가"

            raise SeatProviderTemporaryError(
                "열차 조회 결과가 나타나지 않았습니다. "
                f"현재 페이지={page.url}, "
                f"열차번호={train_no}, "
                f"출발시각={departure_time}, "
                f"문맥={body[:700]}"
            ) from exc
