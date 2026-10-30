"""V3 记忆层：Wiki 条目落盘（一篇一 md + 索引）与 wiki_docs 向量检索（plan §4.1）。

两条存储互为镜像：
- `data/wiki/{slug}.md` 是人类可读、可版本管理的事实来源（frontmatter + 正文）；
- Chroma 的 `wiki_docs` collection 负责「下次优先检索」，page_content 存答案正文。

为什么 slug 用「日期 + 标题哈希」而不是中文标题：
1. 文件名只含 `[a-z0-9-]`，API 与删除接口可以白名单校验，杜绝路径穿越；
2. 同一标题哈希稳定 → 天然去重；标题写在 frontmatter 里，不影响可读性。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document

from .vectorstore import Hit, clamp01

INDEX_NAME = "index.md"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,80}$")
_FRONT_KEYS = ("title", "question", "slug", "created_at", "updated_at", "sources", "summary")


@dataclass
class WikiEntry:
    """一条沉淀记忆。sources 里存「文件名」或「文件名#页码」。"""

    slug: str
    title: str
    question: str
    answer: str
    sources: list[str] = field(default_factory=list)
    summary: str = ""
    created_at: str = ""
    updated_at: str = ""


def timestamp(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def slugify(title: str) -> str:
    """标题 sha1 前 10 位；同标题永远同 slug，跨天也不会重复建文件。

    时间只写在 frontmatter 的 created_at 里 —— 如果把日期塞进 slug，
    昨天沉淀的同一问题会在今天生成第二个文件，去重就失效了。
    """
    digest = hashlib.sha1(title.strip().encode("utf-8")).hexdigest()[:10]
    return digest


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def render_md(entry: WikiEntry) -> str:
    head = [
        "---",
        f"title: {_one_line(entry.title)}",
        f"question: {_one_line(entry.question)}",
        f"slug: {entry.slug}",
        f"created_at: {entry.created_at}",
        f"updated_at: {entry.updated_at or entry.created_at}",
        f"summary: {_one_line(entry.summary)}",
        f"sources: {json.dumps(entry.sources, ensure_ascii=False)}",
        "---",
        "",
        f"# {entry.title}",
        "",
        "## 问题",
        "",
        entry.question,
        "",
        "## 答案",
        "",
        entry.answer,
        "",
    ]
    return "\n".join(head)


def _parse_md(text: str, fallback_slug: str) -> WikiEntry | None:
    """解析 frontmatter；正文按「## 答案」切割，格式损坏时返回 None 而不是抛异常。"""
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("\n---\n", 1)
        if len(parts) == 2:
            raw_head, body = parts[0][3:], parts[1]
            for line in raw_head.splitlines():
                key, _, val = line.partition(":")
                if key.strip() in _FRONT_KEYS:
                    meta[key.strip()] = val.strip()
    if not meta:
        return None
    sources: list[str] = []
    try:
        parsed = json.loads(meta.get("sources", "[]"))
        if isinstance(parsed, list):
            sources = [str(x) for x in parsed]
    except Exception:  # 手改坏 sources 不该让整条记忆消失
        sources = []

    answer = ""
    if "## 答案" in body:
        answer = body.split("## 答案", 1)[1].strip()
    else:
        answer = body.strip()
    return WikiEntry(
        slug=meta.get("slug") or fallback_slug,
        title=meta.get("title") or meta.get("question") or fallback_slug,
        question=meta.get("question") or "",
        answer=answer,
        sources=sources,
        summary=meta.get("summary") or "",
        created_at=meta.get("created_at") or "",
        updated_at=meta.get("updated_at") or meta.get("created_at") or "",
    )


def read_entry(path: Path) -> WikiEntry | None:
    try:
        return _parse_md(Path(path).read_text(encoding="utf-8", errors="replace"), Path(path).stem)
    except Exception:
        return None


def load_entries(wiki_dir: Path) -> list[WikiEntry]:
    """读取全部条目（按创建时间倒序），index.md 不算条目。"""
    wiki_dir = Path(wiki_dir)
    if not wiki_dir.exists():
        return []
    entries = []
    for path in wiki_dir.glob("*.md"):
        if path.name == INDEX_NAME:
            continue
        entry = read_entry(path)
        if entry:
            entries.append(entry)
    entries.sort(key=lambda e: e.created_at, reverse=True)
    return entries


def rebuild_index(wiki_dir: Path) -> None:
    """重写 index.md：开箱即可在编辑器/仓库里看到记忆清单。"""
    wiki_dir = Path(wiki_dir)
    wiki_dir.mkdir(parents=True, exist_ok=True)
    entries = load_entries(wiki_dir)
    lines = ["# Wiki 索引", "", f"共 {len(entries)} 条沉淀记忆（按创建时间倒序）", ""]
    for e in entries:
        lines.append(f"- [{e.title or e.slug}]({e.slug}.md) — {e.created_at}")
    lines.append("")
    (wiki_dir / INDEX_NAME).write_text("\n".join(lines), encoding="utf-8")


def write_entry(wiki_dir: Path, entry: WikiEntry) -> Path:
    wiki_dir = Path(wiki_dir)
    wiki_dir.mkdir(parents=True, exist_ok=True)
    path = wiki_dir / f"{entry.slug}.md"
    path.write_text(render_md(entry), encoding="utf-8")
    rebuild_index(wiki_dir)
    return path


def delete_entry(wiki_dir: Path, slug: str) -> bool:
    if not SLUG_RE.match(slug):
        raise ValueError(f"非法 slug: {slug!r}")
    path = Path(wiki_dir) / f"{slug}.md"
    existed = path.exists()
    if existed:
        path.unlink()
    rebuild_index(wiki_dir)
    return existed


def _wiki_doc(entry: WikiEntry) -> Document:
    return Document(
        page_content=entry.answer,
        metadata={
            "slug": entry.slug,
            "title": entry.title,
            "question": entry.question,
            "summary": entry.summary,
            "sources": json.dumps(entry.sources, ensure_ascii=False),
            "created_at": entry.created_at,
            "source": f"wiki/{entry.slug}.md",
        },
    )


def upsert_entry(store: Chroma, entry: WikiEntry) -> None:
    """同 slug 先删后加：langchain-chroma 的 add 重复 id 行为不稳定，删除是幂等的。"""
    try:
        store.delete(ids=[entry.slug])
    except Exception:  # 首次写入时 collection 为空，delete 可能报错，忽略
        pass
    store.add_documents([_wiki_doc(entry)], ids=[entry.slug])


def find_similar_slug(store: Chroma | None, title: str, threshold: float) -> str | None:
    """标题向量比对：相似度过阈值就返回已有 slug，用于「更新而非新增」。"""
    if store is None or not title.strip():
        return None
    try:
        if store._collection.count() == 0:
            return None
        raw = store.similarity_search_with_relevance_scores(title, k=1)
    except Exception:
        return None
    if not raw:
        return None
    doc, score = raw[0]
    meta = doc.metadata or {}
    if clamp01(score) >= threshold and meta.get("slug"):
        return str(meta["slug"])
    return None


def search_wiki(store: Chroma | None, query: str, k: int = 1, min_score: float = 0.0) -> list[Hit]:
    """wiki_docs 优先检索；低于阈值的命中直接丢弃，让调用方回落 PDF。"""
    if store is None:
        return []
    try:
        if store._collection.count() == 0:
            return []
        raw = store.similarity_search_with_relevance_scores(query, k=k)
    except Exception:  # 记忆层坏了也不该拖垮问答，安静回落到 PDF
        return []
    hits: list[Hit] = []
    for doc, score in raw:
        s = clamp01(score)
        if s < min_score:
            continue
        meta = doc.metadata or {}
        slug = str(meta.get("slug") or "")
        source = str(meta.get("source") or f"wiki/{slug}.md")
        # 验收标准要求来源显式标注 wiki/...
        if not source.startswith("wiki/"):
            source = "wiki/" + Path(source).name
        hits.append(Hit(text=doc.page_content, source=source, page=None, score=s, kind="wiki"))
    return hits
