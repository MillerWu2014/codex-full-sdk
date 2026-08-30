# codex-full-sdk

本仓库演进自己的 Python SDK（`sdk-v1`），通过 git 子模块只读依赖上游 [openai/codex](https://github.com/openai/codex)。

**不要改 `codex/` 里的任何文件。** 协议、CLI、上游官方 SDK 都以子模块为准；客户端封装只在 `sdk-v1/` 上演进。

## 目录

| 路径 | 作用 |
| --- | --- |
| [`sdk-v1/python`](sdk-v1/python) | 本仓库的 Python 客户端（PyPI：`openai-codex`） |
| [`sdk-v1/python-runtime`](sdk-v1/python-runtime) | 本仓库 pinned 的 `codex` CLI runtime（`openai-codex-cli-bin`） |
| [`adapter/`](adapter) | 可选：本机 Responses 适配进程（fold）。不进 wheel，不改 `codex/`。 |
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

## 打包

编排脚本在本仓库根目录，不在 `codex/` 子模块里：

```bash
python3 scripts/build_all.py
```

会依次：从当前子模块编译官方 `codex-package`、把 CLI 打进 `openai-codex-cli-bin` wheel、再打与之同版本的 `openai-codex` SDK wheel。产物都在已忽略的 `dist/` 下（`dist/wheels/*.whl`），不会写进 git 跟踪的 `sdk-v1/python-runtime`。

```bash
python3 scripts/build_all.py --version 1.0.0
python3 scripts/build_all.py --skip-cli          # 复用已有 dist/codex-package-<target>.tar.gz
python3 scripts/build_all.py --cargo-profile dev-small
python3 scripts/build_all.py --cargo "$HOME/.cargo/bin/cargo" --uv "$HOME/.local/bin/uv"
```

开编前会检查 Rust（`cargo`/`rustc`）和 `sdk-v1/python`（`uv` + `datamodel-code-generator`）。缺了会打印安装或 `--cargo` / `--uv` 指定方式。`--skip-cli` 只跳过 Rust 检查。需要已 init 的 `codex/` 子模块。

## 本地模型

Codex 只打 `/v1/responses`。接 Ollama / vLLM / LM Studio / SGLang 时：

1. 后端已经能吃 Codex 的 Responses 请求 → 只改用户级 [`~/.codex/config.toml`](adapter/deploy/config.toml.example)，**不要**起适配器。
2. 有 `/responses` 但 Qwen 等多 system 会炸 → 先起 [`adapter/`](adapter/README.md)，再把 `base_url` 指到 `http://127.0.0.1:18080/v1`。

SDK 和 `codex/` 都不启动该进程。说明与 systemd / launchd 见 [`adapter/README.md`](adapter/README.md)。
