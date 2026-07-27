from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from playwright.sync_api import (
    Browser,
    TimeoutError as PlaywrightTimeoutError,
)

from korail_web_provider import KorailWebSeatProvider
from provider_contract import (
    SeatAvailability,
    SeatCheckResult,
    SeatProviderTemporaryError,
)


class KorailWebSeatProviderV2(KorailWebSeatProvider):
    """페이지 로딩 최적화와 단계별 오류 진단을 적용한 공급자입니다."""

    name = "korail_web"

    def __init__(self) -> None:
        super().__init__()
        # Render 환경변수가 30초로 남아 있어도 최소 60초를 적용합니다.
        self.timeout_ms = max(self.timeout_ms, 60_000)

    def _check_with_browser(
        self,
        browser: Browser,
        job: dict[str, Any],
        next_count: int,
    ) -> SeatCheckResult:
        context = browser.new_context(
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            ignore_https_errors=True,
            service_workers="block",
            viewport={
                "width": 1280,
                "height": 900,
            },
        )

        page = context.new_page()
        page.set_default_timeout(self.timeout_ms)

        def handle_route(route: Any) -> None:
            if route.request.resource_type in {
                "image",
                "font",
                "media",
            }:
                route.abort()
            else:
                route.continue_()

        page.route("**/*", handle_route)
        stage = "코레일 예매페이지 연결"

        try:
            page.goto(
                self.search_url,
                wait_until="commit",
                timeout=self.timeout_ms,
            )

            stage = "예매 검색화면 표시"
            page.wait_for_function(
                """
                () => {
                  const inputs = Array.from(
                    document.querySelectorAll('input')
                  );
                  const hasDeparture = inputs.some((element) => {
                    const hint = [
                      element.name || '',
                      element.placeholder || '',
                      element.getAttribute('aria-label') || ''
                    ].join(' ');
                    return hint.includes('출발') ||
                           hint.toLowerCase().includes('dep');
                  });
                  const body = document.body?.innerText || '';
                  return hasDeparture || body.includes('출발역');
                }
                """,
                timeout=self.timeout_ms,
            )

            self._stop_if_blocked(page)

            stage = "출발역 입력"
            self._fill_station(
                page=page,
                station_name=str(
                    job.get("departure_station_name") or ""
                ),
                kind="departure",
            )

            stage = "도착역 입력"
            self._fill_station(
                page=page,
                station_name=str(
                    job.get("arrival_station_name") or ""
                ),
                kind="arrival",
            )

            departure_dt = self._parse_job_datetime(
                job.get("departure_planned_at")
            )

            stage = "출발일 입력"
            self._fill_travel_date(
                page=page,
                date_value=departure_dt.strftime("%Y-%m-%d"),
            )

            stage = "열차 조회 버튼 실행"
            self._click_search(page)

            stage = "열차 조회 결과 대기"
            self._wait_for_results(
                page=page,
                job=job,
            )
            self._stop_if_blocked(page)

            stage = "열차 조회 결과 읽기"
            body_text = self._normalize_text(
                page.locator("body").inner_text(
                    timeout=self.timeout_ms
                )
            )

            target_text = self._find_train_text(
                body_text=body_text,
                train_no=str(job.get("train_no") or ""),
                departure_time=departure_dt.strftime("%H:%M"),
            )

            general_status = self._read_seat_status(
                target_text,
                "일반실",
            )
            special_status = self._read_seat_status(
                target_text,
                "특실",
            )

            requested_class = str(
                job.get("seat_class") or "any"
            )

            availability = self._resolve_requested_class(
                requested_class=requested_class,
                general_status=general_status,
                special_status=special_status,
            )

            detail = (
                f"공개 예매페이지 표시: "
                f"일반실={general_status}, "
                f"특실={special_status}. "
                f"확인문맥={target_text[:500]}"
            )

            if availability == SeatAvailability.UNKNOWN:
                raise SeatProviderTemporaryError(
                    "일반실·특실 상태를 판별하지 못했습니다. "
                    f"{detail}"
                )

            result_code = (
                "korail_web_available"
                if availability == SeatAvailability.AVAILABLE
                else "korail_web_sold_out"
            )

            return SeatCheckResult(
                availability=availability,
                result_code=result_code,
                detail=detail,
                next_check_count=next_count,
                provider_name=self.name,
                observed_at=datetime.now(timezone.utc),
            )

        except PlaywrightTimeoutError as exc:
            try:
                current_url = page.url
            except Exception:
                current_url = "확인 불가"

            try:
                body_preview = self._normalize_text(
                    page.locator("body").inner_text(timeout=3000)
                )[:500]
            except Exception:
                body_preview = "본문 확인 불가"

            raise SeatProviderTemporaryError(
                f"{stage} 단계에서 "
                f"{self.timeout_ms // 1000}초를 초과했습니다. "
                f"현재 페이지={current_url}, 문맥={body_preview}"
            ) from exc

        finally:
            context.close()
