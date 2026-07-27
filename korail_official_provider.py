from __future__ import annotations

from typing import Any

from provider_contract import (
    SeatCheckResult,
    SeatProviderUnavailableError,
)


class KorailOfficialSeatProvider:
    """향후 코레일 공식 승인 API를 연결하기 위한 자리입니다.

    비공식 웹 엔드포인트, 로그인 자동화, CAPTCHA 우회,
    반복 스크래핑은 구현하지 않습니다.
    """

    name = "korail_official"

    def check(
        self,
        job: dict[str, Any],
    ) -> SeatCheckResult:
        del job
        raise SeatProviderUnavailableError(
            "코레일 공식 잔여좌석 API 또는 제휴 승인이 아직 없습니다. "
            "비공식 조회 주소는 사용하지 않습니다."
        )
