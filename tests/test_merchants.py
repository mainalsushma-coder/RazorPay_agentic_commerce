import os

os.environ.setdefault("RAZORPAY_KEY_ID", "test_key")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "test_secret")

from fastapi.testclient import TestClient

import app.main as main
from app.services.audit_service import audit_logs
from app.services.order_service import OrderServiceError, create_order, orders


client = TestClient(main.app)


def setup_function():
    audit_logs.clear()
    orders.clear()


def test_merchants_are_listed_without_catalogs():
    response = client.get("/merchants")

    assert response.status_code == 200
    merchants = response.json()
    assert {merchant["name"] for merchant in merchants} == {"GlowCare", "TechHub", "BOUND Commerce Test"}
    assert all("catalog" not in merchant for merchant in merchants)


def test_each_merchant_has_its_own_catalog():
    glowcare = client.get("/merchants/glowcare/products")
    techhub = client.get("/merchants/techhub/products")

    assert glowcare.status_code == techhub.status_code == 200
    assert {product["sku"] for product in glowcare.json()} == {
        "SKIN001", "SKIN002", "SKIN003"
    }
    assert {product["sku"] for product in techhub.json()} == {
        "TECH001", "TECH002", "TECH003"
    }
    assert all(product["category"] == "Skincare" for product in glowcare.json())
    assert all(product["category"] == "Electronics" for product in techhub.json())


def test_search_is_scoped_to_merchant():
    tech_keyboard = client.get(
        "/merchants/techhub/products/search", params={"q": "keyboard"}
    )
    glow_vitamin = client.get(
        "/merchants/glowcare/products/search", params={"q": "vitamin"}
    )
    glow_keyboard = client.get(
        "/merchants/glowcare/products/search", params={"q": "keyboard"}
    )

    assert [product["sku"] for product in tech_keyboard.json()] == ["TECH001"]
    assert [product["sku"] for product in glow_vitamin.json()] == ["SKIN001"]
    assert glow_keyboard.json() == []


def test_unknown_merchant_returns_404():
    assert client.get("/merchants/missing/products").status_code == 404
    assert client.get(
        "/merchants/missing/products/search", params={"q": "anything"}
    ).status_code == 404


def test_techhub_order_uses_trusted_catalog_price_and_is_approved():
    calls = []

    result = create_order(
        merchant_id="techhub",
        sku="TECH002",
        quantity=1,
        payment_order_creator=lambda amount_rupees, receipt: (
            calls.append({"amount_rupees": amount_rupees, "receipt": receipt})
            or {"id": "order_techhub"}
        ),
    )

    assert result["merchant_id"] == "techhub"
    assert result["unit_price"] == 1299.0
    assert result["total"] == 1299.0
    assert result["policy_decision"] == "approved"
    assert calls == [{"amount_rupees": 1299.0, "receipt": result["order_id"]}]


def test_cross_merchant_sku_is_rejected_without_payment():
    calls = []

    try:
        create_order(
            merchant_id="glowcare",
            sku="TECH002",
            quantity=1,
            payment_order_creator=lambda **kwargs: calls.append(kwargs),
        )
    except OrderServiceError as exc:
        assert exc.status_code == 404
        assert exc.detail == "Product not found"
    else:
        raise AssertionError("Cross-merchant SKU should not resolve")

    assert calls == []
    assert audit_logs[-1]["decision"] == "blocked"


def test_api_accepts_merchant_scope_and_legacy_orders_default_to_glowcare(monkeypatch):
    monkeypatch.setattr(
        main,
        "create_razorpay_order",
        lambda amount_rupees, receipt: {"id": "order_api"},
    )

    tech_order = client.post(
        "/orders",
        json={"merchant_id": "techhub", "sku": "TECH002", "quantity": 1},
    )
    legacy_order = client.post(
        "/orders", json={"sku": "SKIN001", "quantity": 1}
    )

    assert tech_order.status_code == legacy_order.status_code == 200
    assert tech_order.json()["merchant_id"] == "techhub"
    assert legacy_order.json()["merchant_id"] == "glowcare"
