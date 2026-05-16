# Dify 阅读笔记 — LLM 节点

> 日期: 2026-05-16
> 仓库: https://github.com/langgenius/dify (commit c0bdd679, 本地克隆 /Users/admin/ai/ref/dify/repo/)
> Stars: ~141k

## 项目概述（LLM 节点定位）

Dify 的 LLM 节点是工作流的核心节点，负责调用底层模型服务并将 prompt 渲染后的 messages 传入 LLM，返回结构化的响应。在 Dify 架构中，LLM 节点通过 `graphon` 包（外部依赖 ~0.3.1）中的 `graphon.nodes.llm` 模块实现核心逻辑，工作流层（`api/core/workflow/`）通过适配器（`DifyPreparedLLM`、`DifyNodeFactory`）桥接 Dify 自有的 `ModelInstance` 与 graphon 节点运行时。

## 技术栈（关键技术选择）

| 层 | Dify 选择 | 说明 |
|---|---|---|
| 模型 runtime | `graphon.model_runtime` / Dify 自研 model_providers | 每个 provider 独立插件化，不用 LangChain |
| LLM 调用抽象 | `ModelInstance.invoke_llm()` | 统一同步 / 流式双接口，封装 provider 差异 |
| Prompt 渲染 | Jinja2 + CodeExecutor 沙箱 | `CodeExecutorJinja2TemplateRenderer` 走代码沙箱执行 Jinja2，安全隔离 |
| 工厂分发 | `DifyNodeFactory.create_node()` | 按 node_type 分发不同 init_kwargs（LLM/Tool/HumanInput 各有不同依赖注入） |
| 变量解析 | `graphon` VariablePool | 变量引用路径（selector 数组），不直接用 Jinja2 插值 |
| 错误归一化 | graphon 层统一处理，Dify 层透传 | provider 异常在 graphon 中映射；Dify 工作流层只处理业务错误 |

## 架构要点（核心架构模式，用简图说明）

```
DSL 节点 config (node_type="llm")
    │
    ▼
DifyNodeFactory.create_node()
    │  → fetch_model_config() → ModelInstance
    │  → DifyPreparedLLM(model_instance) (适配层)
    │  → DifyJinja2TemplateRenderer（Jinja2 沙箱）
    │  → fetch_memory()（对话记忆）
    │
    ▼
graphon.nodes.llm.LLMNode.run()（graphon 包，未开源）
    │  1. _render_prompt()  → PromptMessage 列表
    │     ├── system_prompt / user_prompt / assistant_examples → Jinja2 渲染
    │     └── 变量引用通过 VariablePool 解析（variable_selector 数组路径）
    │  2. prepared_llm.invoke_llm(prompt_messages, model_parameters, stream=False)
    │  3. 返回 LLMResult(message, usage, ...)
    │
    ▼
节点输出
    ├── text: str (LLM 响应文本)
    ├── usage: LLMUsage (prompt_tokens / completion_tokens / total_tokens)
    └── finish_reason: str
```

**Dify 的三段 prompt 模式（LLM 节点核心设计）**：
1. `system_prompt` — 系统提示（可含变量 `{{variable}}`）
2. `user_prompt` — 用户主提示（Jinja2 变量替换）
3. `assistant_examples` — few-shot 示例（user + assistant 交替，注入对话历史前）

**raw_prompt（特殊模式）**：
- 直接传 messages JSON 数组，绕过三段渲染，适用高级用户

## 可借鉴的设计模式

### 1. 适配层隔离（`DifyPreparedLLM`）
- **文件**: `api/core/workflow/node_runtime.py`
- **模式**: 工作流层（Dify）与节点运行时（graphon）之间用 Protocol 接口解耦
- **可借鉴**: 我们的 `call_llm()` 函数充当同等角色，将 `init_chat_model` 的细节隔离在 `llm_client.py` 中，LLMNodeExecutor 只依赖 `call_llm` 接口

### 2. 工厂分发 + 依赖注入（`DifyNodeFactory`）
- **文件**: `api/core/workflow/node_factory.py`
- **模式**: 按节点类型分发不同 init_kwargs，每个节点类型需要的服务通过构造函数注入
- **可借鉴**: 我们的 `NodeRegistry` (`@register_node("llm")`) 做类似分发；`LLMNodeExecutor.__init__` 通过 `node_def` 拿到所有配置，不依赖外部 DI 容器

### 3. Jinja2 沙箱隔离（`CodeExecutorJinja2TemplateRenderer`）
- **文件**: `api/core/workflow/template_rendering.py`
- **模式**: Dify 把 Jinja2 渲染委托给独立的 CodeExecutor（代码沙箱进程），彻底隔离模板执行环境
- **可借鉴**: 我们用 `jinja2.sandbox.SandboxedEnvironment` + 白名单 filter（在 `jinja_env.py` 已实现），安全等级略低于 Dify 但对于私有部署场景足够；`_render_config()` 在 `BaseNodeExecutor` 中统一提供

### 4. 节点输出结构化（`LLMResult`）
- **模式**: Dify 定义严格的 `LLMResult` 数据类，包含 `message`、`usage`、`finish_reason`
- **可借鉴**: 我们的 `LLMNodeExecutor.execute()` 返回固定 5 字段：`content / role / usage_metadata / model / response_metadata`，与 LangChain `AIMessage` 字段对齐

### 5. memory 注入（`TokenBufferMemory`）
- **模式**: Dify LLM 节点支持从会话历史注入上下文，通过 `fetch_memory()` 拉取
- **可借鉴**: Phase 1 不实现 memory，但设计时预留 `config.get("memory")` 扩展点（v2 支持）

## 与本项目的关系

### 沿用 Dify 的设计

| Dify 模式 | 本项目实现 | 文件 |
|---|---|---|
| 三段 prompt（system/user/assistant_examples） | `_render_messages()` 按序组装 messages | `nodes/llm.py` |
| Jinja2 变量插值 | `render_with_state()` / `jinja_env.SandboxedEnvironment` | `jinja_env.py` |
| raw_prompt 模式 | `config["raw_prompt"]` → JSON 解析 → messages | `nodes/llm.py` |
| 节点输出固定字段 | `content/role/usage_metadata/model/response_metadata` | `nodes/llm.py` |
| 工厂注册分发 | `@register_node("llm")` + `NodeRegistry` | `nodes/__init__.py` |

### 关键偏离（项目决策，CONTEXT.md 锁定）

| 方面 | Dify 方案 | 本项目方案 | 原因 |
|---|---|---|---|
| LLM 调用层 | Dify 自研 `model_runtime` / graphon | **LangChain `init_chat_model`** | 避免维护 provider 插件；LangChain 生态完整 |
| Provider 扩展 | 每个 provider 独立插件注册（需开发 graphon plugin） | `init_chat_model("provider:model")` 字符串，装对应 `langchain-*` 包即可 | 开发成本更低 |
| 变量引用 | VariablePool + selector 数组路径 | Jinja2 `{{ node_id.field }}` 直接插值 | 前端配置更简单；DSL 可读性更高 |
| Jinja2 沙箱 | 独立 CodeExecutor 进程（最高安全） | `SandboxedEnvironment` + 白名单 filter | 私有部署场景；无需进程隔离的额外开销 |
| 流式输出 | 支持 stream=True | Phase 2 不做 stream | 范围控制；Phase 3 再实现 SSE stream |

### 从 Dify 学到的边界条件

1. **assistant_examples 插入位置**：必须在 user_prompt 之前，system_prompt 之后（Dify 如此实现）
2. **raw_prompt 与三段互斥**：有 `raw_prompt` 时完全忽略三段 prompt 字段
3. **模型名称兜底**：`response_metadata.get("model_name", config["model"])` 处理 provider 不返回 model 名的情况
4. **api_base 覆盖**：Ollama 等自部署场景必须支持 base_url 覆盖，Dify 通过 credentials 机制支持，我们通过 `config.api_base` 直传 `init_chat_model`
