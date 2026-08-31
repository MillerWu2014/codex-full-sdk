#!/usr/bin/env python3
"""Stream one turn and print a few event types."""

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
        turn = thread.turn("请全面的介绍人工智能.")
        started = False
        completed = None
        event_count = 0
        chunks: list[str] = []
        for event in turn.stream():
            event_count += 1
            if event.method == "turn/started":
                started = True
                print("event turn/started")
            elif event.method == "item/agentMessage/delta":
                delta = getattr(event.payload, "delta", None) or ""
                if delta:
                    chunks.append(delta)
                    print(delta, end="", flush=True)
            elif event.method == "turn/completed":
                completed = event.payload.turn.status.value
        if chunks:
            print()
        print(f"events={event_count} started={started} completed={completed}")
        if not started or completed is None:
            return 1
    print("thread stream: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
