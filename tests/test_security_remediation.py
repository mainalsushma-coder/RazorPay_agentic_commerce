import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

import app.main as main
from app.mcp_server import catalog_search, mcp
from app.repositories.catalog_repository import catalog_repository
from app.services import razorpay_service


client = TestClient(main.app)


def test_glowcare_demo_is_real_staged_lifecycle_and_activation(monkeypatch):
    original = catalog_repository.get_catalog("glowcare")
    try:
        assert client.get("/merchant/readiness").json()["readiness_score"] == 71.4
        repaired = client.get("/merchant/readiness/repair-preview").json()
        assert repaired["after"]["readiness_score"] == 90.5
        resolved = client.post("/merchant/readiness/resolve-preview", json={"resolutions": [
            {"sku": "SKIN002", "field": "description", "value": "Resolved cleanser"},
            {"sku": "SKIN003", "field": "price", "value": 1299},
        ]}).json()
        assert resolved["final"]["readiness_score"] == 100
        assert catalog_repository.find_product("glowcare", "SKIN002").price == 399

        activated = client.post("/merchant/readiness/activate")
        assert activated.status_code == 200
        assert catalog_repository.find_product("glowcare", "SKIN002").price == 899
        assert catalog_search("glowcare", "Resolved cleanser")[0]["sku"] == "SKIN002"
        monkeypatch.setattr(main, "create_razorpay_order", lambda **kw: {"id": "order_demo"})
        order = client.post("/buyer/orders", json={
            "merchant_id": "glowcare", "sku": "SKIN003", "quantity": 1,
        }).json()
        assert order["unit_price"] == 1299
    finally:
        catalog_repository.replace_catalog("glowcare", original)


def test_add_and_edit_are_staged_and_invisible_until_activation():
    original = catalog_repository.get_catalog("techhub")
    try:
        added = client.post("/merchants/techhub/products", json={
            "sku": "STAGED", "name": "Staged Product", "category": "Electronics",
            "description": "Not active yet", "price": 500, "currency": "INR",
            "stock": 2, "attributes": {},
        })
        assert added.status_code == 202
        assert catalog_repository.find_product("techhub", "STAGED") is None
        assert catalog_search("techhub", "Staged Product") == []
        assert client.post("/buyer/orders", json={
            "merchant_id": "techhub", "sku": "STAGED", "quantity": 1,
        }).status_code == 404

        product = original[1].model_copy(update={"price": 1}).model_dump()
        edited = client.put("/merchants/techhub/products/TECH002", json=product)
        assert edited.status_code == 200
        assert catalog_repository.find_product("techhub", "TECH002").price == 1299
        activated = client.post(
            f'/merchants/techhub/catalog/imports/{edited.json()["import_id"]}/activate'
        )
        assert activated.status_code == 200
        assert catalog_repository.find_product("techhub", "TECH002").price == 1
    finally:
        catalog_repository.replace_catalog("techhub", original)


def test_repository_returns_deep_copies():
    product = catalog_repository.find_product("glowcare", "SKIN001")
    product.price = 1
    product.attributes["payload"] = "changed"
    authoritative = catalog_repository.find_product("glowcare", "SKIN001")
    assert authoritative.price == 699
    assert "payload" not in authoritative.attributes


def test_merchant_portal_escapes_all_html_attribute_delimiters():
    script = client.get("/static/merchant-portal.js").text
    payload = 'X" onfocus="alert(1)" autofocus="<script>alert(2)</script>&\''
    escaped = (payload.replace("&", "&amp;").replace("<", "&lt;")
               .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))
    assert escaped == "X&quot; onfocus=&quot;alert(1)&quot; autofocus=&quot;&lt;script&gt;alert(2)&lt;/script&gt;&amp;&#39;"
    assert "/[&<>\"']/g" in script
    assert '"&quot;"' in script
    for field in ("p.sku", "p.name", "p.category", "p.price", "p.stock", "i.message"):
        assert f"esc({field})" in script


def test_confirmation_is_atomic_and_replay_safe(monkeypatch):
    main.orders.clear()
    calls = []

    def payment(**kwargs):
        calls.append(kwargs)
        return {"id": "order_once"}

    monkeypatch.setattr(main, "create_razorpay_order", payment)
    pending = client.post("/orders", json={
        "merchant_id": "glowcare", "sku": "SKIN001", "quantity": 3,
    }).json()
    path = f'/orders/{pending["order_id"]}/confirm'
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(path), range(2)))
    assert sorted(response.status_code for response in responses) == [200, 400]
    assert len(calls) == 1
    assert client.post(path).status_code == 400
    assert len(calls) == 1


def test_deterministic_buy_rejects_browser_decisions_and_uses_shared_service(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "create_guarded_order", lambda **kwargs: calls.append(kwargs) or {
        "status": "created", "sku": kwargs["sku"], "merchant_id": kwargs["merchant_id"]
    })
    response = client.post("/buyer/orders", json={
        "merchant_id": "techhub", "sku": "TECH002", "quantity": 1,
    })
    assert response.status_code == 200
    assert calls[0]["sku"] == "TECH002"
    assert calls[0]["merchant_id"] == "techhub"
    for field, value in (("price", 1), ("total", 1), ("policy", "approved"),
                         ("confirmation", True), ("razorpay_order_id", "fake")):
        assert client.post("/buyer/orders", json={
            "merchant_id": "techhub", "sku": "TECH002", "quantity": 1, field: value,
        }).status_code == 422
    script = client.get("/static/app.js").text
    assert 'json("/buyer/orders"' in script
    assert "sku:product.sku" in script
    assert "send(`Buy ${p.name}`" not in script


def test_mcp_surface_remains_exact():
    assert {tool.name for tool in asyncio.run(mcp.list_tools())} == {
        "list_merchants", "catalog_search", "create_order",
    }


def test_payment_boundary_rejects_non_positive_amount(monkeypatch):
    monkeypatch.setattr(
        razorpay_service.client.order, "create",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not pay")),
    )
    for amount in (0, -1):
        try:
            razorpay_service.create_razorpay_order(amount, "invalid")
        except ValueError as exc:
            assert str(exc) == "Payment amount must be greater than zero"
        else:
            raise AssertionError("Non-positive payment amount was accepted")
