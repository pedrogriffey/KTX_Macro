from __future__ import annotations

from provider_contract import (
    SeatProvider,
    SeatProviderUnavailableError,
)
from korail_official_provider import (
    KorailOfficialSeatProvider,
)
from korail_web_provider_v5 import (
    KorailWebSeatProviderV5,
)
from simulation_provider import (
    SimulationSeatProvider,
)


def get_provider(
    provider_name: str,
) -> SeatProvider:
    providers: dict[str, SeatProvider] = {
        "simulation": SimulationSeatProvider(),
        "korail_web": KorailWebSeatProviderV5(),
        "korail_official": KorailOfficialSeatProvider(),
    }

    provider = providers.get(
        str(provider_name).strip()
    )

    if provider is None:
        raise SeatProviderUnavailableError(
            f"등록되지 않은 좌석 공급자입니다: {provider_name}"
        )

    return provider
