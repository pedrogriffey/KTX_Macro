from __future__ import annotations

import re
from typing import Any

from playwright.sync_api import Locator, Page

from korail_web_provider_v2 import KorailWebSeatProviderV2
from provider_contract import SeatProviderTemporaryError


class KorailWebSeatProviderV3(KorailWebSeatProviderV2):
    """코레일의 읽기 전용 역 입력칸과 역 선택창을 처리합니다."""

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
            field.click(timeout=5_000)
        except Exception as exc:
            raise SeatProviderTemporaryError(
                f"{label} 입력칸을 누르지 못했습니다. "
                f"진단={self._station_diagnostics(page)}"
            ) from exc

        page.wait_for_timeout(400)

        # 이전 형태처럼 직접 입력 가능한 칸이면 그대로 입력합니다.
        try:
            editable = field.is_editable()
        except Exception:
            editable = False

        if editable:
            try:
                field.fill(
                    station_name,
                    timeout=5_000,
                )
                page.wait_for_timeout(500)

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

        # 현재 코레일 화면은 읽기 전용 입력칸을 누르면 역 선택창이 열립니다.
        search_input = self._find_station_picker_search(page)

        if search_input is not None:
            try:
                search_input.click(timeout=5_000)
                search_input.fill(
                    station_name,
                    timeout=5_000,
                )
                page.wait_for_timeout(500)
            except Exception as exc:
                raise SeatProviderTemporaryError(
                    f"{label} 역 선택창 검색에 실패했습니다. "
                    f"진단={self._station_diagnostics(page)}"
                ) from exc

        if not self._click_station_choice(
            page=page,
            station_name=station_name,
        ):
            raise SeatProviderTemporaryError(
                f"{label} 역 선택창에서 '{station_name}'을 찾지 못했습니다. "
                f"진단={self._station_diagnostics(page)}"
            )

        page.wait_for_timeout(400)
        self._confirm_station_picker(page)
        page.wait_for_timeout(400)

    def _find_station_field(
        self,
        page: Page,
        kind: str,
    ) -> Locator | None:
        if kind == "departure":
            label_pattern = re.compile(r"출발역|출발")
            keyword = "출발"
            name_keyword = "dep"
        else:
            label_pattern = re.compile(r"도착역|도착")
            keyword = "도착"
            name_keyword = "arr"

        candidates = [
            page.get_by_role(
                "textbox",
                name=label_pattern,
            ),
            page.locator(
                f'input[placeholder*="{keyword}"]'
            ),
            page.locator(
                f'input[aria-label*="{keyword}"]'
            ),
            page.locator(
                f'input[title*="{keyword}"]'
            ),
            page.locator(
                f'input[name*="{name_keyword}" i]'
            ),
            page.locator(
                f'label:has-text("{keyword}") input'
            ),
        ]

        return self._first_visible(candidates)

    def _find_station_picker_search(
        self,
        page: Page,
    ) -> Locator | None:
        dialog = self._visible_dialog(page)
        roots = [dialog] if dialog is not None else []
        roots.append(page.locator("body"))

        for root in roots:
            candidates = [
                root.locator(
                    'input[placeholder*="역명"]'
                ),
                root.locator(
                    'input[placeholder*="역 검색"]'
                ),
                root.locator(
                    'input[placeholder*="검색"]'
                ),
                root.locator(
                    'input[aria-label*="역"]'
                ),
                root.locator('input[type="search"]'),
                root.get_by_role(
                    "textbox",
                    name=re.compile(r"역|검색"),
                ),
            ]

            found = self._first_editable(candidates)
            if found is not None:
                return found

        # 접근성 이름이 없는 검색칸을 위한 마지막 보완입니다.
        inputs = page.locator("input")

        for index in range(inputs.count()):
            item = inputs.nth(index)

            try:
                if not item.is_visible() or not item.is_editable():
                    continue

                input_type = (
                    item.get_attribute("type") or "text"
                ).lower()

                if input_type in {
                    "date",
                    "radio",
                    "checkbox",
                    "hidden",
                }:
                    continue

                hint = " ".join(
                    filter(
                        None,
                        [
                            item.get_attribute("name"),
                            item.get_attribute("placeholder"),
                            item.get_attribute("aria-label"),
                            item.get_attribute("title"),
                        ],
                    )
                ).lower()

                if any(
                    token in hint
                    for token in (
                        "역",
                        "station",
                        "search",
                        "검색",
                    )
                ):
                    return item
            except Exception:
                continue

        return None

    def _click_station_choice(
        self,
        page: Page,
        station_name: str,
    ) -> bool:
        escaped = re.escape(station_name)
        exact_pattern = re.compile(
            rf"^\s*{escaped}(역)?\s*$"
        )

        dialog = self._visible_dialog(page)
        roots = [dialog] if dialog is not None else []
        roots.append(page.locator("body"))

        for root in roots:
            candidates = [
                root.get_by_role(
                    "button",
                    name=exact_pattern,
                ),
                root.get_by_role(
                    "option",
                    name=exact_pattern,
                ),
                root.get_by_role(
                    "radio",
                    name=exact_pattern,
                ),
                root.get_by_text(
                    station_name,
                    exact=True,
                ),
                root.get_by_text(
                    f"{station_name}역",
                    exact=True,
                ),
            ]

            for candidate in candidates:
                try:
                    count = candidate.count()
                except Exception:
                    continue

                # 선택창 결과는 뒤쪽에 표시되는 경우가 많아 마지막 항목부터 확인합니다.
                for index in range(count - 1, -1, -1):
                    item = candidate.nth(index)

                    try:
                        if item.is_visible():
                            item.click(timeout=5_000)
                            return True
                    except Exception:
                        continue

        return False

    def _confirm_station_picker(
        self,
        page: Page,
    ) -> None:
        dialog = self._visible_dialog(page)

        if dialog is None:
            return

        candidates = [
            dialog.get_by_role(
                "button",
                name=re.compile(r"^(선택|확인|적용|완료)$"),
            ),
            dialog.locator(
                'button:has-text("선택")'
            ),
            dialog.locator(
                'button:has-text("확인")'
            ),
        ]

        for candidate in candidates:
            try:
                count = candidate.count()
            except Exception:
                continue

            for index in range(count - 1, -1, -1):
                item = candidate.nth(index)

                try:
                    if item.is_visible():
                        item.click(timeout=5_000)
                        return
                except Exception:
                    continue

    @staticmethod
    def _visible_dialog(
        page: Page,
    ) -> Locator | None:
        dialogs = page.get_by_role("dialog")

        try:
            count = dialogs.count()
        except Exception:
            return None

        for index in range(count - 1, -1, -1):
            dialog = dialogs.nth(index)

            try:
                if dialog.is_visible():
                    return dialog
            except Exception:
                continue

        return None

    @staticmethod
    def _first_editable(
        candidates: list[Locator],
    ) -> Locator | None:
        for candidate in candidates:
            try:
                count = candidate.count()
            except Exception:
                continue

            for index in range(count):
                item = candidate.nth(index)

                try:
                    if item.is_visible() and item.is_editable():
                        return item
                except Exception:
                    continue

        return None

    def _station_diagnostics(
        self,
        page: Page,
    ) -> str:
        input_rows: list[str] = []
        inputs = page.locator("input")

        try:
            count = min(inputs.count(), 20)
        except Exception:
            count = 0

        for index in range(count):
            item = inputs.nth(index)

            try:
                if not item.is_visible():
                    continue

                input_rows.append(
                    "{" + ", ".join(
                        [
                            f"type={item.get_attribute('type')}",
                            f"name={item.get_attribute('name')}",
                            f"placeholder={item.get_attribute('placeholder')}",
                            f"aria={item.get_attribute('aria-label')}",
                            f"readonly={item.get_attribute('readonly')}",
                            f"value={item.input_value(timeout=1_000)}",
                        ]
                    ) + "}"
                )
            except Exception:
                continue

        dialog = self._visible_dialog(page)
        dialog_text = ""

        if dialog is not None:
            try:
                dialog_text = self._normalize_text(
                    dialog.inner_text(timeout=2_000)
                )[:400]
            except Exception:
                dialog_text = "대화상자 본문 확인 불가"

        return (
            f"url={page.url}; "
            f"inputs={input_rows[:10]}; "
            f"dialog={dialog_text}"
        )
