#!/usr/bin/env bash
# run_all_tests.sh — 一条命令跑三层测试 (CLAUDE.md 2.2)
#
# 三层覆盖:
#   1. pytest  (backend/tests)      Unit + Integration  (testcontainers)
#   2. vitest  (web/tests)          前端组件单元
#   3. playwright (e2e/)            E2E  (需要 docker-compose up + RUN_E2E=1)
#
# 用法:
#   scripts/run_all_tests.sh                # 跑前 2 层
#   RUN_E2E=1 scripts/run_all_tests.sh      # 跑全部 3 层 (前提: docker compose up -d)
#
# 退出码:
#   0 = 全过 (含 skip)
#   N = 失败层数

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PASS=()
FAIL=()
SKIP=()

run_layer() {
  local name=$1
  shift
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Layer: $name"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  if "$@"; then
    PASS+=("$name")
  else
    FAIL+=("$name")
  fi
}

# 1. Pytest (后端)
if [[ -d backend/tests ]] && command -v python >/dev/null 2>&1; then
  run_layer "pytest (backend)" bash -c "cd backend && python -m pytest tests/ -x --tb=short"
else
  SKIP+=("pytest (backend/tests 或 python 缺失)")
fi

# 2. Vitest (前端)
if [[ -f web/vitest.config.ts ]] && command -v npx >/dev/null 2>&1; then
  run_layer "vitest (web)" bash -c "cd web && npx vitest run --reporter=verbose"
else
  SKIP+=("vitest (web/vitest.config.ts 或 npx 缺失)")
fi

# 3. Playwright (E2E)
if [[ "${RUN_E2E:-0}" == "1" ]]; then
  if [[ -f e2e/playwright.config.ts ]] && command -v npx >/dev/null 2>&1; then
    run_layer "playwright (e2e)" bash -c "cd e2e && npx playwright test"
  else
    SKIP+=("playwright (e2e/playwright.config.ts 或 npx 缺失)")
  fi
else
  SKIP+=("playwright (set RUN_E2E=1 + docker compose up 后启用)")
fi

echo ""
echo "═════════════════ Summary ═════════════════"
[[ ${#PASS[@]} -gt 0 ]] && printf '  ✓ PASS: %s\n' "${PASS[@]}"
[[ ${#FAIL[@]} -gt 0 ]] && printf '  ✗ FAIL: %s\n' "${FAIL[@]}"
[[ ${#SKIP[@]} -gt 0 ]] && printf '  - SKIP: %s\n' "${SKIP[@]}"
echo "════════════════════════════════════════════"

exit "${#FAIL[@]}"
