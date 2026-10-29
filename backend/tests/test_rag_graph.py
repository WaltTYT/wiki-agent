"""V2.0 LangGraph 状态机离线测试：三条路由 + 打分兜底，不联网、不花 API 钱。

    cd backend; pytest tests/test_rag_graph.py -q
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document

from app.agents.prompts import FALLBACK_ANSWER
from app.agents.rag_graph import make_grader
from app.api.chat import sse_frames
from app.rag.embeddings import CharBigramHashEmbeddings
from app.rag.vectorstore import Hit, build_store, reset_collection

KB = [
    ("公司员工每年享有十五天带薪年假，入职满三年后增加到二十天。", "hr.pdf"),
    ("差旅报销需提供发票原件，审批周期为五个工作日。", "hr.pdf"),
]
QUERY = "年假有几天"


class RouteModel:
    """既能流式生成、又能做 Rewrite（ainvoke）的假模型。"""

    def __init__(self, pieces=("你", "有", "15", "天")):
        self.pieces = pieces
        self.rewrite_calls = 0
        self.rewrite_queries: list[str] = []

    async def ainvoke(self, messages):
        self.rewrite_calls += 1
        text = f"改写查询{self.rewrite_calls}"
        self.rewrite_queries.append(text)
        return SimpleNamespace(content=text)

    async def astream(self, messages):
        for p in self.pieces:
            yield SimpleNamespace(content=p, additional_kwargs={})


def make_grader_stub(verdicts: list[bool]):
    """按顺序返回预设判定，最后一条会一直复用。"""
    calls = {"n": 0}

    async def grade(question, hits):
        i = calls["n"]
        calls["n"] += 1
        if not verdicts:
            return False, "mock"
        return verdicts[min(i, len(verdicts) - 1)], "mock"

    return grade, calls


@pytest.fixture()
def store(tmp_path):
    s = build_store(CharBigramHashEmbeddings(), str(tmp_path / "chroma"), "graph_test_docs")
    reset_collection(s)
    docs = [
        Document(page_content=text, metadata={"source": src, "page": i, "chunk_id": f"g#{i}"})
        for i, (text, src) in enumerate(KB)
    ]
    s.add_documents(docs, ids=[d.metadata["chunk_id"] for d in docs])
    return s


@pytest.fixture()
def empty_store(tmp_path):
    s = build_store(CharBigramHashEmbeddings(), str(tmp_path / "chroma_empty"), "graph_test_empty")
    reset_collection(s)
    return s


def parse(text):
    out = []
    for block in text.split("\n\n"):
        block = block.strip()
        if block.startswith("data:"):
            out.append(json.loads(block[5:].strip()))
    return out


def drain(question, store, model, grader):
    async def collect():
        buf = ""
        async for f in sse_frames(question, store=store, model=model, k=2, grader=grader):
            buf += f
        return parse(buf)

    return asyncio.run(collect())


def nodes(frames):
    return [f["node"] for f in frames if f["type"] == "trace"]


def tokens(frames):
    return "".join(f["text"] for f in frames if f["type"] == "token")


# ── 路由 1：一次命中 → 直接生成 ─────────────────────────────
def test_relevant_goes_straight_to_generate(store):
    model = RouteModel()
    grader, calls = make_grader_stub([True])
    frames = drain(QUERY, store, model, grader)

    assert nodes(frames) == ["retrieve", "grade", "generate"], "相关时应 retrieve → grade → generate"
    assert calls["n"] == 1
    assert model.rewrite_calls == 0, "相关就不该触发改写"
    assert tokens(frames) == "你有15天"
    assert frames[0]["type"] == "sources", "sources 帧必须仍然最先到（V1 协议）"
    assert frames[-1]["type"] == "done"


# ── 路由 2：首轮不相关 → 改写后命中 → 生成 ───────────────────
def test_rewrite_then_generate(store):
    model = RouteModel()
    grader, calls = make_grader_stub([False, True])
    frames = drain(QUERY, store, model, grader)

    assert nodes(frames) == ["retrieve", "grade", "rewrite", "retrieve", "grade", "generate"]
    assert model.rewrite_calls == 1
    assert model.rewrite_queries == ["改写查询1"]
    assert calls["n"] == 2
    assert sum(1 for f in frames if f["type"] == "sources") == 2, "每轮检索都应刷新 sources"
    assert tokens(frames) == "你有15天"
    assert not any(f.get("fallback") for f in frames if f["type"] == "trace")


# ── 路由 3：一直不相关 → 重写次数硬上限 → 兜底话术 ───────────
def test_max_rewrites_then_fallback(store):
    model = RouteModel()
    grader, calls = make_grader_stub([False])  # 永远不相关
    frames = drain(QUERY, store, model, grader)

    assert nodes(frames) == [
        "retrieve", "grade",
        "rewrite", "retrieve", "grade",
        "rewrite", "retrieve", "grade",
        "generate",
    ], "MAX_REWRITES=2：改写两次后必须进兜底，不能死循环"
    assert model.rewrite_calls == 2
    assert calls["n"] == 3
    gen = next(f for f in frames if f["type"] == "trace" and f["node"] == "generate")
    assert gen["fallback"] is True
    assert tokens(frames) == FALLBACK_ANSWER, "兜底不调 LLM，直接给确定性话术"
    assert frames[-1]["type"] == "done"


def test_empty_collection_ends_with_fallback(empty_store):
    """库里一条数据都没有：不打 LLM 打分（无资料即不相关），最终如实兜底。"""
    model = RouteModel()
    grader, calls = make_grader_stub([])
    frames = drain(QUERY, empty_store, model, grader)

    assert nodes(frames)[-1] == "generate"
    assert tokens(frames) == FALLBACK_ANSWER
    assert frames[0] == {"type": "sources", "refs": []}
    assert calls["n"] == 3, "每轮 grade 节点仍会执行，但默认 grader 对空资料直接返回不相关"


# ── 打分兜底：结构化输出不可用时退回相似度阈值 ───────────────
def test_grader_falls_back_to_score_when_model_cannot_grade():
    class NoStructuredOutput:
        pass

    grader = make_grader(NoStructuredOutput(), threshold=0.3)
    high = Hit(text="x", source="a.pdf", page=None, score=0.9)
    low = Hit(text="x", source="a.pdf", page=None, score=0.1)

    ok_high, why_high = asyncio.run(grader("q", [high]))
    ok_low, why_low = asyncio.run(grader("q", [low]))
    assert ok_high is True and ok_low is False
    assert why_high.startswith("score_fallback")
    assert why_low.startswith("score_fallback")

    ok_none, why_none = asyncio.run(grader("q", []))
    assert ok_none is False and why_none == "no_docs"


def test_grader_uses_function_calling_structured_output():
    """千问 / 智谱兼容层对 json_schema 支持不一，必须显式走 tool calling。"""
    seen = {}

    class StructModel:
        def with_structured_output(self, schema, method="json_schema"):
            seen["schema"] = schema
            seen["method"] = method

            class Runner:
                async def ainvoke(self, messages):
                    return {"relevant": True, "reason": "资料直接给出年假天数"}

            return Runner()

    hit = Hit(text="年假十五天", source="hr.pdf", page=None, score=0.2)  # 分数低于阈值也不影响
    ok, reason = asyncio.run(make_grader(StructModel())("年假有几天", [hit]))
    assert ok is True
    assert reason == "资料直接给出年假天数"
    assert seen["method"] == "function_calling"
    assert seen["schema"].__name__ == "GradeVerdict"
