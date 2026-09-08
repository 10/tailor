"""Tailor CLI. `uv run tailor <command>`."""

import argparse
import socket
import subprocess
import sys
from pathlib import Path

from .proxy import run_proxy
from .rule_loader import RuleLoader
from .traffic_store import TrafficStore
from .web.server import start_web


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def _tailscale_ip() -> str | None:
    for executable in ("tailscale", "/Applications/Tailscale.app/Contents/MacOS/Tailscale"):
        try:
            output = subprocess.check_output(
                [executable, "ip", "-4"], stderr=subprocess.DEVNULL, text=True, timeout=1
            )
            return output.strip().splitlines()[0]
        except (OSError, subprocess.SubprocessError, IndexError):
            pass
    return None


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--rules-dir", default="rules", help="directory of rule .py files")
    p.add_argument("--state", default="rule_state.json", help="rule enable/disable state file")
    p.add_argument("--history", default="tailor.db", help="SQLite traffic history path")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tailor", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="start the proxy and web UI")
    _add_common(serve)
    serve.add_argument("--proxy-host", default="0.0.0.0")
    serve.add_argument("--proxy-port", type=int, default=47080)
    serve.add_argument("--ui-host", default="0.0.0.0")
    serve.add_argument("--ui-port", type=int, default=47081)
    serve.add_argument("--no-hot-reload", dest="hot_reload", action="store_false")
    serve.set_defaults(func=cmd_serve)

    rules = sub.add_parser("rules", help="manage rules").add_subparsers(dest="rcmd", required=True)

    rlist = rules.add_parser("list")
    _add_common(rlist)
    rlist.set_defaults(func=cmd_rules_list)

    for name, enabled in (("enable", True), ("disable", False)):
        p = rules.add_parser(name)
        _add_common(p)
        p.add_argument("rule_id")
        p.set_defaults(func=cmd_rules_toggle, enabled=enabled)

    rreload = rules.add_parser("reload", help="touch rule files so a running server reloads")
    _add_common(rreload)
    rreload.set_defaults(func=cmd_rules_reload)

    hist = sub.add_parser("history", help="manage traffic history").add_subparsers(
        dest="hcmd", required=True
    )
    hclear = hist.add_parser("clear")
    _add_common(hclear)
    hclear.set_defaults(func=cmd_history_clear)

    return parser


def cmd_serve(args) -> None:
    for label, host, port, flag in (
        ("Proxy", args.proxy_host, args.proxy_port, "--proxy-port"),
        ("Web UI", args.ui_host, args.ui_port, "--ui-port"),
    ):
        if _port_in_use(host, port):
            print(
                f"{label} port {port} is already in use. "
                f"Free it or pick another port with {flag} <port>.",
                file=sys.stderr,
            )
            sys.exit(1)

    loader = RuleLoader(args.rules_dir, args.state, args.hot_reload)
    store = TrafficStore(args.history)
    proxy_addr = f"{args.proxy_host}:{args.proxy_port}"
    start_web(loader, store, args.ui_host, args.ui_port, proxy_addr)
    print(f"Web UI:  http://{args.ui_host}:{args.ui_port}")
    print(f"Proxy:   http://{proxy_addr}  ({len(loader.rules)} rules)")
    tailscale_ip = _tailscale_ip()
    if tailscale_ip and args.ui_host == "0.0.0.0":
        print(f"Tailscale Web UI: http://{tailscale_ip}:{args.ui_port}")
    if tailscale_ip and args.proxy_host == "0.0.0.0":
        print(f"Tailscale Proxy:  http://{tailscale_ip}:{args.proxy_port}")
    print("Point your device's HTTP/HTTPS proxy here. Ctrl-C to stop.")
    run_proxy(loader, store, args.proxy_host, args.proxy_port)


def cmd_rules_list(args) -> None:
    loader = RuleLoader(args.rules_dir, args.state)
    if not loader.rules:
        print("No rules found in", args.rules_dir)
    for lr in loader.rules.values():
        state = "on " if loader.is_enabled(lr.rule.id) else "off"
        print(f"[{state}] {lr.rule.id:24} {lr.rule.name}  ({lr.source})")
    for fn, tb in loader.load_errors.items():
        print(f"[ERR] {fn}: {tb.strip().splitlines()[-1]}")


def cmd_rules_toggle(args) -> None:
    loader = RuleLoader(args.rules_dir, args.state)
    loader.set_enabled(args.rule_id, args.enabled)
    print(f"{args.rule_id} {'enabled' if args.enabled else 'disabled'}")


def cmd_rules_reload(args) -> None:
    files = list(Path(args.rules_dir).glob("*.py"))
    for p in files:
        p.touch()
    print(f"Touched {len(files)} rule file(s); a running server will hot-reload.")


def cmd_history_clear(args) -> None:
    n = TrafficStore(args.history).clear()
    print(f"Cleared {n} history entries.")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
