"""Core behavior: rules load, toggle, hot-reload, and actually modify flows,
and a broken rule doesn't take everything down."""

import json

import pytest
from mitmproxy.test import tflow, tutils

from tailor.proxy import TailorAddon
from tailor.rule_loader import NEW_RULE_TEMPLATE, RuleLoader
from tailor.traffic_store import TrafficStore

RULE_SRC = '''
from tailor.rule_api import Rule
add = Rule(
    id="add_header",
    match_request=lambda ctx: True,
    modify_request=lambda ctx: ctx.request.headers.__setitem__("X-Test", "yes"),
)
flip = Rule(
    id="flip",
    match_response=lambda ctx: ctx.path == "/cfg",
    modify_response=lambda ctx: ctx.response.set_json({"on": True}),
)
'''

BROKEN_SRC = '''
from tailor.rule_api import Rule
boom = Rule(id="boom", match_request=lambda ctx: 1 / 0)
'''


def _flow():
    return tflow.tflow(
        req=tutils.treq(host="api.example.com", path="/cfg"),
        resp=tutils.tresp(content=b'{"on": false}'),
    )


def _setup(tmp_path, src=RULE_SRC):
    (tmp_path / "r.py").write_text(src)
    loader = RuleLoader(rules_dir=tmp_path, state_path=tmp_path / "state.json")
    store = TrafficStore(tmp_path / "t.db")
    return loader, store, TailorAddon(loader, store)


def test_request_and_response_modified(tmp_path):
    loader, store, addon = _setup(tmp_path)
    f = _flow()
    addon.request(f)
    assert f.request.headers["X-Test"] == "yes"
    addon.response(f)
    assert json.loads(f.response.get_text()) == {"on": True}
    assert set(store.recent()[0]["matched"]) == {"add_header", "flip"}


def test_disable_rule(tmp_path):
    loader, store, addon = _setup(tmp_path)
    loader.set_enabled("add_header", False)
    f = _flow()
    addon.request(f)
    assert "X-Test" not in f.request.headers


def test_broken_rule_does_not_crash(tmp_path):
    loader, store, addon = _setup(tmp_path, BROKEN_SRC)
    f = _flow()
    addon.request(f)  # must not raise
    assert loader.rules["boom"].runtime_error != ""


def test_hot_reload(tmp_path):
    loader, _, _ = _setup(tmp_path)
    assert "add_header" in loader.rules
    import os
    import time

    p = tmp_path / "r.py"
    p.write_text('from tailor.rule_api import Rule\nnew = Rule(id="new")\n')
    os.utime(p, (time.time() + 2, time.time() + 2))
    loader.maybe_reload()
    assert "new" in loader.rules and "add_header" not in loader.rules


def test_file_crud(tmp_path):
    """UI editor: create, read, rename, delete — with syntax and path safety."""
    loader = RuleLoader(rules_dir=tmp_path / "rules", state_path=tmp_path / "state.json")

    loader.save_file("f.py", NEW_RULE_TEMPLATE)
    assert "my_rule" in loader.rules
    assert "my_rule" in loader.read_file("f.py")

    # rename f.py -> g.py, changing the rule id
    loader.save_file("g.py", NEW_RULE_TEMPLATE.replace("my_rule", "other"), original="f.py")
    assert "other" in loader.rules
    assert not (tmp_path / "rules" / "f.py").exists()

    # bad Python is rejected and the good file is left intact
    with pytest.raises(ValueError):
        loader.save_file("g.py", "def (:")
    assert "other" in loader.rules

    # path traversal is rejected on both write and delete
    with pytest.raises(ValueError):
        loader.save_file("../evil.py", "x = 1")
    with pytest.raises(ValueError):
        loader.delete_file("../../evil.py")

    loader.delete_file("g.py")
    assert not loader.rules
