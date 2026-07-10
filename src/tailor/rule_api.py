"""The API rule files import from: `from tailor.rule_api import Rule`.

A rule is plain data + a few callbacks. `ctx` wraps a mitmproxy flow so rules
never touch mitmproxy types directly.
"""

import json
from dataclasses import dataclass
from typing import Any, Callable

from mitmproxy import http


class _Message:
    """Shared body helpers for request/response."""

    def __init__(self, msg: http.Message):
        self._m = msg

    @property
    def headers(self) -> http.Headers:
        return self._m.headers  # case-insensitive, dict-like

    @property
    def text(self) -> str:
        return self._m.get_text(strict=False) or ""

    def set_text(self, value: str) -> None:
        self._m.set_text(value)

    def json(self) -> Any:
        return json.loads(self.text or "null")

    def set_json(self, data: Any) -> None:
        self._m.set_text(json.dumps(data))
        self._m.headers["content-type"] = "application/json"


class RequestView(_Message):
    @property
    def method(self) -> str:
        return self._m.method

    @method.setter
    def method(self, value: str) -> None:
        self._m.method = value

    @property
    def url(self) -> str:
        return self._m.url

    @url.setter
    def url(self, value: str) -> None:
        self._m.url = value


class ResponseView(_Message):
    @property
    def status_code(self) -> int:
        return self._m.status_code

    @status_code.setter
    def status_code(self, value: int) -> None:
        self._m.status_code = value


class Ctx:
    """What rules receive. `ctx.request` always exists; `ctx.response` exists
    only in response hooks."""

    def __init__(self, flow: http.HTTPFlow):
        self.flow = flow
        self.request = RequestView(flow.request)
        self.response = ResponseView(flow.response) if flow.response else None

    @property
    def host(self) -> str:
        return self.flow.request.pretty_host

    @property
    def path(self) -> str:
        return self.flow.request.path.partition("?")[0]

    @property
    def query(self) -> str:
        return self.flow.request.path.partition("?")[2]

    @property
    def method(self) -> str:
        return self.flow.request.method

    @property
    def url(self) -> str:
        return self.flow.request.pretty_url

    def mock_response(
        self,
        status: int = 200,
        text: str = "",
        headers: dict[str, str] | None = None,
        json_body: Any = None,
    ) -> None:
        """Short-circuit: reply without going upstream. Call from a request hook."""
        hdrs = dict(headers or {})
        if json_body is not None:
            text = json.dumps(json_body)
            hdrs.setdefault("content-type", "application/json")
        self.flow.response = http.Response.make(status, text, hdrs)


@dataclass
class Rule:
    id: str
    name: str = ""
    description: str = ""
    match_request: Callable[[Ctx], bool] | None = None
    modify_request: Callable[[Ctx], None] | None = None
    match_response: Callable[[Ctx], bool] | None = None
    modify_response: Callable[[Ctx], None] | None = None
