"""请求/响应模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000, description="用户问题")
    model: str | None = Field(default=None, max_length=100, description="留空则用 .env 的默认模型")


class ModelGroup(BaseModel):
    id: str
    label: str
    models: list[str]


class ModelInfo(BaseModel):
    default: str
    models: list[str]
    groups: list[ModelGroup]


class HealthResponse(BaseModel):
    status: str = "ok"
    collection_count: int | None = None
    model: str | None = None