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

默认只打**本机**那一个官方 triple（Linux 用 musl，与 GitHub `codex-package` 一致）：从子模块编译、打带正确 PEP 425 标签的 `openai-codex-cli-bin`、再打同版本 `openai-codex`（`py3-none-any`）。产物在已忽略的 `dist/wheels/`。

六个官方 package 平台：

| rust target | wheel tag |
| --- | --- |
| `aarch64-apple-darwin` | `macosx_11_0_arm64` |
| `x86_64-apple-darwin` | `macosx_10_9_x86_64` |
| `aarch64-unknown-linux-musl` | `musllinux_1_1_aarch64` |
| `x86_64-unknown-linux-musl` | `musllinux_1_1_x86_64` |
| `aarch64-pc-windows-msvc` | `win_arm64` |
| `x86_64-pc-windows-msvc` | `win_amd64` |

一次打齐六个 cli-bin wheel（下载 `rust-v*` 上的 `codex-package-*.tar.gz`，不必在本机交叉编译）：

```bash
python3 scripts/build_all.py --from-github-release --all-platforms
```

本机有对应二进制时会再打 SDK wheel；只打 runtime 用 `--skip-sdk`。

```bash
python3 scripts/build_all.py --version 0.152.0
python3 scripts/build_all.py --skip-cli          # 复用已有 dist/codex-package-<target>.tar.gz
python3 scripts/build_all.py --cargo-profile dev-small
python3 scripts/build_all.py --cargo "$HOME/.cargo/bin/cargo" --uv "$HOME/.local/bin/uv"
```

cargo 路径会检查 Rust；`--from-github-release` / `--skip-cli` 不检查。`uv` 与 `datamodel-code-generator` 始终需要（打 SDK 时生成类型）。需要已 init 的 `codex/` 子模块。

官方 PyPI 的 `openai-codex-cli-bin` 另外还有两个 `manylinux` wheel（gnu），GitHub 上没有对应的 `*-linux-gnu` package 包；本仓库只 wrap 公开的六个 `codex-package`。

### GitHub Actions

官方 Codex 其实是两层 CI，不要混：

1. **Rust 多 runner 矩阵**（macos / linux / windows）在上游编译 `codex-package` 和预编译 wheel。本仓库不复制那套，也不在 CI 里 `cargo build`。
2. **python-runtime-build** 是一台 `ubuntu-latest`：把已经发布的包重新打成 Python wheel。本仓库走这条。

Workflow：[`.github/workflows/python-wheels.yml`](.github/workflows/python-wheels.yml)。Actions 里手动 `Run workflow`，或推 `v*` tag：

```text
python3 scripts/build_all.py --from-github-release --all-platforms --sdk-from-precomputed
```

`--sdk-from-precomputed` 用子模块里的预计算 schema 打 `py3-none-any` 的 SDK wheel。Ubuntu 上往往跑不了 musl 的 `codex`，所以 CI 不依赖本机执行官方二进制。

产物进 Actions artifact；推 `v0.152.0` 这类 tag 时再挂到 GitHub Release。默认不上 pypi.org：`openai-codex` / `openai-codex-cli-bin` 是 OpenAI 的包名。

## 本地模型

Codex 只打 `/v1/responses`。接 Ollama / vLLM / LM Studio / SGLang 时：

1. 后端已经能吃 Codex 的 Responses 请求 → 只改用户级 [`~/.codex/config.toml`](adapter/deploy/config.toml.example)，**不要**起适配器。
2. 有 `/responses` 但 Qwen 等多 system 会炸 → 先起 [`adapter/`](adapter/README.md)，再把 `base_url` 指到 `http://127.0.0.1:18080/v1`。

SDK 和 `codex/` 都不启动该进程。说明与 systemd / launchd 见 [`adapter/README.md`](adapter/README.md)。

装好 wheel 后，用 conda 环境跑 [`examples/local_adapter/`](examples/local_adapter) 检查 SDK API 是否通（isolated `CODEX_HOME`，不会改你的 `~/.codex/config.toml`）。
