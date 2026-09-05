import pytest
from fastapi.testclient import TestClient

import app.main as main
import app.services.order_service as service
from app.repositories.catalog_repository import catalog_repository


@pytest.mark.parametrize("second_price,second_stock,expected_status", [
    (799, 15, "created"),
    (2500, 15, "requires_confirmation"),
    (11000, 15, "blocked"),
    (699, 0, "out_of_stock"),
])
def test_repeat_purchase_rechecks_authoritative_catalog_and_policy(
    monkeypatch, second_price, second_stock, expected_status,
):
    catalog = catalog_repository.get_catalog("glowcare")
    calls, policy_prices = [], []
    original_policy = service.evaluate_order_policy

    class Executor:
        def create_order(self, **kwargs):
            calls.append(kwargs)
            return {"id": f"order_fake_{len(calls)}"}

    def policy(**kwargs):
        policy_prices.append(kwargs["unit_price"])
        return original_policy(**kwargs)

    monkeypatch.setattr(service, "build_payment_executor", lambda *_: Executor())
    monkeypatch.setattr(service, "evaluate_order_policy", policy)
    monkeypatch.setattr(service, "orders", {})
    client = TestClient(main.app)
    intent = {"merchant_id": "glowcare", "sku": "SKIN001", "quantity": 1}
    try:
        first = client.post("/buyer/orders", json=intent).json()
        assert first["status"] == "created"
        updated = [p.model_copy(deep=True) for p in catalog]
        product = next(p for p in updated if p.sku == "SKIN001")
        product.price, product.stock = second_price, second_stock
        catalog_repository.replace_catalog("glowcare", updated)
        response = client.post("/buyer/orders", json=intent)
        second = response.json()
        if expected_status == "out_of_stock":
            assert response.status_code == 400
            assert second["detail"] == "Insufficient stock"
            assert policy_prices == [699]
        else:
            assert policy_prices == [699, second_price]
            assert second.get("status", second.get("decision")) == expected_status
        if expected_status in {"created", "requires_confirmation"}:
            assert first["order_id"] != second["order_id"]
            assert second["unit_price"] == second_price
        if expected_status == "created":
            assert first["razorpay_order_id"] != second["razorpay_order_id"]
            assert [c["receipt"] for c in calls] == [first["order_id"], second["order_id"]]
            assert [c["amount_rupees"] for c in calls] == [699, 799]
        else:
            assert len(calls) == 1
    finally:
        catalog_repository.replace_catalog("glowcare", catalog)
