"""Validation and preview-only application of merchant catalog facts."""

import copy
import math
from collections.abc import Mapping, Sequence
from typing import Any

from app.services.readiness_service import REQUIRED_FIELDS, scan_catalog_readiness


class CatalogResolutionError(ValueError):
    pass


def _validate_value(field: str, value: Any) -> None:
    if field == "price":
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise CatalogResolutionError("Price must be a positive number")
        return

    if field == "stock":
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CatalogResolutionError(
                "Stock must be a non-negative integer"
            )
        return

    if not isinstance(value, str) or not value.strip():
        raise CatalogResolutionError(
            f"Required text field '{field}' cannot be empty"
        )


def apply_merchant_resolutions(
    catalog: Sequence[Mapping[str, Any]],
    unresolved_issues: Sequence[Mapping[str, Any]],
    resolutions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Apply validated merchant facts to a deep copy of a repaired catalog."""
    resolved_catalog = copy.deepcopy(list(catalog))
    products_by_sku = {product.get("sku"): product for product in resolved_catalog}
    unresolved_keys = {
        (issue.get("sku"), issue.get("field")) for issue in unresolved_issues
    }
    applied: list[dict[str, Any]] = []
    seen: set[tuple[Any, str]] = set()

    for resolution in resolutions:
        sku = resolution["sku"]
        field = resolution["field"]
        value = resolution["value"]

        if sku not in products_by_sku:
            raise CatalogResolutionError(f"Unknown SKU: {sku}")
        if field not in REQUIRED_FIELDS:
            raise CatalogResolutionError(f"Unsupported field: {field}")

        _validate_value(field, value)

        key = (sku, field)
        if key not in unresolved_keys:
            raise CatalogResolutionError(
                f"Field '{field}' for SKU '{sku}' is not currently unresolved"
            )
        if key in seen:
            raise CatalogResolutionError(
                f"Duplicate resolution for field '{field}' and SKU '{sku}'"
            )

        products_by_sku[sku][field] = value
        applied.append({"sku": sku, "field": field, "value": value})
        seen.add(key)

    final_report = scan_catalog_readiness(resolved_catalog)
    remaining = [
        {
            "sku": issue["sku"],
            "field": issue["field"],
            "reason": issue["message"],
        }
        for issue in final_report["issues"]
    ]
    return {
        "catalog": resolved_catalog,
        "merchant_resolutions": applied,
        "remaining_unresolved_issues": remaining,
    }
