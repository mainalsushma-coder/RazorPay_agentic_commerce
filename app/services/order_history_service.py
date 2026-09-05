"""Read-only, allowlisted presentation of process-local native orders."""
from app.services.order_service import orders
from app.services.audit_service import audit_logs
from app.repositories.catalog_repository import catalog_repository


def order_history():
    result = []
    for order in reversed(list(orders.values())):
        merchant = catalog_repository.get_merchant(order.get("merchant_id"))
        events = [e for e in audit_logs if e.get("order_id") == order["order_id"]]
        row = {key: order.get(key) for key in (
            "order_id", "product_name", "sku", "quantity", "unit_price", "total",
            "currency", "status", "razorpay_order_id", "created_at", "image_url",
        )}
        image = row["image_url"]
        row["image_url"] = image if isinstance(image, str) and image.startswith("/static/assets/") and ".." not in image and "?" not in image else None
        row["merchant_name"] = order.get("merchant_name") or (merchant.name if merchant else order.get("merchant_id", "Unavailable"))
        row["created_at"] = row["created_at"] or next((e["timestamp"] for e in events), None)
        row["status_label"] = {
            "created": "Order created", "requires_confirmation": "Confirmation required",
            "blocked": "Blocked",
        }.get(order.get("status"), "Status unavailable")
        confirmed = any(e.get("decision") == "human_confirmed" for e in events)
        row["policy_decision"] = "human_confirmed" if confirmed else order.get("policy_decision")
        row["authority"] = {"human_confirmed": "Human-confirmed", "approved": "Autonomous",
                            "requires_confirmation": "Awaiting human confirmation",
                            "blocked": "Blocked"}.get(row["policy_decision"], "Unavailable")
        row["receipt"] = order["order_id"] if order.get("razorpay_order_id") else None
        row["payment_executor"] = order.get("payment_executor") if order.get("payment_executor") in {"razorpay_sdk", "razorpay_mcp"} else None
        row["test_mode"] = bool(order.get("razorpay_order_id") and order.get("payment_mode") == "test")
        # Never forward reasons or arbitrary executor/audit payloads.
        row["audit_events"] = [{"timestamp": e.get("timestamp"), "label": {
            "approved": "Policy approved order creation",
            "requires_confirmation": "Policy requires human confirmation",
            "human_confirmed": "Human confirmed order creation",
            "blocked": "Policy blocked order",
        }.get(e.get("decision"), "Payment order creation failed")}
            for e in events if e.get("decision") in {"approved", "requires_confirmation", "human_confirmed", "blocked"}
            or e.get("event") == "payment_execution_failed"]
        result.append(row)
    blocked = [{"timestamp": e.get("timestamp"), "status_label": "Blocked",
                "message": "Purchase attempt blocked. No BOUND or Razorpay order was created."}
               for e in reversed(audit_logs) if e.get("decision") == "blocked" and not e.get("order_id")]
    return {"orders": result, "blocked_attempts": blocked}
