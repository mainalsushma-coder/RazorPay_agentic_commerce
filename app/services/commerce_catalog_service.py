from __future__ import annotations

from app.data.merchants import external_merchants
from app.models.commerce_product import CommerceProduct
from app.models.merchant import Merchant
from app.repositories.catalog_repository import catalog_repository
from app.services.shopify_catalog_service import ShopifyCatalogClient, ShopifyCatalogError, normalize_shopify_product


def list_commerce_merchants() -> list[Merchant]:
    return catalog_repository.list_merchants() + [m.model_copy(deep=True) for m in external_merchants]


def get_commerce_merchant(merchant_id: str) -> Merchant | None:
    native = catalog_repository.get_merchant(merchant_id)
    if native:
        return native
    return next((m.model_copy(deep=True) for m in external_merchants if m.merchant_id == merchant_id), None)


def search_commerce_catalog(merchant_id: str, query: str) -> list[CommerceProduct] | None:
    merchant = get_commerce_merchant(merchant_id)
    if merchant is None:
        return None
    if merchant.source == "bound_native":
        products = catalog_repository.search_products(merchant_id, query) or []
        return [CommerceProduct(
            source="bound_native", merchant_id=merchant_id, source_product_id=p.sku,
            sku=p.sku, name=p.name, category=p.category, description=p.description,
            price=p.price, currency=p.currency, available=p.stock > 0, stock=p.stock,
            attributes=p.attributes, authoritative_source="BOUND CatalogRepository",
            checkout_capability={"type": "native", "provider": "razorpay", "execution_enabled": True},
        ) for p in products]

    client = ShopifyCatalogClient(str(merchant.source_config["store_domain"]))
    candidates = client.search_catalog(query)
    verified: list[CommerceProduct] = []
    for candidate in candidates:
        product_id = candidate.get("id")
        if not isinstance(product_id, str):
            continue
        detail = client.get_product(product_id)
        if detail is None:
            continue
        try:
            verified.append(normalize_shopify_product(detail, merchant_id))
        except ShopifyCatalogError:
            continue
    return verified


def universal_search(query: str) -> list[CommerceProduct]:
    """Search all active sources without allowing one external outage to erase others."""
    candidates: list[CommerceProduct] = []
    for merchant in list_commerce_merchants():
        if not merchant.agent_ready:
            continue
        try:
            candidates.extend(search_commerce_catalog(merchant.merchant_id, query) or [])
        except ShopifyCatalogError:
            continue
    return candidates
