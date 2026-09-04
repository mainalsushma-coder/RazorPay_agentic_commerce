from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatHistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class AgentChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=20_000)
    conversation_history: list[ChatHistoryMessage] = Field(
        default_factory=list, max_length=100
    )


class AgentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["tool_call", "policy"]
    tool: str | None = None
    status: str | None = None
    decision: str | None = None


class AgentChatResponse(BaseModel):
    message: str
    merchant_id: str
    events: list[AgentEvent] = Field(default_factory=list)
    products: list[dict[str, Any]] = Field(default_factory=list)
    order: dict[str, Any] | None = None
