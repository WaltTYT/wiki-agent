"""模型切换（白名单 + 候选列表 + 透传）离线测试。"""
from __future__ import annotations

import pytest
from types import SimpleNamespace
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.chat import resolve_model
from app.config import Settings
from app.llm import make_chat_model
import app.llm as llm_mod

FLASH = "qwen3.8-flash"
MAX = "qwen3.8-max"


@pytest.fixture()
def fake_llm_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """不依赖 backend/.env：CI 里没有 .env，靠本机密钥会让用例在干净环境直接失败。"""
    s = Settings(
        llm_model=FLASH,
        llm_models=f"{FLASH},{MAX}",
        llm_api_key="sk-test",
        llm_base_url="https://x.invalid/v1",
    )
    monkeypatch.setattr(llm_mod, "get_settings", lambda: s)
    return s


def test_model_choices_merges_default_and_list():
    s = Settings(llm_model=FLASH, llm_models=f"{FLASH},{MAX}")
    assert s.model_choices == [FLASH, MAX], "默认模型排第一，且不重复"


def test_model_choices_works_without_extra_list():
    s = Settings(llm_model=FLASH, llm_models="")
    assert s.model_choices == [FLASH]


def test_model_choices_ignores_blank_entries():
    s = Settings(llm_model=FLASH, llm_models=f" , {MAX} , ")
    assert s.model_choices == [FLASH, MAX]


def test_resolve_model_passes_valid_name():
    assert resolve_model(MAX, [FLASH, MAX]) == MAX


def test_resolve_model_empty_means_default():
    assert resolve_model(None, [FLASH, MAX]) is None
    assert resolve_model("", [FLASH, MAX]) is None


def test_resolve_model_rejects_unknown():
    with pytest.raises(HTTPException) as ei:
        resolve_model("gpt-9", [FLASH, MAX])
    assert ei.value.status_code == 400
    assert "gpt-9" in str(ei.value.detail)
    assert FLASH in str(ei.value.detail), "报错要告诉前端可选哪些"


def test_make_chat_model_uses_requested_model(fake_llm_settings):
    assert make_chat_model(model=MAX).model_name == MAX
    assert make_chat_model(model=FLASH).model_name == FLASH
    assert make_chat_model().model_name == FLASH, "不传模型时用配置里的默认模型"


def test_make_chat_model_disables_thinking_by_default(fake_llm_settings):
    """qwen3.8 默认会思考，多花 token 也拖慢首字；这里必须显式关掉。"""
    m = make_chat_model(model=FLASH)
    assert m.extra_body == {"enable_thinking": False}
    assert make_chat_model(model=FLASH, thinking=True).extra_body == {"enable_thinking": True}


def test_models_endpoint(monkeypatch: pytest.MonkeyPatch):
    import app.api.chat as mod
    from app.main import app

    monkeypatch.setattr(
        mod, "get_settings",
        lambda: Settings(llm_model=FLASH, llm_models=f"{FLASH},{MAX}", llm_api_key="sk-x", llm_base_url="https://x.invalid/v1"),
    )
    body = TestClient(app).get("/api/models").json()
    assert body["default"] == FLASH
    assert body["models"] == [FLASH, MAX]
    assert body["groups"][0]["models"] == [FLASH, MAX], "老配置应折叠成单个 provider 分组"


def test_chat_rejects_model_outside_whitelist(monkeypatch: pytest.MonkeyPatch):
    """乱填模型名必须在进 LLM 之前就被挡掉。"""
    import app.api.chat as mod
    from app.main import app

    monkeypatch.setattr(
        mod, "get_settings",
        lambda: Settings(llm_model=FLASH, llm_models=MAX, llm_api_key="sk-x", llm_base_url="https://x.invalid/v1"),
    )
    r = TestClient(app).post("/api/chat", json={"question": "随便", "model": "gpt-9"})
    assert r.status_code == 400
    assert "gpt-9" in r.json()["detail"]
# ── 多 Provider（千问 + 智谱 GLM）────────────────────────────
GLM = "glm-4-flash"
GLM_BASE = "https://open.bigmodel.cn/api/paas/v4"
QWEN_BASE = "https://cn-beijing.maas.qianwenaiapi.com/compatible-mode/v1"

PROVIDERS = [
    {
        "id": "qwen",
        "label": "千问 AI 平台",
        "base_url": QWEN_BASE,
        "api_key": "sk-qwen",
        "models": [FLASH, MAX],
        "supports_thinking": True,
    },
    {
        "id": "glm",
        "label": "智谱 GLM",
        "base_url": GLM_BASE,
        "api_key": "glm-key",
        "models": [GLM, "glm-4.7-flash"],
        "supports_thinking": False,
    },
]


@pytest.fixture()
def multi(monkeypatch: pytest.MonkeyPatch):
    import app.config as cfg
    import app.llm as llm_mod

    s = Settings(llm_model=FLASH, llm_models="", llm_providers=PROVIDERS)
    # app.llm 里是 from .config import get_settings，只 patch config 对它无效，两个都要打
    monkeypatch.setattr(cfg, "get_settings", lambda: s)
    monkeypatch.setattr(llm_mod, "get_settings", lambda: s)
    return s


def test_all_models_flattens_across_providers(multi):
    assert multi.all_models == [FLASH, MAX, GLM, "glm-4.7-flash"]


def test_credential_routes_by_provider(multi):
    assert multi.resolve_credential(GLM) == ("glm-key", GLM_BASE)
    assert multi.resolve_credential(MAX) == ("sk-qwen", QWEN_BASE)
    assert multi.provider_of(GLM).id == "glm"


def test_glm_model_gets_no_extra_body(multi):
    """智谱不认 enable_thinking，多传可能被拒；supports_thinking=false 必须完全不下发。"""
    from app.llm import make_chat_model

    glm = make_chat_model(model=GLM)
    assert glm.extra_body is None
    assert str(glm.openai_api_base).rstrip("/").endswith("api/paas/v4")

    qwen = make_chat_model(model=MAX)
    assert qwen.extra_body == {"enable_thinking": False}
    assert "qianwenaiapi" in str(qwen.openai_api_base)


def test_models_endpoint_groups(multi, monkeypatch: pytest.MonkeyPatch):
    import app.api.chat as mod
    from app.main import app

    monkeypatch.setattr(mod, "get_settings", lambda: multi)
    body = TestClient(app).get("/api/models").json()
    assert body["default"] == FLASH
    assert [g["label"] for g in body["groups"]] == ["千问 AI 平台", "智谱 GLM"]
    assert body["groups"][1]["models"] == [GLM, "glm-4.7-flash"]


def test_cross_provider_model_is_accepted(multi, monkeypatch: pytest.MonkeyPatch):
    """白名单现在覆盖所有 provider 的模型，GLM 模型不该被 400 挡掉。"""
    import app.api.chat as mod
    from app.main import app

    monkeypatch.setattr(mod, "get_settings", lambda: multi)

    class _Store:
        _collection = SimpleNamespace(count=lambda: 1)

    monkeypatch.setattr("app.rag.vectorstore.search", lambda store, q, k=4, kind="pdf": [])
    monkeypatch.setattr("app.rag.embeddings.make_embeddings", lambda: None)
    monkeypatch.setattr("app.rag.vectorstore.build_store", lambda *a, **kw: _Store())
    monkeypatch.setattr("app.llm.make_chat_model", lambda model=None, thinking=None: FakeEcho())

    r = TestClient(app).post("/api/chat", json={"question": "你好", "model": GLM})
    assert r.status_code == 200


class FakeEcho:
    async def astream(self, messages):
        class C:
            content = "ok"
            additional_kwargs = {}

        yield C()