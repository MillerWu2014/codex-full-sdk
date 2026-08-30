#!/usr/bin/env python3
"""Self-check for adapter fold + settings. No network."""

from __future__ import annotations

from fold import fold
from server import (
    CHAT_NOT_IMPLEMENTED,
    access_line,
    load_settings,
    parse_listen,
    rewrite_payload,
)


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


def test_chat_rejected() -> None:
    try:
        load_settings(["--upstream", "http://127.0.0.1:1234", "--adapt", "chat"])
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
    test_chat_rejected()
    print("ok")
