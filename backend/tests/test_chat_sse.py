"""SSE 帧协议离线测试：不联网、不装 pytest-asyncio，用真 Chroma + 假模型验证 /chat。

    cd backend; pytest tests/test_chat_sse.py -q
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document

from app.agents.rag_graph import chunk_text
from app.api.chat import frame, sse_frames
from app.rag.embeddings import CharBigramHashEmbeddings
from app.rag.vectorstore import build_store, reset_collection

KB = [
    ("公司员工每年享有十五天带薪年假，入职满三年后增加到二十天。", "hr.pdf"),
    ("差旅报销需提供发票原件，审批周期为五个工作日。", "hr.pdf"),
    ("后端用 FastAPI 的 StreamingResponse 实现逐块流式响应。", "tech.md"),
]


class FakeModel:
    """模拟 qwen3.8：思考与正文分离，并夹带空 chunk / 列表形态 content。"""

    def __init__(self, pieces, with_reasoning=True):
        self.pieces = pieces
        self.with_reasoning = with_reasoning
        self.seen_messages = None

    async def astream(self, messages):
        self.seen_messages = messages
        if self.with_reasoning:
            yield SimpleNamespace(content="", additional_kwargs={"reasoning_content": "用户在问年假，先查资料"})
        yield SimpleNamespace(content=[], additional_kwargs={})
        for p in self.pieces:
            yield SimpleNamespace(content=p, additional_kwargs={})
        yield SimpleNamespace(content="", additional_kwargs={})


class BoomModel:
    async def astream(self, messages):
        raise RuntimeError("上游 500")
        yield  # pragma: no cover


@pytest.fixture()
def store(tmp_path):
    s = build_store(CharBigramHashEmbeddings(), str(tmp_path / "chroma"), "sse_test_docs")
    reset_collection(s)
    docs = [
        Document(page_content=c, metadata={"source": src, "page": i, "chunk_id": f"c#{i}"})
        for i, (c, src) in enumerate(KB)
    ]
    s.add_documents(docs, ids=[d.metadata["chunk_id"] for d in docs])
    return s


def parse(text):
    out = []
    for block in text.split("\n\n"):
        block = block.strip()
        if block.startswith("data:"):
            out.append(json.loads(block[5:].strip()))
    return out


async def _drain(agen):
    buf = ""
    async for f in agen:
        buf += f
    return parse(buf)


def drain(question, store, model, k=2):
    """同步包装：避免引入 pytest-asyncio 依赖。

    V2 起分数由 Grade 节点决定；这里固定注入「有资料即相关」，
    让本文件继续只验证 SSE 帧协议本身（路由行为见 test_rag_graph.py）。
    """

    async def always_relevant(question, hits):
        return bool(hits), "test"

    return asyncio.run(_drain(sse_frames(question, store=store, model=model, k=k, grader=always_relevant)))


# ── 帧协议 ────────────────────────────────────────────────
def test_frame_is_sse_compliant():
    f = frame({"type": "token", "text": "中文"})
    assert f.startswith("data: ")
    assert f.endswith("\n\n")
    assert "中文" in f, "ensure_ascii=False，中文不该被转义成 \\uXXXX"


def test_sources_frame_comes_first(store):
    frames = drain("年假有几天", store, FakeModel(["你", "有", "15", "天"]))
    assert frames[0]["type"] == "sources"
    assert frames[-1]["type"] == "done"
    assert frames[0]["refs"], "应至少有一条引用"
    assert frames[0]["refs"][0]["source"] == "hr.pdf"
    assert 0 <= frames[0]["refs"][0]["score"] <= 1


def test_tokens_reassemble_to_answer(store):
    frames = drain("年假有几天", store, FakeModel(["你", "有", "15", "天"]))
    assert "".join(f["text"] for f in frames if f["type"] == "token") == "你有15天"


def test_reasoning_never_leaks_into_tokens(store):
    """qwen3.8 默认带 reasoning_content，绝不能混进答案流。"""
    frames = drain("年假有几天", store, FakeModel(["好"], with_reasoning=True))
    joined = "".join(f["text"] for f in frames if f["type"] == "token")
    assert joined == "好"
    assert "思考" not in joined and "查资料" not in joined


def test_prompt_contains_retrieved_context(store):
    m = FakeModel(["x"])
    drain("报销要什么材料", store, m)
    system, user = m.seen_messages[0], m.seen_messages[1]
    assert system[0] == "system" and "禁止编造" in system[1]
    assert user[0] == "user" and "发票原件" in user[1], "检索到的资料必须进 prompt"


def test_error_still_terminates_stream(store):
    frames = drain("随便问点什么", store, BoomModel())
    types = [f["type"] for f in frames]
    assert "error" in types, "异常必须以 error 帧告知前端"
    assert types[-1] == "done", "异常后仍要收尾，否则前端一直挂着"


@pytest.mark.parametrize(
    "chunk,expect",
    [
        (SimpleNamespace(content="abc"), "abc"),
        (SimpleNamespace(content=[]), ""),
        (SimpleNamespace(content=[{"type": "text", "text": "甲"}, "乙", {"type": "reasoning", "text": "忽略"}]), "甲乙"),
        (SimpleNamespace(content=None), ""),
    ],
)
def test_chunk_text_extraction(chunk, expect):
    assert chunk_text(chunk) == expect