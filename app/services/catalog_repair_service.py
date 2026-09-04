"""Safe, deterministic repair of raw merchant catalog data."""

import copy
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.services.readiness_service import REQUIRED_FIELDS


_PRICE_PATTERN = re.compile(
    r"^\s*(?P<symbol>\u20b9)?\s*(?P<amount>[+-]?\d+(?:,\d{3})*(?:\.\d+)?)"
    r"\s*(?P<code>INR)?\s*$",
    flags=re.IGNORECASE,
)
_INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")


def _parse_price(value: str) -> float | None:
    match = _PRICE_PATTERN.fullmatch(value)
    if match is None:
        return None
    parsed = float(match.group("amount").replace(",", ""))
    return parsed if math.isfinite(parsed) else None


def _indicates_inr(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    match = _PRICE_PATTERN.fullmatch(value)
    return bool(match and (match.group("symbol") or match.group("code")))


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def repair_catalog(
    catalog: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return a repaired deep copy while preserving unsafe values for review."""
    repaired_catalog = copy.deepcopy(list(catalog))
    repairs: list[dict[str, Any]] = []
    unresolved_issues: list[dict[str, Any]] = []

    def record_repair(
        sku: Any,
        field: str,
        old_value: Any,
        new_value: Any,
        reason: str,
    ) -> None:
        repairs.append(
            {
                "sku": sku,
                "field": field,
                "old_value": old_value,
                "new_value": new_value,
                "reason": reason,
            }
        )

    for index, product in enumerate(repaired_catalog):
        sku = product.get("sku") or f"product_{index + 1}"
        original_price = product.get("price")

        if isinstance(original_price, str):
            normalized_price = _parse_price(original_price)
            if normalized_price is not None:
                product["price"] = normalized_price
                record_repair(
                    sku,
                    "price",
                    original_price,
                    normalized_price,
                    "Converted a safely parseable price to a number",
                )

        stock = product.get("stock")
        if isinstance(stock, str) and _INTEGER_PATTERN.fullmatch(stock.strip()):
            normalized_stock = int(stock)
            product["stock"] = normalized_stock
            record_repair(
                sku,
                "stock",
                stock,
                normalized_stock,
                "Converted a numeric stock string to an integer",
            )

        if _is_missing(product.get("currency")) and _indicates_inr(original_price):
            old_currency = product.get("currency")
            product["currency"] = "INR"
            record_repair(
                sku,
                "currency",
                old_currency,
                "INR",
                "Price explicitly indicates INR",
            )

        for field in REQUIRED_FIELDS:
            if _is_missing(product.get(field)):
                unresolved_issues.append(
                    {
                        "sku": sku,
                        "field": field,
                        "reason": "Required field needs merchant input",
                    }
                )

        repaired_price = product.get("price")
        if isinstance(repaired_price, str) and _parse_price(repaired_price) is None:
            unresolved_issues.append(
                {
                    "sku": sku,
                    "field": "price",
                    "reason": "Unparseable price needs merchant input",
                }
            )

    return {
        "catalog": repaired_catalog,
        "repairs": repairs,
        "unresolved_issues": unresolved_issues,
    }
