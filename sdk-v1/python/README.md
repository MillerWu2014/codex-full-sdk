# OpenAI Codex Python SDK

Build Python applications that start Codex threads, run turns, stream progress,
and control workspace access.

## Install

Install the SDK:

```bash
pip install openai-codex
```

## Quickstart

The SDK reuses your existing Codex authentication when one is already
available:

```python
from openai_codex import Codex

with Codex() as codex:
    thread = codex.thread_start()
    result = thread.run("Explain this repository in three bullets.")
    print(result.final_response)
```

`thread.run(...)` returns a `TurnResult` containing the final response,
collected items, and token usage.

## Dependencies

```text
your app
  →  openai-codex          (this package: Python API)
  →  openai-codex-cli-bin  (pinned Codex binary; started by Codex())
  →  ~/.codex/config.toml  (user-level provider + model; not a pip extra)
  →  model endpoint        (OpenAI or a local /v1/responses server)
```

`pip install openai-codex` pulls `openai-codex-cli-bin` automatically. It does
**not** install or start a local-model adapter.

Codex talks **only** `POST /v1/responses`. Official OpenAI and any backend that
already accepts that API need no extra process: set `model` / `model_provider`
in **user-level** `~/.codex/config.toml` (project `.codex/config.toml` cannot
override providers).

If the local stack (Ollama, vLLM, LM Studio, SGLang, …) has `/v1/responses`
but rejects Codex’s multiple `system`/`developer` items (typical Qwen), run
the optional process in this repo’s [`adapter/`](../../adapter/README.md) and
point `base_url` at `http://127.0.0.1:18080/v1`. The SDK does not launch it.
`adapt = "chat"` in `adapter/config.toml` (Responses → Chat Completions) is not implemented yet.

## Authentication

Existing Codex authentication is reused automatically. To start ChatGPT
browser login explicitly:

```python
from openai_codex import Codex

with Codex() as codex:
    login = codex.login_chatgpt()
    print(login.auth_url)
    print(login.wait().success)
```

For device-code login:

```python
with Codex() as codex:
    login = codex.login_chatgpt_device_code()
    print(login.verification_url, login.user_code)
    login.wait()
```

For API-key login:

```python
with Codex() as codex:
    codex.login_api_key("sk-...")
```

## Built-In Help

Use Python's standard `help(openai_codex)`, `help(Codex)`, or
`python -m pydoc openai_codex` documentation tools.

## Documentation

- [Getting started](docs/getting-started.md)
- [API reference](docs/api-reference.md)
- [FAQ](docs/faq.md)
- [Examples](examples/README.md)

## SDK Artifact Generation Notes

- `scripts/update_sdk_artifacts.py generate-types` prefers a runtime binary, then
  falls back to the checked-in precomputed experimental schema bundle.
- The fallback path requires a system `zstd` CLI (Python 3.10-3.13 supported);
  no extra Python dependency is required.

The package is licensed under the
[repository Apache License 2.0](https://github.com/openai/codex/blob/main/LICENSE).
