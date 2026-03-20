# Hao Wallpaper Downloader

一个基于 FastAPI + Vue 3 的好壁纸下载与任务管理项目，包含账号管理、画廊下载、任务调度、统计监控和图床上传配置。

## 技术栈

- 后端：FastAPI、SQLAlchemy、PyYAML
- 前端：Vue 3、Vite、Pinia、Vue Router、Axios
- 运行数据：SQLite（默认位于 `data/wallpaper.db`）

## 目录结构

```text
backend/        FastAPI 后端
frontend/       Vue 3 前端
data/           本地运行数据，不提交
downloads/      下载产物，不提交
config.example.yaml  配置示例
config.yaml     本地实际配置，不提交
```

## 本地启动

### 1. 安装后端依赖

```bash
pip install -r requirements.txt
```

### 2. 准备配置

将 `config.example.yaml` 复制为 `config.yaml`，再按你的环境修改图床、代理等配置。

### 3. 启动后端

```bash
python -m backend.main
```

或：

```bash
uvicorn backend.main:app --reload --port 8000
```

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev
```

默认前端开发地址为 `http://localhost:5173`，后端接口地址为 `http://localhost:8000`。

## 生产构建

```bash
cd frontend
npm run build
```

构建产物位于 `frontend/dist/`。后端启动时如果检测到该目录，会自动托管前端静态文件。

如果你是通过项目根目录下的 `start.sh` 启动服务，脚本会在每次启动时自动重新构建前端，确保 `git pull` 后页面与最新源码保持一致。

## Docker 部署

项目已提供 `Dockerfile` 和 `docker-compose.yml`，适合单机部署。

### 1. 最简单启动

```bash
mkdir -p data downloads
docker compose up -d --build
```

第一次启动时，容器会自动生成 `data/config.yaml`，SQLite 默认位于 `data/wallpaper.db`。

默认访问地址：

- 应用首页：`http://localhost:8000`
- 健康检查：`http://localhost:8000/api/health`

### 2. 改配置

```bash
sed -n '1,120p' data/config.yaml
```

需要修改图床、代理等配置时，直接编辑宿主机上的 `data/config.yaml`，然后重启容器：

```bash
docker compose restart
```

### 3. 常用命令

```bash
docker compose logs -f
docker compose ps
docker compose down
```

### 4. 可选端口

```bash
APP_PORT=8080 docker compose up -d --build
```

这时访问地址变为 `http://localhost:8080`。

### 5. 部署说明

- 镜像使用多阶段构建，前端会先编译成 `frontend/dist/`，再由 FastAPI 统一托管
- 当前部署模型适合单实例运行，不建议直接扩成多副本
- 原因是项目内置了本地 SQLite、定时调度器、下载队列和 AutoPilot 单例状态
- 如果后续要做多实例，需要再拆分数据库、任务调度和共享存储

## 远程协作建议

- 使用 GitHub 私有仓库
- 通过分支开发，例如 `feature/xxx`
- 通过 Pull Request 合并到 `main`
- 不要提交 `config.yaml`、`data/`、`downloads/`、`frontend/node_modules/`、`frontend/dist/`
- 涉及密钥、Cookie、代理配置时，只保留示例，不提交真实值

## 手动验证

- 健康检查：`GET /api/health`
- 前端页面：启动 `npm run dev` 后检查主要页面是否可访问
- 后端服务：确认 `python -m backend.main` 能正常启动
