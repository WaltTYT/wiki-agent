"""Prompt 集中管理（V1 的回答、V2 的 grade/rewrite、V3 的 reflect 都放这里）。"""
from __future__ import annotations

RAG_SYSTEM = (
    "你是企业知识库问答助手。严格遵守：\n"
    "1. 只依据【资料】回答，资料里没有的必须明确说「当前资料未覆盖该问题」，禁止编造或凭常识补充。\n"
    "2. 回答要简短直接，中文，不要复述资料原文。\n"
    "3. 若资料彼此矛盾，指出矛盾而不是自行取舍。"
)


def build_context(chunks: list[str]) -> str:
    if not chunks:
        return "（本次没有检索到任何资料）"
    return "\n\n".join(f"[资料 {i + 1}] {t}" for i, t in enumerate(chunks))


def build_messages(question: str, chunks: list[str]) -> list[tuple[str, str]]:
    return [
        ("system", RAG_SYSTEM),
        ("user", f"【资料】\n{build_context(chunks)}\n\n【问题】\n{question}"),
    ]


# ── V2.0 Grade：判断检索结果能否回答问题 ────────────────────
GRADE_SYSTEM = (
    "你是检索相关性审核员，只做判断，不回答问题。\n"
    "判断标准：【资料】中至少一段直接包含回答【问题】所需的事实才算相关；"
    "只是主题相近、泛泛提及、或只能靠常识补全的，一律算不相关。"
)

GRADE_HUMAN = "【问题】\n{question}\n\n【资料】\n{context}"


def build_grade_messages(question: str, chunks: list[str]) -> list[tuple[str, str]]:
    return [
        ("system", GRADE_SYSTEM),
        ("user", GRADE_HUMAN.format(question=question, context=build_context(chunks))),
    ]


# ── V2.0 Rewrite：检索失败后把问题改写得更利于召回 ──────────
REWRITE_SYSTEM = (
    "你是检索查询改写器。把用户问题改写成一句更利于向量检索的查询：\n"
    "1. 补全省略的主语/宾语，展开同义词与上下位词（如「报销」→「差旅报销 发票 审批」）；\n"
    "2. 保留原意，不回答问题，不添加资料里可能没有的事实；\n"
    "3. 只输出改写后的查询本身，不要引号、编号或任何解释。"
)

REWRITE_HUMAN = "【原问题】\n{question}\n{previous}"


def build_rewrite_messages(question: str, previous_query: str | None = None) -> list[tuple[str, str]]:
    previous = f"\n【上次检索未命中的查询】\n{previous_query}" if previous_query else ""
    return [
        ("system", REWRITE_SYSTEM),
        ("user", REWRITE_HUMAN.format(question=question, previous=previous)),
    ]


# 重写次数用尽仍不相关时的兜底话术（不调 LLM，直接流给前端）
FALLBACK_ANSWER = (
    "当前资料未覆盖该问题（已自动改写检索词重试，仍未找到相关依据）。"
    "建议补充相关文档后再问，或换一种说法。"
)