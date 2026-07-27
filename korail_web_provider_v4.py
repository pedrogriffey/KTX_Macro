from __future__ import annotations

import re

from playwright.sync_api import Locator, Page

from korail_web_provider_v3 import KorailWebSeatProviderV3
from provider_contract import SeatProviderTemporaryError


class KorailWebSeatProviderV4(KorailWebSeatProviderV3):
    """입력칸 위에 덮인 요소와 전용 역 선택 버튼까지 처리합니다."""

    name = "korail_web"

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

        label = "출발역" if kind == "departure" else "도착역"
        field = self._find_station_field(
            page=page,
            kind=kind,
        )

        if field is None:
            raise SeatProviderTemporaryError(
                f"코레일 페이지에서 {label} 입력칸을 찾지 못했습니다. "
                f"진단={self._station_diagnostics(page)}"
            )

        try:
            editable = field.is_editable()
        except Exception:
            editable = False

        if editable:
            try:
                field.click(
                    force=True,
                    timeout=3_000,
                )
                field.fill(
                    station_name,
                    timeout=5_000,
                )
                page.wait_for_timeout(400)

                if not self._click_station_choice(
                    page=page,
                    station_name=station_name,
                ):
                    field.press("Enter")

                page.wait_for_timeout(400)
                return
            except Exception as exc:
                raise SeatProviderTemporaryError(
                    f"{label} 직접 입력에 실패했습니다. "
                    f"진단={self._station_diagnostics(page)}"
                ) from exc

        if not self._open_station_picker(
            page=page,
            field=field,
            label=label,
        ):
            raise SeatProviderTemporaryError(
                f"{label} 선택창을 열지 못했습니다. "
                f"진단={self._station_diagnostics(page)}; "
                f"버튼={self._button_diagnostics(page)}"
            )

        page.wait_for_timeout(500)

        search_input = self._find_station_picker_search(page)

        if search_input is not None:
            try:
                search_input.click(
                    force=True,
                    timeout=3_000,
                )
                search_input.fill(
                    station_name,
                    timeout=5_000,
                )
                page.wait_for_timeout(500)
            except Exception as exc:
                raise SeatProviderTemporaryError(
                    f"{label} 선택창 검색에 실패했습니다. "
                    f"진단={self._station_diagnostics(page)}"
                ) from exc

        if not self._click_station_choice(
            page=page,
            station_name=station_name,
        ):
            raise SeatProviderTemporaryError(
                f"{label} 선택창에서 '{station_name}'을 찾지 못했습니다. "
                f"진단={self._station_diagnostics(page)}"
            )

        page.wait_for_timeout(400)
        self._confirm_station_picker(page)
        page.wait_for_timeout(400)

    def _open_station_picker(
        self,
        page: Page,
        field: Locator,
        label: str,
    ) -> bool:
        attempts = [
            lambda: field.click(timeout=3_000),
            lambda: field.click(
                force=True,
                timeout=3_000,
            ),
            lambda: field.evaluate(
                "element => element.click()"
            ),
            lambda: field.locator("xpath=..").click(
                force=True,
                timeout=3_000,
            ),
        ]

        for attempt in attempts:
            try:
                attempt()
                page.wait_for_timeout(350)

                if self._picker_appeared(page):
                    return True
            except Exception:
                continue

        label_pattern = re.compile(
            rf"{re.escape(label)}\s*(선택)?"
        )

        candidates = [
            page.get_by_role(
                "button",
                name=label_pattern,
            ),
            page.get_by_text(
                f"{label} 선택",
                exact=True,
            ),
            page.locator(
                f'button:has-text("{label}")'
            ),
            page.locator(
                f'[role="button"]:has-text("{label}")'
            ),
            page.locator(
                f'label:has-text("{label}")'
            ),
            page.locator(
                f'a:has-text("{label}")'
            ),
        ]

        for candidate in candidates:
            try:
                count = candidate.count()
            except Exception:
                continue

            for index in range(count):
                item = candidate.nth(index)

                try:
                    if not item.is_visible():
                        continue

                    item.click(
                        force=True,
                        timeout=3_000,
                    )
                    page.wait_for_timeout(350)

                    if self._picker_appeared(page):
                        return True
                except Exception:
                    continue

        # 마지막 수단: DOM에서 텍스트가 일치하는 클릭 가능 요소를 직접 누릅니다.
        try:
            clicked = page.evaluate(
                """
                ({ label }) => {
                  const elements = Array.from(
                    document.querySelectorAll(
                      'button, a, label, [role="button"], div, span'
                    )
                  );

                  const target = elements.find((element) => {
                    const text = (element.innerText || '')
                      .replace(/\s+/g, ' ')
                      .trim();

                    return (
                      text === label ||
                      text === `${label} 선택`
                    );
                  });

                  if (!target) return false;
                  target.click();
                  return true;
                }
                """,
                {
                    "label": label,
                },
            )

            if clicked:
                page.wait_for_timeout(500)
                return self._picker_appeared(page)
        except Exception:
            pass

        return False

    def _picker_appeared(
        self,
        page: Page,
    ) -> bool:
        if self._visible_dialog(page) is not None:
            return True

        if self._find_station_picker_search(page) is not None:
            return True

        body_text = self._normalize_text(
            page.locator("body").inner_text(
                timeout=2_000
            )
        )

        return any(
            marker in body_text
            for marker in (
                "역명검색",
                "역명 검색",
                "주요역",
                "가나다순",
                "역 선택",
            )
        )

    def _button_diagnostics(
        self,
        page: Page,
    ) -> str:
        rows: list[str] = []
        elements = page.locator(
            'button, a, [role="button"]'
        )

        try:
            count = min(elements.count(), 40)
        except Exception:
            count = 0

        for index in range(count):
            item = elements.nth(index)

            try:
                if not item.is_visible():
                    continue

                text = self._normalize_text(
                    item.inner_text(timeout=1_000)
                )

                if not text:
                    text = self._normalize_text(
                        item.get_attribute("aria-label") or ""
                    )

                if text:
                    rows.append(text[:100])
            except Exception:
                continue

        return str(rows[:25])
