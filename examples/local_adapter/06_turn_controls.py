#!/usr/bin/env python3
"""Turn control: steer during stream, interrupt + TurnHandle.run."""

from __future__ import annotations

from openai_codex import Codex

from _common import discover_model, local_codex_config, start_local_thread


def main() -> int:
    model = discover_model()
    print(f"model={model}")
    with Codex(config=local_codex_config()) as codex:
        thread = start_local_thread(codex, ephemeral=True)
        print(f"thread={thread.id}")

        steer_turn = thread.turn(
            "Count from 1 to 40 with commas, then one short sentence. Do not use tools."
        )
        print(f"steer.turn={steer_turn.id}")
        steered = False
        steer_status = None
        steer_events = 0
        for event in steer_turn.stream():
            steer_events += 1
            if event.method == "turn/started" and not steered:
                ack = steer_turn.steer("Keep it brief and stop after 5 numbers.")
                print(f"steer.ack={ack}")
                steered = True
            if event.method == "turn/completed":
                steer_status = event.payload.turn.status.value
        print(f"steer.status={steer_status} events={steer_events} steered={steered}")
        if steer_status is None:
            print("steer: missing turn/completed")
            return 1
        if not steered:
            print("steer: turn/started never arrived")
            return 1

        interrupt_turn = thread.turn(
            "Count from 1 to 200 with commas, then one short sentence. Do not use tools."
        )
        print(f"interrupt.turn={interrupt_turn.id}")
        interrupt_ack = interrupt_turn.interrupt()
        print(f"interrupt.ack={interrupt_ack}")
        interrupted = interrupt_turn.run()
        print(f"interrupt.status={interrupted.status}")

    print("turn controls: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
