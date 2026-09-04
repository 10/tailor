from types import SimpleNamespace

from tailor import cli


def test_serve_shows_tailscale_urls(monkeypatch, capsys, tmp_path):
    args = SimpleNamespace(
        history=tmp_path / "tailor.db",
        proxy_host="0.0.0.0",
        proxy_port=47080,
        ui_host="0.0.0.0",
        ui_port=47081,
    )
    monkeypatch.setattr(cli, "_port_in_use", lambda host, port: False)
    monkeypatch.setattr(cli, "_loader", lambda args: SimpleNamespace(rules=range(5)))
    monkeypatch.setattr(cli, "TrafficStore", lambda path: object())
    monkeypatch.setattr(cli, "start_web", lambda *args: None)
    monkeypatch.setattr(cli, "run_proxy", lambda *args: None)
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
