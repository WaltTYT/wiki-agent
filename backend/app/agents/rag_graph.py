"""V2.0 LangGraph 状态机：Retrieve → Grade →(相关) Generate / (不相关) Rewrite。

    START → retrieve → grade ──相关──→ generate → END
                        ↑      └──不相关且未超次数──→ rewrite
                        └──────────────────────────────┘
                          （不相关且已达 MAX_REWRITES）──→ generate(兜底话术)

流式方案（langgraph 1.1.10 实测，见 .doc/plan.md §3.3）：
- 节点里用 `get_stream_writer()` 直接写 SSE 载荷，图用 `astream(stream_mode="custom")` 消费。
  这样 token / sources / trace 帧的先后顺序完全由节点决定，也便于离线测试注入假模型。
- 不用 `astream_events`：自定义节点在图里只产生 on_chain_start/stream/end，
  没有 on_chat_model_stream；且 `stream_mode="updates"` 要等节点跑完才吐，拿不到打字机效果。

Grade 打分不稳定时的兜底：结构化输出失败（provider 不支持 tool calling、网络抖动）就退回
「检索最高相似度是否过线」的规则判断，避免一次判断失败演变成整条请求 500。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from ..rag.vectorstore import Hit, search
from .prompts import (
    FALLBACK_ANSWER,
    build_grade_messages,
    build_messages,
    build_rewrite_messages,
)

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


def build_graph(*, store, model, k: int = 4, max_rewrites: int = 2, grader: Grader | None = None):
    """组装 V2 状态图。store / model / grader 以闭包注入，测试可整条替换。"""
    grade_fn = grader or make_grader(model)

    def route_after_grade(state: GraphState) -> str:
        """相关就生成；不相关但还能重写就重写；重写次数用尽则走兜底生成。"""
        if state.get("relevant"):
            return "generate"
        return "rewrite" if state.get("n_rewrites", 0) < max_rewrites else "generate"

    async def retrieve(state: GraphState) -> dict:
        query = state.get("rewritten_query") or state["question"]
        hits = search(store, query, k=k)
        writer = get_stream_writer()
        # sources 必须第一个到，前端才能立刻渲染引用（与 V1 协议一致）
        writer(
            {
                "type": "sources",
                "refs": [{"source": h.source, "page": h.page, "score": round(h.score, 3)} for h in hits],
            }
        )
        writer({"type": "trace", "node": "retrieve"})
        return {"docs": hits}

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

    graph = StateGraph(GraphState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("grade", grade)
    graph.add_node("rewrite", rewrite)
    graph.add_node("generate", generate)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "grade")
    graph.add_conditional_edges("grade", route_after_grade, {"generate": "generate", "rewrite": "rewrite"})
    graph.add_edge("rewrite", "retrieve")
    graph.add_edge("generate", END)
    return graph.compile()


async def run_graph(graph, question: str, *, max_rewrites: int = 2):
    """按 custom 模式消费状态图；调用方逐帧转发即可。"""
    config = {"recursion_limit": 2 * max_rewrites + 6}
    async for payload in graph.astream({"question": question}, config=config, stream_mode="custom"):
        yield payload
