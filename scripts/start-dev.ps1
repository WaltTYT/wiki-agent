<#
一键拉起 wiki-agent（无 Docker 主路径，plan §4.2）。

    .\scripts\start-dev.ps1            # 后端 :8000 + 前端 :5173
    .\scripts\start-dev.ps1 -Ingest    # 先重建向量库再启动
    .\scripts\start-dev.ps1 -BackendOnly

停止：在本窗口按 Ctrl+C（会一并结束子进程）
说明：刻意绕开 `conda run`——它是包装器，会派生真正的 python 子进程，
      Stop-Process 只能杀掉包装器，uvicorn 会变成孤儿进程占着 8000 端口。
      这里直接调用 env 里的 python.exe，杀得干净。
#>
param(
    [switch]$Ingest,
    [switch]$BackendOnly,
    [string]$EnvName = 'langchain1.2'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'

function Say($m) { Write-Host "[start-dev] $m" -ForegroundColor Cyan }
function Die($m) { Write-Host "[start-dev] $m" -ForegroundColor Red; exit 1 }

# 定位 conda env 的 python
$condaRoot = Split-Path -Parent (Split-Path -Parent (Get-Command conda.exe -ErrorAction SilentlyContinue).Source)
$py = Join-Path $condaRoot "envs\$EnvName\python.exe"
if (-not (Test-Path $py)) { Die "找不到 $py（先 conda env list 确认环境名）" }
Say "python = $py"

if (-not (Test-Path (Join-Path $backend '.env'))) { Die '缺少 backend\.env，请复制 .env.example 为 .env 并填写密钥' }

if ($Ingest) {
    Say '重建向量库...'
    Push-Location $backend
    & $py -m app.rag.ingest --kinds pdf,text
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { Die "入库失败（exit=$code）" }
}

$procs = @()
try {
    Say '后端 http://127.0.0.1:8000（日志 backend\uvicorn.log）'
    $be = Start-Process -FilePath $py -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000') `
        -WorkingDirectory $backend -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $backend 'uvicorn.log') -RedirectStandardError (Join-Path $backend 'uvicorn.err.log')
    $procs += $be

    if (-not $BackendOnly) {
        if (-not (Test-Path (Join-Path $frontend 'node_modules'))) { Die 'frontend\node_modules 不存在，先在 frontend 目录执行 npm install' }
        Say '前端 http://localhost:5173'
        $procs += Start-Process -FilePath 'npm.cmd' -ArgumentList @('run', 'dev') -WorkingDirectory $frontend -PassThru -WindowStyle Hidden
    }

    Start-Sleep -Seconds 3
    if ($BackendOnly) { Say '打开 http://127.0.0.1:8000 （dist 已构建时单端口即可看界面）' }
    else { Say '打开 http://localhost:5173 ；按 Ctrl+C 结束' }

    Wait-Process -Id $procs.Id -ErrorAction SilentlyContinue
}
finally {
    foreach ($p in $procs) {
        if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    }
    Say '子进程已清理。'
}