@echo off
chcp 65001 >nul
setlocal
set "REPO_DIR=%~dp0.."
cd /d "%REPO_DIR%"
if exist "%REPO_DIR%\.venv\Scripts\select-to-speech.exe" (
    "%REPO_DIR%\.venv\Scripts\select-to-speech.exe" %*
) else (
    uv run select-to-speech %*
)
endlocal
