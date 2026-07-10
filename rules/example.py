"""Example rules. Copy this file, edit, drop into rules/ — Tailor hot-reloads.

Each Rule defines what it matches and what it changes. Any module-level Rule
instance is picked up, so you can define several per file.
"""

from tailor.rule_api import Ctx, Rule


# --- 1. flip a JSON field in an API response ---------------------------
def _match_config(ctx: Ctx) -> bool:
    return ctx.host == "api.example.com" and ctx.path == "/v1/config"


def _enable_feature(ctx: Ctx) -> None:
    data = ctx.response.json()
    data["feature_enabled"] = True
    ctx.response.set_json(data)


enable_feature = Rule(
    id="enable_feature",
    name="Enable Feature",
    description="Turns on feature_enabled in the config response.",
    match_response=_match_config,
    modify_response=_enable_feature,
)


# --- 2. add a header to every request ----------------------------------
add_header = Rule(
    id="add_debug_header",
    name="Add Debug Header",
    description="Adds X-Tailor: 1 to every outgoing request.",
    match_request=lambda ctx: True,
    modify_request=lambda ctx: ctx.request.headers.__setitem__("X-Tailor", "1"),
)


# --- 3. mock an endpoint without hitting the network -------------------
mock_health = Rule(
    id="mock_health",
    name="Mock Health Check",
    description="Returns a canned 200 for httpbin.org/status/500.",
    match_request=lambda ctx: ctx.host == "httpbin.org" and ctx.path == "/status/500",
    modify_request=lambda ctx: ctx.mock_response(json_body={"status": "ok", "mocked": True}),
)
