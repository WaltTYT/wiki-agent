"""V3.0 LangGraph 状态机：Wiki 优先检索 → Grade → Generate → Reflect → Write_Wiki。

    START → retrieve ──wiki 命中(≥阈值)──→ generate → END
                   └──未命中──→ grade ──相关──→ generate → reflect ──高价值──→ write_wiki → END
                                  ↑      └──不相关且未超次数──→ rewrite
                                  └──────────────────────────────┘
                                    （不相关且已达 MAX_REWRITES）──→ generate(兜底) → END

V2 的 retrieve/grade/rewrite/generate 行为保持不变，只在前面加了「wiki_docs 优先」、
后面加了「Reflect → Write_Wiki」；SSE 协议仍只新增 trace 帧与 sources.refs 的 kind 字段。

流式方案（langgraph 1.1.10 实测，见 .doc/plan.md §3.3）：
- 节点里用 `get_stream_writer()` 直接写 SSE 载荷，图用 `astream(stream_mode="custom")` 消费。
  这样 token / sources / trace 帧的先后顺序完全由节点决定，也便于离线测试注入假模型。
- 不用 `astream_events`：自定义节点在图里只产生 on_chain_start/stream/end，
  没有 on_chat_model_stream；且 `stream_mode="updates"` 要等节点跑完才吐，拿不到打字机效果。

Grade 打分不稳定时的兜底：结构化输出失败（provider 不支持 tool calling、网络抖动）就退回
「检索最高相似度是否过线」的规则判断，避免一次判断失败演变成整条请求 500。
Reflect 失败则直接放弃沉淀（宁缺毋滥），绝不影响已生成的回答。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from ..rag.vectorstore import Hit, search
from ..rag.wiki import search_wiki
from .prompts import (
    FALLBACK_ANSWER,
    build_grade_messages,
    build_messages,
    build_rewrite_messages,
)
from .wiki_writer import ReflectVerdict, Reflector, make_reflector, persist_wiki

# 结构化打分不可用时的规则兜底线。真实 text-embedding-v4 下相关文档实测 0.44+，
# 不相关语料约 0.26；取 0.30 只作「打分失败」时的止损，不参与正常 LLM 判断。
SCORE_FALLBACK = 0.30


class GraphState(TypedDict, total=False):
    question: str
    rewritten_query: str
    docs: list[Hit]
    relevant: bool
    n_rewrites: int
    answer: str
    from_wiki: bool
    worth: bool
    wiki_slug: str
    verdict: ReflectVerdict | None


class GradeVerdict(BaseModel):
    """Grade 节点的结构化输出。"""

    relevant: bool = Field(description="资料是否足以回答问题（至少一段直接包含所需事实）")
    reason: str = Field(default="", description="一句话理由")


# grader 契约：返回 (是否相关, 理由)。测试可注入假实现，避免联网。
Grader = Callable[[str, Sequence[Hit]], Awaitable[tuple[bool, str]]]


def chunk_text(chunk) -> str:
    """从流式 chunk 取正文字符串；思考内容与结构化分片一律不转发。

    qwen3.8 默认返回 reasoning_content，且存在 content=[] 的空 chunk，
    所以不能直接把 chunk.content 拼进答案流。
    """
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


def make_grader(model, *, threshold: float = SCORE_FALLBACK) -> Grader:
    """默认 grader：LLM 结构化判断，失败时退回相似度规则。"""

    async def grade(question: str, hits: Sequence[Hit]) -> tuple[bool, str]:
        if not hits:
            return False, "no_docs"
        top = max(h.score for h in hits)
        try:
            # 显式用 function_calling：千问 / 智谱的 OpenAI 兼容层对 json_schema 支持不一，
            # tool calling 覆盖更广；解析失败会抛异常走下面的规则兜底。
            judge = model.with_structured_output(GradeVerdict, method="function_calling")
            verdict = await judge.ainvoke(build_grade_messages(question, [h.text for h in hits]))
            if isinstance(verdict, dict):
                return bool(verdict.get("relevant")), str(verdict.get("reason", ""))
            return bool(verdict.relevant), str(verdict.reason)
        except Exception as ex:  # noqa: BLE001 打分失败不该拖垮整条请求
            return top >= threshold, f"score_fallback:{type(ex).__name__}"

    return grade


def build_graph(
    *,
    store,
    model,
    k: int = 4,
    max_rewrites: int = 2,
    grader: Grader | None = None,
    wiki_store=None,
    wiki_dir: str | Path | None = None,
    reflector: Reflector | None = None,
    wiki_threshold: float = 0.68,
    dedupe_threshold: float = 0.92,
):
    """组装 V2+V3 状态图。store / model / grader / reflector 全部闭包注入，测试可整条替换。

    wiki_store / wiki_dir 为空时等价于纯 V2：不查记忆、也不写记忆。
    """
    grade_fn = grader or make_grader(model)
    reflect_fn = reflector if reflector is not None else make_reflector(model)
    can_write = wiki_store is not None and wiki_dir is not None

    def route_after_retrieve(state: GraphState) -> str:
        """记忆命中就跳过 PDF 打分，直接生成（这就是「下次变快」）。"""
        return "generate" if state.get("from_wiki") else "grade"

    def route_after_grade(state: GraphState) -> str:
        """相关就生成；不相关但还能重写就重写；重写次数用尽则走兜底生成。"""
        if state.get("relevant"):
            return "generate"
        return "rewrite" if state.get("n_rewrites", 0) < max_rewrites else "generate"

    def route_after_generate(state: GraphState) -> str:
        """只有「确实答出来了」的轮次才值得反思；wiki 命中的轮次不重复沉淀。"""
        if state.get("relevant") and not state.get("from_wiki"):
            return "reflect"
        return END

    def route_after_reflect(state: GraphState) -> str:
        return "write_wiki" if state.get("worth") else END

    async def retrieve(state: GraphState) -> dict:
        query = state.get("rewritten_query") or state["question"]
        wiki_hits = search_wiki(wiki_store, query, k=1, min_score=wiki_threshold) if wiki_store else []
        from_wiki = bool(wiki_hits)
        hits = wiki_hits if from_wiki else search(store, query, k=k)
        writer = get_stream_writer()
        # sources 必须第一个到，前端才能立刻渲染引用（与 V1 协议一致）
        writer(
            {
                "type": "sources",
                "refs": [
                    {"source": h.source, "page": h.page, "score": round(h.score, 3), "kind": h.kind}
                    for h in hits
                ],
            }
        )
        writer({"type": "trace", "node": "retrieve", "from_wiki": from_wiki})
        return {"docs": hits, "from_wiki": from_wiki, "relevant": True if from_wiki else state.get("relevant", False)}

    async def grade(state: GraphState) -> dict:
        ok, reason = await grade_fn(state["question"], state.get("docs") or [])
        get_stream_writer()({"type": "trace", "node": "grade", "relevant": ok, "reason": reason})
        return {"relevant": ok}

    async def rewrite(state: GraphState) -> dict:
        question = state["question"]
        previous = state.get("rewritten_query")
        try:
            msg = await model.ainvoke(build_rewrite_messages(question, previous))
            new_query = chunk_text(msg).strip() or previous or question
        except Exception:  # noqa: BLE001 改写失败就沿用旧查询，循环上限会兜住
            new_query = previous or question
        n = state.get("n_rewrites", 0) + 1
        get_stream_writer()({"type": "trace", "node": "rewrite", "query": new_query})
        return {"rewritten_query": new_query, "n_rewrites": n}

    async def generate(state: GraphState) -> dict:
        writer = get_stream_writer()
        fallback = not state.get("relevant")
        writer({"type": "trace", "node": "generate", "fallback": fallback})
        if fallback:
            # 资料确实不覆盖：不调 LLM，直接给确定性的兜底话术
            writer({"type": "token", "text": FALLBACK_ANSWER})
            return {"answer": FALLBACK_ANSWER}
        messages = build_messages(state["question"], [h.text for h in state.get("docs") or []])
        parts: list[str] = []
        async for chunk in model.astream(messages):
            text = chunk_text(chunk)
            if text:
                parts.append(text)
                writer({"type": "token", "text": text})
        return {"answer": "".join(parts)}

    async def reflect(state: GraphState) -> dict:
        """判断本轮是否值得沉淀。reflector 不可用/失败时静默放弃，不产生 trace。"""
        if not can_write:
            return {"worth": False, "verdict": None}
        verdict = await reflect_fn(state["question"], state.get("answer") or "", state.get("docs") or [])
        if verdict is None:
            return {"worth": False, "verdict": None}
        worth = bool(verdict.worth)
        get_stream_writer()({"type": "trace", "node": "reflect", "worth": worth, "title": verdict.title})
        return {"worth": worth, "verdict": verdict}

    async def write_wiki_node(state: GraphState) -> dict:
        verdict = state.get("verdict")
        if not verdict or not state.get("worth"):
            return {}
        writer = get_stream_writer()
        try:
            slug, merged = persist_wiki(
                store=wiki_store,
                wiki_dir=wiki_dir,
                verdict=verdict,
                question=state["question"],
                answer=state.get("answer") or "",
                hits=state.get("docs") or [],
                dedupe_threshold=dedupe_threshold,
            )
        except Exception as ex:  # noqa: BLE001 写盘失败不能影响已生成的回答
            writer({"type": "trace", "node": "write_wiki", "error": type(ex).__name__})
            return {}
        writer({"type": "trace", "node": "write_wiki", "slug": slug, "merged": merged})
        return {"wiki_slug": slug}

    graph = StateGraph(GraphState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("grade", grade)
    graph.add_node("rewrite", rewrite)
    graph.add_node("generate", generate)
    graph.add_node("reflect", reflect)
    graph.add_node("write_wiki", write_wiki_node)
    graph.add_edge(START, "retrieve")
    graph.add_conditional_edges("retrieve", route_after_retrieve, {"grade": "grade", "generate": "generate"})
    graph.add_conditional_edges("grade", route_after_grade, {"generate": "generate", "rewrite": "rewrite"})
    graph.add_edge("rewrite", "retrieve")
    graph.add_conditional_edges("generate", route_after_generate, {"reflect": "reflect", END: END})
    graph.add_conditional_edges("reflect", route_after_reflect, {"write_wiki": "write_wiki", END: END})
    graph.add_edge("write_wiki", END)
    return graph.compile()


async def run_graph(graph, question: str, *, max_rewrites: int = 2):
    """按 custom 模式消费状态图；调用方逐帧转发即可。"""
    # 节点上限：retrieve/grade 各 max_rewrites+1 次 + generate + reflect + write_wiki + 余量
    config = {"recursion_limit": 2 * max_rewrites + 8}
    async for payload in graph.astream({"question": question}, config=config, stream_mode="custom"):
        yield payload
