import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.data.merchants import get_merchant_catalog
from app.services.audit_service import audit_logs
from app.services.order_service import orders


client = TestClient(main.app)


@pytest.fixture(autouse=True)
def isolated_state():
    audit_logs.clear()
    orders.clear()
    yield
    audit_logs.clear()
    orders.clear()


def never_pay(*args, **kwargs):
    raise AssertionError("Razorpay must not be called for a rejected request")


@pytest.mark.parametrize(
    "extra",
    [
        {"price": 1},
        {"unit_price": 1},
        {"confirmed": True},
        {"human_confirmed": True},
        {"override": True},
        {"razorpay_order_id": "order_attacker"},
    ],
)
def test_order_api_rejects_caller_controlled_trust_fields(monkeypatch, extra):
    monkeypatch.setattr(main, "create_razorpay_order", never_pay)
    response = client.post(
        "/orders",
        json={"merchant_id": "glowcare", "sku": "SKIN001", "quantity": 2, **extra},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("quantity", [0, -1, -100])
def test_invalid_quantities_are_rejected_without_payment(monkeypatch, quantity):
    monkeypatch.setattr(main, "create_razorpay_order", never_pay)
    response = client.post(
        "/orders",
        json={"merchant_id": "glowcare", "sku": "SKIN001", "quantity": quantity},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Quantity must be greater than zero"
    assert audit_logs[-1]["decision"] == "blocked"


@pytest.mark.parametrize(
    "payload, expected_detail",
    [
        ({"merchant_id": "missing", "sku": "SKIN001", "quantity": 1}, "Merchant not found"),
        ({"merchant_id": "glowcare", "sku": "MISSING", "quantity": 1}, "Product not found"),
        ({"merchant_id": "glowcare", "sku": "TECH002", "quantity": 1}, "Product not found"),
    ],
)
def test_unknown_scope_and_skus_are_rejected_without_payment(monkeypatch, payload, expected_detail):
    monkeypatch.setattr(main, "create_razorpay_order", never_pay)
    response = client.post("/orders", json=payload)
    assert response.status_code == 404
    assert response.json()["detail"] == expected_detail
    assert audit_logs[-1]["decision"] == "blocked"


def test_confirmation_revalidates_stock_without_payment(monkeypatch):
    monkeypatch.setattr(main, "create_razorpay_order", never_pay)
    pending = client.post("/orders", json={"sku": "SKIN001", "quantity": 3}).json()
    active = get_merchant_catalog("glowcare")
    product = active[0].model_copy(update={"stock": 2})
    main.catalog_repository.replace_catalog("glowcare", [product, *active[1:]])

    response = client.post(f"/orders/{pending['order_id']}/confirm")

    assert response.status_code == 400
    assert response.json()["detail"] == "Insufficient stock"
    assert orders[pending["order_id"]]["status"] == "requires_confirmation"
    main.catalog_repository.replace_catalog("glowcare", active)


def test_confirmation_rejects_changed_price_without_payment(monkeypatch):
    monkeypatch.setattr(main, "create_razorpay_order", never_pay)
    pending = client.post("/orders", json={"sku": "SKIN001", "quantity": 3}).json()
    active = get_merchant_catalog("glowcare")
    product = active[0].model_copy(update={"price": 799.0})
    main.catalog_repository.replace_catalog("glowcare", [product, *active[1:]])

    response = client.post(f"/orders/{pending['order_id']}/confirm")

    assert response.status_code == 409
    assert response.json()["detail"] == "Product price changed; create a new order"
    assert orders[pending["order_id"]]["status"] == "requires_confirmation"
    main.catalog_repository.replace_catalog("glowcare", active)


def test_confirmation_rejects_invalid_catalog_price_without_payment(monkeypatch):
    monkeypatch.setattr(main, "create_razorpay_order", never_pay)
    pending = client.post("/orders", json={"sku": "SKIN001", "quantity": 3}).json()
    product = main.catalog_repository._catalogs["glowcare"][0]
    monkeypatch.setattr(product, "price", "not-a-price")

    response = client.post(f"/orders/{pending['order_id']}/confirm")

    assert response.status_code == 400
    assert response.json()["detail"] == "Product price is invalid"


def test_max_spend_is_blocked_without_creating_an_order_or_payment(monkeypatch):
    monkeypatch.setattr(main, "create_razorpay_order", never_pay)
    response = client.post("/orders", json={"sku": "SKIN001", "quantity": 15})
    assert response.status_code == 403
    assert response.json()["reason"] == "Order exceeds maximum spend limit"
    assert orders == {}
