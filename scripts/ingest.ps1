<#
重建向量库（plan §4.2）。

    .\scripts\ingest.ps1                # 语料指纹没变就跳过（推荐）
    .\scripts\ingest.ps1 -Force         # 强制全量重建（会调用 Embedding API）
    .\scripts\ingest.ps1 -EnvName xxx   # 换 conda 环境

与 start-dev.ps1 一致：直接调用 env 里的 python.exe，不依赖 `conda activate`。
#>
param(
    [switch]$Force,
    [string]$EnvName = 'langchain1.2'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'

function Say($m) { Write-Host "[ingest] $m" -ForegroundColor Cyan }
function Die($m) { Write-Host "[ingest] $m" -ForegroundColor Red; exit 1 }

$condaRoot = Split-Path -Parent (Split-Path -Parent (Get-Command conda.exe -ErrorAction SilentlyContinue).Source)
$py = Join-Path $condaRoot "envs\$EnvName\python.exe"
if (-not (Test-Path $py)) { Die "找不到 $py（先 conda env list 确认环境名）" }
if (-not (Test-Path (Join-Path $backend '.env'))) { Die '缺少 backend\.env，请复制 .env.example 为 .env 并填写密钥' }

$pyArgs = @('-m', 'app.rag.ingest', '--kinds', 'pdf,text')
if (-not $Force) { $pyArgs += '--if-changed' }

Push-Location $backend
try {
    Say ("python = $py")
    & $py @pyArgs
    if ($LASTEXITCODE -ne 0) { Die "入库失败（exit=$LASTEXITCODE）" }
    Say '完成。'
}
finally {
    Pop-Location
}
