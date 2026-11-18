import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

from tailor import cli


def test_serve_shows_tailscale_urls(monkeypatch, capsys):
    args = cli.build_parser().parse_args(["serve"])
    monkeypatch.setattr(cli, "_port_in_use", lambda host, port: False)
    monkeypatch.setattr("tailor.rule_loader.RuleLoader", lambda *args: SimpleNamespace(rules=range(5)))
    monkeypatch.setattr(cli, "TrafficStore", lambda path: object())
    monkeypatch.setattr("tailor.web.server.start_web", lambda *args: None)
    monkeypatch.setattr("tailor.proxy.run_proxy", lambda *args: None)
    monkeypatch.setattr(cli, "_tailscale_ip", lambda: "100.64.1.2")

    cli.cmd_serve(args)

    output = capsys.readouterr().out
    assert "Tailscale Web UI: http://100.64.1.2:47081" in output
    assert "Tailscale Proxy:  http://100.64.1.2:47080" in output


def test_tailscale_ip_returns_none_when_cli_is_unavailable(monkeypatch):
    def unavailable(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(cli.subprocess, "check_output", unavailable)

    assert cli._tailscale_ip() is None


def test_tailscale_ip_falls_back_to_macos_app(monkeypatch):
    def check_output(command, **kwargs):
        if command[0] == "tailscale":
            raise FileNotFoundError
        return "100.64.1.2\n"

    monkeypatch.setattr(cli.subprocess, "check_output", check_output)

    assert cli._tailscale_ip() == "100.64.1.2"


def test_history_clear_leaves_missing_path_alone(tmp_path, capsys):
    missing = tmp_path / "missing" / "capture.db"
    cli.main(["history", "clear", "--history", str(missing)])
    assert "Cleared 0 history entries." in capsys.readouterr().out
    assert not missing.parent.exists()


def test_history_clear_preserves_unrelated_traffic_table(tmp_path):
    path = tmp_path / "other.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE traffic (count INTEGER)")
        db.execute("INSERT INTO traffic VALUES (10)")
    with pytest.raises(SystemExit, match="Could not clear"):
        cli.main(["history", "clear", "--history", str(path)])
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT count FROM traffic").fetchall() == [(10,)]


def test_serve_rejects_unusable_ports(capsys):
    for option in ("--ui-port", "--proxy-port"):
        for number in ("0", "65536", "-1"):
            with pytest.raises(SystemExit) as exc:
                cli.build_parser().parse_args(["serve", option, number])
            assert exc.value.code == 2
            assert option in capsys.readouterr().err


def test_history_info_reports_counts_without_opening_the_dashboard(tmp_path, capsys):
    path = tmp_path / "capture.db"
    cli.main(["history", "info", "--history", str(path)])
    assert "No history database" in capsys.readouterr().out
    assert not path.exists()

    store = cli.TrafficStore(path)
    record = dict(ts=1, method="GET", host="private.test", path="/", status=200,
                  matched=[], req_headers={}, req_body="private body",
                  resp_headers={}, resp_body="", error="")
    store.add(record)
    store.add({**record, "ts": 5})
    before = path.read_bytes()
    cli.main(["history", "info", "--history", str(path)])
    output = capsys.readouterr().out
    assert "Retained entries: 2" in output
    assert f"Database size: {len(before):,} bytes" in output
    assert "Oldest:" in output and "Newest:" in output
    assert "private.test" not in output and "private body" not in output
    assert path.read_bytes() == before
