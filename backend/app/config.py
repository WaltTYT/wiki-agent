"""集中配置：读 backend/.env，路径一律相对 backend/ 解析。

支持多个模型 Provider（千问 / 智谱 GLM / …），前端可切换。
单 Provider 的老写法（LLM_BASE_URL + LLM_MODEL + LLM_MODELS）仍然有效，
会自动折叠成一个 id=default 的 Provider，不必改配置。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class ProviderSpec(BaseModel):
    """一个上游服务：base_url + key + 它名下可切换的模型。"""

    id: str
    label: str = ""
    base_url: str = ""
    api_key: str = ""
    models: list[str] = Field(default_factory=list)
    # 千问 qwen3.8 系列默认会思考，需要显式传 enable_thinking；
    # 智谱 glm-4-flash 之流不认识这个参数，多传可能被拒，故可按 provider 关掉。
    supports_thinking: bool = True

    @property
    def display(self) -> str:
        return self.label or self.id


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 单 Provider 老写法（也用来指定默认模型）----
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_models: str = ""
    llm_temperature: float = 0.0
    llm_enable_thinking: bool = False

    # ---- 多 Provider 写法：JSON 数组，见 .env.example ----
    llm_providers: list[ProviderSpec] = []

    # ---- Embedding（决策 5a：不允许缺省，缺省即 raise）----
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model: str = ""
    embedding_batch_size: int = 10

    # ---- 数据路径 ----
    chroma_path: str = "../data/chroma"
    pdf_dir: str = "../data/pdfs"
    wiki_dir: str = "../data/wiki"

    # ---- 检索与 Agent 行为 ----
    retrieval_k: int = 4
    wiki_sim_threshold: float = 0.68
    # 标题向量相似度达到该值就视为同一条记忆，合并来源而不是新增（plan §4.1 去重）
    wiki_dedupe_threshold: float = 0.92
    chunk_size: int = 800
    chunk_overlap: int = 150
    max_rewrites: int = 2

    # ---- Provider 解析 ----
    @property
    def providers(self) -> list[ProviderSpec]:
        if self.llm_providers:
            return self.llm_providers
        if not (self.llm_base_url and self.llm_api_key):
            return []
        legacy = ProviderSpec(
            id="default",
            label="默认",
            base_url=self.llm_base_url,
            api_key=self.llm_api_key,
            models=self.model_choices,
            supports_thinking=True,
        )
        return [legacy]

    @property
    def model_choices(self) -> list[str]:
        """候选模型 = 默认模型 + LLM_MODELS（去重保序），默认排第一。"""
        out: list[str] = []
        for name in [self.llm_model, *[x.strip() for x in self.llm_models.split(",")]]:
            if name and name not in out:
                out.append(name)
        return out

    @property
    def all_models(self) -> list[str]:
        """所有 provider 名下模型的扁平列表（保序去重），默认模型排第一。"""
        out: list[str] = []
        for p in self.providers:
            for m in p.models:
                if m and m not in out:
                    out.append(m)
        for m in self.model_choices:
            if m not in out:
                out.insert(0, m)
        return out

    def provider_of(self, model: str | None) -> ProviderSpec | None:
        if not model:
            return None
        for p in self.providers:
            if model in p.models:
                return p
        return None

    @property
    def default_provider(self) -> ProviderSpec | None:
        return self.provider_of(self.llm_model) or (self.providers[0] if self.providers else None)

    def resolve_credential(self, model: str | None) -> tuple[str, str]:
        """返回 (api_key, base_url)：模型属于哪个 provider 就用谁的凭证。"""
        p = self.provider_of(model) or self.default_provider
        if p is None:
            raise RuntimeError("LLM 未配置：请在 .env 填写 LLM_BASE_URL/LLM_API_KEY/LLM_MODEL 或 LLM_PROVIDERS")
        return p.api_key, p.base_url

    # ---- 路径 ----
    def resolve(self, value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else (BACKEND_DIR / p).resolve()

    @property
    def chroma_dir(self) -> Path:
        return self.resolve(self.chroma_path)

    @property
    def pdf_path(self) -> Path:
        return self.resolve(self.pdf_dir)

    @property
    def wiki_path(self) -> Path:
        return self.resolve(self.wiki_dir)


@lru_cache
def get_settings() -> Settings:
    return Settings()