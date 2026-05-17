# Phase 5.C — Deferred Items

## 1. docker_networks 字段在 docker 容器部署下的语义（2026-05-18 加）

**约束**：部署是 docker 容器化，**容器内禁 DinD**（user 2026-05-18 指令）。

**现状**（Plan 05c-01 已实施）：
- `SandboxConfig.docker_networks: list[str]` 字段已加（接口冻结）
- `SandboxRunner.spawn_with_limits(..., docker_networks)` 已加（参数冻结）
- `PosixResourceSandbox` → **no-op**（不调 `docker network connect`）
- `CgroupsV2Sandbox` → 设计上调 `docker network connect`，但**生产 docker 部署用 PosixResourceSandbox**（容器内 cgroups 不可用），所以**隐式满足 no-DinD 约束**

**Deferred 项**：
1. **CONTEXT.md / RESEARCH.md 中"docker network connect"叙述**需重写：明确说明这条路径只适用于**裸金属 / VM 真 cgroups v2**部署，docker 容器部署下退化为 no-op
2. **production 跨网络 plugin（如 HulyPlugin 调 collaborator:3078）**走 **docker-compose `networks` external 声明**（容器启动 join），不是 runtime attach
3. **`docker_networks` manifest 字段**保留作 schema 兼容性（裸金属部署可用），但**docker 部署下应被忽略 + 打 warning**
4. **README 已写入正确部署指南**（"跨网络 plugin 接入"段落 + docker-compose external network 示例）

**触发条件**：进入 Wave 2 / Plan 05c-05 (HulyPlugin) 前，需把 CONTEXT/RESEARCH 中相关段落与 README 对齐，避免误导后续 executor 实施 runtime `docker network connect`。

---

*Created: 2026-05-18*
