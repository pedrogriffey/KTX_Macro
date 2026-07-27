from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import unquote
import xml.etree.ElementTree as ET

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class TagoAPIError(RuntimeError):
    """TAGO API 호출 또는 응답 처리 오류입니다."""


class TagoClient:
    """국토교통부 TAGO 열차정보 API 클라이언트입니다."""

    # 공식 공공데이터포털 명세의 현재 Base URL입니다.
    BASE_URL = "https://apis.data.go.kr/1613000/TrainInfo"

    def __init__(self, service_key: str, timeout: int = 20) -> None:
        # Encoding 키를 붙여 넣은 경우에도 한 번 디코딩하여
        # requests가 쿼리스트링을 정상 인코딩하도록 합니다.
        self.service_key = unquote(service_key.strip())
        self.timeout = timeout

        if not self.service_key:
            raise TagoAPIError("공공데이터포털 인증키가 비어 있습니다.")

        retry = Retry(
            total=2,
            connect=2,
            read=2,
            status=2,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )

        self.session = requests.Session()
        self.session.mount(
            "https://",
            HTTPAdapter(max_retries=retry),
        )

    def _request(
        self,
        operation: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {
            "serviceKey": self.service_key,
            "_type": "json",
            "pageNo": 1,
            "numOfRows": 999,
        }

        if params:
            query.update(params)

        url = f"{self.BASE_URL}/{operation}"

        try:
            response = self.session.get(
                url,
                params=query,
                timeout=self.timeout,
            )
        except requests.exceptions.ConnectTimeout as exc:
            raise TagoAPIError(
                "TAGO 서버 연결 시간이 초과됐습니다. 잠시 후 다시 시도하세요."
            ) from exc
        except requests.exceptions.ReadTimeout as exc:
            raise TagoAPIError(
                "TAGO 서버 응답 시간이 초과됐습니다. 잠시 후 다시 시도하세요."
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise TagoAPIError(
                "TAGO 서버 주소에 연결하지 못했습니다. "
                "인터넷 연결 또는 공공데이터 서버 상태를 확인하세요."
            ) from exc
        except requests.RequestException as exc:
            raise TagoAPIError(
                f"TAGO 요청 중 네트워크 오류가 발생했습니다: "
                f"{type(exc).__name__}"
            ) from exc

        # 잘못된 API 경로나 서버 장애를 인증키 오류와 구분합니다.
        if response.status_code == 404:
            raise TagoAPIError(
                "TAGO API 경로를 찾지 못했습니다(HTTP 404). "
                "앱 코드의 API 주소를 확인하세요."
            )

        if response.status_code == 429:
            raise TagoAPIError(
                "TAGO API 호출 한도를 초과했습니다(HTTP 429). "
                "잠시 후 다시 시도하세요."
            )

        if response.status_code >= 500:
            raise TagoAPIError(
                f"TAGO 서버에서 오류가 발생했습니다"
                f"(HTTP {response.status_code}). 잠시 후 다시 시도하세요."
            )

        if response.status_code >= 400:
            error_message = self._extract_error_message(response.text)
            raise TagoAPIError(
                f"TAGO 요청이 거부됐습니다"
                f"(HTTP {response.status_code}): {error_message}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            error_message = self._extract_error_message(response.text)

            raise TagoAPIError(
                "TAGO가 JSON이 아닌 응답을 반환했습니다: "
                f"{error_message}"
            ) from exc

        response_root = data.get("response", {})
        header = response_root.get("header", {}) or {}

        result_code = str(
            header.get("resultCode", "")
        ).strip()
        result_message = str(
            header.get("resultMsg", "")
        ).strip()

        if result_code not in {"00", "0", ""}:
            raise TagoAPIError(
                f"TAGO API 오류 {result_code}: "
                f"{result_message or '상세 메시지 없음'}"
            )

        return response_root.get("body", {}) or {}

    @staticmethod
    def _extract_error_message(text: str) -> str:
        """XML 또는 텍스트 오류 응답에서 안전한 메시지만 추출합니다."""

        cleaned = (text or "").strip()

        if not cleaned:
            return "응답 내용 없음"

        try:
            root = ET.fromstring(cleaned)

            candidates = (
                "returnAuthMsg",
                "errMsg",
                "resultMsg",
                "cmmMsgHeader",
                "returnReasonCode",
            )

            parts: list[str] = []

            for tag in candidates:
                element = root.find(f".//{tag}")
                if (
                    element is not None
                    and element.text
                    and element.text.strip()
                ):
                    parts.append(element.text.strip())

            if parts:
                return " / ".join(dict.fromkeys(parts))
        except ET.ParseError:
            pass

        # 인증키 등 민감한 쿼리스트링은 응답 본문에 포함되지 않지만,
        # 화면이 과도하게 길어지지 않도록 일부만 표시합니다.
        one_line = " ".join(cleaned.split())
        return one_line[:220]

    @staticmethod
    def _items(body: dict[str, Any]) -> list[dict[str, Any]]:
        items_wrapper = body.get("items") or {}

        item = (
            items_wrapper.get("item")
            if isinstance(items_wrapper, dict)
            else []
        )

        if item is None:
            return []

        if isinstance(item, list):
            return [
                row
                for row in item
                if isinstance(row, dict)
            ]

        if isinstance(item, dict):
            return [item]

        return []

    def get_city_codes(self) -> list[dict[str, str]]:
        body = self._request("getCtyCodeList")
        result: list[dict[str, str]] = []

        for row in self._items(body):
            city_code = str(
                row.get("citycode")
                or row.get("cityCode")
                or ""
            ).strip()

            city_name = str(
                row.get("cityname")
                or row.get("cityName")
                or ""
            ).strip()

            if city_code and city_name:
                result.append(
                    {
                        "city_code": city_code,
                        "city_name": city_name,
                    }
                )

        return result

    def get_stations_by_city(
        self,
        city_code: str,
        city_name: str,
    ) -> list[dict[str, str]]:
        body = self._request(
            "getCtyAcctoTrainSttnList",
            {"cityCode": city_code},
        )

        result: list[dict[str, str]] = []

        for row in self._items(body):
            station_id = str(
                row.get("nodeid")
                or row.get("nodeId")
                or ""
            ).strip()

            station_name = str(
                row.get("nodename")
                or row.get("nodeName")
                or ""
            ).strip()

            if station_id and station_name:
                result.append(
                    {
                        "station_id": station_id,
                        "station_name": station_name,
                        "city_code": city_code,
                        "city_name": city_name,
                    }
                )

        return result

    def get_all_stations(self) -> list[dict[str, str]]:
        cities = self.get_city_codes()
        stations: dict[str, dict[str, str]] = {}

        if not cities:
            raise TagoAPIError(
                "TAGO에서 도시코드 목록을 받지 못했습니다. "
                "인증키 승인 상태를 확인하세요."
            )

        for city in cities:
            rows = self.get_stations_by_city(
                city_code=city["city_code"],
                city_name=city["city_name"],
            )

            for row in rows:
                stations[row["station_id"]] = row

        if not stations:
            raise TagoAPIError(
                "TAGO에서 공식 역 목록을 받지 못했습니다. "
                "인증키 승인 상태와 API 응답을 확인하세요."
            )

        name_counts: dict[str, int] = {}

        for row in stations.values():
            station_name = row["station_name"]
            name_counts[station_name] = (
                name_counts.get(station_name, 0) + 1
            )

        result: list[dict[str, str]] = []

        for row in stations.values():
            display_name = row["station_name"]

            if name_counts[row["station_name"]] > 1:
                display_name = (
                    f"{row['station_name']} · {row['city_name']}"
                )

            result.append(
                {
                    **row,
                    "display_name": display_name,
                }
            )

        return sorted(
            result,
            key=lambda row: (
                row["station_name"],
                row["city_name"],
            ),
        )

    def get_timetable(
        self,
        departure_station_id: str,
        arrival_station_id: str,
        departure_date: str,
    ) -> list[dict[str, Any]]:
        """departure_date는 YYYYMMDD 형식입니다."""

        body = self._request(
            "getStrtpntAlocFndTrainInfo",
            {
                "depPlaceId": departure_station_id,
                "arrPlaceId": arrival_station_id,
                "depPlandTime": departure_date,
                "numOfRows": 300,
            },
        )

        result: list[dict[str, Any]] = []

        for row in self._items(body):
            departure_raw = str(
                row.get("depplandtime")
                or row.get("depPlandTime")
                or ""
            ).strip()

            arrival_raw = str(
                row.get("arrplandtime")
                or row.get("arrPlandTime")
                or ""
            ).strip()

            departure_dt = self._parse_datetime(departure_raw)
            arrival_dt = self._parse_datetime(arrival_raw)

            if departure_dt is None or arrival_dt is None:
                continue

            result.append(
                {
                    "train_type": str(
                        row.get("traingradename")
                        or row.get("trainGradeName")
                        or ""
                    ).strip(),
                    "train_no": str(
                        row.get("trainno")
                        or row.get("trainNo")
                        or ""
                    ).strip(),
                    "departure_station": str(
                        row.get("depplacename")
                        or row.get("depPlaceName")
                        or ""
                    ).strip(),
                    "arrival_station": str(
                        row.get("arrplacename")
                        or row.get("arrPlaceName")
                        or ""
                    ).strip(),
                    "departure_dt": departure_dt,
                    "arrival_dt": arrival_dt,
                    "adult_fare": self._to_int(
                        row.get("adultcharge")
                        or row.get("adultCharge")
                    ),
                }
            )

        return sorted(
            result,
            key=lambda row: row["departure_dt"],
        )

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        digits = "".join(
            character
            for character in value
            if character.isdigit()
        )

        for fmt, length in (
            ("%Y%m%d%H%M%S", 14),
            ("%Y%m%d%H%M", 12),
        ):
            if len(digits) >= length:
                try:
                    return datetime.strptime(
                        digits[:length],
                        fmt,
                    )
                except ValueError:
                    continue

        return None

    @staticmethod
    def _to_int(value: Any) -> int | None:
        try:
            if value is None or value == "":
                return None

            return int(
                str(value).replace(",", "")
            )
        except (TypeError, ValueError):
            return None
