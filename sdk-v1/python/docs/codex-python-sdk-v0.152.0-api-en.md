# Codex Python SDK v0.152.0 API (English)

Package: `openai-codex` **0.152.0**  
Runtime pin: `openai-codex-cli-bin==0.152.0` (bundled `codex app-server`)  
Python: `>=3.10`  
Wire protocol: JSON-RPC v2 over stdio (`codex app-server --listen stdio://`)

This document is the **public** Python API as implemented in `sdk-v1/python` at this version. It is not the full app-server RPC catalog. Unwrapped RPCs still exist in `openai_codex.generated.v2_all` and can be called only via the unexported `CodexClient.request` (not part of `__all__`).

Chinese twin: [codex-python-sdk-v0.152.0-api-zh.md](codex-python-sdk-v0.152.0-api-zh.md)  
Docs hub (section index + related docs): [`../../../README.md`](../../../README.md)  
App-server coverage matrix: [`../../app-server-api.zh.md`](../../app-server-api.zh.md)  
Local disk layout: [codex-home.md](codex-home.md)  
Getting started / FAQ: [getting-started.md](getting-started.md) · [faq.md](faq.md)

---

## 1. Thread vs turn

These two words are the whole conversation model. They are **not** interchangeable, and **thread is not an OS thread**.

| Aspect | **Thread** | **Turn** |
| --- | --- | --- |
| What it is | One persisted conversation (a chat / session). | One model run **inside** that conversation. |
| Lifetime | Created once; reused for every later user message. Survives process exit. | Starts when you send input; ends at `turn/completed` (or interrupt / error). |
| Identity | `Thread.id` — server thread id. | `TurnHandle.id` / `TurnResult.id` — one turn on that thread. |
| On disk | `~/.codex/sessions/.../rollout-<…>-<thread-id>.jsonl` plus SQLite indexes. | Appended into that same rollout as `turn_context` / items. Not a separate file. |
| Python type | `Thread` / `AsyncThread` | There is no `Turn` class. You get `TurnHandle` (in flight) then `TurnResult` (done). |
| Typical API | `codex.thread_start()` / `thread_resume(id)` / `thread_fork(id)` | `thread.run(...)` or `thread.turn(...)` |

A **turn is not “one chat message.”** One turn is one harness execution: your input, then as many model steps, tool calls, file edits, and shell commands as the agent needs, until it finishes that run. The transcript of a thread is a **sequence of turns**.

Follow-up chat = **same `Thread`**, new turn. A new `thread_start()` is a **new conversation** with empty history.

Do not confuse the method name `Thread.turn(...)` with the concept. That method only **starts** a turn and returns a handle. `Thread.run(...)` is the blocking form of the same RPC (`turn/start`): start a turn and wait until it completes.

```
Codex()  →  initialize + initialized
   │
   ├─ login_* / account / logout
   ├─ config / skills / mcp / fs  (engine surface)
   └─ thread_start | resume | fork     ← conversation (Thread)
          └─ Thread.run / Thread.turn  ← start one Turn on that Thread
                └─ TurnHandle.stream | run | steer | interrupt
```

The SDK does **not** assemble chat messages. Context, compaction, tools, and sandbox live in the harness.

`AsyncCodex` / `AsyncThread` / `AsyncTurnHandle` mirror the sync API; every mutating method is `async`. Prefer `async with AsyncCodex()`.

---

## 2. Install and import

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

Version: `openai_codex.__version__` → `"0.152.0"`.

Protocol Pydantic models for annotations: `openai_codex.types` (re-exports generated v2 types).

---

## 3. `CodexConfig`

```python
@dataclass
class CodexConfig:
    codex_bin: str | None = None          # override bundled CLI
    launch_args_override: tuple[str, ...] | None = None  # replace entire argv
    config_overrides: tuple[str, ...] = ()  # passed as repeated --config KEY=VALUE
    cwd: str | None = None                # process cwd for app-server
    env: dict[str, str] | None = None     # merged into os.environ
    client_name: str = "codex_python_sdk"
    client_title: str = "Codex Python SDK"
    client_version: str = SDK_VERSION
    experimental_api: bool = True         # opt-out: set False to gate experimental RPCs
```

Default launch: bundled `codex` + `--config` overrides + `app-server --listen stdio://`.

`experimental_api=True` is the **default** in 0.152.0. Methods annotated **exp** below raise `ExperimentalApiDisabledError` only if you set `experimental_api=False`.

`CodexClient` (internal) accepts `approval_handler`; public `Codex` does not. Default handler auto-`accept`s command/file approvals.

---

## 4. Lifecycle

```python
with Codex() as codex:
    print(codex.metadata)  # InitializeResponse: userAgent, codexHome, platform*
    # ...
# close() on exit
```

| Method | RPC | Notes |
| --- | --- | --- |
| `Codex(config=None)` | `initialize`, `initialized` | Sync: starts process in `__init__`. |
| `close()` | process shutdown | Always pair with construction. |
| `metadata` | initialize result | Property. |

`AsyncCodex` initializes lazily on `async with` or first awaited call.

---

## 5. Account / login

| Method | RPC | Returns |
| --- | --- | --- |
| `login_api_key(api_key)` | `account/login/start` (`apiKey`) | `None` (sync complete) |
| `login_chatgpt()` | `account/login/start` (`chatgpt`) | `ChatgptLoginHandle` |
| `login_chatgpt_device_code()` | `account/login/start` (`chatgptDeviceCode`) | `DeviceCodeLoginHandle` |
| `account(*, refresh_token=False)` | `account/read` | `GetAccountResponse` |
| `logout()` | `account/logout` | `None` |

**Not wrapped:** Bedrock login, rate limits, usage, workspace emails.

### Login handles

`ChatgptLoginHandle`: `login_id`, `auth_url`, `wait()` → `AccountLoginCompletedNotification`, `cancel()` → `CancelLoginAccountResponse`.

`DeviceCodeLoginHandle`: `login_id`, `verification_url`, `user_code`, same `wait` / `cancel`.

`wait()` consumes **only** the completion notification for that `login_id`.

---

## 6. `Codex` — threads

These methods create, list, resume, or fork a **conversation**. They do not run the model. Running the model is a **turn** on the returned SDK `Thread` (section 7).

Two different `Thread` types:

| Name | What it is | How you get it |
| --- | --- | --- |
| SDK `openai_codex.Thread` | Conversation handle: `.id` plus `run` / `turn` / `read` | `thread_start` / `thread_resume` / `thread_fork` / `thread_unarchive` |
| Protocol `types.Thread` | Metadata snapshot: `id`, `cwd`, `name`, `preview`, `status`, `created_at`, … | `thread_list().data`, `thread.read().thread`, etc. |

Omitted keyword args are `None` = leave it to the server / existing thread settings. `thread_start` defaults `approval_mode=ApprovalMode.auto_review`.

**Not public on `thread_start`:** `permissions`, `dynamicTools`.

### 6.1 Method index

| Method | What it does | Parameters | Returns |
| --- | --- | --- | --- |
| `thread_start(**kwargs)` | Create an empty conversation | Keywords only; see [6.2](#62-shared-start--resume--fork-parameters) | SDK `Thread` (`.id` = new thread id) |
| `thread_list(**kwargs)` | List stored conversations | See [6.3](#63-thread_list) | `ThreadListResponse`: `data: list[types.Thread]`, `next_cursor`, `backwards_cursor` |
| `thread_resume(thread_id, **kwargs)` | Load an existing conversation into this app-server so you can run turns | Positional `thread_id: str`; keywords in 6.2 plus `exclude_turns` | SDK `Thread` |
| `thread_fork(thread_id, **kwargs)` | Copy into a **new** thread (new id) | Positional `thread_id`; keywords in 6.2 plus `before_turn_id` **exp**, `last_turn_id`, `exclude_turns`, `ephemeral`, `thread_source` | SDK `Thread` (new id) |
| `thread_archive(thread_id)` | Archive (hidden from the default list) | `thread_id: str` | `ThreadArchiveResponse` (empty object) |
| `thread_unarchive(thread_id)` | Unarchive | `thread_id: str` | SDK `Thread` |
| `thread_delete(thread_id)` | Delete stored conversation | `thread_id: str` | `ThreadDeleteResponse` (empty object) |
| `thread_loaded_list(*, cursor, limit)` | Thread ids currently loaded in this process | `cursor: str \| None`, `limit: int \| None` | `ThreadLoadedListResponse`: `data: list[str]`, `next_cursor` |
| `thread_section_list(*, cursor, limit)` | List UI sections | same | `ThreadSectionListResponse`: `data: list[ThreadSection]`, `next_cursor` |
| `thread_section_create(name, *, appearance)` | Create a section | `name: str`; `appearance: ThreadSectionAppearance \| None` (`color` / `icon`) | `ThreadSectionCreateResponse.section` |
| `thread_section_update(section_id, name, *, appearance)` | Rename / restyle | `section_id: str`, `name: str`, optional `appearance` | `ThreadSectionUpdateResponse.section` |
| `thread_section_delete(section_id)` | Delete a section | `section_id: str` | `ThreadSectionDeleteResponse` (empty object) |

### 6.2 Shared start / resume / fork parameters

Unless noted, `None` means do not override.

| Parameter | Type | Meaning |
| --- | --- | --- |
| `approval_mode` | `ApprovalMode` | Command/patch approvals. `auto_review` (default on `start`) or `deny_all`. Maps to wire `approvalPolicy` / `approvalsReviewer`. |
| `sandbox` | `Sandbox \| None` | Filesystem: `read_only` / `workspace_write` / `full_access`. Omit for configured default. |
| `cwd` | `str \| None` | Working directory (absolute). |
| `model` | `str \| None` | Model slug (e.g. `gpt-5.4`), not a local Ollama tag list. |
| `model_provider` | `str \| None` | Name of `[model_providers.*]` in `config.toml`. |
| `personality` | `Personality \| None` | `none` / `friendly` / `pragmatic`. |
| `base_instructions` | `str \| None` | Override the built-in base. Usually skip; see [section 11](#11-custom-system--developer-instructions). |
| `developer_instructions` | `str \| None` | Extra developer-role message. Prefer this for a custom “system prompt”. |
| `config` | `dict \| None` | Per-thread config overlay (JSON object). |
| `service_tier` | `str \| None` | Service-tier override. |
| `environments` | `list[TurnEnvironmentParams] \| None` | **exp** (`start` only). Sticky environments; empty list disables. |

`thread_start` only:

| Parameter | Type | Meaning |
| --- | --- | --- |
| `ephemeral` | `bool \| None` | `True` avoids persisting to disk when possible. |
| `service_name` | `str \| None` | Service name (analytics / billing). |
| `session_start_source` | `ThreadStartSource \| None` | `startup` / `clear`. |
| `thread_source` | `ThreadSource \| None` | Analytics: `user` / `subagent` / `memory_consolidation`. |

`thread_resume` / `thread_fork` only:

| Parameter | Type | Meaning |
| --- | --- | --- |
| `exclude_turns` | `bool \| None` | `True` skips hydrating history; follow with `turns_list` / `items_list`. |
| `before_turn_id` | `str \| None` | **exp, fork only.** Cut **before** this turn (excludes it and later). Cannot combine with `last_turn_id`. |
| `last_turn_id` | `str \| None` | **fork only.** Include this turn; drop later ones. That turn must not be in progress. |

### 6.3 `thread_list`

All keywords optional.

| Parameter | Type | Meaning |
| --- | --- | --- |
| `archived` | `bool \| None` | `True` = archived only; `False`/`None` = non-archived only. |
| `cursor` | `str \| None` | Previous page’s `next_cursor`. |
| `cwd` | `str \| list[str] \| None` | Exact session cwd match. |
| `limit` | `int \| None` | Page size. |
| `model_providers` | `list[str] \| None` | Filter by recorded provider; empty list = no filter. |
| `search_term` | `str \| None` | Title substring. |
| `section_id` | `str \| None` | Only that section. |
| `sort_direction` | `SortDirection \| None` | `asc` / `desc` (default newest first). |
| `sort_key` | `ThreadSortKey \| None` | `created_at` / `updated_at` / `recency_at` / `section_position`. |
| `source_kinds` | `list[ThreadSourceKind] \| None` | Origin: `cli` / `vscode` / `appServer`, … |
| `use_state_db_only` | `bool \| None` | SQLite index only; do not scan rollouts. |

Useful `types.Thread` fields: `id` (UUIDv7), `cwd`, `name`, `preview`, `created_at` / `updated_at` (Unix seconds), `ephemeral`, `model_provider`, `cli_version`, `status`, `forked_from_id`, `parent_thread_id`, `project_id`, `section`. `turns` is usually empty on list results.

---

## 7. `Thread`

SDK `Thread`: `id` is the server thread id. `run` / `turn` **start a new turn**. Other methods mutate this conversation; they are not a model run.

### 7.1 Method index

| Method | What it does | Parameters | Returns |
| --- | --- | --- | --- |
| `run(input, **turn_kwargs)` | Start a turn and wait until it finishes | See [7.2](#72-run--turn-parameters) | `TurnResult`; failure raises `RuntimeError` |
| `turn(input, **turn_kwargs)` | Start a turn and return control immediately | Same as `run` | `TurnHandle` (`.id` = turn id, `.thread_id`) |
| `read(*, include_turns=False)` | Read metadata; does not take a resume writer lock by itself | `include_turns: bool` — populate `thread.turns` | `ThreadReadResponse.thread` (protocol `Thread`) |
| `set_name(name)` | Set title; also appends `session_index.jsonl` | `name: str` | `ThreadSetNameResponse` (empty object) |
| `compact()` | Request context compaction | none | `ThreadCompactStartResponse` (empty, immediate); progress via turn/item notifications. Parent-owned Multi-Agent V2 children reject |
| `unsubscribe()` | Drop this connection’s subscription | none | `ThreadUnsubscribeResponse.status`: `unsubscribed` / `notLoaded` / `notSubscribed` |
| `turns_list(...)` | Paginate stored turns | `cursor`, `limit`, `sort_direction`, `items_view` (`notLoaded` / `summary` / `full`, default summary) | `ThreadTurnsListResponse`: `data: list[Turn]`, `next_cursor`, `backwards_cursor` |
| `items_list(...)` | Paginate items | `cursor`, `limit`, `sort_direction`, `turn_id` (restrict to one turn) | `ThreadItemsListResponse`: `data: list[ThreadItemEntry]` (`item` + `turn_id`), same cursors |
| `revert(before_turn_id)` | Drop that turn and everything after | `before_turn_id: str` | `ThreadRevertResponse`: `thread` (`turns` empty) plus item/turn backwards cursors |
| `inject_items(items)` | Write raw Responses items; **no** new turn | `items: list[dict]` | `ThreadInjectItemsResponse` |
| `metadata_update(...)` | SQLite metadata | `git_info: ThreadMetadataGitInfoUpdateParams \| None` (`branch` / `origin_url` / `sha`), `project_id: str \| None` | `ThreadMetadataUpdateResponse.thread` |
| `section_move(...)` | Move this thread into a section / before another thread | `section_id`, `before_thread_id` (both optional) | `ThreadSectionMoveResponse` |
| `mcp_tool_call(server, tool, ...)` | Call an MCP tool on a loaded thread | `server: str`, `tool: str`; optional `arguments`, `field_meta`. Subagents reject | `McpServerToolCallResponse`: `content`, `is_error`, `structured_content` |
| `goal_get()` | Read this thread’s goal | none | `ThreadGoalGetResponse.goal` (may be `None`) |
| `goal_set(*, objective, status)` | Set objective / status | `objective: str \| None`, `status: ThreadGoalStatus \| None` (`active` / `paused` / `blocked` / `usageLimited` / `budgetLimited` / `complete`) | `ThreadGoalSetResponse.goal` |
| `goal_clear()` | Clear goal | none | `ThreadGoalClearResponse.cleared: bool` |
| `queue_add(input, *, client_user_message_id)` | **exp** Queue user input while a turn is running | same `input` as a turn; required `client_user_message_id: str` | `ThreadQueueAddResponse.queued_submission` |
| `queue_list(*, cursor, limit)` | **exp** List the queue | pagination | `ThreadQueueListResponse`: `data`, `next_cursor` |
| `queue_update(queued_submission_id, input)` | **exp** Edit a queued item | id + new `input` | `ThreadQueueUpdateResponse` |
| `queue_delete(queued_submission_id)` | **exp** Remove a queued item | id | `ThreadQueueDeleteResponse` |
| `queue_reorder(queued_submission_ids)` | **exp** Reorder | `list[str]` new order | `ThreadQueueReorderResponse` |
| `queue_start(*, queued_submission_id)` | **exp** Start a queued item now | omit = head of queue | `ThreadQueueStartResponse.turn` (protocol `Turn`) |
| `memory_mode_set(mode)` | **exp** Thread memory on/off | `mode: ThreadMemoryMode` (`enabled` / `disabled`) | `ThreadMemoryModeSetResponse` (empty object) |
| `settings_update(**kwargs)` | **exp** Change settings for the **next** turn; does not start a turn | see below | `ThreadSettingsUpdateResponse` (empty object) |

`settings_update` keywords (all optional): `approval_mode`, `collaboration_mode`, `cwd`, `effort`, `model`, `personality`, `sandbox`, `service_tier`, `summary`.

Protocol `Turn` (`turns_list` / some notifications): `id`, `status` (`completed` / `interrupted` / `failed` / `inProgress`), `started_at` / `completed_at` (Unix seconds), `duration_ms`, `error`, `items`, `items_view`.

### 7.2 `run` / `turn` parameters

Positional `input: str | Input` (`str` ≡ `TextInput`; a list is one `turn/start` with several items — section 9). Remaining args are keywords. `sandbox` / `approval_mode` passed here stick to **later turns**.

| Parameter | Type | Meaning |
| --- | --- | --- |
| `approval_mode` | `ApprovalMode \| None` | Override approvals for this turn and later. |
| `sandbox` | `Sandbox \| None` | Override sandbox for this turn and later. |
| `cwd` | `str \| None` | Override working directory. |
| `model` | `str \| None` | Override model. |
| `effort` | `ReasoningEffort \| None` | `none` / `minimal` / `low` / `medium` / `high` / `xhigh` / `max` / `ultra`. |
| `summary` | `ReasoningSummary \| None` | Reasoning summary: `auto` / `concise` / `detailed` / `"none"`. |
| `personality` | `Personality \| None` | Override personality. |
| `service_tier` | `str \| None` | Override service tier. |
| `output_schema` | `dict \| None` | JSON Schema for this turn’s final assistant message. |
| `environments` | `list[TurnEnvironmentParams] \| None` | **exp**. Omit = thread sticky envs; `[]` disables this turn. |
| `tool_output` | `TurnToolOutput \| None` | Feed output into an in-flight tool call: `name`, `namespace`, `output`. |

---

## 8. `TurnHandle`

One **in-flight turn**: attributes `thread_id`, `id` (turn id). Not a conversation. After completion keep `TurnResult`; the handle is spent. One `Codex` can stream several turns; routing is by turn id.

| Method | What it does | Parameters | Returns |
| --- | --- | --- | --- |
| `stream()` | Yield notifications for **this** `turn.id` until `turn/completed` | none | `Iterator[Notification]` (`method` + `payload`) |
| `run()` | Consume `stream()` and collect | none | `TurnResult` (same as `Thread.run`); failure raises `RuntimeError` |
| `steer(input)` | Extra input on an **in-flight** regular turn | `input: str \| Input`. Review/compact turns reject | `TurnSteerResponse.turn_id` |
| `interrupt()` | Request interrupt | none | `TurnInterruptResponse` (empty object) |
| `settings_update(...)` | **exp** Hot-patch the live task | keywords: `effort`, `model`, `service_tier`, `summary` (all optional) | `TurnSettingsUpdateResponse.status`: `applied` / `targetUnavailable` |

### `TurnResult`

Built by `Thread.run()` / `TurnHandle.run()` from this turn’s `item/completed` and `turn/completed`. It is **not** a copy of the protocol `Turn` object.

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | `str` | Turn id (UUIDv7) |
| `status` | `TurnStatus` | `completed` / `interrupted` / `failed` / `inProgress` |
| `error` | `TurnError \| None` | Only when `failed` |
| `started_at` / `completed_at` | `int \| None` | Unix **seconds** |
| `duration_ms` | `int \| None` | Elapsed milliseconds |
| `final_response` | `str \| None` | Prefer `phase=final_answer` agent text; else last phaseless assistant message |
| `items` | `list[ThreadItem]` | Completed items for this turn |
| `usage` | `ThreadTokenUsage \| None` | From `thread/tokenUsage/updated`: `last` / `total` (`TokenUsageBreakdown`), `model_context_window` |

When `status=failed`, `run()` **raises** `RuntimeError` (prefers `TurnError.message`) instead of returning a failed `TurnResult`.

---

## 9. Inputs

```python
TextInput(text)
ImageInput(url)          # data:image/... URL; HTTP(S) URLs are deprecated
LocalImageInput(path)
AudioInput(url)
LocalAudioInput(path)
SkillInput(name, path)
MentionInput(name, path)  # app://... or plugin://...
```

`str` anywhere a turn accepts input ≡ `TextInput`. Lists of items are sent as one `turn/start` `input` array.

---

## 10. `ApprovalMode` and `Sandbox`

| Enum | Wire |
| --- | --- |
| `ApprovalMode.auto_review` | `approvalPolicy=onRequest`, `approvalsReviewer=autoReview` |
| `ApprovalMode.deny_all` | `approvalPolicy=never` |
| `Sandbox.read_only` | thread: `read-only`; turn: `{type: readOnly}` |
| `Sandbox.workspace_write` | `workspace-write` / `{type: workspaceWrite}` |
| `Sandbox.full_access` | `danger-full-access` / `{type: dangerFullAccess}` |

Omitted sandbox → server default (trusted workspaces often `workspace_write`).

Public SDK has **no** custom approval UI. Command/file approvals are auto-accepted. Granular `item/permissions/requestApproval`, elicitation, and `item/tool/call` are not exposed.

---

## 11. Custom system / developer instructions

There is **no** `system_prompt=` argument. What the model sees on the “system side” is several stacked layers. The SDK can change only some of them; tool specs, sandbox/environment blocks, and skill text still come from the harness.

| Layer | Role | How you change it | When to use |
| --- | --- | --- | --- |
| **base instructions** | Built-in model playbook (varies with `personality`) | `thread_start(base_instructions=...)`, or config keys `instructions` / `model_instructions_file` | Usually **do not** replace wholesale; leaving the official template hurts quality |
| **developer instructions** | Extra `developer`-role message | `thread_start(developer_instructions=...)`, or config key `developer_instructions` | Main SDK knob for a custom “system prompt” |
| **AGENTS.md** | User/project notes, injected as `<user_instructions>` | Markdown files, not an RPC | Repo conventions; shared with CLI / IDE |
| **This turn’s input** | Normal user message | `thread.run(...)` | One-shot task, not a system prompt |

`Thread.run` / `turn` have **no** `base_instructions` / `developer_instructions`. Set those on **start / resume / fork**, or change config and **start a new** thread (an already-loaded thread does not pick up toml edits for these fields).

`thread_start(cwd=...)` controls which tree is searched for project `AGENTS.md`. `personality` only selects the default base template; it is not free text.

### Python SDK

Per-thread only (does not write disk config):

```python
from openai_codex import Codex, Sandbox

SYSTEM = "You are a backend reviewer. Reply in Chinese. Do not edit code without evidence."

with Codex() as codex:
    thread = codex.thread_start(
        sandbox=Sandbox.workspace_write,
        developer_instructions=SYSTEM,
        # optional: replace built-in base. Not recommended.
        # base_instructions="...",
        cwd="/path/to/repo",
    )
    result = thread.run("Review the auth module.")
```

`thread_resume` / `thread_fork` take the same keywords.

Process-wide at launch (every new thread; same as CLI `--config`):

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

Persist into `~/.codex/config.toml` (CLI sees it too):

```python
from openai_codex import Codex
from openai_codex.types import MergeStrategy

with Codex() as codex:
    codex.config_value_write(
        "developer_instructions",
        "Always answer in Chinese. Prefer small diffs.",
        MergeStrategy.replace,
    )
    # only threads started after this write pick it up
    thread = codex.thread_start()
```

To override built-in **base** (not recommended), the config key is **`instructions`**, not `base_instructions`:

```python
codex.config_value_write("instructions", "...", MergeStrategy.replace)
# or CodexConfig(config_overrides=("instructions=...",))
# or thread_start(base_instructions="...")
```

File-backed model instructions: `model_instructions_file = "/abs/path.txt"` in `config.toml` (relative paths resolve against effective cwd). The SDK can `config_value_write("model_instructions_file", "/abs/path.txt", MergeStrategy.replace)`. Priority: `thread_start(base_instructions=)` > that file > `instructions` key > built-in model template.

### Config files

User `~/.codex/config.toml` (or project `.codex/config.toml`):

```toml
developer_instructions = """
You are a code reviewer. Use Chinese. Conclusion first, then evidence.
"""

# not recommended: replace built-in base
# instructions = "..."
# model_instructions_file = "/abs/path/to/instructions.txt"
```

Repo-scoped (merged with `cwd`; this is **not** the developer role):

- Project root: `AGENTS.md`
- Override layer: `AGENTS.override.md`
- User-global: `~/.codex/AGENTS.md` (merged with project files)

If `AGENTS.md` is missing, `project_doc_fallback_filenames` lists fallback names. Total size is capped by `project_doc_max_bytes`. See [codex-home.md](codex-home.md).

### What will not work

- Passing a system prompt to `run()`: there is no such argument.
- Editing `config.toml` and expecting an **already** started/resumed thread to change base/developer text: those are fixed at thread start.
- Clearing built-in base with `""`: omit the argument to keep the default; an explicit string is treated as a custom base.
- Experimental `collaboration_mode` with its own `developer_instructions` overrides yours.

---

## 12. Managing skills and MCP

Keep the **config plane** (discover, enable/disable, write `config.toml`) separate from the **data plane** (use them on a turn). The public SDK has **no** `plugin/install` and **no** MCP OAuth, so plugin-bundled skills/MCP cannot be installed here, and browser-login remote MCP cannot finish auth.

| Goal | Skill | MCP |
| --- | --- | --- |
| Add | Write `SKILL.md` on disk (or `skills_extra_roots_set` to an existing tree) | `config_value_write("mcp_servers.<name>", {...})`, then `mcp_reload()` |
| Remove | Delete the directory / `fs_remove`, or only disable | `config_value_write("mcp_servers.<name>", None, replace)`, then `mcp_reload()` |
| Enable/disable | `skills_config_write(enabled, name=…)` | `config_value_write("mcp_servers.<name>.enabled", True/False)`, then `mcp_reload()` |
| List | `skills_list` | `mcp_status_list` |
| Use on this turn | `SkillInput` plus `$name` in text | The model calls tools during the turn; or `thread.mcp_tool_call` |

RPC field lists: [section 13](#13-models-config-skills-mcp-fs).

### Skills: files and toggles

A skill is **not** a JSON blob in config. It is a `SKILL.md` with front matter. Scan roots:

- User: `~/.codex/skills/<name>/SKILL.md`
- Project: `<cwd>/.codex/skills/` or `<cwd>/.agents/skills/`
- Extra roots for this process: `skills_extra_roots_set` (**not persisted**)

**Add** — there is no `skills/create` RPC:

```python
from pathlib import Path
from openai_codex import Codex

home = Path.home() / ".codex" / "skills" / "reviewer"
home.mkdir(parents=True, exist_ok=True)
(home / "SKILL.md").write_text(
    "---\nname: reviewer\ndescription: Review conventions\n---\n\nConclusion first, then evidence.\n",
    encoding="utf-8",
)

with Codex() as codex:
    listed = codex.skills_list(force_reload=True)
    skill = next(s for entry in listed.data for s in entry.skills if s.name == "reviewer")
```

`codex.fs_write_file(path, data_base64)` can write the same path. Temporary trees: `codex.skills_extra_roots_set(["/abs/extra/skills"])` then `skills_list(force_reload=True)`.

**Toggle** (persists as `[[skills.config]]` in user config):

```python
codex.skills_config_write(False, name="reviewer")           # off
codex.skills_config_write(True, name="reviewer")            # on
codex.skills_config_write(False, path=str(skill.path))      # select by absolute path
```

**Delete**: `fs_remove` the skill directory (`recursive=True`), or only `skills_config_write(False, …)` and leave the files. There is no `skills/delete` RPC.

**Inject this turn** (loads the body; more reliable than `$name` alone):

```python
from openai_codex import SkillInput, TextInput

thread = codex.thread_start(cwd="/path/to/repo")
result = thread.run(
    [
        TextInput("Review auth using $reviewer."),
        SkillInput("reviewer", str(skill.path)),
    ]
)
```

Text-only `$reviewer` makes the model search the catalog itself (slower, flakier). `skills/list` does **not** inject a skill into a turn.

Equivalent toml:

```toml
[[skills.config]]
name = "reviewer"
enabled = false
```

### MCP: config, reload, toggles

There is no `mcp/add` RPC. Register `[mcp_servers.<name>]` in `config.toml`, then **`mcp_reload()`**. Loaded threads pick up new processes on the **next turn**. `mcp_status_list` without `thread_id` can show config immediately, but `runtime_status` is `None`.

**Add a stdio server**:

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

HTTP / Streamable HTTP uses `url` (optional `bearer_token_env_var`, `http_headers`). Do not set both `command` and `url`. Common fields: `args`, `env`, `cwd`, `enabled`, `enabled_tools` / `disabled_tools`, `startup_timeout_sec`, `required`.

Launch-time only (not written to disk):

```python
from openai_codex import CodexConfig

cfg = CodexConfig(
    config_overrides=(
        "mcp_servers.docs.command=npx",
        'mcp_servers.docs.args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]',
    ),
)
```

Hand-edited toml still needs `mcp_reload()`:

```toml
[mcp_servers.docs]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
enabled = true
```

**Disable / delete**:

```python
codex.config_value_write("mcp_servers.docs.enabled", False, MergeStrategy.replace)
codex.mcp_reload()  # disabled; entry remains

codex.config_value_write("mcp_servers.docs", None, MergeStrategy.replace)
codex.mcp_reload()  # drop that server from toml
```

**Use**: after it is configured, the model calls MCP tools inside `thread.run(...)`. Direct client call:

```python
thread = codex.thread_start()
out = thread.mcp_tool_call("docs", "list_directory", arguments={"path": "/tmp"})
```

Remote MCP that needs OAuth: the SDK has **no** `mcpServer/oauth/login`. Log in via CLI/IDE first, or use stdio / HTTP with an env token.

---

## 13. Models, config, skills, MCP, FS

### Models

| Method | RPC |
| --- | --- |
| `models(*, include_hidden=False)` | `model/list` — catalog slugs, **not** local Ollama tags |
| `model_provider_capabilities()` | `modelProvider/capabilities/read` |

Local vLLM / Ollama: `[model_providers.*]` in `config.toml` + `model=` / `model_provider=` on thread/turn.

### Config

These RPCs edit `~/.codex/config.toml` (and project layers). They are **not** `CodexConfig.config_overrides` (that is CLI `--config` at launch).

| Method | What it does | Parameters | Returns |
| --- | --- | --- | --- |
| `config_read(*, cwd, include_layers)` | Read effective config | `cwd: str \| None` — resolve project layers from that directory; `include_layers: bool \| None` — include layer breakdown | `ConfigReadResponse`: `config` (merged `Config`), `origins` (which layer owns each key), `layers` (when `include_layers`) |
| `config_value_write(key_path, value, merge_strategy, *, expected_version, file_path)` | Write one key | see table below | `ConfigWriteResponse`: `file_path`, `version`, `status` (`ok` / `okOverridden`), `overridden_metadata` |
| `config_batch_write(edits, *, expected_version, file_path, reload_user_config)` | Write several keys | see table below | same `ConfigWriteResponse` |
| `config_requirements_read()` | Read MDM / `requirements.toml` constraints | none | `ConfigRequirementsReadResponse.requirements` (`None` if unset) |
| `experimental_feature_list(*, cursor, limit, thread_id)` | List experiment flags | `cursor` / `limit` pagination; `thread_id` — compute enablement from that loaded thread’s cwd | `ExperimentalFeatureListResponse`: `data: list[ExperimentalFeature]`, `next_cursor` |
| `experimental_feature_enablement_set(enablement)` | Set experiment flags | `enablement: dict[str, bool]` (keys = feature `name`) | `ExperimentalFeatureEnablementSetResponse.enablement` (entries actually written) |
| `external_agent_config_detect(...)` | Detect config that can be imported from another agent | see below | `ExternalAgentConfigDetectResponse`: `items`, `connectors` |
| `external_agent_config_import(migration_items, ...)` | Run the import | positional `migration_items: list[ExternalAgentConfigMigrationItem]`; keywords `migration_source` / `provider_id` / `source` | `ExternalAgentConfigImportResponse.import_id` (progress via notifications) |
| `external_agent_config_import_read_histories()` | Read import history | none | `ExternalAgentConfigImportHistoriesReadResponse`: `data`, `connectors` |

`config_value_write` / `config_batch_write`:

| Parameter | Type | Meaning |
| --- | --- | --- |
| `key_path` | `str` | Dotted key (`value_write` only). |
| `value` | any JSON | Value to write (`value_write` only). |
| `merge_strategy` | `MergeStrategy` | `replace` whole node; `upsert` merge. |
| `edits` | `list[ConfigEdit]` | Batch only: each has `key_path` + `value` + `merge_strategy`. |
| `expected_version` | `str \| None` | Optimistic lock; mismatch fails. |
| `file_path` | `str \| None` | Target toml; omit = user `config.toml`. |
| `reload_user_config` | `bool \| None` | Batch only. `True` hot-reloads into loaded threads. Session-static model / effort / personality defaults are not reloaded. |

Useful `ExperimentalFeature` fields: `name`, `enabled`, `default_enabled`, `stage` (`beta` / `underDevelopment` / `stable` / `deprecated` / `removed`), optional `display_name` / `description` / `announcement`.

`external_agent_config_detect` keywords (all optional): `cwds` (repo dirs), `include_home`, `max_session_age_days`, `max_sessions`, `migration_source`, `source`. `ExternalAgentConfigMigrationItem`: `item_type` (`AGENTS_MD` / `CONFIG` / `SKILLS` / `PLUGINS` / `MCP_SERVER_CONFIG` / …), `description`, `cwd` (empty = home-scoped), `details`.

### Skills

A skill is an on-disk `SKILL.md` capability pack. Listing/toggling uses the RPCs below; add/remove/inject: [section 12](#12-managing-skills-and-mcp). **To use a skill in a turn:** put `$name` in the text **and** pass `SkillInput(name, path)`.

| Method | What it does | Parameters | Returns |
| --- | --- | --- | --- |
| `skills_list(*, cwds, force_reload)` | Scan visible skills | `cwds: list[str] \| None` — empty = current session cwd; `force_reload: bool \| None` — `True` bypasses cache | `SkillsListResponse.data`: each entry has `cwd`, `skills`, `errors` |
| `skills_extra_roots_set(extra_roots)` | Extra scan roots for this process | `extra_roots: list[str]` (absolute). **Not persisted**; gone when the process exits | `SkillsExtraRootsSetResponse` (empty object) |
| `skills_config_write(enabled, *, name, path)` | Persist enable/disable for one skill | `enabled: bool`; select with `name` and/or `path` (absolute); at least one | `SkillsConfigWriteResponse.effective_enabled` |
| `plugin_skill_read(remote_marketplace_name, remote_plugin_id, skill_name)` | Read a skill body from a remote plugin | three required `str`s | `PluginSkillReadResponse.contents` (may be `None`) |

Useful `SkillMetadata` fields: `name`, `path`, `enabled`, `description`, `short_description`, `scope` (`user` / `repo` / `system` / `admin`), `plugin_id`, `interface`, `dependencies`.

### MCP

MCP servers live under `[mcp_servers]` in `config.toml`. Add/remove/toggle/reload: [section 12](#12-managing-skills-and-mcp). Model-initiated MCP **does** run inside turns. The methods below are the SDK’s direct manage/read surface. **Not wrapped:** MCP OAuth, MCP event streams.

| Method | What it does | Parameters | Returns |
| --- | --- | --- | --- |
| `mcp_reload()` | Reload MCP processes from current config | none. Takes effect on the **next turn** | `McpServerRefreshResponse` (empty object) |
| `mcp_status_list(*, cursor, detail, limit, thread_id)` | List server status and tool inventory | see table below | `ListMcpServerStatusResponse`: `data: list[McpServerStatus]`, `next_cursor` |
| `mcp_resource_read(server, uri, *, connector_id, origin_call_id, thread_id)` | Read an MCP resource | positional `server`, `uri`; keywords below | `McpResourceReadResponse`: `contents`, `origin_call_id` |
| `thread.mcp_tool_call(server, tool, *, arguments, field_meta)` | Call a tool on a **loaded** thread (not model-initiated) | section 7. Subagents reject | `McpServerToolCallResponse`: `content`, `is_error`, `structured_content` |

`mcp_status_list`:

| Parameter | Type | Meaning |
| --- | --- | --- |
| `cursor` / `limit` | `str \| None` / `int \| None` | Pagination. |
| `detail` | `McpServerStatusDetail \| None` | `full` (default) or `toolsAndAuthOnly`. |
| `thread_id` | `str \| None` | Attach/filter by that thread’s runtime connection. |

`mcp_resource_read` keywords: `connector_id`; `origin_call_id` (originating MCP tool call used to pick the app); `thread_id`.

Useful `McpServerStatus` fields: `name`, `auth_status`, `tools`, `resources`, `resource_templates`, `runtime_status`, `server_info`, `plugin_id`. Startup states: `starting` / `ready` / `failed` / `cancelled`.

### Host filesystem (absolute paths)

These RPCs hit **the app-server host**. Paths must be absolute. This is not how the model edits the repo during a turn (`fileChange` items).

| Method | What it does | Parameters | Returns |
| --- | --- | --- | --- |
| `fs_read_file(path)` | Read a file | `path: str` | `FsReadFileResponse.data_base64` |
| `fs_write_file(path, data_base64)` | Write/overwrite a file | `path`; `data_base64: str` | `FsWriteFileResponse` (empty object) |
| `fs_create_directory(path, *, recursive)` | Create a directory | `path`; `recursive: bool \| None` (default `true`, also create parents) | `FsCreateDirectoryResponse` (empty object) |
| `fs_get_metadata(path)` | Metadata | `path` | `is_file` / `is_directory` / `is_symlink`; `created_at_ms` / `modified_at_ms` (Unix **milliseconds**, or `0`) |
| `fs_read_directory(path)` | List direct children | `path` | `entries`: each `file_name` (name only), `is_file`, `is_directory` |
| `fs_remove(path, *, force, recursive)` | Delete file or directory | `path`; `force` defaults `true` (ignore missing); `recursive` defaults `true` | `FsRemoveResponse` (empty object) |
| `fs_copy(source_path, destination_path, *, recursive)` | Copy | two absolute paths; directory copy requires `recursive=True` (ignored for files) | `FsCopyResponse` (empty object) |
| `fs_watch(path, *, watch_id)` | Watch for changes | `path`; omit `watch_id` and the SDK generates a UUID. **exp** SDK gate | `FsWatchHandle` (`.watch_id`; `.response.path` is canonical) |
| `fs_unwatch(watch_id)` | Stop watching | `watch_id: str`. **exp** SDK gate | `FsUnwatchResponse` (empty object) |
| `fuzzy_file_search(query, roots, *, cancellation_token)` | Fuzzy-search files under roots | `query: str`; `roots: list[str]`; optional `cancellation_token` | `FuzzyFileSearchResponse.files`: `path`, `file_name`, `root`, `score`, `match_type`, `indices` |

`FsWatchHandle`: iterate `FsChangedNotification` (`watch_id`, `changed_paths`); `close()` calls `fs/unwatch`; usable as `with`. `AsyncCodex` returns `AsyncFsWatchHandle`.

---

## 14. `codex.experimental`

Requires `experimental_api=True` (already the default).

| Method | RPC |
| --- | --- |
| `thread_search(search_term, *, archived, cursor, limit, sort_direction, sort_key, source_kinds)` | `thread/search` |
| `thread_search_occurrences(thread_id, search_term, *, cursor, limit)` | `thread/searchOccurrences` |
| `collaboration_mode_list()` | `collaborationMode/list` |
| `fuzzy_file_search_session_start(roots, *, session_id)` | `fuzzyFileSearch/sessionStart` |
| `fuzzy_file_search_session_update(session_id, query)` | `fuzzyFileSearch/sessionUpdate` |
| `fuzzy_file_search_session_stop(session_id)` | `fuzzyFileSearch/sessionStop` |
| `memory_reset()` | `memory/reset` |
| `project_list` / `project_read` / `project_create` / `project_import` / `project_update` / `project_move` / `project_delete` | `project/*` |

`project_create` / `project_import` require `idempotency_key`. `project_delete` unassigns threads; it does not delete rollouts.

---

## 15. Notifications

Public consumption is **`TurnHandle.stream()`** (and `run()`). Payloads are typed in `openai_codex.types` / `generated.v2_all`. Typical sequence:

`turn/started` → `item/started` → `item/*/delta` → `item/completed` → `turn/completed`

Also on the turn stream when emitted: `thread/tokenUsage/updated` (folded into `TurnResult.usage`).

There is **no** public subscribe API for `thread/started`, `account/updated`, `skills/changed`, MCP OAuth, etc.

`Notification`: `method` + `payload` (`UnknownNotification` if unregistered).

---

## 16. Errors and retry

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

`retry_on_overload(op, *, max_attempts=3, initial_delay_s=0.25, max_delay_s=2.0, jitter_ratio=0.2)` retries when `is_retryable_error(exc)` is true (overload / busy). Do not retry `InvalidParamsError` / `MethodNotFoundError`.

---

## 17. Not in the public SDK (still in app-server)

Examples: plugin/marketplace install, apps catalog, `command/exec`, `process/*`, realtime, review, remote control, `environment/*`, `feedback/upload`, `hooks/list`, `thread/shellCommand`, `thread/rollback` (deprecated), Windows sandbox setup, Bedrock account RPCs.

Those may still run **inside a turn** (tools, sandbox commands). The Python object model just has no method for them.

Parent-owned Multi-Agent V2 subagents reject most direct `turn/start` / compact / MCP tool calls (`-32600`).

---

## 18. Minimal examples

```python
from openai_codex import Codex, Sandbox

with Codex() as codex:
    thread = codex.thread_start(model="gpt-5.4", sandbox=Sandbox.workspace_write)
    result = thread.run("Say hello in one sentence.")
    print(result.final_response)
```

```python
handle = thread.turn("Refactor the module.")
for event in handle.stream():
    print(event.method)
# or handle.steer("Also add tests."); handle.interrupt()
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

## 19. Return types

RPC responses are generated Pydantic models (`GetAccountResponse`, `ThreadListResponse`, `FsReadFileResponse`, …). Import from `openai_codex.types`. Field names in Python are **snake_case**; JSON-RPC on the wire is camelCase.
