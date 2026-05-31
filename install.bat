@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title StoryFlow AI 一键安装

echo.
echo ╔══════════════════════════════════════╗
echo ║     📖 StoryFlow AI 一键安装        ║
echo ╚══════════════════════════════════════╝
echo.

set "INSTALL_DIR=%~dp0"
set "VENV_DIR=%INSTALL_DIR%venv"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

:: ===== Step 1: 找 Python =====
echo 🔍 检测 Python 环境...
set "PYTHON="

:: 尝试各种 python 命令
for %%p in (python python3 py) do (
    where %%p >nul 2>&1
    if !errorlevel!==0 (
        for /f "delims=" %%v in ('%%p --version 2^>^&1') do set "VER=%%v"
        echo    ✅ 找到: %%p — !VER!
        set "PYTHON=%%p"
        goto :found_python
    )
)

:: 检查常见安装路径
for %%d in (
    "%LOCALAPPDATA%\Programs\Python\Python313"
    "%LOCALAPPDATA%\Programs\Python\Python312"
    "%LOCALAPPDATA%\Programs\Python\Python311"
    "%LOCALAPPDATA%\Programs\Python\Python310"
    "C:\Python313" "C:\Python312" "C:\Python311"
    "%PROGRAMFILES%\Python313" "%PROGRAMFILES%\Python312"
) do (
    if exist "%%~d\python.exe" (
        set "PYTHON=%%~d\python.exe"
        echo    ✅ 找到: !PYTHON!
        goto :found_python
    )
)

echo    ❌ 未找到 Python 3！
echo    请先安装: https://www.python.org/downloads/
echo.
pause
exit /b 1

:found_python

:: ===== Step 2: 创建虚拟环境 =====
echo.
echo 📦 创建虚拟环境...
if not exist "%VENV_DIR%" (
    "%PYTHON%" -m venv "%VENV_DIR%"
    echo    ✅ 已创建
) else (
    echo    ✅ 已存在，跳过
)

set "PIP=%VENV_DIR%\Scripts\pip.exe"
set "PY_VENV=%VENV_DIR%\Scripts\python.exe"

:: ===== Step 3: 安装依赖 =====
echo 📥 安装依赖...
"%PIP%" install -q flask flask-cors requests
echo    ✅ 依赖安装完成

:: ===== Step 4: 停止旧服务 =====
echo 🛑 停止旧服务...
taskkill /f /im python.exe /fi "WINDOWTITLE eq StoryFlow*" >nul 2>&1
echo    ✅ 完成

:: ===== Step 5: 创建后台启动 VBS =====
echo ⚙️ 创建后台启动脚本...
set "VBS_PATH=%INSTALL_DIR%run_silent.vbs"
(
echo Set WshShell = CreateObject^("WScript.Shell"^)
echo WshShell.Run """%PY_VENV%"" ""%INSTALL_DIR%server.py""", 0, False
) > "%VBS_PATH%"

:: ===== Step 6: 创建开机自启快捷方式 =====
if exist "%STARTUP_DIR%" (
    set "SHORTCUT=%STARTUP_DIR%\StoryFlow AI.lnk"
    powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT%'); $s.TargetPath = '%VBS_PATH%'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.Save()" >nul 2>&1
    echo    ✅ 已设置开机自启
) else (
    echo    ⚠️ 未找到启动文件夹，跳过开机自启
)

:: ===== Step 7: 启动服务 =====
echo 🚀 启动服务...
start "" /B "%PY_VENV%" "%INSTALL_DIR%server.py" > "%INSTALL_DIR%server.log" 2>&1

:: 等 2 秒验证
timeout /t 2 /nobreak >nul
curl -s http://127.0.0.1:8505/api/license/features >nul 2>&1
if !errorlevel!==0 (
    echo    ✅ 服务已启动 ^(http://127.0.0.1:8505^)
) else (
    echo    ⚠️ 服务可能未启动，请查看 server.log
)

:: ===== Step 8: 打开浏览器 =====
echo 🌐 打开写作页面...
start "" "http://127.0.0.1:8505"

:: ===== 完成 =====
echo.
echo ╔══════════════════════════════════════╗
echo ║     🎉 安装完成！                  ║
echo ║                                    ║
echo ║  写作地址: http://127.0.0.1:8505   ║
echo ║  开机自启: 已启用                  ║
echo ║                                    ║
echo ║  下次开机自动启动，无需手动操作    ║
echo ╚══════════════════════════════════════╝
echo.
echo 管理命令：
echo   停止服务: 关闭命令行窗口即可
echo   卸载:     双击 uninstall.bat
echo   查看日志: type server.log
echo.
pause
