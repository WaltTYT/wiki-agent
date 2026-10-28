"""Embedding 工厂。

决策 5a（实测硬约束）：Chroma 不显式传 embedding_function 时会静默使用英文模型
all-MiniLM-L6-v2，中文语料 4 条查询实测仅 1 条命中，等于检索层白做。
因此这里禁止任何静默降级：配置不全直接 RuntimeError。
"""
from __future__ import annotations

import hashlib
import math

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from ..config import get_settings

_DIM = 512


def make_embeddings() -> OpenAIEmbeddings:
    s = get_settings()
    missing = [
        name
        for name, val in (
            ("EMBEDDING_MODEL", s.embedding_model),
            ("EMBEDDING_API_KEY", s.embedding_api_key),
            ("EMBEDDING_BASE_URL", s.embedding_base_url),
        )
        if not val
    ]
    if missing:
        raise RuntimeError(
            "Embedding 未配置：" + ", ".join(missing)
            + " 为空。请复制 backend/.env.example 为 backend/.env 并填写（见 plan §0 决策 5a）。"
            " 严禁回落到 Chroma 默认英文 embedding。"
        )
    # check_embedding_ctx_length=False 是实测必需（langchain-openai 1.7.3）：
    # 默认 True 时走 _get_len_safe_embeddings -> _tokenize，把文本编码成 token id 数组再发送，
    # OpenAI 官方能吃，千问 AI 平台兼容层会返回
    #   400 InternalError.Algo.InvalidParameter: input must be an array of strings
    # 关掉后源码里直接 input=texts[...] 发原始字符串（同步/异步两条路径都该分支）。
    # 注意：不要用 tokenize=False —— 该版本没有这个字段；真正的开关是 tiktoken_enabled，
    # 但它 False 会转去依赖 HuggingFace transformers（本项目未安装），所以只关 ctx_length。
    return OpenAIEmbeddings(
        model=s.embedding_model,
        api_key=s.embedding_api_key,
        base_url=s.embedding_base_url,
        check_embedding_ctx_length=False,
        # 分批发送，避免一次塞太多文本触发平台 input 长度上限
        chunk_size=s.embedding_batch_size,
    )


class CharBigramHashEmbeddings(Embeddings):
    """离线确定性 embedding，仅用于测试与骨架自检（不具备真实语义能力）。

    做法：中文按字符 bigram + 英文按空格切词，token 哈希到固定维度后 L2 归一化。
    字面重叠越多 → 余弦越接近 1，足以验证向量库的 space / 阈值 / 幂等逻辑。
    """

    dim: int = _DIM

    def _tokens(self, text: str) -> list[str]:
        text = text.strip()
        out: list[str] = []
        for i in range(len(text) - 1):
            out.append(text[i : i + 2])
        if len(text) == 1:
            out.append(text)
        return out or ["<empty>"]

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in self._tokens(text):
            h = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            sign = 1.0 if h[4] % 2 == 0 else -1.0
            v[idx] += sign
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)

