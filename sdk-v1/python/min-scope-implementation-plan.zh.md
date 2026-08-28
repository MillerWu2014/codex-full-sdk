# Python SDK 最小范围实现方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `sdk-v1/python` 上，按已有 SDK 分层把 [`min-scope-requirements.zh.md`](min-scope-requirements.zh.md) 的 P0/P1 RPC 做成公开 1:1 封装，不改 app-server 协议，不碰上游 `sdk/python`。

**Architecture:** 保持现有三层：`CodexClient.request(method, params, response_model=)` → `CodexClient.<rpc_helper>(*Params)` → 公开 `Codex` / `Thread` 关键字参数构造 Params。`AsyncCodexClient` 只做 `asyncio.to_thread` 镜像；`AsyncCodex` / `AsyncThread` 镜像同步公开面。稳定 unary RPC 平铺；P1 experimental 方法走 `codex.experimental.*` / `thread.queue_*` 并在调用时检查 `CodexConfig.experimental_api`。`fs/watch` 是唯一新增长订阅，按 login/turn 的 `MessageRouter` 队列模式按 `watchId` 路由 `fs/changed`。

**Tech Stack:** Python 3.10+、Pydantic v2 生成模型 `openai_codex.generated.v2_all`、stdio JSON-RPC、`AppServerHarness` pytest、`scripts/update_sdk_artifacts.py`。

## Global Constraints

- 实现目录只有 `sdk-v1/python`（及必要时 `sdk-v1/python-runtime`）。不要改 `sdk/python`。
- 不改 app-server 协议；类型以重新生成后的 `generated/v2_all.py` 为准。禁止手写精简 DTO。
- 一个 RPC 一个公开方法。新方法 docstring 第一行必须是 `"""RPC: <method>."""`。
- 每个新方法必须同时出现在同步与异步面上，风格对齐现有 `thread_list` / `Thread.read` / `Codex.models`。
- 请求/响应使用生成的 `*Params` / `*Response`。Config RPC 键名 snake_case（对齐 `config.toml`）；其余字段 Python snake_case、wire camelCase（`model_dump(by_alias=True, exclude_none=True)`）。
- 不要新增服务器→客户端 handler。不要封装第 2 节非目标 RPC（审批、OAuth、沙箱 exec、`permissions` / `dynamicTools`、弃用 API、plugin 市场其余、apps/review/realtime/remote、连接级通知总线）。
- 现有 `thread_start(sandbox=..., approval_mode=...)` 的 sandbox / approval_mode 语义保持原样；默认审批 handler 继续对 command/fileChange 返回 `{"decision": "accept"}`。
- 不要静默丢字段：调用方传入 experimental 字段或调用 experimental 方法而 `experimental_api=False` 时必须抛清晰错误。
- 不要新增依赖。不要把 50 个方法抽成通用 dispatcher；继续逐方法薄封装。
- 测试：每个新增公开方法至少一条 app-server JSON-RPC 成功路径。不测静态常量。不为「未做的审批」写负向测试。
- 运行测试：`cd sdk-v1/python && uv run pytest <file> -q`。集成测试用现有 `tests/app_server_harness.py`，不要新建测试框架。
- **不要自动 git commit**，除非用户明确要求。

---

## 0. 与现有实现对齐的分层（不要改这套形状）

现有调用链（以 `thread/archive` / `models` 为准）：

```text
Codex.thread_archive(thread_id)
  -> CodexClient.thread_archive(thread_id)
       -> CodexClient.request("thread/archive", {"threadId": ...}, response_model=ThreadArchiveResponse)

AsyncCodex.thread_archive(thread_id)
  -> await AsyncCodexClient.thread_archive(...)
       -> await asyncio.to_thread(self._sync.thread_archive, ...)
```

公开方法：关键字参数 → 构造生成 `*Params` → 调 client helper。  
`# BEGIN GENERATED: Codex.flat_methods` / `Thread.flat_methods` 只覆盖 start/list/resume/fork/turn。**新 unary RPC 写在 GENERATED 块之外**（与 `Codex.models`、`Thread.read` / `set_name` / `compact` 相同）。  
`AsyncCodexClient` 禁止复制 RPC 逻辑，只能 `_call_sync(self._sync.<method>, ...)`。

`CodexClient.request` 继续是逃逸舱，不作为本需求验收面。

---

## 1. 协议事实（当前 schema vs 需求文）

当前 `generated/v2_all.py` 是 **稳定 schema**（`generate-json-schema` 未加 `--experimental`），落后于本仓库 `codex-rs/app-server-protocol`。需求里的若干「补参数」在稳定 schema 里不存在；**禁止在 Python 里发明这些字段**。Task 0 必须先用本仓库 CLI 重生带 experimental 的类型。

| 需求文说法 | 协议真相（Rust v2） | 本方案处理 |
| --- | --- | --- |
| `thread/start` 补 `environments` | `ThreadStartParams.environments`，`#[experimental("thread/start.environments")]` | P0 公开可选参数；依赖 experimental schema + 调用时若传入且 `experimental_api=False` 则报错 |
| 不要补 `permissions` / `dynamicTools` | 同结构上的 experimental 字段 | 生成器 **exclude**，公开签名不出现 |
| `thread/fork` 补 `lastTurnId` / `beforeTurnId` / `excludeTurns` | `last_turn_id` 稳定；`before_turn_id` experimental；**fork 没有 `excludeTurns`** | 公开 `last_turn_id`；公开 `before_turn_id`（experimental 门闩）。`exclude_turns` 在 **`thread/resume`**，不发明到 fork |
| `turn/start` 补 `audio` / `localAudio` | `UserInput` 已有 `AudioUserInput` / `LocalAudioUserInput` | 扩展 `_inputs.py`，与 `SkillInput` 相同 |
| `turn/start` 独立 `toolOutput` | `TurnStartParams.tool_output: Option<TurnToolOutput>`，不是 UserInput 变体 | `Thread.turn` / `run` 增加 `tool_output=` |
| `turn/start` 补 `environments` | experimental 字段 | 同 start：公开可选 + 门闩；exclude `permissions` |

生成器现状（必须改，否则 regen 会把禁止字段漏到公开面）：

```python
# scripts/update_sdk_artifacts.py::generate_public_api_flat_methods
thread_fork_fields = _load_public_fields(..., exclude={"thread_id", "last_turn_id", *approval_fields})
# last_turn_id 被故意排除 → 需求的 fork 参数缺口
```

`Thread.run` **不在** generated 块里，它手写转发 `turn()` 的 kwargs。改 `turn()` 签名后必须同步改 `Thread.run` 与 `AsyncThread.run`。

---

## 2. 文件职责

| 文件 | 职责 |
| --- | --- |
| `scripts/update_sdk_artifacts.py` | 从 CLI 生成 schema；`v2_all.py`；public flat_methods；**公开字段 exclude/allow 名单** |
| `src/openai_codex/generated/v2_all.py` | 唯一协议类型源。只允许脚本改 |
| `src/openai_codex/client.py` | 同步 JSON-RPC helpers + `request` |
| `src/openai_codex/async_client.py` | `to_thread` 镜像，零业务逻辑 |
| `src/openai_codex/api.py` | 公开 `Codex` / `AsyncCodex` / `Thread` / `AsyncThread` / `ExperimentalCodex` |
| `src/openai_codex/_inputs.py` | `AudioInput` / `LocalAudioInput`；`InputItem` union |
| `src/openai_codex/_message_router.py` | P1：按 `watchId` 路由 `fs/changed` |
| `src/openai_codex/_experimental.py` | `require_experimental_api(config)`；`ExperimentalApiDisabledError` |
| `src/openai_codex/errors.py` | 导出新错误类型 |
| `src/openai_codex/types.py` / `__init__.py` | 公开 Response / Input 类型 |
| `tests/test_client_rpc_methods.py` | Params dump by_alias |
| `tests/test_public_api_signatures.py` | 导出列表 + keyword 名单 |
| `tests/test_app_server_*.py` | 每 RPC 至少一条 harness 成功路径 |
| `docs/app-server-api.zh.md` | Python SDK 列：范围内方法改为「公开」 |

不新增 `CodexClient` 子类、不新增 HTTP 传输、不新增通知总线 API。

---

## 3. Unary RPC 统一配方（P0/P1 每个方法都用这一套）

以 `skills/list` 为完整样板。其它方法只替换表中的名字，**不要**换分层。

### 3.1 CodexClient（`client.py`）

先把 `_params_dict` 的类型从「逐个 V2 Params 联合」放宽为所有生成模型都能 dump（实现已经是 `model_dump`，只是注解窄了）：

```python
def _params_dict(params: BaseModel | JsonObject | None) -> JsonObject:
    if params is None:
        return {}
    if isinstance(params, BaseModel):
        dumped = params.model_dump(by_alias=True, exclude_none=True, mode="json")
        if not isinstance(dumped, dict):
            raise TypeError("Expected model_dump() to return dict")
        return dumped
    if isinstance(params, dict):
        return params
    raise TypeError(f"Expected generated params model or dict, got {type(params).__name__}")
```

新 helper 形状（thread 作用域把 `thread_id` 放进 Params，不要再手拼 camelCase dict，除非该方法目前已是手拼且本任务只是升公开）：

```python
def skills_list(self, params: SkillsListParams | JsonObject | None = None) -> SkillsListResponse:
    return self.request(
        "skills/list",
        _params_dict(params),
        response_model=SkillsListResponse,
    )
```

已有 `thread_goal_set` / `thread_goal_clear` **不要重写内部实现**；公开 `Thread.goal_set` / `goal_clear` 转调它们。只新增 `thread_goal_get`。

### 3.2 AsyncCodexClient（`async_client.py`）

```python
async def skills_list(
    self, params: SkillsListParams | JsonObject | None = None
) -> SkillsListResponse:
    return await self._call_sync(self._sync.skills_list, params)
```

### 3.3 公开 Codex（`api.py`，GENERATED 块外，紧挨 `models()`）

```python
def skills_list(
    self,
    *,
    cursor: str | None = None,
    limit: int | None = None,
) -> SkillsListResponse:
    """RPC: skills/list."""
    self._ensure_initialized()
    return self._client.skills_list(SkillsListParams(cursor=cursor, limit=limit))
```

`AsyncCodex` 同样：`await self._ensure_initialized()` + `await self._client.skills_list(...)`。

`Thread` 方法把 `thread_id=self.id` 填进 Params。`AsyncThread` 先 `await self._codex._ensure_initialized()`，再 `await self._codex._client.<helper>(...)`。

可选 Params 字段一律 `X | None = None`，与现有 `thread_list` 一致。需要 `thread_id` 的公开 Thread 方法不要让调用方再传 `thread_id`。

### 3.4 实验性门闩

`src/openai_codex/_experimental.py`：

```python
from .client import CodexConfig
from .errors import ExperimentalApiDisabledError


def require_experimental_api(config: CodexConfig, feature: str) -> None:
    if not config.experimental_api:
        raise ExperimentalApiDisabledError(
            f"{feature} requires CodexConfig.experimental_api=True"
        )
```

`errors.py`：

```python
class ExperimentalApiDisabledError(CodexError):
    """Raised when an experimental RPC or field is used without experimental_api."""
```

规则：

- **整方法**标 experimental（P1：queue/project/search/watch session 等）：公开方法第一行调用 `require_experimental_api(self._client.config, "thread/queue/add")`。
- **稳定方法上的 experimental 字段**（P0：`environments`、`before_turn_id`、`tool_output` 若 schema 标 experimental）：仅当实参不是 `None` 时检查。不要在 `experimental_api=False` 时从 Params 里删掉调用方给的值。
- `experimentalFeature/list` 与 `enablement/set` 是 **P0 稳定 RPC**，平铺为 `Codex.experimental_feature_list`，**不要**放进 `codex.experimental`。

P1 Codex 级方法挂到 `Codex.experimental`：

```python
class ExperimentalCodex:
    def __init__(self, codex: Codex) -> None:
        self._codex = codex

    def project_list(self, *, cursor: str | None = None, limit: int | None = None) -> ProjectListResponse:
        """RPC: project/list."""
        require_experimental_api(self._codex._client.config, "project/list")
        self._codex._ensure_initialized()
        return self._codex._client.project_list(ProjectListParams(cursor=cursor, limit=limit))

# Codex
@property
def experimental(self) -> ExperimentalCodex:
    return ExperimentalCodex(self)
```

`AsyncCodex.experimental` 对称。`Thread.queue_*` 按需求文落在 Thread 上并做同样门闩，不必再套一层 `thread.experimental`。

### 3.5 测试配方

**Params dump**（`tests/test_client_rpc_methods.py` 或新文件 `tests/test_client_min_scope_params.py`）：

```python
def test_skills_list_params_dump_by_alias() -> None:
    dumped = _params_dict(SkillsListParams(cursor="c1", limit=10))
    assert dumped == {"cursor": "c1", "limit": 10}
```

（字段以生成模型为准；有 alias 的必须出现 camelCase。）

**集成成功路径**（新文件按域拆，风格抄 `tests/test_app_server_lifecycle.py`）：

```python
def test_skills_list_returns_data(tmp_path) -> None:
    with AppServerHarness(tmp_path) as harness:
        with Codex(config=harness.app_server_config()) as codex:
            result = codex.skills_list()
    assert result.data is not None  # 或与整个 response 对象 deep equal
```

能不跑模型 turn 就不要 `enqueue_assistant_message`。需要 thread 的先 `codex.thread_start()`。  
每个域至少一条 `AsyncCodex` 镜像（不必每个 RPC 都写 async，但每个 **公开方法** 要有一条成功路径；sync 即可，另用 `test_async_parity_<domain>` 抽查 1 个方法）。需求原文是「同步与异步行为一致」——每个新方法都要有 async 对应实现；测试上：P0 每个方法一条 sync 成功路径 + 每域一条 async 抽查。若某方法 sync/async 签名不同则必须两边都测。

**签名测试**：新根导出加进 `EXPECTED_ROOT_EXPORTS`；`Thread.turn` / `Codex.thread_start` / `thread_fork` 的 keyword 名单随公开字段更新。

运行：

```bash
cd sdk-v1/python
uv run pytest tests/test_app_server_skills.py tests/test_public_api_signatures.py -q
```

Expected: PASS。

---

## Task 0: 用本仓库 CLI 重生 experimental schema，并锁住公开字段名单

**Files:**
- Modify: `sdk-v1/python/scripts/update_sdk_artifacts.py`（`generate_schema_from_pinned_runtime`、`generate_public_api_flat_methods` 的 exclude）
- Modify: `sdk-v1/python/src/openai_codex/generated/v2_all.py`（脚本生成）
- Modify: `sdk-v1/python/src/openai_codex/api.py`（flat_methods 由脚本重写）
- Modify: `sdk-v1/python/tests/test_public_api_signatures.py`（keyword 名单）
- Test: `sdk-v1/python/tests/test_contract_generation.py`、`tests/test_public_api_signatures.py`

**Interfaces:**
- Consumes: 本仓库 `codex-rs/target/release/codex`（或 `sdk-v1/python-runtime` 里与本仓库协议一致的二进制）
- Produces: `ThreadStartParams.environments`、`TurnStartParams.environments` / `tool_output`、`ThreadForkParams.last_turn_id` / `before_turn_id`；公开 `thread_start` 仍无 `permissions` / `dynamic_tools`

- [ ] **Step 1: 确认 schema 生成带 `--experimental`**

把 `generate_schema_from_pinned_runtime` 的 CLI 改成（在现有 `codex app-server generate-json-schema --out` 上加 flag）：

```python
run(
    [
        str(codex_path),
        "app-server",
        "generate-json-schema",
        "--experimental",
        "--out",
        str(schema_dir),
    ],
    cwd=sdk_root(),
)
```

`sdk-v1` 的 runtime 是 path 依赖。生成前确保 `pinned_runtime_codex_path()` 指向的二进制就是本仓库刚编的 CLI（`cargo build --release --bin codex` 后按 `python-runtime` 现有打包方式放进去，或临时让脚本接受 `CODEX_BIN`）。**不要**用过期的 PyPI `0.147.0` schema，否则 `environments` 仍然不会出现。

- [ ] **Step 2: 锁公开字段 exclude（在跑 generate-types 之前改脚本）**

在 `generate_public_api_flat_methods` 中：

```python
approval_fields = {"approval_policy", "approvals_reviewer"}
forbidden_start = {
    "permissions",
    "dynamic_tools",
    "mock_experimental_field",
    "experimental_raw_events",
    "multi_agent_mode",
    "history_mode",
    "project_id",
    "selected_capability_roots",
    "runtime_workspace_roots",
}
thread_start_fields = _load_public_fields(
    "openai_codex.generated.v2_all",
    "ThreadStartParams",
    exclude={*approval_fields, *forbidden_start},
)
# environments 保留在 thread_start_fields 中

thread_resume_fields = _load_public_fields(
    ...,
    exclude={"thread_id", *approval_fields, *forbidden_start},
)
# exclude_turns 若出现在 ResumeParams 则保留（协议在 resume，不在 fork）

thread_fork_fields = _load_public_fields(
    ...,
    exclude={"thread_id", "path", *approval_fields, *forbidden_start},
)
# 不再 exclude last_turn_id；before_turn_id 保留

turn_forbidden = {
    "permissions",
    "additional_context",
    "responsesapi_client_metadata",
    "runtime_workspace_roots",
    "turn_trigger",
    "service_tier_for_turn",
    "client_user_message_id",
}
turn_start_fields = _load_public_fields(
    ...,
    exclude={"thread_id", "input", *approval_fields, *turn_forbidden},
)
# environments、tool_output 保留
```

regen 后立刻打开生成的 `Codex.thread_start` / `Thread.turn` 签名，确认没有 `permissions=` / `dynamic_tools=`。

- [ ] **Step 3: 跑 generate-types**

```bash
cd sdk-v1/python
uv run python scripts/update_sdk_artifacts.py generate-types
```

Expected: 退出码 0；`v2_all.py` 中 `ThreadStartParams` 含 `environments`；`TurnStartParams` 含 `tool_output` 与 `environments`；`ThreadForkParams` 含 `before_turn_id`。

- [ ] **Step 4: 同步手写 `run()` kwargs，并更新签名测试**

`api.py` 里 `Thread.run` / `AsyncThread.run` 目前写死 `cwd/effort/model/...`。把 generated `turn()` 新增的公开关键字（至少 `environments`、`tool_output`）同样加到 `run()` 并原样传给 `self.turn(...)`。

更新 `tests/test_public_api_signatures.py` 里 `Codex.thread_start` / `thread_fork` / `Thread.turn` / `Thread.run` 及 Async 对应名单：加上 `environments`、`last_turn_id`、`before_turn_id`、`tool_output`；**不要**出现 `permissions`。

- [ ] **Step 5: 跑现有测试，修 regen 引起的断裂**

```bash
cd sdk-v1/python
uv run pytest tests/test_public_api_signatures.py tests/test_client_rpc_methods.py tests/test_app_server_lifecycle.py tests/test_app_server_run.py tests/test_app_server_inputs.py -q
```

Expected: PASS。只修本任务引入的签名/生成物断裂，不要顺手改审批测试。

---

## Task 1: 实验性门闩 + `_params_dict` 放宽

**Files:**
- Create: `sdk-v1/python/src/openai_codex/_experimental.py`
- Modify: `sdk-v1/python/src/openai_codex/errors.py`、`__init__.py`
- Modify: `sdk-v1/python/src/openai_codex/client.py`（`_params_dict`）
- Test: `sdk-v1/python/tests/test_experimental_api_guard.py`

**Interfaces:**
- Consumes: `CodexConfig.experimental_api: bool`（默认 `True`）
- Produces: `require_experimental_api(config, feature: str) -> None`；`ExperimentalApiDisabledError`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from openai_codex import CodexConfig
from openai_codex._experimental import require_experimental_api
from openai_codex.errors import ExperimentalApiDisabledError


def test_require_experimental_api_passes_when_enabled() -> None:
    require_experimental_api(CodexConfig(experimental_api=True), "project/list")


def test_require_experimental_api_raises_when_disabled() -> None:
    with pytest.raises(ExperimentalApiDisabledError):
        require_experimental_api(CodexConfig(experimental_api=False), "project/list")
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd sdk-v1/python && uv run pytest tests/test_experimental_api_guard.py -q
```

Expected: FAIL（模块不存在）。

- [ ] **Step 3: 按 §3.4 / §3.1 实现最小代码，根导出 `ExperimentalApiDisabledError`**

- [ ] **Step 4: 再跑测试确认通过**

Expected: PASS。

---

## Task 2: Turn 输入补齐（audio / localAudio / tool_output）+ start/fork/turn 参数缺口

**Files:**
- Modify: `sdk-v1/python/src/openai_codex/_inputs.py`、`api.py`、`__init__.py`
- Modify: `sdk-v1/python/scripts/update_sdk_artifacts.py`（若 Task 0 已做完则此处只补 `run()` 与门闩）
- Test: `sdk-v1/python/tests/test_app_server_inputs.py`、`tests/test_public_api_signatures.py`、`tests/test_app_server_lifecycle.py`

**Interfaces:**
- Consumes: Task 0 生成的 `AudioUserInput` / `LocalAudioUserInput` / `TurnToolOutput` / `TurnEnvironmentParams`
- Produces: `AudioInput(url)`、`LocalAudioInput(path)`；`thread_start(..., environments=)`；`thread_fork(..., last_turn_id=, before_turn_id=)`；`turn/run(..., environments=, tool_output=)`

- [ ] **Step 1: 扩展 `_inputs.py`（对齐 `SkillInput`）**

```python
@dataclass(slots=True)
class AudioInput:
    """Audio URL supplied as turn input."""
    url: str


@dataclass(slots=True)
class LocalAudioInput:
    """Local audio path supplied as turn input."""
    path: str


InputItem = (
    TextInput | ImageInput | LocalImageInput | AudioInput | LocalAudioInput | SkillInput | MentionInput
)


def _to_wire_item(item: InputItem) -> JsonObject:
    if isinstance(item, AudioInput):
        return {"type": "audio", "url": item.url}
    if isinstance(item, LocalAudioInput):
        return {"type": "localAudio", "path": item.path}
    # 保留现有 text/image/skill/mention 分支
```

`__init__.py` 与 `EXPECTED_ROOT_EXPORTS` 加上 `AudioInput`、`LocalAudioInput`。

- [ ] **Step 2: 在 `thread_start` / `turn` 调用点加字段门闩**

对 `environments`、`before_turn_id`、`tool_output`：若实参不是 `None`，调用 `require_experimental_api`。`last_turn_id` 是稳定字段，不要门闩。

不要把 `permissions` 加到任何公开签名。

- [ ] **Step 3: 测试**

`test_app_server_inputs.py` 增加 audio 路径（有 Responses mock 则断言 user content 含 audio；若 harness 还没有 audio helper，至少断言 `turn/start` 发出的 JSON-RPC params `input` 含 `{"type": "audio", "url": ...}`——可在 client 单测里对 `_to_wire_item` 做：

```python
def test_audio_input_wire_shape() -> None:
    assert _to_wire_item(AudioInput("https://example.com/a.wav")) == {
        "type": "audio",
        "url": "https://example.com/a.wav",
    }
```

fork：`tests/test_app_server_lifecycle.py` 风格，`thread_fork(thread.id, last_turn_id=...)` 后 `thread_read` 确认新 thread id 不同。`before_turn_id` 一条成功路径（`experimental_api` 默认 True）。

`experimental_api=False` 且传入 `environments=[...]` 时：

```python
def test_environments_rejected_when_experimental_api_disabled(tmp_path) -> None:
    with AppServerHarness(tmp_path) as harness:
        config = harness.app_server_config()
        config.experimental_api = False
        with Codex(config=config) as codex:
            with pytest.raises(ExperimentalApiDisabledError):
                codex.thread_start(environments=[])
```

- [ ] **Step 4: 跑测试**

```bash
cd sdk-v1/python
uv run pytest tests/test_app_server_inputs.py tests/test_app_server_lifecycle.py tests/test_public_api_signatures.py tests/test_experimental_api_guard.py -q
```

Expected: PASS。

---

## Task 3: Thread 稳定 unary（P0）

**Files:**
- Modify: `client.py`、`async_client.py`、`api.py`、`types.py`
- Test: `tests/test_app_server_thread_management.py`

**Interfaces:**
- Consumes: §3 配方；生成的 Params/Response
- Produces: 下表公开方法

| RPC | 落点 | Client helper | Params / Response |
| --- | --- | --- | --- |
| `thread/delete` | `Codex.thread_delete(thread_id)` | `thread_delete` | `ThreadDeleteParams` / `ThreadDeleteResponse` |
| `thread/unsubscribe` | `Thread.unsubscribe()` | `thread_unsubscribe` | `ThreadUnsubscribeParams` / `ThreadUnsubscribeResponse` |
| `thread/loaded/list` | `Codex.thread_loaded_list(...)` | `thread_loaded_list` | `ThreadLoadedListParams` / `ThreadLoadedListResponse` |
| `thread/turns/list` | `Thread.turns_list(...)` | `thread_turns_list` | `ThreadTurnsListParams` / `ThreadTurnsListResponse` |
| `thread/items/list` | `Thread.items_list(...)` | `thread_items_list` | `ThreadItemsListParams` / `ThreadItemsListResponse` |
| `thread/revert` | `Thread.revert(...)` | `thread_revert` | `ThreadRevertParams` / `ThreadRevertResponse` |
| `thread/inject_items` | `Thread.inject_items(...)` | `thread_inject_items` | `ThreadInjectItemsParams` / `ThreadInjectItemsResponse` |
| `thread/metadata/update` | `Thread.metadata_update(...)` | `thread_metadata_update` | `ThreadMetadataUpdateParams` / `ThreadMetadataUpdateResponse` |
| `thread/section/move` | `Thread.section_move(...)` | `thread_section_move` | `ThreadSectionMoveParams` / `ThreadSectionMoveResponse` |

关键字从各 Params 减去已由 `self.id` / 函数位置参数提供的 `thread_id`。分页字段用 `cursor` / `limit`（与 `thread_list` 相同）。

- [ ] **Step 1: 先写 `test_thread_delete_removes_thread`**

```python
def test_thread_delete_removes_thread(tmp_path) -> None:
    with AppServerHarness(tmp_path) as harness:
        with Codex(config=harness.app_server_config()) as codex:
            thread = codex.thread_start()
            thread_id = thread.id
            codex.thread_delete(thread_id)
            listed = codex.thread_list()
    assert thread_id not in [item.id for item in listed.data]
```

（若 `thread_list` 的条目字段名是 `thread.id` 而不是顶层 `id`，按 `ThreadListResponse` 实际结构断言整个对象或 `.thread.id`。）

跑测 Expected: FAIL（`Codex` 无 `thread_delete`）。

- [ ] **Step 2: 按 §3 实现表中全部方法（同步+异步）**

`Thread.unsubscribe` 示例：

```python
def unsubscribe(self) -> ThreadUnsubscribeResponse:
    """RPC: thread/unsubscribe."""
    return self._client.thread_unsubscribe(ThreadUnsubscribeParams(thread_id=self.id))
```

- [ ] **Step 3: 为表中每个 RPC 补一条 harness 成功路径，再跑**

```bash
cd sdk-v1/python && uv run pytest tests/test_app_server_thread_management.py -q
```

Expected: PASS。

不做：`thread/rollback`、`thread/shellCommand`、guardian/elicitation。

---

## Task 4: Goal 升公开 + threadSection CRUD（P0）

**Files:**
- Modify: `client.py`（新增 `thread_goal_get`）、`async_client.py`、`api.py`、`types.py`
- Test: `tests/test_app_server_goal_operations.py`、`tests/test_app_server_thread_sections.py`

**Interfaces:**
- Consumes: 已有 `CodexClient.thread_goal_set` / `thread_goal_clear`（不要改成另一套语义；那是 persisted goal，不是 `start_goal_operation`）
- Produces: `Thread.goal_set` / `goal_get` / `goal_clear`；`Codex.thread_section_list/create/update/delete`

```python
def goal_set(
    self,
    *,
    objective: str | None = None,
    status: ThreadGoalStatus | None = None,
) -> ThreadGoalSetResponse:
    """RPC: thread/goal/set."""
    return self._client.thread_goal_set(self.id, objective=objective, status=status)

def goal_clear(self) -> ThreadGoalClearResponse:
    """RPC: thread/goal/clear."""
    return self._client.thread_goal_clear(self.id)

def goal_get(self) -> ThreadGoalGetResponse:
    """RPC: thread/goal/get."""
    return self._client.thread_goal_get(ThreadGoalGetParams(thread_id=self.id))
```

Section CRUD 按 §3，方法名 `thread_section_list` 等，RPC `threadSection/list|create|update|delete`。

- [ ] **Step 1: 失败测试 `thread.goal_get()` 与 `codex.thread_section_list()`**
- [ ] **Step 2: 实现 + 每 RPC 一条成功路径**
- [ ] **Step 3: 跑测 Expected: PASS**

---

## Task 5: Skills + plugin/skill/read（P0）

**Files:**
- Modify: `client.py`、`async_client.py`、`api.py`、`types.py`
- Test: `tests/test_app_server_skills.py`

| RPC | 公开方法 |
| --- | --- |
| `skills/list` | `Codex.skills_list` |
| `skills/extraRoots/set` | `Codex.skills_extra_roots_set` |
| `skills/config/write` | `Codex.skills_config_write` |
| `plugin/skill/read` | `Codex.plugin_skill_read` |

不做 `skills/changed` 订阅。`SkillInput` 已有，不要改 turn 内 skill 语义。

- [ ] **Step 1–4: 按 §3 配方，每个方法一条 harness 成功路径（list 至少能 round-trip；write/set 后 list 或 read 验证）**

```bash
cd sdk-v1/python && uv run pytest tests/test_app_server_skills.py -q
```

---

## Task 6: MCP（无 OAuth）（P0）

**Files:**
- Modify: `client.py`、`async_client.py`、`api.py`、`types.py`
- Test: `tests/test_app_server_mcp.py`

| RPC | 公开方法 |
| --- | --- |
| `config/mcpServer/reload` | `Codex.mcp_reload` |
| `mcpServerStatus/list` | `Codex.mcp_status_list` |
| `mcpServer/resource/read` | `Codex.mcp_resource_read` |
| `mcpServer/tool/call` | `Thread.mcp_tool_call`（Params 含 `thread_id=self.id`） |

不做：`mcpServer/oauth/login`、elicitation、`mcpServer/event/stream/*`。

无 MCP server 时，`mcp_status_list` 仍应成功返回列表（可为 empty）。`tool/call` 若 harness 无 MCP，测 Params dump + 若服务器返回 JSON-RPC 错误则断言错误类型而不是封装该方法——需求要成功路径：给 harness 的 `config_overrides` 配一个 mock MCP 不现实时，用 **能成功的** `mcp_status_list` / `mcp_reload` 作集成成功路径；`tool/call` / `resource/read` 用 client 层对 `request` 的 monkeypatch 或现有 harness 若已能连 MCP。优先真 harness；否则在 `tests/test_client_rpc_methods.py` 断言 helper 发出的 method 字符串与 payload alias，并在集成里 skip 仅当 `CODEX_SANDBOX_NETWORK_DISABLED`——本仓库 Python 测试不走该宏。最低标准：四个 helper 都有「发出正确 method + 解析 Response 模型」的测试；其中 list/reload 必须打到真 app-server。

```bash
cd sdk-v1/python && uv run pytest tests/test_app_server_mcp.py tests/test_client_rpc_methods.py -q
```

---

## Task 7: Config / 功能开关 / external agent（P0）

**Files:**
- Modify: `client.py`、`async_client.py`、`api.py`、`types.py`
- Test: `tests/test_app_server_config.py`

| RPC | 公开方法 | 备注 |
| --- | --- | --- |
| `config/read` | `Codex.config_read` | 键 snake_case |
| `config/value/write` | `Codex.config_value_write` | 同上 |
| `config/batchWrite` | `Codex.config_batch_write` | 同上 |
| `configRequirements/read` | `Codex.config_requirements_read` | |
| `experimentalFeature/list` | `Codex.experimental_feature_list` | 稳定 RPC，不是 `codex.experimental` |
| `experimentalFeature/enablement/set` | `Codex.experimental_feature_enablement_set` | 同上 |
| `externalAgentConfig/detect` | `Codex.external_agent_config_detect` | |
| `externalAgentConfig/import` | `Codex.external_agent_config_import` | |
| `externalAgentConfig/import/readHistories` | `Codex.external_agent_config_import_read_histories` | |

不做 `permissionProfile/list`。`CodexConfig.config_overrides` 不动。

成功路径示例：`config_read` 后 `config_value_write` 再 `config_read`，对写入的那一个 key deep equal。

```bash
cd sdk-v1/python && uv run pytest tests/test_app_server_config.py -q
```

---

## Task 8: Model capabilities + FS CRUD + fuzzyFileSearch（P0）

**Files:**
- Modify: `client.py`、`async_client.py`、`api.py`、`types.py`
- Test: `tests/test_app_server_fs.py`、`tests/test_app_server_models.py`

| RPC | 公开方法 |
| --- | --- |
| `modelProvider/capabilities/read` | `Codex.model_provider_capabilities` |
| `fs/readFile` | `Codex.fs_read_file` |
| `fs/writeFile` | `Codex.fs_write_file` |
| `fs/createDirectory` | `Codex.fs_create_directory` |
| `fs/getMetadata` | `Codex.fs_get_metadata` |
| `fs/readDirectory` | `Codex.fs_read_directory` |
| `fs/remove` | `Codex.fs_remove` |
| `fs/copy` | `Codex.fs_copy` |
| `fuzzyFileSearch` | `Codex.fuzzy_file_search` |

路径必须绝对（`tmp_path` 下文件）。不要做 `fs/watch`（P1）。

FS 成功路径：write → read → metadata → copy → readDirectory → remove。`fuzzyFileSearch` 在 `tmp_path` 放一个已知文件名。`model_provider_capabilities` 对当前 provider 读一次。

`Codex.models` 已有，不要重命名。

```bash
cd sdk-v1/python && uv run pytest tests/test_app_server_fs.py tests/test_app_server_models.py -q
```

---

## P0 完成门闩

在开始 P1 之前必须全部为真：

1. Task 0–8 测试通过。
2. 第 2 节非目标 RPC **没有**新的公开方法（抽查 `dir(Codex)` / `dir(Thread)` 不含 `rollback`、`shell_command`、`permission_profile`、`oauth`）。
3. `test_app_server_approvals.py` 仍 PASS（默认 accept 未改）。
4. 同步/异步成对存在。

```bash
cd sdk-v1/python
uv run pytest tests/test_app_server_approvals.py tests/test_public_api_signatures.py tests/test_app_server_thread_management.py tests/test_app_server_skills.py tests/test_app_server_mcp.py tests/test_app_server_config.py tests/test_app_server_fs.py tests/test_app_server_models.py tests/test_app_server_thread_sections.py tests/test_app_server_goal_operations.py tests/test_app_server_inputs.py tests/test_app_server_lifecycle.py -q
```

---

## Task 9: `fs/watch` / `fs/unwatch`（P1，唯一新长订阅）

**Files:**
- Modify: `_message_router.py`、`client.py`、`async_client.py`、`api.py`
- Test: `tests/test_app_server_fs_watch.py`

**Interfaces:**
- Consumes: `FsWatchParams(path, watch_id)`、`FsChangedNotification`（registry 已有 `"fs/changed"`）
- Produces: `Codex.fs_watch` → 同步 iterator / 异步 async iterator；`Codex.fs_unwatch`

**不要**用 `next_global_notification()` 当公开 API（需求禁止新连接级总线）。照抄 login 队列：

在 `route_notification` 里，**先于** turn_id 全局回落，匹配 `notification.method == "fs/changed"` 且 payload 有 `watch_id`，送进 `_watch_notifications[watch_id]`；未 register 则 pending deque（与 login 相同）。`fail_all` 必须唤醒 watch 队列。

公开形状（P1，要门闩）：

```python
def fs_watch(self, path: str, *, watch_id: str) -> Iterator[FsChangedNotification]:
    """RPC: fs/watch."""
    require_experimental_api(self._client.config, "fs/watch")
    self._ensure_initialized()
    self._client.fs_watch(FsWatchParams(path=path, watch_id=watch_id))
    return self._client.stream_fs_changed(watch_id)
```

`stream_fs_changed`：`register_watch` → loop `next_watch_notification` → yield `FsChangedNotification` → `unwatch`/close 时 `unregister`。提供 `close()` 或 context manager 以便 `fs/unwatch`。

Async：`AsyncIterator`，内部 `asyncio.to_thread` 取下一条通知（对齐 `stream_text` 的 async 包装）。

测试：在 `tmp_path` watch 一个文件，SDK 外改文件，iterator 在超时内收到 `changed_paths`。`experimental_api=False` 时 `fs_watch` 抛 `ExperimentalApiDisabledError`。

```bash
cd sdk-v1/python && uv run pytest tests/test_app_server_fs_watch.py -q
```

---

## Task 10: 其余 P1 experimental RPC

全部 `require_experimental_api`。Codex 级走 `codex.experimental.<name>`；Thread 级走 `Thread.queue_*` 等。

| RPC | 落点 |
| --- | --- |
| `thread/search` | `codex.experimental.thread_search` |
| `thread/searchOccurrences` | `codex.experimental.thread_search_occurrences` |
| `turn/settings/update` | `TurnHandle.settings_update` 或 `Thread.turn_settings_update`（需要 turn id 时用 handle；现有 `TurnHandle` 已有 `steer`/`interrupt`，同文件追加） |
| `collaborationMode/list` | `codex.experimental.collaboration_mode_list` |
| `fuzzyFileSearch/sessionStart` | `codex.experimental.fuzzy_file_search_session_start` |
| `fuzzyFileSearch/sessionUpdate` | `codex.experimental.fuzzy_file_search_session_update` |
| `fuzzyFileSearch/sessionStop` | `codex.experimental.fuzzy_file_search_session_stop` |
| `thread/queue/add` | `Thread.queue_add` |
| `thread/queue/list` | `Thread.queue_list` |
| `thread/queue/update` | `Thread.queue_update` |
| `thread/queue/delete` | `Thread.queue_delete` |
| `thread/queue/reorder` | `Thread.queue_reorder` |
| `thread/queue/start` | `Thread.queue_start` |
| `thread/memoryMode/set` | `Thread.memory_mode_set` |
| `memory/reset` | `codex.experimental.memory_reset` |
| `thread/settings/update` | `Thread.settings_update` |
| `project/list` | `codex.experimental.project_list` |
| `project/read` | `codex.experimental.project_read` |
| `project/create` | `codex.experimental.project_create` |
| `project/import` | `codex.experimental.project_import` |
| `project/update` | `codex.experimental.project_update` |
| `project/move` | `codex.experimental.project_move` |
| `project/delete` | `codex.experimental.project_delete` |

精确 RPC 字符串与 Params 类名以 regen 后的 `v2_all.py` 为准（有的可能是 `project/list` vs `projects/list`）。**以生成的 Request.method Literal 为唯一真源**，不要抄本表写错的斜杠。

每个方法：§3 配方 + 一条成功路径 + 一条 `experimental_api=False` 的抛错（每域一条 False 即可，不必每个方法都测 False）。

`TurnHandle.settings_update` 必须与现有 `steer`/`interrupt` 一样挂在 handle 上，不要新开审批流。

```bash
cd sdk-v1/python && uv run pytest tests/test_app_server_experimental.py tests/test_app_server_queue.py tests/test_app_server_project.py -q
```

---

## Task 11: 文档与导出收尾

**Files:**
- Modify: `docs/app-server-api.zh.md`（Python SDK 列：范围内从「无 / 内部 / 部分」改为「公开」；P1 标明须 `experimental_api`）
- Modify: `sdk-v1/python/types.py`、`__init__.py`、`tests/test_public_api_signatures.py`
- Modify: `sdk-v1/python/min-scope-requirements.zh.md` 不改需求语义；如公开方法名与建议落点不一致，在本 plan 或 README 记一笔即可

文档写明：自定义审批 **不在本范围**；默认 command/fileChange 仍 auto-accept。

```bash
cd sdk-v1/python
uv run pytest tests/test_public_api_signatures.py -q
```

---

## 明确不做（执行时对照）

- 任何 `item/*/requestApproval`、`item/tool/call`、`attestation/*`、`mcpServer/oauth/*`、`command/exec*`、`process/*`、`windowsSandbox/*`、`thread/shellCommand`、`permissionProfile/*`
- `thread/start` / `turn/start` 的 `permissions`、`dynamicTools`
- `thread/rollback`、v1 leftover
- 连接级 `thread/closed`、`skills/changed` 订阅
- 改 `CodexClient._default_approval_handler`
- 改上游 `sdk/python`

---

## 建议落地顺序与体积

按 Task 0 → 11 线性做。每个 Task 对应一次可审查 diff。单 Task 超过约 500 行逻辑时，按表中 RPC 再拆 PR（先 delete/unsubscribe/loaded，再 turns/items，再 revert/inject/metadata/section）。

P0 未完成禁止开始 Task 9–10。
