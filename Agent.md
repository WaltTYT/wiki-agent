# Agent.md

> 本文件是 coding agent 在 `wiki-agent` 仓库工作的约束说明。内容基于 2026-10-28 的**实测结果**，不是通用模板。
> 项目演进计划见 `.doc/plan.md`（含 V1.0 验收记录 §1.5–§1.9 与踩坑复盘）。

## 1. 项目概述

### 1.1 项目名称

`wiki-agent` —— 带自我纠错与知识沉淀能力的 RAG 问答系统（当前进度：**V2.0 已完成，待用户验收后打 tag v0.2**）。

### 1.2 技术栈

| 层级 | 技术 | 版本（实测） | 说明 |
|------|------|-----------|------|
| 后端框架 | FastAPI | 0.162.0 | 提供 `/api/chat`（SSE）、`/api/models`、`/api/health` |
| Agent 框架 | LangChain / LangGraph | 1.2.12 / 1.1.10 | LangGraph 用于 V2 状态图（retrieve/grade/rewrite/generate） |
| 向量库 | ChromaDB + langchain-chroma | 1.5.9 / 1.1.0 | 本地持久化 `data/chroma/`，无独立服务 |
| 运行时 | Python | 3.13.12 | conda env **`langchain1.2`**（不是 venv） |
| 前端框架 | Vue | 3.5.44 | **JS 版模板**，非 TypeScript |
| 构建工具 | Vite | 8.3.5 | `@vitejs/plugin-vue` 6.0.10 |
| LLM | 千问 AI 平台 / 智谱 GLM | 多 Provider | 见 §4 与 §9 |
| Embedding | text-embedding-v4 | — | 中文检索实测 4/4 命中 |

### 1.3 架构

- **模式**：前后端分离，但支持**单端口一体化**——`frontend/dist` 存在时由 FastAPI `StaticFiles` 挂载，只跑 :8000 即可。
- **通信**：`POST /api/chat` → **SSE 流式**（自定义帧协议，见 §5.5）。前端用 `fetch + ReadableStream` 手动解析，**不用 EventSource**（后者不支持 POST）。
- **数据流（V2.0）**：PDF/MD/TXT → `loader` 切分 → `text-embedding-v4` 向量化 → Chroma(cosine) → `retrieve → grade →(不相关) rewrite / (相关) generate` 状态机 → LLM 流式生成。
- **外部依赖**：仅两个 HTTP API（千问、智谱）。**无数据库、无 Redis、无 Docker、无消息队列**。
- **演进路线**：V3.0 在图尾部加 `Reflect → Write_Wiki → END`，并把 retrieve 改成「先查 wiki_docs、过阈值即直答」。

## 2. Agent 规则

### 2.1 基本原则

- 按用户要求执行，保持变更聚焦；优先编辑现有文件。
- **未经用户明确允许，不 `git commit`、不 `git push`、不删除项目文件。**
- 安装依赖、调用付费/联网 API、改动 conda 环境等**有外部影响的操作，先说明开销再征得同意**。
- 不泄露、打印、提交任何 API Key。展示密钥时一律脱敏（前 4 后 4 + 长度）。
- 本机 `conda` 的 `envs/` 属主是 Administrators，**agent 的沙箱账户对它无写权限**：装包必须由用户在普通 PowerShell 执行，不要反复重试。

### 2.2 环境铁律（违反会直接跑不起来）

- **只用 conda env `langchain1.2`，不要引入 venv/poetry/uv**，也不要把环境名改成 `wiki-agent`（与项目同名易混）。
- **conda 只管 Python，包全走 pip**。禁止 `conda install` 与 `pip install` 混装同一批包。
- **不要新增 Docker 依赖**。本机未安装 Docker；`docker-compose.yml`/`Dockerfile` 是 V3 的可选交付物，本机不构建不验证。
- 脚本内调用一律 `conda run -n langchain1.2 ...` 或直接 `...\envs\langchain1.2\python.exe`，不依赖 shell 是否 `conda activate` 成功。

### 2.3 验证要求

- 改后端必跑：`cd backend && python -m pytest tests -q`（当前基线 **48 passed**，只增不减）。
- 改前端必跑：`cd frontend && npm run build`（构建失败即语法/模板错误）。
- 涉及真实 API 的行为，**以真实 uvicorn 为准**，不要信 TestClient 的流式结果（见 §9）。
- **不要凭记忆猜第三方库的参数**。本项目已多次因"看起来合理的 API"翻车，一律先反射确认：
  `python -c "import inspect; from langchain_chroma import Chroma; print(inspect.signature(Chroma.__init__))"`

### 2.4 代码风格

- 后端：类型注解 + `from __future__ import annotations`；注释解释**为什么**（尤其是不明显的实测约束），不复述代码。
- 前端：Vue 3 `<script setup>` + JS；不引入 TypeScript 语法。
- 保持"单一改动点"约定：PDF 抽取只允许改 `app/rag/loader.py::load_pdf`，Prompt 只允许改 `app/agents/prompts.py`。

## 3. 项目结构

```text
wiki-agent/
├── Agent.md                      # 本文件
├── environment.yml               # conda 环境声明（name: langchain1.2）
├── .gitignore                    # 排除 .env、data/chroma/、node_modules/、scripts/_local/
├── .doc/
│   ├── plan.md                   # 三版本演进计划 + 实测验收记录与踩坑复盘（§1.5–§3.3）
│   ├── architecture.md           # V1/V2/V3 架构图（Mermaid，V2 已实现）
│   ├── start.bat                 # 一键启动（双击即用）
│   └── *.pdf                     # 论文参考资料（自适应 RAG、混合检索与 Agentic RAG）
├── backend/
│   ├── .env                      # 真实配置与密钥（不提交）
│   ├── .env.example              # 配置模板
│   ├── requirements.txt          # 上界锁版本（>=x,<2）
│   ├── app/
│   │   ├── config.py             # pydantic-settings + 多 Provider 解析
│   │   ├── llm.py                # make_chat_model（按 provider 决定是否下发 enable_thinking）
│   │   ├── schemas.py            # ChatRequest / ModelInfo / HealthResponse
│   │   ├── main.py               # FastAPI 入口、CORS、启动自检、StaticFiles 一体化
│   │   ├── api/chat.py           # /api/chat SSE（消费 V2 状态图）+ /api/models + 模型白名单校验
│   │   ├── agents/
│   │   │   ├── rag_graph.py      # V2 LangGraph 状态机 + 默认 grader + chunk_text
│   │   │   └── prompts.py        # 所有 Prompt 集中管理（V3 reflect 也放这里）
│   │   └── rag/
│   │       ├── embeddings.py     # Embedding 工厂（缺配置即 raise，禁止静默降级）
│   │       ├── loader.py         # PDF/MD/TXT 抽取与中文切分
│   │       ├── vectorstore.py    # Chroma 封装：强制 cosine、分数 clamp、幂等重建
│   │       ├── ingest.py         # python -m app.rag.ingest
│   │       └── search.py         # python -m app.rag.search "问题"
│   ├── scripts/
│   │   ├── check_embedding.py    # embedding 中文质量验证（4/4 才算过）
│   │   ├── smoke_live.py         # V1.0 真实端到端验收
│   │   ├── compare_models.py     # 跨 provider 模型对比（--server 模式为准）
│   │   └── _local/               # 本机一次性排查脚本，已 gitignore，勿提交
│   └── tests/                    # 48 项离线测试（不联网、不花 API 钱）
├── frontend/
│   ├── vite.config.js            # server.proxy: /api -> 127.0.0.1:8000
│   └── src/
│       ├── components/ChatWindow.vue     # 会话主界面 + 模型下拉
│       ├── components/MessageBubble.vue  # 气泡/来源 chip/所用模型
│       └── utils/
│           ├── sse.js                    # ReadableStream 分帧解析
│           └── markdown.js               # 零依赖 Markdown 渲染（先转义后替换）
├── scripts/start-dev.ps1         # PowerShell 版一键启动（带日志重定向）
└── data/
    ├── pdfs/                     # 语料：.pdf/.md/.txt（含示例 sample-handbook.md）
    ├── chroma/                   # 向量库持久化（不提交）
    └── wiki/                     # V3 知识沉淀目录（预留）
```

## 4. 关键配置文件

| 文件 | 用途 |
|------|------|
| `backend/.env` | 全部运行配置与密钥。**手改高危**：曾因编辑器旧缓冲区保存被整段覆盖，导致默认模型被清空、key 退回失效的百炼 key |
| `backend/.env.example` | 配置模板，字段变动必须同步更新 |
| `backend/requirements.txt` | 依赖上界锁（`langchain>=1.2.12,<2` 等），改依赖必须同步 |
| `environment.yml` | conda 复现入口（`conda env create -f environment.yml`） |
| `frontend/vite.config.js` | dev 代理，前端只请求相对路径 `/api/*`，因此**不需要**生产环境 CORS |
| `backend/tests/conftest.py` | 设 `LLM_PROVIDERS=[]` 做测试隔离，防止开发者本机 provider 配置漏进用例 |
| `.gitignore` | 已排除 `.env`、`data/chroma/`、`backend/scripts/_local/`、`node_modules/` |

### 4.1 环境变量

| 变量 | 说明 |
|------|------|
| `LLM_MODEL` | 默认模型，**必须**出现在 `LLM_PROVIDERS` 某 provider 的 `models` 里 |
| `LLM_TEMPERATURE` | 生成温度，默认 0 |
| `LLM_ENABLE_THINKING` | 默认 `false`（千问 qwen3.8 系列默认会思考，拖慢首字） |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODELS` | 单 Provider 兜底写法；`LLM_PROVIDERS` 留空时折叠成一个 provider |
| `LLM_PROVIDERS` | **一行 JSON**：`[{id,label,base_url,api_key,models[],supports_thinking}]` |
| `EMBEDDING_MODEL` / `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL` | 缺失时 `make_embeddings()` 直接 raise（决策 5a） |
| `EMBEDDING_BATCH_SIZE` | 默认 10；千问/百炼对 input 数组长度有上限 |
| `CHROMA_PATH` / `PDF_DIR` / `WIKI_DIR` | 相对路径以 `backend/` 为基准解析 |
| `RETRIEVAL_K` / `WIKI_SIM_THRESHOLD` / `CHUNK_SIZE` / `CHUNK_OVERLAP` / `MAX_REWRITES` | 检索与 Agent 行为参数 |

## 5. 安全基线

### 5.1 身份认证

- **当前无认证**：定位为本地开发/演示工具，仅监听 `127.0.0.1`。若将来对外暴露，必须先加鉴权与速率限制。`[待确认：是否需要多用户]`

### 5.2 输入验证

- `ChatRequest.question`：`min_length=1, max_length=2000`，越界由 FastAPI 返回 422（已测）。
- **模型白名单**：`resolve_model()` 校验 `all_models`，白名单外返回 **400 并在报错里列出可选项**，避免任意模型名打到上游产生费用。
- 错误信息长度截断（`[:400]`），不把堆栈原样吐给前端。

### 5.3 密钥与数据保护

- 密钥只存 `backend/.env`（已 gitignore）；`.env.example` 一律占位符。
- 任何日志、异常、文档、对话输出**不得包含完整密钥**；展示时脱敏。
- `backend/scripts/_local/` 内的排查脚本写死了本机路径与密钥文件位置，**已 gitignore，禁止提交**。

### 5.4 XSS 与 CORS

- `utils/markdown.js` 采用**先整体转义 HTML、再做少量替换**的顺序，因此不存在注入面；不要改成"先替换后转义"。
- CORS 仅放行 `http://localhost:5173` 与 `http://127.0.0.1:5173`，未使用 `*`。

### 5.5 SSE 帧协议（改动必须保持兼容）

```text
data: {"type":"sources","refs":[{"source":"x.md","page":null,"score":0.44}]}
data: {"type":"trace","node":"retrieve"}
data: {"type":"trace","node":"grade","relevant":false,"reason":"..."}
data: {"type":"trace","node":"rewrite","query":"改写后的检索词"}
data: {"type":"trace","node":"generate","fallback":false}
data: {"type":"token","text":"答"}
data: {"type":"error","message":"..."}
data: {"type":"done"}
```

- **`sources` 必须是第一帧**（前端拿到就渲染引用，离线测试也按这条断言）。
- `trace` 是 V2 新增：只新增 type，不改既有字段语义；`node` ∈ `retrieve|grade|rewrite|generate`，其余字段按节点可选。
- 只转发 `chunk.content`；**`reasoning_content` 一律丢弃**（qwen3.8 默认带思考）。
- 异常路径也必须以 `error` + `done` 收尾，否则前端永久挂起。
- 重写次数用尽仍不相关时，`generate` 帧带 `fallback:true`，随后是一条兜底 token（不调 LLM）。

## 6. 测试指南

### 6.1 后端测试（离线，默认必须全绿）

- 目录：`backend/tests/`，共 **48 项**，不联网、不消耗 API 额度。
- 命令：
  ```powershell
  conda activate langchain1.2
  cd backend
  python -m pytest tests -q
  ```
- 覆盖：embedding 缺配置必须 raise、Chroma space 必须 cosine、分数 clamp、入库幂等、SSE 帧序与异常收尾、思考内容不外泄、多 Provider 凭证路由、模型白名单 400、V2 三条路由（直接生成 / 改写后生成 / 超限兜底）与打分兜底。
- 状态图测试用 `tests/test_rag_graph.py` 注入假 grader / 假模型，**不要**为了测试去连真实 LLM。
- **不依赖 `pytest-asyncio`**：异步用例用 `asyncio.run()` 包装（该包在 requirements 里标为可选）。

### 6.2 前端测试

- 目前**无自动化测试**。最低验证：`cd frontend && npm run build` 通过。
- `[待确认：是否引入 vitest]`

### 6.3 手动 / 联网验证

| 目的 | 命令 |
|------|------|
| embedding 中文质量（4/4 才算过） | `python scripts/check_embedding.py` |
| V1.0 端到端验收 | `python scripts/smoke_live.py` |
| 跨 provider 模型对比 | `python scripts/compare_models.py --server http://127.0.0.1:8000` |
| 重新入库 | `python -m app.rag.ingest --kinds pdf,text` |
| 检索冒烟 | `python -m app.rag.search "某问题"` |

> 联网脚本会真实消耗 API 额度，执行前须征得用户同意。

## 7. 部署

### 7.1 所需服务

- 无数据库/无缓存/无容器。仅 conda 环境 + Node + 两个外部 HTTP API。
- 端口：后端 `8000`（uvicorn），前端 dev `5173`（vite）。

### 7.2 启动命令

```powershell
# 方式一（推荐，双击即用）
.doc\start.bat            # 单端口：http://127.0.0.1:8000
.doc\start.bat dev        # 前后端分离：http://localhost:5173
.doc\start.bat ingest     # 先重建向量库
.doc\start.bat check      # 只做环境自检

# 方式二（手工）
conda activate langchain1.2
cd backend
python -m app.rag.ingest --kinds pdf,text
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
cd ../frontend && npm run dev
```

### 7.3 构建

```powershell
cd frontend && npm run build     # 产物 dist/ 会被 FastAPI 自动挂载
```

### 7.4 Docker

- 本机**未安装 Docker**，`docker-compose.yml` 与两个 `Dockerfile` 属 V3 可选交付物，写完标注"未在本机验证"，验证交给 CI（ubuntu runner 自带 docker）。
- 容器内不装 conda，用 `python:3.13-slim` + pip。

## 8. 版本控制

- **远程仓库**：`https://github.com/WaltTYT/wiki-agent`（用户提供；`[待确认：本地尚未 init，无法验证该仓库是否已存在/是否为空]`）
- **本地 git 状态**：`git status` → **尚未 `git init`**（截至 2026-10-28）。首次初始化需用户确认。
- **当前分支**：`[待确认：初始化时确定，建议 main]`
- **推送策略**：未经用户明确许可，不 `commit`、不 `push`。
- **提交前必查**：`.env`、`data/chroma/`、`backend/scripts/_local/`、`node_modules/` 均已在 `.gitignore`；不得绕过。

### 8.1 提交格式规范

| 类型 | 格式 | 说明 | 示例 |
|------|------|------|------|
| 初始化项目 | `init(模块 : 初始化描述)` | 初始化项目结构、配置文件 | `init(all : 初始化默认模板文件)` |
| 增加功能 | `add(模块 : 功能描述)` | 添加新功能、新依赖、新文件 | `add(后端 : 添加redis)` |
| 修复bug | `fix(模块 : 修复描述)` | 修复问题、修正错误 | `fix(前端 : 修复图片尺寸限制)` |
| 删除内容 | `delete(模块 : 删除描述)` | 删除文件、移除无用代码 | `delete(前端 : 删除默认模板文件)` |
| 重构 | `refactor(模块 : 重构描述)` | 重构代码且不改变功能 | `refactor(后端 : 优化异常处理)` |
| 文档 | `docs(模块 : 文档描述)` | 更新文档 | `docs(README : 更新部署说明)` |

### 8.2 提交格式规则

- **模块标识**：使用 `后端`、`前端`、`all` 或具体模块名（如 `向量库`、`启动脚本`）。
- **分隔符**：模块与描述之间用 ` : `（两侧各一个空格）。
- **多提交**：用 ` && ` 连接多个类型，前后各一个空格。
- **示例**：`add(后端 : 支持多Provider模型切换) && fix(前端 : 修复SSE不渲染)`。
- 里程碑打 tag：V1.0 → `v0.1`，V2.0 → `v0.2`，V3.0 → `v1.0`。

## 9. 已知约束

### 9.1 硬性技术约束（都有实测依据，勿回退）

| 约束 | 原因 |
|------|------|
| Chroma 建集合必须显式 `collection_metadata={"hnsw:space":"cosine"}` | 默认 **l2**，`similarity_search_with_relevance_scores` 返回负数并告警，阈值判断失真 |
| relevance 分数比较前一律 `clamp01` | cosine 下实测出现 `-0.017` |
| `similarity_search_with_score` 返回的是**距离**（=1−相似度） | 与 relevance 量纲相反，代码统一只用 relevance |
| `OpenAIEmbeddings(check_embedding_ctx_length=False)` | 默认会把文本编码成 token id 数组，千问兼容层返回 `400 input must be an array of strings` |
| `enable_thinking` 必须走 `extra_body` | 放 `model_kwargs` 会 `TypeError: AsyncCompletions.create() got an unexpected keyword argument` |
| 智谱 provider 设 `supports_thinking=false` | GLM 不认该参数；其 delta 只有 `content`/`role` |
| Chroma 集合名 3–512 字符、首尾须字母数字 | 实测 `t1` 被 `InvalidArgumentError` 拒绝 |
| `langchain-chroma` 的 `Chroma.__init__` **没有** `delete_existing` | 幂等靠实例方法 `reset_collection()`；重建私有方法需 `getattr(store, "_Chroma__ensure_collection")()`（类外直接写会被名字改写） |
| 前端改响应式数组元素必须取回**代理**对象 | `const reply={...}; push(reply)` 后改 `reply.text` 不触发渲染（表现为"收到 token 却空白"） |
| `.bat` 必须 **ASCII + CRLF + 无 BOM** | UTF-8 中文会让 cmd 按字节偏移解析错位；BOM 会破坏首行 `@echo off` |
| `Start-Process` 启动 npm 要写 `npm.cmd` | npm 是 `.cmd` 包装脚本，报"不是有效的 Win32 应用程序" |
| 流式判定以真实 uvicorn 为准 | `TestClient` 每次 `stream()` 另起事件循环，第二次请求可能 `Event loop is closed` |
| LangGraph 1.x 自定义节点必须用 `get_stream_writer()` + `astream(stream_mode="custom")` | 实测 `astream_events` 对自定义节点只给 `on_chain_start/stream/end`，没有 `on_chat_model_stream`，拿不到 token；`updates` 模式要等节点跑完才吐，做不出打字机 |
| `with_structured_output` 显式 `method="function_calling"` | 千问/智谱兼容层对 `json_schema` 支持不一，tool calling 覆盖更广；解析失败必须退回规则判断，不能把请求打成 500 |
| `MAX_REWRITES` 用闭包写进条件边，不放 State | TypedDict 之外的 key 会被 LangGraph 丢掉；写进 state 的 `_max_rewrites` 不会生效 |

### 9.2 生态与数据限制

- `langchain-community` 官方**日落**（issue #674），但 `PyPDFLoader` 实测只有它提供（`langchain_classic` 仅转发、`langchain.document_loaders` 在 1.2 已删）。已收进 `loader.load_pdf` 单点，换 `pymupdf4llm` 只改这一个函数。
- LangChain 0.3/0.4 已被归为 Legacy，本项目跟随 1.x；**老教程与旧 StackOverflow 答案不可照抄**。
- 示例语料 `民间菜谱.pdf` 是 2006 年 pdfFactory 排版，抽取存在字符错位（`要要要`、`窑`），检索可用但脏。
- `pypdf` 无法生成带中文文本层的 PDF（WinAnsi 限制），故离线端到端测试用 `.md/.txt` 语料。
- `WIKI_SIM_THRESHOLD=0.68` 是按 `text-embedding-v4` 实测命中区间（0.565–0.748）校准的；旧值 0.82 会让 V3 的 wiki 快速通道永不触发。

### 9.3 模型与额度

- 千问平台 `/models` 提供 183 个模型；`qwen3.8-flash`（首字 ~0.8s）与 `qwen3.8-max`（~0.9s）实测可用。
- 智谱免费模型：`glm-4-flash` 首字 1.05s 正常；`glm-4.7-flash` **首字 42.6s**、`glm-4.5-flash` 5.9s（思考型，易被误判为卡死）；高峰期可能返回 **429 code 1305**。
- 百炼（`dashscope`）那条 CSV key 已失效（401），**不要**再往回改；Key 与 Base URL 必须同源，中国站/国际站/千问平台三套不通用。

## 10. Agent 自检清单

- [ ] 变更符合本文件约定（尤其 §2.2 环境铁律与 §9.1 硬性约束）
- [ ] 未打印、未提交任何密钥；`.env` 与 `scripts/_local/` 未进暂存区
- [ ] 第三方库的新参数已用 `inspect.signature` / `model_fields` 反射确认，不是凭记忆写的
- [ ] `cd backend && python -m pytest tests -q` 通过且用例数不少于 42
- [ ] 改过前端则 `cd frontend && npm run build` 通过
- [ ] SSE 帧协议保持向后兼容（只新增 type，不改既有语义）
- [ ] 涉及联网 API 的验证已征得用户同意，并说明额度开销
- [ ] 变更范围最小且聚焦，未夹带无关重构
- [ ] `commit` / `push` 前已获得用户明确许可，提交信息符合 §8.1
- [ ] 若改动了配置或依赖，已同步 `.env.example` / `requirements.txt` / `environment.yml` / `.doc/plan.md`