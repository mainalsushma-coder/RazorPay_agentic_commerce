from pydantic import BaseModel, ConfigDict


class OrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str
    quantity: int
