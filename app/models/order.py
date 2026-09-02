from pydantic import BaseModel


class OrderRequest(BaseModel):
    sku: str
    quantity: int
