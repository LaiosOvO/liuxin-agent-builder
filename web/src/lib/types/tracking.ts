/**
 * HITL-07 申请人追踪页类型定义
 *
 * 与后端 schemas/tracking.py Pydantic 模型对齐：
 *  - records ip/ua: 申请人视角为 null（service 层脱敏）
 *  - current_node: 终态实例时为 null
 */

import type { InstanceStatus } from '@/lib/types/instance';

/** 单条审批决策记录（service 层已脱敏） */
export interface TrackingRecord {
  actor_email: string;
  actor_name: string | null;
  action: string;
  reason: string;
  ts: string;
  /** 仅 admin 可见；申请人视角为 null */
  ip: string | null;
  /** 仅 admin 可见；申请人视角为 null */
  ua: string | null;
}

/** 实例申请人摘要 */
export interface TrackingApplicant {
  id: string;
  name: string | null;
}

/** 当前节点等待的 actor */
export interface TrackingCurrentActor {
  email: string | null;
  name: string | null;
}

/** 当前正在等待的节点（节点可视化要求） */
export interface TrackingCurrentNode {
  id: string;
  title: string | null;
  status: string;
  node_type: string;
  actor: TrackingCurrentActor | null;
  deadline_at: string | null;
  started_at: string | null;
}

/** 申请人追踪页响应 */
export interface TrackingResponse {
  instance_id: string;
  status: InstanceStatus;
  workflow_id: string;
  applicant: TrackingApplicant;
  current_node: TrackingCurrentNode | null;
  records: TrackingRecord[];
  created_at: string;
  completed_at: string | null;
}

/** HITL 节点状态徽章配置 — 节点可视化（user feedback 2026-05-17） */
export const HITL_NODE_STATUS_CONFIG: Record<
  string,
  { label: string; icon: string; className: string }
> = {
  pending: { label: '等待中', icon: '○', className: 'bg-gray-100 text-gray-600' },
  waiting_human: { label: '等待提交', icon: '⏳', className: 'bg-amber-100 text-amber-700' },
  in_review: { label: '审核中', icon: '👀', className: 'bg-blue-100 text-blue-700' },
  done: { label: '已通过', icon: '✓', className: 'bg-green-100 text-green-700' },
  rejected: { label: '已拒绝', icon: '✗', className: 'bg-red-100 text-red-700' },
  returned: { label: '已退回', icon: '↺', className: 'bg-orange-100 text-orange-700' },
  running: { label: '运行中', icon: '⟳', className: 'bg-blue-100 text-blue-700' },
  completed: { label: '已完成', icon: '✓', className: 'bg-green-100 text-green-700' },
  failed: { label: '失败', icon: '✗', className: 'bg-red-100 text-red-700' },
};

/** 决策 action 标签 */
export const RECORD_ACTION_LABELS: Record<string, { label: string; className: string }> = {
  submit: { label: '提交', className: 'bg-blue-50 text-blue-700' },
  approve: { label: '通过', className: 'bg-green-50 text-green-700' },
  reject: { label: '拒绝', className: 'bg-red-50 text-red-700' },
  return: { label: '退回', className: 'bg-orange-50 text-orange-700' },
  escalate: { label: '升级', className: 'bg-purple-50 text-purple-700' },
};
