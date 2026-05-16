---
phase: 04-approval-chain-im
plan: "01"
subsystem: hitl-chain-infra
tags: [hitl, chain, payload, immutability, advisory-lock, partial-index, dataclass, frozen]

requires:
  - phase: 03-hitl-email
    provides: HitlTokenStore.invalidate_siblings + HitlToken ORM + hitl_payload 纯函数模式 + advisory_lock 模式
provides:
  - ChainAdvanceResult @dataclass(frozen=True) — 不可变审批链推进结果（5 字段：new_status / new_payload / next_approvers / invalidate_others / supplement_notify）
  - compute_chain_advance 纯函数（4 chain mode × 3 action = 12 状态机分支全覆盖）
  - build_initial_payload 扩展（接受 chain_mode 参数 + parallel_* 自动初始化 decisions 字典）
  - HitlTokenStore.invalidate_chain(instance_id, except_jti) — 跨实例失效未消费 token
  - Alembic 0005 partial index ix_hitl_tokens_instance_used ON (instance_id, used_at) WHERE used_at IS NULL
affects: [04-02-chain-executor, 04-03-delegation, 04-04-escalation, all-im-providers, 04-12-hitl-node-executor]

tech-stack:
  added: []  # 纯 stdlib（dataclass + Literal）；无新依赖
  patterns:
    - "@dataclass(frozen=True) + field(default_factory=list) — immutable 返回值 + 防共享 mutable 默认值"
    - "{**payload, ...} + new list/dict — 纯函数严格 immutability"
    - "Literal['single','sequential','parallel_all','parallel_any'] — 类型族风格统一（与 NodeStatus/Action 一致）"
    - "partial index postgresql_where=sa.text('used_at IS NULL') — Alembic 索引压缩"

key-files:
  created:
    - backend/migrations/versions/0005_phase4_chain_indexes.py
    - backend/tests/test_hitl_payload_chain.py (29 用例)
    - backend/tests/test_hitl_token_store_chain.py (11 用例)
    - docs/reading-dify-04-01-chain-payload-2026-05-17.md
  modified:
    - backend/app/agent_builder/workflow/hitl_payload.py (扩展：+330 lines, +ChainAdvanceResult, +compute_chain_advance, +4 helper, build_initial_payload 加 chain_mode 参数)
    - backend/app/agent_builder/workflow/hitl_token_store.py (扩展：+67 lines, +invalidate_chain 方法)

key-decisions:
  - "ChainAdvanceResult 用 @dataclass(frozen=True) 而非 Pydantic/TypedDict/NamedTuple — 见 reading-dify §6 对比表（frozen + default_factory + 零依赖）"
  - "field(default_factory=list) 防共享 mutable 默认值（test_chain_advance_result_default_factory 验证两个实例 list 是独立对象）"
  - "Alembic 0005 而非 plan 写的 0004 — 0004 已被 0004_phase3_node_state_payload.py 占用（Rule 3 - Blocking）"
  - "invalidate_chain used_ip='system:chain-invalidate' / used_ua='system:invalidate_chain' — 与 sibling-invalidate / 真实用户消费三层审计区分"
  - "build_initial_payload 默认 chain_mode='single' 保持 Phase 3 完全向后兼容（test_build_initial_payload_single_mode_backward_compat 验证）"
  - "parallel_* 模式 decisions 字典初始化所有 approver 为 None；single/sequential 不创建 decisions（用 current_idx 推进）"
  - "supplement_notify 智能过滤：仅返回「未决策 + 非当前 actor」的 approver — 已决策 token 已自然消费，不发重复补通知"
  - "sequential 越权防护：only approvers[current_idx] 能决策；不依赖 actor_id ∈ approvers 弱校验"
  - "0005 partial index `WHERE used_at IS NULL` — invalidate_chain 仅扫未消费 token，partial index 体积更小、更新代价更低"
  - "_advance_single 包装 Phase 3 行为 + 返回 ChainAdvanceResult — 调用方可统一处理 4 模式，不需特殊分支"

patterns-established:
  - "纯函数 chain state machine — 返回 frozen ChainAdvanceResult + 调用方负责副作用（DB INSERT / Redis SET / 邮件入队）"
  - "deep equal immutability 测试 — copy.deepcopy(payload) 前后对比，断言入参无被意外修改"
  - "_redis_key + Redis pipeline 模式延续 — invalidate_chain 复用 invalidate_siblings 的 pipeline 模板"
  - "advisory_xact_lock 兼容性测试 — 在 pg_advisory_xact_lock 持有期间调 invalidate_chain，验证无 deadlock（Pitfall 2 防护）"
  - "Migration 版本号顺延 — 0004 占用时 0005 down_revision='0004' 而非重命名"

requirements-completed:
  - HITL-02
  - HITL-06

duration: 10min
completed: 2026-05-17
---

# Phase 4 Plan 01: 审批链 chain payload + invalidate_chain + Alembic 0005 partial index Summary

**ChainAdvanceResult frozen dataclass + compute_chain_advance 纯函数（4 chain mode × 3 action 状态机）+ HitlTokenStore.invalidate_chain 跨实例失效 + Alembic 0005 partial index 加速 chain 扫描**

## Performance

- **Duration:** 10 min
- **Started:** 2026-05-17T05:25:52Z
- **Completed:** 2026-05-17T05:36:00Z (approx)
- **Tasks:** 3 (Task 0 reading doc + Task 1 hitl_payload + Task 2 hitl_token_store + Alembic)
- **Files modified:** 6 (2 modified + 4 created)

## Accomplishments

- **ChainAdvanceResult @dataclass(frozen=True)** — 不可变返回值数据类，5 字段封装审批链推进结果
- **compute_chain_advance 纯函数** — 4 chain mode（single / sequential / parallel_all / parallel_any）× 3 action（approve / return / reject）= **12 状态机分支** 全覆盖
- **build_initial_payload 扩展** — 接受 chain_mode 参数；parallel_* 模式自动初始化 decisions 字典；Phase 3 default='single' 完全向后兼容
- **HitlTokenStore.invalidate_chain** — 跨整个 instance 失效未消费 token；返回 `[(jti, actor_id), ...]` 供 service 层发"已终止/已被处理"补通知
- **Alembic 0005 partial index** `ix_hitl_tokens_instance_used` ON (instance_id, used_at) WHERE used_at IS NULL — 加速 invalidate_chain 扫描
- **40 个测试** 全过（29 unit chain payload + 11 integration token_store/Alembic），覆盖 4 mode 状态机 + immutability + advisory_lock 兼容性 + partial index 验证

## Task Commits

每个 task 原子提交：

1. **Task 0: Reading doc gate** — `76a2301` (docs) — Dify human_input.py 阅读，确认无 chain，本项目独立设计；ChainAdvanceResult @dataclass(frozen=True) 设计依据（vs Pydantic/TypedDict/NamedTuple 对比表）
2. **Task 1: hitl_payload.compute_chain_advance + ChainAdvanceResult** — `aeb0224` (feat) — 4 chain mode × 3 action 状态机；29 单元测试；hitl_payload.py 模块覆盖率 98%
3. **Task 2: hitl_token_store.invalidate_chain + Alembic 0005** — `b1f9bfc` (feat) — 跨实例失效 + Redis pipeline + partial index；11 集成测试 + upgrade/downgrade 双向验证

**Plan metadata:** 在最终元数据 commit 中收尾（SUMMARY + STATE + ROADMAP）

## Files Created/Modified

### Created

- `docs/reading-dify-04-01-chain-payload-2026-05-17.md` (191 lines) — Reading doc gate（CLAUDE.md §2.7），8 必含小节 + ChainAdvanceResult 设计依据 + Dify 对比图
- `backend/migrations/versions/0005_phase4_chain_indexes.py` (66 lines) — Alembic partial index migration
- `backend/tests/test_hitl_payload_chain.py` (375 lines, 29 用例) — chain 状态机单元测试
- `backend/tests/test_hitl_token_store_chain.py` (370 lines, 11 用例) — invalidate_chain + partial index 集成测试

### Modified

- `backend/app/agent_builder/workflow/hitl_payload.py` (+330 lines)
  - 新增 `ChainMode = Literal[...]`
  - 新增 `ChainAdvanceResult @dataclass(frozen=True)`
  - 新增 `compute_chain_advance` 总入口 + 4 helper（`_advance_single` / `_advance_sequential` / `_advance_parallel_all` / `_advance_parallel_any`）
  - 扩展 `build_initial_payload` 接受 `chain_mode` 参数 + 自动初始化 `approval_chain.decisions`（parallel_* 模式）
- `backend/app/agent_builder/workflow/hitl_token_store.py` (+67 lines)
  - 新增 `HitlTokenStore.invalidate_chain(instance_id, except_jti) -> list[tuple[UUID, UUID]]`

## Decisions Made

### ChainAdvanceResult 设计

- **@dataclass(frozen=True)** 而非 Pydantic — 零依赖、零运行时校验开销、返回值无 validation 需求
- **field(default_factory=list)** — 防共享 mutable 默认值；每次实例化都新建 list（`test_chain_advance_result_default_factory` 验证）
- **5 字段封装**：`new_status / new_payload / next_approvers / invalidate_others / supplement_notify` — 调用方一次拿到全部副作用清单（DB / Redis / 通知）

### chain 模式状态机决策

- **sequential approve advance**：current_idx + 1 + next_approvers=[next]；service 层据此创建下一人 token
- **sequential reject**：立即 rejected，不发补通知（B/C 从未被骚扰）
- **parallel_all reject/return**：immediate 终止 + invalidate_others=True + supplement_notify=未决策的 actor
- **parallel_any approve**：first-wins → done + invalidate_others=True + supplement_notify=未决策的 actor
- **single 模式包装**：返回 ChainAdvanceResult 但 invalidate_others=False；调用方对 4 模式统一处理无特殊分支

### immutability 实施

- 所有 helper 用 `{**payload, ...}` + `dict(...)` + new list 创建新对象
- `copy.deepcopy` 测试断言入参 deep equal 调用前后
- `test_compute_chain_advance_new_payload_independent_list` 验证 `result.new_payload["approval_chain"] is not payload["approval_chain"]`

### Alembic 版本号决策

- Plan 写 `0004_phase4_chain_indexes`，实际 0004 已被 `0004_phase3_node_state_payload.py` 占用
- 用 0005，`down_revision="0004"`
- 不重命名既有 migration（避免 alembic_version 表混乱）

### supplement_notify 智能过滤

- parallel_all reject 时，**仅通知**：「不是当前 actor」AND「未决策（decisions[a] is None）」
- 已决策的 approver（如 B 之前 approve 过）token 已自然消费，无需重复补通知
- 测试 `test_compute_chain_advance_parallel_all_reject_skips_already_decided` 验证此优化

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Alembic migration revision 改 0005**

- **Found during:** Task 2（写 Alembic migration）
- **Issue:** Plan 指定 `revision = "0004_phase4_chain_indexes"`，但 backend/migrations/versions/0004_phase3_node_state_payload.py 已占用 0004
- **Fix:** Migration 文件命名 `0005_phase4_chain_indexes.py`，`revision = "0005"`，`down_revision = "0004"`；migration 顶部 docstring 明示「Why 不放 0004」+ 沿用顺序号规则
- **Files modified:** `backend/migrations/versions/0005_phase4_chain_indexes.py`
- **Verification:** `alembic upgrade head` 跑通 0001→0002→0003→0004→0005 全链；`alembic downgrade -1` 删除 partial index 后 `alembic upgrade head` 再次成功
- **Committed in:** b1f9bfc (Task 2 commit)

**2. [Rule 3 - Blocking] Postgres test container 启动**

- **Found during:** Task 2 集成测试运行前
- **Issue:** 项目 Postgres 容器（端口 15432）未运行，仅 redis 容器运行
- **Fix:** `docker run -d --name agent-builder-postgres-test -p 15432:5432 postgres:16-alpine`；自动等待 `pg_isready`；运行 alembic head + 11 integration test pass
- **Files modified:** 无（环境性修复）
- **Verification:** 所有 11 集成测试通过；Alembic upgrade/downgrade 双向验证；EXPLAIN SQL 输出查询计划
- **Committed in:** 不入 commit（环境配置）；记录在 SUMMARY 此处便于复现

---

**Total deviations:** 2 auto-fixed (2 blocking environment / config issues)
**Impact on plan:** 均为 environment / Alembic 版本号一致性修复，不改变 plan 范围或设计。

## Dify 参考点

参见 [`docs/reading-dify-04-01-chain-payload-2026-05-17.md`](../../../docs/reading-dify-04-01-chain-payload-2026-05-17.md)。

**关键论点**：
- **Dify 无 approval_chain** — grep `chain|approver|parallel_all|parallel_any|sequential` 在 Dify `api/models/` 全空（强证据）
- **HumanInputForm 是单 actor 模式**：一行 form = 一个决策 lifecycle；多收件人是抢锁语义（`FormSubmittedError 412`），非协同决策
- **本项目 chain 字段是独立设计** — HITL-02 是本项目独创需求（多人审批链 4 模式）

**借鉴点**：
- 三层 ORM 拆分思路（Form / Delivery / Recipient）映射到 `hitl_tokens` 表 + `notifications` 表的二元拆分
- `@dataclass(frozen=True)` 替代 Dify 的 Pydantic `Annotated + Field(discriminator)` — 设计模式可借鉴，避免依赖
- advisory_lock + 业务异常细分（与 Phase 3 03-06 已沉淀的模式一致）

**未借鉴**：
- Dify AGPL 源码不可复用
- `FormSubmittedError` 抢锁语义不适合多 actor 协同；我们用 `invalidate_chain` 主动失效语义更精确

## Self-Check Plan

- [x] Reading doc 是第一个 commit (76a2301)
- [x] Task 1 + Task 2 commits 在 reading doc 之后 (aeb0224, b1f9bfc)
- [x] hitl_payload.py 模块覆盖率 98%（仅 3 行未覆盖均为 unreachable error 分支）
- [x] 40 个测试全过（29 unit + 11 integration）
- [x] Alembic 0005 upgrade + downgrade 双向无错
- [x] partial index 含 WHERE used_at IS NULL 子句（pg_indexes 验证）
- [x] invalidate_siblings 既有行为未受影响（regression test 通过）
- [x] 严格 immutability：3 个 deep equal 测试 + 1 个对象 identity 测试
- [x] 不引入新依赖（dataclass + Literal 是 stdlib）
- [x] 不动 flock 上游文件（仅扩展 agent_builder 自己模块）

## Issues Encountered

- **Postgres 容器未运行**：用 `docker run` 临时启动 postgres:16-alpine 测试容器（端口 15432）；alembic head 跑通全链
- **`alembic.ini` 默认端口 5433**：未走默认配置；通过 `POSTGRES_DSN` env 覆盖（与 conftest.py 模式一致）

## Next Plan Readiness

**04-02-PLAN（chain executor）** 立即可启动：

- ✓ ChainAdvanceResult 已经是公共 API（`from hitl_payload import ChainAdvanceResult, compute_chain_advance`）
- ✓ invalidate_chain 已实现（`HitlTokenStore.invalidate_chain`）
- ✓ 04-RESEARCH.md §一 Phase 4 扩展矩阵中 "HitlActionService submit_action 6→7 分叉" 现在有所有底层 primitives
- ✓ Alembic 0005 partial index 加速保证 invalidate_chain 即使有 1000 个未消费 token 也是 ms 级
- ✓ Phase 3 既有 advisory_xact_lock + Pitfall 2 防护沉淀齐全

**接下来可并行**：04-02（chain executor）+ 04-05（escalation 表达式扩展）— 两者均依赖本 plan 但互不写入冲突。

## Self-Check: PASSED

**Files verified:**
- ✓ docs/reading-dify-04-01-chain-payload-2026-05-17.md
- ✓ backend/migrations/versions/0005_phase4_chain_indexes.py
- ✓ backend/tests/test_hitl_payload_chain.py
- ✓ backend/tests/test_hitl_token_store_chain.py
- ✓ .planning/phases/04-approval-chain-im/04-01-SUMMARY.md
- ✓ backend/app/agent_builder/workflow/hitl_payload.py (modified)
- ✓ backend/app/agent_builder/workflow/hitl_token_store.py (modified)

**Commits verified:**
- ✓ 76a2301 (Task 0: reading doc)
- ✓ aeb0224 (Task 1: compute_chain_advance)
- ✓ b1f9bfc (Task 2: invalidate_chain + Alembic 0005)

---
*Phase: 04-approval-chain-im*
*Plan: 04-01*
*Completed: 2026-05-17*
