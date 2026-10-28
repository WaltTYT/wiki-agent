"""对比候选模型的真实表现：走同一个 /api/chat，逐模型测首 token 延迟与耗时。

    cd backend
    python scripts/compare_models.py                      # 进程内 ASGI（TestClient）
    python scripts/compare_models.py --server http://127.0.0.1:8000   # 打真实 uvicorn（推荐，事件循环只有一个）

为什么要 --server：TestClient 每次 stream() 会另起事件循环，第二次请求可能撞上
"Event loop is closed"（客户端实例被上一个循环绑死）。真实部署是单循环长驻，
所以判定切换是否真的可用，必须以 --server 模式的结果为准。
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
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402


def one(client, question: str, model: str | None) -> dict:
    """单个模型跑一次；任何异常都收敛成 error 字段，绝不让整轮对比中断。"""
    t0 = time.time()
    first = None
    answer = ""
    refs: list = []
    err = ""
    body = {"question": question}
    if model:
        body["model"] = model
    try:
        with client.stream("POST", "/api/chat", json=body) as resp:
            if resp.status_code != 200:
                detail = resp.read().decode("utf-8", "replace")[:180]
                return {"model": model or "(默认)", "http": resp.status_code, "error": detail}
            for raw in resp.iter_lines():
                if not raw or not raw.startswith("data:"):
                    continue
                p = json.loads(raw[5:].strip())
                now = time.time() - t0
                if p["type"] == "sources":
                    refs = p["refs"]
                elif p["type"] == "token":
                    if first is None:
                        first = now
                    answer += p["text"]
                elif p["type"] == "error":
                    err = p["message"]
    except Exception as ex:  # noqa: BLE001 超时/断连也要保住其它模型的结果
        err = type(ex).__name__ + ": " + str(ex)[:120]
    top = "-"
    if refs:
        top = str(refs[0]["source"]) + "(" + str(refs[0]["score"]) + ")"
    return {
        "model": model or "(默认)",
        "first_token": first,
        "total": time.time() - t0,
        "chars": len(answer),
        "top_ref": top,
        "error": err,
        "answer": answer,
    }

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", default="差旅报销需要提供什么材料，多久能批下来？")
    ap.add_argument("--server", default="", help="真实 uvicorn 地址；留空则用进程内 TestClient")
    ap.add_argument("--only", default="", help="只测这些模型，逗号分隔")
    ap.add_argument("--timeout", type=int, default=90, help="单模型读超时秒数")
    args = ap.parse_args()

    if args.server:
        import httpx

        base = args.server.rstrip("/")
        client = httpx.Client(base_url=base, timeout=args.timeout)
        print(f"模式：真实 HTTP -> {base}")
    else:
        client = TestClient(app)
        print("模式：进程内 TestClient（受事件循环限制，第二次请求可能报错）")
    info = client.get("/api/models").json()
    print(f"问题：{args.question}")
    print(f"白名单：default={info['default']}  models={info['models']}\n")

    only = {x.strip() for x in args.only.split(",") if x.strip()}
    targets = [m for m in info["models"] if not only or m in only]
    rows = []
    for m in targets:
        r = one(client, args.question, m)   # 逐个跑逐个打印：卡住一个不影响其余
        rows.append(r)
        ft = f"{r['first_token']:.2f}s" if r.get("first_token") is not None else "无"
        head = f"  {r['model']:22} 首token {ft:>7}"
        if r.get("http"):
            print(head + f"  HTTP {r['http']} {r.get('error')}")
        else:
            print(head + f"  总耗时 {r['total']:5.2f}s  {r['chars']:3}字  命中 {r['top_ref']}")
        if r.get("error"):
            print("    [X] " + r["error"])
        elif r.get("answer"):
            print("    -> " + r["answer"][:90])
        print()
    bad = [r for r in rows if r.get("error") or r.get("http")]

    # 额外验证：白名单外的模型必须被挡
    r = one(client, args.question, "gpt-9")
    print(f"\n  越界校验 gpt-9 -> HTTP {r.get('http')} {str(r.get('error'))[:80]}")
    ok = not bad and r.get("http") == 400
    print("\n" + ("[OK] 模型切换全部可用" if ok else "[FAIL] 见上方错误"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
