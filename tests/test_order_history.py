import pytest
from fastapi.testclient import TestClient
import app.main as main
from app.services.order_service import orders
from app.services.audit_service import audit_logs


@pytest.fixture
def client(monkeypatch):
    old_orders, old_audit = dict(orders), list(audit_logs)
    orders.clear(); audit_logs.clear()
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_placeholder")
    monkeypatch.setattr(main, "create_razorpay_order", lambda **kw: {"id": "order_fake_" + kw["receipt"]})
    yield TestClient(main.app)
    orders.clear(); orders.update(old_orders)
    audit_logs[:] = old_audit


def purchase(client, merchant="glowcare", sku="SKIN001", quantity=1):
    return client.post("/buyer/orders", json={"merchant_id": merchant, "sku": sku, "quantity": quantity}).json()


def test_route_navigation_and_repeat_orders(client):
    assert client.get("/orders").status_code == 200
    for route in ("/dashboard", "/profile", "/orders"):
        assert 'href="/orders"' in client.get(route).text
    first, second = purchase(client), purchase(client)
    data = client.get("/buyer/order-history").json()["orders"]
    assert [o["order_id"] for o in data] == [second["order_id"], first["order_id"]]
    for row in data:
        assert row["merchant_name"] == "GlowCare"
        assert row["unit_price"] == row["total"] == 699
        assert row["currency"] == "INR"
        assert row["status_label"] == "Order created"
        assert row["razorpay_order_id"].startswith("order_fake_")
        assert row["receipt"] == row["order_id"]
        assert row["created_at"] and row["test_mode"]
        assert row["authority"] == "Autonomous"


def test_confirmation_and_safe_audit(client):
    order = purchase(client, "techhub", "TECH001")
    row = client.get("/buyer/order-history").json()["orders"][0]
    assert row["total"] == 3499 and row["merchant_name"] == "TechHub"
    assert row["status_label"] == "Confirmation required"
    assert row["razorpay_order_id"] is None and row["receipt"] is None
    assert row["audit_events"][0]["label"] == "Policy requires human confirmation"
    client.post(f"/orders/{order['order_id']}/confirm")
    audit_logs[-1]["reason"] = "secret credential stack trace"
    orders[order["order_id"]]["credentials"] = "private"
    response = client.get("/buyer/order-history")
    assert response.json()["orders"][0]["authority"] == "Human-confirmed"
    assert "secret" not in response.text and "private" not in response.text


def test_blocked_attempt_is_not_fake_order(client):
    assert purchase(client, quantity=15)["decision"] == "blocked"
    data = client.get("/buyer/order-history").json()
    assert data["orders"] == []
    assert data["blocked_attempts"][0]["status_label"] == "Blocked"


def test_shopify_discovery_does_not_create_order(client):
    result = purchase(client, "bound-commerce-test-shopify", "SNOW-001")
    assert result["decision"] == "external_checkout_required"
    assert client.get("/buyer/order-history").json()["orders"] == []


def test_unknown_payment_mode_not_claimed_as_test(client, monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "unknown")
    purchase(client)
    assert client.get("/buyer/order-history").json()["orders"][0]["test_mode"] is False
