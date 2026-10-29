"""/chat SSE 接口（V2 走 LangGraph 状态图，帧协议只新增 trace，不改既有语义）。

帧协议（前端 utils/sse.js 按空行分帧解析）：
    data: {"type":"sources","refs":[{"source":"a.pdf","page":3,"score":0.72}]}
    data: {"type":"trace","node":"retrieve|grade|rewrite|generate", ...}
    data: {"type":"token","text":"答"}
    data: {"type":"error","message":"..."}
    data: {"type":"done"}

设计要点：
- 检索先于生成，所以 sources 帧先到，前端能立刻渲染「参考来源」
- trace 帧只新增字段（node/relevant/query/fallback），V1 前端忽略即可
- 只转发 chunk.content；reasoning_content 被忽略（qwen3.8 默认带思考）
- 异常也必须以 SSE 帧收尾，否则前端会一直挂着不返回
- 模型可由前端切换，但必须过白名单（.env 的 LLM_MODEL + LLM_MODELS）
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..agents.rag_graph import Grader, build_graph, run_graph
from ..config import get_settings
from ..schemas import ChatRequest, ModelGroup, ModelInfo

router = APIRouter()


def frame(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def resolve_model(req_model: str | None, choices: list[str]) -> str | None:
    """白名单校验。返回 None 表示用默认模型；乱填的模型名直接 400，不让它打到上游。"""
    if not req_model:
        return None
    if req_model not in choices:
        joined = ", ".join(choices)
        raise HTTPException(status_code=400, detail=f"不支持的模型 {req_model!r}，可选：{joined}")
    return req_model


async def sse_frames(
    question: str, *, store, model, k: int, grader: Grader | None = None
) -> AsyncIterator[str]:
    """核心生成器：store / model / grader 注入，方便离线测试替换打分行为。"""
    try:
        max_rewrites = get_settings().max_rewrites
        graph = build_graph(store=store, model=model, k=k, max_rewrites=max_rewrites, grader=grader)
        async for payload in run_graph(graph, question, max_rewrites=max_rewrites):
            yield frame(payload)
        yield frame({"type": "done"})
    except Exception as ex:  # noqa: BLE001 必须兜住，否则前端卡死
        yield frame({"type": "error", "message": f"{type(ex).__name__}: {ex}"[:400]})
        yield frame({"type": "done"})


@router.get("/models", response_model=ModelInfo)
def models() -> ModelInfo:
    """给前端下拉框用：默认模型 + 按 provider 分组的候选（千问 / 智谱…）。"""
    s = get_settings()
    groups = [ModelGroup(id=p.id, label=p.display, models=list(p.models)) for p in s.providers if p.models]
    return ModelInfo(default=s.llm_model, models=s.all_models, groups=groups)


@router.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    from ..llm import make_chat_model
    from ..rag.embeddings import make_embeddings
    from ..rag.vectorstore import PDF_COLLECTION, build_store

    s = get_settings()
    use_model = resolve_model(req.model, s.all_models)
    store = build_store(make_embeddings(), str(s.chroma_dir), PDF_COLLECTION)
    model = make_chat_model(model=use_model)
    return StreamingResponse(
        sse_frames(req.question, store=store, model=model, k=s.retrieval_k),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx/代理关缓冲，保证打字机效果
        },
    )
