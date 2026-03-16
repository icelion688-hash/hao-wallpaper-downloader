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
