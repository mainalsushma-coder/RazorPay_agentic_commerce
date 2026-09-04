from typing import Any

from mcp.server.mcpserver import MCPServer as FastMCP

from app.repositories.catalog_repository import catalog_repository
from app.services.order_service import (
    OrderServiceError,
    create_order as create_guarded_order,
)


mcp = FastMCP("Agent Storefront Autopilot")


@mcp.tool()
def list_merchants() -> list[dict[str, Any]]:
    """List public metadata for merchants available to the shopping agent."""
    return [merchant.model_dump() for merchant in catalog_repository.list_merchants()]


@mcp.tool()
def catalog_search(
    merchant_id: str,
    query: str,
) -> list[dict[str, Any]] | dict[str, str]:
    """Search one merchant's catalog by product facts and attributes."""
    merchant_catalog = catalog_repository.search_products(merchant_id, query)
    if merchant_catalog is None:
        return {
            "error": "merchant_not_found",
            "message": "Merchant not found",
            "merchant_id": merchant_id,
        }

    return [
        {
            "merchant_id": merchant_id,
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
