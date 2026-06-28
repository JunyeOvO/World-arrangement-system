from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


@dataclass(frozen=True)
class TokenPrice:
    input_per_million: Decimal
    cache_read_per_million: Decimal
    output_per_million: Decimal


PRICES_USD_PER_MILLION = {
    "deepseek_flash": TokenPrice(Decimal("0.14"), Decimal("0.0028"), Decimal("0.28")),
    "deepseek-v4-flash": TokenPrice(Decimal("0.14"), Decimal("0.0028"), Decimal("0.28")),
    "deepseek_pro": TokenPrice(Decimal("0.435"), Decimal("0.003625"), Decimal("0.87")),
    "deepseek-v4-pro": TokenPrice(Decimal("0.435"), Decimal("0.003625"), Decimal("0.87")),
    "deepseek-v4-pro[1m]": TokenPrice(Decimal("0.435"), Decimal("0.003625"), Decimal("0.87")),
    "mimo_v25": TokenPrice(Decimal("0.14"), Decimal("0.0028"), Decimal("0.28")),
    "mimo-v2.5": TokenPrice(Decimal("0.14"), Decimal("0.0028"), Decimal("0.28")),
    "mimo_v25_pro": TokenPrice(Decimal("0.435"), Decimal("0.0036"), Decimal("0.87")),
    "mimo-v2.5-pro": TokenPrice(Decimal("0.435"), Decimal("0.0036"), Decimal("0.87")),
    "opencode-go/glm-5.2": TokenPrice(Decimal("1.40"), Decimal("0.26"), Decimal("4.40")),
    "opencode_go_glm52": TokenPrice(Decimal("1.40"), Decimal("0.26"), Decimal("4.40")),
    "glm-5.2": TokenPrice(Decimal("1.40"), Decimal("0.26"), Decimal("4.40")),
    "glm": TokenPrice(Decimal("1.40"), Decimal("0.26"), Decimal("4.40")),
}

MILLION = Decimal(1_000_000)
USD_PRECISION = Decimal("0.000001")


def calculate_token_cost_usd(row: dict[str, Any]) -> float:
    price = _price_for_model(row.get("model"))
    if price is None:
        return 0.0
    input_tokens = _decimal_int(row.get("input_tokens"))
    cache_tokens = _decimal_int(row.get("cache_read_input_tokens"))
    output_tokens = _decimal_int(row.get("output_tokens"))
    cost = (
        input_tokens * price.input_per_million
        + cache_tokens * price.cache_read_per_million
        + output_tokens * price.output_per_million
    ) / MILLION
    return float(cost.quantize(USD_PRECISION, rounding=ROUND_HALF_UP))


def _price_for_model(value: Any) -> TokenPrice | None:
    if not isinstance(value, str):
        return None
    return PRICES_USD_PER_MILLION.get(value.strip().lower())


def _decimal_int(value: Any) -> Decimal:
    try:
        return Decimal(int(value or 0))
    except (TypeError, ValueError):
        return Decimal(0)
