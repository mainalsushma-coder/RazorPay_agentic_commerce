from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Merchant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str
    name: str
    description: str
    category: str
    agent_ready: bool
    source: Literal["bound_native", "shopify"] = "bound_native"
    source_config: dict[str, Any] = Field(default_factory=dict, exclude=True)
