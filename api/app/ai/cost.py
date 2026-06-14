from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CostRates:
    input_per_million: float
    output_per_million: float


def estimate_cost(input_tokens: int, output_tokens: int, rates: CostRates) -> float:
    cost = (
        input_tokens * rates.input_per_million + output_tokens * rates.output_per_million
    ) / 1_000_000
    return round(cost, 6)
