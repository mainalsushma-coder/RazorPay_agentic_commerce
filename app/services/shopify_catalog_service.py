from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from html import unescape
from typing import Any

from app.models.commerce_product import CommerceProduct


AGENT_PROFILE = "https://shopify.dev/ucp/agent-profiles/examples/2026-08-25/valid-with-capabilities.json"


class ShopifyCatalogError(RuntimeError):
    """A safe, non-transport-specific external catalog failure."""


class ShopifyCatalogClient:
    def __init__(
        self,
        store_domain: str,
        *,
        timeout: float = 8.0,
        transport: Callable[[str, bytes, float], tuple[int, bytes]] | None = None,
    ) -> None:
        self.store_domain = store_domain
        self.endpoint = f"https://{store_domain}/api/ucp/mcp"
        self.timeout = timeout
        self._transport = transport or self._urlopen

    @staticmethod
    def _urlopen(url: str, body: bytes, timeout: float) -> tuple[int, bytes]:
        request = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()

    def _call(self, name: str, catalog: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0", "method": "tools/call", "id": 1,
            "params": {"name": name, "arguments": {
                "meta": {"ucp-agent": {"profile": AGENT_PROFILE}},
                "catalog": catalog,
            }},
        }
        try:
            status, raw = self._transport(
                self.endpoint, json.dumps(payload).encode("utf-8"), self.timeout
            )
        except (TimeoutError, OSError, urllib.error.URLError) as exc:
            raise ShopifyCatalogError("Shopify catalog is temporarily unavailable") from exc
        if status != 200:
            raise ShopifyCatalogError("Shopify catalog returned an unsuccessful response")
        try:
            response = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
            raise ShopifyCatalogError("Shopify catalog returned malformed data") from exc
        if not isinstance(response, dict):
            raise ShopifyCatalogError("Shopify catalog returned malformed data")
        if response.get("error"):
            raise ShopifyCatalogError("Shopify catalog rejected the request")
        result = response.get("result")
        structured = result.get("structuredContent") if isinstance(result, dict) else None
        if not isinstance(structured, dict):
            raise ShopifyCatalogError("Shopify catalog returned malformed data")
        return structured

    def search_catalog(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        content = self._call("search_catalog", {"query": query, "pagination": {"limit": limit}})
        products = content.get("products", [])
        if not isinstance(products, list):
            raise ShopifyCatalogError("Shopify catalog returned malformed data")
        return [item for item in products if isinstance(item, dict)]

    def get_product(self, product_id: str) -> dict[str, Any] | None:
        content = self._call("get_product", {"id": product_id})
        product = content.get("product")
        return product if isinstance(product, dict) else None


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        raw = value.get("plain") or value.get("html") or ""
        # UCP may supply HTML in a description field. Treat it strictly as text;
        # this is response normalization, not storefront HTML scraping.
        return unescape(str(raw)).replace("<p>", "").replace("</p>", " ").strip()
    return ""


def normalize_shopify_product(product: dict[str, Any], merchant_id: str) -> CommerceProduct:
    variants = product.get("variants") if isinstance(product.get("variants"), list) else []
    variants = [v for v in variants if isinstance(v, dict)]
    variant = next(
        (v for v in variants if isinstance(v.get("availability"), dict) and v["availability"].get("available")),
        variants[0] if variants else {},
    )
    price = variant.get("price") if isinstance(variant.get("price"), dict) else None
    if price is None:
        price_range = product.get("price_range", {})
        price = price_range.get("min") if isinstance(price_range, dict) else None
    if not isinstance(price, dict) or not isinstance(price.get("amount"), int):
        raise ShopifyCatalogError("Shopify product price is unavailable")
    currency = price.get("currency")
    if not isinstance(currency, str) or not currency:
        raise ShopifyCatalogError("Shopify product currency is unavailable")
    product_id = product.get("id")
    if not isinstance(product_id, str) or not product_id:
        raise ShopifyCatalogError("Shopify product identity is unavailable")
    availability = variant.get("availability", {})
    media = product.get("media") if isinstance(product.get("media"), list) else []
    image = next((m for m in media if isinstance(m, dict) and m.get("type") == "image"), {})
    options = variant.get("options") or product.get("options") or []
    return CommerceProduct(
        source="shopify", merchant_id=merchant_id, source_product_id=product_id,
        source_variant_id=variant.get("id"),
        sku=variant.get("sku") or variant.get("id") or product_id,
        name=str(product.get("title") or "Untitled product"),
        description=_text(product.get("description")), price=price["amount"] / 100,
        currency=currency.upper(), available=bool(availability.get("available")),
        image_url=image.get("url") if isinstance(image.get("url"), str) else None,
        attributes={"options": options}, authoritative_source="Shopify Storefront Catalog MCP",
        checkout_capability={"type": "external", "provider": "shopify", "execution_enabled": False},
    )
