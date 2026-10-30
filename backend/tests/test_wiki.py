"""V3.0 Wiki 记忆层离线测试：md 往返、去重合并、优先检索、Reflect 写入。

    cd backend; pytest tests/test_wiki.py -q

全部用 CharBigramHashEmbeddings，不联网、不花 API 钱。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.agents.rag_graph import build_graph, run_graph
from app.agents.wiki_writer import ReflectVerdict, persist_wiki
from app.rag.embeddings import CharBigramHashEmbeddings
from app.rag.vectorstore import Hit, build_store, reset_collection
from app.rag.wiki import (
    WikiEntry,
    delete_entry,
    find_similar_slug,
    load_entries,
    read_entry,
    search_wiki,
    slugify,
    upsert_entry,
    write_entry,
)

KB_TEXT = "公司员工每年享有十五天带薪年假，入职满三年后增加到二十天。"
QUESTION = "年假有几天"


class GenModel:
    """只会流式生成，用来替代真实 LLM（grade/reflect 都走注入的假实现）。"""

    def __init__(self, pieces=("15", "天")):
        self.pieces = pieces

    async def ainvoke(self, messages):  # rewrite 用
        return SimpleNamespace(content="改写后的查询")

    async def astream(self, messages):
        for p in self.pieces:
            yield SimpleNamespace(content=p, additional_kwargs={})


def make_grader(verdict: bool):
    async def grade(question, hits):
        return verdict, "mock"

    return grade


def make_reflector(verdict: ReflectVerdict | None):
    async def reflect(question, answer, hits):
        return verdict

    return reflect


def drain(graph, question: str = QUESTION) -> list[dict]:
    async def collect():
        return [p async for p in run_graph(graph, question, max_rewrites=2)]

    return asyncio.run(collect())


def nodes(frames):
    return [f["node"] for f in frames if f["type"] == "trace"]


@pytest.fixture()
def wiki_store(tmp_path):
    s = build_store(CharBigramHashEmbeddings(), str(tmp_path / "chroma"), "wiki_test_docs")
    reset_collection(s)
    return s


@pytest.fixture()
def pdf_store(tmp_path):
    s = build_store(CharBigramHashEmbeddings(), str(tmp_path / "chroma"), "pdf_test_docs")
    reset_collection(s)
    return s


def seed_pdf(store):
    from langchain_core.documents import Document

    store.add_documents(
        [Document(page_content=KB_TEXT, metadata={"source": "hr.pdf", "page": 0})], ids=["hr#0000"]
    )


def seed_wiki(store, answer=KB_TEXT, question=QUESTION, title="年假天数"):
    entry = WikiEntry(
        slug=slugify(title),
        title=title,
        question=question,
        answer=answer,
        sources=["hr.pdf"],
        summary="每年十五天，满三年二十天",
        created_at="2026-10-30 10:00:00",
    )
    upsert_entry(store, entry)
    return entry


# ── md 层：写、读、索引 ────────────────────────────────────
def test_slug_is_stable_and_ascii():
    assert slugify("年假有几天") == slugify(" 年假有几天 ")
    assert slugify("年假有几天").isalnum()


def test_write_and_read_roundtrip(tmp_path):
    entry = WikiEntry(
        slug=slugify("报销材料"),
        title="报销材料",
        question="差旅报销要交什么",
        answer="发票原件与行程单。",
        sources=["hr.pdf#3", "handbook.md"],
        summary="两样材料",
        created_at="2026-10-30 10:00:00",
    )
    path = write_entry(tmp_path, entry)
    assert path.exists()
    back = read_entry(path)
    assert back is not None
    assert back.title == entry.title
    assert back.answer == entry.answer
    assert back.sources == entry.sources
    assert back.created_at == entry.created_at

    # 索引同步生成，且不计入条目
    index = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "报销材料" in index
    assert [e.slug for e in load_entries(tmp_path)] == [entry.slug]


def test_delete_entry_removes_file_and_updates_index(tmp_path):
    entry = WikiEntry(
        slug=slugify("x"),
        title="x",
        question="q",
        answer="a",
        created_at="2026-10-30 10:00:00",
    )
    write_entry(tmp_path, entry)
    assert delete_entry(tmp_path, entry.slug) is True
    assert load_entries(tmp_path) == []
    with pytest.raises(ValueError):
        delete_entry(tmp_path, "../etc/passwd")


# ── 向量层：优先检索与阈值 ────────────────────────────────
def test_search_wiki_marks_kind_and_blocks_low_score(wiki_store):
    seed_wiki(wiki_store)
    hits = search_wiki(wiki_store, KB_TEXT, k=1, min_score=0.5)
    assert len(hits) == 1
    assert hits[0].kind == "wiki"
    assert hits[0].source.startswith("wiki/")
    assert hits[0].score >= 0.5

    # 不相关查询被阈值挡掉，调用方应回落 PDF
    assert search_wiki(wiki_store, "今天天气怎么样", k=1, min_score=0.5) == []


def test_upsert_is_idempotent(wiki_store):
    seed_wiki(wiki_store)
    seed_wiki(wiki_store, title="年假天数")  # 同 slug 覆盖
    assert wiki_store._collection.count() == 1


def test_persist_wiki_merges_same_question(wiki_store, tmp_path):
    hit = Hit(text=KB_TEXT, source="hr.pdf", page=1, score=0.5)
    verdict = ReflectVerdict(worth=True, title="年假天数", summary="每年十五天")
    slug1, merged1 = persist_wiki(
        store=wiki_store, wiki_dir=tmp_path, verdict=verdict, question=QUESTION,
        answer="十五天。", hits=[hit], dedupe_threshold=0.92,
    )
    hit2 = Hit(text=KB_TEXT, source="handbook.md", page=None, score=0.5)
    slug2, merged2 = persist_wiki(
        store=wiki_store, wiki_dir=tmp_path, verdict=verdict, question=QUESTION,
        answer="十五天（满三年二十天）。", hits=[hit2], dedupe_threshold=0.92,
    )
    assert slug1 == slug2, "同一问题必须复用既有 slug"
    assert merged2 is True
    entries = load_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0].sources == ["hr.pdf#1", "handbook.md"], "来源应合并去重"
    assert "二十天" in entries[0].answer
    assert wiki_store._collection.count() == 1


def test_find_similar_slug_respects_threshold(wiki_store):
    # 标题与已有内容完全一致时相似度为 1；假 embedding 做不了跨语义近似，
    # 真实 text-embedding-v4 下相似标题会落在 0.9+，阈值逻辑本身与模型无关。
    seed_wiki(wiki_store, answer="年假天数", title="年假天数")
    assert find_similar_slug(wiki_store, "年假天数", 0.92) == slugify("年假天数")
    assert find_similar_slug(wiki_store, "今天天气怎么样", 0.5) is None
    assert find_similar_slug(None, "年假天数", 0.5) is None


# ── 图：wiki 优先 → 免 grade ───────────────────────────────
def test_wiki_hit_skips_pdf_and_grade(pdf_store, wiki_store, tmp_path):
    # 答案里带上问题原文，保证假 embedding 的字面相似度过线（真实 embedding 无此需要）
    seed_wiki(wiki_store, answer=f"{QUESTION}：十五天带薪年假。")
    calls = {"n": 0}

    async def grader(q, hits):
        calls["n"] += 1
        return False, "should-not-run"

    graph = build_graph(
        store=pdf_store,
        model=GenModel(),
        k=2,
        grader=grader,
        wiki_store=wiki_store,
        wiki_dir=tmp_path,
        reflector=make_reflector(None),
        wiki_threshold=0.2,
    )
    frames = drain(graph)

    assert frames[0]["type"] == "sources"
    assert frames[0]["refs"][0]["kind"] == "wiki"
    assert calls["n"] == 0, "记忆命中就不该再走 PDF grade"
    assert nodes(frames) == ["retrieve", "generate"]
    assert "".join(f["text"] for f in frames if f["type"] == "token") == "15天"


# ── 图：生成 → reflect → write_wiki ─────────────────────────
def test_reflect_worth_writes_wiki(pdf_store, wiki_store, tmp_path):
    seed_pdf(pdf_store)
    verdict = ReflectVerdict(worth=True, title="年假天数", summary="每年十五天")
    graph = build_graph(
        store=pdf_store,
        model=GenModel(),
        k=2,
        grader=make_grader(True),
        wiki_store=wiki_store,
        wiki_dir=tmp_path,
        reflector=make_reflector(verdict),
    )
    frames = drain(graph)

    assert nodes(frames) == ["retrieve", "grade", "generate", "reflect", "write_wiki"]
    write = next(f for f in frames if f.get("node") == "write_wiki")
    assert write["merged"] is False
    entries = load_entries(tmp_path)
    assert len(entries) == 1 and entries[0].answer == "15天"
    assert entries[0].sources == ["hr.pdf#1"]
    assert wiki_store._collection.count() == 1


def test_reflect_not_worth_skips_write(pdf_store, wiki_store, tmp_path):
    seed_pdf(pdf_store)
    graph = build_graph(
        store=pdf_store,
        model=GenModel(),
        k=2,
        grader=make_grader(True),
        wiki_store=wiki_store,
        wiki_dir=tmp_path,
        reflector=make_reflector(ReflectVerdict(worth=False, title="闲聊", summary="")),
    )
    frames = drain(graph)

    assert nodes(frames) == ["retrieve", "grade", "generate", "reflect"]
    assert not any(f.get("node") == "write_wiki" for f in frames)
    assert load_entries(tmp_path) == []
    assert wiki_store._collection.count() == 0


def test_fallback_answer_never_writes(pdf_store, wiki_store, tmp_path):
    graph = build_graph(
        store=pdf_store,
        model=GenModel(),
        k=2,
        grader=make_grader(False),  # 永远不相关 → 兜底
        wiki_store=wiki_store,
        wiki_dir=tmp_path,
        reflector=make_reflector(ReflectVerdict(worth=True, title="t", summary="")),
    )
    frames = drain(graph)

    assert nodes(frames)[-1] == "generate"
    assert not any(f.get("node") in ("reflect", "write_wiki") for f in frames)
    assert load_entries(tmp_path) == []


# ── API 层：GET /wiki 与 DELETE /wiki/{slug} ───────────────
def test_api_list_and_delete(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app

    s = get_settings()
    monkeypatch.setattr(type(s), "wiki_path", property(lambda self: tmp_path))

    entry = WikiEntry(
        slug=slugify("差旅报销"),
        title="差旅报销",
        question="要交什么材料",
        answer="发票原件与行程单。",
        sources=["hr.pdf"],
        created_at="2026-10-30 10:00:00",
    )
    write_entry(tmp_path, entry)
    client = TestClient(app)

    body = client.get("/api/wiki").json()
    assert body["total"] == 1
    assert body["entries"][0]["slug"] == entry.slug
    assert body["entries"][0]["sources"] == ["hr.pdf"]

    def _no_store(*_a, **_k):
        raise RuntimeError("embedding 未配置")

    monkeypatch.setattr("app.rag.embeddings.make_embeddings", _no_store)
    res = client.delete(f"/api/wiki/{entry.slug}")
    assert res.status_code == 200
    assert res.json()["deleted"] is True
    assert client.get("/api/wiki").json()["total"] == 0
