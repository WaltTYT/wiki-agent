<#
跑后端离线测试（plan §4.2）。

    .\scripts\test.ps1                  # pytest -q
    .\scripts\test.ps1 -Filter wiki     # 只跑名字含 wiki 的用例
    .\scripts\test.ps1 -EnvName xxx

全部用假 embedding / 假模型，不联网、不花 API 额度。
#>
param(
    [string]$Filter = '',
    [string]$EnvName = 'langchain1.2'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'

function Say($m) { Write-Host "[test] $m" -ForegroundColor Cyan }
function Die($m) { Write-Host "[test] $m" -ForegroundColor Red; exit 1 }

$condaRoot = Split-Path -Parent (Split-Path -Parent (Get-Command conda.exe -ErrorAction SilentlyContinue).Source)
$py = Join-Path $condaRoot "envs\$EnvName\python.exe"
if (-not (Test-Path $py)) { Die "找不到 $py（先 conda env list 确认环境名）" }

$pyArgs = @('-m', 'pytest', 'tests', '-q')
if ($Filter) { $pyArgs += @('-k', $Filter) }

Push-Location $backend
try {
    Say ("python = $py")
    & $py @pyArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
