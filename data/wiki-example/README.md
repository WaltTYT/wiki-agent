# Wiki 记忆示例（可公开）

这里演示 V3「Wiki 记忆」落盘后的真实文件格式，内容全部来自可公开的虚构语料
[`data/pdfs-example/sample-handbook.md`](../pdfs-example/sample-handbook.md)。

## 和 `data/wiki/` 的关系

| 目录 | 是否提交 | 用途 |
|---|---|---|
| `data/wiki/` | **不提交**（整目录 gitignore） | 运行时由 Reflect/Write_Wiki 自动写入，可能包含私有语料 |
| `data/wiki-example/` | 提交 | 只作格式说明与演示，不参与检索 |

## 文件格式

一篇记忆一个 `{slug}.md`，`slug = sha1(title)[:10]`（不含日期，保证同一标题跨天复用）：

```markdown
---
title: 差旅报销所需材料
question: 差旅报销需要提供哪些材料？
slug: 21a4f29508
created_at: 2026-10-30 10:00:00
updated_at: 2026-10-30 10:00:00
summary: 发票原件与行程单两样，审批五个工作日
sources: ["sample-handbook.md"]
---

## 问题

...

## 答案

...
```

- `sources` 是 JSON 数组，文件名带 `#页码` 时表示来自 PDF 的哪一页。
- 同目录的 `index.md` 由程序自动重建，列出全部条目标题与创建时间。

## 注意

把示例 md 直接拷进 `data/wiki/` **不会**让它们被检索命中——检索走的是 Chroma 的
`wiki_docs` 集合。示例的作用是让你看清格式；真实记忆请通过问答自动生成。
