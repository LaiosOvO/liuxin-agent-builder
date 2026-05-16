#!/usr/bin/env bash
# scan_public_paths.sh — 公网最小暴露面扫描脚本
# 验证 nginx 80 端口仅放行 3 条路径，其余全部 403
# NET-02 验收测试工具
#
# 用法：
#   bash nginx/test/scan_public_paths.sh [BASE_URL]
#   BASE_URL 默认为 http://localhost:80
#
# 输出格式：
#   PATH | EXPECT | ACTUAL | RESULT
#
# 退出码：
#   0 = 全部通过
#   1 = 有 FAIL

set -euo pipefail

BASE_URL="${1:-http://localhost:80}"
PASS=0
FAIL=0
TOTAL=0

# 颜色输出
RED="\033[0;31m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
NC="\033[0m"  # No Color

check() {
    local path="$1"
    local expect="$2"  # "403" 或 "NOT_403"
    TOTAL=$((TOTAL + 1))

    local actual
    actual=$(curl -s -o /dev/null -w "%{http_code}" \
        --max-time 5 \
        --connect-timeout 3 \
        "${BASE_URL}${path}" 2>/dev/null || echo "000")

    local result
    if [ "$expect" = "403" ]; then
        if [ "$actual" = "403" ]; then
            result="PASS"
            PASS=$((PASS + 1))
        else
            result="FAIL"
            FAIL=$((FAIL + 1))
        fi
    else
        # NOT_403：nginx 已将请求转给后端（后端可能返回 200/400/401/422/500 等，均非 nginx 级 403）
        if [ "$actual" != "403" ]; then
            result="PASS"
            PASS=$((PASS + 1))
        else
            result="FAIL"
            FAIL=$((FAIL + 1))
        fi
    fi

    local color="${GREEN}"
    [ "$result" = "FAIL" ] && color="${RED}"

    printf "${color}%-55s | %-8s | %-8s | %s${NC}\n" "$path" "$expect" "$actual" "$result"
}

echo ""
echo "============================================================"
echo "公网最小暴露面扫描 — ${BASE_URL}"
echo "============================================================"
printf "%-55s | %-8s | %-8s | %s\n" "PATH" "EXPECT" "ACTUAL" "RESULT"
printf "%s\n" "----------------------------------------------------------------------"

echo ""
echo "${YELLOW}[应放行路径] nginx 转给后端，后端决定最终响应码${NC}"
echo "----------------------------------------------------------------------"
# 这 4 条路径 nginx 会转给后端（返回非 403，后端可能 200/401/422）
check "/hitl/page/whatever-token-12345"          "NOT_403"
check "/hitl/action/whatever-token-abcde"        "NOT_403"
check "/api/im/webhook/feishu"                   "NOT_403"
check "/api/im/webhook/wecom"                    "NOT_403"

echo ""
echo "${YELLOW}[应禁止路径] nginx 直接返回 403${NC}"
echo "----------------------------------------------------------------------"
# 根路径
check "/"                                        "403"
# 管理后台
check "/admin"                                   "403"
check "/admin/"                                  "403"
check "/admin/login"                             "403"
check "/admin/users"                             "403"
check "/api/admin"                               "403"
check "/api/admin/"                              "403"
check "/api/setup"                               "403"
# API 通用路径（除 /api/im/webhook 的所有 /api/ 路径）
check "/api"                                     "403"
check "/api/"                                    "403"
check "/api/v1"                                  "403"
check "/api/v1/"                                 "403"
check "/api/users"                               "403"
check "/api/auth"                                "403"
check "/api/auth/login"                          "403"
check "/api/auth/register"                       "403"
check "/api/auth/me"                             "403"
check "/api/workflows"                           "403"
check "/api/v1/instances"                        "403"
check "/api/v1/teams"                            "403"
# 登录 / 注册页
check "/login"                                   "403"
check "/register"                                "403"
check "/setup"                                   "403"
check "/install"                                 "403"
# 管理 UI
check "/dashboard"                               "403"
check "/workflows"                               "403"
check "/settings"                                "403"
# 健康检查 / 监控（内网才能访问）
check "/health"                                  "403"
check "/healthz"                                 "403"
check "/ready"                                   "403"
check "/metrics"                                 "403"
check "/status"                                  "403"
# API 文档（生产应关闭，开发时内网访问）
check "/docs"                                    "403"
check "/redoc"                                   "403"
check "/openapi.json"                            "403"
check "/swagger"                                 "403"
check "/swagger-ui"                              "403"
# 静态文件 / 前端
check "/static/x.js"                             "403"
check "/_next/static/test.js"                    "403"
check "/_next/image?url=test"                    "403"
check "/favicon.ico"                             "403"
# 常见扫描路径
check "/wp-admin"                                "403"
check "/wp-admin/admin.php"                      "403"
check "/wp-login.php"                            "403"
check "/phpmyadmin"                              "403"
check "/phpmyadmin/"                             "403"
check "/grafana"                                 "403"
check "/grafana/"                                "403"
check "/.env"                                    "403"
check "/.git/config"                             "403"
check "/.git/HEAD"                               "403"
check "/config.json"                             "403"
check "/robots.txt"                              "403"
check "/sitemap.xml"                             "403"
check "/server-status"                           "403"
check "/nginx-status"                            "403"

echo ""
echo "${YELLOW}[server_tokens 检查] nginx 应不暴露版本号${NC}"
echo "----------------------------------------------------------------------"
SERVER_HEADER=$(curl -s -I --max-time 5 "${BASE_URL}/" 2>/dev/null | grep -i "^Server:" | tr -d '\r' || echo "")
printf "%-55s | %-8s | %-8s | " "Server 响应头" "无版本号" "${SERVER_HEADER}"
if echo "$SERVER_HEADER" | grep -qE "nginx/[0-9]"; then
    echo -e "${RED}FAIL${NC}"
    FAIL=$((FAIL + 1))
    TOTAL=$((TOTAL + 1))
else
    echo -e "${GREEN}PASS${NC}"
    PASS=$((PASS + 1))
    TOTAL=$((TOTAL + 1))
fi

echo ""
echo "============================================================"
echo "扫描完成：总计 ${TOTAL} 条 | 通过 ${PASS} | 失败 ${FAIL}"
echo "============================================================"
echo ""

if [ "$FAIL" -gt 0 ]; then
    echo -e "${RED}ERROR: 有 ${FAIL} 条路径检查未通过，公网暴露面存在风险！${NC}"
    exit 1
else
    echo -e "${GREEN}OK: 所有路径检查通过，公网暴露面符合预期。${NC}"
    exit 0
fi
