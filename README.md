<div align="center">

# tailor

*Rewrite HTTP traffic with Python rules that reload as you save them.*

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![mitmproxy](https://img.shields.io/badge/Built%20on-mitmproxy-c1272d?style=flat)](https://mitmproxy.org)
[![History](https://img.shields.io/badge/History-SQLite-3f7f5f?style=flat)](https://sqlite.org/)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux-lightgrey)]()

</div>

---

```bash
uv sync
uv run tailor serve
```

Point a browser, phone, emulator, or `curl` at `47080` as its HTTP proxy, then
drop a Python file in `rules/` to change what goes past. The web UI is on
`47081`. Built on [mitmproxy](https://mitmproxy.org).

## Features

- **Rules are just Python** — a file in `rules/` saying what to match and what to change.
- **Save and it is live** — no restart, no reconnect, no re-pointing the client.
- **Mock without going upstream** — `ctx.mock_response(...)` and the request never leaves the machine.
- **UI for the whole loop** — watch flows, toggle rules, read errors, edit files in the browser.
- **One bad rule stays contained** — it shows as errored while everything else keeps serving.

## Rules

```python
from tailor.rule_api import Rule

def match_response(ctx):
    return ctx.host == "api.example.com" and ctx.path == "/v1/config"

def modify_response(ctx):
    data = ctx.response.json()
    data["feature_enabled"] = True
    ctx.response.set_json(data)

rule = Rule(
    id="enable_feature",
    name="Enable Feature",
    description="Turns on feature_enabled in the config response.",
    match_response=match_response,
    modify_response=modify_response,
)
```

A rule can define `match_request` + `modify_request`, `match_response` +
`modify_response`, or both. See [`rules/example.py`](rules/example.py) for
header injection, JSON editing, and mocking.

Everything hangs off `ctx`:

```python
ctx.host, ctx.path, ctx.query, ctx.method, ctx.url  # read-only
ctx.request.method, ctx.request.url                 # read, or assign to rewrite
ctx.response.status_code                            # read, or assign
ctx.flow                                            # raw mitmproxy flow

# request and response share these:
.headers                                            # dict-like, case-insensitive
.text,   .set_text(s)
.json(), .set_json(obj)                             # also sets content-type

ctx.mock_response(status=200, json_body={...})      # request hooks only
```

`ctx.response` is `None` in request hooks.

## Web UI

`http://localhost:47081` shows live flows, per-rule toggles, and a **Load
errors** panel for files that import but define no `Rule`.

It also writes rules: **Rules → + New rule**, or **Edit** on any existing one.
Saves are syntax-checked, written to `rules/`, and reloaded. Load errors link
straight to the editor.

## CLI

```bash
uv run tailor serve                    # proxy + web UI
uv run tailor rules list               # rules and on/off state
uv run tailor rules enable <rule_id>
uv run tailor rules disable <rule_id>
uv run tailor rules reload             # nudge a running server
uv run tailor history clear
```

`serve` takes `--proxy-host`, `--proxy-port`, `--ui-host`, `--ui-port`,
`--rules-dir`, `--state`, `--history`, and `--no-hot-reload`.

State lives in `rule_state.json` (on/off) and `tailor.db` (traffic, rolling
window).

## HTTPS

To read HTTPS, the client has to trust mitmproxy's CA. With the device already
proxied, open **http://mitm.it**, or grab
`~/.mitmproxy/mitmproxy-ca-cert.pem`.

Installing is not enough — it has to be trusted:

- **iOS** — install the profile, then Settings → General → About → Certificate Trust Settings → enable full trust.
- **Android** — install as a CA cert. Apps only trust user CAs if they opt in (API 24+); an emulator with a writable system image is easier.
- **macOS and desktop browsers** — add it to the system or browser trust store.

Apps that pin their certificates will refuse any intercepting proxy.

## Over Tailscale

The proxy already binds `0.0.0.0`, so nothing special is needed:

1. Install Tailscale on the host and the phone, same tailnet.
2. Run `uv run tailor serve`.
3. Set the phone's HTTP proxy to the host's tailnet IP or MagicDNS name, port `47080`.
4. Open `http://<tailnet-name>:47081` and install the cert as above.

## Security

Rules are unsandboxed Python running in-process, and the UI can write rule
files. Anyone who reaches the UI can run code on the host.

The defaults bind `0.0.0.0`, exposing both ports to the whole network. Use
`--ui-host 127.0.0.1` and `--proxy-host 127.0.0.1` to keep them local. Run only
rules you wrote or read.

## Agents

```bash
cp -r skills/tailor-rules ~/.claude/skills/tailor-rules
```

[`SKILL.md`](skills/tailor-rules/SKILL.md) teaches an agent the rule API —
matching, rewriting bodies and headers, mocking endpoints.

## Layout

```
tailor/
├── src/tailor/
│   ├── cli.py                # CLI entrypoint and serve flags
│   ├── proxy.py              # mitmproxy addon, hook path
│   ├── rule_api.py           # the Rule and ctx surface
│   ├── rule_loader.py        # discovery, hot reload, load errors
│   ├── traffic_store.py      # SQLite traffic history
│   └── web/                  # web UI and its HTTP server
├── rules/                    # your rules; example.py included
├── skills/tailor-rules/      # agent skill
└── tests/                    # pytest suite
```

One dependency: `mitmproxy`. Everything else is the standard library.

## Development

```bash
uv run pytest
uv run ruff check .
```
