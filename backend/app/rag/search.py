"""检索 CLI：不依赖 FastAPI，先验证「PDF → Chroma → 命中」最短链路（plan §2.1 冒烟项）。

    python -m app.rag.search "带薪年假有几天"
"""
from __future__ import annotations

import argparse
import sys


def _force_utf8_stdout() -> None:
    """Windows GBK 控制台打印中文会 UnicodeEncodeError，这里统一切到 UTF-8。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from ..config import get_settings
from .embeddings import make_embeddings
from .vectorstore import PDF_COLLECTION, build_store, search


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    s = get_settings()
    ap = argparse.ArgumentParser(description="向量检索冒烟")
    ap.add_argument("query")
    ap.add_argument("--k", type=int, default=s.retrieval_k)
    ap.add_argument("--chroma", default=str(s.chroma_dir))
    ap.add_argument("--collection", default=PDF_COLLECTION)
    args = ap.parse_args(argv)

    store = build_store(make_embeddings(), args.chroma, args.collection)
    if store._collection.count() == 0:
        print("[X] 集合为空，先跑 python -m app.rag.ingest", file=__import__("sys").stderr)
        return 1
    for i, h in enumerate(search(store, args.query, args.k), 1):
        loc = f" p{h.page}" if h.page else ""
        print(f"  {i}. [{h.score:.3f}] {h.source}{loc}  {h.text[:60].replace(chr(10), ' ')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
