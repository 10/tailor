from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread

import pytest

from tailor.rule_loader import RuleLoader
from tailor.traffic_store import TrafficStore
from tailor.web.server import Handler


@pytest.fixture
def dashboard(tmp_path):
    class TestHandler(Handler):
        loader = RuleLoader(tmp_path / "rules", tmp_path / "state.json")
        store = TrafficStore(tmp_path / "history.db")
        proxy_addr = "127.0.0.1:47080"

    with ThreadingHTTPServer(("127.0.0.1", 0), TestHandler) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()

        def request(path, method="GET", headers=None):
            conn = HTTPConnection(*server.server_address, timeout=5)
            try:
                conn.request(method, path, headers=headers or {})
                response = conn.getresponse()
                return response.status, response.headers, response.read().decode()
            finally:
                conn.close()

        try:
            yield request, TestHandler.store
        finally:
            server.shutdown()
            thread.join()


def test_private_pages_are_not_cached(dashboard):
    request, _ = dashboard
    for path in ("/", "/rules/new", "/traffic", "/traffic/1"):
        _, headers, _ = request(path)
        assert headers["Cache-Control"] == "no-store"
    assert request("/static/style.css")[1]["Cache-Control"] != "no-store"


def test_dashboard_rejects_foreign_form_submissions(dashboard):
    request, _ = dashboard
    # Exercise the dispatcher without performing any rule action.
    for headers in (
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
        {"Origin": "http://another.example"},
        {"Origin": "null"},
    ):
        assert request("/missing", "POST", headers)[0] == 403
    assert request("/rules/reload", "POST", {"Sec-Fetch-Site": "same-origin"})[0] == 303
    assert request("/rules/reload", "POST")[0] == 303
