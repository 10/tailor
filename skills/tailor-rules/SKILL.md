---
name: tailor-rules
description: Write rules for the Tailor proxy — Python files in rules/ that match and modify HTTP(S) traffic. Use when the user wants to create, edit, or debug a Tailor rule, mock an endpoint, rewrite a header/body/JSON field, or intercept requests/responses with Tailor.
---

# Writing Tailor rules

A **rule** is a `Rule` object in a `.py` file under `rules/`. It defines what
traffic to **match** and what to **modify**. Tailor hot-reloads the folder, so a
saved file takes effect on the next request — no restart.

Canonical examples live in [`rules/example.py`](../../rules/example.py); the full
`ctx` API is the source of truth in
[`src/tailor/rule_api.py`](../../src/tailor/rule_api.py). Read those first.

## The shape

```python
from tailor.rule_api import Ctx, Rule

def _match(ctx: Ctx) -> bool:
    return ctx.host == "api.example.com" and ctx.path == "/v1/config"

def _modify(ctx: Ctx) -> None:
    data = ctx.response.json()
    data["feature_enabled"] = True
    ctx.response.set_json(data)

enable_feature = Rule(
    id="enable_feature",           # unique across all rules; stable (UI toggle keys on it)
    name="Enable Feature",
    description="Turns on feature_enabled in the config response.",
    match_response=_match,
    modify_response=_modify,
)
```

Every module-level `Rule` instance in the file is loaded, so define several per
file if they belong together.

## Hooks

A rule uses one or both pairs. `match_*` returns a bool; `modify_*` mutates via
`ctx` and returns nothing.

- `match_request` + `modify_request` — fire before the request goes upstream.
- `match_response` + `modify_response` — fire before the response reaches the client.

A rule with only `match_*` and no `modify_*` still records as "matched" in the UI
— useful as a pure traffic filter.

## The `ctx` object

Request metadata (read-only): `ctx.host`, `ctx.path` (no query string),
`ctx.query`, `ctx.method`, `ctx.url`.

`ctx.request` (always present) and `ctx.response` (**only in response hooks** —
`None` in request hooks):

| Call | Effect |
|------|--------|
| `.method` / `.url` (request only) | read or assign to rewrite |
| `.status_code` (response only) | read or assign |
| `.headers` | dict-like, case-insensitive; `ctx.request.headers["X"] = "y"` |
| `.text` / `.set_text(s)` | raw body as string |
| `.json()` / `.set_json(obj)` | parse / replace body as JSON (sets content-type) |

`ctx.mock_response(status=200, text=..., json_body=..., headers=...)` — reply
**without going upstream**. Call it from a `modify_request` hook.

## Patterns

- **Edit a JSON field** — `data = ctx.response.json(); data[k] = v; ctx.response.set_json(data)`.
- **Add/override a header** — `ctx.request.headers["Authorization"] = "Bearer test"`.
- **Rewrite the destination** — `ctx.request.url = ctx.request.url.replace("prod", "staging")`.
- **Text/HTML find-replace** — match on `needle in ctx.response.text`, then
  `ctx.response.set_text(ctx.response.text.replace(needle, ...))`. Match on the
  needle so you only rewrite bodies that contain it.
- **Mock / force an error** — `ctx.mock_response(status=503, json_body={"error": "down"})`
  from `modify_request`.

## Rules that matter

- **`id` must be unique and stable.** Enable/disable state is keyed on `id` in
  `rule_state.json`; renaming an `id` resets its toggle.
- **Match narrowly.** `match_request=lambda ctx: True` runs your modify on *every*
  request. Scope by host/path unless you mean everything.
- **`ctx.response` is `None` in request hooks.** Reading it there raises — and a
  raising rule is shown as errored in the UI while everything else keeps running,
  so check the UI's rule error when a rule silently does nothing.
- **Bodies are decoded text.** `.text`/`.json()` handle gzip/brotli automatically;
  truly binary bodies won't round-trip cleanly through `.text`.

## Verify

Save the file, then confirm it loaded and fires:

```bash
uv run tailor rules list          # your rule id appears, no load error
# send traffic through the proxy, then check the UI Traffic tab →
# filter "Matched only" or click the rule id to see it matched
```
