from fastapi.testclient import TestClient

import app.main as main
from app.services.audit_service import audit_logs
from app.services.order_service import orders


client = TestClient(main.app)


def setup_function():
    audit_logs.clear()
    orders.clear()


def test_requested_api_checkout_flows(monkeypatch):
    calls = []

    def payment(amount_rupees, receipt):
        calls.append((amount_rupees, receipt))
        return {"id": f"order_mock_{len(calls)}"}

    monkeypatch.setattr(main, "create_razorpay_order", payment)

    search = client.get("/merchants/glowcare/products/search", params={"q": "SKIN001"})
    approved = client.post("/orders", json={"merchant_id": "glowcare", "sku": "SKIN001", "quantity": 2})
    assert search.status_code == approved.status_code == 200
    assert [item["sku"] for item in search.json()] == ["SKIN001"]
    assert approved.json()["total"] == 1398.0
    assert approved.json()["policy_decision"] == "approved"
    assert len(calls) == 1

    pending = client.post("/orders", json={"merchant_id": "glowcare", "sku": "SKIN001", "quantity": 3})
    assert pending.json()["total"] == 2097.0
    assert pending.json()["policy_decision"] == "requires_confirmation"
    assert pending.json()["razorpay_order_id"] is None
    assert len(calls) == 1
    confirmed = client.post(f"/orders/{pending.json()['order_id']}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "created"
    assert len(calls) == 2

    blocked = client.post("/orders", json={"merchant_id": "glowcare", "sku": "SKIN001", "quantity": 15})
    assert blocked.status_code == 403
    assert blocked.json()["decision"] == "blocked"
    assert len(calls) == 2

    techhub = client.post("/orders", json={"merchant_id": "techhub", "sku": "TECH002", "quantity": 1})
    assert techhub.status_code == 200
    assert techhub.json()["unit_price"] == techhub.json()["total"] == 1299.0
    assert techhub.json()["policy_decision"] == "approved"
    assert len(calls) == 3

    cross_merchant = client.post("/orders", json={"merchant_id": "glowcare", "sku": "TECH002", "quantity": 1})
    assert cross_merchant.status_code == 404
    assert len(calls) == 3
