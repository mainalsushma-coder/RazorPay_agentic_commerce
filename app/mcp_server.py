from typing import Any

from mcp.server.mcpserver import MCPServer as FastMCP

from app.services.commerce_catalog_service import list_commerce_merchants, search_commerce_catalog
from app.services.shopify_catalog_service import ShopifyCatalogError
from app.services.order_service import (
    OrderServiceError,
    create_order as create_guarded_order,
)


mcp = FastMCP("Agent Storefront Autopilot")


@mcp.tool()
def list_merchants() -> list[dict[str, Any]]:
    """List public metadata for merchants available to the shopping agent."""
    return [merchant.model_dump() for merchant in list_commerce_merchants()]


@mcp.tool()
def catalog_search(
    merchant_id: str,
    query: str,
) -> list[dict[str, Any]] | dict[str, str]:
    """Search one merchant's catalog by product facts and attributes."""
    try:
        merchant_catalog = search_commerce_catalog(merchant_id, query)
    except ShopifyCatalogError:
        return {
            "error": "external_catalog_unavailable",
            "message": "The external catalog is temporarily unavailable",
            "merchant_id": merchant_id,
        }
    if merchant_catalog is None:
        return {
            "error": "merchant_not_found",
            "message": "Merchant not found",
            "merchant_id": merchant_id,
        }

    return [
        {
            **product.model_dump(),
        }
        for product in merchant_catalog
    ]


@mcp.tool()
def create_order(merchant_id: str, sku: str, quantity: int) -> dict[str, Any]:
    """Request an order through the merchant's guarded checkout policy."""
    try:
        return create_guarded_order(
            merchant_id=merchant_id,
            sku=sku,
            quantity=quantity,
        )
    except OrderServiceError as exc:
        return {
            "decision": "blocked",
            "reason": exc.detail,
        }


if __name__ == "__main__":
    mcp.run(transport="stdio")
