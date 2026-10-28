"""/chat SSE 接口（V1 直线版；V2 换成 LangGraph 时保持同样的帧协议）。

帧协议（前端 utils/sse.js 按空行分帧解析）：
    data: {"type":"sources","refs":[{"source":"a.pdf","page":3,"score":0.72}]}
    data: {"type":"token","text":"答"}
    data: {"type":"error","message":"..."}
    data: {"type":"done"}

设计要点：
- 检索先于生成，所以 sources 帧先到，前端能立刻渲染「参考来源」
- 只转发 chunk.content；reasoning_content 被忽略（qwen3.8 默认带思考）
- 异常也必须以 SSE 帧收尾，否则前端会一直挂着不返回
- 模型可由前端切换，但必须过白名单（.env 的 LLM_MODEL + LLM_MODELS）
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..agents.prompts import build_messages
from ..config import get_settings
from ..rag.vectorstore import search
from ..schemas import ChatRequest, ModelGroup, ModelInfo

router = APIRouter()


def frame(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def chunk_text(chunk) -> str:
    """从流式 chunk 取正文字符串；思考内容与结构化分片一律不转发。"""
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, str):
                out.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                out.append(str(part.get("text", "")))
        return "".join(out)
    return ""


def resolve_model(req_model: str | None, choices: list[str]) -> str | None:
    """白名单校验。返回 None 表示用默认模型；乱填的模型名直接 400，不让它打到上游。"""
    if not req_model:
        return None
    if req_model not in choices:
        joined = ", ".join(choices)
        raise HTTPException(status_code=400, detail=f"不支持的模型 {req_model!r}，可选：{joined}")
    return req_model


async def sse_frames(question: str, *, store, model, k: int) -> AsyncIterator[str]:
    """核心生成器：store / model 注入，方便离线测试与 V2 换图。"""
    try:
        hits = search(store, question, k=k)
        refs = [{"source": h.source, "page": h.page, "score": round(h.score, 3)} for h in hits]
        yield frame({"type": "sources", "refs": refs})
        messages = build_messages(question, [h.text for h in hits])
        async for chunk in model.astream(messages):
            text = chunk_text(chunk)
            if text:
                yield frame({"type": "token", "text": text})
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
