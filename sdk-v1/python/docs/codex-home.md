# `~/.codex` (CODEX_HOME)

Codex CLI / `app-server` / Python SDK (`openai-codex`) share one home directory.

Resolution (`codex-rs/utils/home-dir`):

- If `CODEX_HOME` is set, it must already exist and be a directory (canonicalized).
- Otherwise: `$HOME/.codex`.

The Python SDK does not invent a second store. `Codex()` starts the bundled `codex app-server`, which reads and writes this tree. Isolate tests or extra installs with `CODEX_HOME` (and optionally `CODEX_SQLITE_HOME`).

Related: [public API EN](codex-python-sdk-v0.152.0-api-en.md) · [中文](codex-python-sdk-v0.152.0-api-zh.md) · [FAQ](faq.md) · [docs hub](../../../README.md)

SQLite files default to the same directory (`config.sqlite_home`, overridable with `CODEX_SQLITE_HOME` or `sqlite_home` in config). They are **not** the live model prompt. Live context is the in-memory thread plus the JSONL **rollout** under `sessions/`; SQLite is an index, search, goals, memories, queues, and logs.

Do not hand-edit WAL files or `auth.json`. Deleting `sessions/` drops resumable history even if SQLite still has metadata until it is rebuilt.

---

## Config and identity

| Path | Format | When created | Role |
| --- | --- | --- | --- |
| `config.toml` | TOML (`CONFIG_TOML_FILE`) | First run / you edit it | User config: model, features, MCP, `history`, `sqlite_home`, etc. SDK `config/batchWrite` writes here. |
| `auth.json` | JSON (`AuthDotJson`) | Login (`login_with_api_key`, ChatGPT OAuth, …) when store mode is `file` (default) | `OPENAI_API_KEY`, ChatGPT `tokens`, refresh time, optional Bedrock / PAT / agent identity. Keyring mode may omit this file. **Secret.** |
| `.credentials.json` | JSON | MCP OAuth when store mode is `file` | MCP tokens. Same-user readable. |
| `installation_id` | 36-byte UUID text | First process that needs a stable install id | Sent on Responses as `installation_id` / `x-codex-installation-id`. Not a thread id. |
| `version.json` | JSON | Installer / desktop host | Host version stamp. Not required by `app-server` core. |
| `AGENTS.md` | Markdown | You (optional) | User-global instructions. Merged with project `AGENTS.md` (and `AGENTS.override.md`) into model context. |
| `chrome-native-hosts-v2.json` | JSON | Chrome / desktop native-messaging setup | Native-host registration for the Chrome plugin. Not written by the Python SDK. |

`[history]` in `config.toml` controls `history.jsonl` only (`persistence = save-all \| none`, optional `max_bytes`). It does **not** disable `sessions/` rollouts unless the session is `ephemeral`.

---

## Conversation history (what resume actually uses)

### `sessions/`

Canonical thread log. Layout (`codex-rs/rollout`):

```text
sessions/<YYYY>/<MM>/<DD>/rollout-<YYYY-MM-DDTHH-MM-SS>-<thread-id>.jsonl
```

Revert may append `_<rollout-id>` after the thread id. Each line is a `RolloutLine`: `timestamp`, optional `ordinal`, and a tagged item (`session_meta`, `response_item`, `event_msg`, `compacted`, `world_state`, `turn_context`, …). Inspect with `jq`.

Created when a thread starts (CLI TUI, VS Code, `thread/start` from the SDK). Compact writes a `compacted` checkpoint into this file; resume rebuilds live history from the latest checkpoint, not from every pre-compact tool call.

### `archived_sessions/`

Same JSONL shape after archive (`ARCHIVED_SESSIONS_SUBDIR`). Resume from archive is a product path, not something the SDK invents.

### `session_index.jsonl`

JSONL, one object per line (`SessionIndexEntry`): `{ "id", "thread_name", "updated_at" }` (RFC3339). Append-only; **last line for an id wins**. Written when a thread is renamed. Used to resolve names without scanning every rollout.

### `history.jsonl`

JSONL (`codex-rs/message-history`): `{ "session_id", "ts", "text" }`. TUI / composer **input** history (Up-arrow), not the model transcript. Atomic `O_APPEND` writes; optional size cap drops oldest lines.

### `thread_history_1.sqlite`

Paginated thread-history projection (`THREAD_HISTORY_DB_FILENAME`). Opened on `StateRuntime::init`. Rebuildable from rollouts. Split from `state_*.sqlite` to cut lock contention. `-wal` / `-shm` are SQLite WAL (journal_mode=WAL).

### `thread-writer-locks/`

Per-thread lock files so two processes do not append the same rollout. Safe to empty when no Codex process is running.

---

## SQLite runtime (`codex-rs/state`)

Created on first `StateRuntime::init` (CLI, TUI, app-server). WAL + `-shm` sit beside each `.sqlite`. The number in the filename is the **schema generation** (e.g. `state_5`, `logs_2`), not “five databases”.

| File | Role |
| --- | --- |
| `state_5.sqlite` | Thread list metadata, projects, rollout backfill/migration, agent-graph / relations. Source of truth for “which threads exist” in the UI; rollouts remain the transcript. |
| `logs_2.sqlite` | Tracing export (`log_db`). Batched inserts. Not the `log/` text directory. |
| `goals_1.sqlite` | Thread goals (`thread/goal/set`, budget / blocked / usageLimited). |
| `memories_1.sqlite` | Structured memories store (extension). |
| `queue_1.sqlite` | Durable **queued user submissions** while a turn is running (composer queue). |
| `thread_history_1.sqlite` | See above. |

A nested `sqlite/` directory, if present, is not the current default layout (files live at `sqlite_home` root). Treat it as leftover or an old `CODEX_SQLITE_HOME`.

Text logs still default to `$CODEX_HOME/log` (`log_dir`).

---

## Memories vs SQLite memories

| Path | Role |
| --- | --- |
| `memories/` | Markdown (and related files) injected as memory context (`memory_root(codex_home)`). Created when the memories feature writes; config load does not mkdir it. |
| `memories_1.sqlite` | Indexed / structured side of the same subsystem. |

---

## Plugins, skills, pets, tmp

| Path | Role |
| --- | --- |
| `plugins/` | Installed plugins; cache under `plugins/cache/...`. `plugin/install` and marketplace. |
| `skills/` | User-level skills (`SKILL.md` trees). Combined with project / extra roots. |
| `pets/` | TUI pets: `pets/<id>/pet.json`. |
| `tmp/` | Scratch (e.g. `tmp/arg0` for sandbox arg0 helpers). Safe to clear when idle. |
| `computer-use/` | Computer-use plugin artifacts / workspace (bundled plugin id `computer-use@openai-bundled`). |
| `shell_snapshots/` | Shell environment snapshots for a thread (`SNAPSHOT_DIR`, ~3 day retention) when `ShellSnapshot` is on. |

---

## Other directories / files on a typical Mac install

These show up in a long-lived `~/.codex` but are not all owned by `app-server` core:

| Path | Likely role |
| --- | --- |
| `ambient-suggestions/` | TUI / desktop ambient suggestion cache. |
| `visualizations/` | UI visualization artifacts. |
| `vendor_imports/` | Imported vendor / external-agent config. |
| `external_agent_session_imports` | Import log or marker for migrating another agent’s sessions (TUI migration flow). |

If a name is missing from `codex-rs`, it is almost certainly the **desktop / VS Code / Chrome** host, not the Python wheel.

---

## How this maps to the Python SDK

| SDK / RPC | Disk |
| --- | --- |
| `Codex()` / `app-server` | Opens this home; creates SQLite + rollouts as threads run. |
| `login_*` / `logout` | `auth.json` or keyring. |
| `thread/start` | New `sessions/.../rollout-*.jsonl` + SQLite metadata. |
| `thread/resume` | Read rollout (and compact checkpoints); cwd from latest settings snapshot. |
| `thread/compact` | Compact item in the **same** rollout JSONL; advances auto-compact window; SQLite metadata updates. |
| `thread/set_name` | `session_index.jsonl` append. |
| `thread/goal/set` | `goals_1.sqlite`. |
| `config/batchWrite` | `config.toml`. |

Compaction does **not** rewrite `history.jsonl`. That file is composer history only.

---

## Practical notes

- Backup / copy a thread: copy the matching `sessions/YYYY/MM/DD/rollout-*.jsonl`. SQLite can be rebuilt.
- `CODEX_HOME` for the SDK: set it in the environment **before** `Codex()`, or use a wrapper that sets it. Do not point two concurrent app-server processes at the same home without expecting lock contention.
- Isolated examples in this repo use a throwaway `CODEX_HOME` so they never touch your real `~/.codex`.
