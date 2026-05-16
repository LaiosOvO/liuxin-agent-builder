/**
 * Next.js Edge Middleware
 * 负责根据后端初始化状态重定向：
 * - 系统未初始化时强制跳转 /setup
 * - 系统已初始化访问 /setup 时跳回 /
 * - /api/* 路径不拦截（直接透传）
 */

import { type NextRequest, NextResponse } from 'next/server';

/** 不需要 middleware 处理的路径前缀 */
const BYPASS_PREFIXES = [
  '/_next/static',
  '/_next/image',
  '/api/',
  '/favicon',
  '/logo',
  '/bg.',
];

/** 检查路径是否应跳过 middleware */
function shouldBypass(pathname: string): boolean {
  return BYPASS_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

export async function middleware(req: NextRequest): Promise<NextResponse> {
  const { pathname } = req.nextUrl;

  if (shouldBypass(pathname)) {
    return NextResponse.next();
  }

  // 向后端查询初始化状态
  const internalApiBase =
    process.env.INTERNAL_API_BASE ?? 'http://localhost:8000';

  try {
    const res = await fetch(`${internalApiBase}/api/setup/state`, {
      headers: {
        cookie: req.headers.get('cookie') ?? '',
        'x-forwarded-for': req.headers.get('x-forwarded-for') ?? '',
      },
      // 快速超时，避免 middleware 阻塞
      signal: AbortSignal.timeout(3000),
    });

    if (!res.ok) {
      // 后端不可用时放行（fail-open for setup，fail-close 由后端自身决定）
      return NextResponse.next();
    }

    const data = (await res.json()) as { initialized: boolean; version: string };

    // 系统未初始化，除 /setup 外全部跳到 /setup
    if (!data.initialized && pathname !== '/setup') {
      return NextResponse.redirect(new URL('/setup', req.url));
    }

    // 系统已初始化，访问 /setup 跳回根路径
    if (data.initialized && pathname === '/setup') {
      return NextResponse.redirect(new URL('/', req.url));
    }
  } catch {
    // 超时或网络错误时放行，不阻塞页面访问
    return NextResponse.next();
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * 匹配所有路径，排除：
     * - _next/static（静态文件）
     * - _next/image（图片优化）
     * - favicon.ico
     */
    '/((?!_next/static|_next/image|favicon.ico).*)',
  ],
};
