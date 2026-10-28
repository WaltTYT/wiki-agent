"""FastAPI 入口。

    conda activate langchain1.2
    cd backend
    uvicorn app.main:app --reload --port 8000

开发期前端走 vite proxy（/api → 8000）；
生产期把 frontend/dist 交给 StaticFiles 托管，单进程单端口即可演示（plan §4.2 无 Docker 主路径）。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.chat import router as chat_router
from .config import get_settings
from .schemas import HealthResponse

app = FastAPI(title="wiki-agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api")


@app.on_event("startup")
def warn_on_bad_config() -> None:
    """配置被手改坏时（例如 LLM_MODEL 被清空）不要静默给出空模型列表，直接喊出来。"""
    s = get_settings()
    choices = s.all_models
    if not choices:
        print("[warn] LLM 白名单为空：请检查 backend/.env 的 LLM_PROVIDERS / LLM_MODEL", flush=True)
    elif s.llm_model not in choices:
        print(f"[warn] 默认模型 {s.llm_model!r} 不在白名单 {choices} 内，前端将拿不到默认值", flush=True)
    elif not s.embedding_model:
        print("[warn] EMBEDDING_MODEL 未配置，检索会直接报错（决策 5a）", flush=True)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    s = get_settings()
    count = None
    try:
        from .rag.embeddings import make_embeddings
        from .rag.vectorstore import PDF_COLLECTION, build_store

        count = build_store(make_embeddings(), str(s.chroma_dir), PDF_COLLECTION)._collection.count()
    except Exception:  # 向量库未初始化/未配置时不该让健康检查挂掉
        pass
    return HealthResponse(status="ok", collection_count=count, model=s.llm_model)


_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")