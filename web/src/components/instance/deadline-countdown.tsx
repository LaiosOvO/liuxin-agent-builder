'use client';

/**
 * DeadlineCountdown — 显示距离截止时间的倒计时
 *
 * - 每秒前端 setInterval 刷新（不轮询后端，符合 CONTEXT §决策页 UI/UX 倒计时方案）
 * - 超时显示红色 "已超时 Xh Ym"
 * - 未超时显示黄/绿色 "剩余 Xh Ym"（<1h 红色，<6h 黄色，≥6h 绿色）
 */

import { useEffect, useState } from 'react';

interface DeadlineCountdownProps {
  /** 截止时间（ISO8601）；null 时返回空 */
  deadlineAt: string | null;
  /** 可选 className 注入 */
  className?: string;
}

interface CountdownState {
  text: string;
  /** 超时标志 */
  overdue: boolean;
  /** 颜色级别：urgent (<1h) | warning (<6h) | normal */
  level: 'urgent' | 'warning' | 'normal';
}

function computeCountdown(deadlineAt: string): CountdownState {
  const now = Date.now();
  const deadline = new Date(deadlineAt).getTime();
  const diffMs = deadline - now;

  if (diffMs <= 0) {
    const overdueMs = Math.abs(diffMs);
    const h = Math.floor(overdueMs / 3_600_000);
    const m = Math.floor((overdueMs % 3_600_000) / 60_000);
    return { text: `已超时 ${h}h ${m}m`, overdue: true, level: 'urgent' };
  }

  const h = Math.floor(diffMs / 3_600_000);
  const m = Math.floor((diffMs % 3_600_000) / 60_000);
  const s = Math.floor((diffMs % 60_000) / 1_000);

  let level: 'urgent' | 'warning' | 'normal' = 'normal';
  if (h < 1) level = 'urgent';
  else if (h < 6) level = 'warning';

  const text = h > 0 ? `剩余 ${h}h ${m}m` : `剩余 ${m}m ${s}s`;
  return { text, overdue: false, level };
}

const LEVEL_CLASSNAMES: Record<CountdownState['level'], string> = {
  urgent: 'text-red-600 bg-red-50 border-red-200',
  warning: 'text-amber-700 bg-amber-50 border-amber-200',
  normal: 'text-green-700 bg-green-50 border-green-200',
};

export function DeadlineCountdown({ deadlineAt, className = '' }: DeadlineCountdownProps) {
  const [state, setState] = useState<CountdownState | null>(() =>
    deadlineAt ? computeCountdown(deadlineAt) : null,
  );

  useEffect(() => {
    if (!deadlineAt) {
      setState(null);
      return;
    }
    setState(computeCountdown(deadlineAt));
    const timer = window.setInterval(() => {
      setState(computeCountdown(deadlineAt));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [deadlineAt]);

  if (!deadlineAt || !state) return null;

  return (
    <span
      data-testid="deadline-countdown"
      data-overdue={state.overdue ? 'true' : 'false'}
      data-level={state.level}
      className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs font-medium ${LEVEL_CLASSNAMES[state.level]} ${className}`.trim()}
    >
      <span aria-hidden="true">⏱</span>
      <span>{state.text}</span>
    </span>
  );
}
