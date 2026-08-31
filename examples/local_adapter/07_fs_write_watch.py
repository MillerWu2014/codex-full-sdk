#!/usr/bin/env python3
"""FS write/copy/remove plus fs/watch and fs/unwatch. No model turn."""

from __future__ import annotations

import base64
import threading
import time

from openai_codex import Codex

from _common import brief, local_codex_config, scratch_dir


def main() -> int:
    root = scratch_dir()
    nested = (root / "nested").resolve()
    nested_copy = (root / "nested-copy").resolve()
    src = (root / "sdk-fs.txt").resolve()
    copied = (root / "nested" / "sdk-fs-copy.txt").resolve()
    watched = (root / "watched.txt").resolve()
    watched.write_text("before", encoding="utf-8")
    payload = base64.b64encode(b"sdk-fs").decode("ascii")
    after = base64.b64encode(b"after").decode("ascii")
    failed: list[str] = []

    with Codex(config=local_codex_config(cwd=root)) as codex:

        def run(name: str, fn) -> object:
            try:
                value = fn()
                print(f"OK    {name}: {brief(value) if not isinstance(value, str) else value}")
                return value
            except Exception as exc:
                print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
                failed.append(name)
                return None

        run("fs_create_directory", lambda: codex.fs_create_directory(str(nested), recursive=True))
        run("fs_write_file", lambda: codex.fs_write_file(str(src), payload))
        run("fs_read_file", lambda: codex.fs_read_file(str(src)))
        run("fs_get_metadata", lambda: codex.fs_get_metadata(str(src)))
        run("fs_copy", lambda: codex.fs_copy(str(src), str(copied)))
        run("fs_read_directory", lambda: codex.fs_read_directory(str(nested)))
        run(
            "fs_copy.recursive",
            lambda: codex.fs_copy(str(nested), str(nested_copy), recursive=True),
        )
        run("fs_read_directory.copy", lambda: codex.fs_read_directory(str(nested_copy)))

        try:
            with codex.fs_watch(str(watched), watch_id="local-adapter-watch") as handle:
                print(f"OK    fs_watch: watch_id={handle.watch_id}")

                def mutate() -> None:
                    time.sleep(0.2)
                    codex.fs_write_file(str(watched), after)

                worker = threading.Thread(target=mutate, daemon=True)
                worker.start()
                deadline = time.time() + 8
                events = []
                while time.time() < deadline and not events:
                    event = next(handle, None)
                    if event is None:
                        break
                    events.append(event)
                worker.join(timeout=2)
                if events:
                    print(f"OK    fs_watch.event: {brief(events[0])}")
                else:
                    print("FAIL  fs_watch.event: no fs/changed before timeout")
                    failed.append("fs_watch.event")
        except Exception as exc:
            print(f"FAIL  fs_watch: {type(exc).__name__}: {exc}")
            failed.append("fs_watch")
        else:
            print("OK    fs_unwatch: handle context exit")

        run("fs_remove.copy", lambda: codex.fs_remove(str(copied), force=True))
        run("fs_remove.src", lambda: codex.fs_remove(str(src), force=True))
        run("fs_remove.nested", lambda: codex.fs_remove(str(nested), force=True, recursive=True))
        run(
            "fs_remove.nested_copy",
            lambda: codex.fs_remove(str(nested_copy), force=True, recursive=True),
        )
        run("fs_remove.watched", lambda: codex.fs_remove(str(watched), force=True))

    if failed:
        print(f"\n{len(failed)} check(s) failed: {', '.join(failed)}")
        return 1
    print("\nfs write/watch: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
