/**
 * E2E spec: HMAC_SECRET 启动校验
 *
 * 覆盖 ROADMAP.md Phase 1 success criterion #5:
 *   "HMAC_SECRET 长度 < 32 字节时服务启动失败并打印明确错误信息"
 *
 * 实现细节: 见 backend/app/agent_builder/security/startup_checks.py (Plan 01-03)
 *
 * 前置: docker + ability to spawn/kill api containers
 * 触发: E2E_FULL_STACK=1 (因为需要重启容器, 比 RUN_E2E 更严格)
 */
import { test, expect } from '@playwright/test';
import { execSync } from 'node:child_process';

const FULL = !!process.env.E2E_FULL_STACK;

interface DockerCheckResult {
  exitCode: number;
  stderr: string;
  stdout: string;
}

/**
 * 用临时 .env 起 api 容器, 等待退出并捕获 exit code 与 stderr.
 */
function runApiWithHmac(hmacValue: string, timeoutSec = 10): DockerCheckResult {
  try {
    const output = execSync(
      `HMAC_SECRET='${hmacValue}' docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm api 2>&1`,
      { timeout: timeoutSec * 1000, encoding: 'utf-8' },
    );
    return { exitCode: 0, stderr: '', stdout: output };
  } catch (err) {
    const error = err as { status?: number; stdout?: Buffer | string; stderr?: Buffer | string };
    return {
      exitCode: error.status ?? -1,
      stderr: error.stderr?.toString() ?? '',
      stdout: error.stdout?.toString() ?? '',
    };
  }
}

test.describe('HMAC_SECRET 启动校验 (ROADMAP #5)', () => {
  test.skip(() => !FULL, '需要 E2E_FULL_STACK=1 (启停容器)');

  test('空 HMAC_SECRET → 服务退出 + 错误信息含 "HMAC_SECRET"', async () => {
    const result = runApiWithHmac('', 10);
    expect(result.exitCode).not.toBe(0);
    const allOutput = result.stderr + result.stdout;
    expect(allOutput).toMatch(/HMAC_SECRET/i);
    expect(allOutput).toMatch(/32/);
  });

  test('短 HMAC_SECRET (16 chars) → 服务退出 + 错误信息含长度要求', async () => {
    const result = runApiWithHmac('only_16_chars_xx', 10);
    expect(result.exitCode).not.toBe(0);
    const allOutput = result.stderr + result.stdout;
    expect(allOutput).toMatch(/HMAC_SECRET/i);
    expect(allOutput).toMatch(/32|长度/);
  });

  test('合法 HMAC_SECRET (32+ chars) → 服务正常启动', async () => {
    const validKey = 'this_is_a_32_byte_strong_hmac_key_!';
    expect(validKey.length).toBeGreaterThanOrEqual(32);
    // 此处仅检查启动不立即失败; 完整 healthcheck 见 docker_compose_health.spec
    // 启动后立即停止容器避免长时间占用
    const result = runApiWithHmac(validKey, 5);
    // exit code 124 = timeout (正常运行被强杀), 表明启动通过了校验
    expect([0, 124, 137]).toContain(result.exitCode);
    const allOutput = result.stderr + result.stdout;
    // 不应该有 HMAC 拒绝启动的错误
    expect(allOutput).not.toMatch(/HMAC_SECRET.*太短|HMAC_SECRET.*invalid/i);
  });
});
