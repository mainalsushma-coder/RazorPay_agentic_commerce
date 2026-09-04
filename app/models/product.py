import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str
    name: str
    category: str
    description: str
    price: float = Field(ge=0)
    currency: str = "INR"
    stock: int = Field(ge=0)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("sku", "name", "category", "description", "currency")
    @classmethod
    def non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

    @field_validator("price")
    @classmethod
    def finite_price(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("must be finite")
        return value
