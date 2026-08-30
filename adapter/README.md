# Codex 本地 Responses Adapter

Codex（CLI 与 `openai-codex` SDK）**只**向模型服务发 `POST /v1/responses`。Ollama / vLLM / LM Studio / SGLang 经常是：

- 有 `/v1/responses`，但 Qwen 等模板吃不了多条 `system` / `developer`（本适配器的 `fold`）
- 只有 `/v1/chat/completions`（`chat` 翻译**尚未实现**）

本目录是 **Codex 外面的进程**。不改 `codex/`，也不改 SDK 协议。SDK **不会**启动本进程。

```text
你的程序 / CLI
    →  openai-codex / codex app-server
    →  ~/.codex/config.toml 里的 base_url
    →  本 adapter（本机 127.0.0.1）
    →  真正的本地模型服务
```

后端已经能完整讲 Responses、模型也不炸时：**不要起本进程**，config 直接指向上游。

## 依赖关系

| 组件 | 职责 |
| --- | --- |
| `openai-codex` | Python API，拉起 `openai-codex-cli-bin` 里的 `codex app-server` |
| `openai-codex-cli-bin` | 本机 Codex 二进制，读 **用户级** `~/.codex/config.toml` |
| **本 adapter（可选）** | 运维单独部署；只在上游吃不下 Codex 的 Responses 请求时需要 |
| 本地模型服务 | Ollama / vLLM / LM Studio / SGLang 等 |

`model_provider` / `model_providers` 必须写在 **`~/.codex/config.toml`**。项目目录下的 `.codex/config.toml` 会被 Codex 忽略。

## 何时用哪种 mode

| `CODEX_LOCAL_ADAPT` | 何时 |
| --- | --- |
| `fold`（默认，已实现） | 上游已有 `/v1/responses`，但多条 system/developer 会失败（常见于 Qwen + LM Studio） |
| `chat` | **未实现**。上游只有 `/v1/chat/completions` 时先换能讲 Responses 的后端，或等后续增量 |

## 启动

只需 Python 3.10+ 标准库。

```bash
export CODEX_LOCAL_UPSTREAM=http://192.168.101.232:1234
export CODEX_LOCAL_LISTEN=127.0.0.1:18080
export CODEX_LOCAL_ADAPT=fold

# 在仓库根目录
python3 adapter/server.py
```

等价：

```bash
python3 adapter/server.py \
  --upstream http://192.168.101.232:1234 \
  --listen 127.0.0.1:18080 \
  --adapt fold
```

`CODEX_LOCAL_UPSTREAM` 是源站 origin（`http://host:port`），不要带 `/v1`。Codex 请求的路径（`/v1/responses`）会原样接到后面。

探活：`curl -s http://127.0.0.1:18080/health` 应返回 `ok`（探活不打访问日志）。

自检（无网络）：`python3 adapter/check.py`。

日志打到 **stderr**，一行一事，不含 prompt / Authorization：

```text
2026-08-30T13:25:01 INFO listen=127.0.0.1:18080 upstream=http://192.168.101.232:1234 adapt=fold timeout=600.0
2026-08-30T13:25:08 INFO id=a1b2c3d4 client=127.0.0.1 POST /v1/responses status=200 ms=1840 fold=folded model=qwen3 in=12004 out=11880
2026-08-30T13:25:09 ERROR id=ee11ff22 client=127.0.0.1 POST /v1/responses status=502 ms=12 fold=unchanged model=qwen3 in=800 out=800 err=URLError: timed out
```

| 字段 | 含义 |
| --- | --- |
| `id` | 本请求短 ID，方便和并发请求对上 |
| `status` / `ms` | 回给 Codex 的 HTTP 状态、耗时 |
| `fold` | `folded` 已合并多条 system/developer；`unchanged` 无需折；`skip` 非 `/responses` POST；`invalid` JSON 坏了，原样转发 |
| `model` | 请求体里的模型名（没有则省略） |
| `in` / `out` | fold 前后 body 字节数 |
| `err` | 仅 502：异常类型和一行摘要 |

systemd / launchd 示例已把 stderr 接到服务日志。

### 环境变量

| 变量 | 默认 | 含义 |
| --- | --- | --- |
| `CODEX_LOCAL_UPSTREAM` | （必填） | 上游 origin |
| `CODEX_LOCAL_LISTEN` | `127.0.0.1:18080` | 本机监听 |
| `CODEX_LOCAL_ADAPT` | `fold` | `fold` 或 `chat` |
| `CODEX_LOCAL_TIMEOUT` | `600` | 上游超时（秒） |

## 运维：config.toml

先起 adapter，再让 Codex 打 adapter，不要打上游。

```toml
# ~/.codex/config.toml
model = "qwen3"
model_provider = "local"

[model_providers.local]
name = "local"
base_url = "http://127.0.0.1:18080/v1"
wire_api = "responses"
requires_openai_auth = false
```

`model` 换成上游真实模型名。完整示例见 [`deploy/config.toml.example`](deploy/config.toml.example)。

然后：

```python
from openai_codex import Codex

with Codex() as codex:
    print(codex.thread_start().run("hi").final_response)
```

不要用 `CodexConfig.config_overrides` 再改 `model_provider`，否则会盖掉运维配置。

直连（无需 adapter）时，可把 `base_url` 改成上游自己的 `/v1`，或用内置 `lmstudio` / `ollama`。

## 部署

进程要在 **Codex / SDK 之前** 起来，并与 app-server **同一台机器**（`base_url` 是 `127.0.0.1`）。

### 手动

```bash
cd /path/to/codex-full-sdk
CODEX_LOCAL_UPSTREAM=http://192.168.101.232:1234 python3 adapter/server.py
```

### systemd（Linux）

1. 复制 [`deploy/codex-local-adapter.service`](deploy/codex-local-adapter.service)，改 `User`、`WorkingDirectory`、`CODEX_LOCAL_UPSTREAM`。
2. `sudo cp ... /etc/systemd/system/`
3. `sudo systemctl daemon-reload && sudo systemctl enable --now codex-local-adapter`

### launchd（macOS）

1. 复制 [`deploy/com.codex.local-adapter.plist`](deploy/com.codex.local-adapter.plist)，改路径和上游。
2. `cp ... ~/Library/LaunchAgents/`
3. `launchctl load ~/Library/LaunchAgents/com.codex.local-adapter.plist`

### 验收

1. 上游 `/v1/responses` 可访问。
2. `curl -s http://127.0.0.1:18080/health` → `ok`。
3. 已写入用户级 `~/.codex/config.toml`。
4. `python3 -c "from openai_codex import Codex; ..."` 或 `codex exec` 能跑通一轮。

## 本仓库位置

旧的一次性脚本 `sdk-v1/codex-responses-proxy.py` 已由本目录替代（不再写死上游 IP）。
