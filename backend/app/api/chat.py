"""V3.0：/chat SSE 接口走「Wiki 优先 + 自我纠错」状态图；帧协议只新增 trace/kind，不改既有语义。

帧协议（前端 utils/sse.js 按空行分帧解析）：
    data: {"type":"sources","refs":[{"source":"wiki/xxx.md","page":null,"score":0.81,"kind":"wiki"}]}
    data: {"type":"trace","node":"retrieve|grade|rewrite|generate|reflect|write_wiki", ...}
    data: {"type":"token","text":"答"}
    data: {"type":"error","message":"..."}
    data: {"type":"done"}

设计要点：
- 检索先于生成，所以 sources 帧先到，前端能立刻渲染「参考来源」
- trace 帧只新增字段，V1 前端忽略即可
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
from ..agents.wiki_writer import Reflector, make_reflector
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
    question: str,
    *,
    store,
    model,
    k: int,
    grader: Grader | None = None,
    wiki_store=None,
    wiki_dir: str | None = None,
    reflector: Reflector | None = None,
) -> AsyncIterator[str]:
    """核心生成器：store / model / grader / reflector 注入，方便离线测试替换行为。

    wiki_store + wiki_dir 两者都传才启用记忆闭环；只传其一等价于纯 V2。
    """
    try:
        s = get_settings()
        max_rewrites = s.max_rewrites
        graph = build_graph(
            store=store,
            model=model,
            k=k,
            max_rewrites=max_rewrites,
            grader=grader,
            wiki_store=wiki_store,
            wiki_dir=wiki_dir,
            reflector=reflector,
            wiki_threshold=s.wiki_sim_threshold,
            dedupe_threshold=s.wiki_dedupe_threshold,
        )
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
    from ..rag.vectorstore import PDF_COLLECTION, WIKI_COLLECTION, build_store

    s = get_settings()
    use_model = resolve_model(req.model, s.all_models)
    embeddings = make_embeddings()
    store = build_store(embeddings, str(s.chroma_dir), PDF_COLLECTION)
    # 记忆层与 PDF 层共用 embedding，独立 collection，互不污染
    wiki_store = build_store(embeddings, str(s.chroma_dir), WIKI_COLLECTION)
    model = make_chat_model(model=use_model)
    return StreamingResponse(
        sse_frames(
            req.question,
            store=store,
            model=model,
            k=s.retrieval_k,
            wiki_store=wiki_store,
            wiki_dir=str(s.wiki_path),
            reflector=make_reflector(model),
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx/代理关缓冲，保证打字机效果
        },
    )
