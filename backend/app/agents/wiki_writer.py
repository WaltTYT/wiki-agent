"""V3.0 记忆写入：Reflect 判断价值 → 落盘 md + upsert wiki_docs（plan §4.1）。

契约与 V2 的 Grader 一致：节点逻辑通过闭包注入 `reflector`，离线测试可整条替换，
不需要真的联网调模型。`make_reflector` 失败（provider 不支持 tool calling、网络抖动）
一律返回 None —— 宁可不沉淀，也不要把兜底话术或半成品写进记忆。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, Field

from ..rag.wiki import (
    WikiEntry,
    find_similar_slug,
    load_entries,
    read_entry,
    slugify,
    timestamp,
    upsert_entry,
    write_entry,
)
from ..rag.vectorstore import Hit
from .prompts import build_reflect_messages


class ReflectVerdict(BaseModel):
    """Reflect 节点的结构化输出。"""

    worth: bool = Field(description="本轮问答是否值得沉淀为长期记忆")
    title: str = Field(default="", description="不超过 20 字的记忆标题")
    summary: str = Field(default="", description="一句话摘要，便于列表展示")


# reflector 契约：返回 None 表示「本轮不沉淀」，异常也必须收敛成 None。
Reflector = Callable[[str, str, Sequence[Hit]], Awaitable[ReflectVerdict | None]]


def make_reflector(model) -> Reflector:
    """默认 reflector：LLM 结构化判断，失败即放弃写入。"""

    async def reflect(question: str, answer: str, hits: Sequence[Hit]) -> ReflectVerdict | None:
        if not answer.strip() or not hits:
            return None
        try:
            # 与 Grade 相同：显式 function_calling，兼容千问/智谱的 OpenAI 兼容层
            judge = model.with_structured_output(ReflectVerdict, method="function_calling")
            verdict = await judge.ainvoke(
                build_reflect_messages(question, answer, [h.text for h in hits])
            )
            if isinstance(verdict, dict):
                return ReflectVerdict(**verdict)
            return verdict
        except Exception:  # noqa: BLE001 沉淀失败不能影响已生成的回答
            return None

    return reflect


def _source_label(hit: Hit) -> str:
    return f"{hit.source}#{hit.page}" if hit.page else hit.source


def _merge_sources(old: Sequence[str], new: Sequence[str]) -> list[str]:
    out: list[str] = []
    for s in [*old, *new]:
        if s and s not in out:
            out.append(s)
    return out


def persist_wiki(
    *,
    store,
    wiki_dir: Path | str,
    verdict: ReflectVerdict,
    question: str,
    answer: str,
    hits: Sequence[Hit],
    dedupe_threshold: float,
) -> tuple[str, bool]:
    """写入一条记忆，返回 (slug, 是否合并了已有条目)。

    去重规则（plan §4.1）：标题向量相似度过阈值 → 复用已有 slug 并合并来源；
    否则按标题哈希新建。同名文件覆盖（答案取最新一轮）。
    """
    wiki_dir = Path(wiki_dir)
    title = (verdict.title or question).strip()[:60] or question[:60]

    # 去重三道闸：① 同一问题文本 → 直接复用；② 标题向量相似度 → 复用；③ 否则新建。
    entries = load_entries(wiki_dir)
    same_question = next((e for e in entries if e.question.strip() == question.strip()), None)
    similar = find_similar_slug(store, title, dedupe_threshold)
    slug = same_question.slug if same_question else (similar or slugify(title))

    existing_path = wiki_dir / f"{slug}.md"
    existing = same_question if same_question else (read_entry(existing_path) if existing_path.exists() else None)

    now = timestamp()
    sources = _merge_sources(existing.sources if existing else [], [_source_label(h) for h in hits])
    entry = WikiEntry(
        slug=slug,
        title=title if not existing else (existing.title or title),
        question=existing.question if existing and existing.question else question,
        answer=answer.strip(),
        sources=sources,
        summary=verdict.summary.strip(),
        created_at=existing.created_at if existing and existing.created_at else now,
        updated_at=now,
    )

    write_entry(wiki_dir, entry)
    if store is not None:
        try:
            upsert_entry(store, entry)
        except Exception:  # noqa: BLE001 md 已落盘，向量同步失败只影响「下次优先命中」
            pass
    return slug, similar is not None or existing is not None
