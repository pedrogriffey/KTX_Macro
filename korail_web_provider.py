from __future__ import annotations

from datetime import datetime, timezone
import os
import re
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from playwright.sync_api import (
    Browser,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from provider_contract import (
    SeatAvailability,
    SeatCheckResult,
    SeatProviderTemporaryError,
)


KST = ZoneInfo("Asia/Seoul")


class KorailWebSeatProvider:
    """코레일 공개 승차권 예매페이지의 표시상태를 확인합니다.

    포함:
    - 공개 예매페이지 접속
    - 출발역·도착역·출발일 입력
    - 열차번호별 일반실·특실의 가능/매진 표시 확인

    제외:
    - 코레일 로그인
    - 예약·결제 실행
    - CAPTCHA 우회
    - 접속제한 회피
    - 비공개 내부 API 직접 호출
    """

    name = "korail_web"

    def __init__(self) -> None:
        self.search_url = os.getenv(
            "KORAIL_SEARCH_URL",
            "https://www.korail.com/ticket/search",
        ).strip()

        self.timeout_ms = max(
            10_000,
            min(
                int(
                    os.getenv(
                        "KORAIL_BROWSER_TIMEOUT_MS",
                        "30000",
                    )
                ),
                90_000,
            ),
        )

    def check(
        self,
        job: dict[str, Any],
    ) -> SeatCheckResult:
        next_count = int(
            job.get("worker_check_count") or 0
        ) + 1

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    args=["--disable-dev-shm-usage"],
                )

                try:
                    return self._check_with_browser(
                        browser=browser,
                        job=job,
                        next_count=next_count,
                    )
                finally:
                    browser.close()

        except SeatProviderTemporaryError:
            raise
        except PlaywrightTimeoutError as exc:
            raise SeatProviderTemporaryError(
                "코레일 공개 예매페이지 응답 시간이 초과됐습니다."
            ) from exc
        except Exception as exc:
            raise SeatProviderTemporaryError(
                "코레일 공개 예매페이지 확인 중 오류가 발생했습니다: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def _check_with_browser(
        self,
        browser: Browser,
        job: dict[str, Any],
        next_count: int,
    ) -> SeatCheckResult:
        context = browser.new_context(
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={
                "width": 1280,
                "height": 900,
            },
        )

        page = context.new_page()
        page.set_default_timeout(self.timeout_ms)

        try:
            page.goto(
                self.search_url,
                wait_until="domcontentloaded",
                timeout=self.timeout_ms,
            )

            self._stop_if_blocked(page)

            self._fill_station(
                page=page,
                station_name=str(
                    job.get("departure_station_name") or ""
                ),
                kind="departure",
            )
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

            self._fill_travel_date(
                page=page,
                date_value=departure_dt.strftime("%Y-%m-%d"),
            )
            self._click_search(page)
            self._wait_for_results(
                page=page,
                job=job,
            )
            self._stop_if_blocked(page)

            body_text = self._normalize_text(
                page.locator("body").inner_text()
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

        finally:
            context.close()

    def _fill_station(
        self,
        page: Page,
        station_name: str,
        kind: str,
    ) -> None:
        if not station_name:
            raise SeatProviderTemporaryError(
                "조회할 역 이름이 없습니다."
            )

        if kind == "departure":
            candidates = [
                page.locator(
                    'input[placeholder*="출발역"]'
                ),
                page.locator(
                    'input[aria-label*="출발역"]'
                ),
                page.locator(
                    'input[name*="dep" i]'
                ),
                page.get_by_role(
                    "textbox",
                    name=re.compile("출발"),
                ),
            ]
            label = "출발역"
        else:
            candidates = [
                page.locator(
                    'input[placeholder*="도착역"]'
                ),
                page.locator(
                    'input[aria-label*="도착역"]'
                ),
                page.locator(
                    'input[name*="arr" i]'
                ),
                page.get_by_role(
                    "textbox",
                    name=re.compile("도착"),
                ),
            ]
            label = "도착역"

        field = self._first_visible(candidates)

        if field is None:
            raise SeatProviderTemporaryError(
                f"코레일 페이지에서 {label} 입력칸을 찾지 못했습니다."
            )

        field.click()
        field.fill(station_name)
        page.wait_for_timeout(500)

        options = page.get_by_text(
            station_name,
            exact=True,
        )

        clicked = False

        for index in range(
            options.count() - 1,
            -1,
            -1,
        ):
            option = options.nth(index)

            try:
                if option.is_visible():
                    option.click()
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            field.press("Enter")

        page.wait_for_timeout(300)

    def _fill_travel_date(
        self,
        page: Page,
        date_value: str,
    ) -> None:
        candidates = [
            page.locator('input[type="date"]'),
            page.locator(
                'input[placeholder*="날짜"]'
            ),
            page.locator(
                'input[aria-label*="출발일"]'
            ),
            page.locator(
                'input[name*="date" i]'
            ),
        ]

        field = self._first_visible(candidates)

        if field is not None:
            try:
                field.fill(date_value)
                page.wait_for_timeout(200)
                return
            except Exception:
                pass

        changed = page.evaluate(
            """
            (dateValue) => {
              const inputs = Array.from(
                document.querySelectorAll('input')
              );

              const target = inputs.find((element) => {
                const hint = [
                  element.type || '',
                  element.name || '',
                  element.placeholder || '',
                  element.getAttribute('aria-label') || ''
                ].join(' ').toLowerCase();

                return (
                  element.type === 'date' ||
                  hint.includes('date') ||
                  hint.includes('출발일') ||
                  hint.includes('가는날') ||
                  hint.includes('날짜')
                );
              });

              if (!target) return false;

              const descriptor =
                Object.getOwnPropertyDescriptor(
                  HTMLInputElement.prototype,
                  'value'
                );

              if (descriptor && descriptor.set) {
                descriptor.set.call(target, dateValue);
              } else {
                target.value = dateValue;
              }

              target.dispatchEvent(
                new Event('input', { bubbles: true })
              );
              target.dispatchEvent(
                new Event('change', { bubbles: true })
              );

              return true;
            }
            """,
            date_value,
        )

        if not changed:
            raise SeatProviderTemporaryError(
                "코레일 페이지에서 출발일 입력칸을 찾지 못했습니다."
            )

    def _click_search(
        self,
        page: Page,
    ) -> None:
        candidates = [
            page.get_by_role(
                "button",
                name=re.compile(
                    r"열차\s*조회|조회하기"
                ),
            ),
            page.locator(
                'button:has-text("열차 조회")'
            ),
            page.locator(
                'button:has-text("조회")'
            ),
        ]

        button = self._first_visible(candidates)

        if button is None:
            raise SeatProviderTemporaryError(
                "코레일 페이지에서 열차 조회 버튼을 찾지 못했습니다."
            )

        button.click()

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

                  return (
                    text.includes(departureTime) ||
                    text.includes(trainNo) ||
                    (
                      normalizedTrain &&
                      text.includes(normalizedTrain)
                    )
                  );
                }
                """,
                {
                    "trainNo": train_no,
                    "departureTime": departure_time,
                },
                timeout=self.timeout_ms,
            )
        except PlaywrightTimeoutError as exc:
            body = self._normalize_text(
                page.locator("body").inner_text()
            )

            raise SeatProviderTemporaryError(
                "열차 조회 결과가 나타나지 않았습니다. "
                f"현재 페이지={page.url}, 문맥={body[:500]}"
            ) from exc

    def _stop_if_blocked(
        self,
        page: Page,
    ) -> None:
        text = self._normalize_text(
            page.locator("body").inner_text()
        ).lower()

        markers = (
            "captcha",
            "자동입력",
            "비정상적인 접근",
            "접속이 제한",
            "이용이 제한",
            "매크로",
            "접속 대기",
            "대기순서",
        )

        for marker in markers:
            if marker.lower() in text:
                raise SeatProviderTemporaryError(
                    "코레일 페이지가 추가 확인 또는 접속 제한을 "
                    f"요청했습니다({marker}). 우회하지 않고 중지합니다."
                )

    def _find_train_text(
        self,
        body_text: str,
        train_no: str,
        departure_time: str,
    ) -> str:
        normalized_train = self._normalize_train_no(
            train_no
        )
        bare_train = normalized_train.lstrip("0") or "0"

        patterns = [
            re.compile(
                rf"(?<!\d)0*{re.escape(bare_train)}(?!\d)"
            ),
            re.compile(
                re.escape(normalized_train)
            ),
        ]

        positions: list[int] = []

        for pattern in patterns:
            positions.extend(
                match.start()
                for match in pattern.finditer(body_text)
            )

        if not positions:
            raise SeatProviderTemporaryError(
                f"조회 결과에서 열차번호 {train_no}를 찾지 못했습니다. "
                f"페이지 문맥={body_text[:700]}"
            )

        best_position = positions[0]
        best_score = 10**9

        for position in positions:
            start = max(0, position - 500)
            end = min(
                len(body_text),
                position + 1000,
            )
            snippet = body_text[start:end]
            time_position = snippet.find(
                departure_time
            )
            score = (
                abs(time_position - 500)
                if time_position >= 0
                else 10**8
            )

            if score < best_score:
                best_score = score
                best_position = position

        return body_text[
            max(0, best_position - 500):
            min(
                len(body_text),
                best_position + 1200,
            )
        ]

    def _read_seat_status(
        self,
        text: str,
        seat_label: str,
    ) -> str:
        label_position = text.find(seat_label)

        if label_position < 0:
            return "unknown"

        area = text[
            label_position:
            min(
                len(text),
                label_position + 160,
            )
        ]

        if any(
            marker in area
            for marker in (
                "매진",
                "없음",
                "예약불가",
                "선택불가",
                "판매종료",
            )
        ):
            return "sold_out"

        if any(
            marker in area
            for marker in (
                "있음",
                "가능",
                "예약",
                "예매",
                "좌석선택",
                "선택",
            )
        ):
            return "available"

        return "unknown"

    @staticmethod
    def _resolve_requested_class(
        requested_class: str,
        general_status: str,
        special_status: str,
    ) -> SeatAvailability:
        if requested_class == "general":
            statuses = [general_status]
        elif requested_class == "special":
            statuses = [special_status]
        else:
            statuses = [
                general_status,
                special_status,
            ]

        if "available" in statuses:
            return SeatAvailability.AVAILABLE

        if statuses and all(
            status == "sold_out"
            for status in statuses
        ):
            return SeatAvailability.SOLD_OUT

        return SeatAvailability.UNKNOWN

    @staticmethod
    def _first_visible(
        candidates: Iterable[Locator],
    ) -> Locator | None:
        for candidate in candidates:
            try:
                count = candidate.count()
            except Exception:
                continue

            for index in range(count):
                item = candidate.nth(index)

                try:
                    if item.is_visible():
                        return item
                except Exception:
                    continue

        return None

    @staticmethod
    def _parse_job_datetime(
        value: Any,
    ) -> datetime:
        if not value:
            raise SeatProviderTemporaryError(
                "열차 출발시각이 없습니다."
            )

        try:
            parsed = datetime.fromisoformat(
                str(value).replace(
                    "Z",
                    "+00:00",
                )
            )
        except ValueError as exc:
            raise SeatProviderTemporaryError(
                f"열차 출발시각 형식을 처리하지 못했습니다: {value}"
            ) from exc

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=KST)

        return parsed.astimezone(KST)

    @staticmethod
    def _normalize_train_no(
        train_no: str,
    ) -> str:
        digits = "".join(
            character
            for character in str(train_no)
            if character.isdigit()
        )

        return digits or str(train_no).strip()

    @staticmethod
    def _normalize_text(
        text: str,
    ) -> str:
        return re.sub(
            r"\s+",
            " ",
            str(text or ""),
        ).strip()
