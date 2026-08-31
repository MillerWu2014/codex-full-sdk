"""Shared setup for installed-wheel examples against the local Responses adapter.

Uses an isolated CODEX_HOME so these scripts do not read or rewrite
~/.codex/config.toml (that file may belong to the Codex desktop app).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from openai_codex import ApprovalMode, CodexConfig, Sandbox

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = Path(__file__).resolve().parent
CODEX_HOME = EXAMPLES_DIR / ".codex-home"
DEFAULT_ADAPTER = "http://127.0.0.1:18080"
DEFAULT_UPSTREAM = "http://127.0.0.1:1234"


def adapter_base_url() -> str:
    return os.environ.get("CODEX_ADAPTER_URL", DEFAULT_ADAPTER).rstrip("/")


def require_adapter() -> None:
    url = adapter_base_url() + "/health"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            body = resp.read().decode().strip()
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Adapter is not reachable at {url} ({exc}).\n"
            "Start it first:\n"
            "  python3 adapter/server.py"
        ) from exc
    if body != "ok":
        raise SystemExit(f"Adapter /health returned {body!r}, expected 'ok'.")


def discover_model() -> str:
    explicit = os.environ.get("CODEX_LOCAL_MODEL", "").strip()
    if explicit:
        return explicit
    for origin in (adapter_base_url(), os.environ.get("CODEX_LOCAL_UPSTREAM", DEFAULT_UPSTREAM)):
        try:
            with urllib.request.urlopen(origin.rstrip("/") + "/v1/models", timeout=5) as resp:
                payload = json.loads(resp.read().decode())
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError):
            continue
        ids = [
            item.get("id")
            for item in payload.get("data", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        chat = [mid for mid in ids if mid and "embed" not in mid.lower()]
        if chat:
            return chat[0]
    return "qwen3"


def local_codex_config(*, cwd: Path | None = None) -> CodexConfig:
    """Write a throwaway CODEX_HOME that points Codex at the adapter."""
    require_adapter()
    model = discover_model()
    adapter_v1 = adapter_base_url() + "/v1"
    CODEX_HOME.mkdir(parents=True, exist_ok=True)
    (CODEX_HOME / "config.toml").write_text(
        "\n".join(
            [
                f'model = "{model}"',
                'model_provider = "local"',
                "",
                "[model_providers.local]",
                'name = "local"',
                f'base_url = "{adapter_v1}"',
                'wire_api = "responses"',
                "requires_openai_auth = false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["CODEX_HOME"] = str(CODEX_HOME)
    return CodexConfig(cwd=str(cwd or REPO_ROOT), env=env)


def workspace_file() -> Path:
    return (REPO_ROOT / "README.md").resolve()


def scratch_dir() -> Path:
    path = EXAMPLES_DIR / ".scratch"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def start_local_thread(codex, *, ephemeral: bool = False, sandbox: Sandbox = Sandbox.read_only):
    return codex.thread_start(
        model=discover_model(),
        model_provider="local",
        sandbox=sandbox,
        approval_mode=ApprovalMode.deny_all,
        ephemeral=ephemeral,
    )


def brief(value: object, *, limit: int = 160) -> str:
    dump = getattr(value, "model_dump", None)
    text = str(dump()) if callable(dump) else str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."
