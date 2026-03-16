#!/bin/bash
set -e

echo "========================================"
echo "  好壁纸下载器 - 一键启动"
echo "========================================"
echo ""

# 获取脚本所在目录（项目根目录）
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

# ── 检查 Python ──────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "[错误] 未找到 python3，请先安装 Python 3.10+"
    exit 1
fi
PYTHON=$(command -v python3)
echo "[1/3] Python: $($PYTHON --version)"

# ── 虚拟环境（推荐） ──────────────────────────
if [ ! -d "venv" ]; then
    echo "      创建虚拟环境..."
    $PYTHON -m venv venv
fi
source venv/bin/activate
echo "      虚拟环境已激活 ✓"

# ── 安装 Python 依赖 ─────────────────────────
pip show fastapi &>/dev/null || {
    echo "      安装 Python 依赖..."
    pip install -r requirements.txt -q
}
echo "      Python 依赖就绪 ✓"

# ── 前端构建 ─────────────────────────────────
echo "[2/3] 检查前端..."
if command -v node &>/dev/null; then
    if [ ! -d "frontend/dist" ]; then
        echo "      构建前端..."
        cd frontend
        npm install --silent
        npm run build
        cd ..
        echo "      前端构建完成 ✓"
    else
        echo "      前端已构建 ✓"
    fi
else
    echo "      [提示] 未检测到 Node.js，跳过前端构建"
    echo "      后端 API: http://localhost:8000/api/"
fi

# ── 创建必要目录 ──────────────────────────────
mkdir -p data downloads/{anime,landscape,dynamic,uncategorized}

# ── 启动后端 ─────────────────────────────────
echo "[3/3] 启动后端服务..."
echo ""
echo "========================================"
echo "  服务地址: http://localhost:8000"
echo "  按 Ctrl+C 停止服务"
echo "========================================"
echo ""

python -m backend.main
