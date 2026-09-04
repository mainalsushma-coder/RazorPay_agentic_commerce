import os

os.environ.setdefault("RAZORPAY_KEY_ID", "test_key")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "test_secret")

from fastapi.testclient import TestClient

import app.main as main
import app.services.order_service as order_service
from app.mcp_server import catalog_search, create_order, list_merchants, mcp
from app.services.audit_service import audit_logs


client = TestClient(main.app)


def setup_function():
    audit_logs.clear()
    order_service.orders.clear()


def test_list_merchants_returns_only_public_metadata():
    merchants = list_merchants()

    assert {merchant["name"] for merchant in merchants} == {"GlowCare", "TechHub"}
    assert all(set(merchant) == {
        "merchant_id", "name", "category", "description", "agent_ready"
    } for merchant in merchants)


def test_catalog_search_is_merchant_scoped():
    assert [p["sku"] for p in catalog_search("techhub", "keyboard")] == ["TECH001"]
    assert [p["sku"] for p in catalog_search("glowcare", "vitamin")] == ["SKIN001"]
    assert catalog_search("glowcare", "keyboard") == []
    assert catalog_search("techhub", "vitamin") == []


def test_unknown_merchant_search_returns_safe_error():
    assert catalog_search("missing", "keyboard") == {
        "error": "merchant_not_found",
        "message": "Merchant not found",
        "merchant_id": "missing",
    }


def test_mcp_create_order_enforces_policy_and_payment_boundary(monkeypatch):
    calls = []

    def fake_create_razorpay_order(amount_rupees, receipt):
        calls.append({"amount_rupees": amount_rupees, "receipt": receipt})
        return {"id": f"order_test_{len(calls)}"}

    monkeypatch.setattr(
        order_service,
        "create_razorpay_order",
        fake_create_razorpay_order,
    )

    approved = create_order("glowcare", "SKIN001", 2)
    pending = create_order("glowcare", "SKIN001", 3)
    blocked = create_order("glowcare", "SKIN001", 15)
    invalid = create_order("glowcare", "MISSING", 1)

    assert approved["policy_decision"] == "approved"
    assert approved["razorpay_order_id"] == "order_test_1"
    assert pending["policy_decision"] == "requires_confirmation"
    assert pending["razorpay_order_id"] is None
    assert blocked == {
        "decision": "blocked",
        "reason": "Order exceeds maximum spend limit",
    }
    assert invalid == {"decision": "blocked", "reason": "Product not found"}
    assert calls == [{
        "amount_rupees": 1398.0,
        "receipt": approved["order_id"],
    }]
    assert [entry["decision"] for entry in audit_logs] == [
        "approved",
        "requires_confirmation",
        "blocked",
        "blocked",
    ]


def test_techhub_order_and_cross_merchant_isolation(monkeypatch):
    calls = []
    monkeypatch.setattr(
        order_service,
        "create_razorpay_order",
        lambda amount_rupees, receipt: (
            calls.append((amount_rupees, receipt)) or {"id": "order_techhub"}
        ),
    )

    approved = create_order("techhub", "TECH002", 1)
    wrong_glowcare = create_order("glowcare", "TECH002", 1)
    wrong_techhub = create_order("techhub", "SKIN001", 1)

    assert approved["unit_price"] == approved["total"] == 1299.0
    assert approved["policy_decision"] == "approved"
    assert wrong_glowcare == wrong_techhub == {
        "decision": "blocked", "reason": "Product not found"
    }
    assert calls == [(1299.0, approved["order_id"])]


def test_mcp_exposes_only_three_expected_tools():
    import asyncio

    tools = asyncio.run(mcp.list_tools())
    assert {tool.name for tool in tools} == {
        "list_merchants", "catalog_search", "create_order"
    }
    schemas = {tool.name: set(tool.input_schema.get("properties", {})) for tool in tools}
    assert schemas == {
        "list_merchants": set(),
        "catalog_search": {"merchant_id", "query"},
        "create_order": {"merchant_id", "sku", "quantity"},
    }


def test_fastapi_create_order_uses_shared_service(monkeypatch):
    monkeypatch.setattr(
        main,
        "create_razorpay_order",
        lambda amount_rupees, receipt: {"id": "order_api_approved"},
    )

    response = client.post("/orders", json={"sku": "SKIN001", "quantity": 2})

    assert response.status_code == 200
    assert response.json()["policy_decision"] == "approved"
    assert response.json()["razorpay_order_id"] == "order_api_approved"


def test_human_confirmation_remains_api_only(monkeypatch):
    calls = []

    def fake_create_razorpay_order(amount_rupees, receipt):
        calls.append({"amount_rupees": amount_rupees, "receipt": receipt})
        return {"id": "order_human_confirmed"}

    monkeypatch.setattr(main, "create_razorpay_order", fake_create_razorpay_order)
    pending = client.post(
        "/orders", json={"sku": "SKIN001", "quantity": 3}
    ).json()
    assert calls == []

    response = client.post(f"/orders/{pending['order_id']}/confirm")

    assert response.status_code == 200
    assert response.json()["status"] == "created"
    assert response.json()["razorpay_order_id"] == "order_human_confirmed"
    assert calls == [{
        "amount_rupees": 2097.0,
        "receipt": pending["order_id"],
    }]
    assert audit_logs[-1]["decision"] == "human_confirmed"
