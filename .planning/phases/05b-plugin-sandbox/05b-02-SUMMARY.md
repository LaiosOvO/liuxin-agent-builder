# Plan 05b-02 SUMMARY: SandboxRunner Protocol + PosixResourceSandbox

**Status**: ✅ Complete
**Date**: 2026-05-18
**Phase**: 5.B (Plugin 沙箱 + Daemon 通信)
**Position**: Wave 2 (parallel with 05b-03)
**Requirements**: PLUG-FW-09

---

## Tasks

| Task | Status | Commit |
|------|--------|--------|
| Task 0: Dify resource runner reading doc | ✅ | `a7552ad` |
| Task 1: PluginError extensions (SandboxLimitExceeded + NetworkBlockedError placeholders) | ✅ | `814618e` |
| Task 2: SandboxRunner Protocol + PosixResourceSandbox | ✅ | `7beba52` |
| Task 3: pytest markers (linux_only/sandbox_integration/cgroups_v2) | ✅ | `6b6ba35` |
| Task 4: SandboxRunner Protocol 10 tests (1 macOS skipped) | ✅ | (本 commit) |

## 测试结果

```
test_sandbox_runner_is_protocol               PASSED
test_posix_sandbox_spawn_returns_process      PASSED
test_posix_sandbox_stdin_pipe_works           PASSED
test_posix_sandbox_env_injection              PASSED
test_posix_sandbox_cwd_set                    PASSED
test_posix_sandbox_setsid_new_session         PASSED
test_posix_sandbox_close_fds_no_leak          SKIPPED (HIGH-3 fix: macOS)
test_posix_sandbox_rlimit_nproc_set           PASSED
test_posix_sandbox_rlimit_nofile_set          PASSED
test_posix_sandbox_does_not_raise_on_macos    PASSED

9 passed, 1 skipped in 13.20s
```

---

## Pitfall 防护落地

- **Pitfall 1 (macOS RLIMIT 弱 enforcement)**: `@pytest.mark.linux_only` marker + `does_not_raise_on_macos` 验证 macOS 不抛错（但不断言真 enforcement）
- **Pitfall 4 (fork bomb 进程组逃逸)**: `os.setsid()` in preexec_fn → 新 session + 新 PGID（Plan 04 watchdog 用 `os.killpg(pgid, SIGTERM)` 接力）
- **HIGH-3 (macOS close_fds false-pass)**: 改为 `pytest.skip("close_fds 行为 macOS 与 Linux 差异大，仅 Linux 严格断言")`

---

## Dify 参考点

- `api/core/plugin/entities/plugin.py` — 资源运行环境 envelope 借鉴
- 本项目独立设计 SandboxRunner Protocol（Dify 走 Go daemon，本项目 Python resource.setrlimit baseline）

---

## Files Touched

Created:
- `docs/reading-dify-05b-02-resource-runner-2026-05-18.md`
- `backend/app/agent_builder/platforms/sandbox/runner.py` (SandboxRunner Protocol + PosixResourceSandbox)
- `backend/tests/platforms/sandbox/test_runner.py` (10 tests)
- `backend/pytest.ini` (markers: linux_only / sandbox_integration / cgroups_v2)

Modified:
- `backend/app/agent_builder/platforms/exceptions.py` (+ SandboxLimitExceeded + NetworkBlockedError placeholders)

---

## Phase 5.B Progress

- Wave 1 ✓ 05b-01 (49 + 193 regression)
- Wave 2 進行中：05b-02 ✓ (本 plan) / 05b-03 等待
- Wave 3: 05b-04 + 05b-05 等待

Next: Plan 05b-03 (AllowlistTransport) — Wave 2 并行 plan，预计无文件冲突。
