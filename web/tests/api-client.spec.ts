/**
 * API 客户端单元测试
 * 使用 msw 拦截 fetch 请求，验证 apiCall 行为
 */

import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import { apiCall, ApiCallError } from '@/lib/api/client';

// 设置 MSW 测试服务器（node 模式，拦截所有 http://localhost/api/* 请求）
const server = setupServer();

beforeAll(() => {
  // 在 jsdom 中设置 location，使 API_BASE 逻辑使用绝对 URL 前缀
  Object.defineProperty(window, 'location', {
    writable: true,
    value: { href: 'http://localhost/', assign: vi.fn() },
  });
  // 模拟 window.__API_BASE_URL__ 为绝对 URL
  (window as Window & { __API_BASE_URL__?: string }).__API_BASE_URL__ = 'http://localhost/api';
  server.listen({ onUnhandledRequest: 'warn' });
});

afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});

afterAll(() => server.close());

describe('apiCall', () => {
  it('自动携带 credentials=include 并解析 JSON 响应', async () => {
    let capturedCredentials: RequestCredentials | undefined;

    server.use(
      http.get('http://localhost/api/test', ({ request }) => {
        capturedCredentials = request.credentials;
        return HttpResponse.json({ ok: true });
      }),
    );

    const result = await apiCall<{ ok: boolean }>('/test');

    expect(result).toEqual({ ok: true });
    expect(capturedCredentials).toBe('include');
  });

  it('GET 请求时不设置 Content-Type', async () => {
    let capturedContentType: string | null = null;

    server.use(
      http.get('http://localhost/api/no-content-type', ({ request }) => {
        capturedContentType = request.headers.get('content-type');
        return HttpResponse.json({ ok: true });
      }),
    );

    await apiCall<{ ok: boolean }>('/no-content-type');
    expect(capturedContentType).toBeNull();
  });

  it('POST 请求时自动设置 Content-Type: application/json', async () => {
    let capturedContentType: string | null = null;

    server.use(
      http.post('http://localhost/api/json-body', ({ request }) => {
        capturedContentType = request.headers.get('content-type');
        return HttpResponse.json({ ok: true });
      }),
    );

    await apiCall<{ ok: boolean }>('/json-body', {
      method: 'POST',
      body: { data: 'test' },
    });

    expect(capturedContentType).toContain('application/json');
  });

  it('非 200 响应时抛出 ApiCallError 含 status 与 detail', async () => {
    server.use(
      http.get('http://localhost/api/error-endpoint', () => {
        return HttpResponse.json(
          { error: '资源不存在', detail: '指定 ID 未找到' },
          { status: 404 },
        );
      }),
    );

    await expect(apiCall('/error-endpoint')).rejects.toMatchObject({
      status: 404,
      message: '资源不存在',
      detail: { error: '资源不存在', detail: '指定 ID 未找到' },
    });
  });

  it('抛出的错误是 ApiCallError 实例', async () => {
    server.use(
      http.get('http://localhost/api/bad', () => {
        return HttpResponse.json({ error: '出错了' }, { status: 500 });
      }),
    );

    let thrownError: unknown;
    try {
      await apiCall('/bad');
    } catch (e) {
      thrownError = e;
    }

    expect(thrownError).toBeInstanceOf(ApiCallError);
  });

  it('401 时（非 login/setup 路径）设置 window.location.href 跳转到 /login', async () => {
    server.use(
      http.get('http://localhost/api/protected', () => {
        return HttpResponse.json({ error: '未授权' }, { status: 401 });
      }),
    );

    // 使用 Object.defineProperty 追踪 href 赋值
    let redirectTarget = '';
    Object.defineProperty(window, 'location', {
      writable: true,
      configurable: true,
      value: {
        href: 'http://localhost/',
        set href(v: string) { redirectTarget = v; },
        get href() { return 'http://localhost/'; },
        assign: vi.fn(),
      },
    });

    try {
      await apiCall('/protected');
    } catch {
      // 预期抛出 ApiCallError
    }

    expect(redirectTarget).toBe('/login');
  });

  it('401 时 /auth/login 路径不触发跳转', async () => {
    server.use(
      http.post('http://localhost/api/auth/login', () => {
        return HttpResponse.json({ error: '邮箱或密码错误' }, { status: 401 });
      }),
    );

    let redirectCalled = false;
    Object.defineProperty(window, 'location', {
      writable: true,
      configurable: true,
      value: {
        get href() { return 'http://localhost/'; },
        set href(_v: string) { redirectCalled = true; },
        assign: vi.fn(),
      },
    });

    try {
      await apiCall('/auth/login', { method: 'POST', body: {} });
    } catch {
      // 预期抛出
    }

    expect(redirectCalled).toBe(false);
  });

  it('setup 路径 401 不触发跳转', async () => {
    server.use(
      http.get('http://localhost/api/setup/state', () => {
        return HttpResponse.json({ error: '服务未就绪' }, { status: 401 });
      }),
    );

    let redirectCalled = false;
    Object.defineProperty(window, 'location', {
      writable: true,
      configurable: true,
      value: {
        get href() { return 'http://localhost/'; },
        set href(_v: string) { redirectCalled = true; },
        assign: vi.fn(),
      },
    });

    try {
      await apiCall('/setup/state');
    } catch {
      // 预期抛出
    }

    expect(redirectCalled).toBe(false);
  });

  it('响应体非 JSON 时 error 字段 fallback 为 statusText', async () => {
    server.use(
      http.get('http://localhost/api/non-json', () => {
        return new HttpResponse('Not Found', {
          status: 404,
          headers: { 'Content-Type': 'text/plain' },
        });
      }),
    );

    await expect(apiCall('/non-json')).rejects.toMatchObject({
      status: 404,
    });
  });
});
