# Codex App-Server API 分类说明

公开 Python 封装（参数/返回/示例）不在本文，而在：

- [sdk-v1 接口 · 中文](python/docs/codex-python-sdk-v0.152.0-api-zh.md)
- [sdk-v1 API · English](python/docs/codex-python-sdk-v0.152.0-api-en.md)
- 仓库文档入口：[根 README](../README.md)

本文按功能分类整理 `codex app-server` 的 **v2 JSON-RPC** 接口（方法名、作用、依赖、Python SDK 覆盖）。协议字段、错误码与 JSON 示例以英文原文为准：

- [`codex-rs/app-server/README.md`](../codex/codex-rs/app-server/README.md)
- 类型定义：`codex-rs/app-server-protocol/src/protocol/common.rs` 中的 `ClientRequest`

传输不是 REST，而是 JSON-RPC（stdio / Unix socket；websocket 为实验性）。标 **实验性** 的方法需要在 `initialize.capabilities.experimentalApi = true` 后才可用。

## Python SDK 列说明

对照包 `openai-codex`（`sdk-v1/python`）：

| 取值     | 含义                                                                                                |
| -------- | --------------------------------------------------------------------------------------------------- |
| **公开** | `Codex` / `AsyncCodex` / `Thread` / `TurnHandle` 上有一等方法                                       |
| **内部** | 仅 `CodexClient` 有封装，未进公开 `__all__`                                                         |
| **部分** | 公开面只覆盖该 RPC 的一部分参数或变体                                                               |
| **无**   | 无封装。类型在 `generated/v2_all.py`；可用未导出的 `CodexClient.request(method, params)` 打全量协议 |

`Codex()` 构造时会自动 `initialize` + `initialized`。公开入口不导出 `CodexClient`。

## 通用依赖

1. 每个连接必须先发 `initialize`，再发 `initialized`，否则后续请求返回 `"Not initialized"`。
2. 多数 thread / turn 操作需要 **已加载 thread**（由 `thread/start`、`thread/resume` 或 `thread/fork` 得到）。
3. **父级拥有的 Multi-Agent V2 子 agent** 拒绝大部分直接输入（`turn/start`、skill、MCP tool call、shell 等），错误码 `-32600`。

依赖关系概览：

```
initialize
   │
   ├─ account/login/*  ──►  才能稳定调用 OpenAI 模型
   │
   ├─ config/batchWrite ──► config/mcpServer/reload ──► 下一轮 turn 才看到新 MCP
   ├─ skills/extraRoots/set 或 skills/config/write ──► skills/list / turn 里的 $skill
   ├─ plugin/install ──► 可能带 MCP + skill；再 oauth/login
   │
   └─ thread/start | resume
          └─ turn/start  ← 真正跑 agent（工具、沙箱、MCP、Skill）
                ├─ 服务器可能反问：requestApproval / elicitation / tool/call
                └─ 通知流：item/* → turn/completed
```

**配置面**（改引擎能力：MCP / Skill / Plugin / config）和 **数据面**（跑一轮任务：thread / turn）应分开调用。

---

## 0. 连接 / 握手

| 方法                        | 功能                                     | 依赖                     | Python SDK                                                                      |
| --------------------------- | ---------------------------------------- | ------------------------ | ------------------------------------------------------------------------------- |
| `initialize`                | 声明客户端、能力、MCP 扩展、通知 opt-out | 每个连接必须最先调用一次 | **公开**（`Codex()` 构造时自动调用；`CodexConfig.experimental_api` 可开实验面） |
| `initialized`（客户端通知） | 确认握手完成                             | 紧跟 `initialize`        | **公开**（构造时自动发送）                                                      |

返回：`userAgent`、`codexHome`、`platformFamily`、`platformOs`。公开侧通过 `codex.metadata` 读取。  
`clientInfo.name` 会进入 OpenAI Compliance Logs。  
`optOutNotificationMethods` 按精确方法名抑制通知（无通配符）。公开 SDK **不**暴露该字段。

---

## 1. 登录 / 账户（Login）

| 方法                                   | 功能                                                                    | 依赖                                      | Python SDK                                                                                |
| -------------------------------------- | ----------------------------------------------------------------------- | ----------------------------------------- | ----------------------------------------------------------------------------------------- |
| `account/login/start`                  | 开始登录：`apiKey` / `chatgpt` / `chatgptDeviceCode` / `amazonBedrock*` | 写 `account-auth`；Bedrock 需要实验性能力 | **部分**：`login_api_key` / `login_chatgpt` / `login_chatgpt_device_code`；**无** Bedrock |
| `account/login/cancel`                 | 取消进行中的 ChatGPT 登录                                               | `loginId`                                 | **公开**（`ChatgptLoginHandle.cancel()` / 设备码 handle）                                 |
| `account/read`                         | 读当前账户，可选刷新 token                                              | —                                         | **公开**（`codex.account()`）                                                             |
| `account/logout`                       | 登出；Bedrock 时还会清 `model_provider`                                 | —                                         | **公开**（`codex.logout()`）                                                              |
| `account/rateLimits/read`              | ChatGPT 配额、重置额度                                                  | ChatGPT 账户                              | **无**                                                                                    |
| `account/rateLimitResetCredit/consume` | 消费一次已赚取重置                                                      | 幂等键；ChatGPT                           | **无**                                                                                    |
| `account/usage/read`                   | 账户或单 thread 用量                                                    | 可选 `threadId`                           | **无**                                                                                    |
| `account/workspaceMessages/read`       | 工作区公告                                                              | ChatGPT workspace                         | **无**                                                                                    |
| `account/sendAddCreditsNudgeEmail`     | 通知 workspace owner 额度不足                                           | ChatGPT                                   | **无**                                                                                    |
| `account/bedrock/discover` **实验性**  | 发现 AWS profile / 环境凭据（不含密钥）                                 | `experimentalApi`                         | **无**                                                                                    |
| `account/bedrock/setup` **实验性**     | 把 Bedrock provider 写入用户配置                                        | 同上；之后建议重启 app-server             | **无**                                                                                    |

**通知：** `account/login/completed`、`account/updated`、`account/rateLimits/updated`。登录 handle 会消费 login 完成通知；其余无公开订阅 API。  
**服务器 → 客户端：** `account/chatgptAuthTokens/refresh`（客户端要回 token）。SDK **无**自定义处理。

---

## 2. Thread（会话）

核心对象：Thread → Turn → Item。

| 方法                                      | 功能                                              | 依赖                                     | Python SDK                                                                                          |
| ----------------------------------------- | ------------------------------------------------- | ---------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `thread/start`                            | 新建对话，自动订阅事件                            | cwd、model、sandbox / `permissions` 可选 | **公开**（`codex.thread_start`；公开面包含 `environments`，且不暴露 `permissions` / `dynamicTools`） |
| `thread/resume`                           | 按 id 重新打开，后续 turn 追加                    | thread 未被别的进程独占写入              | **公开**（`codex.thread_resume`；包含 `excludeTurns`）                                             |
| `thread/fork`                             | 复制历史成新 thread                               | 可选 `lastTurnId` / `beforeTurnId` / `excludeTurns` | **公开**（`codex.thread_fork`；`beforeTurnId` 为实验性字段） |
| `thread/list`                             | 分页历史；可按 cwd / 归档 / section 过滤          | —                                        | **公开**（`codex.thread_list`）                                                                     |
| `thread/read`                             | 读存储 thread，不 resume                          | 全量 `includeTurns` 对分页 thread 已弃用 | **公开**（`thread.read()`）                                                                         |
| `thread/archive`                          | 归档（含子代）                                    | 独占写入锁                               | **公开**（`codex.thread_archive`）                                                                  |
| `thread/unarchive`                        | 恢复归档                                          | 独占写入锁                               | **公开**（`codex.thread_unarchive`）                                                                |
| `thread/delete`                           | 硬删（含子代）                                    | 独占写入锁                               | **公开**（`codex.thread_delete`）                                                                  |
| `thread/name/set`                         | 改显示名                                          | 已加载或已持久化 rollout                 | **公开**（`thread.set_name`）                                                                       |
| `thread/unsubscribe`                      | 取消订阅；30 分钟无活动后卸载并发 `thread/closed` | —                                        | **公开**（`thread.unsubscribe`）                                                                    |
| `thread/loaded/list`                      | 内存中已加载的 thread id                          | —                                        | **公开**（`codex.thread_loaded_list`）                                                              |
| `thread/turns/list`                       | 分页 turn 历史，不 resume                         | 分页 store                               | **公开**（`thread.turns_list`）                                                                     |
| `thread/items/list`                       | 分页 item，不 resume                              | 分页 store                               | **公开**（`thread.items_list`）                                                                     |
| `thread/compact/start`                    | 手动压缩历史                                      | 已加载 thread                            | **公开**（`thread.compact`）                                                                        |
| `thread/rollback` **已弃用**              | 丢掉最后 N 轮                                     | 分页 thread 不支持                       | **无**                                                                                              |
| `thread/revert`                           | 把历史裁到 `beforeTurnId` 之前                    | 分页 thread                              | **公开**（`thread.revert`）                                                                         |
| `thread/inject_items`                     | 注入原始 Responses item，不开新 turn              | 已加载 thread                            | **公开**（`thread.inject_items`）                                                                   |
| `thread/shellCommand`                     | TUI `!` 命令，**无沙箱全权限**                    | 已加载 thread                            | **无**                                                                                              |
| `thread/approveGuardianDeniedAction`      | 手动放行 Guardian 拒绝的操作                      | —                                        | **无**                                                                                              |
| `thread/metadata/update`                  | 改 sqlite 元数据 / `projectId`                    | —                                        | **公开**（`thread.metadata_update`）                                                                |
| `thread/section/move`                     | 移入 / 移出 section                               | `threadSection/*`                        | **公开**（`thread.section_move`）                                                                   |
| `thread/search` **实验性**                | 搜索 thread                                       | `experimentalApi`                        | **公开**（`codex.experimental.thread_search`）                                                      |
| `thread/searchOccurrences` **实验性**     | 在分页 thread 里搜字面匹配                        | 分页 thread                              | **公开**（`codex.experimental.thread_search_occurrences`）                                          |
| `thread/increment_elicitation` **实验性** | 线程外审批期间暂停超时计数                        | 已加载 thread                            | **无**                                                                                              |
| `thread/decrement_elicitation` **实验性** | 恢复超时计数                                      | 已加载 thread                            | **无**                                                                                              |

**通知：** `thread/started`、`status/changed`、`archived`、`deleted`、`closed`、`name/updated`、`tokenUsage/updated`。公开 SDK 不单独订阅这些，只在 turn `stream()` 里收该 turn 的通知。

---

## 3. Turn（一轮对话）— 数据面核心

| 方法                              | 功能                                                           | 依赖                                                | Python SDK                                                                                                                                                                   |
| --------------------------------- | -------------------------------------------------------------- | --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `turn/start`                      | 发用户输入（text / image / audio / skill / mention），开始生成 | 已加载 thread；可带 sandbox / `permissions` / model | **公开**（`thread.turn` / `thread.run`；包含稳定 `toolOutput`，`environments` 为实验性字段；不暴露 `permissions`） |
| `turn/steer`                      | 往**进行中**的常规 turn 追加输入                               | `expectedTurnId`；review / compact 拒绝             | **公开**（`TurnHandle.steer`）                                                                                                                                               |
| `turn/interrupt`                  | 取消进行中的 turn                                              | `(threadId, turnId)`                                | **公开**（`TurnHandle.interrupt`）                                                                                                                                           |
| `turn/settings/update` **实验性** | 热改当前 live task 的 model / effort                           | `step_model_switching` 功能开关                     | **公开**（`TurnHandle.settings_update`）                                                                                                                             |

**输入类型：** `text`、`image` / `localImage`、`audio` / `localAudio`、`skill`、`mention`（app / plugin）、独立 `toolOutput`。

**通知：** `turn/started` → `item/started` / `item/*/delta` → `item/completed` → `turn/completed`。公开侧用 `TurnHandle.stream()` / `run()` 消费该 turn 的通知。

---

## 4. Skills

Skill **不是**单独跑一轮的引擎；要进模型上下文，走 `turn/start` 的 `skill` item 或文本里的 `$name`。

| 方法                         | 功能                                | 依赖                                                          | Python SDK               |
| ---------------------------- | ----------------------------------- | ------------------------------------------------------------- | ------------------------ |
| `skills/list`                | 按 cwd 列出可用 skill               | `~/.codex/skills/`、`<cwd>/.codex/skills/`、plugin 捆绑 skill | **公开**（`codex.skills_list`） |
| `skills/extraRoots/set`      | 设置进程级额外 skill 根             | **不持久化**；进程退出丢失                                    | **公开**（`codex.skills_extra_roots_set`） |
| `skills/config/write`        | 按 name 或绝对 path 启用 / 禁用     | 写用户 config                                                 | **公开**（`codex.skills_config_write`） |
| `plugin/skill/read`          | 预览未安装远程 plugin 的 `SKILL.md` | 远程 marketplace                                              | **公开**（`codex.plugin_skill_read`） |
| `turn/start` 的 `skill` 输入 | 本轮注入 skill 指令                 | 已知 `name` + `path`                                          | **公开**（`SkillInput`） |

**调用方式（数据面）：** `turn/start` 同时给 `$skill-name` 文本 + `{type:"skill", name, path}`。省略 `skill` item 会让模型自己解析，更慢、更不稳定。

**通知：** `skills/changed`。SDK **无**订阅。

---

## 5. MCP / Tools

两层：

- **配置面：** 改 `config.toml` 的 `[mcp_servers]`，然后 reload。
- **调用面：** 模型在 turn 里自己调 MCP；或客户端直接 `mcpServer/tool/call`。

| 方法                                      | 功能                                                   | 依赖                                 | Python SDK |
| ----------------------------------------- | ------------------------------------------------------ | ------------------------------------ | ---------- |
| `config/mcpServer/reload`                 | 从磁盘重载 MCP 配置，**下一轮 turn** 才进已加载 thread | 先 `config/batchWrite` 或手改 toml   | **公开**（`codex.mcp_reload`） |
| `mcpServerStatus/list`                    | 列出 server、工具、鉴权、runtime 状态                  | 可选 `threadId`；省略则无 runtime    | **公开**（`codex.mcp_status_list`） |
| `mcpServer/oauth/login`                   | 浏览器 OAuth，返回 `authorization_url`                 | 已配置 server；可选 `threadId`       | **无**     |
| `mcpServer/resource/read`                 | 读 MCP resource                                        | `server` + `uri`；可选 thread 作用域 | **公开**（`codex.mcp_resource_read`） |
| `mcpServer/tool/call`                     | **客户端直接**调某个 MCP 工具                          | 必须有 `threadId`；子 agent 拒绝     | **公开**（`thread.mcp_tool_call`） |
| `mcpServer/event/stream/start` **实验性** | 订阅 MCP 事件流                                        | `experimentalApi`                    | **无**     |
| `mcpServer/event/stream/stop` **实验性**  | 停止订阅                                               | `experimentalApi`                    | **无**     |
| `config/read`                             | 读含 `mcp_servers.*` 的有效配置                        | 点分路径，snake_case 对齐 toml       | **公开**（`codex.config_read`） |
| `config/batchWrite`                       | 写 MCP 等配置                                          | 同上                                 | **公开**（`codex.config_batch_write`） |

Turn 进行中模型自行调用的 MCP **会跑**（引擎侧），只是 SDK **没有** MCP 管理 / 直调封装。

**通知：** `mcpServer/oauthLogin/completed`、`mcpServer/startupStatus/updated`、`item/mcpToolCall/progress`。  
**服务器 → 客户端：** `mcpServer/elicitation/request`。SDK **无** elicitation UI；默认审批 handler 也不处理它。

---

## 6. Plugin / Marketplace

| 方法                       | 功能                           | 依赖 / 注意                           | Python SDK                                   |
| -------------------------- | ------------------------------ | ------------------------------------- | -------------------------------------------- |
| `marketplace/add`          | 添加 Git marketplace           | 写用户 marketplace 配置               | **无**                                       |
| `marketplace/remove`       | 移除 marketplace               | 同上                                  | **无**                                       |
| `marketplace/upgrade`      | 升级 marketplace               | 同上                                  | **无**                                       |
| `plugin/list`              | 发现 marketplace + plugin 状态 | 文档标 **开发中，勿用于生产**         | **无**                                       |
| `plugin/search` **实验性** | 搜远程 + 本地                  | 同上                                  | **无**                                       |
| `plugin/installed`         | 已安装列表                     | 同上                                  | **无**                                       |
| `plugin/read`              | 读单个 plugin                  | 同上                                  | **无**                                       |
| `plugin/install`           | 安装（含 MCP）                 | 写 config；可能返回 `appsNeedingAuth` | **无**                                       |
| `plugin/uninstall`         | 卸载                           | 写 config                             | **无**                                       |
| `plugin/share/*`           | 共享、checkout、删除共享       | 远程 plugin 服务                      | **无**                                       |
| `turn/start` 的 `mention`  | 本轮 @plugin                   | path 为 `plugin://name@marketplace`   | **公开**（`MentionInput`；不校验 path 形态） |

---

## 7. Apps（连接器）

| 方法                      | 功能                  | 依赖                       | Python SDK                 |
| ------------------------- | --------------------- | -------------------------- | -------------------------- |
| `app/list`                | 可用连接器目录        | 可选 `threadId` 做功能门控 | **无**                     |
| `app/installed`           | 已安装且是否 callable | 可选 `forceRefresh`        | **无**                     |
| `app/read`                | 按 id 批量读元数据    | 最多 100 个 id             | **无**                     |
| `turn/start` 的 `mention` | 本轮 `$app-slug`      | `app://<connector-id>`     | **公开**（`MentionInput`） |

---

## 8. 审批 / 权限（服务器 → 客户端）

这些是 **app-server 问客户端**，不是客户端主动调用。客户端必须回复，否则 turn 会卡住。

| 方法                                    | 功能                  | 依赖                                            | Python SDK                                            |
| --------------------------------------- | --------------------- | ----------------------------------------------- | ----------------------------------------------------- |
| `item/commandExecution/requestApproval` | 批准 / 拒绝命令       | `approvalPolicy`                                | **部分**：默认自动 `accept`；无自定义审批 UI          |
| `item/fileChange/requestApproval`       | 批准文件补丁          | 同上                                            | **部分**：默认自动 `accept`；无自定义审批 UI          |
| `item/permissions/requestApproval`      | 额外 FS / 网络权限    | Granular 策略                                   | **无**（默认 handler 回 `{}`）                        |
| `item/tool/requestUserInput`            | 向用户问 1–3 个短问题 | 实验性能力                                      | **无**                                                |
| `item/tool/call`                        | 动态工具由客户端执行  | `thread/start.dynamicTools` + `experimentalApi` | **无**（公开 `thread_start` 也不接受 `dynamicTools`） |
| `attestation/generate`                  | 桌面证明              | `capabilities.requestAttestation`               | **无**                                                |
| `currentTime/read` **实验性**           | 外部时钟              | `clock_source = "external"`                     | **无**                                                |

`CodexClient` 可注入 `approval_handler`，但公开 `Codex` **不**暴露该参数。可用 `ApprovalMode`（映射 `approvalPolicy` + `approvalsReviewer`）。

---

## 9. Config / 功能开关

| 方法                                       | 功能                            | 依赖                                 | Python SDK |
| ------------------------------------------ | ------------------------------- | ------------------------------------ | ---------- |
| `config/read`                              | 分层解析后的有效配置            | 含 `desktop.*`                       | **公开**（`codex.config_read`） |
| `config/value/write`                       | 写单个键                        | 与 MDM / requirements 冲突则只读错误 | **公开**（`codex.config_value_write`） |
| `config/batchWrite`                        | 原子多键写入，可选热重载 thread | `reloadUserConfig: true`             | **公开**（`codex.config_batch_write`） |
| `configRequirements/read`                  | 企业托管约束                    | `requirements.toml` / MDM            | **公开**（`codex.config_requirements_read`） |
| `experimentalFeature/list`                 | 列 feature flags                | 可选 `threadId`                      | **公开**（`codex.experimental_feature_list`） |
| `experimentalFeature/enablement/set`       | 进程内改 enablement             | 优先级低于 cloud / `--enable` / toml | **公开**（`codex.experimental_feature_enablement_set`） |
| `permissionProfile/list`                   | beta 权限 profile               | 可选 `cwd`                           | **无**     |
| `collaborationMode/list` **实验性**        | 协作模式预设                    | —                                    | **公开**（`codex.experimental.collaboration_mode_list`） |
| `externalAgentConfig/detect`               | 检测可迁移外部 agent 产物       | —                                    | **公开**（`codex.external_agent_config_detect`） |
| `externalAgentConfig/import`               | 导入迁移项                      | —                                    | **公开**（`codex.external_agent_config_import`） |
| `externalAgentConfig/import/readHistories` | 读导入历史                      | —                                    | **公开**（`codex.external_agent_config_import_read_histories`） |

启动时可经 `CodexConfig.config_overrides` 传 CLI `--config`，这不是上述 RPC。

---

## 10. Model

| 方法                              | 功能               | 依赖                                             | Python SDK                   |
| --------------------------------- | ------------------ | ------------------------------------------------ | ---------------------------- |
| `model/list`                      | 目录里的模型       | `includeHidden`；**不是**本地 Ollama / vLLM 标签 | **公开**（`codex.models()`） |
| `modelProvider/capabilities/read` | 当前 provider 能力 | 当前配置的 provider                              | **公开**（`codex.model_provider_capabilities`） |

实际用哪个模型：`thread/start` / `turn/start` 的 `model`（公开参数有），或 `config.toml`。本地 vLLM 走 `[model_providers.*]`，不走 `model/list`。

---

## 11. 执行：沙箱命令 vs 无沙箱进程

| 方法                                              | 功能                    | 依赖                                       | Python SDK |
| ------------------------------------------------- | ----------------------- | ------------------------------------------ | ---------- |
| `command/exec`                                    | 有沙箱的一次性命令      | `permissionProfile` 或遗留 `sandboxPolicy` | **无**     |
| `command/exec/write`                              | 写 stdin / 关 stdin     | 客户端提供的 `processId`                   | **无**     |
| `command/exec/resize`                             | 调 PTY 大小             | PTY 会话                                   | **无**     |
| `command/exec/terminate`                          | 终止会话                | `processId`                                | **无**     |
| `process/spawn` **实验性**                        | 无沙箱本机进程          | `experimentalApi`；绝对 `cwd`              | **无**     |
| `process/writeStdin` **实验性**                   | 写 stdin                | `processHandle`                            | **无**     |
| `process/resizePty` **实验性**                    | 调 PTY                  | `processHandle`                            | **无**     |
| `process/kill` **实验性**                         | 杀进程                  | `processHandle`                            | **无**     |
| `thread/backgroundTerminals/clean` **实验性**     | 清 thread 全部后台终端  | 已加载 thread                              | **无**     |
| `thread/backgroundTerminals/list` **实验性**      | 列出后台终端            | 已加载 thread                              | **无**     |
| `thread/backgroundTerminals/terminate` **实验性** | 按 id 终止              | 已加载 thread                              | **无**     |
| `windowsSandbox/setupStart`                       | 开始 Windows 沙箱安装   | Windows                                    | **无**     |
| `windowsSandbox/readiness`                        | 读 Windows 沙箱就绪状态 | Windows                                    | **无**     |

Agent 在 turn 里跑的沙箱命令 **会执行**（走 `item/commandExecution*`），只是没有独立 `command/exec` 封装。

---

## 12. 文件系统 / 搜索

| 方法                                       | 功能             | 依赖         | Python SDK |
| ------------------------------------------ | ---------------- | ------------ | ---------- |
| `fs/readFile`                              | 读绝对路径文件   | 路径必须绝对 | **公开**（`codex.fs_read_file`） |
| `fs/writeFile`                             | 写文件           | 同上         | **公开**（`codex.fs_write_file`） |
| `fs/createDirectory`                       | 建目录           | 同上         | **公开**（`codex.fs_create_directory`） |
| `fs/getMetadata`                           | 元数据           | 同上         | **公开**（`codex.fs_get_metadata`） |
| `fs/readDirectory`                         | 列目录           | 同上         | **公开**（`codex.fs_read_directory`） |
| `fs/remove`                                | 删除             | 同上         | **公开**（`codex.fs_remove`） |
| `fs/copy`                                  | 复制             | 同上         | **公开**（`codex.fs_copy`） |
| `fs/watch`                                 | 监视变更         | `watchId`    | **公开**（`codex.fs_watch` → `FsWatchHandle`；SDK 分期仍要求 `experimental_api`） |
| `fs/unwatch`                               | 停止监视         | `watchId`    | **公开**（`codex.fs_unwatch`；SDK 分期仍要求 `experimental_api`） |
| `fuzzyFileSearch`                          | 一次性模糊搜文件 | 遗留仍可用   | **公开**（`codex.fuzzy_file_search`） |
| `fuzzyFileSearch/sessionStart` **实验性**  | 开始搜索会话     | —            | **公开**（`codex.experimental.fuzzy_file_search_session_start`） |
| `fuzzyFileSearch/sessionUpdate` **实验性** | 更新查询         | —            | **公开**（`codex.experimental.fuzzy_file_search_session_update`） |
| `fuzzyFileSearch/sessionStop` **实验性**   | 停止会话         | —            | **公开**（`codex.experimental.fuzzy_file_search_session_stop`） |

这是 **host 文件系统** RPC，不是模型工具。模型改文件走 turn 里的 `fileChange`（SDK 经 turn 流可见，无单独 API）。

---

## 13. Goal / Queue / Memory / Project

| 方法                                | 功能                    | 依赖                         | Python SDK                                                         |
| ----------------------------------- | ----------------------- | ---------------------------- | ------------------------------------------------------------------ |
| `thread/goal/set`                   | 创建 / 更新持久化目标   | 已物化 thread；子 agent 拒绝 | **公开**（`thread.goal_set`）                                              |
| `thread/goal/get`                   | 读当前 goal             | 子 agent 也允许              | **公开**（`thread.goal_get`）                                              |
| `thread/goal/clear`                 | 清除 goal               | 子 agent 拒绝                | **公开**（`thread.goal_clear`）                                            |
| `thread/queue/add` **实验性**       | 排队后续用户消息        | 每 thread 最多 100 条        | **公开**（`thread.queue_add`）                                             |
| `thread/queue/list` **实验性**      | 列队列                  | —                            | **公开**（`thread.queue_list`）                                            |
| `thread/queue/update` **实验性**    | 改排队项                | —                            | **公开**（`thread.queue_update`）                                          |
| `thread/queue/delete` **实验性**    | 删排队项                | —                            | **公开**（`thread.queue_delete`）                                          |
| `thread/queue/reorder` **实验性**   | 重排                    | —                            | **公开**（`thread.queue_reorder`）                                         |
| `thread/queue/start` **实验性**     | 空闲时启动队头          | —                            | **公开**（`thread.queue_start`）                                           |
| `thread/memoryMode/set` **实验性**  | 记忆资格                | `CODEX_HOME/memories`        | **公开**（`thread.memory_mode_set`）                                       |
| `memory/reset` **实验性**           | 清空 memories 目录      | 同上                         | **公开**（`codex.experimental.memory_reset`）                              |
| `thread/settings/update` **实验性** | 改下一轮设置，不开 turn | 已加载 thread                | **公开**（`thread.settings_update`）                                       |
| `project/list` **实验性**           | 列 project              | SQLite                       | **公开**（`codex.experimental.project_list`）                              |
| `project/read` **实验性**           | 读 project              | —                            | **公开**（`codex.experimental.project_read`）                              |
| `project/create` **实验性**         | 创建                    | 幂等 key                     | **公开**（`codex.experimental.project_create`）                            |
| `project/import` **实验性**         | 导入并分配 thread       | 幂等 key                     | **公开**（`codex.experimental.project_import`）                            |
| `project/update` **实验性**         | 更新                    | —                            | **公开**（`codex.experimental.project_update`）                            |
| `project/move` **实验性**           | 调整顺序                | —                            | **公开**（`codex.experimental.project_move`）                              |
| `project/delete` **实验性**         | 删除分配（不删 thread） | —                            | **公开**（`codex.experimental.project_delete`）                            |
| `threadSection/list`                | 列分组                  | —                            | **公开**（`codex.thread_section_list`）                                    |
| `threadSection/create`              | 创建分组                | —                            | **公开**（`codex.thread_section_create`）                                  |
| `threadSection/update`              | 重命名 / 外观           | pinned 不可改                | **公开**（`codex.thread_section_update`）                                  |
| `threadSection/delete`              | 删除分组                | pinned 不可删                | **公开**（`codex.thread_section_delete`）                                  |

---

## 14. Realtime / Review / Remote / Environment

| 方法                                      | 功能                        | 说明               | Python SDK |
| ----------------------------------------- | --------------------------- | ------------------ | ---------- |
| `thread/realtime/start` **实验性**        | 启动 realtime 会话          | 语音 / WebRTC      | **无**     |
| `thread/realtime/appendAudio` **实验性**  | 追加音频                    | —                  | **无**     |
| `thread/realtime/appendText` **实验性**   | 追加文本                    | —                  | **无**     |
| `thread/realtime/appendSpeech` **实验性** | 追加待说文本                | —                  | **无**     |
| `thread/realtime/stop` **实验性**         | 停止会话                    | —                  | **无**     |
| `thread/realtime/listVoices` **实验性**   | 列声音                      | —                  | **无**     |
| `thread/timeline/list` **实验性**         | 分页 turn + realtime 时间线 | —                  | **无**     |
| `review/start`                            | 代码审查                    | 内联或 detached    | **无**     |
| `remoteControl/enable` **实验性**         | 开远程控制                  | Unix daemon / 桌面 | **无**     |
| `remoteControl/disable` **实验性**        | 关远程控制                  | —                  | **无**     |
| `remoteControl/status/read` **实验性**    | 读状态                      | —                  | **无**     |
| `remoteControl/pairing/start` **实验性**  | 开始配对                    | —                  | **无**     |
| `remoteControl/pairing/status` **实验性** | 轮询配对                    | —                  | **无**     |
| `remoteControl/client/list` **实验性**    | 列控制器设备                | —                  | **无**     |
| `remoteControl/client/revoke` **实验性**  | 撤销设备                    | —                  | **无**     |
| `environment/add` **实验性**              | 注册远程 exec 环境          | —                  | **无**     |
| `environment/info` **实验性**             | 读环境信息                  | —                  | **无**     |
| `environment/status` **实验性**           | 读连接状态                  | —                  | **无**     |

---

## 15. 其它

| 方法                                 | 功能                            | Python SDK |
| ------------------------------------ | ------------------------------- | ---------- |
| `server/diagnostics` **实验性**      | 进程内存、仪表                  | **无**     |
| `feedback/upload`                    | 反馈 + 日志                     | **无**     |
| `hooks/list`                         | 发现 hooks                      | **无**     |
| `getConversationSummary` **v1 遗留** | 会话摘要                        | **无**     |
| `getAuthStatus` **v1 遗留**          | 鉴权状态（请用 `account/read`） | **无**     |
| `gitDiffToRemote` **v1 遗留**        | 相对远程 diff                   | **无**     |
