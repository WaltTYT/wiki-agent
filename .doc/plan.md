# wiki-agent 项目规划（plan.md）

> 目标：从「能跑的 RAG」进化到「会自我纠错的 Agent」，最终沉淀出带记忆系统的企业级开源项目。
> 版本节奏：V1.0 全栈基础 RAG → V2.0 LangGraph 状态机 + 自我纠错 → V3.0 LLM Wiki 记忆 + 工程化包装
> 环境策略：后端一律用 **conda** 管理（本机已就绪，见 §0），不使用 venv；本项目不依赖 Docker。

---

## 0. 当前环境与约束

| 项 | 状态 | 说明 |
|---|---|---|
| conda | 就绪 Miniconda 26.5.3，`D:\study\miniconda` | **后端环境唯一入口**：直接复用现有 env `langchain1.2`（见 §2.0）；`environment.yml` 仍保留以复现 |
| 已有 conda envs | `base`(3.14.6) / `langchain1.2`(3.13.12) / `my-agent`(3.11.15) / `dns-dga` | **本项目直接复用 `langchain1.2`**（langchain 1.2.12 + langgraph 1.1.10，与决策 3 主线一致）；另两个 env 不动 |
| 系统 Python | 3.12.6（全局，不使用） | 让位给 conda env，避免装包污染全局 |
| Node / npm | 就绪 v24.12.0 / 11.6.2 | 前端 Vite + Vue3，不走 conda |
| Git | 就绪 2.54 | 每个版本里程碑打 tag：v0.1 / v0.2 / v1.0 |
| Docker | 缺失（不影响主线） | 按决策 5：本机不装 Docker，V3 用脚本一键启动；compose/Dockerfile 仅作可选交付物（CI 或以后验证） |
| LLM API | 已接入千问 AI 平台与智谱 GLM | 统一走 OpenAI 兼容协议，多 Provider 配置位于未提交的 `backend/.env`；公开模板见 `.env.example` |

关键决策（先定死，避免返工）

1. **conda 环境方案**：复用现有 env `langchain1.2`（不新建 `wiki-agent`：env 名与项目名相同，`conda activate wiki-agent` 这类命令极易混淆）。它已含 langchain 1.2.12 / langgraph 1.1.10，本项目只需补 pip 依赖；项目根保留 `environment.yml`（`name: langchain1.2`）以便换机/CI 复现。日常两条命令：`conda activate langchain1.2` + `pip install -r backend/requirements.txt`。
2. **依赖装法：conda 管 Python，pip 管包**。langchain / langgraph / langchain-chroma / pypdf 全部走 pip——conda 默认 channel 里这些包版本陈旧且依赖解析慢，混装容易出 ABI/版本漂移。禁止 `conda install` 与 `pip install` 交替装同一批包。
3. **版本锁（2026-10 校准）**（2026-10-28 补充：决定**直接复用现有 `langchain1.2` env，不新建 `wiki-agent`**，理由见 §2.0）：本项目跟随 **langchain ≥1.2,<2 + langgraph ≥1.1,<2**（PyPI 当前主线 1.4.7 / 1.2.18；官方把 langchain 0.3 与 langgraph 0.4 归为 Legacy）。原计划锁 0.3.x 的理由（教程多）已不成立，代价是**老教程/老 StackOverflow 答案不能照抄**——v0.3 文档已归档但仍在（[v0.3 docs](https://docs.langchain.com/oss/python/migrate/langchain-v1) / [v0.3 API ref](https://python.langchain.com/api_reference)）。本计划代码按 1.x 写法：`init_chat_model("openai", model=..., api_key=..., base_url=...)`、向量库 `from langchain_chroma import Chroma`（已独立成包）、流式 `model.astream()`、V2 用 `graph.astream_events()`。DeepSeek/Qwen/VLLM 等走 OpenAI 兼容层：首选 `langchain-openai` + base_url，若官方推荐用厂商包（`langchain-deepseek` 等）则切换成本很低。
4. IDE 指向：VS Code/PyCharm 解释器选 `D:\study\miniconda\envs\langchain1.2\python.exe`；脚本内用 `conda run -n langchain1.2 ...` 保证不依赖 shell 激活状态。
5. LLM/Embedding 接入：全部通过 ChatOpenAI / OpenAIEmbeddings 的 base_url 适配，配置集中在 backend/.env。

5a. **Embedding 必须显式指定（实测硬约束，不是可选项）**：Chroma 不传 `embedding_function` 会静默使用英文模型 `all-MiniLM-L6-v2`，中文语料实测 3 条查询只中 1 条，等于检索层白做。首选**与 LLM 同厂商的 embedding API**（DeepSeek 目前无 embedding → 配 DashScope text-embedding-v4 / SiliconFlow bge-m3 / OpenAI text-embedding-3-small）；备选本地 `BAAI/bge-small-zh-v1.5`（需 `pip install sentence-transformers`，会带 torch 约 2GB+，且要能连 huggingface 或 hf-mirror）。**代码规约：`Chroma(...)` 构造必须显式传 `embedding_function`，`rag/vectorstore.py` 里若检测到缺省直接 raise，禁止静默降级。**

5b. **PDF loader 选型**：`langchain-community` 官方日落（issue #674），但 `PyPDFLoader` 实测只有它提供（classic 仅转发）。决定：V1 用 `langchain_community.document_loaders.PyPDFLoader` 跑通闭环并**封装在 `rag/loader.py` 一个函数里**，V1.5 若换抽取质量（Markdown + 表格）改 `pymupdf4llm` 自己包 `Document`，只改这一个函数，其余零改动。
6. 向量库：Chroma PersistentClient 本地持久化到 data/chroma/，不起独立服务（本机无 Docker，V3 也以后端自带为准）。
7. 流式协议：后端 StreamingResponse + 自定义 SSE 帧 data: {"type":"token|sources|error|done", ...}，前端 fetch + ReadableStream 手解。
8. **Docker 可选**：本机不装 Docker 也能完成 V3——日常开发用 conda env + uvicorn + Vite dev server；「一键拉起」用脚本实现（start-dev.ps1）；docker-compose.yml 与两个 Dockerfile 照写，作为开源仓库可选交付物，验证推迟到 GitHub Actions CI（ubuntu runner 自带 docker）。

---

### 0.1 当前交付状态（2026-10-29 核对）

- V1 与 V2 已有提交历史；GitHub `main` 与 `v0.2` 标签均已确认存在。V3 Wiki 记忆仍为后续计划，下方早期记录不代表当前阻塞。
- `data/pdfs/` 是本地语料目录，整个目录不提交；公开虚构示例与使用说明放在 `data/pdfs-example/`。首次使用先复制示例到本地语料目录，再入库。
- `.doc/example/`、`backend/.env`、`data/chroma/`、本机诊断脚本与依赖/构建目录继续排除。本次仅从 Git 索引移除旧示例路径，保留本地文件与现有索引。
- Windows 脚本换行由 `.gitattributes` 约定：BAT/PowerShell 使用 CRLF，Markdown 使用 LF。
- 本次打包验证：conda `langchain1.2` 中 `python -m pytest tests -q` 为 **48 passed / 3 warnings**；前端 `npm run build` 成功。未调用真实模型或重建现有索引。
- Codex 重启后的诊断：普通执行通道仍报 `helper_unknown_error: setup refresh had errors`；沙箱外的 `pwsh` 可成功执行。问题已定位到 Windows 沙箱初始化环节，具体根因尚未确认；这不要求修改项目或重建 conda 环境。

## 1. 目录结构总目标

```text
wiki-agent/
├── environment.yml              # 已写：name langchain1.2 / python 3.13 / pip -r requirements.txt
├── .gitignore                   # 已写：chroma/、.env、node_modules/、.chroma_check/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口 + CORS + 路由挂载
│   │   ├── config.py            # pydantic-settings 读 .env
│   │   ├── schemas.py           # 请求/响应模型
│   │   ├── rag/
│   │   │   ├── loader.py        # PDF 加载 + 切分
│   │   │   ├── vectorstore.py   # Chroma 封装（pdf / wiki 两个 collection）
│   │   │   └── ingest.py        # 入库 CLI：conda run -n langchain1.2 python -m app.rag.ingest
│   │   ├── agents/
│   │   │   ├── rag_graph.py     # V2: LangGraph 状态图（retrieve/grade/rewrite/generate）
│   │   │   ├── wiki_writer.py   # V3: Write_Wiki 节点
│   │   │   └── prompts.py       # 所有 prompt 模板集中管理
│   │   └── api/
│   │       └── chat.py          # /chat SSE 接口（V1 直线版 → V2 包 graph → V3 加 wiki）
│   ├── tests/                   # pytest：切分、打分路由、SSE 帧格式
│   ├── requirements.txt         # 已写：按 §1.5 实测版本做上界锁
│   ├── Dockerfile               # 可选交付物（容器内用 python:3.13-slim + pip，不装 conda）
│   ├── .env.example             # 已写：LLM/Embedding/阈值 全参数，复制成 .env 即跑
│   └── scripts/
│       └── check_embedding.py   # 已写：embedding 中文命中实测，4/4 PASS 才进 §2.1
├── frontend/                    # 已脚手架：Vue 3.5.44 + Vite 8.3.5 + plugin-vue 6.0.10（JS 版，非 TS）
│   ├── src/
│   │   ├── App.vue              # 现为 HelloWorld 占位，待替换
│   │   ├── components/          # 待建：ChatWindow / MessageBubble / SourcePanel
│   │   └── utils/sse.js         # 待建：ReadableStream 解析器（.js，不是 .ts）
│   ├── vite.config.ts           # dev proxy /api → localhost:8000
│   ├── Dockerfile               # 可选交付物：build → nginx 静态托管
│   └── nginx.conf               # 生产环境反代 /api
├── scripts/                     # V3: start-dev / ingest / test（conda 版一键脚本，无 Docker 主路径）
├── data/
│   ├── pdfs/                    # 本地 PDF/MD/TXT 语料（整目录 gitignore）
│   ├── pdfs-example/            # 可公开的虚构手册与 README，复制到 pdfs/ 后使用
│   ├── chroma/                  # 向量库持久化（gitignore）
│   └── wiki/                    # V3: 知识沉淀条目（一篇一 md + 索引）
├── docs/
│   ├── plan.md                  # 本文件
│   ├── architecture.md          # Mermaid 架构图
│   └── roadmap.md
├── .github/workflows/ci.yml     # pytest + compose 冒烟（可选）
├── docker-compose.yml           # V3（可选交付物，CI 验证）
├── README.md                    # V3 门面
└── .gitignore                   # data/chroma/、backend/.env、node_modules/、.pytest_cache/
```

---

## 1.5 已验证状态（2026-10-28，conda env `langchain1.2`）

| 项 | 实测结果 |
|---|---|
| ACL 修复 | icacls 两条命令成功处理 8881 文件，`LILY\Walt : Modify` 已生效，普通窗口可 pip 装包 |
| 依赖 | langchain 1.2.12 / langchain-core 1.7.0 / langgraph 1.1.10 / langchain-openai 1.7.3 / langchain-text-splitters 1.1.3 / langchain-chroma 1.1.0 / langchain-community 0.4.2 / langchain-classic 1.0.8 / chromadb 1.5.9 / pypdf 6.21.3 / fastapi 0.162.0 / uvicorn 0.54.0 / sse-starlette 3.6.0 / pytest 9.2.0 |
| import 自检 | 11 个关键模块全部 import OK（Python 3.13.12） |
| Chroma 冒烟 | 建集合 + 入库 + similarity_search 全通：入库 0.7–1.4s、检索 0.24s，默认 embedding 模型已缓存本地 |
| **踩到的坑 1** | Chroma 不传 `embedding_function` 会**静默**用英文模型 `all-MiniLM-L6-v2`。中文 3 条查询实测仅 1 条命中正确文档（另两条正确文档未进 top-2）→ 见决策 5a |
| **踩到的坑 2**（cosine 三连，已全部固化进 `app/rag/vectorstore.py`）| ① 不指定 space 时 **默认 l2**，`similarity_search_with_relevance_scores` 返回负数并告警（实测 -0.075 / -0.439），阈值判断整体失真 → 建集合必须显式 `collection_metadata={"hnsw:space":"cosine"}`；② cosine 下 `similarity_search_with_score` 返回的是**距离**（1-相似度），与 relevance 量纲相反 → 代码统一只用 relevance；③ 实测 relevance 会**略低于 0**（见过 -0.017）→ 比较前一律 clamp 到 [0,1] |
| **踩到的坑 3** | ① Chroma 集合名硬约束：3–512 字符、`[a-zA-Z0-9._-]`、首尾须字母数字（实测 `t1` 被 InvalidArgumentError 拒）；② langchain-chroma 1.1 的 `Chroma.__init__` **没有** `delete_existing`，`delete_collection/reset_collection` 都是实例方法；③ 重建集合要调私有 `__ensure_collection`，类外直接写会被 Python 名字改写成 `_Chroma__ensure_collection` → 必须 `getattr(store, "_Chroma__ensure_collection")()` |
| **踩到的坑 4** | `langchain-community` 官方日落但 PyPDFLoader 只有它提供（classic 仅转发打警告、`langchain.document_loaders` 在 1.2 已删）→ loader 收进 `app/rag/loader.py` 单点，将来换 pymupdf4llm 只改一个函数。另外实测 pypdf 生成的 PDF 抽不出中文（WinAnsi 限制），所以端到端测试改用 .txt/.md 语料，loader 也因此原生支持文本 |
| 后端骨架 | **已落地并通过 16 项离线测试**：`app/config.py`、`rag/embeddings.py`（缺配置即 raise）、`rag/vectorstore.py`（cosine + 自检 + clamp + 幂等 reset）、`rag/loader.py`、`rag/ingest.py`、`rag/search.py`、`tests/`（`pytest -q` → 16 passed / 1 skipped） |
| 唯一未知量 | 真实 embedding 的中文语义质量：`cd backend; python scripts/check_embedding.py`（已改为复用 build_store，自带 cosine），4/4 PASS 才算过 |

### 1.6 当前阻塞：百炼 API Key 被服务端判为无效（2026-10-28）

已用 `默认业务空间-apiKey-7375125.csv` 生成 `backend/.env`（LLM=qwen-plus / Embedding=text-embedding-v4，base_url 用 CSV 自带的业务空间专属域名），实跑 `check_embedding.py` 返回 **401 Invalid API-key**。

排除过程（证据都在，别重复劳动）：

| 假设 | 验证方式 | 结论 |
|---|---|---|
| CSV 解析污染（BOM/空白/引号/换行） | csv 模块解析 + 字符集扫描 + 与 .env 逐字节比对 | **排除**：117 字符、仅 [A-Za-z0-9_-.]、无 CR/TAB、strip 与去引号变体结果相同 |
| 域名与 key 不配套 | 专属域名 / 公共 CN / 国际站 intl 三种 base_url | **排除**：全部 401 |
| 缺 X-DashScope-WorkSpace 头 | 带 / 不带该头各跑一遍 | **排除**：都 401 |
| 我们代码的问题 | 绕开 langchain，用 httpx 直打原生 `/api/v1/services/embeddings` 路径 | **排除**：原生路径同样 InvalidApiKey |
| 只有 embedding 没权限 | qwen-plus chat 在两个域名各试一次 | **排除**：也 401 |

结论：**key 本身在服务端无效**（已删除 / 过期 / 未启用，或账号未开通百炼、欠费、未实名）。网络与代码链路都是通的，拿到有效 key 后**不需要改任何代码**，直接重跑 `python scripts/check_embedding.py`。

追加验证（第二轮，用户提供的 base_url）：`https://cn-beijing.maas.qianwenaiapi.com/compatible-mode/v1` + `qwen3.8-flash` + `enable_thinking`。该域名**可访问且说 OpenAI 协议**（返回规范 401 JSON），但用同一条 `sk-ws-` key 打 `/models`、chat、chat stream、embeddings(v4/v3) 全部 401。

关键判断：`qianwenaiapi.com` 不是 `aliyuncs.com` 体系——它属于**千问 AI 平台**（platform.qianwenai.com，2026-05 上线的 MaaS 平台），与**阿里云百炼**（dashscope / `*.maas.aliyuncs.com`）是两套独立签发体系，**Key 与域名必须同源**。CSV 那条是百炼导出的 key，所以在新域名必然 401；而它在百炼自己的三个域名（业务空间专属 / 公共 CN / 国际站）也 401 → 该 key 本身已失效。

另外注意官方口径：DashScope 中心化域名自 2026-09-30 起不再支持新特性，官方建议迁移到业务空间专属域名（[地域与接入域名](https://help.aliyun.com/zh/model-studio/regions) / [Base URL 总览](https://www.alibabacloud.com/help/zh/model-studio/base-url)）。

**已定方向（2026-10-28）：走千问 AI 平台，废弃百炼 key。** 官方文档已核实四件事，拿到 key 即可直接开工：

| 事实 | 出处 | 对本项目的影响 |
|---|---|---|
| 千问平台提供 **OpenAI 兼容 embeddings**，支持 `text-embedding-v4` / `text-embedding-v3` | [OpenAI 兼容文本向量](https://platform.qianwenai.com/docs/api-reference/text-embedding/openai-embedding) | **一条 key 同时喂 LLM + embedding**，`OpenAIEmbeddings(base_url=...)` 零改造可用，决策 5a 的首选路径成立 |
| API Key 在 platform.qianwenai.com 的「API Key」页面创建；模型无需手动开通 | [首次调用](https://platform.qianwenai.com/docs/developer-guides/getting-started/first-api-call) | 不存在「忘了开通模型服务」这类坑 |
| **Key 不绑定模型**，同一个 key 可调所有模型，用免费额度无需另建 key | [免费额度](https://platform.qianwenai.com/docs/resources/free-quota) | 换模型只改 `.env` 的 `LLM_MODEL` |
| OpenAI 兼容接口**不支持稀疏向量**（`output_type=sparse` 要走 DashScope 原生接口） | 同上 embedding 文档 | 我们用 dense 向量 + cosine，无影响；别去配 sparse 参数 |

另外 `qwen3.8-flash` 支持 `enable_thinking` / `preserve_thinking` / `reasoning_effort`（[模型卡](https://www.modelscope.cn/models/Qwen/Qwen3.8-Flash-Next)）——RAG 生成阶段建议**关掉 thinking**（省延迟），V2 的 Grade 节点若要更强判断可单独开。

**解锁需要二选一**：
- A. 继续用百炼 → 到百炼控制台新建/启用 API Key，base_url 用控制台给出的那个（`[workspace-id].cn-beijing.maas.aliyuncs.com/compatible-mode/v1`）
- B. 改用千问 AI 平台 → 用该平台签发的 Key 配 `https://cn-beijing.maas.qianwenaiapi.com/compatible-mode/v1`，并确认它是否提供 `text-embedding-v4`（若不提供，embedding 需另找一家，见决策 5a）

补充：`enable_thinking=True` 时流式 chunk 的 delta 会分 `reasoning_content`（思考）与 `content`（回复）两个字段，且存在 `choices` 为空的 chunk——V1 的 SSE 生成逻辑必须跳过空 choices 并只转发 `content`（思考过程若要展示需单独事件类型）。

待人工确认（百炼控制台）：① 这条 key 是否仍为「启用」状态；② 账号是否已开通模型服务且无欠费；③ 若新建 key，注意**国际站与中国站的 Key 与域名不能混用**，套餐类 Key（Token/Coding Plan）只能走各自专属域名。
| **踩到的坑 2** | `langchain-community` 官方日落（issue #674）。`PyPDFLoader` 实测**只有** `langchain_community.document_loaders` 提供；`langchain_classic.document_loaders` 只是转发并打警告（实际模块仍是 community）；`langchain.document_loaders` 在 1.2 已不存在 → 见决策 5b |

---

### 1.7 V1.0 真实端到端验收（2026-10-28，已通过）

语料：用户放入的 `民间菜谱.pdf`（112 页，pdfFactory 2006 年排版）+ 自造 `sample-handbook.md`。

```
[i] 抽取切分得到 112 个 chunk（1.1s）
[i] 集合总数 112 / space=cosine
[ 0.27s] sources 帧: 4 条 -> sample-handbook.md(0.438), 民间菜谱.pdf#5(0.263), ...
[ 1.03s] 首个 token: 需提供
[ 1.23s] done 帧
答案（23 字，5 个 token 帧）: 需提供发票原件与行程单，审批周期为五个工作日。
[OK] V1.0 端到端验收通过
```

判定：检索首命中即正确文档；token 分多次到达（首 1.03s / 末 1.23s）→ 确为流式而非缓冲；答案完全来自资料未编造。离线 `pytest -q` → **27 passed**；前端 `npm run build` → 18 modules / 70.59 kB。

验收时又踩到三个真 bug（已修，别退回去）：

| 坑 | 现象 | 修法 |
|---|---|---|
| `enable_thinking` 放在 `model_kwargs` | `TypeError: AsyncCompletions.create() got an unexpected keyword argument 'enable_thinking'` | 必须走 **`extra_body`**（`ChatOpenAI.extra_body` 字段存在，已用 model_fields 确认） |
| 引用来源是绝对路径 | UI 会显示 `D:\...\民间菜谱.pdf` | `Hit.source` 统一 `Path(...).name`；文本语料无页码 → `page=None`，前端 `v-if` 已兜住 |
| `--limit` 截断把答案切没了 | 只入库前 24 chunk 时排在最后的 md 语料没进库，检索全是菜谱页且分数仅 0.26 | `load_dir` 是 PDF 先、文本后；smoke 默认改**全量入库** |

启动方式已固化为 **`.doc\start.bat`（双击即用）**，四种模式：`start.bat` 单端口 :8000 / `start.bat dev` 前后端分离热更新 / `start.bat ingest` 重建向量库 / `start.bat check` 环境自检。它绕开 `conda activate`，直接定位 `conda info --base` 下的 `envs\langchain1.2\python.exe`，因此资源管理器双击也能起来。已实测：自检通过（识别到 pdf_docs 112 条）、uvicorn 真实 HTTP 下 `/api/health`、静态首页、422 校验全部正常。

写 bat 时踩到一个新坑：**批处理必须 CRLF**。用脚本生成 `.bat` 时若写成 LF-only，cmd 会逐行误解析（表现为 `'il' is not recognized`、`@echo off` 失效把 PATH 打出来）；同时必须 **UTF-8 无 BOM**（带 BOM 会让首行变成 `'\ufeff@echo'` 未知命令），再配 `chcp 65001` 才能正常显示中文。

**端口与启动脚本的两个坑（2026-10-28 复盘）**：

| 坑 | 现象 | 修法 |
|---|---|---|
| `start.bat` 无条件打开 5173 | 单端口模式下 5173 没人监听 → 浏览器空白，误以为前端坏了 | 改成 `if defined FORCE_DEV` 才开 5173，否则开 8000（已用 echo 版脚本验证两种模式各指向正确端口） |
| `Start-Process -FilePath 'npm'` | 报 `%1 不是有效的 Win32 应用程序`——npm 是 `.cmd` 包装脚本，不是 exe | 必须写 `npm.cmd`（`start-dev.ps1` 已修；bat 里用 `cmd /k npm run dev` 不受影响） |

一句话记住：**5173 是 vite dev server，只有 `start.bat dev` 才存在；8000 是 FastAPI，因为挂了 StaticFiles 所以自带构建好的界面**。两者是替代关系，不是都要开。

### 1.7b 前端「收到 token 却不显示」的真凶（Vue 3 raw/proxy 陷阱）

现象：`/api/chat` 200，SSE 帧完整到达（sources → 5 个 token → done），界面却一直空白。

原因：`const reply = {...}; messages.value.push(reply)` 之后一直改 `reply.text`。
`ref([])` 底层是 `reactive`，push 进去的普通对象会被包成**代理**，但 `reply` 仍指向**原始对象**；
改原始对象不会走 set 陷阱 → 不触发任何渲染。已从数组取回代理即修复：

```js
messages.value.push({ role: "assistant", text: "", ... })
const reply = messages.value[messages.value.length - 1]   // ← 必须用这个代理
```

结论用 `node + 项目自带的 vue`（`reactive`/`ref` + `effect`）实测证明：改原始对象时渲染值恒为 `""`，改代理则正确拼出完整答案。**V2 加「思考路径」徽章、V3 加 wiki 侧栏时，凡是在异步回调里累加状态，都必须走代理，别留原始引用。**

### 1.7c 批处理不能带中文（UTF-8 + chcp 65001 会让 cmd 解析错位）

`start.bat` 里的中文 REM 注释触发了：

```
'♦端，单端口' is not recognized as an internal or external command
'后端' is not recognized as an internal or external command
```

cmd.exe 读批处理按**字节偏移**定位行，UTF-8 多字节序列会让指针漂移，把一行的中段当新命令执行。`chcp 65001` 只影响显示、救不了解析。
最终方案：**bat 全文 ASCII**（非 ASCII 字节数已校验为 0），中文说明留在 UI 与本文档里。

已用「替身命令干跑」验证三种模式分支都正确：默认只开 `127.0.0.1:8000`；`dev` 才启动 vite 并开 `localhost:5173`；`ingest` 先重建向量库。同时修掉上一版「无条件打开 5173」的 bug，以及 `start-dev.ps1` 里 `Start-Process -FilePath 'npm'` 必须写成 `npm.cmd`（npm 是 .cmd 包装脚本，直接当 exe 启动会报「不是有效的 Win32 应用程序」）。

### 1.8 模型切换（V1.0 追加，已实测）

前端下拉框可直接切 `qwen3.8-flash` / `qwen3.8-max`，实现方式是**后端白名单**而非前端硬编码：

| 环节 | 做法 |
|---|---|
| 配置 | `.env` 的 `LLM_MODEL`（默认）+ `LLM_MODELS`（候选，逗号分隔）→ `Settings.model_choices` 去重保序 |
| 发现 | `GET /api/models` 返回 `{default, models}`，前端下拉动态填充，不写死模型名 |
| 校验 | `resolve_model()`：留空=用默认；不在白名单 → 400 且报错里列出可选项，乱填的模型名打不到上游 |
| 透传 | `ChatRequest.model` → `make_chat_model(model=...)`；`utils/sse.js` 仅在有值时才带 `model` 字段 |
| 体验 | 选择存 `localStorage`；每条回答下方标注实际使用的模型 |

真实 uvicorn 对比（同一问题、检索首条同为 sample-handbook.md 0.438）：

```
qwen3.8-flash   首token 1.12s  总 1.31s  23字  需提供发票原件与行程单，审批周期为五个工作日。
qwen3.8-max     首token 0.77s  总 1.24s  44字  差旅报销需要提供**发票原件与行程单**，审批周期为**五个工作日**（超期不予受理）。
越界校验 gpt-9 -> HTTP 400 {"detail":"不支持的模型 gpt-9，可选：qwen3.8-flash, qwen3.8-max"}
```

max 更详尽且主动用 Markdown 强调；flash 更短平。离线测试增至 37 passed。

排查时抓到一个**测试基础设施的坑**（不是产品 bug）：`TestClient` 每次 `stream()` 会另起事件循环，第二次请求可能报 `RuntimeError: Event loop is closed`（langchain 缓存的 async client 被上一个循环绑死）。真实部署是单循环长驻，不受影响。所以 `scripts/compare_models.py` 加了 `--server` 模式打真实 uvicorn，判定以 `--server` 结果为准；V2 写 LangGraph 异步图测试时同样要避开这个陷阱。

另：该 PDF 抽取质量一般（出现 `要要要`、`窑` 这类排版字符错位），正好印证 §5「中文 PDF 抽取乱码」风险——V1.5 换 `pymupdf4llm` 只需改 `loader.load_pdf` 一个函数。

---

## 2. V1.0 —— 全栈基础 RAG（跑通闭环）

验收标准：前端提问 → 打字机流式输出答案 → 能展示引用来源；换一个 PDF 重新入库后答案跟着变。

### 2.0 环境方案（conda）：复用现有 `langchain1.2` env

实测结论（2026-10-28）：

| 事实 | 影响 |
|---|---|
| `langchain1.2` = Python 3.13.12 + langchain 1.2.12 + langgraph 1.1.10 | 与决策 3 的主线一致，**可复用**；langgraph 已就位，V2 少装一步 |
| 包确实装在该 env（`envs\langchain1.2` 内有 langchain* 目录，base 的 site-packages 没有） | env 结构正常，当初是在该 env 内用 pip 装的 |
| **本机所有 conda env 的 site-packages 都是只读**（连 base 也是） | 当初用了管理员 PowerShell 装东西导致属主变 Administrators。这是与「用哪个 env」无关的共性问题，**必须先修 ACL** |
| Python 3.13 偏新，chromadb 及其依赖（onnxruntime / rust 轮子）在 3.13 未必有预编译包 | **唯一实质风险**：装 chromadb 若报源码编译失败，就退回下方备选方案 |

采用「复用」路线的步骤：

- [ ] 一次性修 ACL（管理员 PowerShell，`*S-1-5-32-544` 是 Administrators 的 SID，比本地化名称稳；PowerShell 里 Set-Acl + NTAccount 容易踩坑，所以用 icacls）：
  icacls "D:\study\miniconda\envs\langchain1.2" /grant "*S-1-5-32-544:(OI)(CI)F" /T /C /Q
  icacls "D:\study\miniconda\envs\langchain1.2" /grant "LILY\Walt:(OI)(CI)M" /T /C /Q
- [ ] 关掉管理员窗口，在**普通** PowerShell 里 `conda activate langchain1.2`，先试装一个小包验证可写，成功再继续
- [ ] 补齐本项目依赖：`pip install "fastapi>=0.115" "uvicorn[standard]" langchain-openai langchain-community langchain-chroma chromadb pypdf sse-starlette pytest httpx`（langchain/langgraph 已在，不用重装）
- [ ] `pip show langchain langgraph langchain-chroma chromadb | Select-String Name,Version` → 把实际版本写进 `backend/requirements.txt`（用 `langchain<2`、`langgraph<2` 这种上界锁），README 标注「基于 langchain 1.x + Python 3.13」
- [ ] `environment.yml` 改为 `name: langchain1.2` + `python=3.13` + `pip: -r backend/requirements.txt`，保留一键复现能力（CI 里照样能 `conda env create -f environment.yml`）
- [ ] IDE 解释器指向 `D:\study\miniconda\envs\langchain1.2\python.exe`；启动脚本统一 `conda run -n langchain1.2 ...`

备选方案（chromadb 在 3.13 装不上，或将来想要项目隔离时启用）：

- [ ] `conda create -p .conda-env python=3.12 -y`：env 落在项目目录内，**免管理员**、不碰 miniconda 权限；`.gitignore` 加 `.conda-env/`，换机靠 environment.yml 重建
- [ ] 一旦走这条，把上文所有 `langchain1.2` 替换为 `.conda-env`，并同步改 `scripts/*.ps1` 里的 `conda run -p .conda-env ...`
- [x] 离线回归：`cd backend; pytest -q` → **16 passed / 1 skipped**（skip 的那条等 data/pdfs/ 出现真实 PDF 会自动启用）

### 2.1 后端（FastAPI + LangChain 1.x + Chroma）

- [x] config.py（`app/config.py`）：Settings 读 backend/.env，路径以 backend/ 为基准 resolve，避免从不同目录启动时找不到 chroma
- [x] rag/loader.py：PyPDFLoader + `RecursiveCharacterTextSplitter`（separators 已中文化并 `keep_separator=True`）；**额外支持 .txt/.md**（`load_dir(kinds=...)`），V3 写 wiki 直接复用
- [x] rag/vectorstore.py：`build_store()` 强制 `collection_metadata={"hnsw:space":"cosine"}` 并**自检 space**（不是 cosine 直接 raise）；`search()` 统一用 relevance 且 clamp01；`reset_collection()` 保证入库幂等；页码统一 +1 输出
- [x] rag/ingest.py：`python -m app.rag.ingest [--pdf-dir --chroma --kinds --chunk-size]`，幂等已由测试证明（重复入库集合总数不变）
- [x] 冒烟已由 `tests/test_e2e_offline.py` 自动化（语料 → ingest → search 全链路，离线 embedding）；等你放入真实 PDF 后 `test_pdf_fixture_test_runs_when_corpus_present` 会自动启用真实 PDF 分支
- [x] api/chat.py：POST /chat，检索 → 拼 context → `astream()` 逐 token yield，已实测通过（见 §1.7）。SSE 帧：
  ```text
  data: {"type":"sources","refs":[{"file":"xx.pdf","page":3}]}
  data: {"type":"token","text":"答"}
  data: {"type":"done"}
  ```
- [x] 异常也走 SSE（实测验证：LLM 报错时前端仍收到 error + done 两帧，不会挂住）
- [x] CORS 允许 localhost:5173；另加 `/api/health`；`frontend/dist` 存在时自动挂 StaticFiles → **单端口 :8000 即可同时跑 UI 和 API**

### 2.2 前端（Vue3 + Vite）

- [x] 前端脚手架已完成（2026-10-28）：Vue 3.5.44 + Vite 8.3.5，**JS 版模板**（main.js / vite.config.js，无 TS）→ 后续一律写 .js，别照抄 TS 教程的泛型签名
- [x] **零新增 Markdown 依赖**：`utils/markdown.js` 先整体转义 HTML 再做少量替换，省掉 markdown-it + dompurify；clone 后仍需在 `frontend/` 执行 `npm ci` 安装 Vue/Vite 等项目依赖
- [x] utils/sse.js：fetch + getReader + TextDecoder，buffer 只在遇到空行才切帧（半帧缓存已处理），末尾残留也兜底解析
- [x] ChatWindow.vue + MessageBubble.vue：sources 先到即渲染来源 chip（含分数），token 逐个追加 + 光标闪烁；空态给 3 个示例问题
- [x] MessageBubble.vue：Markdown 渲染（自研零依赖版，支持代码块/行内码/加粗/列表/链接），来源 chip 含分数
- [x] 停止生成已实现（AbortController，AbortError 转成「已停止生成」提示）
- [x] vite.config.js 已加 server.proxy：把 '/api' 转 http://127.0.0.1:8000，前端只请求相对路径（省掉生产环境 CORS）

里程碑：V1 已合入 `main`；当前远端标签为 `v0.2`，未额外补打 `v0.1`。启动方式见 `.doc/start.bat`，示例使用方式见 `data/pdfs-example/README.md`。

---

## 3. V2.0 —— LangGraph 状态机 + 自我纠错

验收标准：构造一个「PDF 里根本没有」的问题，系统能自动 Rewrite Query 重试，最终如实回答「资料中未提及」，而不是硬编；日志能看到 retrieve → grade → rewrite → retrieve → grade → generate 的完整路径。

### 3.1 图设计

```text
        ┌────────────────────────────────┐
        │                                │ (不相关且未超次数)
START → Retrieve → Grade ──相关──→ Generate → END
                        ↑   │
                        │   └──不相关且已达上限──→ Generate(兜底话术)
                    Rewrite
```

- State（TypedDict）：question, rewritten_query, docs, grade, n_rewrites, answer
- Retrieve：用 rewritten_query or question 检索
- Grade：LLM 结构化输出 {"relevant": true/false}，对每个 doc 单独打分，命中 ≥1 篇即算通过；用 with_structured_output 保证解析稳定
- Rewrite：HyDE 风格——让 LLM 把问题改写成更利于检索的表述/拆成子问题，n_rewrites += 1
- 条件边：route_after_grade(state) -> "generate" | "rewrite"；MAX_REWRITES = 2 必须硬限，防死循环
- Generate：流式生成；兜底路径输出「当前资料未覆盖该问题」模板

### 3.2 工程改造

- [x] langgraph 已在 §2.0 一并安装（≥1.1,<2），确认写进 requirements.txt 与 environment.yml 的 pip 段
- [x] 事件流按 1.x 实测：V2 开工先写探针打印 `graph.astream_events()` 事件名（1.x 与 0.3 不同，凭记忆猜必踩空）——实测自定义节点只产生 `on_chain_start/stream/end`，拿不到 `on_chat_model_stream`；且 `stream_mode="updates"` 要等节点跑完才吐。最终改用**节点内 `get_stream_writer()` + `stream_mode="custom"`**（见 §3.3）
- [x] api/chat.py 改为消费 `rag_graph` 的 custom 流，把 frames 原样转成 SSE —— 对前端协议零变更（只新增 trace 帧）
- [x] SSE 增加 `data: {"type":"trace","node":"grade"}` 帧，前端可选展示「思考路径」小徽章（MessageBubble 已展示路径 + 兜底标记）
- [x] pytest：mock LLM 打分，断言三种路由（直接生成 / 重写后生成 / 超限兜底）
- [x] docs/architecture.md 用 Mermaid 画出上面的图（实际落在 `.doc/architecture.md`，与 plan.md 同目录）

里程碑：`v0.2` 已发布至远端（2026-10-29 核对），V2 实现与验收记录见下节。

### 3.3 V2.0 实现与实测记录（2026-10-29）

| 项 | 结果 |
|---|---|
| 状态图 | `app/agents/rag_graph.py`：`retrieve → grade →(generate / rewrite)`，`rewrite` 回连 `retrieve`，`MAX_REWRITES=2` 由闭包硬限 |
| State | TypedDict：`question / rewritten_query / docs / relevant / n_rewrites / answer`；`docs` 存 `Hit`，节点返回局部更新 |
| Grade | `with_structured_output(GradeVerdict, method="function_calling")`。显式选 tool calling 是因为千问/智谱兼容层对 `json_schema` 支持不一；解析异常时退回「最高相似度 ≥ 0.30」的规则判断，避免单次判断失败导致整条请求 500 |
| Rewrite | `model.ainvoke()` 改写；异常时沿用旧 query，循环上限兜底 |
| 兜底生成 | 重写用尽仍不相关 → **不打 LLM**，直接流 `FALLBACK_ANSWER`（确定性、省额度） |
| 流式 | 节点内 `get_stream_writer()` 写 `sources / trace / token`，`graph.astream(stream_mode="custom")` 消费，帧顺序完全由节点决定 |
| 为什么不 `astream_events` | 探针实测：自定义节点在图里只有 `on_chain_*` 事件，没有 `on_chat_model_stream`；`updates` 模式又在节点结束后才吐，做不出打字机 |
| 帧协议 | 仅新增 `trace`（`node` + `relevant/reason/query/fallback`），`sources/token/error/done` 语义未改 |
| 离线测试 | `pytest -q` → **48 passed**（原 42 + 状态图 6 项） |
| 前端 | `npm run build` → 18 modules / 72.38 kB；气泡内新增「思考路径」与「资料未覆盖」标记 |
| 真实 LLM 验收 | **2026-10-29 已通过**（真实 uvicorn `:8000`，qwen3.8-flash，语料 112 chunk）：用例1 相关 → `retrieve → grade(relevant=True) → generate`，首 token 1.43s / 总 1.98s，sources 首条 sample-handbook 0.438；用例2 无答案 → `retrieve → grade(False) → rewrite ×2 → 兜底`，6.67s 返回「当前资料未覆盖该问题…」，全程无 error 帧 |


---

## 4. V3.0 —— LLM Wiki 记忆 + 工程化包装

验收标准：问一个已有高质量答案的问题，响应变快且引用来源标注为 wiki/...；本机不装 Docker 也能一条脚本命令拉起前后端；docker-compose.yml 作为可选交付物存在（CI 验证，不强求本机跑通）；README + 架构图达到可开源门面水平。

### 4.1 Write_Wiki 记忆闭环

- [ ] 图扩展：Generate → Reflect → (高价值) Write_Wiki → END
- [ ] Reflect：LLM 判断本轮 QA 是否值得沉淀（相关、完整、非闲聊），结构化输出 {worth, title, summary}
- [ ] Write_Wiki：写入 data/wiki/{slug}.md（frontmatter: title / question / sources / created_at），并 upsert 进 Chroma 独立 collection wiki_docs
- [ ] 优先检索：Retrieve 改为「先查 wiki_docs，命中且相似度过阈值 → 直接走 Generate（免 PDF 检索）；否则查 pdf_docs」——这就是「下次优先检索 Wiki」
- [ ] 去重：写前用 title 向量比对已有 wiki 条目，相似则更新（合并引用来源）而非新增，防止 wiki 灌水形成检索回声室
- [ ] GET /wiki 列表接口 + 前端侧栏展示沉淀条目（加分项，体现「记忆可见」）

### 4.2 工程化（无 Docker 版为主路径）

- [ ] scripts/start-dev.ps1：一条命令拉起后端与前端，Ctrl+C 一起退出；README「快速开始」以它为准
  ```powershell
  # 后端：conda run -n langchain1.2 uvicorn app.main:app --reload --port 8000（工作目录 backend/）
  # 前端：Push-Location frontend; npm run dev; Pop-Location
  ```
- [ ] scripts/ingest.ps1（conda run 重建向量库）、scripts/test.ps1（conda run -n langchain1.2 pytest backend/tests）
- [x] 可分发产物已验证：`npm run build` → dist/ 由 FastAPI StaticFiles 挂载，**单端口 :8000 同时提供 UI 与 API**（实测 GET / 返回 200 text/html，/api/* 不被 mount 抢占）
- [ ] backend/Dockerfile、frontend/Dockerfile、docker-compose.yml：仍按开源标准写好（compose：frontend 8080、backend 8000，./data 挂卷；nginx 反代 /api 记得 proxy_buffering off + chunked_transfer_encoding on）。容器内**不装 conda**，用 python:3.13-slim + pip 装 requirements.txt，保持镜像瘦；本机不构建，标注「可选，CI/有 Docker 环境验证」
- [ ] .github/workflows/ci.yml：actions/setup-python(3.11) + pip install -r backend/requirements.txt + pytest；加一条 docker compose build 冒烟（runner 自带 docker）。若要严格复现 conda，可换 mamba-org/setup-micromamba + `conda env create -f environment.yml`
- [ ] 依赖钉版本：每次 pip 装完就 `pip freeze > backend/requirements.txt` 并提交，环境坏了可用 environment.yml 原地重建
- [ ] .pre-commit-config.yaml（ruff）

### 4.3 开源门面

- [ ] README.md：一句话定位 → GIF/截图演示 → 亮点（自我纠错 + Wiki 记忆）→ 30 秒快速开始（conda env create -f environment.yml + scripts/start-dev.ps1 为主，Docker 作为可选路径）→ 架构图 → 路线图
- [ ] docs/architecture.md：整图（V1 数据流 + V2 状态机 + V3 记忆环）Mermaid
- [ ] LICENSE（MIT）、.github/ISSUE_TEMPLATE、贡献指南小节

里程碑：tag v1.0 并推送开源仓库。

---

## 4.9 多 Provider 与模型白名单（V1.0 追加，已实测）

千问与智谱是两套 base_url + key，单配置塞不下，因此改成 **Provider 列表**：

| 环节 | 做法 |
|---|---|
| 配置 | `.env` 的 `LLM_PROVIDERS` = 一行 JSON：`[{id,label,base_url,api_key,models[],supports_thinking}]` |
| 兼容 | 留空则自动把 `LLM_API_KEY/BASE_URL/MODEL/MODELS` 折叠成单个 `id=default` provider，老配置不用改 |
| 凭证路由 | `Settings.resolve_credential(model)` → 模型属于哪个 provider 就用哪个 key/base_url |
| thinking | `supports_thinking=false` 的 provider **完全不下发** `enable_thinking`（智谱不认该参数；实测 glm 的 delta 只有 `content`/`role`，无 `reasoning_content`） |
| 前端 | `/api/models` 返回 `groups`，下拉用 `<optgroup>` 按「千问 AI 平台 / 智谱 GLM」分组 |
| 白名单 | `resolve_model()` 现在校验 `all_models`（跨 provider 并集），乱填仍 400 |

真实 uvicorn 五模型对比（同一问题，检索首条同为 sample-handbook.md 0.39）：

```
qwen3.8-flash   首token  0.78s   总  0.82s  12字  需提供发票原件与行程单。
qwen3.8-max     首token  0.89s   总  1.10s  13字  需要提供发票原件与行程单。
glm-4-flash     首token  1.05s   总  1.27s  17字  差旅报销需要提供发票原件与行程单。
glm-4.7-flash   首token 42.64s   总 42.73s   9字  发票原件与行程单。      ← 思考型，慢到像卡死
glm-4.5-flash   首token  5.87s   总  6.01s   8字  发票原件与行程单
```

选型结论：**默认用 `qwen3.8-flash` 或 `glm-4-flash`**；`glm-4.7-flash` / `glm-4.5-flash` 是思考模型，首 token 分别 42.6s / 5.9s，V1 演示时容易被误认为卡住，留给 V2 的 Grade 节点做"慢但准"的判断更合适。GLM 免费模型另有 429（code 1305「访问量过大」）限流，实测确实会撞到。

`.env` 里 `LLM_MODEL` 等字段**是手改高危区**：本次就发生过编辑器用旧缓冲区覆盖 `.env`，导致 `LLM_MODEL` 被清空、`LLM_PROVIDERS` 整行消失、key 退回已废弃的百炼那条（长度 117 可作识别特征），表现为"模型列表为空"。已加 `startup` 自检：白名单为空或默认模型不在白名单内时直接打印 `[warn]`。`.env` 不进版本库，改完请跑 `start.bat check`。

---

## 5. 风险与预案

| 风险 | 影响 | 预案 |
|---|---|---|
| **langchain 1.x 生态漂移快（0.3 教程失效）** | import/事件名反复报错 | requirements.txt 锁 `>=1.2,<2` 上界；每次装包后 pip freeze 提交；报错先查 [v1 迁移指南](https://docs.langchain.com/oss/python/migrate/langchain-v1) 再搜旧答案 |
| conda 与 pip 混装导致依赖冲突 | env 损坏、装包卡死 | 决策 2：conda 只管 Python，包全走 pip；env 坏了用 `conda env create -f environment.yml` 重建（成本低，几分钟） |
| `conda activate` 在脚本/CI 里失效 | 启动脚本跑错 Python | 一律用 `conda run -n langchain1.2 ...`；CI 用 setup-python 不依赖 conda |
| 大模型 API 网络/额度不稳 | 联调中断 | 统一 OpenAI 兼容层，.env 一键换厂商；关键节点留 mock 测试开关 |
| SSE 经过代理/nginx 被缓冲 | 打字机失效 | Vite proxy 与 nginx 均显式关闭 buffering；用 curl -N 先验后端 |
| Grade 节点打分不稳定 | 路由乱跳 | 结构化输出 + temperature=0 + 相似度阈值先过滤一道作为规则兜底 |
| Rewrite 死循环 | 请求超时 | MAX_REWRITES=2 硬上限 + LangGraph recursion_limit |
| Wiki 低质条目污染检索 | 越用越笨 | Reflect 严门槛 + 去重更新 + GET /wiki 可人工删 |
| 中文 PDF 抽取乱码/断行 | 检索质量差 | 切分器 separators 中文化；必要时换 mineru/unstructured 后端 |
| 无 Docker，compose 无法本机验证 | 交付物可能带错 | 主路径用脚本启动 + StaticFiles 单进程托管；compose 交给 CI 验证，README 明示「未在本机验证」 |

---

## 6. 里程碑时间线（建议 3 周）

| 阶段 | 内容 | 预估 |
|---|---|---|
| W0 | **已完成（2026-10-28）**：修 ACL ✔ / 补齐依赖 ✔ / requirements.txt ✔ / Chroma 冒烟 ✔；剩 1 项：embedding 选型（决策 5a） | 0.5 天 |
| W1 | **V1.0 已完成并通过真实端到端验收（2026-10-28）**，见 §1.7；代码已合入 `main` | 5 天 |
| W2 | **V2.0 已完成**：LangGraph + Grade/Rewrite + 测试；远端已有 `v0.2` | 4–5 天 |
| W3 | V3.0 Wiki 记忆 + 脚本化启动 + compose（可选）+ README/架构图 → tag v1.0 | 4–5 天 |

执行原则：每个版本结束后系统必须可运行、可演示，禁止出现「重构中途跑不起来」的中间态；版本升级不破坏前端 SSE 协议。

---

## 7. 立即下一步

1. ✔ 复用 conda `langchain1.2`；不需要重新初始化 Git 或新建环境。
2. ✔ V1 全栈 RAG、模型切换与 SSE 已完成；V2 自我纠错状态图与前端路径展示已完成，远端已有 `v0.2`。
3. ✔ 本地资料放 `data/pdfs/`，整目录排除；可分发示例放 `data/pdfs-example/`，使用方法见该目录 README。
4. ✔ `.doc/example/`、真实密钥、向量库、本机诊断脚本和构建产物均不提交。
5. 试用现有版本：`.doc\start.bat` 访问 `http://127.0.0.1:8000`；开发前端用 `.doc\start.bat dev` 访问 `http://localhost:5173`。
6. 新增或更新本地语料后无需手动操作：`.doc\start.bat` 启动前会用语料指纹（文件名/大小/mtime/切分参数）比对 `data/chroma/corpus_stamp.json`，有变化才重建索引（会调用 Embedding API）；`.doc\start.bat ingest` 可强制全量重建。
7. 后续按 §4 实现 V3 Wiki 记忆闭环与开源文档；沿用 conda 与脚本启动，不依赖 Docker。
