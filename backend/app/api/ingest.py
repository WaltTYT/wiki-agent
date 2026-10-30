"""/ingest 与 /knowledge：前端「知识库」弹窗用。

- GET  /knowledge       知识库概览：磁盘上的语料文件 + 集合里每个文件实际切出的片段数
- POST /ingest/upload   收前端选的 PDF/MD/TXT，落到 PDF_DIR 后立即重建索引

入库要调 Embedding API、可能几十秒，放到线程池跑，避免阻塞事件循环。
文件名只取 basename 并做扩展名白名单，同名文件覆盖（等价于“更新这份语料”）。
"""
from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from ..config import get_settings
from ..rag.embeddings import make_embeddings
from ..rag.ingest import EmptyCorpusError, run_ingest
from ..rag.loader import list_corpus_files
from ..rag.vectorstore import PDF_COLLECTION, build_store
from ..schemas import IngestResponse, KnowledgeFile, KnowledgeInfo

router = APIRouter()

ALLOWED_SUFFIXES = {".pdf", ".md", ".txt"}  # 与 loader.TEXT_SUFFIXES 保持一致，否则上传了也不会入库
MAX_BYTES = 25 * 1024 * 1024  # 单文件上限，data/pdfs 里最大的 PDF 约 10MB


@router.get("/knowledge", response_model=KnowledgeInfo)
def knowledge() -> KnowledgeInfo:
    s = get_settings()
    files = list_corpus_files(Path(s.pdf_path), ("pdf", "text"))
    counts: Counter[str] = Counter()
    try:
        store = build_store(make_embeddings(), str(s.chroma_dir), PDF_COLLECTION)
        metas = store._collection.get(include=["metadatas"]).get("metadatas") or []
        for meta in metas:
            counts[Path(str((meta or {}).get("source", ""))).name] += 1
    except Exception:  # noqa: BLE001 向量库还没建好时，至少把磁盘上的文件列出来
        pass
    items = [
        KnowledgeFile(name=f.name, size=f.stat().st_size, chunks=counts.get(f.name, 0))
        for f in files
    ]
    items.sort(key=lambda i: i.name)
    return KnowledgeInfo(files=items, total_chunks=sum(counts.values()))


async def _run() -> dict:
    """在线程里跑一次入库，把异常翻译成 HTTP 状态码。"""
    s = get_settings()
    try:
        return await asyncio.to_thread(
            run_ingest,
            pdf_dir=str(s.pdf_path),
            chroma=str(s.chroma_dir),
            kinds=("pdf", "text"),
            chunk_size=s.chunk_size,
            chunk_overlap=s.chunk_overlap,
            if_changed=True,
        )
    except EmptyCorpusError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    except Exception as ex:  # noqa: BLE001 上游 Embedding/Chroma 报错，原样带回给前端提示
        raise HTTPException(status_code=500, detail=f"{type(ex).__name__}: {ex}"[:300]) from ex


@router.post("/ingest/upload", response_model=IngestResponse)
async def upload_and_ingest(files: list[UploadFile] = File(...)) -> IngestResponse:
    s = get_settings()
    target = Path(s.pdf_path)
    target.mkdir(parents=True, exist_ok=True)

    # 先全部读进内存校验，避免“第 3 个文件非法，前 2 个已经落盘”的半成功状态
    ready: list[tuple[str, bytes]] = []
    for f in files:
        name = Path(f.filename or "").name
        if not name or Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
            raise HTTPException(status_code=400, detail=f"只支持 PDF/MD/TXT，收到 {name or '未命名文件'}")
        data = await f.read()
        if not data:
            raise HTTPException(status_code=400, detail=f"{name} 是空文件")
        if len(data) > MAX_BYTES:
            raise HTTPException(status_code=400, detail=f"{name} 超过 {MAX_BYTES // 1024 // 1024}MB 上限")
        ready.append((name, data))
    if not ready:
        raise HTTPException(status_code=400, detail="没有收到文件")

    saved = [name for name, _ in ready]
    for name, data in ready:
        (target / name).write_bytes(data)

    result = await _run()
    result["uploaded"] = saved
    return IngestResponse(**result)
