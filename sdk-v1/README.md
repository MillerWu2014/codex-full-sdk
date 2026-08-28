# Codex SDK v1（Python only）

仓库根目录下的 **v1 Python SDK**，不含 TypeScript。

| 目录 | PyPI 包名 | 作用 |
| --- | --- | --- |
| `python/` | `openai-codex` | 客户端库（`Codex` / `Thread` / JSON-RPC） |
| `python-runtime/` | `openai-codex-cli-bin` | 随 SDK 发布的 pinned `codex` CLI 二进制 |

`openai-codex` 依赖本目录的 `openai-codex-cli-bin`（path），不再走 `sdk/typescript`。

上游对照：`sdk/python`、`sdk/python-runtime`。本树可独立演进（见 `python/min-scope-requirements.zh.md`）。

## 安装（开发）

```bash
cd sdk-v1
uv sync --project python
```

或安装可编辑包：

```bash
cd sdk-v1/python
uv sync
```

`Codex()` 默认 spawn runtime 包里的 `codex app-server`。要用本仓库刚编的二进制：

```python
from openai_codex import Codex, CodexConfig

with Codex(CodexConfig(codex_bin="codex-rs/target/release/codex")) as codex:
    ...
```

## 版本

工作区包版本为 **1.0.0**。
