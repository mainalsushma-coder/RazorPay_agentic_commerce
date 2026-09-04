from typing import Any

from pydantic import BaseModel, ConfigDict


class MerchantResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str
    field: str
    value: Any


class MerchantResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolutions: list[MerchantResolution]
