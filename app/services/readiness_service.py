"""Deterministic checks for merchant catalog readiness."""

import re
from collections.abc import Mapping, Sequence
from typing import Any


REQUIRED_FIELDS = (
    "sku",
    "name",
    "category",
    "description",
    "price",
    "currency",
    "stock",
)


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _string_price_is_parseable(value: str) -> bool:
    """Accept a number decorated with the supported INR marker or code."""
    candidate = value.strip().replace(",", "")
    candidate = re.sub(r"^₹\s*", "", candidate)
    candidate = re.sub(r"\s*INR$", "", candidate, flags=re.IGNORECASE)
    try:
        float(candidate)
    except ValueError:
        return False
    return bool(candidate)


def scan_catalog_readiness(
    catalog: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Scan raw products and return an explainable JSON-serializable report."""
    issues: list[dict[str, Any]] = []
    failed_fields: set[tuple[int, str]] = set()

    def add_issue(
        product_index: int,
        sku: Any,
        field: str,
        issue_type: str,
        message: str,
    ) -> None:
        failed_fields.add((product_index, field))
        issues.append(
            {
                "sku": sku,
                "field": field,
                "issue_type": issue_type,
                "message": message,
            }
        )

    for index, product in enumerate(catalog):
        sku = product.get("sku") or f"product_{index + 1}"

        for field in REQUIRED_FIELDS:
            if _is_missing(product.get(field)):
                issue_type = (
                    "missing_currency"
                    if field == "currency"
                    else "missing_required_field"
                )
                add_issue(
                    index,
                    sku,
                    field,
                    issue_type,
                    f"Required field '{field}' is missing",
                )

        price = product.get("price")
        if not _is_missing(price):
            if isinstance(price, str):
                if _string_price_is_parseable(price):
                    add_issue(
                        index,
                        sku,
                        "price",
                        "non_normalized_price",
                        "Price is parseable but must be stored as a number",
                    )
                else:
                    add_issue(
                        index,
                        sku,
                        "price",
                        "invalid_price",
                        "Price cannot be parsed as a number",
                    )
            elif isinstance(price, bool) or not isinstance(price, (int, float)):
                add_issue(
                    index,
                    sku,
                    "price",
                    "invalid_price",
                    "Price cannot be parsed as a number",
                )

        stock = product.get("stock")
        if not _is_missing(stock) and (
            isinstance(stock, bool) or not isinstance(stock, int)
        ):
            add_issue(
                index,
                sku,
                "stock",
                "non_integer_stock",
                "Stock must be stored as an integer",
            )

    total_products = len(catalog)
    total_checks = total_products * len(REQUIRED_FIELDS)
    failed_checks = len(failed_fields)
    readiness_score = (
        round(((total_checks - failed_checks) / total_checks) * 100, 1)
        if total_checks
        else 100.0
    )
    products_with_failures = {index for index, _ in failed_fields}

    return {
        "readiness_score": readiness_score,
        "total_products": total_products,
        "ready_products": total_products - len(products_with_failures),
        "issue_count": len(issues),
        "issues": issues,
    }
