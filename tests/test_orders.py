import os

os.environ.setdefault("RAZORPAY_KEY_ID", "test_key")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "test_secret")

from fastapi.testclient import TestClient

import app.main as main
from app.services.audit_service import audit_logs


client = TestClient(main.app)


def setup_function():
    audit_logs.clear()
    main.orders.clear()


def test_approved_order_calls_razorpay(monkeypatch):
    calls = []

    def fake_create_razorpay_order(amount_rupees, receipt):
        calls.append({"amount_rupees": amount_rupees, "receipt": receipt})
        return {"id": "order_test_approved"}

    monkeypatch.setattr(main, "create_razorpay_order", fake_create_razorpay_order)

    response = client.post("/orders", json={"sku": "SKIN001", "quantity": 2})

    assert response.status_code == 200
    assert response.json()["policy_decision"] == "approved"
    assert response.json()["razorpay_order_id"] == "order_test_approved"
    assert len(calls) == 1
    assert calls[0]["amount_rupees"] == 1398.0


def test_order_requiring_confirmation_does_not_call_razorpay(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Razorpay must not be called")

    monkeypatch.setattr(main, "create_razorpay_order", fail_if_called)

    response = client.post("/orders", json={"sku": "SKIN001", "quantity": 3})

    assert response.status_code == 200
    assert response.json()["status"] == "requires_confirmation"
    assert response.json()["policy_decision"] == "requires_confirmation"
    assert response.json()["razorpay_order_id"] is None
    assert response.json()["order_id"] in main.orders


def test_blocked_order_does_not_call_razorpay(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Razorpay must not be called")

    monkeypatch.setattr(main, "create_razorpay_order", fail_if_called)

    response = client.post("/orders", json={"sku": "SKIN001", "quantity": 15})

    assert response.status_code == 403
    assert response.json() == {
        "decision": "blocked",
        "reason": "Order exceeds maximum spend limit",
    }
    assert "razorpay_order_id" not in response.json()


def test_audit_contains_all_policy_decisions(monkeypatch):
    monkeypatch.setattr(
        main,
        "create_razorpay_order",
        lambda amount_rupees, receipt: {"id": "order_test_approved"},
    )

    client.post("/orders", json={"sku": "SKIN001", "quantity": 2})
    client.post("/orders", json={"sku": "SKIN001", "quantity": 3})
    client.post("/orders", json={"sku": "SKIN001", "quantity": 15})
    response = client.get("/audit")

    assert response.status_code == 200
    logs = response.json()
    assert [entry["decision"] for entry in logs] == [
        "approved",
        "requires_confirmation",
        "blocked",
    ]
    assert logs[0]["razorpay_order_id"] == "order_test_approved"
    assert logs[0]["order_id"] is not None
    assert logs[1]["razorpay_order_id"] is None
    assert logs[1]["order_id"] is not None
    assert logs[2]["razorpay_order_id"] is None
    assert logs[2]["order_id"] is None


def test_confirm_pending_order_calls_razorpay_and_updates_same_order(monkeypatch):
    calls = []

    def fake_create_razorpay_order(amount_rupees, receipt):
        calls.append({"amount_rupees": amount_rupees, "receipt": receipt})
        return {"id": "order_test_confirmed"}

    monkeypatch.setattr(main, "create_razorpay_order", fake_create_razorpay_order)
    pending = client.post(
        "/orders", json={"sku": "SKIN001", "quantity": 3}
    ).json()

    response = client.post(f"/orders/{pending['order_id']}/confirm")

    assert response.status_code == 200
    confirmed = response.json()
    assert confirmed["order_id"] == pending["order_id"]
    assert confirmed["status"] == "created"
    assert confirmed["razorpay_order_id"].startswith("order_")
    assert calls == [{
        "amount_rupees": 2097.0,
        "receipt": pending["order_id"],
    }]
    assert audit_logs[-1]["decision"] == "human_confirmed"
    assert audit_logs[-1]["order_id"] == pending["order_id"]
    assert audit_logs[-1]["razorpay_order_id"] == "order_test_confirmed"


def test_confirm_nonexistent_order_returns_404():
    response = client.post("/orders/missing-order/confirm")

    assert response.status_code == 404


def test_confirm_created_order_returns_400(monkeypatch):
    monkeypatch.setattr(
        main,
        "create_razorpay_order",
        lambda amount_rupees, receipt: {"id": "order_test_approved"},
    )
    created = client.post(
        "/orders", json={"sku": "SKIN001", "quantity": 2}
    ).json()

    response = client.post(f"/orders/{created['order_id']}/confirm")

    assert response.status_code == 400


def test_order_request_rejects_confirmation_override_fields(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Razorpay must not be called")

    monkeypatch.setattr(main, "create_razorpay_order", fail_if_called)

    for field in ("confirmed", "human_confirmed", "override"):
        response = client.post(
            "/orders",
            json={"sku": "SKIN001", "quantity": 3, field: True},
        )
        assert response.status_code == 422
