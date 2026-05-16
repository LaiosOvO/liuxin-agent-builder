/**
 * MailHog 邮件捕获客户端。
 *
 * 在 E2E 测试中替代真实 SMTP，可重复捕获邮件并解析链接。
 * MailHog API: http://localhost:8025/api/v2/messages
 *
 * 用途（Phase 1）：
 * - 捕获邮箱验证邮件 + 邀请邮件
 * - 解析邀请链接 token（完成注册流程）
 *
 * Phase 3 扩展：Outlook Safe Links UA 模拟（见 safe-links-future-proof.spec.ts）
 */

const MAILHOG_API_URL = process.env.MAILHOG_API_URL ?? 'http://localhost:8025';

/** MailHog 邮件收件人格式 */
interface MailHogRecipient {
  Relays: null | string[];
  Mailbox: string;
  Domain: string;
  Params: string;
}

/** MailHog 邮件内容 */
interface MailHogContent {
  Headers: Record<string, string[]>;
  Body: string;
  Size: number;
  MIME: null | Record<string, unknown>;
}

/** MailHog 单封邮件结构 */
export interface MailHogMessage {
  ID: string;
  From: MailHogRecipient;
  To: MailHogRecipient[];
  Content: MailHogContent;
  Created: string;
  MIME: null | Record<string, unknown>;
  Raw: {
    From: string;
    To: string[];
    Data: string;
    Helo: string;
  };
}

/** MailHog 列表响应 */
interface MailHogListResponse {
  total: number;
  count: number;
  start: number;
  items: MailHogMessage[];
}

/**
 * 轮询 MailHog，直到找到发给指定邮箱的最新邮件。
 *
 * @param toEmail  收件人邮箱地址
 * @param timeout  最大等待毫秒数（默认 10000）
 * @returns        找到的邮件
 * @throws         超时未找到时抛出 Error
 */
export async function getLatestEmail(
  toEmail: string,
  timeout = 10_000,
): Promise<MailHogMessage> {
  const start = Date.now();

  while (Date.now() - start < timeout) {
    const r = await fetch(`${MAILHOG_API_URL}/api/v2/messages?limit=50`);

    if (!r.ok) {
      throw new Error(`MailHog API 返回 ${r.status}，请确认 MailHog 已启动`);
    }

    const data: MailHogListResponse = await r.json();
    const found = data.items.find((m) =>
      m.To.some(
        (t) => `${t.Mailbox}@${t.Domain}`.toLowerCase() === toEmail.toLowerCase(),
      ),
    );

    if (found) return found;

    await new Promise((resolve) => setTimeout(resolve, 300));
  }

  throw new Error(`在 ${timeout}ms 内未找到发给 ${toEmail} 的邮件`);
}

/**
 * 从邮件 HTML body 中提取包含指定字符串的第一个 href 链接。
 *
 * @param email        MailHog 邮件对象
 * @param hrefContains 链接中必须包含的子字符串（如 '/invite?token='）
 * @returns            完整的链接 URL
 * @throws             未找到时抛出 Error
 */
export function extractLink(email: MailHogMessage, hrefContains: string): string {
  const body = email.Content.Body;

  // 尝试匹配 href="..."
  const patterns = [
    new RegExp(`href="([^"]*${escapeRegex(hrefContains)}[^"]*)"`, 'i'),
    new RegExp(`href='([^']*${escapeRegex(hrefContains)}[^']*)'`, 'i'),
  ];

  for (const pattern of patterns) {
    const m = body.match(pattern);
    if (m?.[1]) return m[1];
  }

  // 纯文本链接（fallback）
  const textPattern = new RegExp(
    `(https?://[^\\s<>"']*${escapeRegex(hrefContains)}[^\\s<>"']*)`,
    'i',
  );
  const tm = body.match(textPattern);
  if (tm?.[1]) return tm[1];

  throw new Error(
    `在邮件中未找到包含 "${hrefContains}" 的链接\n邮件 Body 前 500 字符: ${body.slice(0, 500)}`,
  );
}

/**
 * 清空 MailHog 所有邮件（每个 spec 运行前调用以保证隔离）。
 */
export async function purgeAllEmails(): Promise<void> {
  await fetch(`${MAILHOG_API_URL}/api/v1/messages`, {
    method: 'DELETE',
  });
}

/**
 * 获取所有邮件列表。
 */
export async function getAllEmails(): Promise<MailHogMessage[]> {
  const r = await fetch(`${MAILHOG_API_URL}/api/v2/messages?limit=100`);
  if (!r.ok) return [];
  const data: MailHogListResponse = await r.json();
  return data.items;
}

/**
 * 等待 MailHog 接收到发给某邮箱的邮件，返回邮件中匹配的链接。
 * 组合函数：getLatestEmail + extractLink
 */
export async function waitForEmailAndExtractLink(
  toEmail: string,
  hrefContains: string,
  timeout = 15_000,
): Promise<string> {
  const email = await getLatestEmail(toEmail, timeout);
  return extractLink(email, hrefContains);
}

/** Phase 3 HITL 邮件解析后的结构 */
export interface HitlEmailParsed {
  /** 收件人邮箱 */
  to: string;
  /** 发件人邮箱 */
  from: string;
  /** subject 头 */
  subject: string;
  /** 完整 HTML body */
  html: string;
  /** 纯文本 fallback（如有） */
  text: string;
  /** 是否催办邮件（subject 含 [催办] 或 [升级] 前缀） */
  isReminder: boolean;
  /** 是否升级邮件（subject 含 [升级] 前缀） */
  isEscalation: boolean;
  /** 提取的 deeplink 列表 */
  deeplinks: Array<{
    /** action 名称（推断） */
    action: string;
    /** 完整 URL */
    url: string;
    /** JWT token 字符串 */
    token: string;
    /** JWT payload 中的 jti */
    jti: string;
  }>;
}

/**
 * 轮询 MailHog 直到找到发给 recipient 的最新 HITL 邮件，并解析 button + token。
 *
 * @param recipient 收件人邮箱
 * @param timeout   最大等待毫秒数（默认 15000）
 * @returns         结构化解析后的 HITL 邮件
 *
 * **使用约定**：
 * - 调用方应先 purgeAllEmails() 保证测试隔离
 * - 邮件 HTML 必须包含至少 1 个 `/hitl/page/<token>` 链接
 */
export async function getLatestHitlEmail(
  recipient: string,
  timeout = 15_000,
): Promise<HitlEmailParsed> {
  const email = await getLatestEmail(recipient, timeout);

  // 解析头部
  const subject = decodeMimeHeader(email.Content.Headers['Subject']?.[0] ?? '');
  const from = email.Content.Headers['From']?.[0] ?? '';
  const to = email.Content.Headers['To']?.[0] ?? '';

  // 获取完整 body
  const fullBody = email.Content.Body;

  // 提取 HTML 与 text part（MIME multipart 简单解析）
  const { html, text } = splitMimeBody(fullBody);

  // 解析 deeplinks
  const deeplinks = parseDeeplinks(html || fullBody);

  return {
    to,
    from,
    subject,
    html: html || fullBody,
    text,
    isReminder: subject.includes('[催办]'),
    isEscalation: subject.includes('[升级]'),
    deeplinks,
  };
}

/**
 * 从 HITL 邮件 HTML 中提取所有 token。
 *
 * 与 getLatestHitlEmail 互补：当只需要 token 列表（不需完整邮件信息）时使用。
 */
export function extractTokensFromEmail(html: string): Array<{
  action: string;
  jti: string;
  token: string;
}> {
  return parseDeeplinks(html).map(({ action, jti, token }) => ({ action, jti, token }));
}

/**
 * 解析邮件 HTML 中的 HITL deeplink button。
 *
 * 匹配两种格式：
 * 1. `<a href="...hitl/page/TOKEN...">通过</a>`（HTML button）
 * 2. `https://.../hitl/page/TOKEN`（plain text URL）
 */
function parseDeeplinks(body: string): Array<{
  action: string;
  url: string;
  token: string;
  jti: string;
}> {
  const result: Array<{
    action: string;
    url: string;
    token: string;
    jti: string;
  }> = [];
  const seenTokens = new Set<string>();

  // 1. HTML `<a href="...">label</a>` 模式
  const htmlPattern =
    /<a\s+[^>]*href=["']([^"']*\/hitl\/page\/([A-Za-z0-9._-]+))[^"']*["'][^>]*>([^<]*)<\/a>/gi;
  let m: RegExpExecArray | null;

  while ((m = htmlPattern.exec(body)) !== null) {
    const url = m[1];
    const token = m[2];
    const label = (m[3] ?? '').trim();
    if (seenTokens.has(token)) continue;
    seenTokens.add(token);
    result.push({
      action: inferAction(label, url),
      url,
      token,
      jti: extractJtiFromJwt(token),
    });
  }

  // 2. plain text URL（fallback —— 邮件 plain text 没有 HTML 包装）
  const textPattern = /(https?:\/\/[^\s<>"']*\/hitl\/page\/([A-Za-z0-9._-]+))/gi;
  while ((m = textPattern.exec(body)) !== null) {
    const url = m[1];
    const token = m[2];
    if (seenTokens.has(token)) continue;
    seenTokens.add(token);
    result.push({
      action: inferAction('', url),
      url,
      token,
      jti: extractJtiFromJwt(token),
    });
  }

  return result;
}

/** 按 button 文案 + URL 中的查询参数推断 action */
function inferAction(label: string, url: string): string {
  const lower = label.toLowerCase();
  if (lower.includes('通过') || lower.includes('approve')) return 'approve';
  if (lower.includes('提交') || lower.includes('submit')) return 'submit';
  if (lower.includes('退回') || lower.includes('return')) return 'return';
  if (lower.includes('拒绝') || lower.includes('reject')) return 'reject';

  // 从 URL 查询参数推断（如 ?action=submit）
  const urlMatch = url.match(/[?&]action=(\w+)/);
  if (urlMatch) return urlMatch[1];

  return 'unknown';
}

/** 从 JWT 提取 jti（不校验签名） */
function extractJtiFromJwt(token: string): string {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return '';
    const payloadBase64 = parts[1];
    const base64 = payloadBase64.replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4);
    const payloadJson = Buffer.from(padded, 'base64').toString('utf-8');
    const payload = JSON.parse(payloadJson) as { jti?: string };
    return payload.jti ?? '';
  } catch {
    return '';
  }
}

/** Decode quoted-printable / =?UTF-8?B?...?= 编码的 MIME header */
function decodeMimeHeader(raw: string): string {
  // RFC 2047 encoded-word: =?charset?B|Q?encoded-text?=
  return raw.replace(
    /=\?([^?]+)\?([BbQq])\?([^?]*)\?=/g,
    (_, _charset: string, enc: string, text: string) => {
      try {
        if (enc.toUpperCase() === 'B') {
          return Buffer.from(text, 'base64').toString('utf-8');
        }
        // Q encoding（quoted-printable）
        return text.replace(/_/g, ' ').replace(/=([0-9A-F]{2})/g, (_, hex: string) =>
          String.fromCharCode(parseInt(hex, 16)),
        );
      } catch {
        return text;
      }
    },
  );
}

/** Split multipart MIME body into HTML and text parts */
function splitMimeBody(body: string): { html: string; text: string } {
  // 单一格式：body 不含 boundary → 直接判断 HTML/text
  if (!body.includes('Content-Type:') && !body.includes('boundary=')) {
    if (body.trimStart().startsWith('<') || body.includes('<html')) {
      return { html: body, text: '' };
    }
    return { html: '', text: body };
  }

  // multipart 简单切分
  let html = '';
  let text = '';

  // 找 text/html part
  const htmlMatch = body.match(
    /Content-Type:\s*text\/html[^\n]*\n(?:[^\n]*\n)*?\n([\s\S]*?)(?:\n--[a-zA-Z0-9_-]+|\n\.|\Z)/i,
  );
  if (htmlMatch) {
    html = decodeMimeBody(htmlMatch[1]);
  }

  // 找 text/plain part
  const textMatch = body.match(
    /Content-Type:\s*text\/plain[^\n]*\n(?:[^\n]*\n)*?\n([\s\S]*?)(?:\n--[a-zA-Z0-9_-]+|\n\.|\Z)/i,
  );
  if (textMatch) {
    text = decodeMimeBody(textMatch[1]);
  }

  // fallback：什么都没匹配，把整 body 当 html
  if (!html && !text) {
    html = body;
  }

  return { html, text };
}

/** 解码 quoted-printable / base64 编码的 MIME body */
function decodeMimeBody(raw: string): string {
  // quoted-printable: =XX → byte, =\n → 续行
  if (raw.includes('=')) {
    try {
      const decoded = raw
        .replace(/=\n/g, '')
        .replace(/=\r\n/g, '')
        .replace(/=([0-9A-F]{2})/gi, (_, hex: string) =>
          String.fromCharCode(parseInt(hex, 16)),
        );
      // 检查是否为 utf-8 字节序列
      return Buffer.from(decoded, 'binary').toString('utf-8');
    } catch {
      return raw;
    }
  }
  return raw;
}

/** 转义正则特殊字符 */
function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
