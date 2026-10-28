"""入库 CLI（幂等）。

    conda activate langchain1.2
    cd backend
    python -m app.rag.ingest                     # 用 .env 里的 PDF_DIR / CHROMA_PATH
    python -m app.rag.ingest --pdf-dir ../data/pdfs
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
import time

from ..config import get_settings
from .embeddings import make_embeddings
from .loader import load_dir
from .vectorstore import PDF_COLLECTION, add_documents, build_store, reset_collection


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    s = get_settings()
    ap = argparse.ArgumentParser(description="PDF → Chroma 入库")
    ap.add_argument("--pdf-dir", default=str(s.pdf_path))
    ap.add_argument("--chroma", default=str(s.chroma_dir))
    ap.add_argument("--collection", default=PDF_COLLECTION)
    ap.add_argument("--kinds", default="pdf,text", help="要读哪些语料：pdf / text / pdf,text")
    ap.add_argument("--chunk-size", type=int, default=s.chunk_size)
    ap.add_argument("--chunk-overlap", type=int, default=s.chunk_overlap)
    ap.add_argument("--limit", type=int, default=0, help="只入库前 N 个 chunk（0=全部），大 PDF 试跑用")
    args = ap.parse_args(argv)

    t0 = time.time()
    kinds = tuple(x.strip() for x in args.kinds.split(",") if x.strip())
    docs = load_dir(args.pdf_dir, args.chunk_size, args.chunk_overlap, kinds)
    if not docs:
        print(f"[X] 在 {args.pdf_dir} 没找到语料（PDF/文本），先放文件进去（plan §7 第 3 步）", file=sys.stderr)
        return 1
    total = len(docs)
    if args.limit and args.limit < total:
        docs = docs[: args.limit]
        print(f"[i] 抽取到 {total} 个 chunk，按 --limit 只入库前 {len(docs)} 个")
    print(f"[i] 抽取切分得到 {len(docs)} 个 chunk（{time.time() - t0:.1f}s）")

    store = build_store(make_embeddings(), args.chroma, args.collection)
    reset_collection(store)
    n = add_documents(store, docs, ids=[d.metadata["chunk_id"] for d in docs])
    print(f"[OK] 已入库 {n} 条 → collection={args.collection} @ {args.chroma}")
    print(f"[i] 集合总数 {store._collection.count()} / space={store._collection.configuration['hnsw']['space']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
