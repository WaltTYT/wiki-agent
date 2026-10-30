"""入库 CLI（幂等）。

    conda activate langchain1.2
    cd backend
    python -m app.rag.ingest                     # 用 .env 里的 PDF_DIR / CHROMA_PATH
    python -m app.rag.ingest --pdf-dir ../data/pdfs
    python -m app.rag.ingest --if-changed        # 语料没变就跳过（start.bat 默认用它）

`--if-changed` 用一份指纹（文件名 + 大小 + mtime + 切分参数）判断，指纹存在
chroma 目录的 corpus_stamp.json；集合为空或指纹不一致才真正重建。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def _force_utf8_stdout() -> None:
    """Windows GBK 控制台打印中文会 UnicodeEncodeError，这里统一切到 UTF-8。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import time

from ..config import get_settings
from .embeddings import make_embeddings
from .loader import list_corpus_files, load_dir
from .vectorstore import PDF_COLLECTION, add_documents, build_store, reset_collection


def corpus_digest(root, kinds: tuple[str, ...], chunk_size: int, chunk_overlap: int) -> tuple[str, int]:
    """语料指纹：(sha256, 文件数)。文件按路径排序，含大小与 mtime，避免新增/替换漏判。"""
    rows = []
    for f in list_corpus_files(root, kinds):
        st = f.stat()
        rows.append([f.relative_to(root).as_posix(), st.st_size, int(st.st_mtime)])
    rows.sort()
    payload = json.dumps(
        {"files": rows, "chunk": [chunk_size, chunk_overlap]}, ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest(), len(rows)


def read_stamp(path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # 缺失/损坏一律视为“需要重建”
        return {}


def write_stamp(path, digest: str, n_files: int, n_chunks: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "digest": digest,
                "files": n_files,
                "chunks": n_chunks,
                "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


class EmptyCorpusError(RuntimeError):
    """语料目录里没有可入库的文件。"""


def run_ingest(
    *,
    pdf_dir,
    chroma,
    collection: str = PDF_COLLECTION,
    kinds: tuple[str, ...] = ("pdf", "text"),
    chunk_size: int = 800,
    chunk_overlap: int = 150,
    limit: int = 0,
    if_changed: bool = False,
    embeddings=None,
) -> dict:
    """入库一次，返回 {changed, files, chunks, total, seconds}。

    if_changed=True：指纹一致且集合非空就跳过（不调 Embedding API）。
    embeddings 可注入，离线测试用假向量。
    """
    t0 = time.time()
    root = Path(pdf_dir)
    chroma_path = Path(chroma)
    stamp_file = chroma_path / "corpus_stamp.json"
    digest, n_files = corpus_digest(root, kinds, chunk_size, chunk_overlap)
    store = build_store(embeddings or make_embeddings(), str(chroma_path), collection)

    def result(changed: bool, chunks: int) -> dict:
        return {
            "changed": changed,
            "files": n_files,
            "chunks": chunks,
            "total": store._collection.count(),
            "seconds": round(time.time() - t0, 2),
        }

    if n_files == 0:
        if if_changed:
            return result(False, 0)
        raise EmptyCorpusError(f"{root} 没找到语料（PDF/文本）")
    if if_changed and read_stamp(stamp_file).get("digest") == digest and store._collection.count() > 0:
        return result(False, 0)

    docs = load_dir(root, chunk_size, chunk_overlap, kinds)
    if not docs:
        raise EmptyCorpusError(f"{root} 没找到可读语料（PDF/文本）")
    if limit and limit < len(docs):
        docs = docs[:limit]
    reset_collection(store)
    n = add_documents(store, docs, ids=[d.metadata["chunk_id"] for d in docs])
    write_stamp(stamp_file, digest, n_files, len(docs))
    return result(True, n)


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
    ap.add_argument("--if-changed", action="store_true", help="语料指纹未变且集合非空时跳过重建")
    args = ap.parse_args(argv)

    kinds = tuple(x.strip() for x in args.kinds.split(",") if x.strip())
    try:
        r = run_ingest(
            pdf_dir=args.pdf_dir,
            chroma=args.chroma,
            collection=args.collection,
            kinds=kinds,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
            limit=args.limit,
            if_changed=args.if_changed,
        )
    except EmptyCorpusError as ex:
        print(f"[X] {ex}，先放文件进去（plan §7 第 3 步）", file=sys.stderr)
        return 1

    if not r["files"]:
        print(f"[i] {args.pdf_dir} 没有语料，跳过入库")
        return 0
    if not r["changed"]:
        print(f"[i] 语料无变化（{r['files']} 个文件 / {r['total']} chunks），跳过入库")
        return 0
    print(f"[i] 抽取切分 + 入库 {r['chunks']} 个 chunk（{r['seconds']}s）")
    print(f"[OK] 已入库 {r['chunks']} 条 → collection={args.collection} @ {args.chroma}")
    print(f"[i] 集合总数 {r['total']} / space=cosine")  # build_store 已强校验 cosine，这里只做展示
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
