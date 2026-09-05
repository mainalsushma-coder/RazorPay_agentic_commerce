import uuid
from datetime import datetime, timezone


audit_logs = []


def log_audit_event(event: str, **fields):
    entry = {
        "audit_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    audit_logs.append(entry)
    return entry


def log_policy_decision(
    sku: str,
    quantity: int,
    total: float,
    decision: str,
    reason: str,
    order_id: str | None = None,
    razorpay_order_id: str | None = None,
    payment_executor: str | None = None,
    payment_executor_fallback: bool = False,
):
    entry = {
        "audit_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sku": sku,
        "quantity": quantity,
        "total": total,
        "decision": decision,
        "reason": reason,
        "order_id": order_id,
        "razorpay_order_id": razorpay_order_id,
        "payment_executor": payment_executor,
        "payment_executor_fallback": payment_executor_fallback,
    }
    audit_logs.append(entry)
    return entry


def get_audit_logs():
    return audit_logs
