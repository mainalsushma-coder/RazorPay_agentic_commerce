from pydantic import BaseModel


class Merchant(BaseModel):
    merchant_id: str
    name: str
    description: str
    category: str
    agent_ready: bool
