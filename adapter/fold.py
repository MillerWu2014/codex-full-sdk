"""Fold extra system/developer items so Qwen-style chat templates accept Codex /v1/responses."""

from __future__ import annotations


def text_of(content) -> str | None:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    parts = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            return None
        if item.get("type") in (None, "input_text", "output_text", "text") and "text" in item:
            parts.append(item["text"])
        elif "image_url" in item or item.get("type") in {"input_image", "input_audio"}:
            return None
        else:
            return None
    return "\n".join(parts)


def fold(body: dict) -> dict:
    raw_input = body.get("input")
    if isinstance(raw_input, str):
        items = [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": raw_input}],
            }
        ]
    else:
        items = list(raw_input or [])

    parts: list[str] = []
    instructions = body.get("instructions") or ""
    if str(instructions).strip():
        parts.append(str(instructions))

    kept = []
    folded = 0
    for item in items:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        role = item.get("role")
        typ = item.get("type", "message")
        if typ in (None, "message") and role in ("developer", "system"):
            text = text_of(item.get("content"))
            if text is None:
                kept.append(item)
                continue
            folded += 1
            if text.strip():
                parts.append(text)
            continue
        kept.append(item)

    if len(parts) < 2 and folded < 2:
        return body

    out = dict(body)
    out.pop("instructions", None)
    out["input"] = [
        {
            "type": "message",
            "role": "developer",
            "content": [{"type": "input_text", "text": "\n\n".join(parts)}],
        }
    ] + kept
    return out
