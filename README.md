# codex-full-sdk

本仓库演进自己的 Python SDK（`sdk-v1`），通过 git 子模块只读依赖上游 [openai/codex](https://github.com/openai/codex)。**不要改 `codex/` 里的任何文件。** 协议、CLI、上游官方 SDK 都以子模块为准；客户端封装只在 `sdk-v1/` 上演进。

## 目录

| 路径                                             | 作用                                                               |
| ------------------------------------------------ | ------------------------------------------------------------------ |
| [`sdk-v1/python`](sdk-v1/python)                 | 本仓库的 Python 客户端（PyPI：`openai-codex`）                     |
| [`sdk-v1/python-runtime`](sdk-v1/python-runtime) | 本仓库 pinned 的 `codex` CLI runtime（`openai-codex-cli-bin`）     |
| [`adapter/`](adapter)                            | 可选：本机 Responses 适配进程（fold）。不进 wheel，不改 `codex/`。 |
| [`codex/`](codex)                                | 上游子模块：app-server 协议与 CLI。只读。                          |
| [`codex/sdk/`](codex/sdk)                        | 上游官方 SDK（Python + TypeScript）。对照用，不要改。              |

`sdk-v1` 最初从上游 `codex/sdk/python` 分出，之后独立演进，不会自动与 `codex/sdk` 同步。

## 文档

当前公开 Python API 以 **0.152.0** 为准（runtime：`openai-codex-cli-bin==0.152.0`）。完整接口说明是下面两份同结构文档。

| 文档                                                                                          | 语言    | 内容                                                                                         |
| --------------------------------------------------------------------------------------------- | ------- | -------------------------------------------------------------------------------------------- |
| [codex-python-sdk-v0.152.0-api-zh.md](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-zh.md) | 中文    | **公开 SDK 接口**（参数 / 返回 / 作用）：Thread vs Turn、系统提示、Skill/MCP 管理、配置、FS… |
| [codex-python-sdk-v0.152.0-api-en.md](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-en.md) | English | Same public API, English twin                                                                |
| [getting-started.md](sdk-v1/python/docs/getting-started.md)                                   | EN      | 安装、登录、跑一轮 turn                                                                      |
| [faq.md](sdk-v1/python/docs/faq.md)                                                           | EN      | Thread vs turn、sandbox、hang、`CODEX_HOME`                                                  |
| [codex-home.md](sdk-v1/python/docs/codex-home.md)                                             | EN      | `~/.codex` 落盘：rollout、SQLite、`AGENTS.md`、`skills/`                                     |
| [app-server-api.zh.md](sdk-v1/app-server-api.zh.md)                                           | 中文    | **上游 app-server 全量 RPC** vs SDK 覆盖（公开 / 内部 / 无）                                 |
| [min-scope-requirements.zh.md](sdk-v1/python/min-scope-requirements.zh.md)                    | 中文    | 本仓库封装范围（贡献用）                                                                     |
| [adapter/README.md](adapter/README.md)                                                        | 中文    | 本机 Responses fold；**不**进 wheel                                                          |
| [sdk-v1/python/README.md](sdk-v1/python/README.md)                                            | EN      | 包 README：安装与 quickstart                                                                 |
| [examples](sdk-v1/python/examples/README.md) · [local_adapter](examples/local_adapter)        | —       | 示例                                                                                         |

协议真源仍是子模块 [`codex-rs/app-server-protocol`](codex/codex-rs/app-server-protocol/src/protocol/common.rs) 与 [`app-server/README.md`](codex/codex-rs/app-server/README.md)。Python 封装只覆盖其中公开列；未封装 RPC 见覆盖表。

### 建议阅读顺序

```text
README（本文）
  ├─ 上手     → getting-started → python/README → examples
  ├─ 公开 API → v0.152.0 中文 / English（下面目录可直达章节）
  │              ├─ 系统提示、Skill/MCP 管理（无 create RPC，写文件 / config.toml）
  │              └─ faq、codex-home（磁盘与多轮）
  ├─ 覆盖缺口 → app-server-api.zh.md（上游有、SDK 没有的方法）
  └─ 本地模型 → adapter/README、~/.codex/config.toml
```

### 公开 API 章节（中 / 英）

同一节号两边内容对齐。点中文或 English 进对应文件的锚点。

| #   | 中文                                                                                                             | English                                                                                                                                   |
| --- | ---------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | [Thread 与 Turn](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-zh.md#1-thread-与-turn)                        | [Thread vs turn](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-en.md#1-thread-vs-turn)                                                 |
| 2   | [安装与导入](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-zh.md#2-安装与导入)                                | [Install and import](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-en.md#2-install-and-import)                                         |
| 3   | [`CodexConfig`](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-zh.md#3-codexconfig)                            | [`CodexConfig`](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-en.md#3-codexconfig)                                                     |
| 4   | [生命周期](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-zh.md#4-生命周期)                                    | [Lifecycle](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-en.md#4-lifecycle)                                                           |
| 5   | [账户 / 登录](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-zh.md#5-账户--登录)                               | [Account / login](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-en.md#5-account--login)                                                |
| 6   | [`Codex` — Thread](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-zh.md#6-codex--thread)                       | [`Codex` — threads](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-en.md#6-codex--threads)                                              |
| 7   | [`Thread`](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-zh.md#7-thread)                                      | [`Thread`](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-en.md#7-thread)                                                               |
| 8   | [`TurnHandle`](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-zh.md#8-turnhandle)                              | [`TurnHandle`](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-en.md#8-turnhandle)                                                       |
| 9   | [输入](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-zh.md#9-输入)                                            | [Inputs](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-en.md#9-inputs)                                                                 |
| 10  | [ApprovalMode 与 Sandbox](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-zh.md#10-approvalmode-与-sandbox)     | [ApprovalMode and Sandbox](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-en.md#10-approvalmode-and-sandbox)                            |
| 11  | [自定义系统提示词](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-zh.md#11-自定义系统提示词)                   | [Custom system / developer instructions](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-en.md#11-custom-system--developer-instructions) |
| 12  | [管理 Skill 与 MCP](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-zh.md#12-管理-skill-与-mcp)                 | [Managing skills and MCP](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-en.md#12-managing-skills-and-mcp)                              |
| 13  | [模型、配置、Skill、MCP、FS](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-zh.md#13-模型配置skillmcp文件系统) | [Models, config, skills, MCP, FS](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-en.md#13-models-config-skills-mcp-fs)                  |
| 14  | [`codex.experimental`](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-zh.md#14-codexexperimental)              | [`codex.experimental`](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-en.md#14-codexexperimental)                                       |
| 15  | [通知](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-zh.md#15-通知)                                           | [Notifications](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-en.md#15-notifications)                                                  |
| 16  | [错误与重试](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-zh.md#16-错误与重试)                               | [Errors and retry](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-en.md#16-errors-and-retry)                                            |
| 17  | [公开 SDK 没有的](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-zh.md#17-公开-sdk-没有app-server-仍有的)      | [Not in the public SDK](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-en.md#17-not-in-the-public-sdk-still-in-app-server)              |
| 18  | [最小示例](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-zh.md#18-最小示例)                                   | [Minimal examples](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-en.md#18-minimal-examples)                                            |
| 19  | [返回类型](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-zh.md#19-返回类型)                                   | [Return types](sdk-v1/python/docs/codex-python-sdk-v0.152.0-api-en.md#19-return-types)                                                    |

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

| rust target                  | wheel tag               |
| ---------------------------- | ----------------------- |
| `aarch64-apple-darwin`       | `macosx_11_0_arm64`     |
| `x86_64-apple-darwin`        | `macosx_10_9_x86_64`    |
| `aarch64-unknown-linux-musl` | `musllinux_1_1_aarch64` |
| `x86_64-unknown-linux-musl`  | `musllinux_1_1_x86_64`  |
| `aarch64-pc-windows-msvc`    | `win_arm64`             |
| `x86_64-pc-windows-msvc`     | `win_amd64`             |

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

Workflow：[`.github/workflows/python-wheels.yml`](.github/workflows/python-wheels.yml)。推 `main`、Actions 里手动 `Run workflow`，或推 `v*` tag：

```text
python3 scripts/build_all.py --from-github-release --all-platforms --sdk-from-precomputed
```

`--sdk-from-precomputed` 用子模块里的预计算 schema 打 `py3-none-any` 的 SDK wheel。Ubuntu 上往往跑不了 musl 的 `codex`，所以 CI 不依赖本机执行官方二进制。

产物进 Actions artifact。只有推 `v0.152.0` 这类 tag 才会挂到 GitHub Release（普通 push 不会建 Release）。默认不上 pypi.org：`openai-codex` / `openai-codex-cli-bin` 是 OpenAI 的包名。

## 本地模型

Codex 只打 `/v1/responses`。接 Ollama / vLLM / LM Studio / SGLang 时：

1. 后端已经能吃 Codex 的 Responses 请求 → 只改用户级 [`~/.codex/config.toml`](adapter/deploy/config.toml.example)，**不要**起适配器。
2. 有 `/responses` 但 Qwen 等多 system 会炸 → 先起 [`adapter/`](adapter/README.md)，再把 `base_url` 指到 `http://127.0.0.1:18080/v1`。

SDK 和 `codex/` 都不启动该进程。说明与 systemd / launchd 见 [`adapter/README.md`](adapter/README.md)。

装好 wheel 后，用 conda 环境跑 [`examples/local_adapter/`](examples/local_adapter) 检查 SDK API 是否通（isolated `CODEX_HOME`，不会改你的 `~/.codex/config.toml`）。
