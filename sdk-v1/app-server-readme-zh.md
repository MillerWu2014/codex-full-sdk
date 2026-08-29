# codex-app-server

> 本文是 [README.md](../codex/codex-rs/app-server/README.md) 的中文译本。协议字段名、方法名、错误码与 JSON 示例以英文原文为准。

`codex app-server` 是 Codex 用来驱动富交互界面的接口，例如 [Codex VS Code 扩展](https://marketplace.visualstudio.com/items?itemName=openai.chatgpt)。

## 目录

- [协议](#协议)
- [消息 Schema](#消息-schema)
- [核心原语](#核心原语)
- [生命周期概览](#生命周期概览)
- [初始化](#初始化)
- [API 总览](#api-总览)
- [事件](#事件)
- [审批](#审批)
- [Skills](#skills)
- [Apps](#apps)
- [鉴权端点](#鉴权端点)
- [实验性 API 选择加入](#实验性-api-选择加入)

## 协议

与 [MCP](https://modelcontextprotocol.io/) 类似，`codex app-server` 使用 JSON-RPC 2.0 消息进行双向通信（线上省略 `"jsonrpc":"2.0"` 头）。

支持的传输方式：

- stdio（`--stdio` 或 `--listen stdio://`，默认）：换行分隔的 JSON（JSONL）
- websocket（`--listen ws://IP:PORT`）：每个 websocket 文本帧一条 JSON-RPC 消息（**实验性 / 不受支持**）
- unix socket（`--listen unix://` 或 `--listen unix://PATH`）：通过 `$CODEX_HOME/app-server-control/app-server-control.sock` 或自定义 socket 路径建立 websocket 连接，使用标准 HTTP Upgrade 握手
- off（`--listen off`）：不暴露本地传输

使用 `--listen ws://IP:PORT` 时，同一监听器还提供基础 HTTP 健康检查：

- `GET /readyz` 在监听器开始接受新连接后返回 `200 OK`。
- `GET /healthz` 在没有 `Origin` 头时返回 `200 OK`。
- 任何带有 `Origin` 头的请求都会被拒绝，返回 `403 Forbidden`。

Websocket 传输目前是实验性的，且不受支持。不要在生产负载中依赖它。

传入 `--code-mode-host URL`，可将本 app-server 进程连接到远程 code-mode host，而不是启动本地 host。gRPC 请使用不含路径或查询串的根 `http://` 或 `https://` URL。远程 host 需要 `code_mode_host` 功能。这条出站连接与 `--listen` 相互独立，并由该进程的各 thread 共享。

unix socket 传输面向本地 app-server 控制面客户端。`codex app-server proxy` 默认会向 `$CODEX_HOME/app-server-control/app-server-control.sock` 打开恰好一条原始流连接；若提供 `--sock PATH` 则连到该路径，并在该 socket 与 stdin/stdout 之间代理字节。被代理的流先承载 websocket 的 HTTP Upgrade 握手，随后是 websocket 帧。

追踪 / 日志输出：

- `RUST_LOG` 控制日志过滤与详细程度。
- 设置 `LOG_FORMAT=json`，将 app-server 追踪日志以 JSON 形式写入 `stderr`（每行一个事件）。

背压行为：

- 服务器在传输入口、请求处理与出站写入之间使用有界队列。
- 当请求入口饱和时，新请求会被拒绝，JSON-RPC 错误码为 `-32001`，消息为 `"Server overloaded; retry later."`。
- 客户端应将其视为可重试，并使用带抖动的指数退避。

## 消息 Schema

目前可用 `codex app-server generate-ts` 导出 TypeScript 版 schema，或用 `codex app-server generate-json-schema` 导出 JSON Schema 包。每次输出都与你运行该命令时所用的 Codex 版本绑定，因此生成产物保证与该版本匹配。

```
codex app-server generate-ts --out DIR
codex app-server generate-json-schema --out DIR
```

## 核心原语

API 暴露三个顶层原语，表示用户与 Codex 的一次交互：

- **Thread**：用户与 Codex agent 的一段对话。每个 thread 包含多个 turn。
- **Turn**：对话中的一轮，通常以用户消息开始、以 agent 消息结束。每个 turn 包含多个 item。
- **Item**：作为该 turn 一部分的用户输入与 agent 输出，会被持久化并作为后续对话的上下文。例如用户消息、agent 推理、agent 消息、shell 命令、文件编辑等。

用 thread API 创建、列出或归档对话。用 turn API 推进对话，并通过 turn 通知流式获取进度。

## 生命周期概览

- 每个连接初始化一次：打开传输连接后立即发送带客户端元数据的 `initialize` 请求，然后发出 `initialized` 通知。握手完成前，该连接上的任何其他请求都会被拒绝。
- 启动（或恢复）thread：调用 `thread/start` 打开新对话。响应返回 thread 对象，你还会收到 `thread/started` 通知。若要继续已有对话，改为用其 ID 调用 `thread/resume`。若要从已有对话分叉，调用 `thread/fork`，会创建带有复制历史的新 thread id。与 `thread/start` 一样，`thread/fork` 也接受 `ephemeral: true`，用于内存中的临时 thread。
  返回的 `thread.ephemeral` 标志告诉你该会话是否有意只存在于内存中；为 `true` 时，`thread.path` 为 `null`。
- 开始一轮 turn：要发送用户输入，对目标 `threadId` 调用 `turn/start` 并带上用户输入。可选字段可覆盖 model、cwd、sandbox 策略或实验性 `permissions` 配置文件选择、审批策略、审批审查器等。该调用立即返回新的 turn 对象。当该 turn 真正开始运行时，app-server 会发出 `turn/started`。
- 流式事件：`turn/start` 之后持续从 stdout 读取 JSON-RPC 通知。你会看到 `item/started`、`item/completed`、诸如 `item/agentMessage/delta` 的增量、工具进度等。它们表示流式模型输出以及任何副作用（命令、工具调用、推理笔记）。
- 结束 turn：当模型完成（或通过 `turn/interrupt` 中断该 turn）时，服务器发送 `turn/completed`，带有最终 turn 状态和 token 用量。

## 初始化

客户端必须在每个传输连接上、调用任何其他方法之前发送一次 `initialize` 请求，然后用 `initialized` 通知确认。服务器返回它将向上游服务出示的 user agent 字符串、服务器 Codex 主目录 `codexHome`，以及描述 app-server 运行时目标的 `platformFamily` 和 `platformOs` 字符串；初始化前发出的后续请求会收到 `"Not initialized"` 错误，同一连接上重复的 `initialize` 会收到 `"Already initialized"` 错误。

`initialize.params.capabilities` 还支持通过 `optOutNotificationMethods` 按连接选择退出通知，这是要为该连接抑制的精确方法名列表。匹配是精确匹配（无通配符 / 前缀）。未知方法名会被接受并忽略。

客户端在初始化时声明支持的 MCP 扩展。对于 OpenAI 扩展表单，客户端必须处理请求信封，包括对不支持字段类型的回退。`mcpServerOpenaiFormElicitation: true` 仍是声明 `openai/form` 扩展的遗留别名。

```json
{
  "capabilities": {
    "extensions": {
      "openai/form": {},
      "io.modelcontextprotocol/ui": {
        "mimeTypes": ["text/html;profile=mcp-app"]
      }
    }
  }
}
```

App-server 会完整保留 `io.modelcontextprotocol/ui` 下的值，而不是推导出一个 WebView 布尔值，以便客户端可以声明额外支持的 MIME 类型以及未来的扩展设置。MCP 扩展配置文件在 Codex 会话由 `thread/start`、`thread/resume` 或 `thread/fork` 创建时固定。Codex 在下游 MCP `initialize` 请求中声明该配置文件；它不会在单个工具调用元数据中重复。该已加载会话中的每一轮 turn 以及直接 MCP 工具调用因此都使用同一初始化配置文件。另一个 app-server 连接不能通过稍后开始一轮 turn 来改变它。子 agent 会话继承同一扩展配置文件。

构建在 `codex app-server` 之上的应用应通过 `clientInfo` 参数标识自己。

**重要**：`clientInfo.name` 用于在 OpenAI Compliance Logs Platform 中识别客户端。如果你正在开发面向企业使用的新 Codex 集成，请联系我们将其加入已知客户端列表。更多背景：https://chatgpt.com/admin/api-reference#tag/Logs:-Codex

示例（来自 OpenAI 官方 VSCode 扩展）：

```json
{
  "method": "initialize",
  "id": 0,
  "params": {
    "clientInfo": {
      "name": "codex_vscode",
      "title": "Codex VS Code Extension",
      "version": "0.1.0"
    }
  }
}
```

带通知选择退出的示例：

```json
{
  "method": "initialize",
  "id": 1,
  "params": {
    "clientInfo": {
      "name": "my_client",
      "title": "My Client",
      "version": "0.1.0"
    },
    "capabilities": {
      "experimentalApi": true,
      "optOutNotificationMethods": ["thread/started", "item/agentMessage/delta"]
    }
  }
}
```

## API 总览

- `server/diagnostics` — 实验性；读取进程本地内存度量以及已注册的诊断仪表。
- `thread/start` — 创建新 thread；发出 `thread/started`（包含当前 `thread.status`），并自动订阅该 thread 的 turn/item 事件。实验性 `projectId` 将持久 thread 分配到已有 project；临时 thread 会在实时响应中暴露相同的 project 身份，但不会创建可存储 / 可列出的分配。实验性 `historyMode` 选择持久化历史契约：省略时，若活动 thread store 支持 `thread/turns/list` 和 `thread/items/list`，持久 thread 使用 `"paginated"`，而临时 thread 以及不支持该能力的 store 使用 `"legacy"`。当请求包含 `cwd` 且解析出的 sandbox 为 `workspace-write` 或完全访问时，app-server 还会在用户 `config.toml` 中将该 project 标记为受信任。在清空当前会话后启动替换 thread 时，传入 `sessionStartSource: "clear"`，使 `SessionStart` hooks 收到 `source: "clear"` 而不是默认的 `"startup"`。实验性 `allowProviderModelFallback` 允许由权威静态模型目录支撑的 provider 将不可用的请求 `model` 替换为目录默认模型；动态或缓存目录会保留请求的模型。实验性 `runtimeWorkspaceRoots` 提供 app-server 创建默认环境选择时使用的运行时工作区根；路径必须是绝对路径。权限方面，优先按 id 选择实验性 `permissions` 配置文件；遗留的 `sandbox` 简写仍被接受，但不能与 `permissions` 同时使用。已弃用的实验性 `multiAgentMode` 会被忽略；主动多 agent 行为请使用 Ultra reasoning effort。实验性 `environments` 为该 thread 上的 turn 选择粘性执行环境；省略则使用服务器默认，传入 `[]` 禁用环境，或传入带每环境 `cwd` 以及可选的环境原生 `runtimeWorkspaceRoots` 的显式环境 id。显式环境会忽略顶层 roots；省略的每环境 roots 默认使用该环境的 `cwd`，而空列表显式选择无 roots。实验性 `selectedCapabilityRoots` 使用环境原生绝对路径选择环境拥有的 plugin 或独立 skill 根。这些根下发现的 skills 通过拥有该根的环境列出和读取。所选 plugin 声明的 stdio MCP server 在该环境中启动，HTTP MCP 连接使用该环境的 HTTP 客户端。
- `thread/resume` — 按 id 重新打开已有 thread，使后续 `turn/start` 追加到其上。接受与 `thread/start` 相同的权限覆盖规则。
- `thread/fork` — 通过复制已存储历史，将已有 thread 分叉为新 thread id；传入可选 `lastTurnId` 时，仅复制到该 turn（含）为止，并丢弃分叉中更晚的 turn。进行中的 `lastTurnId` 边界会被拒绝。实验性 `beforeTurnId` 改为严格复制该引用 turn 之前的历史，即使该 turn 正在进行中，且不能与 `lastTurnId` 同时使用。若两个边界都为 null，而源 thread 正处于 turn 中，分叉会记录与 `turn/interrupt` 相同的中断标记，而不是继承未标记的部分 turn 后缀。已知时，返回的 `thread.forkedFromId` 指向源 thread。接受 `ephemeral: true` 用于内存中的临时分叉，发出 `thread/started`（包含当前 `thread.status`），并自动订阅新 thread 的 turn/item 事件。若客户端计划通过 `thread/turns/list` 分页获取分叉历史、而不是立即接收完整 turn 数组，可传入 `excludeTurns: true`。实验性 `deferGoalContinuation: true` 会把源 thread 的当前 goal 带入分叉，并在自动续跑恢复前先跑一轮显式 turn。延迟的 goal 续跑会持久化到该 turn 开始为止，且不能与 `ephemeral: true` 同时使用。接受与 `thread/start` 相同的权限覆盖规则。
- `thread/start`、`thread/resume` 和 `thread/fork` 的响应包含遗留 `sandbox` 兼容投影。`instructionSources` 使用每个源环境的原生绝对路径语法列出已加载的指令文件，包括从远程环境加载的文件。实验性客户端可以读取 thread 作用域运行时根 `runtimeWorkspaceRoots`，以及已知时命名或隐式内置配置文件身份 / 来源的 `activePermissionProfile`。它们已弃用的实验性 `multiAgentMode` 字段以及对应 thread 设置始终报告 `explicitRequestOnly`；Ultra reasoning effort 才是主动多 agent 行为的来源。
- `thread/list` — 分页浏览已存储 thread；支持基于 cursor 的分页以及可选的 `modelProviders`、`sourceKinds`、`archived`、`sectionId`、`cwd` 和 `searchTerm` 过滤。实验性 `projectId` 过滤单个 project，而 `null` 选择未分配的 thread。列出某个 section 并按其持久化的手动顺序排列时，将 `sortKey` 设为 `"section_position"`。实验性客户端可用 `parentThreadId` 获取直接派生的子 thread，或用 `ancestorThreadId` 获取任意深度的派生后代；这两个过滤器互斥。Review 和 Guardian thread 不包含在内，因为它们不参与该 spawn-edge 生命周期。每个返回的 `thread` 包含 `status`（`ThreadStatus`），当 thread 当前未加载时默认为 `notLoaded`。子 agent thread 在已知直接父级时还包含 `parentThreadId`。
- `project/list`、`project/read`、`project/create`、`project/import`、`project/update`、`project/move` 和 `project/delete` — 实验性的、基于 SQLite 的 project API。Project 具有服务器生成的规范 ID、持久化的手动位置、有序绝对根，以及不透明字符串元数据包。`project/move` 将某个 project 放到另一个 project 之前，或在 `beforeProjectId` 为 `null` 时追加到末尾。创建和导入需要不透明的 `idempotencyKey`；普通创建应由客户端生成 UUID，迁移时可使用稳定的、带命名空间的遗留 ID。重用某个 key 会返回原始 project，而不发出通知或重复 thread 分配，并且删除后 key 仍被保留。导入可以原子地分配已有 thread ID。删除会清除分配，但从不删除 thread、目录或文件。
- `project/changed` 和 `thread/project/updated` — 在已提交的 project 或分配变更后发出的实验性通知。请用 `project/list` 和 `thread/list` 重新连接以恢复权威状态。
- `threadSection/list` — 分页浏览独立持久化的 thread section，包括其显示名称以及可选的 `appearance`（`icon` 和 `color`）。
- `threadSection/create` — 创建带有服务器生成 UUID、非空显示名称以及可选 `appearance` 的持久自定义 section；返回其 `section`。
- `threadSection/update` — 重命名已有自定义 section，并可选择替换其 `appearance`；省略 appearance 以保留它，或传入 `null` 以清除。内置 pinned section 不能更新。
- `threadSection/delete` — 删除已有自定义 section，并原子地将其成员 thread 退回未分组列表；返回 `{}`。内置 pinned section 不能删除。
- `thread/loaded/list` — 列出当前已加载到内存中的 thread id。
- `thread/read` — 按 id 读取已存储 thread 而不恢复它；可通过 `includeTurns` 选择是否包含 turn。返回的 `thread` 包含 `status`（`ThreadStatus`），当 thread 当前未加载时默认为 `notLoaded`。对于已加载 thread，实验性客户端可用 `canAcceptDirectInput` 判断是否接受 `turn/start` 和 `turn/steer`（父级拥有的 Multi-Agent V2 子 agent 为 `false`）；未加载的已存储 thread 在该能力不可用时报告 `null`。
- `thread/turns/list` — 分页浏览已存储 thread 的 turn 历史而不恢复它；支持带 `sortDirection`、`itemsView`、`nextCursor` 和 `backwardsCursor` 的基于 cursor 的分页。
- `thread/items/list` — 分页浏览已持久化的 thread item 而不恢复该 thread。传入 `turnId` 可将结果限制到一轮 turn，或省略以跨 thread 分页 item。活动 thread store 必须支持 item 分页。
- `thread/searchOccurrences` — 实验性；在一个分页 thread 中查找可见用户消息以及摘要选出的最终助手消息里的字面、不区分大小写匹配。
- `thread/metadata/update` — 在 sqlite 中修补已存储 thread 元数据；支持更新持久化的 `gitInfo` 字段以及实验性 `projectId`，然后返回刷新后的 `thread`。省略 `projectId` 以保留分配，传入空字符串以清除它。
- `thread/section/move` — 原子地将 thread 移入由 `sectionId` 标识的 section，放到另一个 thread 之前，或在 `beforeThreadId` 为 `null` 时放到末尾。同一 section 内重排会保留 `sectionEnteredAt`；进入不同 section 会重置它。将 `sectionId` 设为 `null` 可将 thread 从其 section 中移除。成功时返回 `{}`。
- `thread/settings/update` — 实验性；对已加载 thread 的下一轮设置排队部分更新，而不开始一轮 turn 或添加 transcript item。省略的字段保持设置不变；`serviceTier: null` 清除该档位；已弃用的 `multiAgentMode` 会被忽略，而 Ultra reasoning effort 启用主动多 agent 行为；`sandboxPolicy` 和 `permissions` 不能同时使用。父级拥有的 Multi-Agent V2 子 agent 拒绝直接设置更新。更新被接受时返回 `{}`，仅当有效设置实际发生变化时才发出带有完整有效设置的 `thread/settings/updated`。`turn/start` 的设置覆盖在改变已存储设置时发出相同通知。
- `thread/memoryMode/set` — 实验性；将 thread 的持久化 memory 资格设为 `"enabled"` 或 `"disabled"`，可用于已加载 thread 或已存储 rollout；成功时返回 `{}`。
- `memory/reset` — 实验性；清空当前 `CODEX_HOME/memories` 目录，并重置 sqlite 中持久化的 memory stage 数据，同时保留已有 thread memory 模式；成功时返回 `{}`。
- `thread/goal/set` — 为已物化 thread 创建或更新唯一持久化 goal；返回当前 goal 并发出 `thread/goal/updated`。父级拥有的 Multi-Agent V2 子 agent 拒绝 goal 更新，包括未加载时。
- `thread/goal/get` — 获取已物化 thread 的当前持久化 goal；不存在 goal 时返回 `goal: null`。即使是父级拥有的 Multi-Agent V2 子 agent 也可用。
- `thread/goal/clear` — 清除已物化 thread 的当前持久化 goal；返回是否移除了 goal，并在状态变化时发出 `thread/goal/cleared`。父级拥有的 Multi-Agent V2 子 agent 拒绝清除 goal，包括未加载时。
- `thread/goal/updated` — 每当 thread goal 变化时发出的通知；包含完整的当前 goal。
- `thread/goal/cleared` — 每当 thread goal 被移除时发出的通知。
- `thread/queue/add` — 实验性；持久化一条用户 turn，以便 thread 下次空闲时自动 FIFO 提交。
- `thread/queue/list` — 实验性；返回 thread 排队 turn 的一页。
- `thread/queue/update` — 实验性；编辑排队 turn，同时保留其稳定提交 ID、客户端消息 ID 和位置。
- `thread/queue/delete` — 实验性；按提交 ID 移除一条排队 turn。
- `thread/queue/reorder` — 实验性；替换 thread 排队 turn 的顺序。
- `thread/queue/start` — 实验性；在 thread 空闲时启动队列头或选定的排队提交。
- `thread/queue/changed` — 实验性通知，带有已变化的 `threadId`。
- `thread/settings/updated` — 实验性通知，在已加载 thread 的有效下一轮设置变化时发给已订阅客户端；包含 `threadId` 和完整的 `threadSettings`。
- `thread/status/changed` — 已加载 thread 的状态变化时发出的通知（`threadId` + 新 `status`）。
- `thread/archive` — 将该 thread 的 rollout 文件移入归档目录，并尝试移动任何派生后代 thread 的 rollout 文件；成功时返回 `{}`，并为每个已归档 thread 发出 `thread/archived`。
- `thread/delete` — 硬删除活动或已归档 thread 以及任何派生后代 thread；成功时返回 `{}`，并为每个已删除 thread 发出 `thread/deleted`。
- `thread/unsubscribe` — 使本连接取消订阅 thread 的 turn/item 事件。若这是最后一个订阅者，服务器仍保持 thread 已加载，仅在它连续 30 分钟没有订阅者也没有 thread 活动后才卸载，运行 `SessionEnd` hooks，然后发出 `thread/closed`。
- `thread/name/set` — 为已加载 thread 或持久化 rollout 设置或更新面向用户的名称；成功时返回 `{}`，并向已初始化、已选择加入的客户端发出 `thread/name/updated`。Thread 名称不必唯一；按名称查找会解析到最近更新的 thread。
- `thread/unarchive` — 将已归档 rollout 文件移回 sessions 目录；成功时返回恢复后的 `thread` 并发出 `thread/unarchived`。
- `thread/compact/start` — 触发 thread 的对话历史压缩；立即返回 `{}`，进度通过标准 turn/item 通知流式发送。父级拥有的 Multi-Agent V2 子 agent 拒绝直接压缩请求。
- `thread/shellCommand` — 对 thread 运行用户发起的 `!` shell 命令；以完全访问、无沙箱方式运行，而不是继承 thread sandbox 策略。父级拥有的 Multi-Agent V2 子 agent 拒绝直接 shell 命令。立即返回 `{}`，进度通过标准 turn/item 通知流式发送，任何活动 turn 会在其消息流中收到格式化输出。
- `thread/approveGuardianDeniedAction` — 手动批准先前被 Guardian 拒绝的操作；父级拥有的 Multi-Agent V2 子 agent 拒绝直接审批。不影响对服务器发出的待处理审批请求的回复。
- `thread/backgroundTerminals/clean` — 终止某个 thread 的所有正在运行的后台终端（实验性；需要 `capabilities.experimentalApi`）；清理请求被接受时返回 `{}`。
- `thread/backgroundTerminals/list` — 列出已加载 thread 的正在运行的后台终端（实验性；需要 `capabilities.experimentalApi`）；返回带有运行中终端 id 的 `data`。
- `thread/backgroundTerminals/terminate` — 按 app-server `processId` 终止一个正在运行的后台终端（实验性；需要 `capabilities.experimentalApi`）；返回是否终止了某个进程。
- `thread/rollback` — 已弃用，即将移除。从 agent 的内存上下文中丢弃最后 N 轮 turn，并在 rollout 中持久化 rollback 标记，使未来恢复能看到被裁剪的历史；成功时返回更新后的 `thread`（`turns` 已填充）。分页 thread 不支持 rollback。父级拥有的 Multi-Agent V2 子 agent 拒绝直接 rollback 请求。
- `thread/revert` — 将已加载分页 thread 的持久历史替换为严格位于 `beforeTurnId` 之前的前缀，同时保留其 thread id。该操作必要时会中断活动 turn，使更旧的 rollout 文件保持不可变，重新加载 thread，返回带有空 `turns` 以及分页 cursor 的更新后 thread 元数据，并发出 `thread/reverted`。它不会还原本地文件更改。父级拥有的 Multi-Agent V2 子 agent 拒绝直接 revert 请求。
- `turn/start` — 向 thread 添加用户输入或命名的独立 function-call 输出，并开始 Codex 生成；以初始 `turn` 对象响应，并流式发送 `turn/started`、`item/*` 和 `turn/completed` 通知。对于独立输出，提供带空 `input` 数组的 `toolOutput`。可选 `turnTrigger` 分类是谁或什么开始了新 turn，并作为 `turn_trigger` 发送到 Responses 请求元数据中；若请求是在引导活动 turn，则被忽略。`clientUserMessageId` 可选；提供时，对应的 `userMessage` item 会将其回显为 `clientId`。实验性 `runtimeWorkspaceRoots` 为新解析的环境选择提供默认根。显式 `environments[].runtimeWorkspaceRoots` 用环境原生绝对路径覆盖该回退。权限覆盖优先按 id 选择实验性 `permissions` 配置文件；遗留 `sandboxPolicy` 字段仍被接受，但不能与 `permissions` 同时使用。对于 `collaborationMode`，`settings.developer_instructions: null` 表示“对该所选模式使用内置指令”。已弃用的实验性 `multiAgentMode` 会被忽略；Ultra reasoning effort 选择主动行为。父级拥有的 Multi-Agent V2 子 agent 拒绝直接 turn。
- `thread/inject_items` — 将原始 Responses API item 追加到已加载 thread 的模型可见历史中，而不开始一轮 turn；成功时返回 `{}`。父级拥有的 Multi-Agent V2 子 agent 拒绝直接注入 item。
- `turn/settings/update` — 实验性；将窄范围的模型设置补丁发布到由 `threadId` 和 `turnId` 标识的精确实时任务，无论任务种类。需要 `step_model_switching`；返回 `status: "applied"` 或 `status: "targetUnavailable"`，若被拒绝则返回请求错误。未来 thread 设置以及已经捕获的 step 保持不变。父级拥有的 Multi-Agent V2 子 agent 拒绝直接设置更新。
- `turn/steer` — 向已经在进行中的常规 turn 添加用户输入，而不开始新 turn；返回接受该输入的活动 `turnId`。`clientUserMessageId` 可选；提供时，对应的 `userMessage` item 会将其回显为 `clientId`。Review 和手动压缩 turn 拒绝 `turn/steer`。父级拥有的 Multi-Agent V2 子 agent 拒绝直接引导。
- `turn/interrupt` — 按 `(thread_id, turn_id)` 请求取消进行中的 turn；成功为空 `{}` 响应，该 turn 以 `status: "interrupted"` 结束。父级拥有的 Multi-Agent V2 子 agent 也可用。
- `thread/realtime/start` — 启动 thread 作用域的 realtime 会话（实验性）；传入 `outputModality: "text"` 或 `outputModality: "audio"` 以选择模型输出，可选传入 `model` 和 `version` 仅覆盖本次会话的已配置 realtime 选择，传入 `includeStartupContext: false` 可省略 Codex 生成的启动上下文，并可选传入 `initialItems`，在会话创建时用带完整 role 的文本消息为 V3 播种。传入 `realtimeStartInstructions` 和 `realtimeEndInstructions`，控制本会话开始和结束时给予 backing Codex 模型的 developer 指令。版本 `"v1"` 使用遗留 Bidi `conversation.handoff.*`，`"v2"` 使用 Realtime Voice API，`"v3"` 保留 V1 Codex Voice 行为同时使用 Frameless Bidi `delegation.*`。对于 V3 自动 Codex 文本，`codexResponseHandoffMode` 接受 `"thinking"`（默认；所有输出使用无 channel 的 thinking 追加）、`"commentary"`（所有输出使用 commentary channel），或 `"bemTags"`（原始 BEM 信封选择 API channel：BEM `analysis` 和 `commentary` 使用 `commentary`，而 BEM `final` 以及无法解析的输出使用 `speakable`）。BEM 信封仍保留在追加文本中，供前端模型解释。V1 和 V2 忽略此设置。对于 V3，传入 `delegationAckFiller: false` 可抑制 Realtime API 的 delegation 确认填充词，或传入 `true` 以恢复它；省略该字段则保留 Realtime API 的默认值。V1 和 V2 忽略 `delegationAckFiller`。V3 handoff 不会前置遗留的 `"Agent Final Message"` 标签。传入 `clientManagedHandoffs: true` 可禁用自动 Codex 响应投递，从而只有客户端的显式 append 调用才会产生 handoff。传入 `codexResponsesAsItems: true` 改为将自动 Codex 响应作为 realtime conversation item 发送，并可选择传入 `codexResponseItemPrefix` 为这些 item 前置实验指令。返回 `{}` 并流式发送 `thread/realtime/*` 通知。省略 `transport` 使用 websocket 传输，或传入 `{ "type": "webrtc", "sdp": "..." }` 以从浏览器生成的 SDP offer 创建 Bidi WebRTC 会话；远端 answer SDP 作为 `thread/realtime/sdp` 发出。Conversation `version: "v2"` 请求对 WebRTC 仍不受支持。父级拥有的 Multi-Agent V2 子 agent 拒绝此请求。
- `thread/realtime/appendAudio` — 向活动 realtime 会话追加一段输入音频（实验性）；返回 `{}`。父级拥有的 Multi-Agent V2 子 agent 拒绝此请求。
- `thread/realtime/appendText` — 向活动 realtime 会话追加文本输入，必须带有 `user`、`developer` 或 `assistant` 的 `role`（实验性）；返回 `{}`。省略 `role` 的旧客户端默认为 `user`。父级拥有的 Multi-Agent V2 子 agent 拒绝此请求。
- `thread/realtime/appendSpeech` — 追加 realtime 模型应对用户说出的文本（实验性）；返回 `{}`。父级拥有的 Multi-Agent V2 子 agent 拒绝此请求。
- `thread/realtime/stop` — 停止该 thread 的活动 realtime 会话（实验性）；返回 `{}`。父级拥有的 Multi-Agent V2 子 agent 拒绝此请求。
- `thread/timeline/list` — 按 rollout 顺序一起分页普通 turn item、持久 realtime 事实以及 turn 边界（实验性）。条目标记为 `item`、`realtime`、`turnStarted` 或 `turnCompleted`。Turn 边界携带生命周期元数据，而不复制该 turn 的 item；已完成边界也覆盖被中断和失败的 turn。每次响应包含一个不透明的续页 cursor 以及 `activeRealtimeSessionAtPageStart`，使客户端无需加载更早 thread 历史即可渲染任意有界页面。同一 rollout 位置上的条目具有稳定顺序，并可跨页。现有 `thread/items/list` 保持不变。
- `review/start` — 为 thread 启动 Codex 的自动审查器；响应形状类似 `turn/start`。内联 review 发出带有 `enteredReviewMode` 和 `exitedReviewMode` item 的 `item/started`/`item/completed` 通知，以及包含审查内容的最终助手 `agentMessage`。分离式 review 在新的 review thread 上流动普通 turn item。父级拥有的 Multi-Agent V2 子 agent 拒绝内联和分离式 review。
- `command/exec` — 在服务器沙箱下运行单条命令，而不启动 thread/turn（便于工具和校验）。
- `command/exec/write` — 将 base64 解码后的 stdin 字节写入正在运行的 `command/exec` 会话，或关闭 stdin；返回 `{}`。
- `command/exec/resize` — 按 `processId` 调整正在运行的、基于 PTY 的 `command/exec` 会话大小；返回 `{}`。
- `command/exec/terminate` — 按 `processId` 终止正在运行的 `command/exec` 会话；返回 `{}`。
- `command/exec/outputDelta` — 为流式 `command/exec` 会话发出的、base64 编码的 stdout/stderr 块通知。
- `process/spawn` — 实验性；在 app server 所在主机上、不经过 Codex 沙箱地生成独立进程；进程启动后返回，并发出 `process/outputDelta` 和 `process/exited` 通知。
- `process/writeStdin` — 实验性；将 base64 解码后的 stdin 字节写入正在运行的 `process/spawn` 会话，或关闭 stdin；返回 `{}`。
- `process/resizePty` — 实验性；按 `processHandle` 调整正在运行的、基于 PTY 的 `process/spawn` 会话大小；返回 `{}`。
- `process/kill` — 实验性；按 `processHandle` 终止正在运行的 `process/spawn` 会话；返回 `{}`。
- `process/outputDelta` — 实验性；为流式 `process/spawn` 会话发出的、base64 编码的 stdout/stderr 块通知。
- `process/exited` — 实验性；当 `process/spawn` 会话退出时发出的通知。
- `fs/readFile` — 读取绝对文件路径并返回 `{ dataBase64 }`。
- `fs/writeFile` — 从 base64 编码的 `{ dataBase64 }` 写入绝对文件路径；返回 `{}`。
- `fs/createDirectory` — 创建绝对目录路径；`recursive` 默认为 `true`。
- `fs/getMetadata` — 返回绝对路径的元数据：`isDirectory`、`isFile`、`isSymlink`、`createdAtMs` 和 `modifiedAtMs`。
- `fs/readDirectory` — 列出绝对目录路径的直接子条目；每个条目包含 `fileName`、`isDirectory` 和 `isFile`，且 `fileName` 只是子名称，不是路径。
- `fs/remove` — 删除绝对文件或目录树；`recursive` 和 `force` 默认为 `true`。
- `fs/copy` — 在绝对路径之间复制；目录复制需要 `recursive: true`。
- `fs/watch` — 使本连接订阅某个绝对文件或目录路径以及调用方提供的 `watchId` 的文件系统变更通知；返回规范化后的 `path`。
- `fs/unwatch` — 停止发送先前 `fs/watch` 的通知；返回 `{}`。
- `fs/changed` — 当被监视路径变化时发出的通知，包含 `watchId` 和 `changedPaths`。
- `model/list` — 列出可用模型（设 `includeHidden: true` 以包含 `hidden: true` 的条目），带有模型声明的字符串 reasoning effort 选项（按目录预期进阶顺序）、可选 `modelSpecialty`、可空 `multiAgentVersion`（`disabled`、`v1` 或 `v2`）、`additionalSpeedTiers`、`serviceTiers`、可选 `defaultServiceTier`、可选遗留 `upgrade` 模型 id、可选 `upgradeInfo` 元数据（`model`、`upgradeCopy`、`modelLink`、`migrationMarkdown`、可空信息性 `retirementAt` Unix 时间戳），以及可选 `availabilityNux` 元数据。客户端应保留 `supportedReasoningEfforts` 数组顺序，而不是从 effort 名称推导顺序。
- `modelProvider/capabilities/read` — 读取当前配置的模型 provider 的 provider 级能力。
- `experimentalFeature/list` — 列出带阶段元数据（`beta`、`underDevelopment`、`stable` 等）、启用 / 默认启用状态以及 cursor 分页的功能开关。展示已有已加载 thread 的功能状态时传入 `threadId`，使 `enabled` 根据该 thread 刷新后的配置计算，包括该 thread cwd 的项目本地配置；若省略，服务器使用其默认配置解析上下文。对于非 beta 开关，`displayName`/`description`/`announcement` 为 `null`。
- `permissionProfile/list` — beta；列出可用权限配置文件 id，带可选显示 `description` 文本以及反映有效要求的 `allowed` 标志，使用 cursor 分页。当调用方需要将项目本地 `[permissions.<id>]` 条目包含在当前目录视图中时，传入 `cwd`。
- `experimentalFeature/enablement/set` — 修补当前支持的功能键的进程范围内存运行时功能启用状态。对每个功能，优先级为：cloud requirements > --enable <feature_name> > config.toml > experimentalFeature/enablement/set（新）> 代码默认。无效键会被忽略。
- `environment/add` — 实验性；按 `environmentId` 和 `execServerUrl` 添加或替换命名远程环境，供稍后由 `thread/start` 或 `turn/start` 选择；可选 `connectTimeoutMs` 覆盖 WebSocket 连接超时；返回 `{}`，且不改变默认环境。
- `environment/info` — 实验性；按 `environmentId` 连接到已配置环境，并返回其检测到的 `shell` 以及作为规范环境原生 `file:` URI 的默认 `cwd`。连接失败作为请求错误返回。
- `environment/status` — 实验性；读取某个已配置 `environmentId` 的当前状态。就绪的远程环境通过其现有 exec-server 连接探测，而不启动或重连环境；响应报告 `ready`、`pending`、`disconnected` 或 `unknown`。
- `thread/environment/connected` 和 `thread/environment/disconnected` — 实验性；报告 thread 启动后为所选环境观察到的 exec-server 连接转换。当前连接状态不会重放。
- `collaborationMode/list` — 列出可用协作模式预设（实验性，无分页）。内置预设不选择模型；Plan 预设选择 medium reasoning effort。该响应省略内置 developer 指令；客户端在设置模式时应传入 `settings.developer_instructions: null` 以使用 Codex 的内置指令，或显式提供自己的指令。
- `skills/list` — 为一个或多个 `cwd` 值列出 skills（可选 `forceReload`）。
- `skills/extraRoots/set` — 替换 app-server 进程运行时额外的独立 skill 根。这些根不会持久化；缺失目录会被接受，只是不加载任何 skill。
- `hooks/list` — 为一个或多个 `cwd` 值列出已发现的 hooks。
- `marketplace/add` — 从 HTTP(S) Git URL、SSH Git URL 或 GitHub `owner/repo` 简写添加远程 plugin marketplace，然后将其持久化到用户 marketplace 配置。返回已安装根路径以及该 marketplace 是否已经存在。
- `marketplace/remove` — 按名称从用户 marketplace 配置中移除已配置 marketplace，并在存在时删除其已安装 marketplace 根。
- `marketplace/upgrade` — 升级所有已配置的 Git plugin marketplace，或在提供 `marketplaceName` 时升级一个命名 marketplace。返回所选 marketplace 名称、已升级根以及每个 marketplace 的错误。
- `plugin/list` — 列出已发现的 plugin marketplace 和 plugin 状态，包括有效 marketplace 安装 / 鉴权策略元数据、`installPolicySource` 中可空的远程安装策略来源（`WORKSPACE_SETTING` 或 `IMPLICIT_CANONICAL_APP`）、远程 marketplace `version` 以及可用时本地物化的 `localVersion`、plugin `availability`（默认为 `AVAILABLE`，或上游被阻止的远程 plugin 为 `DISABLED_BY_ADMIN`）、无法解析或加载的 marketplace 文件的 fail-open `marketplaceLoadErrors` 条目，以及官方精选 marketplace 的尽力而为 `featuredPluginIds`。plugin list、installed、read 和 share-list 方法返回的每个 `PluginSummary` 都包含可空的 `disabledReason` 和 `eligiblePlanTypes`，保留 plugin 服务可用性元数据以及远程 plugin 的原始计划标识符，同时对本地 plugin 或更旧的远程响应返回 `null`。同样的摘要包含 `mustShowInstallationInterstitial`：远程服务值保留 `true` 或 `false`，而本地 plugin 以及省略该策略的远程响应返回 `null`。值为 `null` 时客户端应失败关闭。客户端可以显式请求远程 `workspace-directory`、`shared-with-me` 或 `created-by-me-remote` marketplace 种类。设 `forceRefetch: true` 可为请求的 marketplace 绕过基于 TTL 的远程目录缓存并等待新鲜数据；仅在成功获取后才替换缓存条目。当包含本地 marketplace 时，该请求还会在返回 marketplace 摘要前等待已配置 plugin 缓存完成协调。在 app-server 启动时，已有缓存目录在后台刷新期间仍可供 `plugin/list` 使用。`interface.category` 在存在时使用 marketplace 类别；否则回退到 plugin manifest 类别（**开发中；请勿从生产客户端调用**）。
- `plugin/search` — 直接搜索远程 plugin 服务，并将匹配的本地 marketplace plugin 合并到第一页结果。接受 `searchTerm`、可选 `global`、`workspace` 或 `personal` 范围、用于发现仓库 marketplace 的可选 `cwds`，以及可选 `cursor` 和 `limit`；`personal` 搜索用户拥有的 plugin。本地匹配使用 plugin 名称、显示名称和关键词，按不区分大小写和标点的相关性排序。全局搜索包含适用的内置本地 plugin，个人搜索包含其他本地 plugin，工作区搜索仍仅限远程，省略范围则包含所有本地 plugin。当远程全局目录处于活动状态时，它是权威的，并替换本地精选 marketplace。本地结果在 API-key 鉴权以及 `remote_plugin` 禁用时仍可用；在后一种情况下，省略范围和显式工作区搜索仍可查询远程工作区目录，而显式全局和个人搜索不会查询 plugin-service。第一页最多包含 100 个本地匹配，并且可以超过 `limit`；后续页面仅包含远程结果，上游分页 token 原样作为 `nextCursor` 传递。本地和远程副本按共享远程身份去重，远程摘要保留本地已安装状态。每个结果始终显式返回 `plugin.enabled: false`，包括已启用的本地 plugin、去重 plugin 以及后续仅远程页面；搜索报告发现元数据，而不是有效激活状态。用 `plugin/list` 或 `plugin/read` 判断 plugin 是否真正启用。当 `plugin_sharing` 禁用时，在获取远程页面后会省略共享 / 私有工作区结果（**开发中；请勿从生产客户端调用**）。
- `plugin/installed` — 列出已安装 plugin 行以及任何显式请求的本地安装建议 plugin 名称，而不获取更广泛的远程目录。远程行包含可空的 `installPolicySource` 和 `installedAt`（后端安装时间戳，Unix 秒）。`plugin/list`、`plugin/read` 和 `plugin/share/list` 也会返回 `installedAt`；对本地 plugin、未安装 plugin、默认安装的 plugin，以及不包含安装时间戳的更旧后端响应，它为 `null`。提及界面在需要 plugin 提及载荷而不是 plugin 页发现数据时，可以使用这个更窄的视图（**开发中；请勿从生产客户端调用**）。
- `plugin/read` — 按 `marketplacePath` 加 `pluginName` 读取一个 plugin，返回 marketplace 信息、列表风格的 `summary`、manifest 描述 / 界面元数据，以及捆绑的 skills/hooks/apps/MCP server 名称。远程 plugin 详情可包含来自目录的计划任务摘要；`scheduledTasks: null` 表示元数据不可用，而空数组表示目录未找到计划任务。远程 plugin 详情在可用时暴露远程目录提供的规范 `shareUrl`；对本地 plugin 或目录省略它时为 `null`。该字段与继续描述用户和工作区共享状态的 `summary.shareContext` 分开。对于拥有的工作区 plugin，`summary.shareContext.canPublishToWorkspace` 报告当前用户是否可将该 plugin 添加到工作区目录；`plugin/share/save` 在创建或更新共享后返回相同能力，任一值为 `null` 时客户端应失败关闭。当目录提供图标 URL 时，远程 skill 界面暴露 `iconSmallUrl` 和 `iconLargeUrl`。返回的 plugin skill 包含本地配置过滤后的当前 `enabled` 状态；捆绑 hooks 作为轻量声明摘要返回，键用于与 `hooks/list` 关联。用 `plugin/install` 的 `appsNeedingAuth` 驱动安装后鉴权，用 `app/list` 的 `isAccessible` 判断当前连接器可访问性（**开发中；请勿从生产客户端调用**）。
- `plugin/skill/read` — 按 `remoteMarketplaceName`、`remotePluginId` 和 `skillName` 按需读取远程 plugin skill markdown。这让客户端可以预览未安装远程 plugin 的 skills，而无需下载 plugin 包。
- `skills/changed` — 当被监视的本地 skill 文件变化时发出的通知。
- `app/installed` — 从上次提交的快照读取已安装连接器运行时状态，可选先刷新它。
- `app/list` — 列出可用 apps。
- `remoteControl/enable` — 实验性；为当前 app-server 进程启用远程控制，并返回当前远程控制状态快照。默认情况下，任何缺失的 enrollment 会在响应前完成，并且偏好会为当前 app-server 客户端作用域持久化。传入 `ephemeral: true` 仅为本进程启用远程控制，而不改变持久化偏好。
- `remoteControl/disable` — 实验性；为当前 app-server 进程禁用远程控制，并返回当前远程控制状态快照。默认情况下，禁用偏好会为当前 app-server 客户端作用域持久化。传入 `ephemeral: true` 仅为本进程禁用，而不改变持久化偏好。这不会撤销已经 enrollment 的控制器设备。
- `remoteControl/status/read` — 实验性；读取当前远程控制状态快照。`status` 为 `disabled`、`connecting`、`connected` 或 `errored` 之一；`serverName` 是本 app-server 进程使用的本机名称；当 app-server 具有当前 enrollment 时 `environmentId` 为字符串，当该 enrollment 被清除、失效或远程控制被禁用时为 `null`。
- `remoteControl/pairing/start` — 实验性；为当前 app-server 进程启动短期远程控制配对产物。传入 `manualCode: true` 还可请求手动配对码。返回 `pairingCode`、`manualPairingCode`、`environmentId` 以及 Unix 秒的 `expiresAt`；app-server 有意不暴露后端 `serverId`。
- `remoteControl/pairing/status` — 实验性；轮询远程控制 `pairingCode` 或 `manualPairingCode` 是否已被认领。恰好传入这两个字段之一。返回 `claimed`。
- `remoteControl/client/list` — 实验性；列出被授予某个环境访问权限的控制器设备。传入 `environmentId` 以及可选 `cursor`、`limit` 和 `order`；返回面向选择器的客户端元数据以及 `nextCursor`。即使本地中继被禁用或未 enrollment，此已登录账户管理操作仍可用。
- `remoteControl/client/revoke` — 实验性；撤销某个控制器设备对某个环境的授权。传入 `environmentId` 和 `clientId`；返回空对象。即使本地中继被禁用或未 enrollment，此已登录账户管理操作仍可用。
- `remoteControl/status/changed` — 当远程控制状态或客户端可见环境 id 变化时发出的通知。`status` 为 `disabled`、`connecting`、`connected` 或 `errored` 之一；`serverName` 是本 app-server 进程使用的本机名称；当 app-server 具有当前 enrollment 时 `environmentId` 为字符串，当该 enrollment 被清除、失效或远程控制被禁用时为 `null`。新初始化的 app-server 客户端总会收到当前状态快照。
- `skills/config/write` — 按名称或绝对路径写入用户级 skill 配置。
- `plugin/install` — 从已发现的 marketplace 条目安装 plugin，拒绝标记为不可安装的 marketplace 条目，若有则安装 MCP，并返回有效 plugin 鉴权策略以及仍需鉴权的任何 apps。对于远程安装，客户端可包含可选 `installAttemptId`；app-server 将其原样作为后端 POST body 中的 `install_attempt_id` 转发，省略则保留遗留空 body 请求（**开发中；请勿从生产客户端调用**）。
- `plugin/uninstall` — 按 `<plugin>@<marketplace>` 形式的 `pluginId` 卸载本地 plugin，方法是删除其缓存文件并清除其用户级配置条目；或按后端 `pluginId` 卸载远程 ChatGPT plugin，方法是将卸载转发到 ChatGPT plugin 后端并删除任何已下载的远程 plugin 缓存（**开发中；请勿从生产客户端调用**）。
- `mcpServer/oauth/login` — 为已配置 MCP server 启动 OAuth 登录；传入 `threadId` 以从该 thread 所选 plugin 和执行器解析 server，可选传入 `clientRegistration`（`auto`、`cimd` 或 `dcr`）仅覆盖本次登录的客户端注册，并在浏览器流程完成后收到 `authorization_url`，随后是 `mcpServer/oauthLogin/completed`。省略 `clientRegistration` 会自动发现授权服务器支持的注册方法；该覆盖从不持久化到服务器配置中。
- `tool/requestUserInput` — 为工具调用向用户提示 1–3 个简短问题并返回其答案（实验性）。
- `config/mcpServer/reload` — 从磁盘重新加载 MCP server 配置，并为已加载 thread 排队刷新（在每个 thread 的下一轮活动 turn 上应用）；返回 `{}`。在编辑 `config.toml` 而不重启服务器后使用此方法。
- `mcpServerStatus/list` — 枚举已配置 MCP server 及其工具、鉴权状态、服务器信息、拥有 `pluginId`（非 plugin 贡献的 server 为 `null`），以及来自当前 thread 已发布连接的可空 `runtimeStatus`，加上 `full` 详细级别的 resources / resource templates；支持可选 `threadId` 以及 cursor+limit 分页。若省略 `threadId`，服务器直接从最新全局配置读取，且 `runtimeStatus` 为 `null`。当最新服务器注册与该 thread 已发布配置不同时，运行时状态也是 `null`。运行时状态在不启动或重连该 thread 的 server 的情况下观察；可以为 `notStarted`、`starting`、`connected`、`authenticationRequired`、`failed`、`cancelled` 或 `disabled`。清单可能被缓存或单独收集，并不能证明该 thread 已连接。更旧的服务器省略 `runtimeStatus`；客户端应将其视为未知。若省略 `detail`，服务器默认为 `full`。`unknown` 鉴权状态表示无法确定 OAuth 支持；`unsupported` 表示已知不支持 OAuth。
- `mcpServer/resource/read` — 按可选 `threadId`、`server` 和 `uri` 从已配置 MCP server 读取资源，返回 text/blob 资源 `contents`。与 `threadId` 一起传入 `originCallId`，可将 Codex app widget 限定到产生它的已完成工具调用的 app 和账户；成功的限定读取返回相同的 `originCallId`。可选 `connectorId` 将其余托管 app 资源限制到其来源连接器。若省略 `threadId`，服务器直接从最新 MCP 配置读取。
- `mcpServer/event/stream/start`（实验性）— 按 `threadId`、`server`、`subscriptionId`、事件 `name`、`arguments` 以及可选 `_meta` 订阅 MCP 事件。
- `mcpServer/event/stream/stop`（实验性）— 按 `subscriptionId` 停止调用方的事件订阅。
- `mcpServer/tool/call` — 按 `threadId`、`server`、`tool`、可选 `arguments` 以及可选 `_meta` 在 thread 已配置 MCP server 上调用工具，返回 MCP 工具结果。父级拥有的 Multi-Agent V2 子 agent 拒绝直接工具调用。
- `windowsSandbox/setupStart` — 为所选模式（`elevated` 或 `unelevated`）启动 Windows 沙箱设置；接受可选绝对 `cwd` 以针对特定工作区进行设置，立即返回 `{ started: true }`，稍后发出 `windowsSandbox/setupCompleted`。
- `feedback/upload` — 提交反馈报告（分类 + 可选原因 / 日志、conversation_id 以及可选 `extraLogFiles` 附件数组）；返回跟踪 thread id。
- `config/read` — 在解析配置分层与托管要求后获取运行时有效配置，包括存储在 `config.toml` 中的不透明 `desktop` 值。配置时，`packagedDefaults` 层优先级最低。
- `externalAgentConfig/detect` — 用 `includeHome`、可选 `cwds` 以及可选 `migrationSource` 选择器检测可迁移的外部 agent 产物。省略、`null` 或无法识别的迁移源值保留默认行为。已弃用的可选 `source` 字段仍为兼容性而接受，但不选择迁移源。每个检测到的项包含 `cwd`（home 为 `null`），多项目迁移还可能包含带 plugin id、skill 名称、memory、会话元数据或其他产物名称的结构化 `details`。响应还包括从检测到的源会话推断出的连接器候选，带有规范化显示 `name`、使用该连接器的检测到会话数量，以及用于检测的源元数据字段。
- `externalAgentConfig/import` — 通过传入带 `cwd`（home 为 `null`）以及 detect 返回的任何 `details` 的显式 `migrationItems` 来应用所选外部 agent 迁移项。传入与检测相同的可选 `migrationSource`，以便服务器从匹配源读取；省略、`null` 或无法识别的值保留默认行为。可选 `source` 标识发起导入的产品，而可选不透明 `providerId` 将分析归因到该产品选择的 provider，而不影响迁移源选择。响应用 `importId` 确认同步导入阶段。预期迁移失败作为每项失败报告，而不是 JSON-RPC 错误，因此服务器仍返回该 `importId`，并在所有同步和后台工作完成后发出带有相同 ID 的 `externalAgentConfig/import/completed`。完成通知包含带成功和失败的类型级 `itemTypeResults`，包括供客户端单独报告的原始失败消息。
- `externalAgentConfig/import/readHistories` — 读取已完成的导入历史，以及从成功导入的会话历史中检测到的连接器候选。成功的会话条目在可用时包含原始导入标题。连接器候选包含规范化显示 `name`、使用该连接器的已导入会话数量，以及用于检测的源元数据字段。
- `config/value/write` — 将单个配置键 / 值写入磁盘上的用户 config.toml；诸如 `desktop.someKey` 的点分路径使用相同的通用写入面。与托管要求重叠的写入会以 `configRequirementReadonly` 被拒绝。
- `config/batchWrite` — 将多个配置编辑原子应用到磁盘上的用户 config.toml，可选 `reloadUserConfig: true` 以热重载已加载 thread，包括多个 `desktop.*` 编辑。会话静态的 model、reasoning-effort、Plan 模式 reasoning-effort、service-tier 和 personality 默认值不会重载已有 thread。
- `configRequirements/read` — 从 `requirements.toml` 和 / 或 MDM 获取已加载的要求约束（若均未配置则为 `null`），包括精确托管值（`cliAuthCredentialsStore`、`chatgptBaseUrl`、`sqliteHome`、`logDir`、`modelCatalogJson`、`checkForUpdateOnStartup`、`allowLoginShell`、`feedback.enabled` 和 `windowsSandboxPrivateDesktop`）、仅存在于要求中的 developer 指令（`additionalDeveloperInstructions`，独立于普通 developer 指令提供）、允许列表（`allowedApprovalPolicies`、`allowedSandboxModes`、`allowedWebSearchModes`）、分层权限配置文件允许映射（`allowedPermissionProfiles`）、托管权限配置文件默认值（`defaultPermissions`）、生命周期 hook 锁定（`allowManagedHooksOnly`）、远程控制策略（`allowRemoteControl`；`false` 强制禁用远程控制，而 `true` 或 `null` 保留现有行为）、Browser/Computer Use 总策略（`allowBrowserAndComputerUse`）、computer use 策略（`computerUse`，包括持久审批、默认应用访问以及按平台应用规则）、Browser Use 策略（`browserUse`，包括历史访问、来源规则、自动审查和审批控制）、交互式浏览器导入策略（`inAppBrowser.allowExternalBrowserSettingsImport`）、钉住的功能值（`featureRequirements`，包括管理员可设为 `false` 的默认允许 `in_app_updates` 策略）、托管生命周期 hooks（`hooks`，包括带可选 `additionalContextLimit` 的命令处理器，以及带 `server`、`tool`、`input`、`timeoutSec` 和 `statusMessage` 的 `mcp_tool` 处理器）、`enforceResidency`、托管自动审查（`autoReview.requiredOnModels` 和 `autoReview.ignoreRules`）、模型默认值（`models.newThread.model`、`models.newThread.modelReasoningEffort` 和 `models.newThread.serviceTier`），以及诸如规范域名 / socket 权限加上 `managedAllowedDomainsOnly` 和 `dangerFullAccessDenylistOnly` 的 `network` 约束。

### Plugin 配置作用域

Plugin 激活和 MCP 设置使用现有的合并配置，包括系统设置和受信任的项目覆盖。`skills/list` 会为每个请求的工作目录独立解析 plugin skills。

省略或空的目录 `cwds` 会排除项目配置，包括 app-server 进程自己的项目。

Marketplace 定义可以来自系统配置，但已配置的 Git marketplace 目前需要已有的已下载快照。

当 marketplace 名称定义在该操作已加载配置栈的另一已启用层中时，`marketplace/remove` 会拒绝移除。否则它会移除快照以及任何 base-user 条目；清理不需要必须存在 base-user 条目。

### 示例：启动或恢复 thread

需要新的 Codex 对话时，启动一个全新 thread。

```json
{ "method": "thread/start", "id": 10, "params": {
    // 可选设置配置。若未指定，将使用用户当前配置。
    "model": "gpt-5.1-codex",
    "cwd": "/Users/me/project",
    "approvalPolicy": "never",
    "sandbox": "workspaceWrite",
    // 优先使用实验性配置文件选择：
    // "permissions": ":workspace"
    // 用于 :workspace_roots 物化的实验性运行时根：
    // "runtimeWorkspaceRoots": ["/Users/me/project", "/Users/me/openai"],
    // 由托管平台选择的实验性能力根：
    "selectedCapabilityRoots": [
        {
            "id": "github@openai",
            "location": {
                "type": "environment",
                "environmentId": "workspace",
                "path": "/opt/cca/plugins/github"
            }
        }
    ],
    // 不要同时发送 "sandbox" 和 "permissions"。
    "personality": "friendly",
    "serviceName": "my_app_server_client", // 可选指标标签（`service_name`）
    "sessionStartSource": "startup", // 可选："startup"（默认）或 "clear"
    // 实验性：需要选择加入
    "dynamicTools": [
        {
            "type": "namespace",
            "name": "tickets",
            "description": "Ticket management tools",
            "tools": [
                {
                    "type": "function",
                    "name": "lookup_ticket",
                    "description": "Fetch a ticket by id",
                    "deferLoading": true,
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "id": { "type": "string" }
                        },
                        "required": ["id"]
                    }
                }
            ]
        }
    ],
} }
{ "id": 10, "result": {
    "thread": {
        "id": "thr_123",
        "preview": "",
        "modelProvider": "openai",
        "createdAt": 1730910000
    }
} }
{ "method": "thread/started", "params": { "thread": { … } } }
```

有效的 `personality` 值为 `"friendly"`、`"pragmatic"` 和 `"none"`。选择 `"none"` 时，personality 占位符会被替换为空字符串。

要继续已存储会话，用你先前记录的 `thread.id` 调用 `thread/resume`。响应形状与 `thread/start` 相同。当已存储会话包含持久化 token 用量时，服务器会在响应后立即发出 `thread/tokenUsage/updated`，以便客户端在下一轮 turn 开始前渲染恢复的用量。你也可以传入 `thread/start` 支持的相同配置覆盖，包括 `approvalsReviewer`。冷恢复时，审批策略和活动权限配置文件 ID 按此顺序选择来源：请求覆盖、最新持久化 thread 设置、当前配置的默认值。持久化配置文件 ID 通过与 `permissions` 覆盖相同的配置和要求路径解析。没有活动配置文件 ID 的 thread 使用当前配置，而不是恢复其具体的历史权限。

父级拥有的 Multi-Agent V2 子级是例外：`thread/resume` 忽略配置覆盖，并重新附着到现有子级。未加载的子级会通过其实际、当前已加载的父级、使用父级派生的配置重新加载。若无法执行该由所有者控制的重新加载，请求返回 JSON-RPC 错误 `-32600`；请先恢复父级，或用 `thread/read` 或 `thread/turns/list` 检查子级的已存储历史而不加载它。该策略遵循子级的多 agent 运行时，包括无法进一步委托的叶子 worker。

默认情况下，`thread/resume` 在 `thread.turns` 中包含重建的 turn 历史。对分页 thread 的全历史水合已弃用，并发出 `deprecationNotice`；客户端应传入 `excludeTurns: true`，仅返回 thread 元数据和实时恢复状态，然后用 `thread/turns/list` 和 `thread/items/list` 分页。冷分页恢复在能识别对应已存储 turn 时仍可重放持久化的 `thread/tokenUsage/updated`；恢复已经加载的 thread 会等待下一次实时更新。

分页 thread 保持与遗留 thread 相同的恢复契约。默认恢复会将完整投影历史物化到 `thread.turns`；`excludeTurns: true` 使该数组保持为空，并包含 `turnsBackwardsCursor` 和 `itemsBackwardsCursor`，用于恢复边界处可见的持久历史。将每个 cursor 直接传给匹配的 list API，并设 `sortDirection: "desc"`；第一页包含 cursor 标识的那一行，而更新的记录通过实时通知到达。当还没有持久行时，任一 cursor 为 `null`。

同一时间只有一个 app-server 进程可以打开分页 thread 进行写入。若另一进程已经拥有该 thread，`thread/resume`、`thread/archive` 和 `thread/delete` 会以 JSON-RPC 错误 `-32600` 失败。若另一进程拥有任何派生后代，归档和删除也会失败。只读请求在不恢复 thread 的情况下仍可用。

希望在一次往返中同时获得实时恢复订阅和一页 turn 的实验性客户端，可以传入 `initialTurnsPage`。它接受与 `thread/turns/list` 相同的 `limit`、`sortDirection` 和 `itemsView` 控制；省略的控制使用其默认值。响应包含带有 `nextCursor` 和 `backwardsCursor` 的 `initialTurnsPage`，供后续分页。

默认情况下，恢复使用与该 thread 关联的最新持久化 `model` 和 `reasoningEffort` 值。提供 `model`、`modelProvider`、`config.model` 或 `config.model_reasoning_effort` 中的任何一个都会禁用该持久化回退，改为使用显式覆盖加上正常配置解析。

示例：

```json
{ "method": "thread/resume", "id": 11, "params": {
    "threadId": "thr_123",
    "personality": "friendly"
} }
{ "id": 11, "result": { "thread": { "id": "thr_123", … } } }

{ "method": "thread/resume", "id": 12, "params": {
    "threadId": "thr_123",
    "excludeTurns": true
} }
{ "id": 12, "result": {
    "thread": { "id": "thr_123", "turns": [], … },
    "turnsBackwardsCursor": "turn-backwards-cursor-or-null",
    "itemsBackwardsCursor": "item-backwards-cursor-or-null"
} }

{ "method": "thread/resume", "id": 13, "params": {
    "threadId": "thr_123",
    "excludeTurns": true,
    "initialTurnsPage": {
        "limit": 20,
        "sortDirection": "desc",
        "itemsView": "summary"
    }
} }
{ "id": 13, "result": {
    "thread": { "id": "thr_123", "turns": [], … },
    "initialTurnsPage": {
        "data": [ ... ],
        "nextCursor": "older-turns-cursor-or-null",
        "backwardsCursor": "newer-turns-cursor-or-null"
    }
} }
```

要从已存储会话分叉，用 `thread.id` 调用 `thread/fork`。这会创建新 thread id，并为其发出 `thread/started` 通知。返回的 `thread.sessionId` 标识当前实时会话树的根。根 thread 使用自己的 `thread.id` 作为 `thread.sessionId`；未加载的已存储 thread 也报告自己的 `thread.id`，因为恢复其中一个会使它成为新实时会话树的根。当源历史包含持久化 token 用量时，服务器还会在响应后立即为新 thread 发出 `thread/tokenUsage/updated`。若源 thread 正在运行，分叉会先将其快照为当前 turn 已被中断。当分叉应仅保留在内存中时，传入 `ephemeral: true`：

```json
{ "method": "thread/fork", "id": 12, "params": { "threadId": "thr_123", "ephemeral": true } }
{ "id": 12, "result": { "thread": { "id": "thr_456", "sessionId": "thr_456", … } } }
{ "method": "thread/started", "params": { "thread": { … } } }
```

与 `thread/resume` 一样，对分页 `thread/fork` 的全历史水合已弃用，并发出 `deprecationNotice`。客户端应传入 `excludeTurns: true`，仅在 `thread.turns` 中返回 thread 元数据，并用 `thread/turns/list` 和 `thread/items/list` 分页历史。仅元数据的分叉不会重放恢复的 `thread/tokenUsage/updated`。分页 thread 的临时分叉需要 `excludeTurns: true`。

### 示例：列出 thread（带分页和过滤）

`thread/list` 可用于渲染历史 UI。结果默认按 `createdAt`（最新优先）降序。

对于已加载的派生 thread，当 V1 agent 接受直接输入时实验性 `canAcceptDirectInput` 为 `true`，当 V2 agent 由其父级拥有时为 `false`。当该能力不可用或不适用时为 `null`，包括未加载 thread 和普通 CLI thread。`thread/list` 和 `thread/search` 都从已加载 thread 状态推导该能力，而不是从持久化元数据。

可传入任意组合：

- `cursor` — 来自先前响应的不透明字符串；第一页省略。
- `limit` — 未设置时服务器默认为合理页大小。
- `sortKey` — `created_at`（默认）、`updated_at`、`recency_at`，或用于某个 section 持久化手动顺序的 `section_position`。
- `recencyAt` 在 thread 创建时初始化，并在 turn 开始时前进。与 `updatedAt` 不同，后台输出和其他持久化变更不会推进它。
- `sortDirection` — `desc`（时间戳排序的默认值）或 `asc`（`section_position` 的默认值）。
- `modelProviders` — 将结果限制到特定 provider；未设置、null 或空数组会包含所有 provider。
- `sourceKinds` — 将结果限制到特定来源；省略或传入 `[]` 仅限交互式会话（`cli`、`vscode`）。
- `archived` — 为 `true` 时仅列出已归档 thread。为 `false` 或 `null` 时列出未归档 thread（默认）。
- `sectionId` — 提供来自 `threadSection/list` 的 ID 以返回该 section 中的 thread；传入 `null` 仅返回没有 section 的 thread；或省略以包含每个 section 中的 thread 以及没有 section 的 thread。
- `cwd` — 将结果限制到会话 cwd 精确匹配此路径的 thread，或在提供数组时匹配其中之一。相对路径在匹配前会相对 app-server 进程 cwd 解析。
- `useStateDbOnly` — 为 `true` 时从状态 DB 返回，而不扫描 JSONL rollout 以修复元数据。省略或传入 `false` 以保留默认的扫描并修复行为。
- `searchTerm` — 将结果限制到提取标题包含此子串的 thread（区分大小写）。
- 响应包含用于同方向继续的 `nextCursor`，以及在反转 `sortDirection` 时作为 `cursor` 传入的 `backwardsCursor`。
- 响应在可用时包含 AgentControl 派生的 thread 子 agent 的 `agentNickname` 和 `agentRole`。

示例：

```json
{ "method": "thread/list", "id": 20, "params": {
    "cursor": null,
    "limit": 25,
    "cwd": ["/Users/me/project", "/Users/me/project-worktree"],
    "sortKey": "created_at"
} }
{ "id": 20, "result": {
    "data": [
        { "id": "thr_a", "preview": "Create a TUI", "modelProvider": "openai", "createdAt": 1730831111, "updatedAt": 1730831111, "recencyAt": 1730831111, "status": { "type": "notLoaded" }, "agentNickname": "Atlas", "agentRole": "explorer" },
        { "id": "thr_b", "preview": "Fix tests", "modelProvider": "openai", "createdAt": 1730750000, "updatedAt": 1730750000, "recencyAt": 1730750000, "status": { "type": "notLoaded" } }
    ],
    "nextCursor": "opaque-token-or-null",
    "backwardsCursor": "opaque-token-or-null"
} }
```

当 `nextCursor` 为 `null` 时，你已到达最后一页。

### 示例：列出后代 thread

在初始化期间启用 `capabilities.experimentalApi`，然后用带 `ancestorThreadId` 的 `thread/list`，从持久化 spawn-edge 状态分页浏览某个 thread 的每个派生后代。祖先本身被排除，每个结果的 `parentThreadId` 仍是其直接父级。只想要直接子级时改用 `parentThreadId`；同时发送两个过滤器无效。Review 和 Guardian thread 不包含在内，因为它们不参与 spawn-edge 生命周期。省略 `modelProviders` 或 `sourceKinds` 时，关系过滤请求分别包含每个 provider 或来源种类。显式过滤器保留普通 `thread/list` 行为，包括空 `sourceKinds` 列表的仅交互式默认值。

```json
{ "method": "thread/list", "id": 21, "params": {
    "ancestorThreadId": "00000000-0000-0000-0000-000000000100",
    "limit": 25
} }
{ "id": 21, "result": {
    "data": [
        { "id": "00000000-0000-0000-0000-000000000101", "parentThreadId": "00000000-0000-0000-0000-000000000100", "status": { "type": "notLoaded" } },
        { "id": "00000000-0000-0000-0000-000000000102", "parentThreadId": "00000000-0000-0000-0000-000000000101", "status": { "type": "notLoaded" } }
    ],
    "nextCursor": null,
    "backwardsCursor": null
} }
```

### 示例：列出已加载 thread

`thread/loaded/list` 返回当前已加载到内存中的 thread id。当你想检查哪些会话处于活动状态、而不扫描磁盘上的 rollout 时，这很有用。

```json
{ "method": "thread/loaded/list", "id": 21 }
{ "id": 21, "result": {
    "data": ["thr_123", "thr_456"]
} }
```

### 示例：读取服务器诊断

`server/diagnostics` 返回 app-server 进程及其已注册仪表的度量。在初始化期间启用 `capabilities.experimentalApi`。物理占用在 macOS 上可用，在其他平台为 `null`。

```json
{ "method": "server/diagnostics", "id": 22, "params": {} }
{ "id": 22, "result": {
    "process": {
        "id": 1234,
        "residentMemoryBytes": 4194304,
        "physicalFootprintBytes": 5242880
    },
    "gauges": [
        { "name": "app.requests.in_flight", "value": 1 },
        { "name": "core.threads.live", "value": 1 }
    ]
} }
```

仪表在首次使用时注册。取决于进程活动，快照还可以包含 `app.requests.queued`、`app.server_requests.pending`、`core.mailbox.pending`、`core.turns.active` 和 `mcp.connections.live`。诊断请求本身包含在 `app.requests.in_flight` 中。

### 示例：跟踪 thread 状态变化

`thread/status/changed` 在已加载 thread 已经向客户端介绍之后、其状态发生变化时发出：

- 包含 `threadId` 和新 `status`。
- 状态可以是 `notLoaded`、`idle`、`systemError` 或 `active`（带 `activeFlags`；`active` 意味着正在运行）。
- `thread/start`、`thread/fork` 和分离式 review thread 不会发出单独的初始 `thread/status/changed`；它们的 `thread/started` 通知已经携带当前 `thread.status`。

```json
{
  "method": "thread/status/changed",
  "params": {
    "threadId": "thr_123",
    "status": { "type": "active", "activeFlags": [] }
  }
}
```

### 示例：取消订阅已加载 thread

`thread/unsubscribe` 移除当前连接对某个 thread 的订阅。响应状态为以下之一：

- `unsubscribed`：该连接已订阅且现已移除。
- `notSubscribed`：该连接未订阅该 thread。
- `notLoaded`：该 thread 未加载。

若这是最后一个订阅者，服务器不会立即卸载该 thread。它会在该 thread 连续 30 分钟没有订阅者也没有 thread 活动后卸载，运行 `SessionEnd` hooks，然后发出 `thread/closed` 以及向 `notLoaded` 的 `thread/status/changed` 转换。

`SessionEnd` 也会在归档、删除以及优雅 app-server 关闭之前运行。它仅对根 thread 运行，不对 `ThreadSpawn` 子级或内部子 agent 运行。Hooks 是建议性的：它们的输出不能阻止拆卸。默认超时为一秒，配置的超时上限为三秒，`async: true` 会同步运行并带配置警告，hook 输入始终报告 `reason: "other"`。`SessionEnd` 匹配器针对该 reason 求值。

```json
{ "method": "thread/unsubscribe", "id": 22, "params": { "threadId": "thr_123" } }
{ "id": 22, "result": { "status": "unsubscribed" } }
```

稍后，空闲卸载超时之后：

```json
{ "method": "thread/status/changed", "params": {
    "threadId": "thr_123",
    "status": { "type": "notLoaded" }
} }
{ "method": "thread/closed", "params": { "threadId": "thr_123" } }
```

### 示例：读取 thread

用 `thread/read` 按 id 获取已存储 thread 而不恢复它。需要将 thread 历史加载到 `thread.turns` 时传入 `includeTurns`。返回的 thread 在可用时包含子 agent thread 的 `parentThreadId`、`agentNickname` 和 `agentRole`。

分页 thread 也可以使用 `includeTurns: true`，但全历史水合已弃用，并发出 `deprecationNotice`。客户端应省略 `includeTurns`（或将其设为 `false`），然后用 `thread/turns/list` 和 `thread/items/list` 进行增量历史加载。

```json
{ "method": "thread/read", "id": 22, "params": { "threadId": "thr_123" } }
{ "id": 22, "result": {
    "thread": { "id": "thr_123", "status": { "type": "notLoaded" }, "turns": [] }
} }
```

```json
{ "method": "thread/read", "id": 23, "params": { "threadId": "thr_123", "includeTurns": true } }
{ "id": 23, "result": {
    "thread": { "id": "thr_123", "status": { "type": "notLoaded" }, "turns": [ ... ] }
} }
```

### 示例：列出 thread turn

用 `thread/turns/list` 分页浏览已存储 thread 的 turn 历史而不恢复它。默认结果按降序排列，以便客户端可以从当前开始，并用 `nextCursor` 获取更旧的 turn。响应还包含 `backwardsCursor`；稍后将其作为 `cursor` 传入，并设 `sortDirection: "asc"`，以获取比先前页面第一项更新的 turn。

每个返回的 `Turn` 都包含 `itemsView`，告诉客户端 `items` 数组是有意省略（`notLoaded`）、仅包含摘要 item（`summary`），还是包含来自持久化 app-server 历史的每个 item（`full`）。传入 `itemsView` 以选择返回的详细级别；省略的 `itemsView` 默认为 `"summary"`。

分页 thread 支持相同视图。它们的 `full` 视图在 app-server 返回 turn 页之前从分页 item 投影物化。

```json
{ "method": "thread/turns/list", "id": 24, "params": {
    "threadId": "thr_123",
    "limit": 50,
    "sortDirection": "desc",
    "itemsView": "summary"
} }
{ "id": 24, "result": {
    "data": [ ... ],
    "nextCursor": "older-turns-cursor-or-null",
    "backwardsCursor": "newer-turns-cursor-or-null"
} }
```

`thread/items/list` 跨 thread 分页完整持久化 item，可选过滤到一轮 turn：

```json
{ "method": "thread/items/list", "id": 25, "params": {
    "threadId": "thr_123",
    "turnId": "turn_456",
    "limit": 100,
    "sortDirection": "asc"
} }
```

每个返回条目包含所属 `turnId` 及其完整 `item`，因此客户端可以将未过滤页面分组到 turn 中。省略 `turnId` 或传入 `null` 以跨 thread 分页 item。Item cursor 可以在有或没有 `turnId` 的情况下重用；过滤器不会改变 cursor 的作用域。未实现 item 分页的 thread store 返回 JSON-RPC `-32601`，消息为 `thread/items/list is not supported yet`。

`thread/searchOccurrences` 搜索一个分页 thread，而不重放其 rollout。它按时间顺序从每条可见用户消息（包括引导消息）以及最终助手消息返回匹配项。`snippetMatchRange` 使用 `snippet` 内的 UTF-16 偏移，`turnCursor` 可以直接传给 `thread/turns/list` 以加载包含该匹配的 turn。

```json
{ "method": "thread/searchOccurrences", "id": 26, "params": {
    "threadId": "thr_123",
    "searchTerm": "needle",
    "limit": 50
} }
{ "id": 26, "result": {
    "data": [{
        "turnId": "turn_456",
        "itemId": "item_789",
        "snippet": "The needle is here.",
        "snippetMatchRange": { "start": 4, "end": 10 },
        "turnCursor": "opaque-inclusive-turn-cursor"
    }],
    "nextCursor": null
} }
```

### 示例：更新已存储 thread 元数据

用 `thread/metadata/update` 修补 sqlite 支持的 `gitInfo`，而不恢复 thread。省略的字段保持不变，而显式 `null` 会清除已存储值。用 `thread/section/move` 进入、重排或离开某个 section；显式移动会在首次 turn 之前就持久化新启动的非临时 thread。Section 位置仍由服务器拥有，当 `sortKey` 为 `section_position` 时，`thread/list` 按手动顺序返回 thread。非空 `sectionId` 过滤器包含预览仍为空的、已显式放置的 thread。

```json
{ "method": "thread/metadata/update", "id": 24, "params": {
    "threadId": "thr_123",
    "gitInfo": { "branch": "feature/sidebar-pr" }
} }
{ "id": 24, "result": {
    "thread": {
        "id": "thr_123",
        "gitInfo": { "sha": null, "branch": "feature/sidebar-pr", "originUrl": null }
    }
} }

{ "method": "thread/metadata/update", "id": 25, "params": {
    "threadId": "thr_123",
    "gitInfo": { "branch": null }
} }
{ "id": 25, "result": {
    "thread": {
        "id": "thr_123",
        "gitInfo": null
    }
} }

{ "method": "thread/section/move", "id": 26, "params": {
    "threadId": "thr_123",
    "sectionId": "01984de2-8f74-7c91-a3b2-5c5e937cf318",
    "beforeThreadId": null
} }
{ "id": 26, "result": {} }

{ "method": "thread/list", "id": 27, "params": {
    "sectionId": "01984de2-8f74-7c91-a3b2-5c5e937cf318",
    "sortKey": "section_position",
    "limit": 100
} }

{ "method": "thread/section/move", "id": 28, "params": {
    "threadId": "thr_123",
    "sectionId": "01984de2-8f74-7c91-a3b2-5c5e937cf318",
    "beforeThreadId": "thr_456"
} }
{ "id": 28, "result": {} }

{ "method": "thread/section/move", "id": 29, "params": {
    "threadId": "thr_123",
    "sectionId": null,
    "beforeThreadId": null
} }
{ "id": 29, "result": {} }
```

实验性：用 `thread/memoryMode/set` 更改 thread 是否仍有资格进行未来的 memory 生成。

```json
{ "method": "thread/memoryMode/set", "id": 26, "params": {
    "threadId": "thr_123",
    "mode": "disabled"
} }
{ "id": 26, "result": {} }
```

实验性：用 `memory/reset` 清除当前 Codex home 的本地 memory 产物以及 sqlite 支持的 memory stage 数据。这会保留已有 thread memory 模式；当某个 thread 的未来 memory 资格应改变时，请单独使用 `thread/memoryMode/set`。

```json
{ "method": "memory/reset", "id": 27 }
{ "id": 27, "result": {} }
```

### 示例：设置和更新 thread goal

用 `thread/goal/set` 为已物化 thread 创建或更新当前 goal。客户端可以在因 token 预算耗尽或接近耗尽而停止时设置 `budgetLimited`，在进度等待外部干预时设置 `blocked`，以及在用量可用性阻止进一步工作时设置 `usageLimited`。当记账越过已配置 token 预算时，系统也会设置 `budgetLimited`；当 turn 因硬用量限制错误结束时，系统会设置 `usageLimited`。

当配置了 `goals.max_goal_token_budget` 时，新 goal 默认使用该限制，更大的预算会被拒绝，将 `tokenBudget` 设为 `null` 会把预算重置为已配置限制，而不是移除它。

```json
{ "method": "thread/goal/set", "id": 27, "params": {
    "threadId": "thr_123",
    "objective": "Keep improving the benchmark until p95 latency is under 120ms",
    "tokenBudget": 200000
} }
{ "id": 27, "result": { "goal": {
    "threadId": "thr_123",
    "objective": "Keep improving the benchmark until p95 latency is under 120ms",
    "status": "active",
    "tokenBudget": 200000,
    "tokensUsed": 0,
    "timeUsedSeconds": 0,
    "createdAt": 1776272400,
    "updatedAt": 1776272400
} } }
{ "method": "thread/goal/updated", "params": { "threadId": "thr_123", "goal": {
    "threadId": "thr_123",
    "objective": "Keep improving the benchmark until p95 latency is under 120ms",
    "status": "active",
    "tokenBudget": 200000,
    "tokensUsed": 0,
    "timeUsedSeconds": 0,
    "createdAt": 1776272400,
    "updatedAt": 1776272400
} } }
```

```json
{ "method": "thread/goal/set", "id": 28, "params": {
    "threadId": "thr_123",
    "status": "blocked"
} }
{ "id": 28, "result": { "goal": {
    "threadId": "thr_123",
    "objective": "Keep improving the benchmark until p95 latency is under 120ms",
    "status": "blocked",
    "tokenBudget": 200000,
    "tokensUsed": 10000,
    "timeUsedSeconds": 60,
    "createdAt": 1776272400,
    "updatedAt": 1776272460
} } }
```

用 `thread/goal/get` 读取当前 goal 而不改变它。

```json
{ "method": "thread/goal/get", "id": 29, "params": { "threadId": "thr_123" } }
{ "id": 29, "result": { "goal": null } }
```

用 `thread/goal/clear` 移除当前 goal。

```json
{ "method": "thread/goal/clear", "id": 30, "params": { "threadId": "thr_123" } }
{ "id": 30, "result": { "cleared": true } }
{ "method": "thread/goal/cleared", "params": { "threadId": "thr_123" } }
```

### 示例：排队后续用户 turn（实验性）

排队 turn 需要 `capabilities.experimentalApi = true`。用 `thread/queue/add` 在 turn 运行时持久化后续内容。每个 thread 最多可排队 100 条消息，服务器会在 thread 变为空闲时启动下一条排队 turn。

排队提交包含其用户输入以及必需的、由客户端提供的 `clientUserMessageId`。服务器会分配单独的稳定提交 ID，并在编辑提交时保留这两个 ID。应用上下文和 Responses API 客户端元数据在普通 `turn/start` 上仍可用；排队提交不会持久化或重放这些可选 turn 功能。

```json
{ "method": "thread/queue/add", "id": 40, "params": {
    "threadId": "thr_123",
    "input": [{ "type": "text", "text": "Now fix the failing tests." }],
    "clientUserMessageId": "019faba0-0000-7000-8000-000000000003"
} }
{ "id": 40, "result": { "queuedSubmission": {
    "id": "019faba0-0000-7000-8000-000000000001",
    "input": [{ "type": "text", "text": "Now fix the failing tests." }],
    "clientUserMessageId": "019faba0-0000-7000-8000-000000000003"
} } }
{ "method": "thread/queue/changed", "params": { "threadId": "thr_123" } }
```

用 `thread/queue/list` 读取有序队列。传入可选 `cursor` 和 `limit` 值以请求一页，并用返回的 `nextCursor` 继续直到它为 `null`。每个 `thread/queue/changed` 通知包含已变化的 `threadId`；获取当前页面以刷新队列。通过将 `queuedSubmissionId` 和替换 `input` 传给 `thread/queue/update` 来更新排队 turn；该提交保留其 ID 和位置。将该 ID 传给 `thread/queue/delete` 以移除它，或将每个排队 ID 按新顺序作为 `queuedSubmissionIds` 传给 `thread/queue/reorder`。

已完成和失败的 turn 会自动启动下一条排队提交。被中断的 turn 会使队列暂停，包括在 `thread/resume` 之后。用 `thread/queue/start` 启动队列头，或通过传入 `queuedSubmissionId` 选择一条排队提交。空闲 thread 会开始新 turn 并返回它；活动 thread 返回无效请求错误并使队列保持不变。排队提交的客户端消息 ID 保持稳定，其队列条目在 Core 接受新 turn 时被移除。普通 `turn/start` 不会消费排队提交。

### 示例：归档 thread

用 `thread/archive` 将持久化 rollout（作为磁盘上的 JSONL 文件存储）移入归档会话目录，并尝试移动任何派生后代 thread rollout。

```json
{ "method": "thread/archive", "id": 21, "params": { "threadId": "thr_b" } }
{ "id": 21, "result": {} }
{ "method": "thread/archived", "params": { "threadId": "thr_b" } }
```

已归档 thread 不会出现在 `thread/list` 中，除非将 `archived` 设为 `true`。

### 示例：删除 thread

用 `thread/delete` 硬删除 thread 及其派生后代 thread。现有 rollout 文件和关联元数据必须在请求成功前被移除；缺失的 rollout 文件被视为已经删除。

```json
{ "method": "thread/delete", "id": 23, "params": { "threadId": "thr_b" } }
{ "id": 23, "result": {} }
{ "method": "thread/deleted", "params": { "threadId": "thr_b" } }
```

### 示例：取消归档 thread

用 `thread/unarchive` 将已归档 rollout 移回 sessions 目录。

```json
{ "method": "thread/unarchive", "id": 24, "params": { "threadId": "thr_b" } }
{ "id": 24, "result": { "thread": { "id": "thr_b" } } }
{ "method": "thread/unarchived", "params": { "threadId": "thr_b" } }
```

### 示例：触发 thread 压缩

用 `thread/compact/start` 触发 thread 的手动历史压缩。请求立即返回 `{}`。

进度作为同一 `threadId` 上的标准 `turn/*` 和 `item/*` 通知发出。客户端应预期单个压缩 item：

- `item/started`，带有 `item: { "type": "contextCompaction", ... }`
- `item/completed`，带有相同的 `contextCompaction` item id

压缩运行时，该 thread 实际上处于一轮 turn 中，因此客户端应根据通知展示进度 UI。

```json
{ "method": "thread/compact/start", "id": 25, "params": { "threadId": "thr_b" } }
{ "id": 25, "result": {} }
```

### 示例：运行 thread shell 命令

将 `thread/shellCommand` 用于 TUI `!` 工作流。请求立即返回 `{}`。此 API 以完全访问、无沙箱方式运行；它不继承 thread sandbox 策略。

若 thread 已有活动 turn，该命令作为该 turn 上的辅助操作运行。在这种情况下，进度作为现有 turn 上的标准 `item/*` 通知发出，格式化输出被注入该 turn 的消息流：

- `item/started`，带有 `item: { "type": "commandExecution", "source": "userShell", ... }`
- 零个或多个 `item/commandExecution/outputDelta`
- `item/completed`，带有相同的 `commandExecution` item id

若 thread 尚未有活动 turn，服务器会为该 shell 命令启动独立 turn。在这种情况下客户端应预期：

- `turn/started`
- `item/started`，带有 `item: { "type": "commandExecution", "source": "userShell", ... }`
- 零个或多个 `item/commandExecution/outputDelta`
- `item/completed`，带有相同的 `commandExecution` item id
- `turn/completed`

```json
{ "method": "thread/shellCommand", "id": 26, "params": { "threadId": "thr_b", "command": "git status --short" } }
{ "id": 26, "result": {} }
```

### 示例：开始一轮 turn（发送用户输入）

Turn 将用户输入（文本、图片或音频）附加到 thread，并触发 Codex 生成。`input` 字段是带判别的联合列表：

- `{"type":"text","text":"Explain this diff"}`
- `{"type":"image","url":"data:image/png;base64,…"}`
- `{"type":"localImage","path":"/tmp/screenshot.png"}`
- `{"type":"audio","url":"data:audio/wav;base64,…"}`
- `{"type":"localAudio","path":"/tmp/recording.mp3"}`

`image` 变体接受内联 data URL。远程 HTTP(S) 图片 URL 会被拒绝；请改用 data URL 或 `localImage`。
`audio` 变体接受 data URL。其他 URL scheme 会被拒绝。`localAudio` 读取本地 wav、mp3、m4a、webm 和 ogg 文件，并在 Responses API 请求前将它们转换为 data URL。

你可以选择在新 turn 上指定配置覆盖。若指定，这些设置会成为同一 thread 上后续 turn 的默认值。`outputSchema` 仅应用于当前 turn。实验性 `environments` 是 turn 作用域的：省略以继承 thread 的粘性环境，传入 `[]` 使该 turn 不使用环境，或传入显式环境 id 仅覆盖本轮的粘性选择。

`serviceTierForTurn` 仅在请求开始新 turn 时覆盖档位，而不改变 thread 已保存的档位。使用 `"default"` 表示标准速度，或省略它（或传入 `null`）以继承 thread 的档位。当请求引导活动 turn 时会被忽略。现有 `serviceTier` 字段仍会改变后续 turn 的档位，包括两个字段同时提供时。

实验性 `cyberAccessProgram` 也仅应用于新 turn。它接受 `standard`、`daybreakBlue` 或 `daybreakRed`；省略则保留自动后端行为。对于通过内置 OpenAI provider 的 ChatGPT 鉴权请求，Codex 会在 Responses 和远程压缩请求的 `access_programs.cyber` 中发送对应的 `standard`、`daybreak_blue` 或 `daybreak_red` 值。WebSocket `response.create` 消息按请求携带该选择，因此更改它不需要重连。服务器仍会强制执行工作区授权和模型限制。API-key 和自定义 provider 请求省略此字段。此字段不会改变已保存模型或授予访问权限。

子 agent 在被生成或在新的后续上启动时（包括重新加载后）使用调用 turn 的选择。向已经在运行的子 turn 投递的输入不会改变该 turn 的选择。

`approvalsReviewer` 接受：

- `"user"` — 默认。直接在客户端审查审批请求。
- `"auto_review"` — 将审批请求路由到经过仔细提示的子 agent，它会收集相关上下文并应用基于风险的决策框架，然后再批准或拒绝请求。遗留值 `"guardian_subagent"` 仍为兼容性而接受。

托管 `requirements.toml` 可以对特定模型要求自动审查：

```toml
[auto_review]
required_on_models = ["protected-model"]
ignore_rules = ["protected-model"]
```

`required_on_models` 中的模型使用 `approvalsReviewer: "auto_review"`，同时保留任何有效配置的 `approvalPolicy`。Full Access 会被降级为 workspace-write 访问。不兼容的运行时覆盖或禁用的 Guardian 自动审查会被拒绝。`ignore_rules` 中的模型会忽略已保存的命令前缀审批。

```json
{ "method": "turn/start", "id": 30, "params": {
    "threadId": "thr_123",
    "clientUserMessageId": "client_msg_123",
    "input": [ { "type": "text", "text": "Run tests" } ],
    // 以下为可选配置覆盖
    "cwd": "/Users/me/project",
    // 实验性：turn 作用域环境选择。
    "environments": [
        { "environmentId": "local", "cwd": "/Users/me/project" }
    ],
    "approvalPolicy": "unlessTrusted",
    "sandboxPolicy": {
        "type": "workspaceWrite",
        "writableRoots": ["/Users/me/project"],
        "networkAccess": true
    },
    // 优先使用实验性配置文件选择：
    // "permissions": ":workspace"
    // 用于 :workspace_roots 物化的实验性运行时根：
    // "runtimeWorkspaceRoots": ["/Users/me/project", "/Users/me/openai"],
    // 不要同时发送 "sandboxPolicy" 和 "permissions"。
    "model": "gpt-5.1-codex",
    "effort": "medium",
    "summary": "concise",
    "personality": "friendly",
    // 可选 JSON Schema，用于约束本轮最终助手消息。
    "outputSchema": {
        "type": "object",
        "properties": { "answer": { "type": "string" } },
        "required": ["answer"],
        "additionalProperties": false
    }
} }
{ "id": 30, "result": { "turn": {
    "id": "turn_456",
    "status": "inProgress",
    "items": [],
    "error": null
} } }
```

### 示例：开始一轮 turn（调用 skill）

通过在文本输入中包含 `$<skill-name>`，并在旁边添加 `skill` 输入 item，来显式调用 skill。

```json
{ "method": "turn/start", "id": 33, "params": {
    "threadId": "thr_123",
    "input": [
        { "type": "text", "text": "$skill-creator Add a new skill for triaging flaky CI and include step-by-step usage." },
        { "type": "skill", "name": "skill-creator", "path": "/Users/me/.codex/skills/skill-creator/SKILL.md" }
    ]
} }
{ "id": 33, "result": { "turn": {
    "id": "turn_457",
    "status": "inProgress",
    "items": [],
    "error": null
} } }
```

### 示例：开始一轮 turn（调用 app）

通过在文本输入中包含 `$<app-slug>`，并添加 `path` 为 `app://<connector-id>` 形式的 `mention` 输入 item 来调用 app。

```json
{ "method": "turn/start", "id": 34, "params": {
    "threadId": "thr_123",
    "input": [
        { "type": "text", "text": "$demo-app Summarize the latest updates." },
        { "type": "mention", "name": "Demo App", "path": "app://demo-app" }
    ]
} }
{ "id": 34, "result": { "turn": {
    "id": "turn_458",
    "status": "inProgress",
    "items": [],
    "error": null
} } }
```

### 示例：开始一轮 turn（调用 plugin）

通过在文本输入中包含诸如 `@sample` 的 UI 提及 token，并添加 `mention` 输入 item，其 `path` 为 `plugin/installed` 或 `plugin/list` 返回的精确 `plugin://<plugin-name>@<marketplace-name>` 路径，来调用 plugin。

```json
{ "method": "turn/start", "id": 35, "params": {
    "threadId": "thr_123",
    "input": [
        { "type": "text", "text": "@sample Summarize the latest updates." },
        { "type": "mention", "name": "Sample Plugin", "path": "plugin://sample@test" }
    ]
} }
{ "id": 35, "result": { "turn": {
    "id": "turn_459",
    "status": "inProgress",
    "items": [],
    "error": null
} } }
```

### 示例：开始一轮 turn（独立工具输出）

提供命名的 `toolOutput` 以及空 `input` 数组，以开始真正的 turn 或加入活动常规 turn。`namespace` 可空，`output` 可以是文本或结构化内容 item。该输出保留工具级权威，并在持久历史和标准 item 通知中作为 `functionCallOutput` item 出现；客户端决定是否显示它。

```json
{ "method": "turn/start", "id": 36, "params": {
    "threadId": "thr_123",
    "input": [],
    "toolOutput": {
        "name": "send_message_to_thread",
        "namespace": "codex_app",
        "output": "Another agent delegated this task."
    }
} }
{ "id": 36, "result": { "turn": { "id": "turn_460", "status": "inProgress", "items": [], "error": null } } }
```

### 示例：注入原始历史 item

用 `thread/inject_items` 将预构建的 Responses API item 追加到已加载 thread 的提示历史中，而不开始一轮 turn。这些 item 会持久化到 rollout，并包含在后续模型请求中。独立的 `function_call_output` 在具有非空 `name` 时可以省略 `call_id`；`namespace` 可选，输出保留工具级权威。任何 `input_image` item 必须使用内联 data URL；远程 HTTP(S) 图片 URL 会被拒绝。仅历史输出不会作为 thread item 暴露。

```json
{ "method": "thread/inject_items", "id": 37, "params": {
    "threadId": "thr_123",
    "items": [
        {
            "type": "message",
            "role": "assistant",
            "content": [{ "type": "output_text", "text": "Previously computed context." }]
        },
        {
            "type": "function_call_output",
            "name": "send_message_to_thread",
            "namespace": "codex_app",
            "output": "Another agent delegated this task."
        }
    ]
} }
{ "id": 37, "result": {} }
```

### 示例：用 WebRTC 启动 realtime

当浏览器或 webview 拥有 `RTCPeerConnection`、且 app-server 应创建服务器端 realtime 会话时，用 `transport.type: "webrtc"` 调用 `thread/realtime/start`。传输 `sdp` 必须是 `RTCPeerConnection.createOffer()` 产生的 offer SDP，而不是手写或最小 SDP 字符串。

offer 应包含客户端想要协商的媒体段。对于标准 realtime UI 流程，在调用 `createOffer()` 之前创建音频轨道 / transceiver 以及 `oai-events` 数据通道：

```javascript
const pc = new RTCPeerConnection();

audioElement.autoplay = true;
pc.ontrack = (event) => {
  audioElement.srcObject = event.streams[0];
};

const mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
pc.addTrack(mediaStream.getAudioTracks()[0], mediaStream);
pc.createDataChannel("oai-events");

const offer = await pc.createOffer();
await pc.setLocalDescription(offer);
```

然后将 `offer.sdp` 发送给 app-server。Core 使用 `experimental_realtime_ws_backend_prompt` 作为后端指令，并使用 thread conversation id 作为默认 Realtime API 会话标识符。此 `realtimeSessionId` 值指向上游 Realtime API 会话，而不是 Codex 会话 / thread-group id。start 响应为 `{}`；远端 answer SDP 稍后作为 `thread/realtime/sdp` 到达，应传给 `setRemoteDescription()`：

```json
{ "method": "thread/realtime/start", "id": 40, "params": {
    "threadId": "thr_123",
    "outputModality": "audio",
    "prompt": "You are on a call.",
    "realtimeSessionId": null,
    "transport": { "type": "webrtc", "sdp": "v=0\r\no=..." }
} }
{ "id": 40, "result": {} }
{ "method": "thread/realtime/sdp", "params": {
    "threadId": "thr_123",
    "sdp": "v=0\r\no=..."
} }
```

自己创建并协商 realtime 通话的客户端可以改为传入其通话 ID：

```json
{ "method": "thread/realtime/start", "id": 41, "params": {
    "threadId": "thr_123",
    "outputModality": "audio",
    "version": "v3",
    "realtimeSessionId": "sess_123",
    "transport": { "type": "existingCall", "callId": "rtc_123" }
} }
{ "id": 41, "result": {} }
```

existing-call 传输通过其旁路 WebSocket 将 Codex 附着到该通话，而不会创建另一通话或发出 `thread/realtime/sdp`。客户端拥有 SDP 协商和初始 realtime 会话配置。对 existing call，Codex 启动上下文默认禁用；`includeStartupContext: true`、`prompt`、非空 `initialItems`、`model`、`voice` 和 `delegationAckFiller` 会被拒绝，因为它们会改变客户端拥有的会话。当已知上游会话 ID 时提供 `realtimeSessionId`；否则 `thread/realtime/started` 通知报告 `realtimeSessionId: null`。

省略 `prompt` 以使用 Codex 的默认 realtime 后端提示。当会话应在没有该默认后端提示的情况下启动时，发送 `prompt: null` 或 `prompt: ""`。传入 `realtimeStartInstructions`，提供 thread 进入 realtime 模式时给予 backing Codex 模型的 developer 指令；传入 `realtimeEndInstructions`，提供会话结束时的 developer 指令。这些指令配置 Codex，而不是 realtime 前端模型。它们在 realtime 状态转换时发出，而不是在每一轮 turn 上重复。每个指令字段限制为 8,192 个估算 token。省略任一字段会保留 Codex 现有的默认指令。客户端还可以在 `thread/realtime/start` 上传入 `model`，以选择不同的 realtime 会话配置，而不改变 thread 或用户配置。客户端可以传入 `version`，仅为本会话选择 realtime 协议。WebRTC 使用 AVAS，并支持遗留 Bidi `"v1"` 或 Frameless Bidi `"v3"`；Realtime Voice `"v2"` 对 WebRTC 会被拒绝。传入 `includeStartupContext: false` 可为本会话跳过 Codex 的启动上下文，同时仍使用所选后端提示。对于 V3，客户端可以传入 `initialItems`，在实时输入开始前用完整文本消息为会话播种：

```json
{
  "initialItems": [
    {
      "role": "developer",
      "text": "Relevant user memory: prefers concise technical answers."
    },
    {
      "role": "user",
      "text": "Continue from the prior discussion."
    }
  ]
}
```

每个 item 需要 `"user"`、`"developer"` 或 `"assistant"` 的 `role` 以及 `text` 字符串。Core 在初始会话引导期间（包括 WebRTC 通话创建）将它们序列化为 Frameless Bidi `session.initial_items`。请求限制为 128 个 item、每个 item 8,192 个估算文本 token，以及所有 item 合计 8,192 个估算文本 token。省略 `initialItems` 或传入空列表会保留先前的会话载荷和启动行为。V1 和 V2 拒绝非空 `initialItems`。对于 V3，传入 `delegationAckFiller: false` 可在 WebRTC 会话创建期间抑制 Realtime API 的 delegation 确认填充词，或传入 `true` 以恢复遗留确认。省略 `delegationAckFiller` 会保留 Realtime API 的默认值。V1 和 V2 忽略此设置。传入 `clientManagedHandoffs: true` 可抑制自动 Codex 响应 handoff 和 item。客户端随后可以用 `thread/realtime/appendText` 或 `thread/realtime/appendSpeech` 选择投递哪些更新。传入 `codexResponsesAsItems: true`，用 `conversation.item.create` 注入自动 Codex 响应，而不是协议的默认可说输出路径。使用该模式时，`codexResponseItemPrefix` 可以为每个自动 Codex 响应 item 前置简短实验指令。省略 `codexResponsesAsItems` 或传入 `false` 以保留默认可说行为。在 V3 中，自动 handoff 默认为 `codexResponseHandoffMode: "thinking"`，它为每个自动响应省略上下文追加 `channel`。传入 `"commentary"` 将每个响应路由到 commentary，或传入 `"bemTags"` 将 BEM commentary 标签路由到 `commentary`、final 标签路由到 `speakable`、analysis 标签路由到 `commentary`。无法解析的 BEM 输出回退到 `speakable`。BEM 路由读取原始信封并将其保留在追加文本中，供前端模型使用。使用 `"bemTags"` 时，客户端可以传入 `codexResponseHandoffChannelPrefixes` 以覆盖单个 channel 的已接受前缀，例如 `{"analysis":["[THINKING]"],"commentary":["[PROGRESS]","[UPDATE]"],"final":["[DONE]"]}`。省略的 channel 保留硬编码的 `[ANALYSIS]`、`[COMMENTARY]` 和 `[FINAL]` 默认值。此设置对 V1 或 V2 无效。V3 handoff 从不前置遗留 `"Agent Final Message"` 标签。更旧的客户端可以继续发送已移除的 `codexResponseHandoffPrefix` 字段；服务器忽略未知请求字段。调用 `thread/realtime/appendText` 以追加应用提供的 realtime 文本 item，或在应用决定应将 realtime 更新说出来时调用 `thread/realtime/appendSpeech`。

```javascript
await pc.setRemoteDescription({
  type: "answer",
  sdp: notification.params.sdp,
});
```

### 示例：中断活动 turn

你可以用 `turn/interrupt` 取消正在运行的 Turn。

```json
{ "method": "turn/interrupt", "id": 31, "params": {
    "threadId": "thr_123",
    "turnId": "turn_456"
} }
{ "id": 31, "result": {} }
```

服务器请求取消活动 turn，然后发出带有 `status: "interrupted"` 的 `turn/completed` 事件。这不会终止后台终端；当你明确想停止这些 shell 时，使用 `thread/backgroundTerminals/clean`。依赖 `turn/completed` 事件来知道 turn 中断何时完成。

### 示例：清理后台终端

用 `thread/backgroundTerminals/clean` 终止与某个 thread 关联的所有正在运行的后台终端。此方法是实验性的，需要 `capabilities.experimentalApi = true`。

```json
{ "method": "thread/backgroundTerminals/clean", "id": 35, "params": {
    "threadId": "thr_123"
} }
{ "id": 35, "result": {} }
```

### 示例：列出并终止后台终端

用 `thread/backgroundTerminals/list` 检查与已加载 thread 关联的正在运行的后台终端。`backgroundTerminals` 段有意沿用现有 `thread/backgroundTerminals/clean` 方法。返回的 `processId` 是 app-server 进程 id；主机 OS 元数据可空。请求接受标准 `cursor` 和 `limit` 分页字段。当 `nextCursor` 非空时，将其作为 `cursor` 传入以获取下一页。

```json
{ "method": "thread/backgroundTerminals/list", "id": 36, "params": { "threadId": "thr_123" } }
{ "id": 36, "result": { "data": [
    {
        "itemId": "item_456",
        "processId": "42",
        "command": "python3 -m http.server",
        "cwd": "/workspace",
        "osPid": null,
        "cpuPercent": null,
        "rssKb": null
    }
], "nextCursor": null } }
```

用 `thread/backgroundTerminals/terminate` 按该 `processId` 终止一个正在运行的后台终端。

```json
{ "method": "thread/backgroundTerminals/terminate", "id": 37, "params": { "threadId": "thr_123", "processId": "42" } }
{ "id": 37, "result": { "terminated": true } }
```

### 示例：更新正在运行的 turn 的设置（实验性）

启用 `capabilities.experimentalApi` 以及默认禁用的 `step_model_switching` 功能。提供来自 `turn/start`、`turn/started`、带 `includeTurns: true` 的 `thread/read` 或 `thread/turns/list` 的精确 turn ID：

```json
{ "method": "turn/settings/update", "id": 42, "params": {
    "threadId": "thr_123", "turnId": "turn_456", "model": "gpt-5.4"
} }
{ "id": 42, "result": { "status": "applied" } }
```

仅 `model`、`effort`、`summary` 和 `serviceTier` 可以更改。未知字段会被拒绝。省略的字段保持设置不变；`serviceTier: null` 清除请求的档位，而对 model、effort 或 summary 传入 `null` 则保持不变。

响应会等待 core：`status: "applied"` 表示已为后续捕获发布设置快照，即使其值未改变。正常默认值和档位过滤仍适用；发布并不能保证会再运行一次推理或使用每个偏好。已捕获的现有 step 保留其设置。

任何实时任务种类都可以接受发布。更新父级 review 上下文不会更新其子会话；shell 任务不会采样，未迁移的压缩消费者可能仍使用初始设置。

`status: "targetUnavailable"` 表示精确实时任务在发布前缺失或丢失。校验、功能和安全拒绝会返回 JSON-RPC 请求错误，说明在 `error.message` 中。这两种情况都不会重试或改向另一轮 turn。

这从不更新未来 thread 设置。若也要改变那些设置，请单独发送 `thread/settings/update` 并单独处理其排队确认。更旧的服务器会拒绝未知 turn 方法；客户端不得回退到 thread 更新。不提供新的 step 状态检查 API。

此诊断路径保留实时授权和临时安全检查。大多数消费者（包括模型特定的世界状态指令）仍使用初始 turn 设置。已保存 thread 受支持，但这些切换的完整模型指令正确性、模型归属以及恢复行为不受保证。

### 示例：引导活动 turn

用 `turn/steer` 将额外用户输入追加到当前活动的常规 turn。这不会发出 `turn/started`，也不接受 thread 设置覆盖。

```json
{ "method": "turn/steer", "id": 32, "params": {
    "threadId": "thr_123",
    "clientUserMessageId": "client_msg_124",
    "input": [ { "type": "text", "text": "Actually focus on failing tests first." } ],
    "expectedTurnId": "turn_456"
} }
{ "id": 32, "result": { "turnId": "turn_456" } }
```

`expectedTurnId` 是必需的。若没有活动 turn、`expectedTurnId` 与活动 turn 不匹配，或活动 turn 种类不接受同轮引导（例如 review 或手动压缩），请求会以 `invalid request` 错误失败。

### 示例：请求代码审查

用 `review/start` 在当前检出的项目上运行 Codex 的审查器。请求接受 thread id 以及描述应审查内容的 `target`：

- `{"type":"uncommittedChanges"}` — 已暂存、未暂存和未跟踪文件。
- `{"type":"baseBranch","branch":"main"}` — 相对所提供分支的上游做 diff（参见 prompt 以了解 Codex 将运行的精确 `git merge-base`/`git diff` 指令）。
- `{"type":"commit","sha":"abc1234","title":"Optional subject"}` — 审查特定提交。
- `{"type":"custom","instructions":"Free-form reviewer instructions"}` — 等价于遗留手动审查请求的回退提示。
- `delivery`（`"inline"` 或 `"detached"`，默认 `"inline"`）— 审查在何处运行：
  - `"inline"`：在现有 thread 上作为新 turn 运行审查。响应的 `reviewThreadId` 等于原始 `threadId`，不会发出新的 `thread/started` 通知。
  - `"detached"`：从父对话分叉新的 review thread，并在那里运行审查。响应的 `reviewThreadId` 是此新 review thread 的 id，服务器在流动 review item 之前会为其发出 `thread/started` 通知。

示例请求 / 响应：

```json
{ "method": "review/start", "id": 40, "params": {
    "threadId": "thr_123",
    "delivery": "inline",
    "target": { "type": "commit", "sha": "1234567deadbeef", "title": "Polish tui colors" }
} }
{ "id": 40, "result": {
    "turn": {
        "id": "turn_900",
        "status": "inProgress",
        "items": [
            { "type": "userMessage", "id": "turn_900", "content": [ { "type": "text", "text": "Review commit 1234567: Polish tui colors" } ] }
        ],
        "error": null
    },
    "reviewThreadId": "thr_123"
} }
```

对于分离式 review，使用 `"delivery": "detached"`。响应形状相同，但 `reviewThreadId` 将是新 review thread 的 id（与原始 `threadId` 不同）。服务器还会在流动 review turn 之前为该新 thread 发出 `thread/started` 通知。在内部，这是一个普通分叉 thread 和 turn，其 prompt 提及捆绑的 `$review-agent` skill，因此普通 turn 引导、工具、权限和 item 流行为适用。

当父 thread 是分页的时，分离式 review 不受支持。

对于内联 review，Codex 会流动通常的 `turn/started` 通知，随后是带有 `enteredReviewMode` item 的 `item/started`，以便客户端可以展示进度：

```json
{
  "method": "item/started",
  "params": {
    "item": {
      "type": "enteredReviewMode",
      "id": "turn_900",
      "review": "current changes"
    }
  }
}
```

当审查器完成时，服务器发出包含带最终审查文本的 `exitedReviewMode` item 的 `item/started` 和 `item/completed`：

```json
{
  "method": "item/completed",
  "params": {
    "item": {
      "type": "exitedReviewMode",
      "id": "turn_900",
      "review": "Looks solid overall...\n\n- Prefer Stylize helpers — app.rs:10-20\n  ..."
    }
  }
}
```

`review` 字符串是纯文本，已经捆绑了总体说明以及对每个结构化发现的要点列表（与生成 schema 中的 `ThreadItem::ExitedReviewMode` 匹配）。用此通知在客户端中渲染审查器输出。

### 示例：一次性命令执行

在服务器沙箱中运行独立命令（argv 向量），而不创建 thread 或 turn：

```json
{ "method": "command/exec", "id": 32, "params": {
    "command": ["ls", "-la"],
    "processId": "ls-1",                           // 可选字符串；流式传输和终止进程所需
    "cwd": "/Users/me/project",                    // 可选；默认为服务器 cwd
    "env": { "FOO": "override" },                  // 可选；合并到服务器环境并覆盖同名项
    "size": { "rows": 40, "cols": 120 },           // 可选；以字符单元格计的 PTY 大小，仅在 tty=true 时有效
    "permissionProfile": ":workspace",             // 可选配置文件 id；默认为用户配置
    "outputBytesCap": 1048576,                     // 可选；每流捕获上限
    "disableOutputCap": false,                     // 可选；不能与 outputBytesCap 同时使用
    "timeoutMs": 10000,                            // 可选；毫秒超时；默认为服务器超时
    "disableTimeout": false                        // 可选；不能与 timeoutMs 同时使用
} }
{ "id": 32, "result": {
    "exitCode": 0,
    "stdout": "...",
    "stderr": ""
} }
```

- 当你想要显式无沙箱的进程执行 API，并带有立即 spawn 确认、基于句柄的控制、输出通知以及退出通知时，优先使用 `process/spawn`。
- 对于已经在外部被沙箱化的客户端，将遗留 `sandboxPolicy` 设为 `{"type":"externalSandbox","networkAccess":"enabled"}`（或省略 `networkAccess` 以保持受限）。Codex 在此模式下不会强制执行自己的沙箱；它告诉模型它具有完整文件系统访问，并通过 `environment_context` 传递 `networkAccess` 状态。

说明：

- 空 `command` 数组会被拒绝。
- 命令权限覆盖优先使用 `permissionProfile`。它按 id 选择活动配置文件（例如 `:read-only`、`:workspace`，或用户定义的 `[permissions.<id>]` 配置文件），而不是接受低级文件系统 / 网络权限。遗留 `sandboxPolicy` 字段接受与 `turn/start` 相同的形状（例如 `dangerFullAccess`、`readOnly`、带标志的 `workspaceWrite`、带 `networkAccess` `restricted|enabled` 的 `externalSandbox`），但不能与 `permissionProfile` 同时使用。
- `env` 合并到服务器 shell 环境策略产生的环境中。同名项被覆盖；未指定的变量保持不变。
- 省略时，`timeoutMs` 回退到服务器默认值。
- 省略时，`outputBytesCap` 回退到每流 1 MiB 的服务器默认值。
- `disableOutputCap: true` 禁用该 `command/exec` 请求的 stdout/stderr 捕获截断。它不能与 `outputBytesCap` 同时使用。
- `disableTimeout: true` 完全禁用该 `command/exec` 请求的超时。它不能与 `timeoutMs` 同时使用。
- 缓冲执行时 `processId` 可选。省略时，Codex 会生成内部 id 用于生命周期跟踪，但 `tty`、`streamStdin` 和 `streamStdoutStderr` 必须保持禁用，并且后续 `command/exec/write` / `command/exec/terminate` 调用对该命令不可用。
- `size` 仅在 `tty: true` 时有效。它以字符单元格设置初始 PTY 大小。
- 缓冲的 Windows 沙箱执行接受 `processId` 用于关联，但这些请求仍不支持 `command/exec/write` 和 `command/exec/terminate`。
- 缓冲的 Windows 沙箱执行还需要默认输出上限；那里不支持自定义 `outputBytesCap` 和 `disableOutputCap`。
- `tty`、`streamStdin` 和 `streamStdoutStderr` 是可选布尔值。省略它们的遗留请求继续使用缓冲执行。
- `tty: true` 意味着 PTY 模式加上 `streamStdin: true` 和 `streamStdoutStderr: true`。
- `tty` 和 `streamStdin` 本身不会禁用超时；省略 `timeoutMs` 以使用服务器默认超时，或设 `disableTimeout: true` 以使进程保持存活直到退出或显式终止。
- `outputBytesCap` 独立应用于 `stdout` 和 `stderr`，流式字节不会复制到最终响应中。
- `command/exec` 响应会延迟到进程退出，并且仅在该连接的所有 `command/exec/outputDelta` 通知发出之后才发送。
- `command/exec/outputDelta` 通知是连接作用域的。若发起连接关闭，服务器会终止该进程。

流式 stdin/stdout 使用 base64，以便 PTY 会话可以承载任意字节：

```json
{ "method": "command/exec", "id": 33, "params": {
    "command": ["bash", "-i"],
    "processId": "bash-1",
    "tty": true,
    "outputBytesCap": 32768
} }
{ "method": "command/exec/outputDelta", "params": {
    "processId": "bash-1",
    "stream": "stdout",
    "deltaBase64": "YmFzaC00LjQkIA==",
    "capReached": false
} }
{ "method": "command/exec/write", "id": 34, "params": {
    "processId": "bash-1",
    "deltaBase64": "cHdkCg=="
} }
{ "id": 34, "result": {} }
{ "method": "command/exec/write", "id": 35, "params": {
    "processId": "bash-1",
    "closeStdin": true
} }
{ "id": 35, "result": {} }
{ "method": "command/exec/resize", "id": 36, "params": {
    "processId": "bash-1",
    "size": { "rows": 48, "cols": 160 }
} }
{ "id": 36, "result": {} }
{ "method": "command/exec/terminate", "id": 37, "params": {
    "processId": "bash-1"
} }
{ "id": 37, "result": {} }
{ "id": 33, "result": {
    "exitCode": 137,
    "stdout": "",
    "stderr": ""
} }
```

- `command/exec/write` 接受 `deltaBase64`、`closeStdin` 或两者。
- 客户端可以在 `command/exec` 中提供连接作用域字符串 `processId`；`command/exec/write`、`command/exec/resize` 和 `command/exec/terminate` 仅接受这些客户端提供的字符串 id。
- `command/exec/outputDelta.processId` 始终是原始 `command/exec` 请求中客户端提供的字符串 id。
- `command/exec/outputDelta.stream` 为 `stdout` 或 `stderr`。PTY 模式通过 `stdout` 复用终端输出。
- 当 `outputBytesCap` 截断某个流时，该流的最后一块流式数据上 `command/exec/outputDelta.capReached` 为 `true`；该流上的后续输出会被丢弃。
- `command/exec.params.env` 按键覆盖服务器计算的环境；将某个键设为 `null` 以取消设置继承的变量。
- `command/exec/resize` 仅支持基于 PTY 的 `command/exec` 会话。

### 示例：进程生命周期执行

用 `process/spawn` 在 app server 所在主机上启动独立的、基于 argv 的进程，而不经过 Codex 沙箱。`process/*` API 是实验性的，需要 `initialize.params.capabilities.experimentalApi: true`。spawn 响应意味着进程已启动且 `processHandle` 已注册；完成稍后通过 `process/exited` 报告。

```json
{ "method": "process/spawn", "id": 40, "params": {
    "command": ["cargo", "check"],
    "processHandle": "cargo-check-1",
    "cwd": "/Users/me/project",                    // 必需的绝对路径
    "env": { "RUST_LOG": null },                    // 可选；覆盖或取消设置 app-server 环境变量
    "outputBytesCap": 1048576,                     // 可选；省略为默认，null 禁用
    "timeoutMs": 10000                             // 可选；省略为默认，null 禁用
} }
{ "id": 40, "result": {} }
{ "method": "process/exited", "params": {
    "processHandle": "cargo-check-1",
    "exitCode": 0,
    "stdout": "...",
    "stdoutCapReached": false,
    "stderr": "",
    "stderrCapReached": false
} }
```

对于交互式或流式进程，设 `tty: true` 或 `streamStdoutStderr: true`，并按 `processHandle` 路由输出通知：

```json
{ "method": "process/spawn", "id": 41, "params": {
    "command": ["bash", "-i"],
    "processHandle": "bash-1",
    "cwd": "/Users/me/project",
    "tty": true,
    "size": { "rows": 40, "cols": 120 },
    "outputBytesCap": null,
    "timeoutMs": null
} }
{ "id": 41, "result": {} }
{ "method": "process/outputDelta", "params": {
    "processHandle": "bash-1",
    "stream": "stdout",
    "deltaBase64": "YmFzaC00LjQkIA==",
    "capReached": false
} }
{ "method": "process/writeStdin", "id": 42, "params": {
    "processHandle": "bash-1",
    "deltaBase64": "cHdkCg=="
} }
{ "id": 42, "result": {} }
{ "method": "process/resizePty", "id": 43, "params": {
    "processHandle": "bash-1",
    "size": { "rows": 48, "cols": 160 }
} }
{ "id": 43, "result": {} }
{ "method": "process/kill", "id": 44, "params": {
    "processHandle": "bash-1"
} }
{ "id": 44, "result": {} }
{ "method": "process/exited", "params": {
    "processHandle": "bash-1",
    "exitCode": 137,
    "stdout": "",
    "stdoutCapReached": false,
    "stderr": "",
    "stderrCapReached": false
} }
```

- 空 `command` 数组和空 `processHandle` 字符串会被拒绝。
- `cwd` 是必需的，且必须是绝对路径。
- `process/spawn` 有意无沙箱，并且不定义诸如 `sandboxPolicy` 或 `permissionProfile` 的沙箱选择字段。
- 同一连接上重复的活动 `processHandle` 值会被拒绝；先前进程退出后可以重用同一句柄。
- `tty: true` 意味着 PTY 模式加上 `streamStdin: true` 和 `streamStdoutStderr: true`。
- `process/writeStdin` 接受 `deltaBase64`、`closeStdin` 或两者。
- 省略时，`timeoutMs` 和 `outputBytesCap` 回退到服务器默认值。将任一字段设为 `null` 可为终端风格会话禁用该限制。
- `outputBytesCap` 独立应用于 `stdout` 和 `stderr`；`process/exited.stdoutCapReached` 和 `stderrCapReached` 报告每个流是否达到上限。流式字节不会复制到 `process/exited` 中。
- `process/outputDelta` 和 `process/exited` 通知是连接作用域的。若发起连接关闭，服务器会终止该进程。

### 示例：文件系统工具

这些方法在主机文件系统的绝对路径上操作，覆盖读取、写入、目录遍历、复制、删除和变更通知。

本节中的所有文件系统路径必须是绝对路径。

```json
{ "method": "fs/createDirectory", "id": 40, "params": {
    "path": "/tmp/example/nested",
    "recursive": true
} }
{ "id": 40, "result": {} }
{ "method": "fs/writeFile", "id": 41, "params": {
    "path": "/tmp/example/nested/note.txt",
    "dataBase64": "aGVsbG8="
} }
{ "id": 41, "result": {} }
{ "method": "fs/getMetadata", "id": 42, "params": {
    "path": "/tmp/example/nested/note.txt"
} }
{ "id": 42, "result": {
    "isDirectory": false,
    "isFile": true,
    "isSymlink": false,
    "createdAtMs": 1730910000000,
    "modifiedAtMs": 1730910000000
} }
{ "method": "fs/readFile", "id": 43, "params": {
    "path": "/tmp/example/nested/note.txt"
} }
{ "id": 43, "result": {
    "dataBase64": "aGVsbG8="
} }
```

- `fs/getMetadata` 返回路径是否解析为目录或常规文件、路径本身是否为符号链接，以及 Unix 毫秒的 `createdAtMs` 和 `modifiedAtMs`。若当前平台上时间戳不可用，该字段为 `0`。
- 省略时，`fs/createDirectory` 将 `recursive` 默认为 `true`。
- 省略时，`fs/remove` 将 `recursive` 和 `force` 都默认为 `true`。
- `fs/readFile` 始终通过 `dataBase64` 返回 base64 字节，`fs/writeFile` 始终期望 `dataBase64` 中的 base64 字节。
- `fs/copy` 同时处理文件复制和目录树复制；当 `sourcePath` 是目录时需要 `recursive: true`。递归复制会遍历常规文件、目录和符号链接；其他条目类型会被跳过。

### 示例：文件系统监视

`fs/watch` 接受绝对文件或目录路径。监视文件会为该文件路径发出 `fs/changed`，包括通过替换或重命名操作投递的更新。

```json
{ "method": "fs/watch", "id": 44, "params": {
    "watchId": "0195ec6b-1d6f-7c2e-8c7a-56f2c4a8b9d1",
    "path": "/Users/me/project/.git/HEAD"
} }
{ "id": 44, "result": {
    "path": "/Users/me/project/.git/HEAD"
} }
{ "method": "fs/changed", "params": {
    "watchId": "0195ec6b-1d6f-7c2e-8c7a-56f2c4a8b9d1",
    "changedPaths": ["/Users/me/project/.git/HEAD"]
} }
{ "method": "fs/unwatch", "id": 45, "params": {
    "watchId": "0195ec6b-1d6f-7c2e-8c7a-56f2c4a8b9d1"
} }
{ "id": 45, "result": {} }
```

## 事件

事件通知是服务器发起的事件流，用于 thread 生命周期、turn 生命周期以及其中的 item。启动或恢复 thread 后，持续从 stdout 读取 `thread/started`、`thread/archived`、`thread/unarchived`、`thread/closed`、`turn/*` 和 `item/*` 通知。

Thread realtime 会在其现有 realtime 通知之外，为分页 thread 发布 thread 作用域的时间线 item 生命周期通知。已完成的时间线 item 由 `thread/timeline/list` 与普通 turn item 持久交错。任一表面都不会改变 `ThreadItem`、`thread/read`、`thread/resume` 或 `thread/fork`；客户端忽略它们无法识别的通知方法。

每个 realtime item 都有 `id`、`realtimeSessionId`，以及四种类型之一：`realtimeSessionStarted`、`transcriptSegment`、`bemItemPromoted` 或 `realtimeSessionClosed`。`bemItemPromoted` item 通过 `turnId` 和 `itemId` 引用现有 backing-agent item；其 `presentation` 为 `wholeItem`、`inlineMarkdown` 或带 `index` 的 `inlineVisualization`。

可恢复的配置和初始化警告使用现有 `configWarning` 通知：`{ summary, details?, path?, range? }`。App-server 可能在初始化期间为配置解析和相关设置诊断发出它，或在 `thread/start` 期间向请求连接发出，当该 thread 的 exec-policy 规则解析失败时。

通用运行时警告使用 `warning` 通知：`{ threadId?, message }`。App-server 为核心事件流中的非致命警告发出此通知，包括并非所有已启用 skill 都被包含在会话的模型可见 skill 列表中的情况。

### 通知选择退出

客户端可以通过在 `initialize.params.capabilities.optOutNotificationMethods` 中发送精确方法名，按连接抑制特定通知。

- 仅精确匹配：`item/agentMessage/delta` 只抑制该方法。
- 未知方法名会被忽略。
- 适用于 app-server 类型化通知，例如 `thread/*`、`turn/*`、`item/*` 和 `rawResponseItem/*`。
- 不适用于请求 / 响应 / 错误。

示例：

- 选择退出 thread 生命周期通知：`thread/started`
- 选择退出流式 agent 文本增量：`item/agentMessage/delta`

### 模糊文件搜索事件（实验性）

模糊文件搜索会话 API 发出按查询的通知：

- `fuzzyFileSearch/sessionUpdated` — `{ sessionId, query, files }`，带有活动查询的当前匹配文件。
- `fuzzyFileSearch/sessionCompleted` — `{ sessionId, query }`，一旦该查询的索引 / 匹配完成。

### Thread realtime 事件（实验性）

Thread realtime API 为会话生命周期和流式媒体发出 thread 作用域通知：

- `thread/realtime/started` — `{ threadId, realtimeSessionId }`，一旦该 thread 的 realtime 启动（实验性）。`realtimeSessionId` 是上游 Realtime API 会话标识符，而不是 Codex 会话 / thread-group id。
- `thread/realtime/itemAdded` — `{ threadId, item }`，用于没有专用类型化 app-server 通知的原始非音频 realtime item，包括 `handoff_request`（实验性）。在上游 websocket item schema 仍不稳定时，`item` 作为原始 JSON 转发。
- `thread/realtime/transcript/delta` — `{ threadId, role, delta }`，用于实时 realtime 转写增量（实验性）。
- `thread/realtime/transcript/done` — `{ threadId, role, text }`，当 realtime 为某个转写部分发出最终完整文本时（实验性）。
- `thread/realtime/item/started` — `{ threadId, item }`，当 realtime item 开始时。会话边界和产物立即完成；转写段 ID 在流式传输和持久化期间保持稳定（实验性）。
- `thread/realtime/item/transcript/delta` — `{ threadId, itemId, delta }`，用于追加到已开始转写段的文本（实验性）。
- `thread/realtime/item/completed` — `{ threadId, item }`，在会话边界、转写段或已提升的 backing-agent 产物被持久提交之后（实验性）。
- `thread/realtime/outputAudio/delta` — `{ threadId, audio }`，用于流式输出音频块（实验性）。`audio` 使用 camelCase 字段（`data`、`sampleRate`、`numChannels`、`samplesPerChannel`）。
- `thread/realtime/error` — `{ threadId, message }`，当 realtime 遇到传输或后端错误时（实验性）。
- `thread/realtime/closed` — `{ threadId, reason }`，当 realtime 传输关闭时（实验性）。

因为音频有意与 `ThreadItem` 分开，客户端可以用 `optOutNotificationMethods` 独立选择退出 `thread/realtime/outputAudio/delta`。

### Windows 沙箱设置事件

- `windowsSandbox/setupCompleted` — `{ mode, success, error }`，在 `windowsSandbox/setupStart` 请求完成后。

### MCP server 启动事件

- `mcpServer/startupStatus/updated` — `{ threadId, name, status, error, failureReason }`，当 app-server 观察到 MCP server 启动转换时。当启动是 thread 作用域时 `threadId` 标识拥有该启动的 thread，当启动是 app 作用域时为 `null`。`status` 为 `starting`、`ready`、`failed` 或 `cancelled` 之一。除 `failed` 外，`error` 和 `failureReason` 为 `null`；当已存储 OAuth 凭据过期且无法刷新时，`failureReason` 为 `reauthenticationRequired`，因此客户端可以提示用户重新连接该命名 server。

### Turn 事件

Turn 运行时，app-server 会流动 JSON-RPC 通知。每个 turn 在开始运行时发出 `turn/started`，并以 `turn/completed`（最终 `turn` 状态）结束。Token 用量事件通过 `thread/tokenUsage/updated` 单独流动。客户端订阅它们关心的事件，在更新到达时增量渲染每个 item。每 item 生命周期始终是：`item/started` → 零个或多个 item 特定增量 → `item/completed`。

- `turn/started` — `{ turn }`，带有 turn id、空 `items` 和 `status: "inProgress"`。
- `turn/completed` — `{ turn }`，其中 `turn.status` 为 `completed`、`interrupted` 或 `failed`；成功 turn 在可用时包含其最终 agent 消息，失败则携带 `{ error: { message, codexErrorInfo?, additionalDetails?, misalignment? } }`。
- `turn/diff/updated` — `{ threadId, turnId, diff }` 表示 turn 级 unified diff 的最新快照，在每个 FileChange item 之后发出。`diff` 是该 turn 中每个文件变更的最新聚合 unified diff。UI 可以渲染它以展示完整的“改了什么”视图，而不必拼接单个 `fileChange` item。
- `turn/plan/updated` — `{ turnId, explanation?, plan }`，每当 agent 分享或更改其计划时；每个 `plan` 条目为 `{ step, status }`，`status` 为 `pending`、`inProgress` 或 `completed`。
- `rawResponse/completed` — 仅内部；当启用 `thread/start.experimentalRawEvents` 时，对每次上游 Responses API 完成发出一次 `{ threadId, turnId, responseId, usage }`。`usage` 是映射到 app-server token 分解形状的精确上游用量载荷，当上游完成省略用量时为 `null`。与 `thread/tokenUsage/updated` 不同，此通知不会被累计、估算、持久化或重放。
- `model/safetyBuffering/updated` — `{ threadId, turnId, model, useCases, reasons, showBufferingUi, fasterModel }`，当响应进入安全缓冲时。`fasterModel` 可空。此通知是瞬时的，不会持久化到 rollout 历史中。
- `model/rerouted` — `{ threadId, turnId, fromModel, toModel, reason }`，当后端将请求改向到不同模型时（例如由于高风险网络空间安全检查）。
- `model/verification` — `{ threadId, turnId, verifications }`，当后端标记额外账户验证时，例如 `trustedAccessForCyber`。
- `turn/moderationMetadata` — 实验性；`{ threadId, turnId, metadata }`，当第一方后端提供用于客户端展示的 turn 作用域审核元数据时。

`turn/started` 不携带 item。`turn/completed` 仅将最终 agent 消息作为摘要回退携带；继续消费 `item/*` 通知以获取完整规范 item 列表。

#### Items

`ThreadItem` 是 turn 响应和 `item/*` 通知中携带的带标签联合。目前我们支持以下 item 的事件：

- `userMessage` — `{id, clientId, content}`，其中 `clientId` 是提供给 `turn/start` 或 `turn/steer` 的可选 `clientUserMessageId`，`content` 是用户输入列表（`text`、`image`、`localImage`、`audio` 或 `localAudio`）。
- `functionCallOutput` — `{id, name, namespace, output}`，用于没有 `call_id` 的独立 function-call 输出。`namespace` 可空，`output` 是字符串或结构化内容 item。客户端决定是否渲染这些工具权威 item；普通成对 function-call 输出不会单独发出。
- `agentMessage` — `{id, text, phase, memoryCitation, delivery}`，包含累计的 agent 回复。`delivery: "async"` 标识在不结束当前 turn 的情况下发送的用户可见消息；普通 agent 消息具有 `delivery: null`。
- `plan` — `{id, text}`，为 plan 模式 turn 发出；计划文本可以通过 `item/plan/delta` 流动（实验性）。
- `reasoning` — `{id, summary, content}`，其中 `summary` 保存流式推理摘要（适用于大多数 OpenAI 模型），`content` 保存原始推理块（适用于例如开源模型）。
- `commandExecution` — `{id, pluginId?, scriptPath?, command, cwd, status, commandActions, aggregatedOutput?, exitCode?, durationMs?}`，用于沙箱命令；`pluginId` 仅对归因于受信任第一方 plugin 的命令存在，新归因的 item 还将 `scriptPath` 作为相对受信任 plugin 根的安全 `/` 分隔路径包含，更旧历史可能省略 `scriptPath`，`status` 为 `inProgress`、`completed`、`failed` 或 `declined`。普通执行 item 及其重放将 `command` 和 `commandActions` 暴露为脱敏显示值，而不是可执行命令。
  `cwd` 和读取的 `commandActions[].path` 使用执行器的原生路径约定，即使 app-server 运行在不同操作系统上。例如，运行在 Linux 上的 app-server 可以为 Windows 执行器返回 `C:\repo\src\main.rs`；客户端不得将该路径解释为 app-server 本地路径。
- `fileChange` — `{id, changes, status}`，描述提议的编辑；`changes` 列出 `{path, kind, diff}`，`status` 为 `inProgress`、`completed`、`failed` 或 `declined`。
- `mcpToolCall` — `{id, server, tool, status, arguments, appContext, mcpAppResourceUri?, pluginId, readOnlyHint, result?, error?}`，描述 MCP 调用；对通过受信任 MCP app 的调用，`appContext` 为 `{connectorId, linkId, resourceUri, appName, actionName}`，其中 `connectorId` 标识拥有该工具的连接器，`linkId` 标识 app 链接，`resourceUri` 指向 widget 模板，`appName` 是连接器的显示名称，`actionName` 是稳定的连接器 `Action.name`。对只读工具 `readOnlyHint` 为 `true`，对可写工具为 `false`，当注解不可用时（包括更旧 rollout 条目）为 `null`。该提示描述工具能力，而不是调用是否成功或执行了写入；用 `status`、`result` 和 `error` 确定执行结果。对更旧 rollout 条目，`appName` 和 `actionName` 可能为 null。顶层 `mcpAppResourceUri` 已弃用，并暂时为客户端迁移而重复。`tool` 标识原始 MCP 工具。`status` 为 `inProgress`、`completed` 或 `failed`。
- `collabToolCall` — `{id, tool, status, senderThreadId, receiverThreadId?, newThreadId?, prompt?, agentStatus?}`，描述协作工具调用（`spawn_agent`、`send_input`、`resume_agent`、`wait`、`close_agent`）；`status` 为 `inProgress`、`completed` 或 `failed`。
- `subAgentActivity` — `{id, kind, agentThreadId, agentPath}`，描述 Multi-Agent V2 生命周期活动；`kind` 为 `started`、`interacted`、`interrupted` 或 `completed`。成功的子级完成归因于生成它的父 turn，因此其 `item/completed` 通知可能在该 turn 的 `turn/completed` 通知之后到达，并在读取历史时包含在该 turn 中。

  `CollabAgentTool` schema 还包括用于私有 Multi-Agent V2 分析的 `sendMessage`、`followupTask`、`interruptAgent` 和 `listAgents`。这些调用不会发出公共协作者工具 item；它们现有的 `subAgentActivity` 通知保持不变，且 `list_agents` 不发出活动 item。在处理器执行期间取消的调用会以状态 `interrupted` 私下记录，与工具失败不同。
- `webSearch` — `{id, query, action?, results?}`，用于 agent 发出的网络搜索请求；`action` 镜像 Responses API web_search action 载荷（`search`、`open_page`、`find_in_page`），并且可能在完成前省略。对于独立网络搜索，`results` 包含 `/v1/alpha/search` 返回的带外结构化结果 DTO；客户端应忽略它们不理解的结果类型和字段。
- `imageGeneration` — `{id, status, revisedPrompt, result, transparentBackground, savedPath?}`，用于生成的图片。当 Images API 报告透明背景时 `transparentBackground` 为 `true`，报告不透明背景时为 `false`，当背景是自动、不可用或该 item 尚未完成时为 `null`。该字段始终存在于 v2 item 载荷上，包括持久化和恢复的 item。
- `imageView` — `{id, path}`，当 agent 调用图片查看器工具时发出。
- `sleep` — `{id, durationMs}`，当 agent 等待一段时间或新输入时发出。
- `enteredReviewMode` — `{id, review}`，当审查器开始时发送；`review` 是简短的面向用户标签，例如 `"current changes"` 或请求的目标描述。
- `exitedReviewMode` — `{id, review}`，当审查器完成时发出；`review` 是完整纯文本审查（通常是总体说明加上要点发现）。
- `contextCompaction` — `{id}`，当 Codex 压缩对话历史时发出。这可以自动发生。
- `compacted` — `{threadId, turnId}`，当 Codex 压缩对话历史时。这可以自动发生。**已弃用：** 请改用 `contextCompaction`。

所有 item 发出共享生命周期事件：

- `item/started` — 在新工作单元开始时发出完整 `item`，以便 UI 可以立即渲染它；此载荷中的 `item.id` 与增量使用的 `itemId` 匹配。
- `item/completed` — 一旦该工作本身完成（例如工具调用或消息完成后）发送最终 `item`；将其视为权威执行 / 结果状态。
- `item/autoApprovalReview/started` — [不稳定] 临时自动审查通知，在审批自动审查开始时携带 `{threadId, turnId, targetItemId, review, action}`。此形状预计很快会改变。
- `item/autoApprovalReview/completed` — [不稳定] 临时自动审查通知，在审批自动审查解决时携带 `{threadId, turnId, targetItemId, review, action}`。此形状预计很快会改变。
- `autoApprovalReview/strictReviewRequired` — 实验性通知，每当提升或过期的 Guardian v2 风险需要同步审批审查时携带 `{threadId, turnId, startedAtMs}`。

`review` 是 [不稳定] 的，目前具有 `{status, riskLevel?, userAuthorization?, rationale?}`，其中 `status` 为 `inProgress`、`approved`、`denied` 或 `aborted` 之一。存在时 `riskLevel` 为 `"low"`、`"medium"`、`"high"` 或 `"critical"` 之一。存在时 `userAuthorization` 为 `"unknown"`、`"low"`、`"medium"` 或 `"high"` 之一。`action` 是带标签联合，`type: "command" | "execve" | "writeStdin" | "applyPatch" | "networkAccess" | "mcpToolCall" | "requestPermissions"`。类似命令的操作包含 `source` 判别器（`"shell"` 或 `"unifiedExec"`）。`writeStdin` 操作携带 `approvalId`、`processId`、`stdin` 和 `cwd`；它审查对现有命令 item 的输入，而不改变该父 item 的生命周期。这些通知与目标 item 自己的 `item/completed` 生命周期分开，并且在自动审查 app 协议仍在设计时有意是临时的。

还有额外的 item 特定事件：

#### agentMessage

- `item/agentMessage/delta` — 追加 agent 消息的流式文本；按顺序拼接同一 `itemId` 的 `delta` 值以重建完整回复。

#### plan

- `item/plan/delta` — 为 plan item 流动提议的计划内容（实验性）；拼接同一 plan `itemId` 的 `delta` 值。这些增量对应 `<proposed_plan>` 块。

#### reasoning

- `item/reasoning/summaryTextDelta` — 流动可读推理摘要；当新摘要节打开时 `summaryIndex` 递增。
- `item/reasoning/summaryPartAdded` — 标记某个 `itemId` 的推理摘要节之间的边界；后续 `summaryTextDelta` 条目共享同一 `summaryIndex`。
- `item/reasoning/textDelta` — 流动原始推理文本（仅适用于例如开源模型）；用 `contentIndex` 将属于一起的增量分组，然后再在 UI 中显示它们。

#### commandExecution

- `item/commandExecution/outputDelta` — 为命令流动 stdout/stderr；按顺序追加增量，以便与最终 item 中的 `aggregatedOutput` 一起渲染实时输出。
  最终 `commandExecution` item 包含解析后的 `commandActions`、`status`、`exitCode` 和 `durationMs`，以便 UI 可以总结运行了什么以及是否成功。

#### fileChange

- `item/fileChange/patchUpdated` — 当启用 `features.apply_patch_streaming_events` 时，流动从模型生成的补丁中解析出的结构化文件变更快照，然后才执行它。
- `item/fileChange/outputDelta` — 已弃用的遗留协议条目，用于 `apply_patch` 文本输出；为兼容性而保留，但服务器不再发出。

### 错误

对父级拥有的 Multi-Agent V2 子 agent 的所有权拒绝返回 JSON-RPC 错误码 `-32600`，消息为 `direct app-server input is not allowed for multi-agent v2 sub-agents`。

每当服务器在 turn 中途遇到错误（例如上游模型错误或配额限制）时发出 `error` 事件。携带与 `turn.status: "failed"` 相同的 `{ error: { message, codexErrorInfo?, additionalDetails?, misalignment? } }` 载荷，并且可能先于该终止通知。

`codexErrorInfo` 映射到 `CodexErrorInfo` 枚举。常见值：

- `ContextWindowExceeded`
- `SessionBudgetExceeded`
- `UsageLimitExceeded`
- `rateLimitExceeded`：在流式响应内部收到的上游速率限制；仅在其现有流重试预算耗尽后，该 turn 才以此类别失败
- `misalignmentPolicyViolation`：被错位策略阻止的不可重试请求
- `HttpConnectionFailed { httpStatusCode? }`：上游 HTTP 失败，包括 4xx/5xx
- `ResponseStreamConnectionFailed { httpStatusCode? }`：无法连接到响应 SSE 流
- `ResponseStreamDisconnected { httpStatusCode? }`：在 turn 完成前中途断开响应 SSE 流
- `ResponseTooManyFailedAttempts { httpStatusCode? }`
- `ActiveTurnNotSteerable { turnKind }`：在当前活动 turn 不可引导时提交了 `turn/start` 或 `turn/steer`，例如 `/review` 或手动 `/compact`
- `BadRequest`
- `Unauthorized`
- `SandboxError`
- `InternalServerError`
- `Other`：所有未分类错误

当上游 HTTP 状态可用时（例如来自 Responses API 或某个 provider），它会在相关 `codexErrorInfo` 变体的 `httpStatusCode` 中转发。

对于 `misalignmentPolicyViolation`，可选 `misalignment` 详情包含 `errorType`、`detailedExplanation` 以及 `steer: { message }`。错误类别是开放的。仅类别仍是终止阻止；仅当同时存在实质性说明和引导消息时，客户端才可以提供继续。要在用户确认后继续，用现有 `turn/start` 方法提交引导消息，并包含 `responsesapiClientMetadata: { misalignment_override: JSON.stringify({ timestamp, feedback }) }`，其中 `timestamp` 是 Unix 毫秒的确认时间，`feedback` 是用户的说明。错位说明和引导详情会实时投递，但会从持久化 rollout 错误中排除，因此重启后不可用的详情仍是终止阻止。

## 审批

某些操作（shell 命令或修改文件）可能根据用户配置需要显式用户审批。使用 `turn/start` 时，app-server 通过向客户端发送服务器发起的 JSON-RPC 请求来驱动审批流程。客户端必须响应以告诉 Codex 是否继续。UI 应在活动 turn 中内联展示这些请求，以便用户在选择前审查提议的命令或 diff。

- 请求包含 `threadId` 和 `turnId`——用它们将 UI 状态限定到活动对话。
- 用单个 `{ "decision": ... }` 载荷响应。命令审批支持 `accept`、`acceptForSession`、`acceptWithExecpolicyAmendment`、`applyNetworkPolicyAmendment`、`decline` 或 `cancel`。服务器恢复或拒绝该工作，并以 `item/completed` 结束该 item。

### 命令执行审批

消息顺序：

1. `item/started` — 展示待处理 `commandExecution` item，带有 `command`、`cwd` 和其他字段，以便你可以渲染提议的操作。
2. `item/commandExecution/requestApproval`（请求）— 携带相同的 `itemId`、`threadId`、`turnId`、命令将运行的可空 `environmentId`、`kind`（`command` 或 `writeStdin`）、可选 `approvalId`（用于子命令回调或 stdin 写入）以及 `reason`。新的 shell 和 unified-exec 审批会设置 `environmentId`；不提供它的更旧事件暴露为 `null`。对于普通命令审批，请求还包含用于友好显示的 `command`、`cwd` 和 `commandActions`。当 `initialize.params.capabilities.experimentalApi = true` 时，它还可能包含描述请求的按命令沙箱访问的实验性 `additionalPermissions`；该载荷中的任何文件系统路径在线上都是绝对路径，网络访问表示为 `additionalPermissions.network.enabled`。对于仅网络审批，那些命令字段可能被省略，并改为提供 `networkApprovalContext`。还可能通过 `proposedExecpolicyAmendment` 和 `proposedNetworkPolicyAmendments` 包含可选持久化提示。存在时客户端可以优先使用 `availableDecisions` 来渲染服务器想要暴露的精确选择集，若省略则仍回退到更旧启发式。
3. 客户端响应 — 例如 `{ "decision": "accept" }`、`{ "decision": "acceptForSession" }`、`{ "decision": { "acceptWithExecpolicyAmendment": { "execpolicy_amendment": [...] } } }`、`{ "decision": { "applyNetworkPolicyAmendment": { "network_policy_amendment": { "host": "example.com", "action": "allow" } } } }`、`{ "decision": "decline" }` 或 `{ "decision": "cancel" }`。
4. `serverRequest/resolved` — `{ threadId, requestId }` 确认待处理请求已解决或清除，包括 turn 开始 / 完成 / 中断时的生命周期清理。
5. `item/completed` — 最终 `commandExecution` item，带有 `status: "completed" | "failed" | "declined"` 以及执行输出。将其渲染为权威结果。

`kind` 将命令审批与对现有终端的写入区分开。没有 `kind` 的更旧服务器请求保留 `command` 语义；仅 `approvalId` 不能将 stdin 写入与 execve 拦截区分开。

启用 stdin 审批时，`write_stdin` 审批设置 `kind: "writeStdin"`，引用原始终端命令的 `itemId`，并有自己的 `approvalId`。该请求属于当前 turn，可能与打开终端的 turn 不同。使用 `approvalsReviewer: "auto_review"` 时，`item/autoApprovalReview/*` 通知同样以原始命令 item 为目标，并携带类型为 `writeStdin` 的操作，带有 `approvalId`、`processId`、`stdin` 和 `cwd`。对于 stdin 审批，`cwd` 是终端的启动目录，而不是其当前工作目录。批准或拒绝 stdin 写入不会开始、完成或改变父命令执行 item 的状态。

### 文件变更审批

消息顺序：

1. `item/started` — 发出带有 `changes`（diff 块摘要）和 `status: "inProgress"` 的 `fileChange` item。向用户展示提议的编辑和路径。
2. `item/fileChange/requestApproval`（请求）— 包含 `itemId`、`threadId`、`turnId`、可选 `reason`，并且当 agent 请求特定根下的会话作用域写访问时可能包含不稳定的 `grantRoot`。
3. 客户端响应 — `{ "decision": "accept" }`、`{ "decision": "acceptForSession" }`、`{ "decision": "decline" }` 或 `{ "decision": "cancel" }`。
4. `serverRequest/resolved` — `{ threadId, requestId }` 确认待处理请求已解决或清除，包括 turn 开始 / 完成 / 中断时的生命周期清理。
5. `item/completed` — 在补丁尝试后返回同一 `fileChange` item，`status` 更新为 `completed`、`failed` 或 `declined`。依赖此通知展示成功 / 失败，并在 UI 中最终确定 diff 状态。

IDE 的 UI 指导：请求到达后立即展示审批对话框。服务器收到对审批请求的响应后，该 turn 将继续。终止的 `item/completed` 通知会带有相应状态发送。

### request_user_input

`item/tool/requestUserInput` 包含必需的 `isBlocking`，它指示客户端是否应无限期等待显式用户输入。更旧的 `autoResolutionMs` 字段已弃用，仅为兼容性而保留。

当客户端响应 `item/tool/requestUserInput` 时，服务器发出带有 `{ threadId, requestId }` 的 `serverRequest/resolved`。若待处理请求在客户端回答前因 turn 开始、turn 完成或 turn 中断而被清除，服务器会为该清理发出相同通知。

### 证明生成

提供上游证明的桌面宿主应在 `initialize` 期间设置 `capabilities.requestAttestation`，并处理服务器发起的 `attestation/generate` 请求。App-server 会在转发 `x-oai-attestation` 的 ChatGPT Codex 请求之前即时发出它；客户端以 `{ "token": "v1.<opaque>" }` 响应，其中 `token` 是客户端拥有的不透明值。当 app-server 收到客户端响应时，它转发一致的外层信封，例如 `{ "v": 1, "s": 0, "t": "v1.<opaque>" }`，其中 `t` 包含未更改的客户端 token。若 app-server 尝试证明但在自己的边界内失败，它发送相同信封形状，带有 app-server 状态码且没有 `t`（`1 = timeout`，`2 = request failed`，`3 = request canceled`，`4 = malformed response`）。若没有已初始化客户端选择加入证明，app-server 会为该上游请求省略 `x-oai-attestation`。

### 当前时间

当启用 `[features.current_time_reminder]` 且 `clock_source = "external"` 时，在时间提醒到期时，app-server 会向订阅该 thread 的客户端发送实验性 `currentTime/read` 请求，载荷为 `{ "threadId": "thr_123" }`。客户端以 `{ "currentTimeAt": 1781717655 }` 响应，其中 `currentTimeAt` 是整数 Unix 时间戳（秒）。失败、取消、超时或格式错误的响应会在模型请求发送前停止该 turn。

### MCP server elicitation

MCP server 可以通过 `mcpServer/elicitation/request` 中断一轮 turn，并向客户端请求结构化输入。

消息顺序：

1. `mcpServer/elicitation/request`（请求）— 包含 `threadId`、可空 `turnId`、`serverName`，以及以下之一：
   - 表单请求：`{ "mode": "form", "message": "...", "requestedSchema": { ... } }`
   - OpenAI 扩展表单请求：`{ "mode": "openai/form", "message": "...", "requestedSchema": { ... } }`
   - URL 请求：`{ "mode": "url", "message": "...", "url": "...", "elicitationId": "..." }`
2. 客户端响应 — `{ "action": "accept", "content": ... }`、`{ "action": "decline", "content": null }` 或 `{ "action": "cancel", "content": null }`。
3. `serverRequest/resolved` — `{ threadId, requestId }` 确认待处理请求已解决或清除，包括 turn 开始 / 完成 / 中断时的生命周期清理。

`turnId` 是尽力而为的。当 elicitation 与活动 turn 关联时，请求包含该 turn id；否则为 `null`。

对于 `openai/form`，app-server 将 `requestedSchema` 作为不透明 JSON 转发。客户端拥有对支持字段类型的校验和渲染，并且在无法渲染表单时必须返回有效的 `decline` 或 `cancel` 响应。

对于 MCP 工具审批 elicitation，表单请求 `meta` 包含 `codex_approval_kind: "mcp_tool_call"`，并可能包含 `persist: "session"`、`persist: "always"` 或 `persist: ["session", "always"]`，以声明客户端是否可以提供会话作用域和 / 或持久审批选择。

### 权限请求

内置 `request_permissions` 工具向客户端发送带有请求权限配置文件的 `item/permissions/requestApproval` JSON-RPC 请求。此 v2 载荷镜像命令执行 `additionalPermissions` 形状：它可以请求网络访问和额外文件系统访问。`environmentId` 和 `cwd` 字段标识用于解析项目根权限和相对拒绝 glob 的环境和目录。

```json
{
  "method": "item/permissions/requestApproval",
  "id": 61,
  "params": {
    "threadId": "thr_123",
    "turnId": "turn_123",
    "itemId": "call_123",
    "environmentId": "local",
    "cwd": "/Users/me/project",
    "reason": "Select a workspace root",
    "permissions": {
      "fileSystem": {
        "write": ["/Users/me/project", "/Users/me/shared"]
      }
    }
  }
}
```

客户端以 `result.permissions` 响应，它应是所请求权限配置文件的已授予子集。它还可以将 `result.scope` 设为 `"session"`，使该授权对同一会话中的后续 turn 持久；省略或 `"turn"` 保留现有 turn 作用域行为：

```json
{
  "id": 61,
  "result": {
    "scope": "session",
    "permissions": {
      "fileSystem": {
        "write": ["/Users/me/project"]
      }
    }
  }
}
```

线上只有已授予子集有意义。从 `result.permissions` 中省略的任何权限都被视为拒绝。原始请求中不存在的任何权限会被服务器忽略。

在同一 turn 内，已授予权限是粘性的：后续类似 shell 的工具调用可以自动重用已授予子集，而不重新发出单独的权限请求。

若会话审批策略使用带 `request_permissions: false` 的 `Granular`，独立 `request_permissions` 工具调用会被自动拒绝，并且不会发送 `item/permissions/requestApproval` 提示。内联 `with_additional_permissions` 命令请求仍由 `sandbox_approval` 控制，任何先前授予的权限对同一 turn 中后续类似 shell 的调用仍保持粘性。

### 动态工具调用（实验性）

`thread/start` 上的 `dynamicTools` 以及对应的 `item/tool/call` 请求 / 响应流程是实验性 API。要启用它们，设 `initialize.params.capabilities.experimentalApi = true`。

`dynamicTools` 中的每个条目要么是顶层函数，要么是包含函数工具的命名空间。动态工具标识符遵循与 Responses 工具相同的约束：

- `name` 必须匹配 `^[a-zA-Z0-9_-]+$`，长度为 1 到 128 个字符。
- 命名空间名称必须匹配 `^[a-zA-Z0-9_-]+$`，长度为 1 到 64 个字符。
- 命名空间描述最多 1,024 个字符。
- 命名空间名称不得与保留的 Responses 运行时命名空间冲突，例如 `functions`、`multi_tool_use`、`file_search`、`web`、`browser`、`image_gen`、`computer`、`container`、`terminal`、`python`、`python_user_visible`、`api_tool`、`tool_search` 或 `submodel_delegator`。

每个函数可以设置 `deferLoading`。省略时默认为 `false`。延迟函数必须属于某个命名空间。设为 `true` 可使该函数保持注册，并可由诸如 `code_mode` 的运行时功能调用，同时将其从普通 turn 发送的面向模型的工具列表中排除。当 `tool_search` 可用时，延迟动态工具可被搜索，并可由匹配的搜索结果暴露。

当在 turn 期间调用动态工具时，服务器向客户端发送 `item/tool/call` JSON-RPC 请求：

```json
{
  "method": "item/tool/call",
  "id": 60,
  "params": {
    "threadId": "thr_123",
    "turnId": "turn_123",
    "callId": "call_123",
    "namespace": "tickets",
    "tool": "lookup_ticket",
    "arguments": { "id": "ABC-123" }
  }
}
```

服务器还在请求周围发出 item 生命周期通知：

1. `item/started`，`item.type = "dynamicToolCall"`，`status = "inProgress"`，加上 `tool` 和 `arguments`。
2. `item/tool/call` 请求。
3. 客户端响应。
4. `item/completed`，`item.type = "dynamicToolCall"`，最终 `status`，以及返回的 `contentItems`/`success`。

客户端必须用内容 item 响应。文本使用 `inputText`，内联图片 data URL 使用 `inputImage`，内联音频 data URL 使用 `inputAudio`。音频 data URL 接受 wav、mp3、m4a、webm 和 ogg 媒体类型。远程 HTTP(S) 图片 URL 以及非 data 音频 URL 会使动态工具响应无效。

```json
{
  "id": 60,
  "result": {
    "contentItems": [
      { "type": "inputText", "text": "Ticket ABC-123 is open." },
      { "type": "inputImage", "imageUrl": "data:image/png;base64,AAA" },
      { "type": "inputAudio", "audioUrl": "data:audio/wav;base64,AAA" }
    ],
    "success": true
  }
}
```

## Skills

通过在文本输入中包含 `$<skill-name>` 来调用 skill。添加 `skill` 输入 item（推荐），以便后端注入完整 skill 指令，而不是依赖模型解析名称。

```json
{
  "method": "turn/start",
  "id": 101,
  "params": {
    "threadId": "thread-1",
    "input": [
      {
        "type": "text",
        "text": "$skill-creator Add a new skill for triaging flaky CI."
      },
      {
        "type": "skill",
        "name": "skill-creator",
        "path": "/Users/me/.codex/skills/skill-creator/SKILL.md"
      }
    ]
  }
}
```

若省略 `skill` item，模型仍会解析 `$<skill-name>` 标记并尝试定位该 skill，这可能增加延迟。

示例：

```
$skill-creator Add a new skill for triaging flaky CI and include step-by-step usage.
```

用 `skills/list` 获取可用 skills（可选按 `cwds` 限定范围，带 `forceReload`）。
每个 skill 在已知时包含可空 `pluginId`，与其拥有 plugin 在 `plugin/list` 中的 `id` 匹配。客户端可以用它分组 plugin 拥有的 skills，而不从名称或路径推断所有权。更旧的服务器可能省略此字段。
`skills/list` 可能按 `cwd` 重用缓存的 skills 结果；将 `forceReload` 设为 `true` 会从磁盘刷新结果。
当被监视的本地 skill 文件变化时，服务器还会发出 `skills/changed` 通知。将其视为失效信号，并在需要时用当前参数重新运行 `skills/list`。
用 `skills/extraRoots/set` 替换当前 app-server 进程的额外独立 skill 根。这些根使用与其他独立 skill 根相同的布局：每个根包含 skill 目录，每个 skill 目录包含 `SKILL.md`。缺失的根会被接受，在它们存在之前不加载任何 skill。app-server 退出时此设置会丢失。

```json
{ "method": "skills/list", "id": 25, "params": {
    "cwds": ["/Users/me/project", "/Users/me/other-project"],
    "forceReload": true
} }
{ "id": 25, "result": {
    "data": [{
        "cwd": "/Users/me/project",
        "skills": [
            {
              "name": "skill-creator",
              "description": "Create or update a Codex skill",
              "enabled": true,
              "pluginId": null,
              "interface": {
                "displayName": "Skill Creator",
                "shortDescription": "Create or update a Codex skill",
                "iconSmall": "icon.svg",
                "iconLarge": "icon-large.svg",
                "brandColor": "#111111",
                "defaultPrompt": "Add a new skill for triaging flaky CI."
              }
            }
        ],
        "errors": []
    }]
} }
```

```json
{
  "method": "skills/changed",
  "params": {}
}
```

```json
{
  "method": "skills/extraRoots/set",
  "id": 26,
  "params": {
    "extraRoots": ["/Users/me/generated-skills"]
  }
}
{ "id": 26, "result": {} }
```

按绝对路径启用或禁用 skill：

```json
{
  "method": "skills/config/write",
  "id": 27,
  "params": {
    "path": "/Users/alice/.codex/skills/skill-creator/SKILL.md",
    "name": null,
    "enabled": false
  }
}
```

按名称启用或禁用 skill：

```json
{
  "method": "skills/config/write",
  "id": 28,
  "params": {
    "path": null,
    "name": "github:yeet",
    "enabled": false
  }
}
```

用 `hooks/list` 获取一个或多个 `cwds` 的已发现 hooks。每个结果用该 `cwd` 的有效配置求值，因此功能门控和已发现配置层可以在单次响应内不同。

对于链接的 Git worktree，项目 hook 声明来自根检出中匹配的 `.codex/` 文件夹，而不是仅存储在链接 worktree 中的分叉 hook 声明。这使每个仓库保持一个权威项目 hook 定义和一个信任状态。

即使禁用也会返回 hooks，以便客户端可以渲染并重新启用它们。用户控制状态位于 `hooks.state` 下。托管 hooks 不可配置，加载期间会忽略托管 hook 键的用户条目。

命令 hook 的 `async` 字段报告其有效执行行为。`async: false` 的 hooks 参与当前操作，而 `async: true` 的 hooks 在后台运行，并通过现有基于 steer 的注入路径投递信息性输出。输出会立即注入活动 turn，或在会话空闲时持久化而不开始新 turn。MCP 工具 hooks 没有 `async` 字段，并且始终同步运行。生命周期通知继续在 hook 运行摘要上报告 `executionMode`。

对于非托管 hooks，`currentHash` 和 `trustStatus` 描述当前定义是首次看到、已批准，还是自批准以来已更改。只有受信任的非托管 hooks 才会变为可运行。Hook 键将源身份与当前按位置的尾部事件 / 组 / 处理器选择器组合。

MCP 工具 hooks 以 `handlerType: "mcpTool"` 出现。它们的 `server` 和 `tool` 字段标识已配置 MCP 目标。命令 hooks 则包含 `command` 字段。

```json
{
  "method": "hooks/list",
  "id": 28,
  "params": {
    "cwds": ["/Users/me/project"]
  }
}
```

```json
{
  "id": 28,
  "result": {
    "data": [{
      "cwd": "/Users/me/project",
      "hooks": [{
        "key": "/Users/me/.codex/config.toml:pre_tool_use:0:0",
        "eventName": "pre_tool_use",
        "handlerType": "command",
        "async": false,
        "isManaged": false,
        "matcher": "Bash",
        "command": "python3 /Users/me/hook.py",
        "timeoutSec": 5,
        "statusMessage": "running hook",
        "additionalContextLimit": null,
        "sourcePath": "/Users/me/.codex/config.toml",
        "source": "user",
        "pluginId": null,
        "displayOrder": 0,
        "enabled": true,
        "currentHash": "sha256:...",
        "trustStatus": "untrusted"
      }],
      "warnings": [],
      "errors": []
    }]
  }
}
```

要禁用非托管 hook，用 `config/batchWrite` 在 `hooks.state` 处 upsert 状态条目：

```json
{
  "method": "config/batchWrite",
  "id": 29,
  "params": {
    "edits": [{
      "keyPath": "hooks.state",
      "value": {
        "/Users/me/.codex/config.toml:pre_tool_use:0:0": {
          "enabled": false
        }
      },
      "mergeStrategy": "upsert"
    }],
    "reloadUserConfig": true
  }
}
```

要重新启用它，用 `"enabled": true` upsert 同一 hook 键。

## Apps

用 `app/installed` 读取已安装 apps，以及每个 app 当前是否启用且可调用。

```json
{ "method": "app/installed", "id": 49, "params": {
    "threadId": "thr_123",
    "forceRefresh": false
} }
{ "id": 49, "result": {
    "apps": [
        {
            "id": "demo-app",
            "runtimeName": "Demo App",
            "enabled": true,
            "callable": true
        }
    ]
} }
```

`id` 是 app 的连接器 ID，`runtimeName` 是运行时报告的可空名称。`enabled` 反映有效 app 配置和工作区策略。当 app 已启用且至少有一个被 app 和工具策略允许的模型可见工具时，`callable` 为 true。

提供 `threadId` 时，响应使用该 thread 的有效配置；否则使用当前全局配置。`forceRefresh` 默认为 `false`。设为 `true` 可在读取响应前刷新托管连接器运行时工具快照。当 Apps 被全局或工作区策略禁用时，先前观察到的 apps 仍可能被返回，且 `enabled` 和 `callable` 设为 `false`。

用 `app/list` 获取可用 apps（连接器）。每个条目包含诸如 app `id`、显示 `name`、`installUrl`、遗留 logo URL、结构化浅色和深色图标资源、`branding`、`appMetadata`、`labels`、当前是否可访问，以及是否在配置中启用等元数据。

```json
{ "method": "app/list", "id": 50, "params": {
    "cursor": null,
    "limit": 50,
    "threadId": "thr_123",
    "forceRefetch": false
} }
{ "id": 50, "result": {
    "data": [
        {
            "id": "demo-app",
            "name": "Demo App",
            "description": "Example connector for documentation.",
            "logoUrl": "https://example.com/demo-app.png",
            "logoUrlDark": null,
            "iconAssets": {
                "256_square": "https://example.com/demo-app-square.png"
            },
            "iconDarkAssets": null,
            "distributionChannel": null,
            "branding": null,
            "appMetadata": null,
            "labels": null,
            "installUrl": "https://chatgpt.com/apps/demo-app/demo-app",
            "isAccessible": true,
            "isEnabled": true
        }
    ],
    "nextCursor": null
} }
```

提供 `threadId` 时，app 功能门控（`Feature::Apps`）使用该 thread 的配置快照求值。省略时使用最新全局配置。

`app/list` 在可访问 apps 和目录 apps 都加载后返回。设 `forceRefetch: true` 可绕过 app 缓存并从源获取新鲜数据。仅当这些重新获取成功时才替换缓存条目。

当新加载的可访问或目录 apps 改变合并后的 app 列表时，服务器还会发出 `app/list/updated` 通知。每个通知包含最新合并后的 app 列表。初始缓存的 `app/list` 仍会发出一次最终通知，以便其他已初始化客户端可以刷新其 app 列表，而读取未更改的缓存续页不会发出重复通知；`forceRefetch: true` 在新鲜数据加载时保留现有渐进通知。

```json
{
  "method": "app/list/updated",
  "params": {
    "data": [
      {
        "id": "demo-app",
        "name": "Demo App",
        "description": "Example connector for documentation.",
        "logoUrl": "https://example.com/demo-app.png",
        "logoUrlDark": null,
        "iconAssets": {
          "256_square": "https://example.com/demo-app-square.png"
        },
        "iconDarkAssets": null,
        "distributionChannel": null,
        "branding": null,
        "appMetadata": null,
        "labels": null,
        "installUrl": "https://chatgpt.com/apps/demo-app/demo-app",
        "isAccessible": true,
        "isEnabled": true
      }
    ]
  }
}
```

当客户端已经拥有 app id 并且只需要元数据时，使用 `app/read`。请求最多接受 100 个 `appIds`；重复 id 会去重，同时保留首次请求顺序。`apps` 和 `missingAppIds` 都遵循该顺序。未知或未授权 id 作为部分未命中返回，而不是使整个请求失败。

```json
{ "method": "app/read", "id": 51, "params": {
    "appIds": ["demo-app", "missing-app"],
    "threadId": "thr_123",
    "includeTools": true
} }
{ "id": 51, "result": {
    "apps": [
        {
            "id": "demo-app",
            "name": "Demo App",
            "description": "Example app for documentation.",
            "iconUrl": "https://files.openai.com/content?id=demo-app",
            "toolSummaries": [
                {
                    "name": "search",
                    "title": "Search",
                    "description": "Search the app.",
                    "isEnabled": true,
                    "disabledReason": null,
                    "isReadOnly": true
                }
            ]
        }
    ],
    "missingAppIds": ["missing-app"]
} }
```

`app/read` 从按后端 URL 和 ChatGPT 账户 / 工作区身份分区的缓存中读取新鲜元数据记录，然后对缺失或过期 id 最多发出一次 `POST /ps/apps/batch`。提供 `threadId` 时，app 功能门控、工作区策略和 plugin 归属使用该 thread 的有效配置。`includeTools` 默认为 false，并作为 `include_tools` 转发；当请求工具摘要时，仅元数据的新鲜缓存条目会被重新获取。后端或传输失败会返回 RPC 错误，而不替换现有缓存记录。其元数据形状可以包含带启用 / 只读状态的仅显示公共工具摘要，并有意排除运行时状态、MCP 工具状态、完整 actions 和模型描述。

已连接 apps 可以在 `config.toml` 中覆盖 thread 的审批审查器。
用 `apps._default.approvals_reviewer` 为所有 apps 设置审查器，并用每 app 值覆盖该默认值。两者都省略时，该 app 继承顶层 `approvals_reviewer` 值：

```toml
approvals_reviewer = "auto_review"

[apps._default]
approvals_reviewer = "user"
default_tools_approval_mode = "prompt"

[apps.demo-app]
approvals_reviewer = "auto_review"
default_tools_approval_mode = "approve"
```

将 app 值设为 `"user"` 会将其审批提示路由给用户而不是 Guardian；设为 `"auto_review"` 会在配置要求允许时选择该 app 进入 Guardian 审查。

用 `apps._default.default_tools_approval_mode` 为没有每 app 或每工具覆盖的工具设置审批模式。支持的值为 `"auto"`、`"prompt"`、`"writes"` 和 `"approve"`。`"writes"` 模式会提示未声明 `readOnlyHint = true` 的工具，并跳过已声明只读的工具。工具级 `approval_mode` 优先于每 app `default_tools_approval_mode`，后者优先于 `apps._default` 值。托管工具要求优先于所有这些设置。当均未配置时，模式默认为 `"auto"`。

通过在文本输入中插入 `$<app-slug>` 来调用 app。slug 从 app 名称派生，并小写化，非字母数字字符替换为 `-`（例如 "Demo App" 变为 `$demo-app`）。添加 `mention` 输入 item（推荐），以便服务器使用精确的 `app://<connector-id>` 路径，而不是按名称猜测。Plugin 使用相同的 `mention` item 形状，但路径为来自 `plugin/installed` 或 `plugin/list` 的 `plugin://<plugin-name>@<marketplace-name>`。

示例：

```
$demo-app Pull the latest updates from the team.
```

```json
{
  "method": "turn/start",
  "id": 51,
  "params": {
    "threadId": "thread-1",
    "input": [
      {
        "type": "text",
        "text": "$demo-app Pull the latest updates from the team."
      },
      { "type": "mention", "name": "Demo App", "path": "app://demo-app" }
    ]
  }
}
```

## 鉴权端点

JSON-RPC 鉴权 / 账户表面暴露请求 / 响应方法以及服务器发起的通知（无 `id`）。用它们确定鉴权状态、开始或取消登录、登出，以及检查 ChatGPT 速率限制。

### 鉴权模式

Codex 支持这些鉴权模式。当前模式在 `account/updated`（`authMode`）中暴露，可用时还包含当前 ChatGPT `planType`，并且可以从 `account/read` 推断。自助 Business ProLite 账户使用 `self_serve_business_prolite` 计划类型；Enterprise 自动化账户使用 `enterprise_cbp_automation`。

- **API key（`apiKey`）**：调用方通过 `type: "apiKey"` 的 `account/login/start` 提供 OpenAI API key。API key 会被保存并用于 API 请求。
- **ChatGPT 托管（`chatgpt`）**（推荐）：Codex 拥有 ChatGPT OAuth 流程和刷新 token。通过 `type: "chatgpt"` 的 `account/login/start` 启动浏览器流程，或通过 `type: "chatgptDeviceCode"` 启动设备码流程；Codex 将 token 持久化到磁盘并自动刷新它们。
- **Codex 托管的 Amazon Bedrock 鉴权（实验性）**：调用方通过 `account/login/start` 使用 `type: "amazonBedrock"` 提供 Amazon Bedrock API key，或使用 `type: "amazonBedrockAccessKeys"` 提供 AWS access key。客户端必须启用 `experimentalApi` 初始化能力。Codex 用 Bedrock 凭据替换当前主鉴权，并向用户配置写入 `model_provider = "amazon-bedrock"`。
- **个人访问 token（`personalAccessToken`）**：Codex 使用在 app-server 登录 RPC 之外加载的、由 ChatGPT 支持的个人访问 token，例如用 `codex login --with-access-token` 或 `CODEX_ACCESS_TOKEN`。

### API 总览

- `account/read` — 获取当前账户信息；可选刷新 token。
- `account/login/start` — 开始登录（`apiKey`、`chatgpt`、`chatgptDeviceCode`、`amazonBedrock`、`amazonBedrockAccessKeys`）。
- `account/bedrock/discover` — 实验性；列出可用 AWS profile，并识别 app-server 环境中可见的 AWS access key 或 Amazon Bedrock API key。
- `account/bedrock/setup` — 实验性；校验所选 AWS profile 或现有环境凭据，然后持久化 Amazon Bedrock provider 配置。
- `account/login/completed`（通知）— 当登录尝试完成时发出（成功或错误）。
- `account/login/cancel` — 按 `loginId` 取消待处理的托管 ChatGPT 登录。
- `account/logout` — 登出；成功时触发 `account/updated`。
- `account/updated`（通知）— 每当鉴权模式变化时发出（`authMode`：`apikey`、`bedrockApiKey`、`bedrockAccessKeys`、`chatgpt`、`personalAccessToken` 或 `null`），可用时包含当前 ChatGPT `planType`。
- `account/rateLimits/read` — 获取 ChatGPT 速率限制、可选有效月度额度限制、是否已达到花费控制，以及当前可用的已赚取速率限制重置（包括后端提供时的过期详情）。速率限制更新通过 `account/rateLimits/updated`（通知）到达；重置额度数据仅为快照。
- `account/rateLimitResetCredit/consume` — 使用调用方提供的幂等键消费一次已赚取重置，可选选择 `account/rateLimits/read` 返回的重置额度 ID。
- `account/usage/read` — 获取 ChatGPT 账户 token 活动摘要和每日分桶，或将有效 thread UUID 作为 `threadId` 传入，以使用 app-server 的活动账户读取单个 thread 的估算额度、可选成本和用量分解。可选 `threadUsage` 响应字段在更旧服务器上不存在，当计费路由不可用时为 `null`。
- `account/workspaceMessages/read` — 获取活动工作区消息，可用时包括工作区通知标题。
- `account/rateLimits/updated`（通知）— 每当用户的 ChatGPT 速率限制变化时发出。这是稀疏滚动更新；将可用值合并到最近的 `account/rateLimits/read` 响应中，或重新获取该快照。
  当后端报告花费控制状态时 `spendControlReached` 为 `true` 或 `false`；`null` 表示不可用，并且不得在稀疏更新中清除先前观察到的值。
- `account/sendAddCreditsNudgeEmail` — 请 ChatGPT 向工作区所有者发送关于额度耗尽或已达到用量限制的邮件。
- `mcpServer/oauthLogin/completed`（通知）— 在某个 server 的 `mcpServer/oauth/login` 流程完成后发出；载荷包含 `{ name, threadId, success, error? }`。
- `mcpServer/startupStatus/updated`（通知）— 当已配置 MCP server 的启动状态变化时发出；载荷包含 `{ threadId, name, status, error, failureReason }`，当启动是 thread 作用域时 `threadId` 是拥有该启动的 thread，当它是 app 作用域时为 `null`，`status` 为 `starting`、`ready`、`failed` 或 `cancelled`。当已存储 OAuth 凭据过期且无法刷新时，`failureReason` 为 `reauthenticationRequired`，因此客户端可以提示用户重新连接该命名 server。
- `mcpServer/event/stream/notification`（实验性，通知）— 向拥有该订阅的连接转发 `{ subscriptionId, notification: { method, params } }`。

### 1) 检查鉴权状态

请求：

```json
{ "method": "account/read", "id": 1, "params": { "refreshToken": false } }
```

响应示例：

```json
{ "id": 1, "result": { "account": { "type": "chatgpt", "email": "user@example.com", "planType": "pro" }, "requiresOpenaiAuth": true } }
{ "id": 1, "result": { "account": { "type": "amazonBedrock", "usesCodexManagedCredentials": false }, "requiresOpenaiAuth": false } }
```

字段说明：

- `refreshToken`（bool）：设为 `true` 以强制刷新 token。
- 当 ChatGPT 账户没有电子邮件地址时，`email` 为 `null`。
- `requiresOpenaiAuth` 反映活动 provider；为 `false` 时，Codex 可以在没有 OpenAI 凭据的情况下运行。
- 当 Amazon Bedrock 使用由 Codex 管理的 Bedrock API key 或 AWS access key 时，报告 `usesCodexManagedCredentials: true`。对外部凭据路径（包括 AWS 凭据链和已配置命令鉴权）报告 `false`。这标识是否选择了 Codex 管理的凭据；它不校验凭据源能否解析凭据。

### 2) 用 API key 登录

1. 发送：
   ```json
   {
     "method": "account/login/start",
     "id": 2,
     "params": { "type": "apiKey", "apiKey": "sk-…" }
   }
   ```
2. 预期：
   ```json
   { "id": 2, "result": { "type": "apiKey" } }
   ```
3. 通知：
   ```json
   { "method": "account/login/completed", "params": { "loginId": null, "success": true, "error": null } }
   { "method": "account/updated", "params": { "authMode": "apikey", "planType": null } }
   ```

### 3) 用 ChatGPT 登录（浏览器流程）

1. 开始：
   ```json
   { "method": "account/login/start", "id": 3, "params": { "type": "chatgpt" } }
   { "id": 3, "result": { "type": "chatgpt", "loginId": "<uuid>", "authUrl": "https://chatgpt.com/…&redirect_uri=http%3A%2F%2Flocalhost%3A<port>%2Fauth%2Fcallback" } }
   ```
2. 在浏览器中打开 `authUrl`；app-server 托管本地回调。
   默认情况下，成功回调会重定向到本地成功页。客户端可以设 `useHostedLoginSuccessPage: true`，将不需要组织设置的成功回调改为重定向到托管 Codex 成功页。启用托管登录成功时，客户端可以设 `appBrand` 为 `"codex"` 或 `"chatgpt"` 以选择匹配的托管页图稿；省略或 `null` 值默认为 `"codex"`。
3. 等待通知：
   ```json
   { "method": "account/login/completed", "params": { "loginId": "<uuid>", "success": true, "error": null, "onboardingEntrypoint": "life_sciences" } }
   { "method": "account/updated", "params": { "authMode": "chatgpt", "planType": "plus" } }
   ```
   `onboardingEntrypoint` 是可选的，仅当 OAuth 回调携带已识别的引导提示时才发出。

### 3) 用 Amazon Bedrock 凭据登录

此实验性流程要求客户端以 `experimentalApi: true` 初始化。

1. 发送：
   ```json
   {
     "method": "account/login/start",
     "id": 3,
     "params": { "type": "amazonBedrock", "apiKey": "…", "region": "us-west-2" }
   }
   ```
2. 预期：
   ```json
   { "id": 3, "result": { "type": "amazonBedrock" } }
   ```
3. 通知：
   ```json
   { "method": "account/login/completed", "params": { "loginId": null, "success": true, "error": null } }
   { "method": "account/updated", "params": { "authMode": "bedrockApiKey", "planType": null } }
   ```

改为用 AWS access key 登录：

```json
{
  "method": "account/login/start",
  "id": 30,
  "params": {
    "type": "amazonBedrockAccessKeys",
    "accessKeyId": "...",
    "secretAccessKey": "...",
    "sessionToken": "...",
    "region": "us-west-2"
  }
}
{ "id": 30, "result": { "type": "amazonBedrock" } }
{ "method": "account/login/completed", "params": { "loginId": null, "success": true, "error": null } }
{ "method": "account/updated", "params": { "authMode": "bedrockAccessKeys", "planType": null } }
```

会话 token 是可选的。两个流程都将凭据存储在已配置鉴权后端（`auth.json` 或 keyring）中，替换任何先前存储的登录，并选择 `model_provider = "amazon-bedrock"`；access-key 登录还会将所选 AWS 区域写入活动用户配置。两个流程都不会改变 `$CODEX_HOME/.env`。现有已加载会话保留其当前 provider 选择，因此客户端应在发送更多模型请求前重启 app-server。此限制将在后续跟进中解决。

### 发现并配置 AWS 管理的 Amazon Bedrock 凭据

这些实验性方法要求客户端以 `experimentalApi: true` 初始化。

发现 app-server 进程已经可见的 AWS profile 和凭据：

```json
{ "method": "account/bedrock/discover", "id": 31, "params": {} }
{
  "id": 31,
  "result": {
    "profiles": [{ "name": "engineering", "region": "us-west-2" }],
    "environmentCredentials": [
      { "type": "accessKeys", "region": "us-west-2" },
      { "type": "bedrockApiKey", "region": "us-west-2" }
    ]
  }
}
```

发现仅返回凭据元数据；它从不包含 access key、secret access key、会话 token 或 Bedrock API key。当该源没有可用的 profile 区域或显式 `AWS_REGION` 时，profile 或环境凭据的 `region` 为 `null`。

设置命名 AWS profile：

```json
{
  "method": "account/bedrock/setup",
  "id": 32,
  "params": { "type": "profile", "profile": "engineering", "region": "us-west-2" }
}
{ "id": 32, "result": {} }
```

要选择环境中已经可见的凭据，使用 `{ "type": "environment", "region": "us-west-2" }`。Provider 通过其正常鉴权链解析可用环境凭据。选择 profile 或环境凭据会使 `$CODEX_HOME/.env` 中的现有密钥保持不变。

成功设置会将 `model_provider = "amazon-bedrock"` 和所选 AWS 区域写入活动用户配置，并且对于基于 profile 的设置还会额外写入所选 profile。客户端应在发送更多模型请求前重启 app-server。在选择 Amazon Bedrock provider 时登出会清除用户配置的 provider、profile 和区域，移除任何 Codex 管理的凭据，并使 AWS 管理的凭据以及 `$CODEX_HOME/.env` 保持不变。

### 4) 用 ChatGPT 登录（设备码流程）

1. 开始：
   ```json
   { "method": "account/login/start", "id": 4, "params": { "type": "chatgptDeviceCode" } }
   { "id": 4, "result": { "type": "chatgptDeviceCode", "loginId": "<uuid>", "verificationUrl": "https://auth.openai.com/codex/device", "userCode": "ABCD-1234" } }
   ```
2. 向用户展示 `verificationUrl` 和 `userCode`；前端拥有 UX。
3. 等待通知：
   ```json
   { "method": "account/login/completed", "params": { "loginId": "<uuid>", "success": true, "error": null } }
   { "method": "account/updated", "params": { "authMode": "chatgpt", "planType": "plus" } }
   ```

### 5) 取消 ChatGPT 登录

```json
{ "method": "account/login/cancel", "id": 5, "params": { "loginId": "<uuid>" } }
{ "method": "account/login/completed", "params": { "loginId": "<uuid>", "success": false, "error": "…" } }
```

### 6) 登出

```json
{ "method": "account/logout", "id": 6 }
{ "id": 6, "result": {} }
{ "method": "account/updated", "params": { "authMode": null, "planType": null } }
```

当 `model_provider` 为 `"amazon-bedrock"` 或 `"amazon-bedrock-runtime"` 时，登出会清除该 provider 选择及其已配置 AWS profile 和区域，无论凭据是 Codex 管理还是 AWS 管理。若所选模型是 Bedrock 特定的，登出还会清除 `model`；`model_reasoning_effort` 和其他通用设置会被保留。Codex 管理的凭据会被移除；AWS profile、环境凭据和 `$CODEX_HOME/.env` 保持不变。

### 7) 速率限制（ChatGPT）

```json
{ "method": "account/rateLimits/read", "id": 7 }
{
  "id": 7,
  "result": {
    "rateLimits": {
      "primary": { "usedPercent": 25, "windowDurationMins": 15, "resetsAt": 1730947200 },
      "secondary": null,
      "rateLimitReachedType": null
    },
    "rateLimitResetCredits": {
      "availableCount": 2,
      "credits": [
        {
          "id": "RateLimitResetCredit_1",
          "resetType": "codexRateLimits",
          "status": "available",
          "grantedAt": 1781654400,
          "expiresAt": 1784246400,
          "title": "Full reset (Weekly + 5 hr)",
          "description": "Ready to redeem"
        }
      ]
    }
  }
}
{ "method": "account/rateLimits/updated", "params": { "rateLimits": { … } } }
```

字段说明：

- `usedPercent` 是 OpenAI 配额窗口内的当前用量。
- `windowDurationMins` 是配额窗口长度。
- `resetsAt` 是下次重置的 Unix 时间戳（秒）。
- `rateLimitReachedType` 在已达到某个限制时标识后端分类的限制状态。
- 可用时 `individualLimit` 描述有效月度额度限制。在 `account/rateLimits/read` 响应中，`null` 表示没有可用月度限制。在稀疏 `account/rateLimits/updated` 通知中，可空账户元数据可能不可用，并且不会清除先前观察到的值。
- 当后端提供时，`rateLimitResetCredits` 包含可用已赚取重置计数；否则为 `null`。
- 仅计数可用时 `rateLimitResetCredits.credits` 为 `null`。空数组表示已获取详情且没有返回可用额度。
- 后端可能限制 `rateLimitResetCredits.credits`，因此 `availableCount` 是权威总数，并且可以大于详情行数。
- 消费重置后重新获取 `account/rateLimits/read`。

### 8) 已赚取速率限制重置（ChatGPT）

```json
{ "method": "account/rateLimitResetCredit/consume", "id": 8, "params": { "idempotencyKey": "8ae96ff3-3425-4f4c-8772-b6fd61502868", "creditId": "RateLimitResetCredit_1" } }
{ "id": 8, "result": { "outcome": "reset" } }
```

字段说明：

- `idempotencyKey` 必须非空。建议为每次逻辑兑换尝试使用 UUID；重试该尝试时重用同一值。
- `creditId` 可选。提供时，它必须是 `account/rateLimits/read` 返回的非空不透明 ID；省略时，后端选择下一个可用额度。
- `reset` 表示已消费一个额度。
- `alreadyRedeemed` 表示同一兑换先前已完成。将其视为幂等成功并刷新账户限制。
- `nothingToReset` 表示没有符合条件的速率限制窗口可重置。
- `noCredit` 表示账户没有可用的已赚取重置额度。
- 消费重置后重新获取 `account/rateLimits/read`，而不是从此响应推断更新状态。

### 9) 工作区消息（ChatGPT）

```json
{ "method": "account/workspaceMessages/read", "id": 9 }
{ "id": 9, "result": { "featureEnabled": true, "messages": [
    { "messageId": "msg_123", "messageType": "headline", "messageBody": "Workspace maintenance starts at 5pm.", "createdAt": 1781395200, "archivedAt": null }
] } }
```

当上游工作区消息功能禁用时，`featureEnabled` 为 `false` 且 `messages` 为空。

### 10) 就限制通知工作区所有者

```json
{ "method": "account/sendAddCreditsNudgeEmail", "id": 9, "params": { "creditType": "credits" } }
{ "id": 9, "result": { "status": "sent" } }
```

当工作区额度耗尽时使用 `creditType: "credits"`，当已达到工作区用量限制时使用 `creditType: "usage_limit"`。若所有者最近已被通知，响应状态为 `cooldown_active`。

## 实验性 API 选择加入

某些 app-server 方法和字段有意门控在没有向后兼容保证的实验性能力之后。这让客户端可以在以下之间选择：

- 仅稳定表面（默认）：不选择加入，不暴露实验性方法 / 字段。
- 实验性表面：在 `initialize` 期间选择加入。

### 生成稳定 vs 实验性客户端 schema

`codex app-server` schema 生成默认使用稳定 API 表面（实验性字段和方法被过滤掉）。传入 `--experimental` 以在生成的 TypeScript 或 JSON schema 中包含实验性方法 / 字段：

```bash
# 仅稳定输出（默认）
codex app-server generate-ts --out DIR
codex app-server generate-json-schema --out DIR

# 包含实验性 API 表面
codex app-server generate-ts --out DIR --experimental
codex app-server generate-json-schema --out DIR --experimental
```

### 客户端如何在运行时选择加入

在你的单次 `initialize` 请求中将 `capabilities.experimentalApi` 设为 `true`：

```json
{
  "method": "initialize",
  "id": 1,
  "params": {
    "clientInfo": {
      "name": "my_client",
      "title": "My Client",
      "version": "0.1.0"
    },
    "capabilities": {
      "experimentalApi": true
    }
  }
}
```

然后发送标准 `initialized` 通知并正常继续。

说明：

- 若省略 `capabilities`，`experimentalApi` 被视为 `false`。
- 此设置在初始化时为进程生命周期协商一次（重新初始化会以 `"Already initialized"` 被拒绝）。

### 未选择加入时会发生什么

若请求使用实验性方法或设置实验性字段而未选择加入，app-server 会以 JSON-RPC 错误拒绝它。消息为：

`<descriptor> requires experimentalApi capability`

descriptor 字符串示例：

- `mock/experimentalMethod`（方法级门控）
- `thread/start.mockExperimentalField`（字段级门控）
- `askForApproval.granular`（枚举变体门控，用于 `approvalPolicy: { "granular": ... }`）

### 维护者：添加实验性字段和方法

当引入仅在客户端选择加入实验性 API 时才应可用的字段 / 方法时，使用此清单。

在运行时，客户端必须发送带有 `capabilities.experimentalApi = true` 的 `initialize` 才能使用实验性方法或字段。

1. 在协议类型（通常是 `app-server-protocol/src/protocol/common.rs`）中用以下方式注解该字段：
   ```rust
   #[experimental("thread/start.myField")]
   pub my_field: Option<String>,
   ```
2. 确保 params 类型派生 `ExperimentalApi`，以便可以在运行时检测字段级门控。

3. 在 `app-server-protocol/src/protocol/common.rs` 中，保持方法稳定，并在仅部分字段是实验性时使用 `inspect_params: true`（例如 `thread/start`）。若整个方法是实验性的，用 `#[experimental("method/name")]` 注解该方法变体。

枚举变体也可以被门控：

```rust
#[derive(ExperimentalApi)]
enum AskForApproval {
    #[experimental("askForApproval.granular")]
    Granular { /* ... */ },
}
```

若稳定字段包含本身可能是实验性的嵌套类型，用 `#[experimental(nested)]` 标记该字段，以便 `ExperimentalApi` 将嵌套原因向上冒泡到包含类型：

```rust
#[derive(ExperimentalApi)]
struct Config {
    #[experimental(nested)]
    approval_policy: Option<AskForApproval>,
}
```

对于服务器发起的请求载荷，以相同方式注解该字段，以便 schema 生成将其视为实验性，并确保当客户端未选择加入 `experimentalApi` 时 app-server 省略该字段。

4. 重新生成协议 fixtures：

   ```bash
   just write-app-server-schema
   # 刷新包含实验性 API 字段 / 方法的嵌入导出。
   just write-app-server-schema --experimental
   ```

5. 校验协议 crate：

   ```bash
   just test -p codex-app-server-protocol
   ```
