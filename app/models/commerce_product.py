from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CommerceProduct(BaseModel):
    """Source-preserving product facts safe for buyer-facing responses."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["bound_native", "shopify"]
    merchant_id: str
    source_product_id: str
    source_variant_id: str | None = None
    sku: str | None = None
    name: str
    category: str = "Product"
    description: str = ""
    price: float = Field(ge=0)
    currency: str
    available: bool
    stock: int | None = None
    image_url: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    authoritative_source: str
    verified: bool = True
    checkout_capability: dict[str, Any]
