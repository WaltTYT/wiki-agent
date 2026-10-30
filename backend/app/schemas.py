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


class IngestResponse(BaseModel):
    """一次入库的结果摘要。/ingest/upload 返回，前端据此提示“入库 N 条”。"""

    changed: bool = Field(description="是否真的重建了索引")
    files: int = Field(description="语料文件数")
    chunks: int = Field(description="本次入库的 chunk 数，跳过时为 0")
    total: int = Field(description="集合总 chunk 数")
    seconds: float = Field(description="耗时（秒）")
    uploaded: list[str] = Field(default_factory=list, description="本次上传并落盘的文件名（仅 upload 接口）")


class KnowledgeFile(BaseModel):
    name: str = Field(description="文件名")
    size: int = Field(description="字节数")
    chunks: int = Field(description="该文件在向量库里的片段数")


class KnowledgeInfo(BaseModel):
    """知识库概览：磁盘语料 + 每个文件实际入库的片段数。"""

    files: list[KnowledgeFile]
    total_chunks: int


class WikiEntryInfo(BaseModel):
    """一条沉淀记忆（GET /wiki 用）。"""

    slug: str
    title: str
    question: str
    answer: str
    summary: str = ""
    sources: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class WikiListResponse(BaseModel):
    entries: list[WikiEntryInfo]
    total: int