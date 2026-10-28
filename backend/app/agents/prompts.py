"""Prompt 集中管理（V1 只有一组，V2/V3 的 grade/rewrite/reflect 也放这里）。"""
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