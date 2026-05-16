/**
 * HITL 决策页 API 客户端（Plan 03-07）。
 *
 * 注意：本模块不走 /lib/api/client.ts（apiCall）—— 该 wrapper 默认 path 前缀 /api，
 * 但 HITL 公网端点裸路径是 /hitl/page/* 和 /hitl/action/*（Phase 1 NET-02 nginx 已开放）。
 *
 * 关键设计：
 * - GET 用 Accept: application/json + credentials: 'include'（cookie 自动携带）
 * - POST 用 application/x-www-form-urlencoded（与后端 FastAPI Form() 装饰器匹配）+ Accept: JSON
 * - cookie forwarding 在 Server Component 中由调用方注入（next/headers cookies）
 */

import type {
  HitlPageResponse,
  HitlSubmitBody,
  HitlSubmitResult,
} from '@/lib/types/hitl';

/**
 * 取 HITL 公网端点基础地址。
 *
 * 客户端：相对路径，nginx 会路由到后端
 * Server Component：可通过 NEXT_PUBLIC_API_BASE 注入内网后端地址
 */
function getHitlBase(): string {
  if (typeof window !== 'undefined') {
    const override = (window as Window & { __HITL_BASE_URL__?: string })
      .__HITL_BASE_URL__;
    if (override) return override;
    return '';
  }
  return process.env.HITL_BASE_URL || process.env.NEXT_PUBLIC_API_BASE || '';
}

/** GET 请求选项 —— SSR 模式下可注入 cookie / user-agent 头。 */
export interface FetchHitlPageOptions {
  cookie?: string;
  userAgent?: string;
  signal?: AbortSignal;
}

/**
 * 拉取 HITL 决策页数据（GET /hitl/page/<token>）。
 *
 * - 后端按 Accept: application/json 返回结构化 JSON
 * - bot UA 路径返回 { bot_scan: true }；调用方据此切换渲染
 * - 异常（401/410/404/400）抛 HitlPageError；调用方按 status 切换 error UI
 */
export async function fetchHitlPage(
  token: string,
  options: FetchHitlPageOptions = {},
): Promise<HitlPageResponse> {
  const url = `${getHitlBase()}/hitl/page/${encodeURIComponent(token)}`;

  const headers: Record<string, string> = {
    Accept: 'application/json',
  };
  if (options.cookie) {
    headers.cookie = options.cookie;
  }
  if (options.userAgent) {
    headers['user-agent'] = options.userAgent;
  }

  const res = await fetch(url, {
    method: 'GET',
    credentials: 'include',
    headers,
    cache: 'no-store',
    signal: options.signal,
  });

  if (!res.ok) {
    const detail = await safeJson(res);
    throw new HitlPageError(
      detail?.error || res.statusText || 'GET /hitl/page 失败',
      res.status,
    );
  }

  return (await res.json()) as HitlPageResponse;
}

/**
 * 提交 HITL 决策（POST /hitl/action/<token>）。
 *
 * - 用 application/x-www-form-urlencoded（后端 FastAPI Form() 装饰器）
 * - form_data 各字段直接展开到 url-encoded body（与 page.html 表单提交一致）
 * - 返回 HitlSubmitResult 联合类型 —— 调用方按 ok 字段判别后续 UI
 */
export async function submitHitlAction(
  token: string,
  body: HitlSubmitBody,
): Promise<HitlSubmitResult> {
  const url = `${getHitlBase()}/hitl/action/${encodeURIComponent(token)}`;

  // FormData / URLSearchParams：与后端 Form() 装饰器匹配
  const params = new URLSearchParams();
  params.set('action', body.action);
  params.set('reason', body.reason);
  for (const [key, value] of Object.entries(body.form_data)) {
    if (value === null || value === undefined) continue;
    // 复杂类型序列化为 JSON 字符串（后端再 jsonschema 校验）
    if (typeof value === 'object') {
      params.set(key, JSON.stringify(value));
    } else {
      params.set(key, String(value));
    }
  }

  const res = await fetch(url, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      Accept: 'application/json',
    },
    body: params.toString(),
  });

  if (res.ok) {
    const data = (await res.json()) as {
      ok: boolean;
      action: string;
      instance_id: string;
      new_node_status: string;
    };
    return {
      ok: true,
      action: data.action,
      instance_id: data.instance_id,
      new_node_status: data.new_node_status,
    };
  }

  const detail = await safeJson(res);
  return {
    ok: false,
    status_code: res.status,
    error: detail?.error || mapStatusToMessage(res.status),
    errors: detail?.errors,
  };
}

/** GET 阶段错误 —— 区分 page 数据获取失败的状态码。 */
export class HitlPageError extends Error {
  public readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'HitlPageError';
    this.status = status;
  }
}

/** 状态码 → 友好中文消息映射。 */
function mapStatusToMessage(status: number): string {
  switch (status) {
    case 400:
      return '请求参数错误';
    case 401:
      return '会话已过期，请重新点击邮件链接';
    case 404:
      return '关联资源不存在';
    case 409:
      return '决策已提交，不可重复操作';
    case 410:
      return '链接已失效';
    case 422:
      return '表单校验失败';
    default:
      return `提交失败（${status}）`;
  }
}

/** 安全解析 JSON 响应（解析失败返回 null）。 */
async function safeJson(
  res: Response,
): Promise<{ error?: string; errors?: string[] } | null> {
  try {
    return (await res.json()) as { error?: string; errors?: string[] };
  } catch {
    return null;
  }
}
