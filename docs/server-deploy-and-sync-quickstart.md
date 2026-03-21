# 服务器部署与多机同步手册

本文档基于当前仓库里的实际 Docker 实现编写，适用于以下场景：

- 单机 Docker 部署
- 已上线实例的升级维护
- 通过反向代理对外提供访问
- 多台服务器之间迁移上传记录，避免重复上传到同一图床

当前仓库提供的是单容器部署模型：容器内运行 FastAPI，前端静态资源在镜像构建阶段编译后由后端统一托管。

## 1. 部署模型说明

当前 Docker 方案的行为如下：

- 使用多阶段构建，先在 Node 镜像中构建前端
- 运行阶段使用 Python 3.11 slim 镜像
- 容器启动时自动检查 `data/config.yaml`
- 如果 `data/config.yaml` 不存在，会由 `config.example.yaml` 自动生成
- 宿主机的 `data/` 和 `downloads/` 会挂载到容器内
- 应用默认监听容器内 `8000` 端口

持久化数据位置：

- 配置文件：`data/config.yaml`
- 数据库文件：`data/wallpaper.db`
- 下载产物：`downloads/`

不建议直接把当前方案横向扩为多副本，原因很明确：

- 项目使用本地 SQLite
- 下载任务与调度状态都在单实例内维护
- `downloads/` 默认使用本地磁盘
- AutoPilot、任务队列、上传去重注册表都更适合单实例模型

如果你的目标是稳定上线，建议先按“单实例 + 反向代理 + 定期备份”的方式部署。

## 2. 前置要求

建议服务器至少满足：

- Linux x86_64
- 已安装 Docker Engine 24+
- 已安装 Docker Compose Plugin
- 能访问 GitHub、PyPI、npm 源
- 磁盘空间足够存放 `downloads/` 和 `data/`

可用以下命令确认环境：

```bash
docker --version
docker compose version
```

## 3. 首次部署

如果你希望尽量小白化，当前仓库已经提供一键部署脚本 [deploy_docker.sh](../deploy_docker.sh)。它会自动完成以下操作：

- 检查当前服务器是否已安装 Docker
- 如果未安装，则自动安装 Docker 与 Compose
- 检查并安装 `git`、`curl`、`ca-certificates`
- 克隆或更新项目代码
- 创建 `data/` 和 `downloads/` 持久化目录
- 执行 `docker compose up -d --build`

### 3.1 一键部署命令

空白 Linux 服务器推荐直接执行：

```bash
curl -fsSL https://raw.githubusercontent.com/icelion688-hash/hao-wallpaper-downloader/main/deploy_docker.sh | sudo bash -s -- --port 8000
```

如果你已经把仓库拉到本机，也可以在项目根目录执行：

```bash
sudo bash ./deploy_docker.sh --port 8000
```

常用参数：

- `--port <端口>`：设置对外端口，默认 `8000`
- `--dir <目录>`：设置部署目录，默认 `/opt/hao-wallpaper-downloader`
- `--tz <时区>`：设置时区，默认 `Asia/Shanghai`
- `--branch <分支>`：指定部署分支，默认 `main`
- `--local-repo`：优先使用当前仓库代码部署
- `--remote-repo`：强制从远程仓库克隆或更新

示例：

```bash
curl -fsSL https://raw.githubusercontent.com/icelion688-hash/hao-wallpaper-downloader/main/deploy_docker.sh | sudo bash -s -- --port 8080 --dir /opt/hao-wallpaper-downloader
```

说明：

- 脚本仅支持 Linux
- 脚本会使用 root 或 sudo 提权执行安装操作
- 如果部署目录已存在且不是 Git 仓库，脚本会直接退出，避免误覆盖
- 默认仓库地址为当前 GitHub 仓库，可通过 `--repo` 覆盖
### 3.2 拉取代码

```bash
git clone <your-repo-url>
cd hao-wallpaper-downloader
```

### 3.3 准备持久化目录

```bash
mkdir -p data downloads
```

说明：

- `data/` 用于保存配置和 SQLite 数据库
- `downloads/` 用于保存下载的图片和动态资源
- 这两个目录不要删，否则会丢失运行数据

### 3.4 构建并启动

```bash
docker compose up -d --build
```

默认行为：

- 对外暴露端口 `8000`
- 容器名为 `hao-wallpaper`
- 容器异常退出后自动重启

### 3.5 验证服务是否启动成功

查看容器状态：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f
```

检查健康接口：

```bash
curl http://127.0.0.1:8000/api/health
```

浏览器访问：

```text
http://<服务器IP>:8000
```

## 4. 首次启动后需要做什么

第一次启动时，入口脚本会自动执行以下动作：

- 创建 `data/`
- 创建 `downloads/` 下的默认分类目录
- 如果 `data/config.yaml` 不存在，则从 `config.example.yaml` 复制一份
- 将 `/app/config.yaml` 链接到 `/app/data/config.yaml`

也就是说，实际应该编辑的配置文件始终是：

```text
data/config.yaml
```

修改配置后重启容器即可生效：

```bash
docker compose restart
```

## 5. 配置文件要点

当前默认配置示例位于仓库根目录的 `config.example.yaml`。生产部署时应重点检查以下配置：

### 5.1 基础运行配置

```yaml
download_root: "downloads"
db_path: "data/wallpaper.db"
log_level: "INFO"
```

说明：

- `download_root` 指向容器内目录，保持默认值即可
- `db_path` 指向容器内 SQLite 文件，保持默认值即可
- 如果你把它们改成别的路径，需要保证路径仍然位于持久化挂载目录中

### 5.2 代理配置

如果服务器访问目标站点需要代理，配置：

```yaml
use_proxy: true
proxies:
  - "http://127.0.0.1:7890"
```

如果不需要代理，保持：

```yaml
use_proxy: false
proxies: []
```

### 5.3 图床上传配置

`uploads` 段决定上传目标、压缩策略、目录策略和过滤条件。这里通常是生产环境最需要手动调整的部分。

修改后建议至少验证：

- 上传凭证是否正确
- `base_url` 是否可访问
- 目录策略是否符合你的图床习惯
- 压缩与格式转换是否符合预期

### 5.4 同步配置

如果你准备启用多机迁移上传记录，请配置：

```yaml
sync:
  auth_token: "replace-with-a-strong-token"
  allowed_sources:
    - "192.168.1.10"
  export_rate_limit_per_minute: 60
```

说明：

- `auth_token` 用于保护同步接口
- `allowed_sources` 用于限制允许访问同步导出接口的来源 IP 或 CIDR
- `export_rate_limit_per_minute` 用于限制每个来源每分钟请求次数

## 6. 端口与环境变量

`docker-compose.yml` 当前支持以下环境变量：

- `APP_PORT`：宿主机映射端口，默认 `8000`
- `TZ`：时区，默认 `Asia/Shanghai`

示例：

```bash
APP_PORT=8080 TZ=Asia/Shanghai docker compose up -d --build
```

此时访问地址为：

```text
http://<服务器IP>:8080
```

如果你使用 `.env` 文件，也可以在项目根目录创建：

```env
APP_PORT=8080
TZ=Asia/Shanghai
```

然后直接执行：

```bash
docker compose up -d --build
```

## 7. 日常运维命令

启动或重建：

```bash
docker compose up -d --build
```

查看状态：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f
```

重启服务：

```bash
docker compose restart
```

停止服务：

```bash
docker compose down
```

说明：

- `docker compose down` 只会删除容器和网络
- 不会删除宿主机上的 `data/` 和 `downloads/`
- 只要这两个目录还在，重新启动后数据会继续保留

## 8. 升级流程

建议使用下面的升级流程，而不是直接覆盖目录后盲目重启。

### 8.1 拉取最新代码

```bash
git pull --ff-only
```

### 8.2 对比配置示例是否有新增字段

重点对比：

- `config.example.yaml`
- 你自己的 `data/config.yaml`

如果上游新增了配置项，需要手动合并到 `data/config.yaml`。

### 8.3 重建并启动

```bash
docker compose up -d --build
```

### 8.4 验证升级结果

至少检查以下内容：

- `docker compose ps` 显示容器正常运行
- `docker compose logs -f` 无启动异常
- `/api/health` 返回正常
- 首页和关键页面能打开
- 新增功能对应页面可以访问

## 9. 备份与迁移建议

单机部署时，真正重要的数据只有两类：

- `data/`
- `downloads/`

最低限度的备份建议：

### 9.1 只备份业务数据

```bash
tar czf backup-$(date +%F).tar.gz data downloads
```

### 9.2 最少要保证的恢复材料

- `data/config.yaml`
- `data/wallpaper.db`
- `downloads/`

恢复时只需要：

1. 部署同版本或兼容版本代码
2. 还原 `data/` 和 `downloads/`
3. 重新执行 `docker compose up -d --build`

## 10. 反向代理建议

推荐对外暴露方式：

- 应用容器只监听本机端口
- 由 Nginx 或 Caddy 统一对外提供 HTTPS

### 10.1 推荐做法

例如将宿主机端口改成仅供本机访问：

```yaml
ports:
  - "127.0.0.1:8000:8000"
```

然后由 Nginx 反代到：

```text
http://127.0.0.1:8000
```

### 10.2 Nginx 参考配置

```nginx
server {
    listen 80;
    server_name example.com;

    client_max_body_size 100m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

说明：

- 上传和同步功能都依赖正确的反向代理头
- 如果你准备启用同步白名单，务必正确转发 `X-Forwarded-For` 或 `X-Real-IP`

## 11. 多服务器上传记录同步

当两台或多台服务器都部署了本项目，并且都会上传到同一个图床时，建议先同步“上传记录注册表”，这样后续上传可以直接复用已有 URL，避免重复上传。

功能入口：

- 前端页面：`/sync`
- 远程握手：`GET /api/sync/handshake`
- 远程导出：`GET /api/sync/export`
- 导入：`POST /api/sync/import`
- 远程拉取迁移：`POST /api/sync/pull`

### 11.1 两台服务器可以互相访问

源服务器 A：

1. 打开 `/sync`
2. 配置同步密钥
3. 配置来源白名单
4. 按需设置导出限流

目标服务器 B：

1. 打开 `/sync`
2. 填写服务器 A 地址
3. 填写服务器 A 的同步密钥
4. 先执行“测试远程连接”
5. 测试通过后再执行“一键从远程服务器迁移”

### 11.2 两台服务器不能互相访问

源服务器 A：

1. 打开 `/sync`
2. 导出上传记录 JSON

目标服务器 B：

1. 打开 `/sync`
2. 导入该 JSON 文件
3. 先看预览结果
4. 确认无误后正式导入

### 11.3 迁移完成后的检查项

建议至少检查：

1. `/sync` 页面中的注册表记录数是否增加
2. 最近操作中是否出现本次导入或迁移记录
3. 任意选取一张历史已上传图片，验证后续上传是否直接复用 URL

## 12. 常见问题排查

### 12.1 容器启动了，但页面打不开

优先检查：

- `docker compose ps` 是否正常
- `docker compose logs -f` 是否有启动异常
- 宿主机防火墙是否开放对应端口
- 反向代理是否正确转发到 `8000`

### 12.2 `data/config.yaml` 修改后没有生效

优先检查：

- 是否改的是宿主机上的 `data/config.yaml`
- 修改后是否执行了 `docker compose restart`
- YAML 缩进是否正确

### 12.3 升级后页面异常或接口报错

优先检查：

- 是否重新执行了 `docker compose up -d --build`
- `data/config.yaml` 是否漏合并了新配置项
- 浏览器是否缓存了旧前端资源

### 12.4 `403 同步密钥无效`

说明：

- 目标服务器提交给源服务器的同步密钥不正确

检查：

1. 源服务器 `sync.auth_token`
2. 目标服务器 `/sync` 页面里填写的远程迁移密钥

### 12.5 `403 来源不在同步白名单内`

说明：

- 源服务器拒绝了当前导出请求

检查：

1. `allowed_sources` 是否包含目标服务器出口 IP
2. 反向代理是否正确传递了 `X-Forwarded-For` 或 `X-Real-IP`
3. `/sync` 页面中的探测结果里，对端识别到的来源地址是否符合预期

### 12.6 `429 同步接口请求过于频繁`

说明：

- 命中了导出限流

处理方式：

1. 稍后重试
2. 适度提高 `export_rate_limit_per_minute`

### 12.7 导入成功，但仍然重复上传

优先检查：

1. 注册表记录数是否真的增加
2. 这些图片是否具有相同的 `resource_id`、`sha256` 或 `md5`
3. 是否导入到了正确的目标实例

## 13. 生产环境建议

如果你打算长期运行，建议遵循以下原则：

- 使用固定版本的 Docker 和 Compose
- 通过反向代理统一处理 HTTPS
- 不要把 `data/` 和 `downloads/` 放在临时磁盘
- 升级前先备份 `data/`，大批量任务期间避免贸然升级
- 公网暴露同步接口时，至少启用：
  - `sync.auth_token`
  - `sync.allowed_sources`
  - `sync.export_rate_limit_per_minute`

## 14. 当前 Docker 方案的边界

这份部署方案已经足够支持单机长期运行，但它仍然是偏轻量的模型，当前边界包括：

- 数据库是 SQLite，不适合多实例并发写入
- 下载目录是本地存储，不适合多实例共享
- 调度、任务执行和状态管理都更偏向单实例
- 文档没有引入额外的 Redis、PostgreSQL、对象存储等组件

这符合当前项目状态，也符合 KISS 和 YAGNI。只有在你真的需要多实例、任务隔离或集中式存储时，再考虑拆分架构。
