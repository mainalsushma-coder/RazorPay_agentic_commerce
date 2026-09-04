from app.services import razorpay_service


def test_razorpay_adapter_converts_rupees_to_paise_and_passes_receipt(monkeypatch):
    calls = []
    monkeypatch.setattr(
        razorpay_service.client.order,
        "create",
        lambda *, data: calls.append(data) or {"id": "order_boundary"},
    )

    result = razorpay_service.create_razorpay_order(1398.0, "internal-order-id")

    assert result == {"id": "order_boundary"}
    assert calls == [{"amount": 139800, "currency": "INR", "receipt": "internal-order-id"}]
