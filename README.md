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

如果你准备在服务器上长期运行，或需要处理升级、备份、反向代理、多机同步等问题，优先参考这份部署手册：

- [服务器部署与多机同步手册](./docs/server-deploy-and-sync-quickstart.md)

### 1. 最简单启动

```bash
mkdir -p data downloads
docker compose up -d --build
```

如果你希望服务器从“未安装 Docker”开始也能一条命令完成部署，可以直接使用根目录的 [deploy_docker.sh](./deploy_docker.sh)：

```bash
curl -fsSL https://raw.githubusercontent.com/icelion688-hash/hao-wallpaper-downloader/main/deploy_docker.sh | sudo bash -s -- --port 8000
```

这个脚本会自动检查并安装 Docker、拉取或更新仓库、创建持久化目录，然后启动容器。

如果服务器位于中国大陆，访问 GitHub 不稳定，可以额外传入部署代理：

```bash
curl -fsSL https://raw.githubusercontent.com/icelion688-hash/hao-wallpaper-downloader/main/deploy_docker.sh | sudo bash -s -- --port 8000 --proxy http://127.0.0.1:7890
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

如果你准备正式上线，建议继续阅读上面的部署手册，里面补充了：

- 首次部署后的配置说明
- `APP_PORT`、`TZ` 等环境变量用法
- 升级与备份流程
- Nginx 反向代理示例
- 多机同步上传记录的建议做法

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

## 多服务器上传记录迁移

当你在多台服务器上部署本项目，并且这些服务器都会上传图片到同一个图床时，建议先同步“上传记录注册表”，这样可以避免重复上传。

### 3 步快速迁移

#### 场景 1：两台服务器可以互相访问

1. 在源服务器 `/sync` 页面配置同步密钥、来源白名单
2. 在目标服务器 `/sync` 页面先点击“测试远程连接”
3. 测试通过后点击“一键从远程服务器迁移”

#### 场景 2：两台服务器不能互相访问

1. 在源服务器 `/sync` 页面导出 JSON
2. 把 JSON 文件传到目标服务器
3. 在目标服务器 `/sync` 页面导入该文件

#### 迁移完成后建议立刻做的检查

1. 在目标服务器 `/sync` 页面确认“注册表记录”数量已经增加
2. 任选 1 张历史已上传过的图片，触发一次上传流程，确认直接复用 URL
3. 查看“最近操作”面板，确认导入或迁移已记录到后端历史

### 功能入口

- 前端页面：`/sync`
- 握手探测：`GET /api/sync/handshake`
- 导出接口：`GET /api/sync/export`
- 导出筛选项：`GET /api/sync/export-options`
- 导出预估：`GET /api/sync/export-estimate`
- 导入接口：`POST /api/sync/import`
- 导入预览：`POST /api/sync/preview`
- 远程一键拉取：`POST /api/sync/pull`
- 远程探测：`POST /api/sync/probe`
- 统计接口：`GET /api/sync/stats`
- 历史接口：`GET /api/sync/history`
- 重复项扫描：`GET /api/sync/duplicates`
- 重复项合并：`POST /api/sync/duplicates/merge`

### 推荐使用方式

#### 方式 1：一键从远程服务器迁移

在目标服务器后台打开“数据同步”页面，填写源服务器地址，例如：

```text
http://192.168.1.20:8000
```

然后点击“一键从远程服务器迁移”。

系统会自动：

1. 请求源服务器的 `/api/sync/export`
2. 拉取上传记录 JSON
3. 导入到本机的 `upload_registry`
4. 后续上传时自动复用已有图床 URL

在正式迁移前，也可以先点击“测试远程连接”，验证：

- 远程地址是否可达
- 远程同步密钥是否正确
- 当前目标服务器在对端识别到的来源 IP
- 对端注册表中可导出的记录数量
- 对端是否启用了白名单和限流

#### 方式 2：手动导出 / 导入

如果两台服务器不能互相直连：

1. 在源服务器“数据同步”页面导出 JSON
2. 下载该文件
3. 在目标服务器“数据同步”页面上传并导入

### 同步后会发生什么

- 下载任务自动上传时，会先查本地上传注册表
- 画廊批量上传时，也会先查本地上传注册表
- 如果命中相同 `resource_id` / `sha256` / `md5` 的上传记录，会直接复用图床 URL
- 不会再次真实上传同一张图片
- 最近导出、导入、探测、迁移、去重操作会持久化到后端数据库，换浏览器后仍可查看

### 兼容性说明

- 新版同步数据基于独立的 `upload_registry` 表
- 仍兼容旧版基于 `wallpapers.upload_records` 导出的 JSON 文件
- 历史上传记录会在导出统计或同步过程中自动回填到注册表

### 安全建议

- 可以直接在前端“数据同步”页面保存当前服务器的同步密钥、来源白名单和同步限流
- 也可以在 `config.yaml` 中手动配置：

```yaml
sync:
  auth_token: "replace-with-a-strong-token"
  allowed_sources:
    - "192.168.1.20"
    - "10.0.0.0/24"
  export_rate_limit_per_minute: 60
```

- 配置后，`GET /api/sync/export` 和 `GET /api/sync/handshake` 需要满足以下条件：
  - 如果配置了 `auth_token`，请求必须携带 `X-Sync-Token`
  - 如果配置了 `allowed_sources`，请求来源必须命中白名单
  - 如果配置了 `export_rate_limit_per_minute`，单个来源访问频率不能超限
- 同步页面已支持：
  当前服务器同步密钥保存
  当前服务器来源白名单保存
  当前服务器同步限流保存
  远程迁移密钥填写
- `POST /api/sync/pull` 依赖目标服务器能访问源服务器的 `/api/sync/export`
- 如果服务暴露在公网，建议至少同时启用同步密钥和来源白名单
- 在使用反向代理时，请确保正确转发 `X-Forwarded-For` 或 `X-Real-IP`

### 常见问题排查

- `403 同步密钥无效`
  检查源服务器是否配置了 `sync.auth_token`，以及目标服务器“远程迁移密钥”是否填写一致。
- `403 来源 xxx 不在同步白名单内`
  检查源服务器 `allowed_sources` 是否包含目标服务器出口 IP，或者反向代理是否正确传递了 `X-Forwarded-For` / `X-Real-IP`。
- `429 同步接口请求过于频繁`
  说明命中了 `export_rate_limit_per_minute`，稍后重试或适当提高阈值。
- 测试远程连接正常，但一键迁移失败
  一般说明 `/api/sync/handshake` 可达，但 `/api/sync/export` 被密钥、白名单、限流或反向代理配置拦住了。
- 导入成功，但后续仍然重复上传
  先在 `/sync` 页面确认注册表记录数量已增加，再检查图片是否具备相同的 `resource_id`、`sha256` 或 `md5`。
- 重复项扫描发现很多冲突组
  说明同一身份键下存在多个不同 URL，建议先确认是否确实指向同一资源，再执行“一键合并重复项”。

### 对外暴露建议

- 只在需要时开放 `/api/sync/export` 和 `/api/sync/handshake`
- 优先走内网地址，不建议长期裸露在公网
- 如果必须公网暴露，至少同时启用：
  - `auth_token`
  - `allowed_sources`
  - `export_rate_limit_per_minute`

### 后续优化路线

当前已经完成：

- 独立上传记录注册表
- 导出 / 导入 / 一键远程迁移
- 同步密钥配置
- 远程连通性测试
- 最近操作记录
- 导入文件预校验与摘要预览
- 注册表重复项扫描与合并工具
- 按 Profile / 格式筛选导出
- 同步接口限流与来源白名单
- 迁移结果持久化到后端而非仅浏览器本地
- 增加同步相关的后端 API 测试覆盖

目前这套多服务器同步/迁移链路已经具备：

- 上传记录导出 / 导入
- 远程探测 / 一键迁移
- 导入预览 / 迁移历史
- 重复项扫描 / 合并
- 筛选导出 / 安全限制
- 后端测试覆盖

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
