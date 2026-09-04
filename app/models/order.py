from pydantic import BaseModel, ConfigDict


class OrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str = "glowcare"
    sku: str
    quantity: int


class DeterministicOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    merchant_id: str
    sku: str
    quantity: int = 1
