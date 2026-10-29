# wiki-agent 架构（V2.0）

> 图用 Mermaid 编写，GitHub 与 VS Code（Mermaid 插件）可直接渲染。
> 版本演进与验收记录见 [plan.md](./plan.md)。

## 1. 部署与数据流总览

```mermaid
flowchart LR
    subgraph Browser["浏览器"]
        UI["Vue 3 ChatWindow<br/>fetch + ReadableStream"]
    end
    subgraph API["FastAPI :8000"]
        CHAT["POST /api/chat<br/>SSE 帧"]
        MODELS["GET /api/models<br/>模型白名单分组"]
        STATIC["StaticFiles<br/>frontend/dist"]
    end
    subgraph RAG["检索层"]
        EMB["text-embedding-v4"]
        PDF["Chroma: pdf_docs<br/>cosine"]
        INGEST["ingest CLI<br/>PDF/MD/TXT → chunk"]
    end
    subgraph LLM["OpenAI 兼容上游"]
        QWEN["千问 AI 平台"]
        GLM["智谱 GLM"]
    end

    UI -->|POST 问题| CHAT
    UI -->|拉取模型列表| MODELS
    STATIC -.->|单端口模式| UI
    CHAT -->|检索 query| EMB
    EMB --> PDF
    INGEST --> PDF
    CHAT -->|generate / grade / rewrite| QWEN
    CHAT -->|可切换 provider| GLM
```

## 2. V1.0 直线 RAG

```mermaid
flowchart LR
    START([START]) --> R[Retrieve<br/>top-k]
    R --> P[拼 Prompt<br/>资料 + 问题]
    P --> G[LLM astream<br/>逐 token]
    G --> END([END])
```

前端 SSE 帧：`sources → token… → done`。

## 3. V2.0 LangGraph 状态机（当前）

```mermaid
flowchart TD
    START([START]) --> R[retrieve<br/>用 rewritten_query 检索]
    R --> J{grade<br/>资料能回答问题?}
    J -- 相关 --> G[generate<br/>流式生成答案]
    J -- 不相关且 n_rewrites < MAX --> W[rewrite<br/>改写查询 n+1]
    W --> R
    J -- 不相关且已达上限 --> F[generate<br/>兜底话术]
    G --> END([END])
    F --> END
```

要点：

| 项 | 实现 |
|---|---|
| State | `question / rewritten_query / docs / relevant / n_rewrites / answer`（TypedDict） |
| Grade | LLM 结构化输出 `GradeVerdict{relevant, reason}`，`method="function_calling"`；失败退回相似度阈值 0.30 |
| Rewrite | HyDE 风格改写，最多 `MAX_REWRITES=2` 次，硬上限防死循环 |
| 兜底 | 重写用尽仍不相关 → 不调 LLM，直接流 `FALLBACK_ANSWER` |
| 流式 | 节点内 `get_stream_writer()` 写帧，图用 `astream(stream_mode="custom")` 消费 |

前端 SSE 帧（向后兼容，只新增 `trace`）：

```text
data: {"type":"sources","refs":[{"source":"hr.pdf","page":3,"score":0.438}]}
data: {"type":"trace","node":"retrieve"}
data: {"type":"trace","node":"grade","relevant":false,"reason":"..."}
data: {"type":"trace","node":"rewrite","query":"差旅报销 发票 审批"}
data: {"type":"trace","node":"retrieve"}
data: {"type":"trace","node":"grade","relevant":true,"reason":"..."}
data: {"type":"trace","node":"generate","fallback":false}
data: {"type":"token","text":"需提供"}
data: {"type":"done"}
```

## 4. V3.0 规划（虚线为未实现）

```mermaid
flowchart TD
    START([START]) --> R[retrieve]
    R --> J{grade}
    J -- 相关 --> G[generate]
    J -- 不相关 --> W[rewrite]
    W --> R
    J -- 超限 --> F[兜底]
    G --> REF[reflect<br/>是否值得沉淀]
    REF -- 高价值 --> WW[write_wiki<br/>data/wiki/*.md + wiki_docs]
    REF -- 普通 --> END([END])
    WW --> END
    F --> END
    R -.->|优先命中| WIKI[(Chroma: wiki_docs<br/>阈值 0.68)]
```
