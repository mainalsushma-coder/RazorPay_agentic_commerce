from typing import Any

from mcp.server.mcpserver import MCPServer as FastMCP

from app.data.merchants import get_merchant_catalog, merchant_registry
from app.services.order_service import (
    OrderServiceError,
    create_order as create_guarded_order,
)


mcp = FastMCP("Agent Storefront Autopilot")


@mcp.tool()
def list_merchants() -> list[dict[str, Any]]:
    """List public metadata for merchants available to the shopping agent."""
    return [entry["merchant"].model_dump() for entry in merchant_registry.values()]


@mcp.tool()
def catalog_search(
    merchant_id: str,
    query: str,
) -> list[dict[str, Any]] | dict[str, str]:
    """Search one merchant's catalog by product facts and attributes."""
    merchant_catalog = get_merchant_catalog(merchant_id)
    if merchant_catalog is None:
        return {
            "error": "merchant_not_found",
            "message": "Merchant not found",
            "merchant_id": merchant_id,
        }

    normalized_query = query.casefold()

    return [
        {
            "merchant_id": merchant_id,
            **product.model_dump(),
        }
        for product in merchant_catalog
        if any(
            normalized_query in str(value).casefold()
            for value in (
                product.sku,
                product.name,
                product.category,
                product.description,
                *product.attributes.keys(),
                *product.attributes.values(),
            )
        )
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
