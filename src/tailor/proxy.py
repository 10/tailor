"""mitmproxy addon: applies enabled rules and records traffic.

Rule exceptions are caught per-rule so one broken rule never takes down the
proxy or other rules.
"""

import asyncio
import time

from mitmproxy import http
from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster

from .rule_api import Ctx
from .rule_loader import RuleLoader
from .traffic_store import TrafficStore, body_preview


class TailorAddon:
    def __init__(self, loader: RuleLoader, store: TrafficStore):
        self.loader = loader
        self.store = store

    def request(self, flow: http.HTTPFlow) -> None:
        self.loader.maybe_reload()
        ctx = Ctx(flow)
        matched: list[str] = []
        for rule in self.loader.enabled_rules():
            if not rule.match_request:
                continue
            try:
                if rule.match_request(ctx):
                    matched.append(rule.id)
                    if rule.modify_request:
                        rule.modify_request(ctx)
                        ctx = Ctx(flow)  # refresh view (rule may have mocked a response)
            except Exception as exc:
                self.loader.record_error(rule.id, exc)
        flow.metadata["tailor_matched"] = matched

    def response(self, flow: http.HTTPFlow) -> None:
        ctx = Ctx(flow)
        matched: list[str] = list(flow.metadata.get("tailor_matched", []))
        for rule in self.loader.enabled_rules():
            if not rule.match_response:
                continue
            try:
                if rule.match_response(ctx):
                    matched.append(rule.id)
                    if rule.modify_response:
                        rule.modify_response(ctx)
            except Exception as exc:
                self.loader.record_error(rule.id, exc)
        self._record(flow, matched)

    def error(self, flow: http.HTTPFlow) -> None:
        self._record(flow, list(flow.metadata.get("tailor_matched", [])),
                     error=str(flow.error))

    def _record(self, flow: http.HTTPFlow, matched: list[str], error: str = "") -> None:
        req, resp = flow.request, flow.response
        self.store.add(
            {
                "ts": time.time(),
                "method": req.method,
                "host": req.pretty_host,
                "path": req.path,
                "status": resp.status_code if resp else None,
                "matched": matched,
                "req_headers": dict(req.headers),
                "req_body": body_preview(req.get_text(strict=False) or ""),
                "resp_headers": dict(resp.headers) if resp else {},
                "resp_body": body_preview(resp.get_text(strict=False) or "") if resp else "",
                "error": error,
            }
        )


async def _serve(loader: RuleLoader, store: TrafficStore, host: str, port: int) -> None:
    opts = Options(listen_host=host, listen_port=port)
    master = DumpMaster(opts, with_termlog=False, with_dumper=False)
    master.addons.add(TailorAddon(loader, store))
    await master.run()


def run_proxy(loader: RuleLoader, store: TrafficStore, host: str, port: int) -> None:
    """Blocks, running the mitmproxy event loop in the current thread."""
    try:
        asyncio.run(_serve(loader, store, host, port))
    except KeyboardInterrupt:
        pass
