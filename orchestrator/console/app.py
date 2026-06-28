from __future__ import annotations

import argparse
import mimetypes
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse

from .api import ConsoleAPI, json_response
from .streams import sse_stream


def create_server(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    api = ConsoleAPI()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if path == "/api/stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                for chunk in sse_stream(api.service.db):
                    self.wfile.write(chunk)
                    self.wfile.flush()
                return
            if path.startswith("/api/"):
                status, content_type, payload = api.handle_get(path, parsed.query)
                self._send_payload(status, content_type, payload)
                return
            self._send_static(path)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
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

    return ThreadingHTTPServer((host, port), Handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="World Web Console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    server = create_server(args.host, args.port)
    print(f"World Console listening on http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
