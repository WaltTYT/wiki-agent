import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 测试隔离：pydantic-settings 里真实环境变量优先于 .env，
# 不设这行会导致开发者本机的 LLM_PROVIDERS（千问 + 智谱）漏进「只测老配置」的用例。
os.environ.setdefault("LLM_PROVIDERS", "[]")

# CI 里没有 backend/.env，本地却有；把敏感键显式置空（环境变量优先级高于 .env），
# 保证两边跑的是同一套离线用例，避免「本机绿、CI 红」的隐性耦合。
for _key in (
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_MODELS",
    "EMBEDDING_API_KEY",
    "EMBEDDING_BASE_URL",
    "EMBEDDING_MODEL",
):
    os.environ[_key] = ""