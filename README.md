# Tailor 🧵

A programmable, self-hosted proxy for inspecting and modifying HTTP/HTTPS
traffic during development and testing. Point a browser, phone, emulator, or
`curl` at Tailor as an explicit proxy, then write small Python rules to change
requests and responses on the fly. Built on [mitmproxy](https://mitmproxy.org).

## Quick start

```bash
uv sync
uv run tailor serve
```

This starts:

- **Proxy** on `0.0.0.0:47080` — configure this as your client's HTTP/HTTPS proxy.
- **Web UI** on `http://localhost:47081` — view traffic, toggle rules, see errors.

Ports default to the quiet `47080`/`47081` to avoid clashing with the usual
`8080`/`3000`/etc. Override with `--proxy-port` / `--ui-port` if needed.

Rules live in `rules/*.py`. Enable/disable state is stored in `rule_state.json`,
and traffic history in `tailor.db` (SQLite, rolling ~1000 entries). Rules
hot-reload when you edit the files — no restart needed.

## Writing rules

A rule is a `Rule` object that says what to match and what to change. Drop any
`.py` file with one or more `Rule` instances into `rules/`.

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

### The `ctx` object

| Attribute | What it is |
|-----------|-----------|
| `ctx.host`, `ctx.path`, `ctx.query`, `ctx.method`, `ctx.url` | request metadata |
| `ctx.request.method` / `.url` | read or assign to rewrite |
| `ctx.request.headers` | dict-like, case-insensitive |
| `ctx.request.text` / `.set_text(s)` | raw body |
| `ctx.request.json()` / `.set_json(obj)` | JSON body |
| `ctx.response.status_code` | read or assign |
| `ctx.response.headers` / `.text` / `.set_text` / `.json` / `.set_json` | response body |
| `ctx.mock_response(status=200, text=..., json_body=..., headers=...)` | reply without going upstream (call from a request hook) |

`ctx.response` is `None` in request hooks. Any Python is fair game — rules are
trusted local code and are **not** sandboxed. A rule that raises is shown as
errored in the UI; the proxy and other rules keep running.

Hooks a rule can define: `match_request` + `modify_request`,
`match_response` + `modify_response`. See [`rules/example.py`](rules/example.py)
for header injection, JSON editing, and endpoint mocking.

You can also create, edit, rename, and delete rule files from the web UI
(**Rules → + New rule**, or **Edit** on any rule). It's a plain code editor —
saves are syntax-checked, written to `rules/`, and hot-reloaded. A file that
imports cleanly but fails at load (e.g. defines no `Rule`) shows up under
**Load errors** with an inline edit link.

## CLI

```bash
uv run tailor serve                    # start proxy + web UI
uv run tailor rules list               # list rules and their on/off state
uv run tailor rules enable <rule_id>   # toggle without editing files
uv run tailor rules disable <rule_id>
uv run tailor rules reload             # nudge a running server to hot-reload
uv run tailor history clear            # wipe traffic history
```

`serve` flags: `--proxy-host`, `--proxy-port`, `--ui-host`, `--ui-port`,
`--rules-dir`, `--state`, `--history`, `--no-hot-reload`.

## HTTPS interception

To read/modify HTTPS you must trust mitmproxy's CA certificate on the client:

1. With Tailor running and your device using it as a proxy, open
   **http://mitm.it** on the device and follow the per-platform instructions,
   or grab the cert directly from `~/.mitmproxy/mitmproxy-ca-cert.pem`.
2. Install **and trust** it:
   - **iOS:** install the profile, then Settings → General → About → Certificate
     Trust Settings → enable full trust for the mitmproxy cert.
   - **Android:** install as a CA certificate. Note apps only trust user CAs if
     they opt in (API 24+); the emulator with a writable system image is easier.
   - **macOS/desktop browsers:** add the cert to the system/browser trust store.

**Certificate pinning:** some apps pin their certificates and will refuse to
talk through any intercepting proxy. That's expected and not fixable from
Tailor's side.

## Using it from a phone over Tailscale

Tailor works well on a [Tailscale](https://tailscale.com)-connected machine —
no special config needed, just bind the proxy to `0.0.0.0` (the default).

1. Install Tailscale on both the machine running Tailor and your phone; sign
   both into the same tailnet.
2. Run `uv run tailor serve` on the machine.
3. On the phone, set the HTTP proxy to the machine's Tailnet IP (or MagicDNS
   name like `my-mac.tailnet-name.ts.net`) on port `47080`.
4. Open the web UI at `http://<tailnet-name>:47081`.
5. For HTTPS, install the cert as above.

## Notes & limitations

- History is a rolling window; old entries are dropped automatically.
- Rules run in-process without sandboxing — only run rules you trust.
- The web UI can write and run rule files, so anyone who can reach it can
  execute Python on the host. Binding the proxy and UI to `0.0.0.0` exposes
  them to your whole network/tailnet — use `--ui-host 127.0.0.1` (and
  `--proxy-host 127.0.0.1`) to keep them local, and only expose the UI on a
  trusted tailnet.

## Development

```bash
uv run pytest
uv run ruff check .
```
