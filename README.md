# codex-full-sdk

本仓库演进自己的 Python SDK（`sdk-v1`），通过 git 子模块只读依赖上游 [openai/codex](https://github.com/openai/codex)。

**不要改 `codex/` 里的任何文件。** 协议、CLI、上游官方 SDK 都以子模块为准；客户端封装只在 `sdk-v1/` 上演进。

## 目录

| 路径 | 作用 |
| --- | --- |
| [`sdk-v1/python`](sdk-v1/python) | 本仓库的 Python 客户端（PyPI：`openai-codex`） |
| [`sdk-v1/python-runtime`](sdk-v1/python-runtime) | 本仓库 pinned 的 `codex` CLI runtime（`openai-codex-cli-bin`） |
| [`codex/`](codex) | 上游子模块：app-server 协议与 CLI。只读。 |
| [`codex/sdk/`](codex/sdk) | 上游官方 SDK（Python + TypeScript）。对照用，不要改。 |

`sdk-v1` 最初从上游 `codex/sdk/python` 分出，之后独立演进，不会自动与 `codex/sdk` 同步。

协议真源是子模块里的 [`codex/codex-rs/app-server-protocol/src/protocol/common.rs`](codex/codex-rs/app-server-protocol/src/protocol/common.rs)。RPC 覆盖范围见 [`sdk-v1/app-server-api.zh.md`](sdk-v1/app-server-api.zh.md) 与 [`sdk-v1/python/min-scope-requirements.zh.md`](sdk-v1/python/min-scope-requirements.zh.md)。

## 开发

```bash
git submodule update --init --recursive
cd sdk-v1/python
uv sync
uv run pytest -q
```

`Codex()` 默认启动 runtime 包里的 `codex app-server`。要用当前子模块编出来的二进制：

```python
from openai_codex import Codex, CodexConfig

with Codex(CodexConfig(codex_bin="codex/codex-rs/target/release/codex")) as codex:
    thread = codex.thread_start()
    print(thread.run("Explain this repository.").final_response)
```

在 `codex/codex-rs` 下 `cargo build --release --bin codex` 即可得到该二进制。不要把构建产物或补丁写回 `codex/`。
