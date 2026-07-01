import http.client
import threading

import pytest

from orchestrator.console.app import create_server


def _request(server, method: str, path: str, *, body: bytes = b"", headers: dict[str, str] | None = None):
    host, port = server.server_address
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, data


def test_console_refuses_non_loopback_bind_without_token():
    with pytest.raises(ValueError):
        create_server("0.0.0.0", 0, token="")


def test_console_api_requires_token_when_configured():
    server = create_server("127.0.0.1", 0, token="secret-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        unauthorized, _ = _request(server, "GET", "/api/console/snapshot")
        authorized, _ = _request(
            server,
            "GET",
            "/api/console/snapshot",
            headers={"Authorization": "Bearer secret-token"},
        )
    finally:
        server.shutdown()
        server.server_close()

    assert unauthorized == 401
    assert authorized == 200


def test_console_post_rejects_cross_origin_request():
    server = create_server("127.0.0.1", 0, token="secret-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _ = _request(
            server,
            "POST",
            "/api/tasks/missing/cancel",
            body=b"{}",
            headers={
                "Authorization": "Bearer secret-token",
                "Content-Type": "application/json",
                "Origin": "http://evil.example",
            },
        )
    finally:
        server.shutdown()
        server.server_close()

    assert status == 403


def test_console_sse_connection_cap_returns_429():
    server = create_server("127.0.0.1", 0, max_sse_connections=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _ = _request(server, "GET", "/api/stream")
    finally:
        server.shutdown()
        server.server_close()

    assert status == 429
