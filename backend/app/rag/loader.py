"""语料加载与切分。

决策 5b：`langchain-community` 官方日落（issue #674），但实测 PyPDFLoader 目前**只有**它提供
（`langchain_classic.document_loaders` 只是转发并打警告，`langchain.document_loaders` 在 1.2 已不存在）。
所以 loader 收在这一个模块里：将来换 pymupdf4llm（Markdown 抽取质量更好）只改 `load_pdf`。

同时支持 .txt/.md：V3 的 wiki 条目就是 md，且让端到端测试不依赖真实 PDF。
"""
from __future__ import annotations

import warnings
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 中文优先的分隔符（实测：默认 separators 对中文长句几乎不切）
SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]
TEXT_SUFFIXES = (".txt", ".md")


def make_splitter(chunk_size: int = 800, chunk_overlap: int = 150) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=SEPARATORS,
        keep_separator=True,
    )


def load_pdf(pdf_file: Path, splitter: RecursiveCharacterTextSplitter | None = None) -> list[Document]:
    """单个 PDF → 带 metadata 的 chunk 列表。page 用 0-based（PyPDFLoader 惯例），展示层再 +1。"""
    with warnings.catch_warnings():
        # langchain-community 的日落告警不该刷屏日志
        warnings.filterwarnings("ignore", message=".*langchain-community.*")
        from langchain_community.document_loaders import PyPDFLoader

    docs = PyPDFLoader(str(pdf_file)).load()
    for d in docs:
        d.metadata["source"] = d.metadata.get("source") or pdf_file.name
    return _tag(splitter or make_splitter(), docs, pdf_file)


def load_text(text_file: Path, splitter: RecursiveCharacterTextSplitter | None = None) -> list[Document]:
    """单个 .txt/.md → chunk 列表（无页码，metadata.page 缺失）。"""
    content = Path(text_file).read_text(encoding="utf-8", errors="replace")
    docs = [Document(page_content=content, metadata={"source": text_file.name})]
    return _tag(splitter or make_splitter(), docs, text_file)


def _tag(splitter: RecursiveCharacterTextSplitter, docs: list[Document], src: Path) -> list[Document]:
    split = splitter.split_documents(docs)
    for i, d in enumerate(split):
        d.metadata.setdefault("source", src.name)
        d.metadata["chunk_id"] = f"{src.stem}#{i:04d}"
    return split


def list_corpus_files(root: Path, kinds: tuple[str, ...] = ("pdf", "text")) -> list[Path]:
    """列出语料目录里要入库的文件（PDF 在前、文本在后，顺序稳定）。"""
    root = Path(root)
    files: list[Path] = []
    if "pdf" in kinds:
        files += sorted(root.glob("*.pdf"))
    if "text" in kinds and root.exists():
        files += sorted(p for p in root.iterdir() if p.suffix.lower() in TEXT_SUFFIXES)
    return files


def load_dir(
    root: Path,
    chunk_size: int = 800,
    chunk_overlap: int = 150,
    kinds: tuple[str, ...] = ("pdf", "text"),
) -> list[Document]:
    """加载目录下的 PDF / 文本语料。kinds 控制要读哪几类。"""
    files = list_corpus_files(root, kinds)
    if not files:
        return []
    splitter = make_splitter(chunk_size, chunk_overlap)
    out: list[Document] = []
    for f in files:
        out.extend(load_pdf(f, splitter) if f.suffix.lower() == ".pdf" else load_text(f, splitter))
    return out


# 兼容旧名（plan §2.1 里写的 load_pdfs）
def load_pdfs(pdf_dir: Path, chunk_size: int = 800, chunk_overlap: int = 150) -> list[Document]:
    return load_dir(pdf_dir, chunk_size, chunk_overlap, kinds=("pdf",))
