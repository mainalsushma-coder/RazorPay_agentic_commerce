from typing import Any

from pydantic import BaseModel


class Product(BaseModel):
    sku: str
    name: str
    category: str
    description: str
    price: float | str
    currency: str = "INR"
    stock: int | str
    attributes: dict[str, Any] = {}
