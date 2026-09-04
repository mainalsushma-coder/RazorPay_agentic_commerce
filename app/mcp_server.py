from typing import Any

from mcp.server.mcpserver import MCPServer as FastMCP

from app.data.catalog import catalog
from app.services.order_service import (
    OrderServiceError,
    create_order as create_guarded_order,
)


mcp = FastMCP("Agent Storefront Autopilot")


@mcp.tool()
def catalog_search(query: str) -> list[dict[str, Any]]:
    """Search the product catalog by name, category, description, or SKU."""
    normalized_query = query.casefold()

    return [
        product.model_dump(
            include={
                "sku",
                "name",
                "category",
                "description",
                "price",
                "currency",
                "stock",
            }
        )
        for product in catalog
        if any(
            normalized_query in value.casefold()
            for value in (
                product.name,
                product.category,
                product.description,
                product.sku,
            )
        )
    ]


@mcp.tool()
def create_order(sku: str, quantity: int) -> dict[str, Any]:
    """Request an order through the merchant's guarded checkout policy."""
    try:
        return create_guarded_order(sku=sku, quantity=quantity)
    except OrderServiceError as exc:
        return {
            "decision": "blocked",
            "reason": exc.detail,
        }


if __name__ == "__main__":
    mcp.run(transport="stdio")
