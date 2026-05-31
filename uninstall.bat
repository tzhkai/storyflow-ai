@echo off
chcp 65001 >nul
title StoryFlow AI 卸载

set "INSTALL_DIR=%~dp0"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

echo.
echo 🗑️  卸载 StoryFlow AI...
echo.

:: 删开机自启
if exist "%STARTUP_DIR%\StoryFlow AI.lnk" (
    del /f /q "%STARTUP_DIR%\StoryFlow AI.lnk" >nul 2>&1
    echo    ✅ 开机自启已移除
)

:: 杀进程
taskkill /f /im python.exe /fi "WINDOWTITLE eq StoryFlow*" >nul 2>&1
echo    ✅ 服务已停止

:: 删虚拟环境
if exist "%INSTALL_DIR%venv" (
    rmdir /s /q "%INSTALL_DIR%venv" >nul 2>&1
    echo    ✅ 虚拟环境已删除
)

:: 删 VBS
if exist "%INSTALL_DIR%run_silent.vbs" (
    del /f /q "%INSTALL_DIR%run_silent.vbs" >nul 2>&1
)

:: 删日志
if exist "%INSTALL_DIR%server.log" (
    del /f /q "%INSTALL_DIR%server.log" >nul 2>&1
)

echo.
echo ✅ 卸载完成。StoryFlow 文件夹可手动删除。
echo.
pause
