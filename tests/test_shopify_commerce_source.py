import json

import pytest

import app.services.commerce_catalog_service as commerce
import app.services.order_service as order_service
from app.mcp_server import catalog_search
from app.services.shopify_catalog_service import (
    ShopifyCatalogClient,
    ShopifyCatalogError,
    normalize_shopify_product,
)


PRODUCT = {
    "id": "gid://shopify/Product/1001",
    "title": "Mountain Snowboard",
    "description": {"plain": "A real development-store snowboard."},
    "media": [{"type": "image", "url": "https://cdn.shopify.com/s/files/snowboard.png"}],
    "variants": [{
        "id": "gid://shopify/ProductVariant/2001",
        "sku": "SNOW-001",
        "price": {"amount": 62995, "currency": "USD"},
        "availability": {"available": True},
        "options": [{"name": "Color", "label": "Blue"}],
    }],
}


def rpc(structured):
    return 200, json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": structured}}).encode()


def test_shopify_normalization_preserves_authoritative_product_facts():
    product = normalize_shopify_product(PRODUCT, "bound-commerce-test-shopify")
    assert product.price == 629.95
    assert product.currency == "USD"
    assert product.source_product_id == "gid://shopify/Product/1001"
    assert product.source_variant_id == "gid://shopify/ProductVariant/2001"
    assert product.sku == "SNOW-001"
    assert product.image_url == "https://cdn.shopify.com/s/files/snowboard.png"
    assert product.available is True
    assert product.source == "shopify"
    assert product.authoritative_source == "Shopify Storefront Catalog MCP"
    assert product.checkout_capability["execution_enabled"] is False


@pytest.mark.parametrize("transport", [
    lambda *_: (503, b"no"),
    lambda *_: (200, b"not-json"),
    lambda *_: (200, b'{"jsonrpc":"2.0","error":{"code":-1}}'),
])
def test_shopify_network_and_protocol_failures_are_safe(transport):
    client = ShopifyCatalogClient("example.myshopify.com", transport=transport)
    with pytest.raises(ShopifyCatalogError):
        client.search_catalog("snowboard")


def test_shopify_search_is_reverified_with_product_detail(monkeypatch):
    calls = []

    class Client:
        def __init__(self, domain): assert domain == "bound-commerce-test.myshopify.com"
        def search_catalog(self, query):
            calls.append(("search_catalog", query))
            return [{"id": PRODUCT["id"], "title": "Untrusted search title"}]
        def get_product(self, product_id):
            calls.append(("get_product", product_id))
            return PRODUCT

    monkeypatch.setattr(commerce, "ShopifyCatalogClient", Client)
    result = commerce.search_commerce_catalog("bound-commerce-test-shopify", "snowboard")
    assert result and result[0].name == "Mountain Snowboard"
    assert result[0].verified is True
    assert calls == [("search_catalog", "snowboard"), ("get_product", PRODUCT["id"])]


def test_shopify_cannot_reach_razorpay_or_inr_mandate(monkeypatch):
    monkeypatch.setattr(order_service, "create_razorpay_order", lambda **_: pytest.fail("Razorpay called"))
    monkeypatch.setattr(order_service, "evaluate_order_policy", lambda **_: pytest.fail("INR policy called"))
    result = order_service.create_order(
        merchant_id="bound-commerce-test-shopify", sku="SNOW-001", quantity=1
    )
    assert result["status"] == "external_checkout_required"
    assert result["checkout_capability"] == {
        "type": "external", "provider": "shopify", "execution_enabled": False,
    }
    assert result["mandate"]["applied"] is False


def test_mcp_external_failure_is_structured(monkeypatch):
    monkeypatch.setattr("app.mcp_server.search_commerce_catalog", lambda *_: (_ for _ in ()).throw(ShopifyCatalogError()))
    result = catalog_search("bound-commerce-test-shopify", "snowboard")
    assert result["error"] == "external_catalog_unavailable"
    assert "myshopify.com" not in str(result)


def test_universal_search_returns_native_and_external(monkeypatch):
    class Client:
        def __init__(self, domain): pass
        def search_catalog(self, query): return [{"id": PRODUCT["id"]}]
        def get_product(self, product_id): return PRODUCT

    monkeypatch.setattr(commerce, "ShopifyCatalogClient", Client)
    results = commerce.universal_search("wireless")
    assert {p.source for p in results} == {"bound_native", "shopify"}
    assert any(p.merchant_id == "bound-commerce-test-shopify" for p in results)


@pytest.mark.parametrize("queries", [
    ["Vitamin C"], ["snowboard", "Vitamin C"],
    ["Vitamin C", "snowboard", "Vitamin C", "keyboard"],
])
def test_independent_global_sources_and_native_execution(monkeypatch, queries):
    searches, payments = [], []
    class Client:
        def __init__(self, domain): pass
        def search_catalog(self, query):
            searches.append(query)
            return [{"id": PRODUCT["id"]}] if query == "snowboard" else []
        def get_product(self, product_id): return PRODUCT
    monkeypatch.setattr(commerce, "ShopifyCatalogClient", Client)
    def payment(**kwargs):
        payments.append(kwargs)
        return {"id": "order_mock_global", "amount": 69900}
    for query in queries:
        products = commerce.universal_search(query)
        expected = "SNOW-001" if query == "snowboard" else "SKIN001" if query == "Vitamin C" else "TECH001"
        assert products and {p.sku for p in products} == {expected}
        product = products[0]
        result = order_service.create_order(merchant_id=product.merchant_id, sku=product.sku, quantity=1, payment_order_creator=payment)
        assert result["status"] == ("external_checkout_required" if query == "snowboard" else "created" if query == "Vitamin C" else "requires_confirmation")
    assert searches == queries
    assert len(payments) == queries.count("Vitamin C")

