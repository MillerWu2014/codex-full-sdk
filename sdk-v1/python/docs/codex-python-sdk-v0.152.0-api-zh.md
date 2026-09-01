# Codex Python SDK v0.152.0 接口文档（中文）

包：`openai-codex` **0.152.0**  
Runtime 钉死：`openai-codex-cli-bin==0.152.0`（内嵌 `codex app-server`）  
Python：`>=3.10`  
传输：stdio 上的 JSON-RPC v2（`codex app-server --listen stdio://`）

本文描述本版本 `sdk-v1/python` **公开** Python API，不是 app-server 全量 RPC。未封装的方法仍在 `openai_codex.generated.v2_all`；只能通过未导出的 `CodexClient.request` 调用（不在 `__all__`）。

英文对照：[codex-python-sdk-v0.152.0-api-en.md](codex-python-sdk-v0.152.0-api-en.md)  
仓库文档入口（章节目录 + 其它文档）：[`../../../README.md`](../../../README.md)  
App-server 覆盖表：[`../../app-server-api.zh.md`](../../app-server-api.zh.md)  
本机目录： [codex-home.md](codex-home.md)  
上手 / FAQ：[getting-started.md](getting-started.md) · [faq.md](faq.md)

---

## 1. Thread 与 Turn

这两个词就是整套对话模型。它们**不能互换**；**thread 也不是操作系统线程**。

| 维度        | **Thread（会话）**                                                        | **Turn（一轮执行）**                                               |
|:-----------:| ------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| 是什么      | 一条持久化的对话（一次聊天 / 一个 session）。                             | 这条对话里的 **一次** 模型执行。                                   |
| 生命周期    | 创建一次，之后每条用户消息都复用它；进程退出后仍在。                      | 你提交输入时开始，到 `turn/completed`（或中断 / 失败）结束。       |
| 身份        | `Thread.id` — 服务端 thread id。                                          | `TurnHandle.id` / `TurnResult.id` — 该 thread 上的某一次 turn。    |
| 落盘        | `~/.codex/sessions/.../rollout-<…>-<thread-id>.jsonl`，外加 SQLite 索引。 | 追加进**同一份** rollout（`turn_context` / items），没有单独文件。 |
| Python 类型 | `Thread` / `AsyncThread`                                                  | **没有** `Turn` 类。进行中是 `TurnHandle`，结束后是 `TurnResult`。 |
| 常用 API    | `codex.thread_start()` / `thread_resume(id)` / `thread_fork(id)`          | `thread.run(...)` 或 `thread.turn(...)`                            |

**Turn 不是「一条聊天消息」。** 一次 turn 是一次 harness 执行：你的输入，再加上模型为完成这次任务所需的多步推理、工具调用、改文件、跑命令，直到本轮结束。一条 thread 的 transcript 就是 **一串 turn**。

接着聊 = **同一个 `Thread`**，再开一次 turn。再调 `thread_start()` 是 **新对话**，历史为空。

不要把方法名 `Thread.turn(...)` 当成「turn 这个概念」。这个方法只是 **启动** 一次 turn 并返回 handle。`Thread.run(...)` 是同一个 RPC（`turn/start`）的阻塞写法：开一轮并等到结束。

```
Codex()  →  initialize + initialized
   │
   ├─ login_* / account / logout
   ├─ config / skills / mcp / fs  （配置 / 引擎面）
   └─ thread_start | resume | fork     ← 对话（Thread）
          └─ Thread.run / Thread.turn  ← 在该 Thread 上启动一次 Turn
                └─ TurnHandle.stream | run | steer | interrupt
```

SDK **不**自己拼 messages。上下文、压缩、工具、沙箱都在 Codex 内部的 harness。

`AsyncCodex` / `AsyncThread` / `AsyncTurnHandle` 与同步 API 同形，写操作为 `async`。推荐 `async with AsyncCodex()`。

---

## 2. 安装与导入

```bash
pip install openai-codex==0.152.0
```

```python
from openai_codex import (
    Codex,
    AsyncCodex,
    CodexConfig,
    ApprovalMode,
    Sandbox,
    Thread,
    AsyncThread,
    TurnHandle,
    AsyncTurnHandle,
    TurnResult,
    TextInput,
    ImageInput,
    LocalImageInput,
    AudioInput,
    LocalAudioInput,
    SkillInput,
    MentionInput,
    retry_on_overload,
)
from openai_codex.types import GetAccountResponse, ThreadItem, Notification
```

版本：`openai_codex.__version__` → `"0.152.0"`。

协议类型（注解 / 匹配）：`openai_codex.types`（再导出 generated v2）。

---

## 3. `CodexConfig`

```python
@dataclass
class CodexConfig:
    codex_bin: str | None = None
    launch_args_override: tuple[str, ...] | None = None  # 整段替换 argv
    config_overrides: tuple[str, ...] = ()  # 重复传入 --config KEY=VALUE
    cwd: str | None = None                  # app-server 进程 cwd
    env: dict[str, str] | None = None       # 合并进 os.environ
    client_name: str = "codex_python_sdk"
    client_title: str = "Codex Python SDK"
    client_version: str = SDK_VERSION
    experimental_api: bool = True           # 设 False 则实验 RPC 被挡住
```

默认启动：bundled `codex` + `--config` + `app-server --listen stdio://`。

0.152.0 里 `experimental_api` **默认 True**。下文标 **实验** 的接口仅在你设成 `False` 时抛 `ExperimentalApiDisabledError`。

内部 `CodexClient` 可注入 `approval_handler`；公开 `Codex` 不暴露。默认 handler 对命令/补丁审批自动 `accept`。

---

## 4. 生命周期

```python
with Codex() as codex:
    print(codex.metadata)  # InitializeResponse：userAgent、codexHome、platform*
# 退出时 close()
```

| 方法                 | RPC                         | 说明                      |
| -------------------- | --------------------------- | ------------------------- |
| `Codex(config=None)` | `initialize`、`initialized` | 同步：`__init__` 就起进程 |
| `close()`            | 关进程                      | 必须与构造配对            |
| `metadata`           | initialize 结果             | 属性                      |

`AsyncCodex` 在 `async with` 或第一次 await 时才 initialize。

---

## 5. 账户 / 登录

| 方法                              | RPC                                          | 返回                    |
| --------------------------------- | -------------------------------------------- | ----------------------- |
| `login_api_key(api_key)`          | `account/login/start`（`apiKey`）            | `None`（同步完成）      |
| `login_chatgpt()`                 | `account/login/start`（`chatgpt`）           | `ChatgptLoginHandle`    |
| `login_chatgpt_device_code()`     | `account/login/start`（`chatgptDeviceCode`） | `DeviceCodeLoginHandle` |
| `account(*, refresh_token=False)` | `account/read`                               | `GetAccountResponse`    |
| `logout()`                        | `account/logout`                             | `None`                  |

**未封装：** Bedrock 登录、配额、用量、workspace 邮件。

### 登录 handle

`ChatgptLoginHandle`：`login_id`、`auth_url`，`wait()` → `AccountLoginCompletedNotification`，`cancel()` → `CancelLoginAccountResponse`。

`DeviceCodeLoginHandle`：`login_id`、`verification_url`、`user_code`，同样的 `wait` / `cancel`。

`wait()` **只**消费该 `login_id` 的完成通知。

---

## 6. `Codex` — Thread

这些方法创建、列出、恢复或 fork **一条对话**，本身不会跑模型。跑模型是在返回的 SDK `Thread` 上开一次 **turn**（第 7 节）。有两个容易混的 `Thread`：

| 名字                      | 是什么                                                              | 怎么拿到                                                              |
| ------------------------- | ------------------------------------------------------------------- | --------------------------------------------------------------------- |
| SDK `openai_codex.Thread` | 对话句柄，只有 `.id`，上面挂 `run` / `turn` / `read` 等             | `thread_start` / `thread_resume` / `thread_fork` / `thread_unarchive` |
| 协议 `types.Thread`       | 元数据快照：`id`、`cwd`、`name`、`preview`、`status`、`created_at`… | `thread_list().data`、`thread.read().thread` 等                       |

未写默认值的关键字参数均可省略（`None` = 交给服务端 / 已有 thread 设置）。`thread_start` 的 `approval_mode` 默认 `ApprovalMode.auto_review`。

**`thread_start` 未封装：** `permissions`、`dynamicTools`。

### 6.1 方法一览

| 方法                                                     | 作用                                             | 参数                                                                                                                           | 返回                                                                                |
| -------------------------------------------------------- | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------- |
| `thread_start(**kwargs)`                                 | 新建一条空对话                                   | 仅关键字，见 [6.2](#62-thread_start--resume--fork-共用参数)                                                                    | SDK `Thread`（`.id` = 新 thread id）                                                |
| `thread_list(**kwargs)`                                  | 列出已保存对话                                   | 见 [6.3](#63-thread_list)                                                                                                      | `ThreadListResponse`：`data: list[types.Thread]`，`next_cursor`，`backwards_cursor` |
| `thread_resume(thread_id, **kwargs)`                     | 把已有对话加载进当前 app-server，以便继续跑 turn | 位置：`thread_id: str`；关键字见 6.2，另有 `exclude_turns`                                                                     | SDK `Thread`                                                                        |
| `thread_fork(thread_id, **kwargs)`                       | 从已有对话复制出**新** thread（新 id）           | 位置：`thread_id`；关键字见 6.2，另有 `before_turn_id` **实验**、`last_turn_id`、`exclude_turns`、`ephemeral`、`thread_source` | SDK `Thread`（新 id）                                                               |
| `thread_archive(thread_id)`                              | 归档（列表默认不再出现）                         | `thread_id: str`                                                                                                               | `ThreadArchiveResponse`（空对象）                                                   |
| `thread_unarchive(thread_id)`                            | 取消归档                                         | `thread_id: str`                                                                                                               | SDK `Thread`                                                                        |
| `thread_delete(thread_id)`                               | 删除存储的对话                                   | `thread_id: str`                                                                                                               | `ThreadDeleteResponse`（空对象）                                                    |
| `thread_loaded_list(*, cursor, limit)`                   | 当前进程内存里已加载的 thread id                 | `cursor: str \| None`，`limit: int \| None`                                                                                    | `ThreadLoadedListResponse`：`data: list[str]`，`next_cursor`                        |
| `thread_section_list(*, cursor, limit)`                  | 列出 UI 分组（section）                          | 同上                                                                                                                           | `ThreadSectionListResponse`：`data: list[ThreadSection]`，`next_cursor`             |
| `thread_section_create(name, *, appearance)`             | 新建分组                                         | `name: str`；`appearance: ThreadSectionAppearance \| None`（`color` / `icon`）                                                 | `ThreadSectionCreateResponse.section`                                               |
| `thread_section_update(section_id, name, *, appearance)` | 改分组名/外观                                    | `section_id: str`，`name: str`，`appearance` 可选                                                                              | `ThreadSectionUpdateResponse.section`                                               |
| `thread_section_delete(section_id)`                      | 删分组                                           | `section_id: str`                                                                                                              | `ThreadSectionDeleteResponse`（空对象）                                             |

### 6.2 `thread_start` / `resume` / `fork` 共用参数

除特别注明外，`None` = 不覆盖。

| 参数                     | 类型                                  | 作用                                                                                                               |
| ------------------------ | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `approval_mode`          | `ApprovalMode`                        | 命令/补丁审批。`auto_review`（默认，仅 `start`）或 `deny_all`。映射到线上 `approvalPolicy` / `approvalsReviewer`。 |
| `sandbox`                | `Sandbox \| None`                     | 文件系统权限：`read_only` / `workspace_write` / `full_access`。省略则用配置默认。                                  |
| `cwd`                    | `str \| None`                         | 该对话的工作目录（绝对路径）。                                                                                     |
| `model`                  | `str \| None`                         | 模型 slug（如 `gpt-5.4`），不是本地 Ollama 标签列表。                                                              |
| `model_provider`         | `str \| None`                         | `config.toml` 里 `[model_providers.*]` 的名字。                                                                    |
| `personality`            | `Personality \| None`                 | `none` / `friendly` / `pragmatic`。                                                                                |
| `base_instructions` | `str \| None` | 覆盖模型内置 base。一般不要用；详见 [第 11 节](#11-自定义系统提示词)。 |
| `developer_instructions` | `str \| None` | 额外 developer 消息。自定义「系统提示」优先用这个。 |
| `config`                 | `dict \| None`                        | 本 thread 的配置覆盖（JSON 对象）。                                                                                |
| `service_tier`           | `str \| None`                         | 服务档位覆盖。                                                                                                     |
| `environments`           | `list[TurnEnvironmentParams] \| None` | **实验**（仅 `start`）。粘性 environment；空列表表示关掉。                                                         |

仅 `thread_start`：

| 参数                   | 类型                        | 作用                                                     |
| ---------------------- | --------------------------- | -------------------------------------------------------- |
| `ephemeral`            | `bool \| None`              | `True` 则尽量不落盘。                                    |
| `service_name`         | `str \| None`               | 服务名（分析/计费用）。                                  |
| `session_start_source` | `ThreadStartSource \| None` | `startup` / `clear`。                                    |
| `thread_source`        | `ThreadSource \| None`      | 分析分类：`user` / `subagent` / `memory_consolidation`。 |

仅 `thread_resume` / `thread_fork`：

| 参数             | 类型           | 作用                                                                                          |
| ---------------- | -------------- | --------------------------------------------------------------------------------------------- |
| `exclude_turns`  | `bool \| None` | `True` 时响应不灌满历史 turn；随后用 `turns_list` / `items_list` 分页。                       |
| `before_turn_id` | `str \| None`  | **实验，仅 fork**。在该 turn **之前**切开（不含该 turn 及之后）。不能与 `last_turn_id` 同用。 |
| `last_turn_id`   | `str \| None`  | **仅 fork**。包含该 turn，丢掉之后的 turn；该 turn 不能仍在进行中。                           |

### 6.3 `thread_list`

全部关键字可选。

| 参数                | 类型                             | 作用                                                              |
| ------------------- | -------------------------------- | ----------------------------------------------------------------- |
| `archived`          | `bool \| None`                   | `True` 只列已归档；`False`/`None` 只列未归档。                    |
| `cursor`            | `str \| None`                    | 上一页的 `next_cursor`。                                          |
| `cwd`               | `str \| list[str] \| None`       | session cwd **精确**匹配。                                        |
| `limit`             | `int \| None`                    | 页大小。                                                          |
| `model_providers`   | `list[str] \| None`              | 按记录的 provider 过滤；空列表 = 不过滤。                         |
| `search_term`       | `str \| None`                    | 标题子串。                                                        |
| `section_id`        | `str \| None`                    | 只列该分组。                                                      |
| `sort_direction`    | `SortDirection \| None`          | `asc` / `desc`（默认新的在前）。                                  |
| `sort_key`          | `ThreadSortKey \| None`          | `created_at` / `updated_at` / `recency_at` / `section_position`。 |
| `source_kinds`      | `list[ThreadSourceKind] \| None` | 来源：`cli` / `vscode` / `appServer` 等。                         |
| `use_state_db_only` | `bool \| None`                   | 只查 SQLite 索引，不扫 rollout。                                  |

`types.Thread` 常用字段：`id`（UUIDv7）、`cwd`、`name`、`preview`、`created_at` / `updated_at`（Unix 秒）、`ephemeral`、`model_provider`、`cli_version`、`status`、`forked_from_id`、`parent_thread_id`、`project_id`、`section`。`turns` 在 list 结果里通常是空列表。

---

## 7. `Thread`

SDK `Thread`：`id` 是服务端 thread id。`run` / `turn` **新开一轮 turn**；其余方法改这条对话，本身不是一次模型执行。

### 7.1 方法一览

| 方法                                          | 作用                                          | 参数                                                                                                                                            | 返回                                                                                                 |
| --------------------------------------------- | --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `run(input, **turn_kwargs)`                   | 开一轮并等到结束                              | 见 [7.2](#72-run--turn-参数)                                                                                                                    | `TurnResult`；失败抛 `RuntimeError`                                                                  |
| `turn(input, **turn_kwargs)`                  | 开一轮，立刻把控制权给你                      | 同 `run`                                                                                                                                        | `TurnHandle`（`.id` = turn id，`.thread_id`）                                                        |
| `read(*, include_turns=False)`                | 读元数据；不单独抢 resume 写锁                | `include_turns: bool`：是否带上 `thread.turns`                                                                                                  | `ThreadReadResponse.thread`（协议 `Thread`）                                                         |
| `set_name(name)`                              | 设标题，并追加 `session_index.jsonl`          | `name: str`                                                                                                                                     | `ThreadSetNameResponse`（空对象）                                                                    |
| `compact()`                                   | 请求压缩上下文                                | 无                                                                                                                                              | `ThreadCompactStartResponse`（立刻空对象）；进度走 turn/item 通知。父级 Multi-Agent V2 子 agent 拒绝 |
| `unsubscribe()`                               | 取消本连接对该 thread 的订阅                  | 无                                                                                                                                              | `ThreadUnsubscribeResponse.status`：`unsubscribed` / `notLoaded` / `notSubscribed`                   |
| `turns_list(...)`                             | 分页列出 store 里的 turn                      | `cursor`，`limit`，`sort_direction`，`items_view`（`notLoaded` / `summary` / `full`，默认 summary）                                             | `ThreadTurnsListResponse`：`data: list[Turn]`，`next_cursor`，`backwards_cursor`                     |
| `items_list(...)`                             | 分页列出 item                                 | `cursor`，`limit`，`sort_direction`，`turn_id`（只列该 turn）                                                                                   | `ThreadItemsListResponse`：`data: list[ThreadItemEntry]`（`item` + `turn_id`），游标同上             |
| `revert(before_turn_id)`                      | 丢掉该 turn 及之后的历史                      | `before_turn_id: str`                                                                                                                           | `ThreadRevertResponse`：`thread`（`turns` 为空），加 items/turns 回溯游标                            |
| `inject_items(items)`                         | 写入原始 Responses item，**不开**新 turn      | `items: list[dict]`                                                                                                                             | `ThreadInjectItemsResponse`                                                                          |
| `metadata_update(...)`                        | 改 SQLite 元数据                              | `git_info: ThreadMetadataGitInfoUpdateParams \| None`（`branch` / `origin_url` / `sha`），`project_id: str \| None`                             | `ThreadMetadataUpdateResponse.thread`                                                                |
| `section_move(...)`                           | 把本 thread 挪到某分组 / 某条之前             | `section_id`，`before_thread_id`（均可 `None`）                                                                                                 | `ThreadSectionMoveResponse`                                                                          |
| `mcp_tool_call(server, tool, ...)`            | 在已加载 thread 上直接调 MCP 工具             | `server: str`，`tool: str`；`arguments`、`field_meta` 可选。子 agent 拒绝                                                                       | `McpServerToolCallResponse`：`content`，`is_error`，`structured_content`                             |
| `goal_get()`                                  | 读该 thread 的 goal                           | 无                                                                                                                                              | `ThreadGoalGetResponse.goal`（可能 `None`）                                                          |
| `goal_set(*, objective, status)`              | 设目标/状态                                   | `objective: str \| None`，`status: ThreadGoalStatus \| None`（`active` / `paused` / `blocked` / `usageLimited` / `budgetLimited` / `complete`） | `ThreadGoalSetResponse.goal`                                                                         |
| `goal_clear()`                                | 清 goal                                       | 无                                                                                                                                              | `ThreadGoalClearResponse.cleared: bool`                                                              |
| `queue_add(input, *, client_user_message_id)` | **实验** 排队一条用户输入（当前 turn 还在跑） | `input` 同 turn；`client_user_message_id: str` 必填                                                                                             | `ThreadQueueAddResponse.queued_submission`                                                           |
| `queue_list(*, cursor, limit)`                | **实验** 列队                                 | 分页                                                                                                                                            | `ThreadQueueListResponse`：`data`，`next_cursor`                                                     |
| `queue_update(queued_submission_id, input)`   | **实验** 改已排队项                           | id + 新 `input`                                                                                                                                 | `ThreadQueueUpdateResponse`                                                                          |
| `queue_delete(queued_submission_id)`          | **实验** 删排队项                             | id                                                                                                                                              | `ThreadQueueDeleteResponse`                                                                          |
| `queue_reorder(queued_submission_ids)`        | **实验** 重排                                 | `list[str]` 新顺序                                                                                                                              | `ThreadQueueReorderResponse`                                                                         |
| `queue_start(*, queued_submission_id)`        | **实验** 立刻开跑排队项                       | 省略则按队头                                                                                                                                    | `ThreadQueueStartResponse.turn`（协议 `Turn`）                                                       |
| `memory_mode_set(mode)`                       | **实验** 开关该 thread 的 memory              | `mode: ThreadMemoryMode`（`enabled` / `disabled`）                                                                                              | `ThreadMemoryModeSetResponse`（空对象）                                                              |
| `settings_update(**kwargs)`                   | **实验** 改**下一轮**设置，不开 turn          | 见下                                                                                                                                            | `ThreadSettingsUpdateResponse`（空对象）                                                             |

`settings_update` 关键字（均可省略）：`approval_mode`、`collaboration_mode`、`cwd`、`effort`、`model`、`personality`、`sandbox`、`service_tier`、`summary`。

协议 `Turn`（`turns_list` / 部分通知）：`id`、`status`（`completed` / `interrupted` / `failed` / `inProgress`）、`started_at` / `completed_at`（Unix 秒）、`duration_ms`、`error`、`items`、`items_view`。

### 7.2 `run` / `turn` 参数

位置参数 `input: str | Input`（`str` ≡ `TextInput`；列表则一次提交多项，见第 9 节）。其余仅关键字；本 turn 传入的 `sandbox` / `approval_mode` 会粘到**之后的 turn**。

| 参数            | 类型                                  | 作用                                                                         |
| --------------- | ------------------------------------- | ---------------------------------------------------------------------------- |
| `approval_mode` | `ApprovalMode \| None`                | 覆盖本 turn 及之后的审批。                                                   |
| `sandbox`       | `Sandbox \| None`                     | 覆盖本 turn 及之后的沙箱。                                                   |
| `cwd`           | `str \| None`                         | 覆盖工作目录。                                                               |
| `model`         | `str \| None`                         | 覆盖模型。                                                                   |
| `effort`        | `ReasoningEffort \| None`             | `none` / `minimal` / `low` / `medium` / `high` / `xhigh` / `max` / `ultra`。 |
| `summary`       | `ReasoningSummary \| None`            | 推理摘要：`auto` / `concise` / `detailed` / `"none"`。                       |
| `personality`   | `Personality \| None`                 | 覆盖性格。                                                                   |
| `service_tier`  | `str \| None`                         | 覆盖服务档。                                                                 |
| `output_schema` | `dict \| None`                        | JSON Schema，约束本轮最终助手消息。                                          |
| `environments`  | `list[TurnEnvironmentParams] \| None` | **实验**。省略用 thread 粘性环境；`[]` 本轮关掉。                            |
| `tool_output`   | `TurnToolOutput \| None`              | 向进行中的工具调用回灌输出：`name`、`namespace`、`output`。                  |

---

## 8. `TurnHandle`

一次 **进行中的 turn**：属性 `thread_id`、`id`（turn id）。不是对话。结束后用 `TurnResult`；handle 已用完。一个 `Codex` 可同时 stream 多个 turn，按 turn id 路由。

| 方法                   | 作用                                               | 参数                                                                | 返回                                                                 |
| ---------------------- | -------------------------------------------------- | ------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `stream()`             | 只收**本** `turn.id` 的通知，直到 `turn/completed` | 无                                                                  | `Iterator[Notification]`（`method` + `payload`）                     |
| `run()`                | 消费 `stream()` 并汇总                             | 无                                                                  | `TurnResult`（与 `Thread.run` 相同）；失败抛 `RuntimeError`          |
| `steer(input)`         | 向**进行中**的常规 turn 追加输入                   | `input: str \| Input`。review / compact turn 拒绝                   | `TurnSteerResponse.turn_id`                                          |
| `interrupt()`          | 请求中断本轮                                       | 无                                                                  | `TurnInterruptResponse`（空对象）                                    |
| `settings_update(...)` | **实验** 热改正在跑的 task                         | 关键字：`effort`、`model`、`service_tier`、`summary`（均可 `None`） | `TurnSettingsUpdateResponse.status`：`applied` / `targetUnavailable` |

### `TurnResult`

`Thread.run()` / `TurnHandle.run()` 从本轮 `item/completed` 和 `turn/completed` 汇总，**不是**协议里的 `Turn` 原样拷贝。

| 字段                          | 类型                       | 含义                                                                                                |
| ----------------------------- | -------------------------- | --------------------------------------------------------------------------------------------------- |
| `id`                          | `str`                      | turn id（UUIDv7）                                                                                   |
| `status`                      | `TurnStatus`               | `completed` / `interrupted` / `failed` / `inProgress`                                               |
| `error`                       | `TurnError \| None`        | 仅 `failed` 时有                                                                                    |
| `started_at` / `completed_at` | `int \| None`              | Unix **秒**                                                                                         |
| `duration_ms`                 | `int \| None`              | 耗时毫秒                                                                                            |
| `final_response`              | `str \| None`              | 优先 `phase=final_answer` 的助手文本，否则最后一条无 phase 的助手消息                               |
| `items`                       | `list[ThreadItem]`         | 本轮完成的 item                                                                                     |
| `usage`                       | `ThreadTokenUsage \| None` | 来自 `thread/tokenUsage/updated`：`last` / `total`（`TokenUsageBreakdown`），`model_context_window` |

`status=failed` 时 `run()` **抛** `RuntimeError`（优先 `TurnError.message`），不会返回失败的 `TurnResult`。

---

## 9. 输入

```python
TextInput(text)
ImageInput(url)          # data:image/...；HTTP(S) URL 已弃用
LocalImageInput(path)
AudioInput(url)
LocalAudioInput(path)
SkillInput(name, path)
MentionInput(name, path)  # app://... 或 plugin://...
```

turn 入参里的 `str` ≡ `TextInput`。item 列表作为一次 `turn/start` 的 `input` 数组。

---

## 10. `ApprovalMode` 与 `Sandbox`

| 枚举                       | 线上                                                       |
| -------------------------- | ---------------------------------------------------------- |
| `ApprovalMode.auto_review` | `approvalPolicy=onRequest`，`approvalsReviewer=autoReview` |
| `ApprovalMode.deny_all`    | `approvalPolicy=never`                                     |
| `Sandbox.read_only`        | thread：`read-only`；turn：`{type: readOnly}`              |
| `Sandbox.workspace_write`  | `workspace-write` / `{type: workspaceWrite}`               |
| `Sandbox.full_access`      | `danger-full-access` / `{type: dangerFullAccess}`          |

省略 sandbox → 服务端默认（已信任工程常见 `workspace_write`）。

公开 SDK **没有**自定义审批 UI。命令/补丁默认自动接受。细粒度 `item/permissions/requestApproval`、elicitation、`item/tool/call` 未暴露。

---

## 11. 自定义系统提示词

Codex **没有**单独的 `system_prompt=`。发给模型的「系统侧」文本是几层叠在一起的，SDK 只能改其中几层；工具说明、沙箱/环境块、skill 说明仍由 harness 注入。

| 层 | 角色 | 改什么 | 推荐用法 |
| --- | --- | --- | --- |
| **base instructions** | 模型内置工作说明书（随 `personality` 变） | `thread_start(base_instructions=...)`，或配置键 `instructions` / `model_instructions_file` | 一般**不要**整段替换；偏离官方模板会明显伤效果 |
| **developer instructions** | 额外 `developer` 角色消息 | `thread_start(developer_instructions=...)`，或配置键 `developer_instructions` | SDK 里自定义「系统提示」的主入口 |
| **AGENTS.md** | 用户/工程说明，进 `<user_instructions>` | 写 Markdown 文件，不是 RPC | 仓库级规范、编码约定；和 CLI / IDE 共用 |
| **本轮用户输入** | 普通 user 消息 | `thread.run(...)` | 一次性任务，不是系统提示 |

`Thread.run` / `turn` **没有** `base_instructions` / `developer_instructions`。要改系统侧文本，在 **start / resume / fork** 时传入，或改配置后 **新开** thread（已加载 thread 不会因为改 toml 自动换 base/developer 指令）。

`thread_start(cwd=...)` 决定从哪棵目录树找工程 `AGENTS.md`。`personality` 只影响默认 base 模板，不是自由文本。

### Python SDK

只对这一条对话加说明（不改磁盘配置）：

```python
from openai_codex import Codex, Sandbox

SYSTEM = "你是后端评审员。回复用中文。没有依据不要改代码。"

with Codex() as codex:
    thread = codex.thread_start(
        sandbox=Sandbox.workspace_write,
        developer_instructions=SYSTEM,
        # 可选：覆盖内置 base。不推荐。
        # base_instructions="...",
        cwd="/path/to/repo",
    )
    result = thread.run("检查 auth 模块。")
```

`thread_resume` / `thread_fork` 同样接受这两个关键字。

启动进程时注入（所有新 thread 都吃到，等同 CLI `--config`）：

```python
from openai_codex import Codex, CodexConfig

cfg = CodexConfig(
    config_overrides=(
        "developer_instructions=Always answer in Chinese.",
    ),
)
with Codex(cfg) as codex:
    thread = codex.thread_start()
    ...
```

用配置 RPC 写进 `~/.codex/config.toml`（持久，CLI 也生效）：

```python
from openai_codex import Codex
from openai_codex.types import MergeStrategy

with Codex() as codex:
    codex.config_value_write(
        "developer_instructions",
        "Always answer in Chinese. Prefer small diffs.",
        MergeStrategy.replace,
    )
    # 之后新开的 thread 才会用到
    thread = codex.thread_start()
```

覆盖内置 base（不推荐）时，配置键是 **`instructions`**，不是 `base_instructions`：

```python
codex.config_value_write("instructions", "...", MergeStrategy.replace)
# 或 CodexConfig(config_overrides=("instructions=...",))
# 或 thread_start(base_instructions="...")
```

从文件读入官方所谓的 model instructions：`config.toml` 里设 `model_instructions_file = "/abs/path.txt"`（相对路径相对生效 cwd）。SDK 侧也可 `config_value_write("model_instructions_file", "/abs/path.txt", MergeStrategy.replace)`。优先级：`thread_start(base_instructions=)` > 该文件 > `instructions` 键 > 模型内置模板。

### 配置文件

用户级 `~/.codex/config.toml`（或工程层 `.codex/config.toml`）：

```toml
developer_instructions = """
你是代码评审员。用中文。先给结论再给证据。
"""

# 不推荐：替换模型内置 base
# instructions = "..."
# model_instructions_file = "/abs/path/to/instructions.txt"
```

仓库级（随 `cwd` 合并进上下文，不是 `developer` 角色）：

- 工程根：`AGENTS.md`
- 覆盖层：`AGENTS.override.md`
- 用户全局：`~/.codex/AGENTS.md`（再与工程文件合并）

缺 `AGENTS.md` 时可用 `project_doc_fallback_filenames` 指定备用文件名。总大小受 `project_doc_max_bytes` 限制。详见 [codex-home.md](codex-home.md)。

### 不要指望的

- 在 `run()` 里传系统提示：没有这个参数。
- 只改 `config.toml` 就更新**已经** `thread_start` / `resume` 的会话：base / developer 在 thread 启动时定。
- 用空字符串清掉内置 base：省略参数才是「用默认」；显式传入会当成自定义 base。
- 实验性 `collaboration_mode` 若带了自己的 `developer_instructions`，会盖过你设的 developer 文本。

---

## 12. 管理 Skill 与 MCP

配置面（发现、开关、写 `config.toml`）和数据面（本轮 turn 里用）要分开。公开 SDK **没有** `plugin/install`、MCP OAuth；插件自带的 skill/MCP 装不上、需要浏览器登录的远程 MCP 也完不成授权。

| 你想做的 | Skill | MCP |
| --- | --- | --- |
| 新增 | 在磁盘写 `SKILL.md`（或 `skills_extra_roots_set` 指到已有目录） | `config_value_write("mcp_servers.<name>", {...})`，再 `mcp_reload()` |
| 删除 | 删目录 / `fs_remove`；或只关掉 | `config_value_write("mcp_servers.<name>", None, replace)`，再 `mcp_reload()` |
| 开关 | `skills_config_write(enabled, name=…)` | `config_value_write("mcp_servers.<name>.enabled", True/False)`，再 `mcp_reload()` |
| 列出 | `skills_list` | `mcp_status_list` |
| 本轮注入 / 使用 | `SkillInput` + 文本 `$name` | 模型在 turn 里自己调工具；或 `thread.mcp_tool_call` |

RPC 字段见 [第 13 节](#13-模型配置skillmcp文件系统)。

### Skill：落盘与开关

Skill **不是** config 里的一段 JSON，而是带 front matter 的 `SKILL.md`。扫描根：

- 用户：`~/.codex/skills/<name>/SKILL.md`
- 工程：`<cwd>/.codex/skills/` 或 `<cwd>/.agents/skills/`（测试里用过后者）
- 本进程额外根：`skills_extra_roots_set`（**不持久化**）

**新增（写文件）** — 没有 `skills/create` RPC：

```python
from pathlib import Path
from openai_codex import Codex

home = Path.home() / ".codex" / "skills" / "reviewer"
home.mkdir(parents=True, exist_ok=True)
(home / "SKILL.md").write_text(
    "---\nname: reviewer\ndescription: 代码评审约定\n---\n\n先给结论，再给证据。\n",
    encoding="utf-8",
)

with Codex() as codex:
    listed = codex.skills_list(force_reload=True)
    skill = next(s for entry in listed.data for s in entry.skills if s.name == "reviewer")
```

也可用 `codex.fs_write_file(path, data_base64)` 写同一路径。临时目录：`codex.skills_extra_roots_set(["/abs/extra/skills"])` 后 `skills_list(force_reload=True)`。

**开关（持久化到用户 config 的 `[[skills.config]]`）**：

```python
codex.skills_config_write(False, name="reviewer")           # 关
codex.skills_config_write(True, name="reviewer")            # 开
codex.skills_config_write(False, path=str(skill.path))      # 按绝对路径选
```

**删除**：`fs_remove` 掉该 skill 目录（`recursive=True`），或只 `skills_config_write(False, …)` 保留文件但禁用。没有单独的 `skills/delete` RPC。

**本轮注入**（让模型读到正文，比只靠 `$name` 解析稳）：

```python
from openai_codex import SkillInput, TextInput

thread = codex.thread_start(cwd="/path/to/repo")
result = thread.run(
    [
        TextInput("按 $reviewer 检查 auth。"),
        SkillInput("reviewer", str(skill.path)),
    ]
)
```

省略 `SkillInput`、只在文本里写 `$reviewer` 时，模型自己去目录里找，更慢、不稳定。`skills/list` **不会**把 skill 塞进 turn。

等价 toml：

```toml
[[skills.config]]
name = "reviewer"
enabled = false
```

### MCP：写配置、reload、开关

没有 `mcp/add` RPC。登记在 `config.toml` 的 `[mcp_servers.<name>]`，然后 **`mcp_reload()`**。已加载 thread 要到 **下一轮 turn** 才用新进程；省略 `thread_id` 的 `mcp_status_list` 能立刻看到配置，但 `runtime_status` 为 `None`。

**新增 stdio 服务器**：

```python
from openai_codex import Codex
from openai_codex.types import MergeStrategy

with Codex() as codex:
    codex.config_value_write(
        "mcp_servers.docs",
        {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            "enabled": True,
        },
        MergeStrategy.replace,
    )
    codex.mcp_reload()
    status = codex.mcp_status_list()
```

HTTP / Streamable HTTP 用 `url`（可选 `bearer_token_env_var`、`http_headers`）。`command` 与 `url` 不要同时设。常用字段：`args`、`env`、`cwd`、`enabled`、`enabled_tools` / `disabled_tools`、`startup_timeout_sec`、`required`。

启动时注入（不写盘）：

```python
from openai_codex import CodexConfig

cfg = CodexConfig(
    config_overrides=(
        'mcp_servers.docs.command=npx',
        'mcp_servers.docs.args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]',
    ),
)
```

手改 toml 同样要 `mcp_reload()`：

```toml
[mcp_servers.docs]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
enabled = true
```

**开关 / 删除**：

```python
codex.config_value_write("mcp_servers.docs.enabled", False, MergeStrategy.replace)
codex.mcp_reload()  # 禁用，配置还在

codex.config_value_write("mcp_servers.docs", None, MergeStrategy.replace)
codex.mcp_reload()  # 从 toml 删掉该 server
```

**使用**：配好之后，模型在 `thread.run(...)` 里会自己调 MCP 工具。客户端直调：

```python
thread = codex.thread_start()
out = thread.mcp_tool_call("docs", "list_directory", arguments={"path": "/tmp"})
```

需要 OAuth 的远程 MCP：SDK **没有** `mcpServer/oauth/login`，先用 CLI/IDE 登好，或换 stdio / 带 env token 的 HTTP。

---

## 13. 模型、配置、Skill、MCP、文件系统

### 模型

| 方法                              | RPC                                                |
| --------------------------------- | -------------------------------------------------- |
| `models(*, include_hidden=False)` | `model/list` — 目录 slug，**不是**本地 Ollama 标签 |
| `model_provider_capabilities()`   | `modelProvider/capabilities/read`                  |

本地 vLLM / Ollama：`config.toml` 的 `[model_providers.*]`，再在 thread/turn 上设 `model=` / `model_provider=`。

### 配置

改的是 `~/.codex/config.toml`（及工程层），**不是** `CodexConfig.config_overrides`（那是启动 CLI 的 `--config`）。

| 方法 | 作用 | 参数 | 返回 |
| --- | --- | --- | --- |
| `config_read(*, cwd, include_layers)` | 读生效配置 | `cwd: str \| None`：从该目录解析工程层；`include_layers: bool \| None`：是否带分层明细 | `ConfigReadResponse`：`config`（合并后的 `Config`），`origins`（各键来自哪一层），`layers`（仅 `include_layers` 时） |
| `config_value_write(key_path, value, merge_strategy, *, expected_version, file_path)` | 写单个键 | 见下表 | `ConfigWriteResponse`：`file_path`，`version`，`status`（`ok` / `okOverridden`），`overridden_metadata` |
| `config_batch_write(edits, *, expected_version, file_path, reload_user_config)` | 一次写多个键 | 见下表 | 同上 `ConfigWriteResponse` |
| `config_requirements_read()` | 读 MDM / `requirements.toml` 约束 | 无 | `ConfigRequirementsReadResponse.requirements`（未配置则为 `None`） |
| `experimental_feature_list(*, cursor, limit, thread_id)` | 列实验开关 | `cursor` / `limit` 分页；`thread_id`：按该已加载 thread 的 cwd 算 enablement | `ExperimentalFeatureListResponse`：`data: list[ExperimentalFeature]`，`next_cursor` |
| `experimental_feature_enablement_set(enablement)` | 批量改实验开关 | `enablement: dict[str, bool]`（键 = feature `name`） | `ExperimentalFeatureEnablementSetResponse.enablement`（实际写进去的项） |
| `external_agent_config_detect(...)` | 探测可从外部 agent 迁入的配置 | 见下表 | `ExternalAgentConfigDetectResponse`：`items`，`connectors` |
| `external_agent_config_import(migration_items, ...)` | 执行迁入 | 位置：`migration_items: list[ExternalAgentConfigMigrationItem]`；关键字 `migration_source` / `provider_id` / `source` | `ExternalAgentConfigImportResponse.import_id`（进度走通知） |
| `external_agent_config_import_read_histories()` | 读迁入历史 | 无 | `ExternalAgentConfigImportHistoriesReadResponse`：`data`，`connectors` |

`config_value_write` / `config_batch_write`：

| 参数 | 类型 | 作用 |
| --- | --- | --- |
| `key_path` | `str` | 点分键（仅 `value_write`）。 |
| `value` | 任意 JSON | 要写入的值（仅 `value_write`）。 |
| `merge_strategy` | `MergeStrategy` | `replace` 整段替换；`upsert` 合并。 |
| `edits` | `list[ConfigEdit]` | 仅 batch：每项 `key_path` + `value` + `merge_strategy`。 |
| `expected_version` | `str \| None` | 乐观锁，对不上则失败。 |
| `file_path` | `str \| None` | 目标 toml；省略则用户 `config.toml`。 |
| `reload_user_config` | `bool \| None` | 仅 batch。`True` 则热加载到已加载 thread。模型 / effort / personality 等 session 静态项不会热更。 |

`ExperimentalFeature` 常用字段：`name`、`enabled`、`default_enabled`、`stage`（`beta` / `underDevelopment` / `stable` / `deprecated` / `removed`），以及可选 `display_name` / `description` / `announcement`。

`external_agent_config_detect` 关键字（均可省略）：`cwds`（仓库目录列表）、`include_home`、`max_session_age_days`、`max_sessions`、`migration_source`、`source`。`ExternalAgentConfigMigrationItem`：`item_type`（`AGENTS_MD` / `CONFIG` / `SKILLS` / `PLUGINS` / `MCP_SERVER_CONFIG` / …）、`description`、`cwd`（空 = home 范围）、`details`。

### Skill

Skill 是磁盘上的 `SKILL.md` 能力包。列出/开关用下面的 RPC；增删与本轮注入见 [第 12 节](#12-管理-skill-与-mcp)。**本轮要用某个 skill**：文本里写 `$name`，并带 `SkillInput(name, path)`。

| 方法 | 作用 | 参数 | 返回 |
| --- | --- | --- | --- |
| `skills_list(*, cwds, force_reload)` | 扫描可见 skill | `cwds: list[str] \| None`：空则用当前 session cwd；`force_reload: bool \| None`：`True` 跳过缓存重扫盘 | `SkillsListResponse.data`：每项 `cwd`、`skills`、`errors` |
| `skills_extra_roots_set(extra_roots)` | 给本进程加额外扫描根 | `extra_roots: list[str]`（绝对路径）。**不写盘**，进程结束即丢 | `SkillsExtraRootsSetResponse`（空对象） |
| `skills_config_write(enabled, *, name, path)` | 持久化打开/关闭某个 skill | `enabled: bool`；用 `name` 或 `path`（绝对路径）选中，至少一种 | `SkillsConfigWriteResponse.effective_enabled` |
| `plugin_skill_read(remote_marketplace_name, remote_plugin_id, skill_name)` | 读远程插件里某 skill 的正文 | 三个 `str`，均为必填 | `PluginSkillReadResponse.contents`（可能 `None`） |

`SkillMetadata` 常用字段：`name`、`path`、`enabled`、`description`、`short_description`、`scope`（`user` / `repo` / `system` / `admin`）、`plugin_id`、`interface`、`dependencies`。

### MCP

MCP 服务器配在 `config.toml` 的 `[mcp_servers]`。增删/开关/reload 见 [第 12 节](#12-管理-skill-与-mcp)。模型在 **turn 里自己调** MCP 会执行。下面是 SDK 直接调的管理/读取口。**未封装：** MCP OAuth、MCP 事件流。

| 方法 | 作用 | 参数 | 返回 |
| --- | --- | --- | --- |
| `mcp_reload()` | 按当前配置重载 MCP 进程 | 无。**下一轮 turn** 才生效 | `McpServerRefreshResponse`（空对象） |
| `mcp_status_list(*, cursor, detail, limit, thread_id)` | 列 MCP 服务器状态与工具清单 | 见下表 | `ListMcpServerStatusResponse`：`data: list[McpServerStatus]`，`next_cursor` |
| `mcp_resource_read(server, uri, *, connector_id, origin_call_id, thread_id)` | 读某 MCP 资源 | 位置：`server`、`uri`；关键字见下表 | `McpResourceReadResponse`：`contents`，`origin_call_id` |
| `thread.mcp_tool_call(server, tool, *, arguments, field_meta)` | 在**已加载** thread 上直接调工具（不是模型发起） | 见第 7 节。子 agent 拒绝 | `McpServerToolCallResponse`：`content`，`is_error`，`structured_content` |

`mcp_status_list`：

| 参数 | 类型 | 作用 |
| --- | --- | --- |
| `cursor` / `limit` | `str \| None` / `int \| None` | 分页。 |
| `detail` | `McpServerStatusDetail \| None` | `full`（默认）或 `toolsAndAuthOnly`。 |
| `thread_id` | `str \| None` | 按该 thread 的 runtime 连接状态过滤/附带。 |

`mcp_resource_read` 关键字：`connector_id`；`origin_call_id`（用发起该资源的 MCP tool call 选 app）；`thread_id`。

`McpServerStatus` 常用字段：`name`、`auth_status`、`tools`、`resources`、`resource_templates`、`runtime_status`、`server_info`、`plugin_id`。启动态枚举：`starting` / `ready` / `failed` / `cancelled`。

### 主机文件系统（绝对路径）

这些 RPC 走 **app-server 本机**，路径必须是绝对路径。和模型在 turn 里改仓库（`fileChange` item）不是同一条路。

| 方法 | 作用 | 参数 | 返回 |
| --- | --- | --- | --- |
| `fs_read_file(path)` | 读文件 | `path: str` | `FsReadFileResponse.data_base64` |
| `fs_write_file(path, data_base64)` | 写文件（覆盖） | `path`；`data_base64: str` | `FsWriteFileResponse`（空对象） |
| `fs_create_directory(path, *, recursive)` | 建目录 | `path`；`recursive: bool \| None`（默认 `true`，连父目录一起建） | `FsCreateDirectoryResponse`（空对象） |
| `fs_get_metadata(path)` | 元数据 | `path` | `is_file` / `is_directory` / `is_symlink`；`created_at_ms` / `modified_at_ms`（Unix **毫秒**，没有则为 `0`） |
| `fs_read_directory(path)` | 列直接子项 | `path` | `entries`：每项 `file_name`（只有名字）、`is_file`、`is_directory` |
| `fs_remove(path, *, force, recursive)` | 删文件或目录 | `path`；`force` 默认 `true`（缺路径不报错）；`recursive` 默认 `true` | `FsRemoveResponse`（空对象） |
| `fs_copy(source_path, destination_path, *, recursive)` | 复制 | 两个绝对路径；拷目录时必须 `recursive=True`（拷文件则忽略） | `FsCopyResponse`（空对象） |
| `fs_watch(path, *, watch_id)` | 监视路径变化 | `path`；`watch_id` 省略则 SDK 生成 UUID。**实验门**（`experimental_api`） | `FsWatchHandle`（`.watch_id`；`.response.path` 为规范化路径） |
| `fs_unwatch(watch_id)` | 取消监视 | `watch_id: str`。**实验门** | `FsUnwatchResponse`（空对象） |
| `fuzzy_file_search(query, roots, *, cancellation_token)` | 在若干根下模糊搜文件 | `query: str`；`roots: list[str]`；`cancellation_token` 可选 | `FuzzyFileSearchResponse.files`：`path`、`file_name`、`root`、`score`、`match_type`、`indices` |

`FsWatchHandle`：迭代 `FsChangedNotification`（`watch_id`、`changed_paths`）；`close()` 会调 `fs/unwatch`；可用 `with`。`AsyncCodex` 对应 `AsyncFsWatchHandle`。

---

## 14. `codex.experimental`

需要 `experimental_api=True`（当前默认已是 True）。

| 方法                                                                                             | RPC                             |
| ------------------------------------------------------------------------------------------------ | ------------------------------- |
| `thread_search(search_term, *, archived, cursor, limit, sort_direction, sort_key, source_kinds)` | `thread/search`                 |
| `thread_search_occurrences(thread_id, search_term, *, cursor, limit)`                            | `thread/searchOccurrences`      |
| `collaboration_mode_list()`                                                                      | `collaborationMode/list`        |
| `fuzzy_file_search_session_start(roots, *, session_id)`                                          | `fuzzyFileSearch/sessionStart`  |
| `fuzzy_file_search_session_update(session_id, query)`                                            | `fuzzyFileSearch/sessionUpdate` |
| `fuzzy_file_search_session_stop(session_id)`                                                     | `fuzzyFileSearch/sessionStop`   |
| `memory_reset()`                                                                                 | `memory/reset`                  |
| `project_list` / `read` / `create` / `import` / `update` / `move` / `delete`                     | `project/*`                     |

`project_create` / `project_import` 需要 `idempotency_key`。`project_delete` 只取消分配，不删 rollout。

---

## 15. 通知

公开消费口是 **`TurnHandle.stream()`**（以及 `run()`）。payload 类型在 `openai_codex.types`。常见顺序：

`turn/started` → `item/started` → `item/*/delta` → `item/completed` → `turn/completed`

同流还可能有 `thread/tokenUsage/updated`（汇总进 `TurnResult.usage`）。

**没有**公开订阅：`thread/started`、`account/updated`、`skills/changed`、MCP OAuth 等。

`Notification`：`method` + `payload`（未注册则为 `UnknownNotification`）。

---

## 16. 错误与重试

```python
CodexError
  ExperimentalApiDisabledError
  TransportClosedError
  JsonRpcError          # .code, .message, .data
    CodexRpcError
      ParseError
      InvalidRequestError
      MethodNotFoundError
      InvalidParamsError
      InternalRpcError
      ServerBusyError
        RetryLimitExceededError
```

`retry_on_overload(op, *, max_attempts=3, initial_delay_s=0.25, max_delay_s=2.0, jitter_ratio=0.2)` 在 `is_retryable_error(exc)` 为真时重试。不要重试 `InvalidParamsError` / `MethodNotFoundError`。

---

## 17. 公开 SDK 没有、app-server 仍有的

例如：plugin/marketplace 安装、apps 目录、`command/exec`、`process/*`、realtime、review、remote control、`environment/*`、`feedback/upload`、`hooks/list`、`thread/shellCommand`、已弃用的 `thread/rollback`、Windows 沙箱安装、Bedrock 账户 RPC。

它们仍可能在 **turn 内部**跑（工具、沙箱命令），只是没有对应 Python 方法。

父级拥有的 Multi-Agent V2 子 agent 会拒绝大部分直接 `turn/start` / compact / MCP tool call（`-32600`）。

---

## 18. 最小示例

```python
from openai_codex import Codex, Sandbox

with Codex() as codex:
    thread = codex.thread_start(model="gpt-5.4", sandbox=Sandbox.workspace_write)
    result = thread.run("用一句话说你好。")
    print(result.final_response)
```

```python
handle = thread.turn("重构这个模块。")
for event in handle.stream():
    print(event.method)
# 或 handle.steer("再加测试。"); handle.interrupt()
```

```python
import asyncio
from openai_codex import AsyncCodex

async def main():
    async with AsyncCodex() as codex:
        thread = await codex.thread_start()
        result = await thread.run("Summarize README.md")
        print(result.final_response)

asyncio.run(main())
```

---

## 19. 返回类型

RPC 返回值是 generated Pydantic 模型（`GetAccountResponse`、`ThreadListResponse`、`FsReadFileResponse` 等），从 `openai_codex.types` 导入。Python 字段为 **snake_case**；线上 JSON-RPC 为 camelCase。
