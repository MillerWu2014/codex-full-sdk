#!/usr/bin/env python3
"""AsyncCodex parity for a short local turn."""

from __future__ import annotations

import asyncio

from openai_codex import ApprovalMode, AsyncCodex, Sandbox

from _common import discover_model, local_codex_config


async def main() -> int:
    model = discover_model()
    print(f"model={model}")
    async with AsyncCodex(config=local_codex_config()) as codex:
        info = codex.metadata.serverInfo
        print(f"server={info.name} {info.version}")
        thread = await codex.thread_start(
            model=model,
            model_provider="local",
            sandbox=Sandbox.read_only,
            approval_mode=ApprovalMode.deny_all,
            ephemeral=True,
        )
        result = await thread.run("请深度介绍LLM模型.")
        print(f"status={result.status}")
        print(f"text={result.final_response!r}")
        if result.error is not None or not (result.final_response or "").strip():
            return 1
    print("async run: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
