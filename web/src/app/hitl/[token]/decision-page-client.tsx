/**
 * HITL 决策页客户端容器（Plan 03-07）。
 *
 * 设计要点：
 * - 客户端 fetch 后端 GET /hitl/page（Accept: application/json）
 * - 浏览器自动携带 cookie（包括 hitl_session_<jti>）
 * - 4 种状态：loading / error / bot_scan / decision
 * - 超时通过 DeadlineCountdown.onTimeout 回调禁用 DecisionForm
 */

'use client';

import { useEffect, useState, useCallback } from 'react';
import { fetchHitlPage, HitlPageError } from '@/lib/api/hitl';
import type { HitlPageResponse, HitlPagePayload } from '@/lib/types/hitl';
import { DecisionForm } from '@/components/hitl/decision-form';
import { RecordsTimeline } from '@/components/hitl/records-timeline';
import { DeadlineCountdown } from '@/components/hitl/deadline-countdown';
import { BotScanPage } from '@/components/hitl/bot-scan-page';

interface DecisionPageClientProps {
  token: string;
}

type FetchState =
  | { kind: 'loading' }
  | { kind: 'error'; status: number; message: string }
  | { kind: 'data'; payload: HitlPageResponse };

export function DecisionPageClient({ token }: DecisionPageClientProps) {
  const [state, setState] = useState<FetchState>({ kind: 'loading' });
  const [isDeadlineExceeded, setIsDeadlineExceeded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    fetchHitlPage(token, { signal: controller.signal })
      .then((payload) => {
        if (!cancelled) {
          setState({ kind: 'data', payload });
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof HitlPageError) {
          setState({
            kind: 'error',
            status: err.status,
            message: mapErrorMessage(err.status, err.message),
          });
        } else if (err instanceof Error && err.name === 'AbortError') {
          // 静默取消
          return;
        } else {
          const message =
            err instanceof Error ? err.message : '加载决策页失败';
          setState({ kind: 'error', status: 0, message });
        }
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [token]);

  const handleTimeout = useCallback(() => {
    setIsDeadlineExceeded(true);
  }, []);

  if (state.kind === 'loading') {
    return (
      <main
        className="mx-auto max-w-3xl px-6 py-16 text-center"
        data-testid="loading-state"
      >
        <div className="inline-flex h-10 w-10 animate-spin rounded-full border-4 border-emerald-200 border-t-emerald-600" />
        <p className="mt-4 text-sm text-gray-600">加载决策页…</p>
      </main>
    );
  }

  if (state.kind === 'error') {
    return (
      <main
        className="mx-auto max-w-2xl px-6 py-16 text-center"
        data-testid="error-state"
      >
        <div className="rounded-md border border-red-200 bg-red-50 p-6">
          <h1 className="text-lg font-semibold text-red-900">
            无法加载决策页
          </h1>
          <p className="mt-3 text-sm text-red-700" data-testid="error-message">
            {state.message}
          </p>
          {state.status > 0 && (
            <p
              className="mt-2 text-xs text-red-500"
              data-testid="error-status"
            >
              状态码：{state.status}
            </p>
          )}
        </div>
      </main>
    );
  }

  // state.kind === 'data'
  if (state.payload.bot_scan) {
    return <BotScanPage />;
  }

  const data: HitlPagePayload = state.payload;

  return (
    <main className="mx-auto max-w-5xl px-4 py-8 md:px-6" data-testid="decision-layout">
      {/* Header */}
      <header className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900 md:text-2xl">
          HITL 审批决策
        </h1>
        {data.flow_title && (
          <p className="mt-1 text-sm text-gray-600" data-testid="flow-title">
            流程：{data.flow_title}
          </p>
        )}
        <p className="mt-1 text-sm text-gray-500">
          {data.phase === 'submit' ? '执行人提交阶段' : '审核人审批阶段'}
          {data.current_actor && (
            <>
              {' · '}当前操作人：
              <span className="font-medium text-gray-700">
                {data.current_actor.email}
              </span>
            </>
          )}
        </p>
      </header>

      {/* Layout: main content (form) + side (records + countdown) */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Main column */}
        <section className="lg:col-span-2">
          <div className="rounded-md border border-gray-200 bg-white p-6 shadow-sm">
            <h2 className="mb-4 text-base font-semibold text-gray-900">
              决策表单
            </h2>
            <DecisionForm
              token={data.token}
              jti={data.jti}
              formSchema={data.form_schema}
              phase={data.phase}
              disabled={isDeadlineExceeded}
            />
          </div>
        </section>

        {/* Side column */}
        <aside className="space-y-4">
          <div className="rounded-md border border-gray-200 bg-white p-4 shadow-sm">
            <h3 className="mb-2 text-sm font-semibold text-gray-900">
              倒计时
            </h3>
            <DeadlineCountdown
              deadlineAt={data.deadline_at}
              onTimeout={handleTimeout}
            />
          </div>
          <div className="rounded-md border border-gray-200 bg-white p-4 shadow-sm">
            <h3 className="mb-3 text-sm font-semibold text-gray-900">
              历史决策（{data.records.length} 条）
            </h3>
            <RecordsTimeline records={data.records} />
          </div>
        </aside>
      </div>

      <footer className="mt-10 text-center text-xs text-gray-400">
        由 agent-builder 系统自动发送，操作将记录到审计日志。
      </footer>
    </main>
  );
}

/** 状态码 → 友好中文错误消息映射。 */
function mapErrorMessage(status: number, fallback: string): string {
  switch (status) {
    case 400:
      return '链接格式错误，请确认邮件中的完整 URL。';
    case 401:
      return '链接签名无效或会话已过期，请重新点击邮件中的按钮。';
    case 404:
      return '决策节点不存在，可能流程已被删除。';
    case 410:
      return '链接已失效或决策已被提交。';
    default:
      return fallback || `加载失败（${status}）`;
  }
}
