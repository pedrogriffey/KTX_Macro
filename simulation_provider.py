from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SeatCheckResult:
    is_available: bool
    result_code: str
    detail: str
    next_check_count: int


class SimulationSeatProvider:
    """실제 좌석 API 연결 전 Worker 동작 검증용 공급자입니다."""

    name = "simulation"

    def check(
        self,
        job: dict[str, Any],
    ) -> SeatCheckResult:
        current_count = int(
            job.get("worker_check_count") or 0
        )
        next_count = current_count + 1

        available_after = int(
            job.get(
                "simulation_available_after_checks"
            )
            or 3
        )

        is_available = (
            next_count >= available_after
        )

        if is_available:
            return SeatCheckResult(
                is_available=True,
                result_code="simulation_available",
                detail=(
                    "연습용 좌석 발견 조건이 충족됐습니다."
                ),
                next_check_count=next_count,
            )

        return SeatCheckResult(
            is_available=False,
            result_code="simulation_sold_out",
            detail=(
                f"연습용 매진 상태 "
                f"({next_count}/{available_after}회)"
            ),
            next_check_count=next_count,
        )
