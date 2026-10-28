import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 测试隔离：pydantic-settings 里真实环境变量优先于 .env，
# 不设这行会导致开发者本机的 LLM_PROVIDERS（千问 + 智谱）漏进「只测老配置」的用例。
os.environ.setdefault("LLM_PROVIDERS", "[]")