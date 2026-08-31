#!/usr/bin/env python3
"""Smoke-check SDK RPCs that do not need a model turn.

Uses the installed `openai-codex` wheel. Requires adapter/server.py.
"""

from __future__ import annotations

import traceback

from openai_codex import Codex, Sandbox

from _common import local_codex_config, workspace_file


def brief(value: object, *, limit: int = 160) -> str:
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        text = str(dump())
    else:
        text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _ok(name: str, detail: str) -> None:
    print(f"OK    {name}: {detail}")


def _fail(name: str, exc: BaseException) -> None:
    print(f"FAIL  {name}: {type(exc).__name__}: {exc}")


def main() -> int:
    readme = workspace_file()
    failed: list[str] = []
    with Codex(config=local_codex_config()) as codex:
        checks: list[tuple[str, object]] = []

        def run(name: str, fn, *, critical: bool = True) -> None:
            try:
                detail = fn()
                _ok(name, detail)
            except Exception as exc:
                _fail(name, exc)
                if critical:
                    failed.append(name)
                    traceback.print_exc()

        meta = None

        def metadata() -> str:
            nonlocal meta
            meta = codex.metadata
            info = meta.serverInfo
            return f"{info.name} {info.version}"

        run("metadata", metadata)
        run("models", lambda: brief(codex.models()))
        run("model_provider_capabilities", lambda: brief(codex.model_provider_capabilities()))
        run("config_read", lambda: brief(codex.config_read()))
        run("config_requirements_read", lambda: brief(codex.config_requirements_read()))
        run("thread_list", lambda: brief(codex.thread_list(limit=5)))
        run("thread_loaded_list", lambda: brief(codex.thread_loaded_list()))
        run("thread_section_list", lambda: brief(codex.thread_section_list()))
        run("skills_list", lambda: brief(codex.skills_list()))
        run("mcp_status_list", lambda: brief(codex.mcp_status_list()))
        run("experimental_feature_list", lambda: brief(codex.experimental_feature_list()))
        run("fs_get_metadata", lambda: brief(codex.fs_get_metadata(str(readme))))
        run("fs_read_file", lambda: brief(codex.fs_read_file(str(readme))))
        run("fs_read_directory", lambda: brief(codex.fs_read_directory(str(readme.parent))))
        run(
            "fuzzy_file_search",
            lambda: brief(codex.fuzzy_file_search("README", roots=[str(readme.parent)])),
        )
        run(
            "thread_start",
            lambda: f"id={codex.thread_start(sandbox=Sandbox.read_only, ephemeral=True).id}",
        )
        run("account", lambda: brief(codex.account()), critical=False)

    if failed:
        print(f"\n{len(failed)} critical check(s) failed: {', '.join(failed)}")
        return 1
    print("\nruntime APIs: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
