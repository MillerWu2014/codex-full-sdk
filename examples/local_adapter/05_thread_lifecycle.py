#!/usr/bin/env python3
"""Thread lifecycle and thread-scoped RPCs against the local adapter.

One seed turn (needed for turns/items/revert/compact/search). The rest is control-plane.
"""

from __future__ import annotations

import traceback
import uuid

from openai_codex import Codex, Sandbox, TurnHandle
from openai_codex.types import ThreadGoalStatus, ThreadMemoryMode, ThreadMetadataGitInfoUpdateParams

from _common import brief, local_codex_config, start_local_thread


def main() -> int:
    failed: list[str] = []
    with Codex(config=local_codex_config()) as codex:

        def run(name: str, fn, *, critical: bool = True) -> object:
            try:
                value = fn()
                print(f"OK    {name}: {brief(value) if not isinstance(value, str) else value}")
                return value
            except Exception as exc:
                print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
                if critical:
                    failed.append(name)
                    traceback.print_exc()
                return None

        thread = start_local_thread(codex, ephemeral=False)
        print(f"thread={thread.id}")
        seed = thread.run("Reply with the single word pong. Do not use tools.")
        print(f"seed={seed.id} status={seed.status}")
        if seed.error is not None:
            print(f"seed error: {seed.error}")
            return 1

        run("thread.read", lambda: thread.read(include_turns=True))
        run("thread.set_name", lambda: thread.set_name("local-adapter-lifecycle"))
        run(
            "thread.metadata_update",
            lambda: thread.metadata_update(
                git_info=ThreadMetadataGitInfoUpdateParams(
                    branch="main",
                    sha="deadbeef",
                    origin_url="https://example.invalid/org/repo.git",
                )
            ),
        )
        run("thread.turns_list", lambda: thread.turns_list())
        run("thread.items_list", lambda: thread.items_list())
        run("thread_loaded_list", lambda: codex.thread_loaded_list())
        run(
            "experimental.thread_search",
            lambda: codex.experimental.thread_search("pong", limit=5),
        )
        run(
            "experimental.thread_search_occurrences",
            lambda: codex.experimental.thread_search_occurrences(thread.id, "pong", limit=5),
            critical=False,
        )
        run("thread.goal_get", lambda: thread.goal_get())
        run(
            "thread.goal_set",
            lambda: thread.goal_set(objective="smoke goal", status=ThreadGoalStatus.active),
        )
        run("thread.goal_clear", lambda: thread.goal_clear())
        run(
            "thread.memory_mode_set",
            lambda: thread.memory_mode_set(ThreadMemoryMode.disabled),
        )
        run(
            "thread.settings_update",
            lambda: thread.settings_update(sandbox=Sandbox.read_only),
        )
        # queue_start only works while idle; queue_add while idle auto-starts a turn.
        busy = thread.turn("Count slowly from 1 to 80. Do not use tools.")
        print(f"busy={busy.id}")
        added = run(
            "thread.queue_add",
            lambda: thread.queue_add("queued ping", client_user_message_id=str(uuid.uuid4())),
        )
        extra = run(
            "thread.queue_add.drop",
            lambda: thread.queue_add("drop me", client_user_message_id=str(uuid.uuid4())),
        )
        run("thread.queue_list", lambda: thread.queue_list())
        qid = added.queued_submission.id if added is not None else None
        if extra is not None:
            run(
                "thread.queue_delete",
                lambda: thread.queue_delete(extra.queued_submission.id),
            )
        if qid is not None:
            run("thread.queue_update", lambda: thread.queue_update(qid, "queued pong"))
            run("thread.queue_reorder", lambda: thread.queue_reorder([qid]))
        run("busy.interrupt", lambda: busy.interrupt())
        run("busy.drain", lambda: busy.run())
        if qid is not None:
            started = run(
                "thread.queue_start",
                lambda: thread.queue_start(queued_submission_id=qid),
            )
            if started is not None and getattr(started, "turn", None) is not None:
                handle = TurnHandle(thread._client, thread.id, started.turn.id)
                run("queue_start.drain", lambda: handle.run())
            else:
                run("thread.queue_delete", lambda: thread.queue_delete(qid))
        run(
            "thread.inject_items",
            lambda: thread.inject_items(
                [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "injected"}],
                    }
                ]
            ),
            critical=False,
        )
        run("thread.compact", lambda: thread.compact())
        run("thread.revert", lambda: thread.revert(seed.id))
        created = run("thread_section_create", lambda: codex.thread_section_create("SDK Section"))
        if created is not None:
            section_id = created.section.id
            run(
                "thread.section_move",
                lambda: thread.section_move(section_id=section_id),
            )
            run(
                "thread_section_update",
                lambda: codex.thread_section_update(section_id, "Renamed Section"),
            )
            run("thread_section_delete", lambda: codex.thread_section_delete(section_id))
        run("thread.unsubscribe", lambda: thread.unsubscribe())
        run("thread_list.active", lambda: codex.thread_list(limit=20, archived=False))
        run("thread_archive", lambda: codex.thread_archive(thread.id))
        run("thread_list.archived", lambda: codex.thread_list(limit=20, archived=True))
        unarchived = run("thread_unarchive", lambda: codex.thread_unarchive(thread.id))
        if unarchived is not None:
            run("thread_resume", lambda: codex.thread_resume(unarchived.id))
            forked = run("thread_fork", lambda: codex.thread_fork(unarchived.id))
            if forked is not None:
                run("thread_delete.fork", lambda: codex.thread_delete(forked.id))
        run("thread_delete", lambda: codex.thread_delete(thread.id))

    if failed:
        print(f"\n{len(failed)} critical check(s) failed: {', '.join(failed)}")
        return 1
    print("\nthread lifecycle: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
