/**
 * HITL DSL Builder
 *
 * 为 Phase 3 E2E spec 提供含 HITL 节点的 DSL JSON 预设。
 * 与 dsl-builder.ts (Phase 2) 并列：dsl-builder 仅含基础节点；hitl-builder 含 HITL 节点。
 *
 * 设计参考 Dify human_input_form schema：
 *   type=hitl + assignees (List[str]) + form_schema (JSON Schema Draft-7) + timeout_seconds + escalate_to
 *
 * 用途：
 * - hitl_email_delivery.spec.ts: buildHitlDsl() → 启动实例 → mailhog 收邮件
 * - hitl_token_login.spec.ts: 同上 + 提交决策
 * - hitl_safe_links_bot.spec.ts: 同上 + bot UA 探测
 * - hitl_token_invalidation.spec.ts: 同上 + 重提交断言
 * - hitl_tracking_page.spec.ts: 同上 + 申请人追踪
 *
 * Phase 4 多人审批链时新增 buildHitlSequenceDsl / buildHitlParallelDsl（本 plan 留接口）。
 */

import type { DslEdge, DslJson, DslNode, Position } from './dsl-builder';

/** HITL 节点的 form_schema（JSON Schema Draft-7） */
export interface HitlFormSchema {
  type: 'object';
  properties: Record<
    string,
    {
      type: 'string' | 'number' | 'boolean';
      title?: string;
      maxLength?: number;
      minLength?: number;
      enum?: string[];
      description?: string;
    }
  >;
  required?: string[];
  additionalProperties?: boolean;
}

/** buildHitlDsl 入参 */
export interface BuildHitlDslOptions {
  /** 流程名 */
  name?: string;
  /** 审批人邮箱列表（v1 单人模式只取 [0]） */
  approverEmails: string[];
  /** 申请人邮箱（默认不填，由 instance 启动时的 creator 注入） */
  applicantEmail?: string;
  /** 决策表单 schema（可选，默认极简） */
  formSchema?: HitlFormSchema;
  /** 超时秒数（默认 24h） */
  timeoutSeconds?: number;
  /** 升级接收人邮箱（v1 简化为 email 字符串，Phase 5 扩展） */
  escalateTo?: string;
  /** 节点标题（默认"审批"） */
  hitlNodeTitle?: string;
  /** 描述文本（form_schema.description） */
  description?: string;
}

/** 默认极简 form_schema */
const DEFAULT_FORM_SCHEMA: HitlFormSchema = {
  type: 'object',
  properties: {
    reason_detail: {
      type: 'string',
      title: '详细原因',
      maxLength: 500,
      description: '请补充说明',
    },
  },
  required: [],
  additionalProperties: false,
};

/**
 * 构建含 HITL 节点的 DSL（3 节点 Start → HITL → End）。
 *
 * 拓扑：
 *   start → hitl_1（审批）→ end
 *
 * HITL 节点 config 包含：
 *   - assignees: 审批人邮箱列表（v1 single 模式只取 [0]）
 *   - form_schema: JSON Schema Draft-7
 *   - timeout_seconds: 默认 86400 (24h)
 *   - escalate_to: 升级邮箱（可选）
 *   - description: 表单描述
 */
export function buildHitlDsl(opts: BuildHitlDslOptions): DslJson {
  const {
    name = 'HITL E2E 测试工作流',
    approverEmails,
    formSchema = DEFAULT_FORM_SCHEMA,
    timeoutSeconds = 86_400,
    escalateTo,
    hitlNodeTitle = '审批节点',
    description = '请审批此申请',
  } = opts;

  if (approverEmails.length === 0) {
    throw new Error('buildHitlDsl: approverEmails 至少需要一个邮箱');
  }

  const hitlConfig: Record<string, unknown> = {
    assignees: approverEmails,
    form_schema: formSchema,
    timeout_seconds: timeoutSeconds,
    description,
  };

  if (escalateTo) {
    hitlConfig.escalate_to = escalateTo;
  }

  const positions: Record<string, Position> = {
    start: { x: 80, y: 200 },
    hitl_1: { x: 320, y: 200 },
    end: { x: 560, y: 200 },
  };

  const nodes: DslNode[] = [
    {
      id: 'start',
      type: 'start',
      label: '开始',
      position: positions.start,
      config: {},
    },
    {
      id: 'hitl_1',
      type: 'hitl',
      label: hitlNodeTitle,
      position: positions.hitl_1,
      config: hitlConfig,
    },
    {
      id: 'end',
      type: 'end',
      label: '结束',
      position: positions.end,
      config: {},
    },
  ];

  const edges: DslEdge[] = [
    { id: 'e1', source: 'start', target: 'hitl_1' },
    { id: 'e2', source: 'hitl_1', target: 'end' },
  ];

  return {
    version: '1.0',
    name,
    state_schema: {
      input: 'str',
      applicant_email: 'str',
      output: 'str',
    },
    nodes,
    edges,
  };
}

/**
 * 构建串联 2 个 HITL 节点的 DSL（Phase 4 多人审批链预留）。
 *
 * 拓扑：
 *   start → hitl_1（提交人审核）→ hitl_2（审批人审核）→ end
 *
 * **本 plan 仅保留接口，Phase 4 实现 HITL-04 顺序会签时使用。**
 */
export function buildHitlSequenceDsl(opts: {
  name?: string;
  submitterEmail: string;
  approverEmail: string;
  formSchema?: HitlFormSchema;
}): DslJson {
  const {
    name = 'HITL 顺序会签 E2E 测试工作流',
    submitterEmail,
    approverEmail,
    formSchema = DEFAULT_FORM_SCHEMA,
  } = opts;

  const nodes: DslNode[] = [
    {
      id: 'start',
      type: 'start',
      label: '开始',
      position: { x: 80, y: 200 },
      config: {},
    },
    {
      id: 'hitl_1',
      type: 'hitl',
      label: '提交人审核',
      position: { x: 320, y: 200 },
      config: {
        assignees: [submitterEmail],
        form_schema: formSchema,
        timeout_seconds: 86_400,
        description: '请提交申请',
      },
    },
    {
      id: 'hitl_2',
      type: 'hitl',
      label: '审批人审核',
      position: { x: 560, y: 200 },
      config: {
        assignees: [approverEmail],
        form_schema: formSchema,
        timeout_seconds: 86_400,
        description: '请审核此申请',
      },
    },
    {
      id: 'end',
      type: 'end',
      label: '结束',
      position: { x: 800, y: 200 },
      config: {},
    },
  ];

  const edges: DslEdge[] = [
    { id: 'e1', source: 'start', target: 'hitl_1' },
    { id: 'e2', source: 'hitl_1', target: 'hitl_2' },
    { id: 'e3', source: 'hitl_2', target: 'end' },
  ];

  return {
    version: '1.0',
    name,
    state_schema: {
      input: 'str',
      applicant_email: 'str',
      output: 'str',
    },
    nodes,
    edges,
  };
}

/**
 * 解析后的邮件 deeplink（mailhog 提取）。
 */
export interface HitlDeeplink {
  /** action 字符串（submit / approve / return / reject） */
  action: string;
  /** 完整 URL（含 token） */
  url: string;
  /** 从 URL 提取的 token（JWT 字符串） */
  token: string;
  /** JWT payload 中的 jti */
  jti: string;
}

/**
 * 从邮件 HTML body 解析所有 HITL deeplink。
 *
 * 邮件模板（03-04 hitl_decision.html）含 3 个 `<a href>` button：
 *   - action 在 button 文案 ("通过" / "退回" / "拒绝" 或 "提交" / "退回" / "拒绝")
 *   - URL 在 href 中：{PUBLIC_BASE_URL}/hitl/page/<JWT>
 *   - JWT payload 含 jti / action 等字段
 *
 * **本 helper 仅解析 URL + token；jti 解析由 spec 内通过 base64 解码 JWT payload 完成。**
 */
export function parseHitlDeeplinksFromHtml(html: string): HitlDeeplink[] {
  const deeplinks: HitlDeeplink[] = [];
  const seen = new Set<string>();

  // 匹配 href + 包含 /hitl/page/ 的链接
  const pattern = /href=["']([^"']*\/hitl\/page\/([^"'?#]+))[^"']*?["'][^>]*>([^<]*)</gi;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(html)) !== null) {
    const url = match[1];
    const token = match[2];
    const linkText = (match[3] ?? '').trim();

    // 同一 token 只记一次
    if (seen.has(token)) continue;
    seen.add(token);

    // action 推断（按文案 + URL fragment）
    const action = inferActionFromLinkText(linkText);

    // jti 从 JWT 解码（payload 段 base64url decode）
    const jti = extractJtiFromJwt(token);

    deeplinks.push({ action, url, token, jti });
  }

  return deeplinks;
}

/** 从 button 文案推断 action（容错） */
function inferActionFromLinkText(text: string): string {
  const lower = text.toLowerCase();
  if (lower.includes('通过') || lower.includes('approve')) return 'approve';
  if (lower.includes('提交') || lower.includes('submit')) return 'submit';
  if (lower.includes('退回') || lower.includes('return')) return 'return';
  if (lower.includes('拒绝') || lower.includes('reject')) return 'reject';
  return 'unknown';
}

/** 从 JWT token 解码 jti（不校验签名，仅 E2E 断言用） */
function extractJtiFromJwt(token: string): string {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return '';
    const payloadBase64 = parts[1];
    // base64url → base64
    const base64 = payloadBase64.replace(/-/g, '+').replace(/_/g, '/');
    // 补 padding
    const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4);
    const payloadJson = Buffer.from(padded, 'base64').toString('utf-8');
    const payload = JSON.parse(payloadJson) as { jti?: string };
    return payload.jti ?? '';
  } catch {
    return '';
  }
}
