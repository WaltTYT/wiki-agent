# 示例知识库

`sample-handbook.md` 是虚构的员工手册，仅用于演示检索、引用来源与流式问答。

`data/pdfs/` 是本地语料目录，整个目录被 Git 忽略；这里的示例可以公开提交。`.doc/example/` 同样仅供本地使用。

在项目根目录的 PowerShell 中准备演示语料：

```powershell
New-Item -ItemType Directory -Path .\data\pdfs -Force | Out-Null
Copy-Item -LiteralPath .\data\pdfs-example\sample-handbook.md -Destination .\data\pdfs\sample-handbook.md
```

配置 `backend/.env` 中的模型与 Embedding 凭证、安装前后端依赖后，运行：

```powershell
.\.doc\start.bat ingest
```

该命令会重建当前语料索引并启动应用，入库会调用配置的 Embedding API。默认访问 <http://127.0.0.1:8000/>；开发模式用 `.\.doc\start.bat dev`，前端访问 <http://localhost:5173/>。

可以试问「员工每年有几天年假？」或「差旅报销需要哪些材料？」。手册内容不代表任何真实公司的制度。添加自己的 PDF、Markdown 或文本文件后，重新入库即可检索。
