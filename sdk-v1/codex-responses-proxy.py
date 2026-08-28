#!/usr/bin/env python3
"""Merge extra system/developer items so Qwen chat templates accept Codex /v1/responses."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

UPSTREAM = "http://192.168.101.232:1234"
LISTEN = ("127.0.0.1", 18080)
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
       "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length"}


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
        items = [{"type": "message", "role": "user",
                  "content": [{"type": "input_text", "text": raw_input}]}]
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

    body.pop("instructions", None)
    body["input"] = [{
        "type": "message",
        "role": "developer",
        "content": [{"type": "input_text", "text": "\n\n".join(parts)}],
    }] + kept
    return body


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {fmt % args}")

    def _proxy(self):
        length = int(self.headers.get("Content-Length") or 0)
        payload = self.rfile.read(length) if length else b""
        if self.command == "POST" and self.path.rstrip("/").endswith("/responses"):
            try:
                payload = json.dumps(fold(json.loads(payload or b"{}"))).encode()
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        headers["Content-Length"] = str(len(payload))
        req = Request(
            url=UPSTREAM + self.path,
            data=payload if self.command != "GET" else None,
            headers=headers,
            method=self.command,
        )
        try:
            with urlopen(req, timeout=600) as resp:
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() not in HOP:
                        self.send_header(k, v)
                self.end_headers()
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except Exception as exc:
            msg = str(exc).encode()
            self.send_response(502)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    def do_GET(self):
        self._proxy()

    def do_POST(self):
        self._proxy()


if __name__ == "__main__":
    httpd = ThreadingHTTPServer(LISTEN, Handler)
    print(f"proxy {LISTEN[0]}:{LISTEN[1]} -> {UPSTREAM}")
    httpd.serve_forever()
