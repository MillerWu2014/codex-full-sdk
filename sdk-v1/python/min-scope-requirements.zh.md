# Python SDK 最小范围实现需求

本文约定 `openai-codex`（`sdk/python`）下一阶段要 **公开 1:1 封装** 的 app-server v2 方法。协议字段以 [`codex-rs/app-server/README.md`](../../codex-rs/app-server/README.md) 与 `generated/v2_all.py` 为准。分类对照 [`docs/app-server-api.zh.md`](../../docs/app-server-api.zh.md)。

## 1. 目标

在 **不改 app-server 协议** 的前提下，把下列域的客户端 RPC 做到公开可调用（`Codex` / `AsyncCodex` / `Thread` / `AsyncThread`）：

- Thread
- Turn
- Skills
- MCP / Tools（不含 OAuth）
- Config / 功能开关（不含权限 profile）
- Model
- 文件系统 / 搜索
- Goal / Queue / Memory / Project / Thread section

调用方应能用带类型的方法完成：建/管会话、跑 turn、列/配 skill、配 MCP 并直调工具、读写 config、列模型、操作 host 文件、管 goal/project。不必再靠未导出的 `CodexClient.request()`。

`CodexClient.request(method, params)` 继续保留作逃逸舱，不作为本需求的验收面。

## 2. 非目标（本阶段明确不做）

| 类别 | 例子 | 原因 |
| --- | --- | --- |
| 审批 / 权限（服务器→客户端） | `item/*/requestApproval`、`item/tool/requestUserInput`、`item/tool/call`、`attestation/generate`、`currentTime/read`、`mcpServer/elicitation/request` | 调用方要求先不做；现有默认自动 `accept` 命令/补丁审批 **保持不变** |
| 与审批配套的 thread API | `thread/approveGuardianDeniedAction`、`thread/increment_elicitation`、`thread/decrement_elicitation` | 同上 |
| MCP OAuth | `mcpServer/oauth/login` 及 `mcpServer/oauthLogin/completed` | 调用方要求不做 |
| 沙箱 / 本机执行 | `command/exec*`、`process/*`、`thread/backgroundTerminals/*`、`windowsSandbox/*`、`thread/shellCommand` | 沙箱与无沙箱进程均不做；TUI `!` 无沙箱命令也不做 |
| 权限 profile | `permissionProfile/list`；`thread/start` / `turn/start` 新增 `permissions` / `dynamicTools` | 属权限/沙箱面 |
| 已弃用 | `thread/rollback`、`getConversationSummary`、`getAuthStatus`、`gitDiffToRemote`；`thread/read` 的全量 `includeTurns`（分页 thread 已弃用该语义） | 不封装 |
| 本需求未点名的域 | Plugin / Marketplace（除 `plugin/skill/read`）、Apps、Review、Realtime、Remote control、Environment、Login 缺口（Bedrock / rateLimits / usage）、Hooks、Feedback、Diagnostics | 不做 |
| 新通知总线 | 连接级订阅 `thread/closed`、`skills/changed` 等 | 本阶段不要求；turn 仍用现有 `TurnHandle.stream()` / `run()` |

现有 `thread_start(sandbox=..., approval_mode=...)` **保持原样**，不扩展、不删除。

## 3. 实现原则

1. **类型 1:1**：请求/响应使用已生成的 `*Params` / `*Response`，字段 camelCase 与协议一致。不要再做一层精简 DTO。
2. **方法 1:1**：一个 RPC 一个公开方法；参数缺口（如 `thread/fork` 的 `lastTurnId`）补齐到协议完整 Params。
3. **双表面**：每个新方法同时出现在同步与异步 API 上，风格与现有 `thread_list` / `thread.run` 一致。
4. **实验性隔离**：协议标 experimental 的方法放在独立模块或明确前缀（例如 `codex.experimental.queue_add`，或 `Thread.queue_add` 但文档/类型标 experimental），并要求 `CodexConfig.experimental_api = True`（即 `initialize.capabilities.experimentalApi`）。未开实验面时调用应得到清晰错误，而不是静默丢字段。
5. **不新增服务器→客户端 handler**。OAuth、elicitation、自定义审批都不做。
6. **测试**：每个新增公开方法至少一条 app-server JSON-RPC 集成测试（mock 或 `TestAppServer` 同类 harness）。不测「静态常量」。不把「未做的审批」写成负向测试。

## 4. 范围内 RPC

图例：

- **已有**：公开 1:1 已够用（可小补参数）
- **待做**：本需求必须公开封装
- **实验性待做**：必须封装，但走实验性命名空间 / 开关
- **补参数**：方法已有，Params 未对齐协议

### 4.1 Thread

| RPC | 状态 | 公开落点（建议） |
| --- | --- | --- |
| `thread/start` | 已有；**补参数** `environments`（不要补 `permissions` / `dynamicTools`） | `Codex.thread_start` |
| `thread/resume` | 已有 | `Codex.thread_resume` |
| `thread/fork` | **补参数** `lastTurnId` / `beforeTurnId` / `excludeTurns` | `Codex.thread_fork` |
| `thread/list` | 已有 | `Codex.thread_list` |
| `thread/read` | 已有 | `Thread.read` |
| `thread/archive` | 已有 | `Codex.thread_archive` |
| `thread/unarchive` | 已有 | `Codex.thread_unarchive` |
| `thread/delete` | 待做 | `Codex.thread_delete` |
| `thread/name/set` | 已有 | `Thread.set_name` |
| `thread/unsubscribe` | 待做 | `Thread.unsubscribe` |
| `thread/loaded/list` | 待做 | `Codex.thread_loaded_list` |
| `thread/turns/list` | 待做 | `Thread.turns_list` |
| `thread/items/list` | 待做 | `Thread.items_list` |
| `thread/compact/start` | 已有 | `Thread.compact` |
| `thread/revert` | 待做 | `Thread.revert` |
| `thread/inject_items` | 待做 | `Thread.inject_items` |
| `thread/metadata/update` | 待做 | `Thread.metadata_update` |
| `thread/section/move` | 待做 | `Thread.section_move` |
| `thread/search` | 实验性待做 | experimental |
| `thread/searchOccurrences` | 实验性待做 | experimental |

不做：`thread/rollback`、`thread/shellCommand`、`thread/approveGuardianDeniedAction`、elicitation 计数。

### 4.2 Turn

| RPC | 状态 | 公开落点（建议） |
| --- | --- | --- |
| `turn/start` | 已有；**补输入** `audio` / `localAudio`、独立 `toolOutput`；**补参数** `environments`（不要补 `permissions`） | `Thread.turn` / `Thread.run` |
| `turn/steer` | 已有 | `TurnHandle.steer` |
| `turn/interrupt` | 已有 | `TurnHandle.interrupt` |
| `turn/settings/update` | 实验性待做 | experimental |

Turn 事件流维持现状（`stream()` / `run()`）。不要求单独订阅 item 审批。

### 4.3 Skills

| RPC | 状态 | 公开落点（建议） |
| --- | --- | --- |
| `skills/list` | 待做 | `Codex.skills_list` |
| `skills/extraRoots/set` | 待做 | `Codex.skills_extra_roots_set` |
| `skills/config/write` | 待做 | `Codex.skills_config_write` |
| `plugin/skill/read` | 待做 | `Codex.plugin_skill_read` |
| `turn/start` 的 `skill` | 已有 | `SkillInput` |

不做：`skills/changed` 通知订阅。Plugin 安装/市场其余 API 不做。

### 4.4 MCP / Tools

| RPC | 状态 | 公开落点（建议） |
| --- | --- | --- |
| `config/mcpServer/reload` | 待做 | `Codex.mcp_reload` |
| `mcpServerStatus/list` | 待做 | `Codex.mcp_status_list` |
| `mcpServer/resource/read` | 待做 | `Codex.mcp_resource_read` |
| `mcpServer/tool/call` | 待做 | `Thread.mcp_tool_call`（需要 `threadId`） |
| `config/read` / `config/batchWrite` | 见 Config | 配 `[mcp_servers]` 走 config API |

不做：`mcpServer/oauth/login`、elicitation、`mcpServer/event/stream/*`。

说明：turn 内模型自行调用 MCP 已由引擎执行，本需求只补 **配置面 reload/status** 与 **客户端直调 tool/call、resource/read**。需要登录的 MCP server 本阶段不支持走 SDK 完成 OAuth。

### 4.5 Config / 功能开关

| RPC | 状态 | 公开落点（建议） |
| --- | --- | --- |
| `config/read` | 待做 | `Codex.config_read` |
| `config/value/write` | 待做 | `Codex.config_value_write` |
| `config/batchWrite` | 待做 | `Codex.config_batch_write` |
| `configRequirements/read` | 待做 | `Codex.config_requirements_read` |
| `experimentalFeature/list` | 待做 | `Codex.experimental_feature_list` |
| `experimentalFeature/enablement/set` | 待做 | `Codex.experimental_feature_enablement_set` |
| `externalAgentConfig/detect` | 待做 | `Codex.external_agent_config_detect` |
| `externalAgentConfig/import` | 待做 | `Codex.external_agent_config_import` |
| `externalAgentConfig/import/readHistories` | 待做 | `Codex.external_agent_config_import_read_histories` |
| `collaborationMode/list` | 实验性待做 | experimental |

不做：`permissionProfile/list`。`CodexConfig.config_overrides` 保持现有 CLI 覆盖，不算本需求新 RPC。

Config 键名按协议走 **snake_case**（对齐 `config.toml`）。

### 4.6 Model

| RPC | 状态 | 公开落点（建议） |
| --- | --- | --- |
| `model/list` | 已有 | `Codex.models` |
| `modelProvider/capabilities/read` | 待做 | `Codex.model_provider_capabilities` |

选用模型继续用 `thread_start` / `turn` 的 `model` / `model_provider`。不要求 SDK 发现 Ollama/vLLM 本地 tag。

### 4.7 文件系统 / 搜索

Host FS RPC，路径必须绝对。不是模型 `fileChange` 工具。

| RPC | 状态 | 公开落点（建议） |
| --- | --- | --- |
| `fs/readFile` | 待做 | `Codex.fs_read_file` |
| `fs/writeFile` | 待做 | `Codex.fs_write_file` |
| `fs/createDirectory` | 待做 | `Codex.fs_create_directory` |
| `fs/getMetadata` | 待做 | `Codex.fs_get_metadata` |
| `fs/readDirectory` | 待做 | `Codex.fs_read_directory` |
| `fs/remove` | 待做 | `Codex.fs_remove` |
| `fs/copy` | 待做 | `Codex.fs_copy` |
| `fs/watch` | 待做 | `Codex.fs_watch` |
| `fs/unwatch` | 待做 | `Codex.fs_unwatch` |
| `fuzzyFileSearch` | 待做 | `Codex.fuzzy_file_search` |
| `fuzzyFileSearch/sessionStart` | 实验性待做 | experimental |
| `fuzzyFileSearch/sessionUpdate` | 实验性待做 | experimental |
| `fuzzyFileSearch/sessionStop` | 实验性待做 | experimental |

`fs/watch` 必须能收到变更通知（可返回 iterator / async iterator）。这是本范围内 **唯一新增的长订阅**。

### 4.8 Goal / Queue / Memory / Project / Section

| RPC | 状态 | 公开落点（建议） |
| --- | --- | --- |
| `thread/goal/set` | 内部已有 → **升公开** | `Thread.goal_set` |
| `thread/goal/get` | 待做 | `Thread.goal_get` |
| `thread/goal/clear` | 内部已有 → **升公开** | `Thread.goal_clear` |
| `threadSection/list` | 待做 | `Codex.thread_section_list` |
| `threadSection/create` | 待做 | `Codex.thread_section_create` |
| `threadSection/update` | 待做 | `Codex.thread_section_update` |
| `threadSection/delete` | 待做 | `Codex.thread_section_delete` |
| `thread/queue/*`（add/list/update/delete/reorder/start） | 实验性待做 | `Thread.queue_*` |
| `thread/memoryMode/set` | 实验性待做 | experimental |
| `memory/reset` | 实验性待做 | experimental |
| `thread/settings/update` | 实验性待做 | experimental |
| `project/list|read|create|import|update|move|delete` | 实验性待做 | `Codex.project_*` |

## 5. 建议公开 API 形状

不要把 50+ 方法全堆在 `Codex` 上而无分组。推荐：

```text
Codex
  thread_start / resume / fork / list / archive / unarchive / delete / thread_loaded_list
  models / model_provider_capabilities
  skills_* / plugin_skill_read
  mcp_reload / mcp_status_list / mcp_resource_read
  config_* / experimental_feature_* / external_agent_config_*
  fs_* / fuzzy_file_search
  thread_section_* / project_*
  experimental  # 或同名方法但要求 experimental_api

Thread
  read / set_name / compact / unsubscribe / revert / inject_items
  turns_list / items_list / metadata_update / section_move
  turn / run / steer / interrupt
  mcp_tool_call
  goal_set / goal_get / goal_clear
  queue_*   # experimental
```

方法名与 RPC 的对应必须在 docstring 第一行写明，例如 `"""RPC: skills/list."""`。

## 6. 分期（仍属本需求，便于落地）

**P0（稳定、无订阅）** — 先合并

- Thread：delete、unsubscribe、loaded/list、turns/list、items/list、revert、inject_items、metadata/update、section/move；fork 补参数；start 补 `environments`
- Turn：audio / toolOutput；environments
- Skills 四个管理 RPC
- MCP：reload、status/list、resource/read、tool/call
- Config 全套（不含 permissionProfile、不含 collaborationMode）
- Model：capabilities/read
- FS CRUD + `fuzzyFileSearch`
- Goal 公开三方法 + threadSection CRUD

**P1（本需求内的实验性 + watch）**

- `fs/watch` / `fs/unwatch`
- Queue、Project、Memory、`thread/settings/update`、`turn/settings/update`
- `thread/search*`、`collaborationMode/list`、fuzzy search session

P0 未完成不开始 P1。P1 全部隐藏在 experimental 开关后。

## 7. 验收

1. 第 4 节「待做 / 补参数 / 升公开 / 实验性待做」均有对应公开方法（P1 须 `experimental_api`）。
2. 第 2 节列出的 RPC **没有** 新的公开封装。
3. `just test` 范围内：`sdk/python` 新增测试覆盖每个新 RPC 的至少一次成功路径。
4. 同步与异步行为一致（同一 Params/Response 类型）。
5. 更新 [`docs/app-server-api.zh.md`](../../docs/app-server-api.zh.md) 的 Python SDK 列：范围内方法从「无 / 内部 / 部分」改为「公开」。
6. 默认审批行为与现在相同（命令/补丁自动 accept）；文档写明自定义审批 **不在本范围**。

## 8. 刻意保留的限制

- 需要 OAuth 的 MCP 只能先用进程外登录 / 手改 config，再 `mcp_reload`。
- 需要人工审批的 turn 仍会走默认 accept；本阶段不做宿主审批 UI。
- `model/list` 仍不是本地推理标签目录。
- Skill 进入模型上下文仍须 `turn/start` 的 `SkillInput`（或 `$name` 文本）；`skills/list` 只负责发现。
