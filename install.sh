#!/bin/bash
# ============================================
# StoryFlow AI — 一键安装脚本
# 自动配置环境、安装依赖、启动服务、开机自启
# ============================================
set -e

APP_NAME="StoryFlow AI"
INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$INSTALL_DIR/venv"
PLIST_PATH="$HOME/Library/LaunchAgents/com.storyflow.server.plist"

# ---- 颜色 ----
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "${CYAN}╔══════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     📖 StoryFlow AI 一键安装        ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════╝${NC}"
echo ""

# ---- Step 1: 找 Python ----
echo -e "🔍 检测 Python 环境..."
PYTHON=""

# 优先用 python3
for py in python3 python3.14 python3.13 python3.12 python3.11 python3.10; do
    if command -v $py &>/dev/null; then
        PYTHON=$(command -v $py)
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "${RED}❌ 未找到 Python 3！${NC}"
    echo ""
    echo "请先安装 Python 3："
    echo "  brew install python3"
    echo "  或访问 https://www.python.org/downloads/"
    echo ""
    exit 1
fi

echo -e "   ✅ Python: $($PYTHON --version 2>&1)"

# ---- Step 2: 创建虚拟环境 ----
echo -e "📦 创建虚拟环境..."
if [ ! -d "$VENV_DIR" ]; then
    $PYTHON -m venv "$VENV_DIR"
    echo -e "   ✅ 已创建"
else
    echo -e "   ✅ 已存在，跳过"
fi

PIP="$VENV_DIR/bin/pip"
PYTHON_VENV="$VENV_DIR/bin/python"

# ---- Step 3: 安装依赖 ----
echo -e "📥 安装依赖..."
$PIP install -q flask flask-cors requests
echo -e "   ✅ 依赖安装完成"

# ---- Step 4: 停掉旧服务 ----
echo -e "🛑 检查旧服务..."
if [ -f "$PLIST_PATH" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    echo -e "   ✅ 旧服务已停止"
fi

# 杀掉可能卡住的进程
pkill -f "storyflow.*server.py" 2>/dev/null || true
sleep 1

# ---- Step 5: 启动服务 ----
echo -e "🚀 启动服务..."
nohup $PYTHON_VENV "$INSTALL_DIR/server.py" > "$INSTALL_DIR/server.log" 2>&1 &
sleep 2

# 验证服务
if curl -s http://127.0.0.1:8505/api/license/features > /dev/null 2>&1; then
    echo -e "   ${GREEN}✅ 服务已启动 (http://127.0.0.1:8505)${NC}"
else
    echo -e "   ${RED}⚠️ 服务启动检测失败，请查看 server.log${NC}"
fi

# ---- Step 6: 设置开机自启 ----
echo -e "⚙️ 设置开机自启..."

cat > "$PLIST_PATH" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.storyflow.server</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_VENV</string>
        <string>$INSTALL_DIR/server.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>$INSTALL_DIR/server.log</string>
    <key>StandardErrorPath</key>
    <string>$INSTALL_DIR/server.log</string>
</dict>
</plist>
PLISTEOF

launchctl load "$PLIST_PATH" 2>/dev/null
echo -e "   ✅ 已设置（下次开机自动启动）"

# ---- Step 7: 打开浏览器 ----
echo -e "🌐 打开写作页面..."
sleep 1
open "http://127.0.0.1:8505"

# ---- 完成 ----
echo ""
echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     🎉 安装完成！                  ║${NC}"
echo -e "${GREEN}║                                    ║${NC}"
echo -e "${GREEN}║  写作地址: http://127.0.0.1:8505   ║${NC}"
echo -e "${GREEN}║  开机自启: 已启用                  ║${NC}"
echo -e "${GREEN}║                                    ║${NC}"
echo -e "${GREEN}║  下次开机自动启动，无需手动操作    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
echo ""
echo "管理命令："
echo "  查看日志:  cat $INSTALL_DIR/server.log"
echo "  停止服务:  launchctl unload $PLIST_PATH"
echo "  卸载:      bash $INSTALL_DIR/uninstall.sh"
echo ""
