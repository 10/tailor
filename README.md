<div align="center">

# tailor

*Rewrite HTTP traffic with Python rules that reload as you save them.*

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![mitmproxy](https://img.shields.io/badge/Built%20on-mitmproxy-c1272d?style=flat)](https://mitmproxy.org)
[![History](https://img.shields.io/badge/History-SQLite-3f7f5f?style=flat)](https://sqlite.org/)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux-lightgrey)]()

</div>

---

Browser devtools stop at the browser. When the traffic you care about belongs to
a native app, a phone, an emulator, or a background service, there is no obvious
place to stand and watch it — let alone change it.

`tailor` is that place. Point any client at it as an explicit proxy, then write
small Python rules that match and rewrite requests and responses in flight. Save
the file and the next request already uses it. Built on
[mitmproxy](https://mitmproxy.org).

## Features

- **Rules are just Python** — a file in `rules/` that says what to match and what to change. Any `.py` holding a `Rule` gets picked up.
- **Save and it is live** — rules reload on write. No restart, no reconnect, no re-pointing the client's proxy settings.
- **Answer without going upstream** — `ctx.mock_response(...)` from a request hook and the request never leaves the machine.
- **A UI for the whole loop** — watch flows live, flip rules on and off, read load errors, and edit rule files in the browser.
- **History that sticks around** — every flow lands in SQLite as a rolling window, so the request you noticed a minute ago is still there.
- **One bad rule stays contained** — a rule that raises is marked errored in the UI while the proxy and every other rule keep serving.
- **Out-of-the-way ports** — `47080` and `47081`, chosen not to collide with whatever else you already have running.

## Install

```bash
uv sync
uv run tailor serve
```

That starts two things:

- Proxy on `0.0.0.0:47080` — set this as the client's HTTP/HTTPS proxy.
- Web UI on `http://localhost:47081` — traffic, rules, and errors.

Override either with `--proxy-port` / `--ui-port`. Rules live in `rules/*.py`,
enable state in `rule_state.json`, and traffic history in `tailor.db`.

## Rules

A rule declares what to match and what to change. Drop a file with one or more
`Rule` instances into `rules/`:

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
`modify_response`, or both pairs. [`rules/example.py`](rules/example.py) covers
header injection, JSON editing, and endpoint mocking.

Everything a hook needs hangs off `ctx`:

```python
ctx.host, ctx.path, ctx.query, ctx.method, ctx.url  # request metadata, read-only
ctx.request.method, ctx.request.url                 # read, or assign to rewrite
ctx.response.status_code                            # read, or assign
ctx.flow                                            # the raw mitmproxy flow

# ctx.request and ctx.response share the same body helpers:
.headers                                            # dict-like, case-insensitive
.text,   .set_text(s)                               # raw body
.json(), .set_json(obj)                             # JSON body; also sets content-type

ctx.mock_response(status=200, json_body={...})      # reply without going upstream
```

`ctx.response` is `None` in request hooks, and `mock_response` is only callable
from one. Any Python is fair game — rules are trusted local code that run
in-process.

## Web UI

The UI at `http://localhost:47081` shows live flows, per-rule on/off toggles,
and a **Load errors** panel for files that import cleanly but produce no `Rule`.

It also edits rule files directly: **Rules → + New rule**, or **Edit** on any
existing rule. Saves are syntax-checked, written to `rules/`, and hot-reloaded.
Each load error links straight to the editor for the file that caused it.

## CLI

```bash
uv run tailor serve                    # start proxy + web UI
uv run tailor rules list               # rules and their on/off state
uv run tailor rules enable <rule_id>   # toggle without editing files
uv run tailor rules disable <rule_id>
uv run tailor rules reload             # nudge a running server to reload
uv run tailor history clear            # wipe traffic history
```

`serve` accepts `--proxy-host`, `--proxy-port`, `--ui-host`, `--ui-port`,
`--rules-dir`, `--state`, `--history`, and `--no-hot-reload`.

## HTTPS

Reading or modifying HTTPS means trusting mitmproxy's CA on the client. With
tailor running and the device already proxied through it, open
**http://mitm.it** on the device, or take the certificate from
`~/.mitmproxy/mitmproxy-ca-cert.pem`.

Installing is not enough on its own — the certificate has to be trusted:

- iOS: install the profile, then Settings → General → About → Certificate Trust Settings → enable full trust.
- Android: install as a CA certificate. Apps only trust user CAs if they opt in (API 24+), so an emulator with a writable system image is easier.
- macOS and desktop browsers: add it to the system or browser trust store.

Apps that pin their certificates will refuse any intercepting proxy. That is
expected and not fixable from tailor's side.

## Remote Access

tailor needs no special configuration on a [Tailscale](https://tailscale.com)
machine, since the proxy already binds `0.0.0.0`:

1. Install Tailscale on both the host and the phone, signed into one tailnet.
2. Run `uv run tailor serve` on the host.
3. On the phone, set the HTTP proxy to the host's tailnet IP or MagicDNS name — `my-mac.tailnet-name.ts.net` — on port `47080`.
4. Open `http://<tailnet-name>:47081` for the UI, and install the certificate as above.

## Security

Rules are unsandboxed Python running in-process, and the web UI can create and
save rule files. Anyone who can reach the UI can therefore execute code on the
host.

The defaults bind `0.0.0.0`, which exposes both the proxy and the UI to the
whole local network. Keep them local with `--ui-host 127.0.0.1` and
`--proxy-host 127.0.0.1`, and expose the UI only on a network you trust.

Run only rules you wrote or read.

## Agents

[`skills/tailor-rules/SKILL.md`](skills/tailor-rules/SKILL.md) teaches an agent
the rule API — matching, rewriting bodies and headers, and mocking endpoints.
Install it by copying the directory:

```bash
cp -r skills/tailor-rules ~/.claude/skills/tailor-rules
```

## Layout

```
tailor/
├── src/tailor/
│   ├── cli.py                # CLI entrypoint and serve flags
│   ├── proxy.py              # mitmproxy addon, request/response hook path
│   ├── rule_api.py           # the Rule and ctx surface rules are written against
│   ├── rule_loader.py        # discovery, hot reload, load-error tracking
│   ├── traffic_store.py      # SQLite traffic history and its rolling window
│   └── web/                  # web UI and its HTTP server
├── rules/                    # your rules; example.py ships as a reference
├── skills/tailor-rules/      # agent skill
└── tests/                    # pytest suite
```

One direct dependency: `mitmproxy`, which supplies the TLS interception and flow
machinery. Everything else is the standard library.

## Development

```bash
uv run pytest
uv run ruff check .
```
