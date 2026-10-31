"""A free server sleeps and takes about a minute to wake. No real server is needed."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import fsr_api


class Handler(BaseHTTPRequestHandler):
    status, body, hits = 200, b"{}", 0

    def do_GET(self):
        type(self).hits += 1
        self.send_response(self.status)
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server(tmp_path, monkeypatch):
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    config = tmp_path / "api_config.json"
    config.write_text(json.dumps({"base_url": f"http://127.0.0.1:{httpd.server_port}"}), encoding="utf-8")
    monkeypatch.setattr(fsr_api, "CONFIG_FILE", config)
    Handler.hits = 0
    yield Handler
    httpd.shutdown()


@pytest.mark.parametrize("status", fsr_api.WAKING)
def test_hosting_error_page_says_the_server_is_starting(server, monkeypatch, status):
    monkeypatch.setattr(server, "status", status)
    monkeypatch.setattr(server, "body", b"<html>waking</html>")
    with pytest.raises(fsr_api.ApiError, match="starting") as error:
        fsr_api._call("GET", "/reports")
    assert error.value.status == status


def test_loading_page_with_status_200_says_the_server_is_starting(server, monkeypatch):
    monkeypatch.setattr(server, "body", b"<html>waking</html>")
    with pytest.raises(fsr_api.ApiError, match="starting"):
        fsr_api._call("GET", "/reports")


def test_api_error_message_is_kept_during_503(server, monkeypatch):
    monkeypatch.setattr(server, "status", 503)
    monkeypatch.setattr(server, "body", b'{"error": {"code": "database_unavailable", "message": "No database."}}')
    with pytest.raises(fsr_api.ApiError, match="No database"):
        fsr_api._call("GET", "/reports")


def test_keep_awake_reaches_the_server(server):
    fsr_api.keep_awake(interval=0.05)
    for _ in range(200):
        if server.hits >= 2:
            break
        threading.Event().wait(0.01)
    assert server.hits >= 2
