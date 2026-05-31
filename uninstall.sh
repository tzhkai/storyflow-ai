#!/bin/bash
# ============================================
# StoryFlow AI — 卸载脚本
# ============================================

PLIST_PATH="$HOME/Library/LaunchAgents/com.storyflow.server.plist"
INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "🗑️  卸载 StoryFlow AI..."

# 停服务
if [ -f "$PLIST_PATH" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null
    rm -f "$PLIST_PATH"
    echo "   ✅ 开机自启已移除"
fi

# 杀进程
pkill -f "storyflow.*server.py" 2>/dev/null && echo "   ✅ 服务已停止" || true

# 删虚拟环境
if [ -d "$INSTALL_DIR/venv" ]; then
    rm -rf "$INSTALL_DIR/venv"
    echo "   ✅ 虚拟环境已删除"
fi

# 删日志
rm -f "$INSTALL_DIR/server.log"

echo ""
echo "✅ 卸载完成。StoryFlow 文件夹可手动删除。"
echo ""
