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

/** 转义正则特殊字符 */
function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
