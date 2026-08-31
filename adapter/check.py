#!/usr/bin/env python3
"""Self-check for adapter fold + settings. No network."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory

from fold import fold
from server import (
    CHAT_NOT_IMPLEMENTED,
    access_line,
    default_config_path,
    load_settings,
    parse_listen,
    rewrite_payload,
)


def _write_toml(directory: Path, text: str) -> Path:
    path = directory / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_listen() -> None:
    assert parse_listen("127.0.0.1:18080") == ("127.0.0.1", 18080)
    try:
        parse_listen("18080")
    except ValueError:
        pass
    else:
        raise AssertionError("bare port should fail")


def test_fold_merges_extra_developer() -> None:
    body = {
        "instructions": "base",
        "input": [
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "extra"}],
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hi"}],
            },
        ],
    }
    out = fold(body)
    assert "instructions" not in out
    assert out["input"][0]["role"] == "developer"
    text = out["input"][0]["content"][0]["text"]
    assert "base" in text and "extra" in text
    assert out["input"][1]["role"] == "user"


def test_fold_skips_single_system() -> None:
    body = {
        "input": [
            {
                "type": "message",
                "role": "system",
                "content": [{"type": "input_text", "text": "only"}],
            }
        ]
    }
    assert fold(body) is body


def test_rewrite_only_responses_post() -> None:
    raw = b'{"model":"qwen3","instructions":"a","input":[{"type":"message","role":"developer","content":[{"type":"input_text","text":"b"}]}]}'
    info = rewrite_payload("fold", "POST", "/v1/responses", raw)
    assert b"instructions" not in info.payload
    assert info.fold == "folded"
    assert info.model == "qwen3"
    skipped = rewrite_payload("fold", "GET", "/v1/responses", raw)
    assert skipped.payload == raw and skipped.fold == "skip"


def test_access_line_has_ops_fields_not_prompt() -> None:
    line = access_line(
        req_id="deadbeef",
        client="127.0.0.1",
        method="POST",
        path="/v1/responses",
        status=502,
        ms=12,
        fold="folded",
        model="qwen3",
        in_bytes=100,
        out_bytes=90,
        err="URLError: timed out",
    )
    assert "id=deadbeef" in line and "ms=12" in line and "fold=folded" in line
    assert "model=qwen3" in line and "err=URLError: timed out" in line
    assert "developer" not in line


def test_default_config_path_is_beside_server() -> None:
    assert default_config_path() == Path(__file__).resolve().parent / "config.toml"


def test_load_settings_from_toml() -> None:
    with TemporaryDirectory() as tmp:
        path = _write_toml(
            Path(tmp),
            'upstream = "http://127.0.0.1:1234"\n'
            'listen = "127.0.0.1:18081"\n'
            'adapt = "fold"\n'
            "timeout = 30\n",
        )
        settings = load_settings(path)
    assert settings.upstream == "http://127.0.0.1:1234"
    assert settings.host == "127.0.0.1"
    assert settings.port == 18081
    assert settings.adapt == "fold"
    assert settings.timeout == 30.0


def test_load_settings_defaults() -> None:
    with TemporaryDirectory() as tmp:
        path = _write_toml(Path(tmp), 'upstream = "http://192.0.2.1:9"\n')
        settings = load_settings(path)
    assert settings.host == "127.0.0.1"
    assert settings.port == 18080
    assert settings.adapt == "fold"
    assert settings.timeout == 600.0


def test_missing_config_exits() -> None:
    missing = Path("/tmp/codex-adapter-missing-config.toml")
    if missing.exists():
        missing.unlink()
    try:
        load_settings(missing)
    except SystemExit as exc:
        assert "config.toml" in str(exc)
    else:
        raise AssertionError("missing config must exit")


def test_missing_upstream_exits() -> None:
    with TemporaryDirectory() as tmp:
        path = _write_toml(Path(tmp), 'listen = "127.0.0.1:18080"\n')
        try:
            load_settings(path)
        except SystemExit as exc:
            assert "upstream" in str(exc)
        else:
            raise AssertionError("missing upstream must exit")


def test_env_and_argv_are_ignored() -> None:
    os.environ["CODEX_LOCAL_UPSTREAM"] = "http://env.example:1"
    os.environ["CODEX_LOCAL_LISTEN"] = "0.0.0.0:9"
    os.environ["CODEX_LOCAL_ADAPT"] = "chat"
    os.environ["CODEX_LOCAL_TIMEOUT"] = "1"
    try:
        with TemporaryDirectory() as tmp:
            path = _write_toml(Path(tmp), 'upstream = "http://127.0.0.1:1234"\n')
            settings = load_settings(path)
        assert settings.upstream == "http://127.0.0.1:1234"
        assert settings.port == 18080
        assert settings.adapt == "fold"
        assert settings.timeout == 600.0
    finally:
        for key in (
            "CODEX_LOCAL_UPSTREAM",
            "CODEX_LOCAL_LISTEN",
            "CODEX_LOCAL_ADAPT",
            "CODEX_LOCAL_TIMEOUT",
        ):
            os.environ.pop(key, None)


def test_chat_rejected() -> None:
    with TemporaryDirectory() as tmp:
        path = _write_toml(
            Path(tmp),
            'upstream = "http://127.0.0.1:1234"\nadapt = "chat"\n',
        )
        try:
            load_settings(path)
        except SystemExit as exc:
            assert "not implemented" in str(exc)
            assert "fold" in CHAT_NOT_IMPLEMENTED
        else:
            raise AssertionError("chat must exit")


if __name__ == "__main__":
    test_parse_listen()
    test_fold_merges_extra_developer()
    test_fold_skips_single_system()
    test_rewrite_only_responses_post()
    test_access_line_has_ops_fields_not_prompt()
    test_default_config_path_is_beside_server()
    test_load_settings_from_toml()
    test_load_settings_defaults()
    test_missing_config_exits()
    test_missing_upstream_exits()
    test_env_and_argv_are_ignored()
    test_chat_rejected()
    print("ok")
