#!/bin/bash
# StoryFlow AI 启动脚本
# 用法: bash start.sh  或 双击运行

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

echo "=========================================="
echo "  StoryFlow AI 启动中..."
echo "=========================================="

# 找 python：优先用 python3.14，找不到就用 python3
PYTHON=""
if command -v python3.14 &>/dev/null; then
    PYTHON="python3.14"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    echo "❌ 找不到 Python，请先安装 Python 3.10+"
    echo "   下载地址: https://www.python.org/downloads/"
    read -p "按回车退出..."
    exit 1
fi

echo "✅ 使用 Python: $($PYTHON --version 2>&1)"

# 检查依赖
_MISSING=$($PYTHON - << 'PYEOF'
import sys, importlib
missing = []
for pkg in ['flask', 'flask_cors', 'requests']:
    try:
        importlib.import_module(pkg)
    except ImportError:
        # pip 包名和 import 名不同
        pip_name = {'flask_cors': 'flask-cors'}.get(pkg, pkg)
        missing.append(pip_name)
print(','.join(missing))
PYEOF
)

if [ -n "$_MISSING" ]; then
    echo ""
    echo "❌ 缺少依赖: $_MISSING"
    echo "   正在自动安装..."
    $PYTHON -m pip install $_MISSING
    if [ $? -ne 0 ]; then
        echo ""
        echo "❌ 自动安装失败，请手动运行："
        echo "   $PYTHON -m pip install $_MISSING"
        read -p "按回车退出..."
        exit 1
    fi
fi

echo ""
echo "🚀 启动服务器..."
echo "   访问地址: http://127.0.0.1:8505"
echo "   停止服务: 按 Ctrl+C"
echo "=========================================="
echo ""

$PYTHON server.py
