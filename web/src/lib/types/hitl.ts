/**
 * HITL 决策页前端类型定义（Plan 03-07）。
 *
 * 后端契约见：
 * - GET /hitl/page/<token>（Accept: application/json）→ HitlPageResponse
 * - POST /hitl/action/<token>（Accept: application/json + Form/JSON body）→ HitlSubmitResponse
 *
 * Phase 3 P0 简化：单人审批 + 单 phase 切换（submit | review）。
 */

import type { RJSFSchema } from '@rjsf/utils';

/** 历史决策记录（脱敏 IP/UA — 决策页用户视角不可见敏感字段）。 */
export interface HitlRecord {
  /** 操作人邮箱（可显示） */
  actor_email: string;
  /** 操作类型：submit / approve / return / reject / escalate */
  action: string;
  /** 备注 / 理由（可选） */
  reason?: string;
  /** ISO 8601 时间戳 */
  ts: string;
}

/** 当前操作人信息。 */
export interface HitlActor {
  id: string;
  email: string;
  role: 'executor' | 'reviewer';
}

/** GET /hitl/page bot 扫描模式响应。 */
export interface HitlBotScanResponse {
  bot_scan: true;
  message: string;
}

/** GET /hitl/page 正常模式响应（form_schema + records + deadline）。 */
export interface HitlPagePayload {
  bot_scan: false;
  /** JWT token 原文（提交时回传） */
  token: string;
  /** 一次性 ID — 提交时校验 */
  jti: string;
  /** 默认 action（按 JWT.allowed_actions[0] 取） */
  action: string;
  /** allowed_actions 数组（决定按钮组渲染） */
  allowed_actions: string[];
  /** 关联节点状态 ID */
  node_state_id: string;
  /** RJSF schema —— 动态表单字段定义（JSON Schema Draft-07） */
  form_schema: RJSFSchema;
  /** 历史决策记录 */
  records: HitlRecord[];
  /** ISO 8601 截止时间 */
  deadline_at: string | null;
  /** 当前操作人（可选 — 未必所有 phase 都有） */
  current_actor: HitlActor | null;
  /** 当前阶段：'submit'（执行人） | 'review'（审核人） */
  phase: 'submit' | 'review';
  /** 流程标题（用于页面 title） */
  flow_title?: string | null;
}

/** GET /hitl/page 错误响应（JSON 模式）。 */
export interface HitlErrorResponse {
  error: string;
  status_code: number;
  /** 422 时携带的字段级错误 */
  errors?: string[];
}

/** GET 响应联合类型 —— 由调用方根据 bot_scan 字段判别。 */
export type HitlPageResponse = HitlPagePayload | HitlBotScanResponse;

/** POST /hitl/action 提交体（FormData 形式发到后端）。 */
export interface HitlSubmitBody {
  action: string;
  reason: string;
  form_data: Record<string, unknown>;
}

/** POST /hitl/action 成功响应。 */
export interface HitlSubmitSuccess {
  ok: true;
  action: string;
  instance_id: string;
  new_node_status: string;
}

/** POST /hitl/action 失败响应（包含 422 表单校验错误）。 */
export interface HitlSubmitFailure {
  ok: false;
  status_code: number;
  error: string;
  /** 422 时携带 */
  errors?: string[];
}

/** 提交结果联合类型 —— 调用方按 ok 字段判别。 */
export type HitlSubmitResult = HitlSubmitSuccess | HitlSubmitFailure;

/** 按钮 phase 配置 —— 决定 3 按钮组合与样式。 */
export interface ActionButtonConfig {
  /** 后端 action 标识 */
  id: string;
  /** 按钮文字（中文） */
  label: string;
  /** Tailwind 类（背景色 + hover） */
  color: string;
}
