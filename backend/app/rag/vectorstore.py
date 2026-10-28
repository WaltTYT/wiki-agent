"""Chroma 向量库封装：PDF 语料与 Wiki 记忆两个 collection。

三条实测约束（chromadb 1.5.9 + langchain-chroma 1.1.0，见 .doc/plan.md §1.5）：
1. 不指定 space 时默认 **l2**，`similarity_search_with_relevance_scores` 会返回负数并告警，
   阈值判断整体失真 → 建集合必须显式传 collection_metadata={"hnsw:space": "cosine"}。
2. cosine 下 `similarity_search_with_score` 返回的是**距离**（= 1 - 相似度），
   而 relevance_scores 是相似度；两者量纲相反，代码里统一只用 relevance。
3. 实测 relevance 可能略低于 0（见过 -0.017），因此一律 clamp 到 [0, 1] 再和阈值比较。

另外集合名有硬约束：3–512 字符、只能 [a-zA-Z0-9._-]、首尾必须是字母或数字
（实测 "t1" 会被 InvalidArgumentError 拒绝）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

PDF_COLLECTION = "pdf_docs"
WIKI_COLLECTION = "wiki_docs"
COSINE = {"hnsw:space": "cosine"}


def build_store(
    embeddings: Embeddings,
    persist_dir: str,
    collection_name: str = PDF_COLLECTION,
) -> Chroma:
    """构建向量库；显式锁定 cosine 并自检，防止版本升级后静默退回 l2。"""
    if len(collection_name) < 3 or not collection_name[0].isalnum() or not collection_name[-1].isalnum():
        raise ValueError(f"非法 collection 名: {collection_name!r}（需 3-512 字符，首尾为字母/数字）")
    store = Chroma(
        collection_name=collection_name,
        persist_directory=persist_dir,
        embedding_function=embeddings,
        collection_metadata=dict(COSINE),
    )
    space = store._collection.configuration["hnsw"]["space"]
    if space != "cosine":
        raise RuntimeError(f"向量库 space 异常：期望 cosine，实际 {space!r}（chromadb 行为可能已变）")
    return store


def reset_collection(store: Chroma) -> None:
    """删掉集合并重建，保证入库幂等（重复 ingest 不会产生重复 chunk）。

    注意：langchain_chroma 的重建方法是私有 `__ensure_collection`，在类外直接写
    `store.__ensure_collection()` 会被 Python 名字改写（name mangling）成
    `_Chroma__ensure_collection` 而 AttributeError → 必须用 getattr 显式取真名。
    """
    name = store._collection.name
    store._client.delete_collection(name)
    getattr(store, "_Chroma__ensure_collection")()


@dataclass(frozen=True)
class Hit:
    text: str
    source: str
    page: int | None
    score: float
    kind: str = "pdf"

    def as_dict(self) -> dict:
        return {"kind": self.kind, "source": self.source, "page": self.page, "score": round(self.score, 4), "text": self.text}


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def search(store: Chroma, query: str, k: int = 4, kind: str = "pdf") -> list[Hit]:
    raw = store.similarity_search_with_relevance_scores(query, k=k)
    hits: list[Hit] = []
    for doc, score in raw:
        meta = doc.metadata or {}
        page = meta.get("page")
        hits.append(
            Hit(
                text=doc.page_content,
                source=Path(str(meta.get("source", "unknown"))).name,
                page=int(page) + 1 if isinstance(page, (int, float)) else None,
                score=clamp01(score),
                kind=kind,
            )
        )
    return hits


def add_documents(store: Chroma, docs: list[Document], ids: list[str] | None = None) -> int:
    if not docs:
        return 0
    store.add_documents(docs, ids=ids)
    return len(docs)
