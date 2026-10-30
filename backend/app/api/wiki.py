"""/wiki：记忆条目列表与删除（plan §4.1 第 6 项 + §5「wiki 可人工删」）。

- GET    /wiki         读 data/wiki/*.md（md 是事实来源，前端侧栏展示）
- DELETE /wiki/{slug}  删 md + 同步删除 wiki_docs 里的向量，避免「删了还命中」

删除时向量库不可用（未配置 embedding / chroma 损坏）只影响向量同步，
md 文件仍会被删掉 —— 记一次 warn，不返回 500。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..config import get_settings
from ..rag.wiki import SLUG_RE, delete_entry, load_entries
from ..schemas import WikiEntryInfo, WikiListResponse

router = APIRouter()


@router.get("/wiki", response_model=WikiListResponse)
def list_wiki() -> WikiListResponse:
    s = get_settings()
    entries = load_entries(Path(s.wiki_path))
    items = [
        WikiEntryInfo(
            slug=e.slug,
            title=e.title,
            question=e.question,
            answer=e.answer,
            summary=e.summary,
            sources=list(e.sources),
            created_at=e.created_at,
            updated_at=e.updated_at,
        )
        for e in entries
    ]
    return WikiListResponse(entries=items, total=len(items))


@router.delete("/wiki/{slug}")
def remove_wiki(slug: str) -> dict:
    if not SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail=f"非法 slug: {slug!r}")
    s = get_settings()
    removed = delete_entry(Path(s.wiki_path), slug)
    vector_removed = False
    try:
        from ..rag.embeddings import make_embeddings
        from ..rag.vectorstore import WIKI_COLLECTION, build_store

        store = build_store(make_embeddings(), str(s.chroma_dir), WIKI_COLLECTION)
        store.delete(ids=[slug])
        vector_removed = True
    except Exception:  # noqa: BLE001 向量同步失败不影响删文件
        pass
    if not removed and not vector_removed:
        raise HTTPException(status_code=404, detail=f"没有这条记忆: {slug}")
    return {"slug": slug, "deleted": removed, "vector_deleted": vector_removed}
