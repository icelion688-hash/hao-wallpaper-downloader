# 好壁纸下载器

基于 FastAPI + Vue 3 的壁纸批量下载、管理与自动化上传系统。支持多账号轮询、验证码求解、去重、图床上传、AutoPilot 自动驾驶。

## 系统要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.10+ | 后端运行环境 |
| Node.js | 18+ | 前端构建（首次启动时自动处理） |
| Docker | 24+ | 仅 Docker 部署时需要 |

---

## 快速启动

### Windows

双击或运行：

```bat
start.bat
```

脚本会自动检测依赖、安装 Python 包、构建前端，然后启动服务。

### Linux / macOS

```bash
chmod +x start.sh
./start.sh
```

首次运行会自动创建虚拟环境、安装依赖、构建前端。

启动后访问：`http://localhost:8000`

---

## Docker 部署

适合服务器长期运行，无需手动安装 Python 和 Node.js。

### 最简单启动

```bash
mkdir -p data downloads
docker compose up -d --build
```

### 一键部署脚本（从零开始）

适合全新服务器，自动安装 Docker、拉取代码、启动容器：

```bash
curl -fsSL https://raw.githubusercontent.com/icelion688-hash/hao-wallpaper-downloader/main/scripts/deploy_docker.sh | sudo bash -s -- --port 8000
```

国内服务器可加代理：

```bash
curl -fsSL https://raw.githubusercontent.com/icelion688-hash/hao-wallpaper-downloader/main/scripts/deploy_docker.sh | sudo bash -s -- --port 8000 --proxy http://127.0.0.1:7890
```

脚本选项：

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `--port <端口>` | 8000 | 对外端口 |
| `--dir <路径>` | /opt/hao-wallpaper-downloader | 部署目录 |
| `--tz <时区>` | Asia/Shanghai | 时区 |
| `--proxy <地址>` | 无 | HTTP 代理 |

### 宝塔面板部署

```bash
bash scripts/deploy_bt.sh
```

### 常用 Docker 命令

```bash
docker compose logs -f        # 查看日志
docker compose ps             # 查看状态
docker compose restart        # 重启服务
docker compose down           # 停止并删除容器
APP_PORT=8080 docker compose up -d --build  # 自定义端口
```

---

## 手动安装（开发环境）

```bash
# 1. 安装后端依赖
pip install -r requirements.txt

# 2. 复制并编辑配置
cp config.example.yaml config.yaml

# 3. 启动后端
python -m backend.main

# 4. 启动前端开发服务器（另开终端）
cd frontend
npm install
npm run dev      # http://localhost:5173（代理到后端 8000）
```

生产构建前端：

```bash
cd frontend && npm run build  # 产物到 frontend/dist/，FastAPI 自动托管
```

---

## 首次配置

服务启动后，`data/config.yaml` 会自动生成。关键配置项：

```yaml
# 图床上传（可选）
uploads:
  task_profile: compressed_webp
  profiles:
    - key: compressed_webp
      base_url: https://your-imgbed.com
      api_token: your_token
      channel: telegram

# 代理（可选）
use_proxy: false
proxies:
  - http://127.0.0.1:7890
```

---

## 项目结构

```
backend/          FastAPI 后端
frontend/         Vue 3 前端
scripts/          部署脚本（deploy_docker.sh、deploy_bt.sh）
docker/           Docker 相关文件（entrypoint.sh）
start.sh          Linux/macOS 本地一键启动
start.bat         Windows 本地一键启动
docker-compose.yml
config.example.yaml
```

运行时目录（自动创建，不提交 git）：

```
data/             SQLite 数据库、配置文件、运行状态
downloads/        壁纸文件
frontend/dist/    前端构建产物
```

---

## 多服务器同步

如果多台服务器共用同一图床，可通过「数据同步」页面（`/sync`）导出/导入上传记录，避免重复上传同一张图片。

- 两台互通：在目标服务器填写源服务器地址，点击「一键从远程迁移」
- 不互通：在源服务器导出 JSON，在目标服务器导入

---

## 验证部署

```bash
curl http://localhost:8000/api/health
```

返回 `{"status":"ok"}` 即正常。
