from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from provider_contract import (
    SeatAvailability,
    SeatCheckResult,
)


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

        if next_count >= available_after:
            return SeatCheckResult(
                availability=SeatAvailability.AVAILABLE,
                result_code="simulation_available",
                detail="연습용 좌석 발견 조건이 충족됐습니다.",
                next_check_count=next_count,
                provider_name=self.name,
                observed_at=datetime.now(timezone.utc),
            )

        return SeatCheckResult(
            availability=SeatAvailability.SOLD_OUT,
            result_code="simulation_sold_out",
            detail=(
                f"연습용 매진 상태 "
                f"({next_count}/{available_after}회)"
            ),
            next_check_count=next_count,
            provider_name=self.name,
            observed_at=datetime.now(timezone.utc),
        )
