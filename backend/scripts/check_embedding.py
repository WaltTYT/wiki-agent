"""Embedding 选型冒烟测试（对应 .doc/plan.md §0 决策 5a）。不依赖 FastAPI，直接跑：

    conda activate langchain1.2
    cd backend
    python scripts/check_embedding.py

判定标准：4 条中文查询里，正确文档必须排第 1；否则换 embedding 模型再跑。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag.vectorstore import build_store  # noqa: E402  复用同一套 cosine + 空间自检

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

COLLECTION = "check_embedding"
PERSIST = "./.chroma_check"

# (文本, 正确标签)
CORPUS = [
    ("员工每年享有 15 天带薪年假，入职满三年增加至 20 天。", "hr-leave"),
    ("向量数据库用余弦相似度在嵌入空间里查找语义最接近的文本块。", "vector-db"),
    ("FastAPI 的 StreamingResponse 配合异步生成器可以逐块返回 HTTP 响应。", "streaming"),
    ("公司报销差旅费需提供发票原件，审批周期为五个工作日。", "hr-expense"),
]

# (查询, 期望命中的标签)
QUERIES = [
    ("年假有几天", "hr-leave"),
    ("怎么把响应一段段发给前端", "streaming"),
    ("发票和报销", "hr-expense"),
    ("语义检索是怎么找相似文本的", "vector-db"),
]


def build_embeddings() -> OpenAIEmbeddings:
    model = os.getenv("EMBEDDING_MODEL")
    key = os.getenv("EMBEDDING_API_KEY")
    base = os.getenv("EMBEDDING_BASE_URL")
    if not (model and key and base):
        sys.exit("[X] .env 里 EMBEDDING_MODEL / EMBEDDING_API_KEY / EMBEDDING_BASE_URL 没填全")
    print(f"[i] embedding model = {model}")
    print(f"[i] base_url        = {base}")
    # 复用生产工厂，避免脚本与 app 行为不一致（tokenize=False 等约束只维护一处）
    from app.rag.embeddings import make_embeddings

    return make_embeddings()


def main() -> None:
    t0 = time.time()
    # 走 build_store：强制 cosine + 空间自检，避免与生产代码行为不一致
    db = build_store(build_embeddings(), PERSIST, COLLECTION)
    db.reset_collection()
    docs = [Document(page_content=text, metadata={"id": tag}) for text, tag in CORPUS]
    db.add_documents(docs, ids=[tag for _, tag in CORPUS])
    print(f"[i] 入库 {len(docs)} 条，耗时 {time.time() - t0:.1f}s\n")

    ok = 0
    for query, expect in QUERIES:
        hits = db.similarity_search_with_relevance_scores(query, k=2)
        got = [h.metadata.get("id") for h, _ in hits]
        score = float(hits[0][1]) if hits else 0.0
        good = bool(got) and got[0] == expect
        ok += int(good)
        print(f"  {'PASS' if good else 'FAIL'}  Q={query!r}  top1={got[0] if got else '-'} ({score:.3f})  期望={expect}")

    print(f"\n结果: {ok}/{len(QUERIES)} 命中第一")
    if ok < len(QUERIES):
        sys.exit("[X] embedding 中文检索不达标，换模型再跑（候选见 plan §0 决策 5a）")
    print("[OK] 该 embedding 可用于中文语料，进入 plan §2.1")


if __name__ == "__main__":
    main()
