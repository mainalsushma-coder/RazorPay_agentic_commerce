from pydantic import BaseModel, ConfigDict


class OrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str = "glowcare"
    sku: str
    quantity: int
