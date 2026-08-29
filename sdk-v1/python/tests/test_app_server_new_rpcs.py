from __future__ import annotations

import asyncio
import base64

import pytest
from app_server_harness import AppServerHarness

from openai_codex import AsyncCodex, AudioInput, Codex, ExperimentalApiDisabledError
from openai_codex.generated.v2_all import MergeStrategy, TurnEnvironmentParams
from openai_codex.types import ConfigEdit


def test_thread_delete_removes_thread(tmp_path) -> None:
    with AppServerHarness(tmp_path) as harness:
        with Codex(config=harness.app_server_config()) as codex:
            thread = codex.thread_start()
            thread_id = thread.id
            loaded = codex.thread_loaded_list()
            assert thread_id in loaded.data
            codex.thread_delete(thread_id)
            remaining = {item.id for item in codex.thread_list().data}
            assert thread_id not in remaining


def test_thread_unsubscribe_and_goal_round_trip(tmp_path) -> None:
    with AppServerHarness(tmp_path) as harness:
        with Codex(config=harness.app_server_config()) as codex:
            thread = codex.thread_start()
            unsubscribed = thread.unsubscribe()
            assert unsubscribed.status is not None
            empty = thread.goal_get()
            assert empty.goal is None


def test_thread_turns_and_items_list(tmp_path) -> None:
    with AppServerHarness(tmp_path) as harness:
        harness.responses.enqueue_assistant_message("listed", response_id="list-turn")
        with Codex(config=harness.app_server_config()) as codex:
            thread = codex.thread_start()
            thread.run("please list later")
            turns = thread.turns_list()
            assert turns.data
            items = thread.items_list()
            assert items.data


def test_thread_section_crud(tmp_path) -> None:
    with AppServerHarness(tmp_path) as harness:
        with Codex(config=harness.app_server_config()) as codex:
            created = codex.thread_section_create("SDK Section")
            listed = codex.thread_section_list()
            assert any(section.id == created.section.id for section in listed.data)
            updated = codex.thread_section_update(created.section.id, "Renamed Section")
            assert updated.section.name == "Renamed Section"
            thread = codex.thread_start()
            thread.section_move(section_id=created.section.id)
            codex.thread_section_delete(created.section.id)


def test_skills_list_returns_data(tmp_path) -> None:
    with AppServerHarness(tmp_path) as harness:
        with Codex(config=harness.app_server_config()) as codex:
            result = codex.skills_list()
            assert result.data is not None


def test_config_read_and_experimental_features(tmp_path) -> None:
    with AppServerHarness(tmp_path) as harness:
        with Codex(config=harness.app_server_config()) as codex:
            config = codex.config_read()
            assert config.config is not None
            features = codex.experimental_feature_list()
            assert features.data is not None
            capabilities = codex.model_provider_capabilities()
            assert capabilities.web_search is not None or capabilities.image_generation is not None


def test_fs_write_read_and_metadata(tmp_path) -> None:
    with AppServerHarness(tmp_path) as harness:
        target = (harness.workspace / "sdk-fs.txt").resolve()
        payload = base64.b64encode(b"sdk-fs").decode("ascii")
        with Codex(config=harness.app_server_config()) as codex:
            codex.fs_write_file(str(target), payload)
            read = codex.fs_read_file(str(target))
            meta = codex.fs_get_metadata(str(target))
            listing = codex.fs_read_directory(str(harness.workspace.resolve()))
        assert base64.b64decode(read.data_base64) == b"sdk-fs"
        assert meta.is_file is True
        assert any(entry.file_name == "sdk-fs.txt" for entry in listing.entries)


def test_mcp_reload_and_status_list(tmp_path) -> None:
    with AppServerHarness(tmp_path) as harness:
        with Codex(config=harness.app_server_config()) as codex:
            reload_result = codex.mcp_reload()
            status = codex.mcp_status_list()
        assert reload_result is not None
        assert status.data is not None


def test_environments_rejected_when_experimental_api_disabled(tmp_path) -> None:
    with AppServerHarness(tmp_path) as harness:
        config = harness.app_server_config()
        config.experimental_api = False
        with Codex(config=config) as codex:
            with pytest.raises(ExperimentalApiDisabledError):
                codex.thread_start(
                    environments=[TurnEnvironmentParams(cwd=str(tmp_path), environment_id="env-1")]
                )


def test_async_skills_list_and_thread_delete(tmp_path) -> None:
    async def scenario(harness: AppServerHarness) -> tuple[bool, bool]:
        async with AsyncCodex(config=harness.app_server_config()) as codex:
            skills = await codex.skills_list()
            thread = await codex.thread_start()
            await codex.thread_delete(thread.id)
            return bool(skills.data is not None), True

    with AppServerHarness(tmp_path) as harness:
        listed, deleted = asyncio.run(scenario(harness))
    assert listed is True
    assert deleted is True


def test_audio_input_is_accepted_by_run(tmp_path) -> None:
    with AppServerHarness(tmp_path) as harness:
        harness.responses.enqueue_assistant_message("audio ok", response_id="audio-input")
        with Codex(config=harness.app_server_config()) as codex:
            result = codex.thread_start().run([AudioInput("data:audio/wav;base64,AAAA")])
        assert result.final_response == "audio ok"


def test_config_batch_write_round_trip(tmp_path) -> None:
    with AppServerHarness(tmp_path) as harness:
        with Codex(config=harness.app_server_config()) as codex:
            written = codex.config_batch_write(
                [
                    ConfigEdit(
                        key_path="model",
                        merge_strategy=MergeStrategy.replace,
                        value="mock-model",
                    )
                ]
            )
        assert written.file_path is not None
