#!/usr/bin/env python3
"""One short turn through the local adapter (installed openai-codex wheel)."""

from __future__ import annotations

from openai_codex import ApprovalMode, Codex, Sandbox

from _common import discover_model, local_codex_config


def main() -> int:
    model = discover_model()
    print(f"model={model}")
    with Codex(config=local_codex_config()) as codex:
        thread = codex.thread_start(
            model=model,
            model_provider="local",
            sandbox=Sandbox.read_only,
            approval_mode=ApprovalMode.deny_all,
            ephemeral=True,
        )
        print(f"thread={thread.id}")
        result = thread.run("请介绍你自己！.")
        print(f"turn={result.id}")
        print(f"status={result.status}")
        if result.error is not None:
            print(f"error={result.error}")
            return 1
        print(f"text={result.final_response!r}")
        print(f"items={len(result.items)}")
        if result.usage is not None:
            print(f"usage={result.usage}")
        if not (result.final_response or "").strip():
            print("empty final_response")
            return 1
    print("thread run: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
