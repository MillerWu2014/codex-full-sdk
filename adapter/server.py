#!/usr/bin/env python3
"""Local Responses adapter for Codex. Does not modify the Codex CLI or SDK.

Codex only speaks POST /v1/responses. Point ~/.codex/config.toml at this
process when the real backend needs a request rewrite (fold) before it can
accept Codex traffic.

    CODEX_LOCAL_UPSTREAM=http://127.0.0.1:1234 \\
    CODEX_LOCAL_LISTEN=127.0.0.1:18080 \\
    CODEX_LOCAL_ADAPT=fold \\
    python3 adapter/server.py
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fold import fold

HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}

CHAT_NOT_IMPLEMENTED = (
    "ADAPT=chat is not implemented. Codex only speaks /v1/responses; "
    "translating that into /v1/chat/completions is a later increment.\n"
    "Use a backend that already exposes /v1/responses, or ADAPT=fold if it "
    "does but rejects multiple system/developer messages (typical Qwen)."
)


LOG = logging.getLogger("codex.adapter")


@dataclass(frozen=True)
class Settings:
    upstream: str
    host: str
    port: int
    adapt: str
    timeout: float


@dataclass(frozen=True)
class RewriteInfo:
    payload: bytes
    fold: str
    model: str | None
    in_bytes: int
    out_bytes: int


def parse_listen(value: str) -> tuple[str, int]:
    text = value.strip()
    if not text or ":" not in text:
        raise ValueError(f"LISTEN must be host:port, got {value!r}")
    host, _, port_s = text.rpartition(":")
    if not host:
        raise ValueError(f"LISTEN missing host: {value!r}")
    try:
        port = int(port_s)
    except ValueError as exc:
        raise ValueError(f"LISTEN port is not an integer: {value!r}") from exc
    if not (1 <= port <= 65535):
        raise ValueError(f"LISTEN port out of range: {port}")
    return host, port


def load_settings(argv: list[str] | None = None) -> Settings:
    parser = argparse.ArgumentParser(description="Codex local Responses adapter.")
    parser.add_argument("--upstream", help="Upstream origin, no path. Env: CODEX_LOCAL_UPSTREAM.")
    parser.add_argument(
        "--listen",
        help="host:port to bind. Env: CODEX_LOCAL_LISTEN. Default 127.0.0.1:18080.",
    )
    parser.add_argument(
        "--adapt",
        choices=("fold", "chat"),
        help="Rewrite mode. Env: CODEX_LOCAL_ADAPT. Default fold.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        help="Upstream timeout seconds. Env: CODEX_LOCAL_TIMEOUT. Default 600.",
    )
    args = parser.parse_args(argv)

    upstream = (args.upstream or os.environ.get("CODEX_LOCAL_UPSTREAM") or "").rstrip("/")
    if not upstream:
        raise SystemExit(
            "Set CODEX_LOCAL_UPSTREAM or --upstream to the local model origin, "
            "for example http://127.0.0.1:1234 (no /v1 suffix required if the "
            "client already requests /v1/responses)."
        )
    listen = args.listen or os.environ.get("CODEX_LOCAL_LISTEN") or "127.0.0.1:18080"
    try:
        host, port = parse_listen(listen)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    adapt = (args.adapt or os.environ.get("CODEX_LOCAL_ADAPT") or "fold").strip().lower()
    if adapt == "chat":
        raise SystemExit(CHAT_NOT_IMPLEMENTED)
    if adapt != "fold":
        raise SystemExit(f"Unknown ADAPT={adapt!r}. Supported: fold.")
    timeout_s = args.timeout
    if timeout_s is None:
        timeout_s = float(os.environ.get("CODEX_LOCAL_TIMEOUT") or "600")
    return Settings(upstream=upstream, host=host, port=port, adapt=adapt, timeout=timeout_s)


def _token(value: object, *, limit: int = 80) -> str | None:
    if not isinstance(value, str):
        return None
    text = "".join(value.split())
    if not text:
        return None
    return text[:limit]


def _one_line(exc: BaseException, *, limit: int = 200) -> str:
    text = f"{type(exc).__name__}: {exc}".replace("\r", " ").replace("\n", " ")
    return text[:limit]


def rewrite_payload(adapt: str, method: str, path: str, payload: bytes) -> RewriteInfo:
    in_bytes = len(payload)
    if adapt != "fold" or method != "POST" or not path.rstrip("/").endswith("/responses"):
        return RewriteInfo(payload, "skip", None, in_bytes, in_bytes)
    try:
        parsed = json.loads(payload or b"{}")
    except (json.JSONDecodeError, TypeError, ValueError):
        return RewriteInfo(payload, "invalid", None, in_bytes, in_bytes)
    if not isinstance(parsed, dict):
        return RewriteInfo(payload, "invalid", None, in_bytes, in_bytes)
    model = _token(parsed.get("model"))
    rewritten = fold(parsed)
    out = json.dumps(rewritten).encode()
    fold_state = "folded" if rewritten is not parsed else "unchanged"
    return RewriteInfo(out, fold_state, model, in_bytes, len(out))


def access_line(
    *,
    req_id: str,
    client: str,
    method: str,
    path: str,
    status: int,
    ms: int,
    fold: str,
    model: str | None,
    in_bytes: int,
    out_bytes: int,
    upstream_status: int | None = None,
    err: str | None = None,
) -> str:
    parts = [
        f"id={req_id}",
        f"client={client}",
        f"{method} {path}",
        f"status={status}",
        f"ms={ms}",
        f"fold={fold}",
        f"in={in_bytes}",
        f"out={out_bytes}",
    ]
    if model:
        parts.append(f"model={model}")
    if upstream_status is not None and upstream_status != status:
        parts.append(f"upstream_status={upstream_status}")
    if err:
        parts.append(f"err={err}")
    return " ".join(parts)


def make_handler(settings: Settings) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def log_request(self, code: object = "-", size: object = "-") -> None:
            return

        def do_GET(self) -> None:
            if self.path.rstrip("/") in {"/health", "/healthz"}:
                body = b"ok\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._proxy()

        def do_POST(self) -> None:
            self._proxy()

        def _proxy(self) -> None:
            started = time.perf_counter()
            req_id = uuid.uuid4().hex[:8]
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            info = rewrite_payload(settings.adapt, self.command, self.path, raw)
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
            headers["Content-Length"] = str(len(info.payload))
            status = 502
            upstream_status: int | None = None
            err: str | None = None
            try:
                with urlopen(
                    Request(
                        url=settings.upstream + self.path,
                        data=info.payload if self.command != "GET" else None,
                        headers=headers,
                        method=self.command,
                    ),
                    timeout=settings.timeout,
                ) as resp:
                    status = resp.status
                    upstream_status = resp.status
                    self.send_response(resp.status)
                    for key, value in resp.headers.items():
                        if key.lower() not in HOP:
                            self.send_header(key, value)
                    self.end_headers()
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
            except Exception as exc:
                status = 502
                err = _one_line(exc)
                msg = err.encode()
                self.send_response(502)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)
            ms = int((time.perf_counter() - started) * 1000)
            line = access_line(
                req_id=req_id,
                client=self.address_string(),
                method=self.command,
                path=self.path,
                status=status,
                ms=ms,
                fold=info.fold,
                model=info.model,
                in_bytes=info.in_bytes,
                out_bytes=info.out_bytes,
                upstream_status=upstream_status,
                err=err,
            )
            if err:
                LOG.error(line)
            else:
                LOG.info(line)

    return Handler


def configure_logging() -> None:
    if LOG.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%S"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    LOG.propagate = False


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    settings = load_settings(argv)
    httpd = ThreadingHTTPServer((settings.host, settings.port), make_handler(settings))
    LOG.info(
        "listen=%s:%s upstream=%s adapt=%s timeout=%s",
        settings.host,
        settings.port,
        settings.upstream,
        settings.adapt,
        settings.timeout,
    )
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
