from __future__ import annotations

import asyncio
import uuid

import pytest
from app_server_harness import AppServerHarness
from app_server_helpers import streaming_response

from openai_codex import AsyncCodex, Codex, ExperimentalApiDisabledError
from openai_codex.generated.v2_all import ProjectRoot, ThreadMemoryMode


def test_experimental_namespace_requires_opt_in(tmp_path) -> None:
    with AppServerHarness(tmp_path) as harness:
        config = harness.app_server_config()
        config.experimental_api = False
        with Codex(config=config) as codex:
            with pytest.raises(ExperimentalApiDisabledError):
                codex.experimental.project_list()
            with pytest.raises(ExperimentalApiDisabledError):
                thread = codex.thread_start()
                thread.queue_list()


def test_project_list_and_create(tmp_path) -> None:
    with AppServerHarness(tmp_path) as harness:
        with Codex(config=harness.app_server_config()) as codex:
            listed = codex.experimental.project_list()
            created = codex.experimental.project_create(
                "SDK Project",
                [ProjectRoot(path=str(harness.workspace.resolve()))],
                idempotency_key=str(uuid.uuid4()),
            )
            read = codex.experimental.project_read(created.project.id)
        assert listed.data is not None
        assert read.project.id == created.project.id


def test_thread_queue_add_and_list(tmp_path) -> None:
    with AppServerHarness(tmp_path) as harness:
        harness.responses.enqueue_sse(
            streaming_response("queue-block", "msg-queue", ["blocking"]),
            delay_between_events_s=0.3,
        )
        with Codex(config=harness.app_server_config()) as codex:
            thread = codex.thread_start()
            turn = thread.turn("keep this turn busy")
            harness.responses.wait_for_requests(1)
            added = thread.queue_add("queued later", client_user_message_id=str(uuid.uuid4()))
            listed = thread.queue_list()
            turn.interrupt()
        assert added.queued_submission.id
        assert any(item.id == added.queued_submission.id for item in listed.data)


def test_thread_memory_mode_and_settings(tmp_path) -> None:
    with AppServerHarness(tmp_path) as harness:
        with Codex(config=harness.app_server_config()) as codex:
            thread = codex.thread_start()
            thread.memory_mode_set(ThreadMemoryMode.disabled)
            thread.settings_update(model="mock-model")
            reset = codex.experimental.memory_reset()
        assert reset is not None


def test_thread_search_and_collaboration_modes(tmp_path) -> None:
    with AppServerHarness(tmp_path) as harness:
        harness.responses.enqueue_assistant_message("searchable", response_id="search-1")
        with Codex(config=harness.app_server_config()) as codex:
            thread = codex.thread_start()
            thread.run("searchable needle")
            results = codex.experimental.thread_search("needle")
            modes = codex.experimental.collaboration_mode_list()
        assert results.data is not None
        assert modes.data is not None


def test_async_experimental_project_list(tmp_path) -> None:
    async def scenario(harness: AppServerHarness) -> int:
        async with AsyncCodex(config=harness.app_server_config()) as codex:
            listed = await codex.experimental.project_list()
            return len(listed.data)

    with AppServerHarness(tmp_path) as harness:
        count = asyncio.run(scenario(harness))
    assert count >= 0
