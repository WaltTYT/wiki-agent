"""端到端：语料 → ingest CLI → search CLI（离线确定性 embedding，不联网、不花 API 钱）。

覆盖 plan §2.1 冒烟项「文档 → Chroma → 本地检索命中」。跑通即说明后端骨架完整，
剩下唯一未知量是真实 embedding 的中文质量（用 scripts/check_embedding.py 单独验）。
"""
from __future__ import annotations

import pytest

CORPUS = """第一章 假期制度。公司员工每年享有十五天带薪年假，入职满三年后增加到二十天，
请假需提前三个工作日在系统提交申请。

第二章 报销制度。差旅报销需要提供发票原件，审批周期为五个工作日，超期不予受理。
单笔金额超过五千元的需要财务总监复核。

第三章 技术说明。后端使用 FastAPI 的 StreamingResponse 配合异步生成器实现逐块流式响应，
前端用 ReadableStream 解析 SSE 帧渲染打字机效果。
"""


@pytest.fixture()
def emb_stub(monkeypatch):
    """把 embeddings 换成离线确定性实现，并把配置伪装成已填好。"""
    import app.rag.embeddings as emb_mod
    from app.config import Settings
    from app.rag.embeddings import CharBigramHashEmbeddings

    monkeypatch.setattr(
        emb_mod,
        "get_settings",
        lambda: Settings(
            embedding_model="stub",
            embedding_api_key="sk-stub",
            embedding_base_url="https://example.invalid/v1",
        ),
    )
    monkeypatch.setattr(emb_mod, "make_embeddings", lambda: CharBigramHashEmbeddings())
    return emb_mod


def test_text_corpus_end_to_end(tmp_path, emb_stub, capsys):
    from app.rag.ingest import main as ingest_main
    from app.rag.search import main as search_main

    (tmp_path / "handbook.md").write_text(CORPUS, encoding="utf-8")
    chroma = str(tmp_path / "chroma")
    # 语料只有 ~300 字，必须调小 chunk 才能验证「按章节切开并检索到对应块」
    args = ["--pdf-dir", str(tmp_path), "--chroma", chroma, "--kinds", "text", "--chunk-size", "60", "--chunk-overlap", "5"]

    assert ingest_main(args) == 0
    out = capsys.readouterr().out
    assert "已入库" in out and "space=cosine" in out, out

    assert search_main(["报销发票要什么材料", "--chroma", chroma]) == 0
    out = capsys.readouterr().out
    first = next(ln for ln in out.splitlines() if ln.strip().startswith("1."))
    assert "报销" in first, first
    assert "handbook.md" in first, first


def test_ingest_is_idempotent(tmp_path, emb_stub, capsys):
    from app.rag.ingest import main as ingest_main

    (tmp_path / "kb.md").write_text(CORPUS, encoding="utf-8")
    chroma = str(tmp_path / "chroma")
    args = ["--pdf-dir", str(tmp_path), "--chroma", chroma, "--kinds", "text"]

    import re

    args = ["--pdf-dir", str(tmp_path), "--chroma", chroma, "--kinds", "text", "--chunk-size", "60", "--chunk-overlap", "5"]

    def count_after_run() -> int:
        assert ingest_main(args) == 0
        line = next(ln for ln in capsys.readouterr().out.splitlines() if "集合总数" in ln)
        return int(re.search(r"集合总数\s*(\d+)", line).group(1))

    n1 = count_after_run()
    n2 = count_after_run()
    assert n1 > 1, f"chunk 数应大于 1，实际 {n1}"
    assert n1 == n2, f"重复入库导致集合翻倍：{n1} -> {n2}"


def test_pdf_fixture_test_runs_when_corpus_present(tmp_path, emb_stub, capsys):
    """有真实中文 PDF 时自动跑 PDF 分支（plan §7 第 3 步放入 data/pdfs/ 后即生效）。"""
    from app.config import get_settings
    from app.rag.ingest import main as ingest_main
    from app.rag.search import main as search_main

    pdfs = sorted(get_settings().pdf_path.glob("*.pdf"))
    if not pdfs:
        pytest.skip("data/pdfs/ 还没有 PDF 语料，跳过真实 PDF 分支")
    chroma = str(tmp_path / "chroma_pdf")
    assert ingest_main(["--pdf-dir", str(pdfs[0].parent), "--chroma", chroma, "--kinds", "pdf"]) == 0
    assert search_main(["测试查询", "--chroma", chroma]) == 0


def test_ingest_without_corpus_fails_cleanly(tmp_path, emb_stub, capsys):
    from app.rag.ingest import main as ingest_main

    assert ingest_main(["--pdf-dir", str(tmp_path / "none"), "--chroma", str(tmp_path / "c")]) == 1
    assert "没找到语料" in capsys.readouterr().err
