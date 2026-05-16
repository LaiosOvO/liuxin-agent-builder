#!/usr/bin/env bash
# bootstrap_fork.sh — 幂等 fork 重建脚本
#
# 用途:
#   新开发者首次 clone 仓库后, 若 backend/ 或 web/ 缺失, 运行此脚本从
#   Onelevenvy/flock 重建. 当前提交已 vendor 了 flock 源码, 通常不需要跑.
#
# 用法:
#   scripts/bootstrap_fork.sh           # 检查 backend/web 是否存在, 缺失才 fork
#   FORCE=1 scripts/bootstrap_fork.sh   # 强制重建 (会删现有 backend/web)
#   FLOCK_COMMIT=<hash> scripts/...     # 指定不同 commit
#
# 注意:
#   * 本脚本 NEVER merge 上游 (fork = 快照)
#   * .planning/phases/01-skeleton/FORK_AUDIT.md 记录当前 vendor 的 commit hash
#   * 仅在新开发者环境用; CI 不需要 (源码已 vendor 进 git)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

FLOCK_COMMIT="${FLOCK_COMMIT:-8b6aebbf1530d3968c050c422a8ed69e1de610e5}"
FLOCK_URL="${FLOCK_URL:-https://github.com/Onelevenvy/flock.git}"
TEMP_DIR="$(mktemp -d -t agent-builder-fork-XXXXX)"

cleanup() { rm -rf "$TEMP_DIR"; }
trap cleanup EXIT

echo "▶ bootstrap_fork.sh — ${FLOCK_URL}@${FLOCK_COMMIT}"

if [[ -d backend/ && -d web/ && "${FORCE:-0}" != "1" ]]; then
  echo "✓ backend/ + web/ 已存在, 跳过. 设 FORCE=1 强制重建."
  exit 0
fi

if [[ "${FORCE:-0}" == "1" ]]; then
  echo "⚠ FORCE=1: 删除现有 backend/ + web/"
  rm -rf backend/ web/
fi

echo "▶ Clone flock to $TEMP_DIR/flock"
git clone --depth=15 "$FLOCK_URL" "$TEMP_DIR/flock" 2>&1 | tail -3
(cd "$TEMP_DIR/flock" && git checkout "$FLOCK_COMMIT") 2>&1 | tail -3

echo "▶ Copy backend/ web/"
cp -R "$TEMP_DIR/flock/backend/" backend/
cp -R "$TEMP_DIR/flock/web/" web/

echo "▶ Clean lockfiles (会重新生成)"
rm -f backend/uv.lock backend/test.db web/pnpm-lock.yaml

echo "▶ Rebrand: pyproject.toml name"
if [[ -f backend/pyproject.toml ]]; then
  sed -i.bak 's/^name = "flock"/name = "agent-builder"/' backend/pyproject.toml || true
  sed -i.bak 's/^description = "Flock project"/description = "agent-builder — 通用拖拽式 LangGraph 编排平台 (fork from Onelevenvy\/flock)"/' backend/pyproject.toml || true
  rm -f backend/pyproject.toml.bak
fi

echo "▶ Rebrand: package.json name"
if [[ -f web/package.json ]]; then
  sed -i.bak 's/"name": "web"/"name": "agent-builder-web"/' web/package.json
  rm -f web/package.json.bak
fi

echo ""
echo "✓ Bootstrap 完成. 见 .planning/phases/01-skeleton/FORK_AUDIT.md"
echo "  下一步: 装依赖 → docker compose build → docker compose up"
