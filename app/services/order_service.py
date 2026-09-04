import uuid
from collections.abc import Callable
from typing import Any

from app.repositories.catalog_repository import catalog_repository
from app.services.audit_service import log_policy_decision
from app.services.policy_engine import PolicyDecision, evaluate_order_policy
from app.services.razorpay_service import create_razorpay_order


# Temporary in-memory order storage shared by the API and MCP server.
orders: dict[str, dict[str, Any]] = {}


class OrderServiceError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def create_order(
    sku: str,
    quantity: int,
    *,
    merchant_id: str = "glowcare",
    payment_order_creator: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create an order through catalog validation and the purchase policy."""
    if quantity <= 0:
        log_policy_decision(
            sku=sku,
            quantity=quantity,
            total=0,
            decision=PolicyDecision.BLOCKED.value,
            reason="Quantity must be greater than zero",
        )
        raise OrderServiceError(400, "Quantity must be greater than zero")

    merchant = catalog_repository.get_merchant(merchant_id)
    if merchant is None:
        log_policy_decision(
            sku=sku,
            quantity=quantity,
            total=0,
            decision=PolicyDecision.BLOCKED.value,
            reason="Merchant not found",
        )
        raise OrderServiceError(404, "Merchant not found")

    product = catalog_repository.find_product(merchant_id, sku)
    if product is None:
        log_policy_decision(
            sku=sku,
            quantity=quantity,
            total=0,
            decision=PolicyDecision.BLOCKED.value,
            reason="Product not found",
        )
        raise OrderServiceError(404, "Product not found")

    stock = int(product.stock)
    unit_price = float(product.price)
    total = unit_price * quantity

    if total <= 0:
        log_policy_decision(
            sku=product.sku, quantity=quantity, total=total,
            decision=PolicyDecision.BLOCKED.value,
            reason="Payment amount must be greater than zero",
        )
        raise OrderServiceError(400, "Payment amount must be greater than zero")

    if stock < quantity:
        log_policy_decision(
            sku=product.sku,
            quantity=quantity,
            total=total,
            decision=PolicyDecision.BLOCKED.value,
            reason="Insufficient stock",
        )
        raise OrderServiceError(400, "Insufficient stock")

    policy_result = evaluate_order_policy(
        sku=sku,
        quantity=quantity,
        unit_price=unit_price,
        catalog_product=product,
    )
    decision = policy_result["decision"]
    reason = str(policy_result["reason"])

    if decision == PolicyDecision.BLOCKED:
        log_policy_decision(
            sku=product.sku,
            quantity=quantity,
            total=total,
            decision=PolicyDecision.BLOCKED.value,
            reason=reason,
        )
        return {
            "decision": PolicyDecision.BLOCKED.value,
            "reason": reason,
        }

    order_id = str(uuid.uuid4())

    if decision == PolicyDecision.REQUIRES_CONFIRMATION:
        new_order = {
            "order_id": order_id,
            "razorpay_order_id": None,
            "merchant_id": merchant_id,
            "sku": product.sku,
            "product_name": product.name,
            "quantity": quantity,
            "unit_price": unit_price,
            "total": total,
            "currency": product.currency,
            "status": "requires_confirmation",
            "policy_decision": PolicyDecision.REQUIRES_CONFIRMATION.value,
        }
        orders[order_id] = new_order
        log_policy_decision(
            sku=product.sku,
            quantity=quantity,
            total=total,
            decision=PolicyDecision.REQUIRES_CONFIRMATION.value,
            reason=reason,
        )
        return new_order

    creator = payment_order_creator or create_razorpay_order
    razorpay_order = creator(
        amount_rupees=total,
        receipt=order_id,
    )
    new_order = {
        "order_id": order_id,
        "razorpay_order_id": razorpay_order["id"],
        "merchant_id": merchant_id,
        "sku": product.sku,
        "product_name": product.name,
        "quantity": quantity,
        "unit_price": unit_price,
        "total": total,
        "currency": product.currency,
        "status": "created",
        "policy_decision": PolicyDecision.APPROVED.value,
    }
    orders[order_id] = new_order
    log_policy_decision(
        sku=product.sku,
        quantity=quantity,
        total=total,
        decision=PolicyDecision.APPROVED.value,
        reason=reason,
        order_id=order_id,
        razorpay_order_id=razorpay_order["id"],
    )
    return new_order
