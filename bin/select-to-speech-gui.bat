@echo off
chcp 65001 >nul
setlocal
set "REPO_DIR=%~dp0.."
if exist "%REPO_DIR%\src\ui\build\windows\x64\runner\Release\ui.exe" (
    start "" "%REPO_DIR%\src\ui\build\windows\x64\runner\Release\ui.exe" %*
) else (
    echo [!] Release binary not found. Running via Flutter runner...
    cd /d "%REPO_DIR%\src\ui"
    flutter run -d windows
)
endlocal
