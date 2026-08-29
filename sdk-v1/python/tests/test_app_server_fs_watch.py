from __future__ import annotations

import threading
import time

import pytest
from app_server_harness import AppServerHarness

from openai_codex import Codex, ExperimentalApiDisabledError
from openai_codex.generated.v2_all import FsChangedNotification


def test_fs_watch_requires_experimental_api(tmp_path) -> None:
    with AppServerHarness(tmp_path) as harness:
        config = harness.app_server_config()
        config.experimental_api = False
        with Codex(config=config) as codex:
            with pytest.raises(ExperimentalApiDisabledError):
                codex.fs_watch(str(harness.workspace.resolve()), watch_id="watch-1")


def test_fs_watch_receives_change_and_close(tmp_path) -> None:
    watched = (tmp_path / "watched.txt").resolve()
    watched.write_text("before")
    with AppServerHarness(tmp_path) as harness:
        with Codex(config=harness.app_server_config()) as codex:
            handle = codex.fs_watch(str(watched), watch_id="sdk-watch")
            try:

                def mutate() -> None:
                    time.sleep(0.2)
                    watched.write_text("after")

                worker = threading.Thread(target=mutate, daemon=True)
                worker.start()
                deadline = time.time() + 8
                events: list[FsChangedNotification] = []
                while time.time() < deadline and not events:
                    event = next(handle, None)
                    if event is None:
                        break
                    events.append(event)
                worker.join(timeout=2)
            finally:
                handle.close()
    assert events
    assert any(str(watched) in [str(path.root) for path in event.changed_paths] for event in events)


def test_fs_watch_transport_failure_wakes_consumer() -> None:
    from openai_codex._message_router import MessageRouter
    from openai_codex.errors import TransportClosedError

    router = MessageRouter()
    router.register_watch("watch-1")
    router.fail_all(TransportClosedError("closed"))
    with pytest.raises(TransportClosedError):
        router.next_watch_notification("watch-1")


def test_fs_watch_registers_before_request(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    order: list[str] = []

    with AppServerHarness(tmp_path) as harness:
        with Codex(config=harness.app_server_config()) as codex:
            original_register = codex._client.register_watch_notifications
            original_watch = codex._client.fs_watch

            def register(watch_id: str) -> None:
                order.append(f"register:{watch_id}")
                original_register(watch_id)

            def watch(params):  # noqa: ANN001
                order.append("request")
                return original_watch(params)

            monkeypatch.setattr(codex._client, "register_watch_notifications", register)
            monkeypatch.setattr(codex._client, "fs_watch", watch)
            handle = codex.fs_watch(str(harness.workspace.resolve()), watch_id="ordered")
            handle.close()
    assert order[:2] == ["register:ordered", "request"]
