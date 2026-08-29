from __future__ import annotations

import asyncio
import base64

from openai_codex.client import CodexClient, _params_dict
from openai_codex.generated.v2_all import (
    SkillsListParams,
    ThreadDeleteParams,
    ThreadRevertParams,
    ThreadStartParams,
)
from openai_codex.types import FuzzyFileSearchResponse, TurnEnvironmentParams


def test_params_dict_accepts_base_model_and_json_object() -> None:
    dumped = _params_dict(SkillsListParams(cwds=["/tmp"], force_reload=True))
    assert dumped == {"cwds": ["/tmp"], "forceReload": True}
    assert _params_dict({"searchTerm": "x"}) == {"searchTerm": "x"}
    assert _params_dict(None) == {}


def test_thread_delete_payload_uses_aliases() -> None:
    captured: dict[str, object] = {}

    def fake_request(method: str, params, *, response_model):  # noqa: ANN001
        captured["method"] = method
        captured["params"] = params
        return response_model.model_validate({})

    client = CodexClient.__new__(CodexClient)
    client.request = fake_request  # type: ignore[method-assign]
    client.thread_delete(ThreadDeleteParams(thread_id="thread-1"))
    assert captured == {"method": "thread/delete", "params": {"threadId": "thread-1"}}


def test_thread_revert_payload_uses_aliases() -> None:
    captured: dict[str, object] = {}

    def fake_request(method: str, params, *, response_model):  # noqa: ANN001
        captured["method"] = method
        captured["params"] = params
        return object()

    client = CodexClient.__new__(CodexClient)
    client.request = fake_request  # type: ignore[method-assign]
    client.thread_revert(ThreadRevertParams(thread_id="thread-1", before_turn_id="turn-9"))
    assert captured == {
        "method": "thread/revert",
        "params": {"threadId": "thread-1", "beforeTurnId": "turn-9"},
    }


def test_fuzzy_file_search_parses_files_response() -> None:
    captured: dict[str, object] = {}

    def fake_request(method: str, params, *, response_model):  # noqa: ANN001
        captured["method"] = method
        captured["params"] = params
        return response_model.model_validate(
            {
                "files": [
                    {
                        "file_name": "a.py",
                        "match_type": "file",
                        "path": "/tmp/a.py",
                        "root": "/tmp",
                        "score": 1,
                    }
                ]
            }
        )

    client = CodexClient.__new__(CodexClient)
    client.request = fake_request  # type: ignore[method-assign]
    from openai_codex.generated.v2_all import FuzzyFileSearchParams

    result = client.fuzzy_file_search(FuzzyFileSearchParams(query="a", roots=["/tmp"]))
    assert captured["method"] == "fuzzyFileSearch"
    assert captured["params"] == {"query": "a", "roots": ["/tmp"]}
    assert isinstance(result, FuzzyFileSearchResponse)
    assert result.files[0].file_name == "a.py"


def test_environments_serialize_on_thread_start() -> None:
    params = ThreadStartParams(
        environments=[TurnEnvironmentParams(cwd="/tmp", environment_id="env-1")]
    )
    dumped = _params_dict(params)
    assert dumped["environments"] == [{"cwd": "/tmp", "environmentId": "env-1"}]


def test_mcp_reload_sends_no_params() -> None:
    captured: dict[str, object] = {}

    def fake_request(method: str, params, *, response_model):  # noqa: ANN001
        captured["method"] = method
        captured["params"] = params
        return response_model.model_validate({})

    client = CodexClient.__new__(CodexClient)
    client.request = fake_request  # type: ignore[method-assign]
    client.mcp_reload()
    assert captured == {"method": "config/mcpServer/reload", "params": None}


def test_async_client_mirrors_thread_delete() -> None:
    from openai_codex.async_client import AsyncCodexClient

    async def scenario() -> str:
        client = AsyncCodexClient()
        seen: list[str] = []

        def fake_delete(params):  # noqa: ANN001
            seen.append(params.thread_id)
            from openai_codex.generated.v2_all import ThreadDeleteResponse

            return ThreadDeleteResponse()

        client._sync.thread_delete = fake_delete  # type: ignore[method-assign]
        await client.thread_delete(ThreadDeleteParams(thread_id="t1"))
        return seen[0]

    assert asyncio.run(scenario()) == "t1"


def test_base64_round_trip_helper() -> None:
    payload = base64.b64encode(b"hello").decode("ascii")
    assert base64.b64decode(payload) == b"hello"
