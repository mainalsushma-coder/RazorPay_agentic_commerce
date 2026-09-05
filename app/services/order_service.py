import uuid
import os
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any

from app.repositories.catalog_repository import catalog_repository
from app.services.audit_service import log_policy_decision
from app.services.audit_service import log_audit_event
from app.services.payment_executor import PaymentExecutor, build_payment_executor
from app.services.policy_engine import PolicyDecision, evaluate_order_policy
from app.services.razorpay_service import create_razorpay_order

_DEFAULT_SDK_CREATOR = create_razorpay_order


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
    payment_executor: PaymentExecutor | None = None,
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

    from app.services.commerce_catalog_service import get_commerce_merchant

    commerce_merchant = get_commerce_merchant(merchant_id)
    if commerce_merchant is not None and commerce_merchant.source == "shopify":
        return {
            "decision": "external_checkout_required",
            "merchant_id": merchant_id,
            "sku": sku,
            "quantity": quantity,
            "status": "external_checkout_required",
            "reason": "External checkout connection required",
            "checkout_capability": {
                "type": "external", "provider": "shopify", "execution_enabled": False,
            },
            "mandate": {"applied": False, "reason": "The current purchase mandate is INR-only"},
        }

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
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "merchant_name": merchant.name,
        "image_url": product.attributes.get("image_url"),
        "payment_mode": "test" if os.getenv("RAZORPAY_KEY_ID", "").startswith("rzp_test_") else "unknown",
    }

    if decision == PolicyDecision.REQUIRES_CONFIRMATION:
        new_order = {
            "order_id": order_id,
            **metadata,
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
            order_id=order_id,
        )
        return new_order

    if payment_executor is not None:
        executor = payment_executor
    elif payment_order_creator is not None:
        from app.services.payment_executor import RazorpaySDKExecutor
        executor = RazorpaySDKExecutor(payment_order_creator)
    elif create_razorpay_order is not _DEFAULT_SDK_CREATOR:
        # Preserve the established test/custom-injection seam without contacting MCP.
        from app.services.payment_executor import RazorpaySDKExecutor
        executor = RazorpaySDKExecutor(create_razorpay_order)
    else:
        executor = build_payment_executor(create_razorpay_order)
    try:
        razorpay_order = executor.create_order(
        amount_rupees=total,
        currency=product.currency,
        receipt=order_id,
        )
    except Exception:
        log_audit_event("payment_execution_failed", order_id=order_id)
        raise
    selected = razorpay_order.get("payment_executor", "razorpay_sdk")
    new_order = {
        "order_id": order_id,
        **metadata,
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
        "payment_executor": selected,
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
        payment_executor=selected,
        payment_executor_fallback=razorpay_order.get("payment_executor_fallback", False),
    )
    return new_order
