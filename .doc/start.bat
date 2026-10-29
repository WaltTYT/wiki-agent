@echo off
setlocal EnableDelayedExpansion
title wiki-agent

rem ============================================================
rem  wiki-agent V1.0 launcher  (double-click to run)
rem
rem  start.bat          backend only, auto-reindex if corpus changed, open http://127.0.0.1:8000
rem  start.bat dev      backend + vite dev server, open http://localhost:5173
rem  start.bat ingest   force a full rebuild of the vector store first, then start
rem  start.bat check    environment self-check only, do not start servers
rem
rem  Stop: press Ctrl+C in this window.
rem  NOTE: keep this file ASCII-only. UTF-8 + chcp 65001 makes cmd.exe
rem        mis-parse multi-byte lines ("... is not recognized as ...").
rem ============================================================

set "ENV_NAME=langchain1.2"
set "PORT=8000"
for %%A in ("%~dp0..") do set "ROOT=%%~fA"
set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"

echo.
echo [wiki-agent] project root: %ROOT%

rem ---- locate python inside the conda env (avoid relying on conda activate) ----
set "CONDA_BASE="
for /f "delims=" %%I in ('conda info --base 2^>nul') do set "CONDA_BASE=%%I"
if not defined CONDA_BASE (
    echo   [X] conda not found on PATH
    goto :fail
)
set "PY=%CONDA_BASE%\envs\%ENV_NAME%\python.exe"
if not exist "%PY%" (
    echo   [X] env %ENV_NAME% not found. Existing envs:
    conda env list
    goto :fail
)
echo   [OK] python: %PY%

if not exist "%BACKEND%\.env" (
    echo   [X] backend\.env is missing.
    echo       Copy backend\.env.example to backend\.env and fill in your API key.
    goto :fail
)
echo   [OK] backend\.env present

if not exist "%FRONTEND%\dist\index.html" (
    if /I not "%~1"=="dev" (
        echo   [!] frontend\dist not built - falling back to dev mode
        set "FORCE_DEV=1"
    )
)

if /I "%~1"=="check" (
    echo.
    echo   [OK] environment check passed. vector store:
    pushd "%BACKEND%"
    "%PY%" -c "import chromadb;from app.config import get_settings;s=get_settings();c=chromadb.PersistentClient(path=str(s.chroma_dir));n=[(k.name,k.count()) for k in c.list_collections()];print('      collections:', n if n else 'EMPTY - run start.bat ingest first')"
    popd
    goto :end
)

if /I "%~1"=="ingest" (
    echo.
    echo [wiki-agent] rebuilding vector store...
    pushd "%BACKEND%"
    "%PY%" -m app.rag.ingest --kinds pdf,text
    set "RC=!ERRORLEVEL!"
    popd
    if not "!RC!"=="0" (
        echo   [X] ingest failed, aborted.
        goto :fail
    )
)

if /I not "%~1"=="ingest" (
    echo.
    echo [wiki-agent] checking corpus for new/changed files...
    pushd "%BACKEND%"
    "%PY%" -m app.rag.ingest --kinds pdf,text --if-changed
    set "RC=!ERRORLEVEL!"
    popd
    if not "!RC!"=="0" (
        echo   [!] corpus check failed - starting with the existing index
        echo       run "start.bat ingest" to rebuild manually
    )
)

if /I "%~1"=="dev" set "FORCE_DEV=1"
if defined FORCE_DEV (
    if not exist "%FRONTEND%\node_modules" (
        echo   [X] frontend\node_modules missing. Run: npm install  ^(in frontend dir^)
        goto :fail
    )
    echo [wiki-agent] starting vite dev server in a new window...
    start "wiki-agent-frontend" /D "%FRONTEND%" cmd /k npm run dev
)

rem ---- open only the port that is actually listening ----
if defined FORCE_DEV start "" /b cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:5173"
if not defined FORCE_DEV start "" /b cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:%PORT%"

echo.
echo   backend : http://127.0.0.1:%PORT%
if defined FORCE_DEV echo   frontend: http://localhost:5173
echo   stop    : Ctrl+C in this window
echo.
echo   Try asking:  annual leave / expense report / how the typewriter effect works
echo.

pushd "%BACKEND%"
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%
popd
goto :end

:fail
echo.
echo   Aborted. Fix the issue above and run again.
endlocal
pause
exit /b 1

:end
endlocal