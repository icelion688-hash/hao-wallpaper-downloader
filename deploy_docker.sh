#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="hao-wallpaper"
DEFAULT_REPO_URL="https://github.com/icelion688-hash/hao-wallpaper-downloader.git"
DEFAULT_BRANCH="main"
DEFAULT_INSTALL_DIR="/opt/hao-wallpaper-downloader"
DEFAULT_PORT="8000"
DEFAULT_TZ="Asia/Shanghai"

REPO_URL="${REPO_URL:-$DEFAULT_REPO_URL}"
BRANCH="${BRANCH:-$DEFAULT_BRANCH}"
INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
APP_PORT="${APP_PORT:-$DEFAULT_PORT}"
TZ_VALUE="${TZ:-$DEFAULT_TZ}"
USE_LOCAL_REPO="auto"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info() {
  printf '[INFO] %s\n' "$1"
}

warn() {
  printf '[WARN] %s\n' "$1"
}

error() {
  printf '[ERROR] %s\n' "$1" >&2
}

usage() {
  cat <<'EOF'
用法：
  sudo bash deploy_docker.sh [选项]

选项：
  --dir <路径>       部署目录，默认 /opt/hao-wallpaper-downloader
  --port <端口>      对外端口，默认 8000
  --tz <时区>        时区，默认 Asia/Shanghai
  --repo <地址>      Git 仓库地址
  --branch <分支>    Git 分支，默认 main
  --local-repo       优先使用当前脚本所在仓库
  --remote-repo      强制从远程仓库克隆或更新
  --help             显示帮助

示例：
  sudo bash deploy_docker.sh --port 8080
  curl -fsSL https://raw.githubusercontent.com/icelion688-hash/hao-wallpaper-downloader/main/deploy_docker.sh | sudo bash -s -- --port 8080
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dir)
      INSTALL_DIR="$2"
      shift 2
      ;;
    --port)
      APP_PORT="$2"
      shift 2
      ;;
    --tz)
      TZ_VALUE="$2"
      shift 2
      ;;
    --repo)
      REPO_URL="$2"
      shift 2
      ;;
    --branch)
      BRANCH="$2"
      shift 2
      ;;
    --local-repo)
      USE_LOCAL_REPO="yes"
      shift
      ;;
    --remote-repo)
      USE_LOCAL_REPO="no"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      error "未知参数：$1"
      usage
      exit 1
      ;;
  esac
done

if [ "$(uname -s)" != "Linux" ]; then
  error "该脚本仅支持 Linux 服务器。"
  exit 1
fi

case "$APP_PORT" in
  ''|*[!0-9]*)
    error "端口必须是数字。"
    exit 1
    ;;
esac

if [ "$APP_PORT" -lt 1 ] || [ "$APP_PORT" -gt 65535 ]; then
  error "端口必须在 1-65535 之间。"
  exit 1
fi

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
elif command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
else
  error "请使用 root 运行，或先安装 sudo。"
  exit 1
fi

run_root() {
  if [ -n "$SUDO" ]; then
    "$SUDO" "$@"
  else
    "$@"
  fi
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

detect_pkg_manager() {
  if command_exists apt-get; then
    echo "apt"
    return
  fi
  if command_exists dnf; then
    echo "dnf"
    return
  fi
  if command_exists yum; then
    echo "yum"
    return
  fi
  echo ""
}

install_base_packages() {
  local pkg_manager
  pkg_manager="$(detect_pkg_manager)"

  if [ -z "$pkg_manager" ]; then
    error "未识别到受支持的包管理器，仅支持 apt / dnf / yum。"
    exit 1
  fi

  info "检查基础依赖（git、curl、ca-certificates）..."

  case "$pkg_manager" in
    apt)
      run_root apt-get update
      run_root apt-get install -y ca-certificates curl git
      ;;
    dnf)
      run_root dnf install -y ca-certificates curl git
      ;;
    yum)
      run_root yum install -y ca-certificates curl git
      ;;
  esac
}

ensure_docker_service() {
  if command_exists systemctl; then
    run_root systemctl enable docker
    run_root systemctl restart docker
  else
    run_root service docker start
  fi
}

install_compose_plugin_if_missing() {
  if docker compose version >/dev/null 2>&1; then
    return
  fi

  local pkg_manager
  pkg_manager="$(detect_pkg_manager)"

  warn "未检测到 docker compose，尝试安装 Compose 插件..."

  case "$pkg_manager" in
    apt)
      run_root apt-get update
      run_root apt-get install -y docker-compose-plugin
      ;;
    dnf)
      run_root dnf install -y docker-compose-plugin
      ;;
    yum)
      run_root yum install -y docker-compose-plugin
      ;;
    *)
      error "无法自动安装 docker compose 插件。"
      exit 1
      ;;
  esac
}

install_docker_if_needed() {
  if command_exists docker && docker compose version >/dev/null 2>&1; then
    info "检测到 Docker 和 Compose，跳过安装。"
    ensure_docker_service
    return
  fi

  info "开始安装 Docker..."
  install_base_packages
  run_root sh -c "curl -fsSL https://get.docker.com | sh"
  ensure_docker_service
  install_compose_plugin_if_missing
}

run_git_remote() {
  run_root git -C "$INSTALL_DIR" "$@"
}

resolve_repo_mode() {
  if [ "$USE_LOCAL_REPO" = "yes" ]; then
    echo "local"
    return
  fi

  if [ "$USE_LOCAL_REPO" = "no" ]; then
    echo "remote"
    return
  fi

  if [ -d "$SCRIPT_DIR/.git" ] && [ -f "$SCRIPT_DIR/docker-compose.yml" ]; then
    echo "local"
    return
  fi

  echo "remote"
}

prepare_repo() {
  local repo_mode
  repo_mode="$(resolve_repo_mode)"

  if [ "$repo_mode" = "local" ]; then
    INSTALL_DIR="$SCRIPT_DIR"
    info "使用当前本地仓库：$INSTALL_DIR"

    if command_exists git && [ -d "$INSTALL_DIR/.git" ]; then
      info "同步当前仓库最新代码..."
      git -C "$INSTALL_DIR" fetch origin "$BRANCH"
      git -C "$INSTALL_DIR" checkout "$BRANCH"
      git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"
    fi
    return
  fi

  info "准备部署目录：$INSTALL_DIR"
  run_root mkdir -p "$INSTALL_DIR"

  if [ -d "$INSTALL_DIR/.git" ]; then
    info "检测到已存在仓库，拉取最新代码..."
    run_git_remote fetch origin "$BRANCH"
    run_git_remote checkout "$BRANCH"
    run_git_remote pull --ff-only origin "$BRANCH"
    return
  fi

  if [ -n "$(find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | head -n 1)" ]; then
    error "部署目录不是空目录，且不是 Git 仓库：$INSTALL_DIR"
    exit 1
  fi

  info "从远程仓库克隆代码..."
  run_root git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
}

prepare_data_dirs() {
  info "准备持久化目录..."
  run_root mkdir -p "$INSTALL_DIR/data"
  run_root mkdir -p \
    "$INSTALL_DIR/downloads/anime" \
    "$INSTALL_DIR/downloads/landscape" \
    "$INSTALL_DIR/downloads/dynamic" \
    "$INSTALL_DIR/downloads/uncategorized"
}

deploy_app() {
  info "开始构建并启动容器..."
  run_root env APP_PORT="$APP_PORT" TZ="$TZ_VALUE" bash -lc "cd \"$INSTALL_DIR\" && docker compose up -d --build"
}

show_result() {
  local server_ip
  server_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"

  echo
  echo "========================================"
  echo "  ${APP_NAME} 部署完成"
  echo "========================================"
  echo "部署目录: $INSTALL_DIR"
  echo "访问端口: $APP_PORT"
  echo "时区设置: $TZ_VALUE"
  if [ -n "$server_ip" ]; then
    echo "访问地址: http://$server_ip:$APP_PORT"
  else
    echo "访问地址: http://<服务器IP>:$APP_PORT"
  fi
  echo
  echo "常用命令："
  echo "  cd \"$INSTALL_DIR\" && docker compose ps"
  echo "  cd \"$INSTALL_DIR\" && docker compose logs -f"
  echo "  cd \"$INSTALL_DIR\" && docker compose restart"
  echo
}

info "开始执行 Docker 一键部署..."
install_base_packages
install_docker_if_needed
prepare_repo
prepare_data_dirs
deploy_app
show_result
