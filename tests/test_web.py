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


def test_traffic_filters_search_the_retained_history(dashboard):
    request, store = dashboard
    record = dict(ts=0, method="GET", host="fixture.test", path="/old-match", status=200,
                  matched=["docs"], req_headers={}, req_body="private request",
                  resp_headers={}, resp_body="private response", error="")
    store.add(record)
    for i in range(201):
        store.add({**record, "path": f"/newer/{i}", "matched": []})
    store.add({**record, "path": "/other-rule", "matched": ["docs-extra"]})

    all_rows = request("/traffic")[2]
    assert all_rows.count('class="clickable"') == 200
    assert "/old-match" not in all_rows
    matches = request("/traffic?matched=1")[2]
    assert matches.index("/other-rule") < matches.index("/old-match")
    by_rule = request("/traffic?rule=docs")[2]
    assert "/old-match" in by_rule and "/other-rule" not in by_rule
    assert "private request" not in by_rule
    assert "private request" in request("/traffic/1")[2]


def test_invalid_traffic_links_render_a_missing_entry(dashboard):
    request, _ = dashboard
    for suffix in ("", "missing", "extra/1", "9223372036854775808", "0"):
        status, _, page = request(f"/traffic/{suffix}")
        assert status == 404
        assert "Entry not found" in page
