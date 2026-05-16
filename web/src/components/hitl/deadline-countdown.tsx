/**
 * HITL 截止时间倒计时（Plan 03-07）。
 *
 * 设计要点：
 * - 客户端 setInterval(1000) 更新（不轮询后端 — CONTEXT §UI/UX）
 * - 显示 "剩余 1 天 3 小时 22 分钟" / "已超时" 红色
 * - 超时后通过 onTimeout callback 通知父组件 disable buttons
 * - SSR 安全：useEffect 中启动 interval，cleanup 中清理
 */

'use client';

import { useEffect, useMemo, useState } from 'react';

interface DeadlineCountdownProps {
  /** ISO 8601 截止时间（后端 payload.deadline_at） */
  deadlineAt: string | null;
  /** 超时回调（父组件用于 disable 按钮） */
  onTimeout?: () => void;
}

interface CountdownBreakdown {
  isOverdue: boolean;
  days: number;
  hours: number;
  minutes: number;
  seconds: number;
}

/** 计算 deadline 与当前时刻的差值（精确到秒）。 */
function computeBreakdown(
  deadlineMs: number,
  nowMs: number,
): CountdownBreakdown {
  const diffMs = deadlineMs - nowMs;
  if (diffMs <= 0) {
    return {
      isOverdue: true,
      days: 0,
      hours: 0,
      minutes: 0,
      seconds: 0,
    };
  }
  const totalSec = Math.floor(diffMs / 1000);
  const days = Math.floor(totalSec / 86400);
  const hours = Math.floor((totalSec % 86400) / 3600);
  const minutes = Math.floor((totalSec % 3600) / 60);
  const seconds = totalSec % 60;
  return { isOverdue: false, days, hours, minutes, seconds };
}

function formatBreakdown(b: CountdownBreakdown): string {
  if (b.isOverdue) return '已超时';
  const parts: string[] = [];
  if (b.days > 0) parts.push(`${b.days} 天`);
  if (b.hours > 0 || b.days > 0) parts.push(`${b.hours} 小时`);
  parts.push(`${b.minutes} 分钟`);
  // 仅在不足 1 小时时显示秒数（避免长串闪烁）
  if (b.days === 0 && b.hours === 0) {
    parts.push(`${b.seconds} 秒`);
  }
  return `剩余 ${parts.join(' ')}`;
}

export function DeadlineCountdown({
  deadlineAt,
  onTimeout,
}: DeadlineCountdownProps) {
  const deadlineMs = useMemo(() => {
    if (!deadlineAt) return null;
    const t = new Date(deadlineAt).getTime();
    return Number.isNaN(t) ? null : t;
  }, [deadlineAt]);

  // 初始 now 用 deadlineMs 自身（SSR 一致，避免 hydration mismatch）
  // 客户端 useEffect 立即纠正为真实 now
  const [nowMs, setNowMs] = useState<number>(() => {
    if (typeof window === 'undefined' && deadlineMs !== null) {
      return deadlineMs;
    }
    return Date.now();
  });

  useEffect(() => {
    if (deadlineMs === null) return;
    setNowMs(Date.now());
    const id = setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => clearInterval(id);
  }, [deadlineMs]);

  // 超时回调：useEffect 监听 isOverdue 变化
  const breakdown = useMemo(() => {
    if (deadlineMs === null) {
      return null;
    }
    return computeBreakdown(deadlineMs, nowMs);
  }, [deadlineMs, nowMs]);

  useEffect(() => {
    if (breakdown?.isOverdue && onTimeout) {
      onTimeout();
    }
  }, [breakdown?.isOverdue, onTimeout]);

  if (deadlineAt === null || deadlineMs === null) {
    return (
      <div
        className="text-sm text-gray-500"
        data-testid="deadline-countdown-empty"
      >
        无截止时间
      </div>
    );
  }

  if (breakdown === null) {
    return null;
  }

  const text = formatBreakdown(breakdown);
  const className = breakdown.isOverdue
    ? 'text-red-600 font-semibold'
    : 'text-gray-700';

  return (
    <div
      className={`text-sm ${className}`}
      data-testid="deadline-countdown"
      data-overdue={breakdown.isOverdue ? 'true' : 'false'}
    >
      <span className="text-xs text-gray-500">截止时间：</span>
      <span className="ml-1" data-testid="countdown-text">
        {text}
      </span>
    </div>
  );
}
