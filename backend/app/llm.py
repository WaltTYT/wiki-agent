"""对话模型工厂（多 Provider）。

实测约束（2026-10-28）：
- 千问 qwen3.8-flash / qwen3.8-max **默认就会返回 reasoning_content**，需要显式
  `extra_body={"enable_thinking": False}` 关掉（省延迟与 token）。
  注意必须走 extra_body：放 model_kwargs 会被 openai SDK 当具名参数拒收。
- 智谱 glm-4-flash 的流式 delta 只有 content/role（无思考字段），
  而且不认 enable_thinking，所以按 provider 的 supports_thinking 决定是否下发。
"""
from __future__ import annotations

from langchain_openai import ChatOpenAI

from .config import get_settings


def make_chat_model(thinking: bool | None = None, *, model: str | None = None) -> ChatOpenAI:
    s = get_settings()
    use_model = model or s.llm_model
    if not use_model:
        raise RuntimeError("LLM 未配置：请在 backend/.env 填写 LLM_MODEL 或 LLM_PROVIDERS")
    api_key, base_url = s.resolve_credential(use_model)
    if not (api_key and base_url):
        raise RuntimeError(f"Provider 缺少 api_key / base_url（模型 {use_model}）")

    provider = s.provider_of(use_model) or s.default_provider
    kwargs: dict = {}
    if provider is not None and provider.supports_thinking:
        use_thinking = s.llm_enable_thinking if thinking is None else thinking
        kwargs["extra_body"] = {"enable_thinking": bool(use_thinking)}

    return ChatOpenAI(
        model=use_model,
        api_key=api_key,
        base_url=base_url,
        temperature=s.llm_temperature,
        streaming=True,
        **kwargs,
    )