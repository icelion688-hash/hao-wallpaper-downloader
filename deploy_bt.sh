#!/bin/bash
# ============================================================
#  宝塔面板一键部署脚本
#  使用方法：chmod +x deploy_bt.sh && sudo bash deploy_bt.sh
# ============================================================

set -e
APP_NAME="hao-wallpaper"
APP_DIR="/www/wwwroot/hao-wallpaper"
APP_PORT=8000
PYTHON_MIN="3.10"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     好壁纸下载器 — 宝塔面板部署脚本        ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── Step 1: 检查运行环境 ──────────────────────
echo "▶ Step 1: 检查环境"

PYTHON=$(command -v python3.11 || command -v python3.10 || command -v python3 || echo "")
if [ -z "$PYTHON" ]; then
    echo "  [错误] 未找到 Python 3.10+，请在宝塔面板先安装 Python 3.11"
    exit 1
fi
echo "  Python: $($PYTHON --version)"

if ! command -v node &>/dev/null; then
    echo "  [警告] 未找到 Node.js，前端需手动构建或预先上传 dist 目录"
fi

# ── Step 2: 创建应用目录 ──────────────────────
echo "▶ Step 2: 创建目录结构"
mkdir -p "$APP_DIR"
mkdir -p "$APP_DIR/data"
mkdir -p "$APP_DIR/downloads/{anime,landscape,dynamic,uncategorized}"
mkdir -p "$APP_DIR/logs"

# 复制项目文件（假设当前目录就是项目根目录）
cp -r backend   "$APP_DIR/"
cp -r frontend  "$APP_DIR/"  2>/dev/null || true
cp config.yaml  "$APP_DIR/"
cp requirements.txt "$APP_DIR/"
echo "  文件复制完成 ✓"

cd "$APP_DIR"

# ── Step 3: 创建虚拟环境并安装依赖 ────────────
echo "▶ Step 3: 安装 Python 依赖"
$PYTHON -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "  依赖安装完成 ✓"

# ── Step 4: 构建前端 ──────────────────────────
if command -v node &>/dev/null && [ -d "frontend" ]; then
    echo "▶ Step 4: 构建前端"
    cd frontend
    npm install --silent
    npm run build
    cd ..
    echo "  前端构建完成 ✓"
else
    echo "▶ Step 4: 跳过前端构建（Node.js 未安装）"
fi

# ── Step 5: 创建 systemd 服务（进程守护） ──────
echo "▶ Step 5: 配置系统服务（systemd）"

cat > /etc/systemd/system/${APP_NAME}.service << EOF
[Unit]
Description=好壁纸下载器后端
After=network.target

[Service]
Type=simple
User=www
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/python -m backend.main
Restart=always
RestartSec=5
StandardOutput=append:${APP_DIR}/logs/app.log
StandardError=append:${APP_DIR}/logs/error.log
Environment=PYTHONPATH=${APP_DIR}
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ${APP_NAME}
systemctl restart ${APP_NAME}
echo "  systemd 服务已启动 ✓"

# ── Step 6: 输出 Nginx 反向代理配置 ───────────
echo ""
echo "▶ Step 6: Nginx 反向代理配置（在宝塔面板中添加）"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
cat << 'NGINX'
# 在宝塔面板 → 网站 → 设置 → 反向代理 → 添加反向代理
# 或直接粘贴到网站 Nginx 配置文件中：

location /api/ {
    proxy_pass         http://127.0.0.1:8000/api/;
    proxy_http_version 1.1;
    proxy_set_header   Upgrade $http_upgrade;
    proxy_set_header   Connection "upgrade";
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_read_timeout 300s;
}

location / {
    # 前端静态文件（如果有构建产物）
    root /www/wwwroot/hao-wallpaper/frontend/dist;
    index index.html;
    try_files $uri $uri/ /index.html;
}
NGINX
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── 完成 ───────────────────────────────────────
echo "╔══════════════════════════════════════════╗"
echo "║  部署完成！                               ║"
echo "║                                          ║"
echo "║  服务状态: systemctl status $APP_NAME    ║"
echo "║  查看日志: tail -f $APP_DIR/logs/app.log ║"
echo "║  本机访问: http://localhost:$APP_PORT    ║"
echo "╚══════════════════════════════════════════╝"
