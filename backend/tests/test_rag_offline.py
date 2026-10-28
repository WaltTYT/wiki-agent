"""离线单测：不需要 API key、不联网。

    conda activate langchain1.2
    cd backend
    pytest -q
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.rag.embeddings import CharBigramHashEmbeddings, make_embeddings
from app.rag.loader import make_splitter
from app.rag.vectorstore import (
    PDF_COLLECTION,
    Hit,
    add_documents,
    build_store,
    clamp01,
    reset_collection,
    search,
)

EMB = CharBigramHashEmbeddings()

CORPUS = {
    "年假": "公司员工每年享有十五天带薪年假，入职满三年后增加到二十天。",
    "报销": "差旅报销需要提供发票原件，审批周期为五个工作日。",
    "流式": "FastAPI 使用 StreamingResponse 配合异步生成器实现逐块流式响应。",
}


@pytest.fixture()
def store(tmp_path: Path):
    s = build_store(EMB, str(tmp_path / "chroma"), PDF_COLLECTION)
    docs = [
        __import__("langchain_core.documents", fromlist=["Document"]).Document(
            page_content=text, metadata={"source": "kb.pdf", "page": i, "chunk_id": f"kb#{i}"}
        )
        for i, (_, text) in enumerate(CORPUS.items())
    ]
    add_documents(s, docs, ids=[f"kb#{i}" for i in range(len(docs))])
    return s


# ── 决策 5a：禁止静默降级 ────────────────────────────────────
def test_missing_embedding_config_raises(monkeypatch: pytest.MonkeyPatch):
    import app.rag.embeddings as mod

    empty = Settings(embedding_model="", embedding_api_key="", embedding_base_url="")
    monkeypatch.setattr(mod, "get_settings", lambda: empty)
    with pytest.raises(RuntimeError, match="EMBEDDING_MODEL"):
        mod.make_embeddings()


def test_embeddings_factory_builds_when_configured(monkeypatch: pytest.MonkeyPatch):
    import app.rag.embeddings as mod

    ok = Settings(
        embedding_model="text-embedding-v4",
        embedding_api_key="sk-test",
        embedding_base_url="https://example.invalid/v1",
    )
    monkeypatch.setattr(mod, "get_settings", lambda: ok)
    emb = make_embeddings()
    assert emb.model == "text-embedding-v4"
    assert str(emb.openai_api_base).rstrip("/").endswith("/v1")
    # 实测约束：千问 AI 平台兼容层不接受 token id 数组，必须关掉 ctx_length 走原始字符串
    # （见 .doc/plan.md §1.6；回归防呆——有人改回 True 就立刻红）
    assert emb.check_embedding_ctx_length is False
    assert emb.chunk_size == 10, "必须分批发送，避免平台 input 上限"


# ── §1.5 实测约束 1：space 必须是 cosine ─────────────────────
def test_space_is_cosine(store):
    assert store._collection.configuration["hnsw"]["space"] == "cosine"


def test_bad_collection_name_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="非法 collection 名"):
        build_store(EMB, str(tmp_path), "t1")  # 实测：Chroma 拒绝 <3 字符的名字


# ── §1.5 实测约束 3：relevance 可能 <0，必须 clamp ────────────
@pytest.mark.parametrize("x,expect", [(-0.017, 0.0), (1.2, 1.0), (0.5, 0.5)])
def test_clamp01(x: float, expect: float):
    assert clamp01(x) == expect


def test_scores_within_unit_range(store):
    hits = search(store, "带薪年假有几天", k=3)
    assert hits, "检索不应为空"
    assert all(0.0 <= h.score <= 1.0 for h in hits)
    assert hits[0].source == "kb.pdf"
    assert isinstance(hits[0], Hit)


def test_literal_overlap_wins(store):
    assert search(store, "差旅报销发票原件", k=1)[0].text == CORPUS["报销"]
    assert search(store, "逐块流式响应", k=1)[0].text == CORPUS["流式"]


def test_page_is_one_based(store):
    hit = search(store, "十五天带薪年假", k=1)[0]
    assert hit.page == 1  # metadata page=0 → 展示为第 1 页


# ── 幂等：重复 ingest 不该让集合翻倍 ─────────────────────────
def test_reset_is_idempotent(store):
    before = store._collection.count()
    reset_collection(store)
    assert store._collection.count() == 0
    add_documents(store, [], ids=None)
    assert store._collection.count() == 0
    # 重建后 space 仍是 cosine
    assert store._collection.configuration["hnsw"]["space"] == "cosine"
    assert before == 3


# ── 切分器：中文分隔符 + metadata 透传 ───────────────────────
def test_splitter_respects_size():
    from langchain_core.documents import Document

    long = "这是第一句话。" * 400
    chunks = make_splitter(chunk_size=200, chunk_overlap=20).split_documents([Document(page_content=long)])
    assert len(chunks) > 1
    assert all(len(c.page_content) <= 240 for c in chunks)


def test_splitter_keeps_chinese_punctuation():
    from langchain_core.documents import Document

    text = "第一段内容。第二段内容。第三段内容。"
    chunks = make_splitter(chunk_size=10, chunk_overlap=0).split_documents([Document(page_content=text)])
    assert "".join(c.page_content for c in chunks).replace(" ", "").startswith("第一段内容")
