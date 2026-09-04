from enum import Enum
from typing import Any


AUTO_APPROVE_LIMIT = 2000
MAX_SPEND_LIMIT = 10000


class PolicyDecision(str, Enum):
    APPROVED = "approved"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    BLOCKED = "blocked"


def evaluate_order_policy(
    sku: str,
    quantity: int,
    unit_price: float,
    catalog_product: Any,
) -> dict[str, PolicyDecision | str | float]:
    catalog_price = float(catalog_product.price)
    catalog_stock = int(catalog_product.stock)

    if quantity <= 0:
        return {
            "decision": PolicyDecision.BLOCKED,
            "reason": "Quantity must be greater than 0",
            "calculated_total": 0,
        }

    if sku != catalog_product.sku:
        return {
            "decision": PolicyDecision.BLOCKED,
            "reason": "SKU validation failed",
            "calculated_total": 0,
        }

    if unit_price != catalog_price:
        return {
            "decision": PolicyDecision.BLOCKED,
            "reason": "Price validation failed",
            "calculated_total": 0,
        }

    if catalog_stock < quantity:
        return {
            "decision": PolicyDecision.BLOCKED,
            "reason": "Insufficient stock",
            "calculated_total": 0,
        }

    total = catalog_price * quantity

    if total > MAX_SPEND_LIMIT:
        return {
            "decision": PolicyDecision.BLOCKED,
            "reason": "Order exceeds maximum spend limit",
            "calculated_total": total,
        }

    if total > AUTO_APPROVE_LIMIT:
        return {
            "decision": PolicyDecision.REQUIRES_CONFIRMATION,
            "reason": "Human confirmation required",
            "calculated_total": total,
        }

    return {
        "decision": PolicyDecision.APPROVED,
        "reason": "Order satisfies automatic purchase policy",
        "calculated_total": total,
    }
