#!/usr/bin/env bash
# =============================================================================
# wss-recorder-arm 一键安装 / 部署脚本（ARM64 Linux）
# 用法（在项目根目录）:
#   chmod +x install.sh && sudo ./install.sh
# 可选环境变量:
#   INSTALL_DIR=/opt/wss-recorder-arm   安装目录（默认当前目录或 /opt/wss-recorder-arm）
#   WSS_CONSOLE_PASSWORD=xxx           控制台密码（默认随机生成）
#   WSS_DEVICE_ID=14eaa12a154e         设备 SN
#   WSS_PORT=8080                      映射端口
#   SKIP_DOCKER_INSTALL=1              跳过 Docker 安装
#   NON_INTERACTIVE=1                  不询问确认
# =============================================================================
set -euo pipefail

APP_NAME="wss-recorder-arm"
DEFAULT_INSTALL_DIR="/opt/wss-recorder-arm"
DEFAULT_PORT="8080"
DEFAULT_DEVICE_ID="14eaa12a154e"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-wss-recorder}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; }
info() { echo -e "${CYAN}[i]${NC} $*"; }

die() { err "$*"; exit 1; }

need_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    die "请使用 root 运行: sudo $0 $*"
  fi
}

rand_hex() {
  local n="${1:-24}"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$n"
  elif [[ -r /dev/urandom ]]; then
    head -c "$n" /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c $((n * 2))
  else
    date +%s%N | sha256sum | awk '{print $1}'
  fi
}

detect_arch() {
  local m
  m="$(uname -m)"
  case "$m" in
    aarch64|arm64) echo "arm64" ;;
    x86_64|amd64)  echo "amd64" ;;
    *)             echo "$m" ;;
  esac
}

detect_os() {
  if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    echo "${ID:-linux}"
  else
    echo "linux"
  fi
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    echo "docker compose"
  elif have_cmd docker-compose; then
    echo "docker-compose"
  else
    return 1
  fi
}

primary_ip() {
  local ip=""
  ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}' || true)"
  if [[ -z "$ip" ]]; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  fi
  if [[ -z "$ip" ]]; then
    ip="127.0.0.1"
  fi
  echo "$ip"
}

ensure_packages_basic() {
  local os_id
  os_id="$(detect_os)"
  log "安装基础依赖 (curl ca-certificates) ..."
  case "$os_id" in
    ubuntu|debian|raspbian|armbian)
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -y
      apt-get install -y --no-install-recommends ca-certificates curl gnupg lsb-release openssl
      ;;
    centos|rhel|rocky|almalinux|fedora|opencloudos|anolis)
      if have_cmd dnf; then
        dnf install -y curl ca-certificates openssl
      else
        yum install -y curl ca-certificates openssl
      fi
      ;;
    alpine)
      apk add --no-cache curl ca-certificates openssl
      ;;
    *)
      warn "未知发行版 ($os_id)，跳过包管理器安装；请确保 curl/openssl 可用"
      ;;
  esac
}

install_docker() {
  if have_cmd docker && compose_cmd >/dev/null 2>&1; then
    log "Docker 与 Compose 已就绪: $(docker --version)"
    return 0
  fi

  if [[ "${SKIP_DOCKER_INSTALL:-0}" == "1" ]]; then
    die "未找到 Docker/Compose，且 SKIP_DOCKER_INSTALL=1"
  fi

  local os_id arch
  os_id="$(detect_os)"
  arch="$(detect_arch)"
  log "安装 Docker (arch=${arch}, os=${os_id}) ..."

  case "$os_id" in
    ubuntu|debian|raspbian|armbian)
      export DEBIAN_FRONTEND=noninteractive
      # 官方便捷脚本对 arm64 兼容较好
      if curl -fsSL https://get.docker.com -o /tmp/get-docker.sh; then
        sh /tmp/get-docker.sh
      else
        warn "get.docker.com 失败，尝试发行版仓库 ..."
        apt-get install -y docker.io docker-compose-plugin || apt-get install -y docker.io docker-compose
      fi
      ;;
    centos|rhel|rocky|almalinux|fedora|opencloudos|anolis)
      if curl -fsSL https://get.docker.com -o /tmp/get-docker.sh; then
        sh /tmp/get-docker.sh
      else
        die "无法安装 Docker，请手动安装后重试"
      fi
      ;;
    alpine)
      apk add --no-cache docker docker-cli-compose || apk add --no-cache docker docker-compose
      rc-update add docker default 2>/dev/null || true
      service docker start 2>/dev/null || true
      ;;
    *)
      if curl -fsSL https://get.docker.com -o /tmp/get-docker.sh; then
        sh /tmp/get-docker.sh
      else
        die "无法自动安装 Docker，请手动安装 docker + compose 后重试"
      fi
      ;;
  esac

  systemctl enable docker 2>/dev/null || true
  systemctl start docker 2>/dev/null || service docker start 2>/dev/null || true

  if ! have_cmd docker; then
    die "Docker 安装失败"
  fi
  if ! compose_cmd >/dev/null 2>&1; then
    # 尝试补装 compose 插件
    local os_id2
    os_id2="$(detect_os)"
    case "$os_id2" in
      ubuntu|debian|raspbian|armbian)
        apt-get install -y docker-compose-plugin || apt-get install -y docker-compose || true
        ;;
    esac
  fi
  if ! compose_cmd >/dev/null 2>&1; then
    die "Docker Compose 不可用，请安装 docker-compose-plugin 或 docker-compose"
  fi
  log "Docker 安装完成: $(docker --version)"
}

find_project_root() {
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [[ -f "${here}/Dockerfile" && -f "${here}/docker-compose.yml" && -d "${here}/app" ]]; then
    echo "$here"
    return 0
  fi
  if [[ -f "./Dockerfile" && -f "./docker-compose.yml" && -d "./app" ]]; then
    pwd
    return 0
  fi
  return 1
}

prepare_install_dir() {
  local src="$1"
  local dest="$2"

  mkdir -p "$dest"
  if [[ "$(cd "$src" && pwd)" == "$(cd "$dest" && pwd)" ]]; then
    log "在源码目录内部署: $dest"
    return 0
  fi

  log "同步项目到 $dest ..."
  # 保留 data / .env，覆盖代码与编排文件
  rsync -a --delete \
    --exclude '.venv' \
    --exclude 'venv' \
    --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    --exclude '.git' \
    --exclude 'data' \
    --exclude '.env' \
    --exclude 'config.yaml' \
    --exclude 'deploy.tgz' \
    --exclude '*.pyc' \
    "$src"/ "$dest"/ 2>/dev/null || {
      # 无 rsync 时用 tar
      tar -C "$src" \
        --exclude='.venv' --exclude='venv' --exclude='__pycache__' \
        --exclude='.pytest_cache' --exclude='.git' --exclude='data' \
        --exclude='.env' --exclude='config.yaml' --exclude='deploy.tgz' \
        -cf - . | tar -C "$dest" -xf -
    }
}

write_env_and_config() {
  local dest="$1"
  local password="$2"
  local secret="$3"
  local device_id="$4"
  local port="$5"

  mkdir -p "${dest}/data/recordings"

  if [[ ! -f "${dest}/data/config.yaml" ]]; then
    if [[ -f "${dest}/config.example.yaml" ]]; then
      cp "${dest}/config.example.yaml" "${dest}/data/config.yaml"
      log "已生成 data/config.yaml"
    else
      die "缺少 config.example.yaml"
    fi
  else
    info "保留已有 data/config.yaml"
  fi

  # 写入 .env（compose 读取）
  cat > "${dest}/.env" <<EOF
# generated by install.sh $(date -Iseconds 2>/dev/null || date)
WSS_CONSOLE_PASSWORD=${password}
WSS_SESSION_SECRET=${secret}
WSS_DEVICE_ID=${device_id}
WSS_AUTO_START=true
WSS_PORT=${port}
TZ=Asia/Shanghai
EOF
  chmod 600 "${dest}/.env"
  log "已写入 .env（权限 600）"

  # 确保 compose 端口可配置
  if [[ -f "${dest}/docker-compose.yml" ]]; then
    # 若仍是硬编码 8080:8080，替换为 ${WSS_PORT:-8080}:8080
    if grep -q '"8080:8080"\|- "8080:8080"\|- 8080:8080' "${dest}/docker-compose.yml"; then
      sed -i.bak 's/"8080:8080"/"${WSS_PORT:-8080}:8080"/g; s/- 8080:8080/- "${WSS_PORT:-8080}:8080"/g' "${dest}/docker-compose.yml" || true
    fi
  fi
}

deploy_compose() {
  local dest="$1"
  local ccmd
  ccmd="$(compose_cmd)" || die "compose 不可用"

  cd "$dest"
  log "停止旧容器（如有）..."
  $ccmd down 2>/dev/null || true

  log "构建镜像（可能需要数分钟，尤其是 arm64 首次构建）..."
  $ccmd build --pull

  log "启动服务..."
  $ccmd up -d

  # 等待健康
  local i
  for i in $(seq 1 40); do
    if curl -fsS "http://127.0.0.1:${WSS_PORT:-8080}/api/health" >/dev/null 2>&1; then
      log "健康检查通过"
      return 0
    fi
    sleep 1
  done
  warn "健康检查超时，请查看日志: cd ${dest} && ${ccmd} logs --tail 80"
  return 0
}

open_firewall() {
  local port="$1"
  if have_cmd ufw && ufw status 2>/dev/null | grep -qi active; then
    ufw allow "${port}/tcp" >/dev/null 2>&1 || true
    info "已尝试 ufw allow ${port}/tcp"
  fi
  if have_cmd firewall-cmd && systemctl is-active firewalld >/dev/null 2>&1; then
    firewall-cmd --permanent --add-port="${port}/tcp" >/dev/null 2>&1 || true
    firewall-cmd --reload >/dev/null 2>&1 || true
    info "已尝试 firewalld 放行 ${port}/tcp"
  fi
}

print_banner() {
  echo
  echo -e "${BOLD}========================================${NC}"
  echo -e "${BOLD}  wss-recorder-arm 一键部署${NC}"
  echo -e "${BOLD}========================================${NC}"
  echo
}

print_credentials() {
  local dest="$1"
  local password="$2"
  local secret="$3"
  local device_id="$4"
  local port="$5"
  local ip
  ip="$(primary_ip)"
  local arch
  arch="$(detect_arch)"

  # 持久化一份密钥信息到安装目录（仅 root 可读）
  local cred_file="${dest}/CREDENTIALS.txt"
  cat > "$cred_file" <<EOF
# wss-recorder-arm 部署信息 — $(date -Iseconds 2>/dev/null || date)
# 请妥善保管，勿提交到 git

安装目录:     ${dest}
架构:         ${arch} ($(uname -m))
本机 IP:      ${ip}
访问地址:     http://${ip}:${port}
本机地址:     http://127.0.0.1:${port}
控制台密码:   ${password}
Session密钥:  ${secret}
设备 ID:      ${device_id}
配置文件:     ${dest}/data/config.yaml
环境变量:     ${dest}/.env
数据目录:     ${dest}/data
录像目录:     ${dest}/data/recordings

常用命令:
  查看状态:   cd ${dest} && $(compose_cmd 2>/dev/null || echo 'docker compose') ps
  查看日志:   cd ${dest} && $(compose_cmd 2>/dev/null || echo 'docker compose') logs -f --tail 100
  重启服务:   cd ${dest} && $(compose_cmd 2>/dev/null || echo 'docker compose') restart
  停止服务:   cd ${dest} && $(compose_cmd 2>/dev/null || echo 'docker compose') down
  健康检查:   curl -sS http://127.0.0.1:${port}/api/health

获取 Ticket:
  1. 浏览器打开 https://qly.cmviot.cn/normal/hubs/home 并登录
  2. F12 → Network → WS → 播放摄像头
  3. 找到 wss://...?ticket=xxxx ，复制 ticket
  4. 打开控制台 Ticket 页粘贴保存，Dashboard 开始录制
EOF
  chmod 600 "$cred_file"

  echo
  echo -e "${GREEN}${BOLD}========== 部署成功 / 关键信息 ==========${NC}"
  echo -e "  ${BOLD}访问地址${NC}     : ${CYAN}http://${ip}:${port}${NC}"
  echo -e "  ${BOLD}本机地址${NC}     : http://127.0.0.1:${port}"
  echo -e "  ${BOLD}控制台密码${NC}   : ${YELLOW}${password}${NC}"
  echo -e "  ${BOLD}Session 密钥${NC} : ${secret}"
  echo -e "  ${BOLD}设备 ID${NC}      : ${device_id}"
  echo -e "  ${BOLD}安装目录${NC}     : ${dest}"
  echo -e "  ${BOLD}配置文件${NC}     : ${dest}/data/config.yaml"
  echo -e "  ${BOLD}密钥备份${NC}     : ${cred_file}"
  echo -e "${GREEN}${BOLD}========================================${NC}"
  echo
  info "日志: cd ${dest} && $(compose_cmd) logs -f --tail 100"
  info "健康: curl -sS http://127.0.0.1:${port}/api/health"
  echo
}

main() {
  print_banner
  need_root "$@"

  local arch
  arch="$(detect_arch)"
  if [[ "$arch" != "arm64" && "$arch" != "amd64" ]]; then
    warn "当前架构 $(uname -m) 未专门测试，将继续尝试部署"
  else
    log "检测到架构: ${arch} ($(uname -m))"
  fi

  local src
  if ! src="$(find_project_root)"; then
    die "请在项目根目录执行（需含 Dockerfile / docker-compose.yml / app/）"
  fi
  log "项目源码: $src"

  local dest="${INSTALL_DIR:-}"
  if [[ -z "$dest" ]]; then
    # 若已在 /opt 下或显式希望原地安装，用源码目录
    if [[ "$src" == /opt/* ]] || [[ "${IN_PLACE:-0}" == "1" ]]; then
      dest="$src"
    else
      dest="$DEFAULT_INSTALL_DIR"
    fi
  fi

  local port="${WSS_PORT:-$DEFAULT_PORT}"
  local device_id="${WSS_DEVICE_ID:-$DEFAULT_DEVICE_ID}"
  local password="${WSS_CONSOLE_PASSWORD:-}"
  local secret="${WSS_SESSION_SECRET:-}"

  # 若已有 .env，优先复用密码（升级场景）
  if [[ -z "$password" && -f "${dest}/.env" ]]; then
    # shellcheck disable=SC1090
    password="$(grep -E '^WSS_CONSOLE_PASSWORD=' "${dest}/.env" | head -1 | cut -d= -f2- || true)"
  fi
  if [[ -z "$secret" && -f "${dest}/.env" ]]; then
    secret="$(grep -E '^WSS_SESSION_SECRET=' "${dest}/.env" | head -1 | cut -d= -f2- || true)"
  fi
  if [[ -z "$password" ]]; then
    password="$(rand_hex 8)"
  fi
  if [[ -z "$secret" ]]; then
    secret="wss-$(rand_hex 24)"
  fi

  export WSS_PORT="$port"

  if [[ "${NON_INTERACTIVE:-0}" != "1" && -t 0 ]]; then
    echo "将安装到: ${dest}"
    echo "端口: ${port}  设备ID: ${device_id}"
    read -r -p "继续? [Y/n] " ans || true
    case "${ans:-Y}" in
      n|N|no|NO) die "已取消" ;;
    esac
  fi

  ensure_packages_basic
  install_docker
  prepare_install_dir "$src" "$dest"
  write_env_and_config "$dest" "$password" "$secret" "$device_id" "$port"
  open_firewall "$port"
  deploy_compose "$dest"
  print_credentials "$dest" "$password" "$secret" "$device_id" "$port"
}

main "$@"
