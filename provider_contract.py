from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Protocol


class SeatAvailability(str, Enum):
    AVAILABLE = "available"
    SOLD_OUT = "sold_out"
    UNKNOWN = "unknown"
    UNAVAILABLE = "provider_unavailable"


@dataclass(frozen=True)
class SeatCheckResult:
    availability: SeatAvailability
    result_code: str
    detail: str
    next_check_count: int
    provider_name: str
    observed_at: datetime


class SeatProviderError(RuntimeError):
    """좌석 공급자 공통 오류입니다."""


class SeatProviderUnavailableError(SeatProviderError):
    """공급자가 승인되지 않았거나 설정되지 않은 상태입니다."""


class SeatProviderTemporaryError(SeatProviderError):
    """일시적 오류로 추후 재시도할 수 있습니다."""


class SeatProvider(Protocol):
    name: str

    def check(
        self,
        job: dict[str, Any],
    ) -> SeatCheckResult:
        ...
