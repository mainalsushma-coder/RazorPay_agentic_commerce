import uuid
from datetime import datetime, timezone


audit_logs = []


def log_policy_decision(
    sku: str,
    quantity: int,
    total: float,
    decision: str,
    reason: str,
    order_id: str | None = None,
    razorpay_order_id: str | None = None,
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
    }
    audit_logs.append(entry)
    return entry


def get_audit_logs():
    return audit_logs
