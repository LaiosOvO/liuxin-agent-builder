#!/usr/bin/env bash
# agent-builder PostgreSQL SSH 隧道控制脚本
#
# 拓扑:
#   本机 Mac (localhost:15432) --SSH--> .44 host:5432 --socat--> mattermost-docker-postgres-1:5432 (docker)
#                                       (agent-builder-pg-bridge 容器)
#
# 使用:
#   scripts/db_tunnel.sh up     启动隧道
#   scripts/db_tunnel.sh down   关闭隧道
#   scripts/db_tunnel.sh status 查看隧道状态
#   scripts/db_tunnel.sh psql   通过隧道打开 psql shell (读 .env 取连接串)
#
# 前置:
#   * 已装 sshpass:  brew install hudochenkov/sshpass/sshpass
#   * .ssh_pass 文件存放 SSH 密码 (不入仓), 或环境变量 SSH_PASS
#   * .env 中已配置 POSTGRES_DSN
#   * .44 上的 agent-builder-pg-bridge 容器已运行
#
# 安全:
#   * .ssh_pass 在 .gitignore 内
#   * 隧道用 ServerAliveInterval=30 防止断流
#   * Ctrl+C 不会自动关 (-f 后台), 用 ./db_tunnel.sh down 关闭

set -euo pipefail

SSH_USER="${SSH_USER:-GigaByte}"
SSH_HOST="${SSH_HOST:-192.168.2.44}"
LOCAL_PORT="${LOCAL_PORT:-15432}"
REMOTE_PORT="${REMOTE_PORT:-5432}"

# SSH 密码来源优先级: env > .ssh_pass 文件
if [[ -z "${SSH_PASS:-}" ]]; then
  if [[ -f "$(dirname "$0")/../.ssh_pass" ]]; then
    SSH_PASS="$(<"$(dirname "$0")/../.ssh_pass")"
  else
    echo "✗ 未找到 SSH 密码: 请设 SSH_PASS env 或在仓库根创建 .ssh_pass 文件 (内容仅密码,无换行)"
    exit 1
  fi
fi

PATTERN="${LOCAL_PORT}:localhost:${REMOTE_PORT}"

cmd_status() {
  local pids
  pids=$(pgrep -af "ssh.*${PATTERN}" || true)
  if [[ -n "$pids" ]]; then
    echo "✓ 隧道运行中:"
    echo "$pids"
  else
    echo "✗ 隧道未运行"
    return 1
  fi
}

cmd_up() {
  if cmd_status >/dev/null 2>&1; then
    echo "i 隧道已在跑，跳过启动"
    cmd_status
    return 0
  fi
  echo "▶ 启动 SSH tunnel ${LOCAL_PORT} → ${SSH_HOST}:${REMOTE_PORT}"
  SSHPASS="${SSH_PASS}" sshpass -e ssh -f -N \
    -L "${LOCAL_PORT}:localhost:${REMOTE_PORT}" \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o StrictHostKeyChecking=accept-new \
    "${SSH_USER}@${SSH_HOST}"
  sleep 1
  cmd_status
}

cmd_down() {
  if pgrep -f "ssh.*${PATTERN}" >/dev/null 2>&1; then
    pkill -f "ssh.*${PATTERN}"
    sleep 1
    echo "✓ 隧道已关闭"
  else
    echo "i 没有运行中的隧道"
  fi
}

cmd_psql() {
  cmd_up >/dev/null
  # 从 .env 取连接串
  if [[ ! -f .env ]]; then
    echo "✗ 找不到 .env"
    exit 1
  fi
  local dsn pass user db
  dsn=$(grep '^POSTGRES_DSN=' .env | cut -d'=' -f2-)
  pass=$(echo "$dsn" | sed -E 's|.*//[^:]+:([^@]+)@.*|\1|')
  user=$(echo "$dsn" | sed -E 's|.*//([^:]+):.*|\1|')
  db=$(echo "$dsn" | sed -E 's|.*/([^?]+).*|\1|')
  PGPASSWORD="${pass}" psql -h localhost -p "${LOCAL_PORT}" -U "${user}" -d "${db}"
}

case "${1:-status}" in
  up|start)   cmd_up   ;;
  down|stop)  cmd_down ;;
  status)     cmd_status ;;
  psql)       cmd_psql ;;
  *)
    echo "Usage: $0 {up|down|status|psql}"
    exit 1
    ;;
esac
