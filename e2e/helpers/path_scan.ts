/**
 * 公网最小暴露面路径定义（NET-02 E2E 验收辅助）。
 *
 * EXPECTED_FORBIDDEN_PATHS: nginx 80 端口应返回 403 的路径列表
 * EXPECTED_PROXIED_PATHS: nginx 80 端口应转给后端的路径列表（返回非 403）
 *
 * 前置条件：docker-compose up -d nginx api web 已就绪
 */

/** 公网 80 端口应被 nginx 直接拦截（返回 403）的路径 */
export const EXPECTED_FORBIDDEN_PATHS: readonly string[] = [
  // 根路径
  '/',

  // 管理后台
  '/admin',
  '/admin/',
  '/admin/login',
  '/admin/users',
  '/api/admin',
  '/api/admin/',
  '/api/setup',

  // API 通用路径（除 /api/im/webhook/ 之外的所有 /api/ 路径）
  '/api',
  '/api/',
  '/api/v1',
  '/api/v1/',
  '/api/users',
  '/api/auth',
  '/api/auth/login',
  '/api/auth/register',
  '/api/auth/me',
  '/api/workflows',
  '/api/v1/instances',
  '/api/v1/teams',

  // 登录 / 注册页
  '/login',
  '/register',
  '/setup',
  '/install',

  // 管理 UI
  '/dashboard',
  '/workflows',
  '/settings',

  // 健康检查 / 监控（内网才能访问）
  '/health',
  '/healthz',
  '/ready',
  '/metrics',
  '/status',

  // API 文档（生产应关闭，开发时内网访问）
  '/docs',
  '/redoc',
  '/openapi.json',
  '/swagger',
  '/swagger-ui',

  // 静态文件 / 前端
  '/static/x.js',
  '/_next/static/test.js',
  '/favicon.ico',

  // 常见扫描路径
  '/wp-admin',
  '/wp-admin/admin.php',
  '/wp-login.php',
  '/phpmyadmin',
  '/phpmyadmin/',
  '/grafana',
  '/grafana/',
  '/.env',
  '/.git/config',
  '/.git/HEAD',
  '/config.json',
  '/robots.txt',
  '/sitemap.xml',
  '/server-status',
  '/nginx-status',
] as const;

/**
 * 公网 80 端口应被 nginx 转给后端的路径。
 * 后端可能返回 200 / 400 / 401 / 404 / 422 等，但不会是 nginx 级 403。
 */
export const EXPECTED_PROXIED_PATHS: readonly string[] = [
  '/hitl/page/whatever-token-12345',
  '/hitl/action/whatever-token-abcde',
  '/api/im/webhook/feishu',
  '/api/im/webhook/wecom',
] as const;
