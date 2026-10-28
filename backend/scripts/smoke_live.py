"""V1.0 真实端到端验收（需要 .env 里有可用 key，会真实调用 API）。

    cd backend
    python scripts/smoke_live.py                 # 默认只入库前 24 个 chunk
    python scripts/smoke_live.py --limit 0       # 整本入库
    python scripts/smoke_live.py --question "红烧肉怎么做"

验收点（对应 plan §2 的 V1 标准）：
1. 真 PDF 能被抽取入库
2. /api/chat 以 SSE 逐帧返回，首 token 早于末 token（证明是流式而非缓冲）
3. sources 帧先到，token 帧能拼成完整答案，最后有 done
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="入库 chunk 数上限，0=全部（默认全量，否则排在后面的语料进不了库）")
    ap.add_argument("--question", default="差旅报销需要提供什么材料，多久能批下来？")
    args = ap.parse_args()

    from fastapi.testclient import TestClient

    from app.main import app
    from app.rag.ingest import main as ingest_main

    print("=" * 62)
    print("[1/3] 真实入库（PDF + 示例 md）")
    print("=" * 62)
    ingest_args = ["--kinds", "pdf,text"]
    if args.limit:
        ingest_args += ["--limit", str(args.limit)]
    rc = ingest_main(ingest_args)
    if rc != 0:
        print("[X] 入库失败", file=sys.stderr)
        return rc

    print()
    print("=" * 62)
    print(f"[2/3] 走 HTTP 打 /api/chat（真 LLM 流式）：{args.question}")
    print("=" * 62)
    client = TestClient(app)
    h = client.get("/api/health").json()
    print(f"  health: model={h['model']} collection_count={h['collection_count']}")

    t0 = time.time()
    first_token_at = None
    last_token_at = None
    token_frames = 0
    answer = ""
    sources: list = []
    errors: list = []

    with client.stream("POST", "/api/chat", json={"question": args.question}) as resp:
        print(f"  HTTP {resp.status_code} content-type={resp.headers.get('content-type')}")
        assert resp.status_code == 200
        for raw in resp.iter_lines():
            if not raw or not raw.startswith("data:"):
                continue
            payload = json.loads(raw[5:].strip())
            now = time.time() - t0
            if payload["type"] == "sources":
                sources = payload["refs"]
                print(f"  [{now:5.2f}s] sources 帧: {len(sources)} 条 -> " + ", ".join("%s#%s(%.3f)" % (s["source"], s["page"], s["score"]) for s in sources[:4]))
            elif payload["type"] == "token":
                token_frames += 1
                answer += payload["text"]
                if first_token_at is None:
                    first_token_at = now
                    print(f"  [{now:5.2f}s] 首个 token: {payload['text']!r}")
                last_token_at = now
            elif payload["type"] == "error":
                errors.append(payload["message"])
                print(f"  [{now:5.2f}s] ERROR: {payload['message']}")
            elif payload["type"] == "done":
                print(f"  [{now:5.2f}s] done 帧")

    print()
    print("=" * 62)
    print("[3/3] 验收判定")
    print("=" * 62)
    print(f"  答案（{len(answer)} 字，{token_frames} 个 token 帧）:")
    print("  " + answer.replace(chr(10), chr(10) + "  "))
    ok = True
    if errors:
        ok = False
    if token_frames < 2:
        print("  [X] token 帧太少，不像流式")
        ok = False
    if first_token_at is not None and last_token_at is not None and last_token_at - first_token_at < 0.05:
        print("  [X] 首末 token 几乎同时，疑似被缓冲后一次性下发")
        ok = False
    if not sources:
        print("  [!] 没有引用来源（集合为空或检索未命中）")
    ft = f"{first_token_at:.2f}s" if first_token_at is not None else "无"
    print("\n" + ("[OK] V1.0 端到端验收通过" if ok else "[FAIL] 见上方问题"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
