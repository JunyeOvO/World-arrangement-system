from __future__ import annotations

import argparse
import mimetypes
import os
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse

from .api import ConsoleAPI, json_response
from .streams import sse_stream


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    token: str | None = None,
    max_sse_connections: int = 4,
) -> ThreadingHTTPServer:
    api = ConsoleAPI()
    console_token = token if token is not None else os.environ.get("WORLD_CONSOLE_TOKEN", "")
    if not _is_loopback_host(host) and not console_token:
        raise ValueError("WORLD_CONSOLE_TOKEN is required when binding World Console outside loopback")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if path == "/api/stream":
                if not _is_authorized(self.headers, console_token):
                    self._send_payload(401, "application/json", {"status": "UNAUTHORIZED"})
                    return
                if not _try_acquire_sse_slot(self.server):
                    self._send_payload(429, "application/json", {"status": "TOO_MANY_STREAMS"})
                    return
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    for chunk in sse_stream(api.service.db):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                finally:
                    _release_sse_slot(self.server)
                return
            if path.startswith("/api/"):
                if not _is_authorized(self.headers, console_token):
                    self._send_payload(401, "application/json", {"status": "UNAUTHORIZED"})
                    return
                status, content_type, payload = api.handle_get(path, parsed.query)
                self._send_payload(status, content_type, payload)
                return
            self._send_static(path)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if not _is_authorized(self.headers, console_token):
                self._send_payload(401, "application/json", {"status": "UNAUTHORIZED"})
                return
            if not _origin_allowed(self.headers):
                self._send_payload(403, "application/json", {"status": "FORBIDDEN_ORIGIN"})
                return
            length = int(self.headers.get("content-length") or "0")
            body = self.rfile.read(length)
            status, content_type, payload = api.handle_post(unquote(parsed.path), body)
            self._send_payload(status, content_type, payload)

        def _send_payload(self, status: int, content_type: str, payload) -> None:
            if isinstance(payload, str):
                data = payload.encode("utf-8")
            else:
                data = json_response(status, payload)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_static(self, path: str) -> None:
            root = Path(__file__).parent / "static"
            relative = "index.html" if path in {"", "/"} else path.lstrip("/")
            target = (root / relative).resolve()
            try:
                target.relative_to(root.resolve())
            except ValueError:
                self.send_error(403)
                return
            if not target.exists() or not target.is_file():
                target = root / "index.html"
            if not target.exists():
                self.send_error(404)
                return
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt: str, *args) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    server.active_sse_connections = 0  # type: ignore[attr-defined]
    server.max_sse_connections = max(0, int(max_sse_connections))  # type: ignore[attr-defined]
    server.sse_lock = threading.Lock()  # type: ignore[attr-defined]
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="World Web Console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default=None)
    parser.add_argument("--max-sse-connections", type=int, default=4)
    args = parser.parse_args(argv)
    server = create_server(args.host, args.port, token=args.token, max_sse_connections=args.max_sse_connections)
    print(f"World Console listening on http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


def _is_loopback_host(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


def _is_authorized(headers, token: str | None) -> bool:
    if not token:
        return True
    bearer = headers.get("Authorization", "")
    if bearer == f"Bearer {token}":
        return True
    return headers.get("X-World-Console-Token", "") == token


def _origin_allowed(headers) -> bool:
    host = headers.get("Host", "")
    origin = headers.get("Origin", "")
    if origin and urlparse(origin).netloc != host:
        return False
    referer = headers.get("Referer", "")
    if referer and urlparse(referer).netloc != host:
        return False
    return True


def _try_acquire_sse_slot(server) -> bool:
    with server.sse_lock:  # type: ignore[attr-defined]
        if server.active_sse_connections >= server.max_sse_connections:  # type: ignore[attr-defined]
            return False
        server.active_sse_connections += 1  # type: ignore[attr-defined]
        return True


def _release_sse_slot(server) -> None:
    with server.sse_lock:  # type: ignore[attr-defined]
        server.active_sse_connections = max(0, server.active_sse_connections - 1)  # type: ignore[attr-defined]


if __name__ == "__main__":
    raise SystemExit(main())
