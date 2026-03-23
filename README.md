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

### 图床上传策略说明

- `uploads.task_profile` 是系统默认上传 Profile。
- 图库手动上传、任务下载上传、AutoPilot 自动上传，都基于 `uploads.profiles` 中定义的 Profile 工作。
- 每个 Profile 都可以单独配置：
  - 是否上传后同步标签 `sync_remote_tags`
  - 横图 / 竖图 / 动态图目录
  - 路径模板 `folder_pattern`
  - 上传尺寸门槛 `upload_filter`
  - 本地预处理和服务端压缩策略

推荐做法：

- 静态图使用 `compressed_webp` 这类压缩 Profile。
- 动态图使用单独 Profile，并按体积、渠道、目录规则独立配置。
- 如果 `folder_dynamic` 留空，动态图会自动回退到横图 / 竖图目录分流，而不是固定写入 `bg/dynamic`。
- 如果 `folder_pattern` 非空，会优先于固定目录，支持的变量包括：
  - `{type}`
  - `{orientation}`
  - `{category}`
  - `{year}`
  - `{month}`
  - `{date}`

示例：

```yaml
uploads:
  task_profile: "compressed_webp"
  profiles:
    - key: "compressed_webp"
      sync_remote_tags: true
      folder_pattern: "wallpaper/{type}/{orientation}/{category}"
```

---

## 主要工作流

### 图床管理

- “同步元数据标签”现在只同步远端标签，不再移动远端目录。
- 同步时会优先按历史上传记录、远端文件名、`resource_id` 匹配本地图片，不要求远端目录和本地原目录一致。
- 执行“一键修复并同步标签”时，会先修复旧的远端路径记录，再同步标签。
- 标签同步已经支持：
  - 按相同标签集合批量打标
  - 批量失败后自动回退到单文件重试
  - 失败项一键重试
  - 远端标签回写本地数据库

### AutoPilot 自动驾驶

- AutoPilot 现在支持“静态图 Profile”和“动态图 Profile”分开配置。
- 自动上传时会根据图片类型自动选择对应 Profile。
- 上传区已经拆成两张独立策略卡，静态图和动态图的目录、压缩、标签同步互不干扰。
- AutoPilot 的自动清理支持三种策略：
  - `keep_count`：保留最新 N 张
  - `keep_days`：保留最近 N 天
  - `upload_and_delete`：删除所有已上传本地文件
- AutoPilot 页面会显示：
  - 当前清理策略
  - 下次何时触发
  - 最近一次自动清理是否执行、为什么跳过、删除了多少文件

### 动态图目录规则

- 图床侧：动态图支持横图 / 竖图分类，与静态图目录语义保持一致。
- 本地下载侧：动态图不再统一放入单一 `dynamic` 目录，会按分类和横竖方向分流。
- 如果没有分类，动态图本地目录会至少保留方向层级，例如 `方图/`、`横图/`、`竖图/`。

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
