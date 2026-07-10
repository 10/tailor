"""Server-rendered web UI on stdlib http.server. No framework.

Templates live in templates/*.html (string.Template), styles in static/.
Runs in a daemon thread alongside the mitmproxy event loop, sharing the same
RuleLoader and TrafficStore instances.
"""

import html
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from string import Template
from urllib.parse import parse_qs, urlparse

from ..rule_loader import NEW_RULE_TEMPLATE, RuleLoader
from ..traffic_store import TrafficStore

HERE = Path(__file__).parent


def render(template: str, /, **kw: object) -> str:
    return Template((HERE / "templates" / template).read_text()).substitute(**kw)


def _esc(v: object) -> str:
    return html.escape(str(v))


def _status_class(code: int | None) -> str:
    if not code:
        return "s-none"
    if code < 300:
        return "s-ok"
    if code < 400:
        return "s-redir"
    if code < 500:
        return "s-warn"
    return "s-err"


class Handler(BaseHTTPRequestHandler):
    loader: RuleLoader
    store: TrafficStore
    proxy_addr: str

    def log_message(self, *args):  # silence default stderr logging
        pass

    # --- response helpers ---
    def _page(self, title: str, nav_current: str, body: str, status: int = 200) -> None:
        doc = render(
            "base.html",
            title=_esc(title),
            nav="".join(
                f'<a href="{href}" class="{"active" if href == nav_current else ""}">{label}</a>'
                for href, label in (("/", "Rules"), ("/traffic", "Traffic"))
            ),
            proxy_addr=_esc(self.proxy_addr),
            body=body,
        )
        self._write(doc.encode(), status, "text/html; charset=utf-8")

    def _write(self, body: bytes, status: int, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self) -> None:
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    # --- routing ---
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._page("Rules", "/", self._rules_body())
        elif path == "/traffic":
            q = parse_qs(parsed.query)
            self._page(
                "Traffic", "/traffic",
                self._traffic_body(
                    only_matched=q.get("matched", ["0"])[0] == "1",
                    rule=q.get("rule", [""])[0],
                ),
            )
        elif path == "/rules/new":
            self._page("New rule", "/", self._editor_body())
        elif path == "/rules/edit":
            self._edit_page(parse_qs(parsed.query).get("file", [""])[0])
        elif path.startswith("/traffic/"):
            self._entry(int(path.rsplit("/", 1)[1]))
        elif path == "/static/style.css":
            self._write((HERE / "static/style.css").read_bytes(), 200, "text/css")
        else:
            self._page("Not found", "", '<p class="sub">Not found</p>', 404)

    def _form(self) -> dict[str, str]:
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        return {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/rules/reload":
            self.loader.load()
            self._redirect()
        elif path == "/rules/save":
            self._save_rule(self._form())
        elif path == "/rules/delete":
            try:
                self.loader.delete_file(self._form().get("file", ""))
            except (ValueError, OSError):
                pass
            self._redirect()
        elif path.startswith("/rules/") and path.endswith("/toggle"):
            rule_id = path[len("/rules/"):-len("/toggle")]
            self.loader.set_enabled(rule_id, not self.loader.is_enabled(rule_id))
            self._redirect()
        else:
            self._page("Not found", "", '<p class="sub">Not found</p>', 404)

    # --- rule editor ---
    def _editor_body(self, filename: str = "", source: str | None = None,
                     original: str = "", error: str = "") -> str:
        if source is None:
            source = NEW_RULE_TEMPLATE
        return render(
            "editor.html",
            heading="New rule" if not original else f"Editing {_esc(original)}",
            filename=_esc(filename),
            original=_esc(original),
            source=_esc(source),
            error=f'<div class="editor-error">{_esc(error)}</div>' if error else "",
        )

    def _edit_page(self, filename: str) -> None:
        try:
            source = self.loader.read_file(filename)
        except (ValueError, OSError):
            self._page("Not found", "/", '<p class="sub">Rule file not found</p>', 404)
            return
        self._page(f"Editing {filename}", "/",
                   self._editor_body(filename, source, original=filename))

    def _save_rule(self, form: dict[str, str]) -> None:
        filename = form.get("filename", "").strip()
        source = form.get("source", "")
        original = form.get("original", "").strip()
        try:
            self.loader.save_file(filename, source, original)
        except (ValueError, OSError) as exc:
            self._page("Edit rule", "/",
                       self._editor_body(filename, source, original, str(exc)))
            return
        self._redirect()

    # --- pages ---
    def _rules_body(self) -> str:
        rows = []
        enabled_count = 0
        for lr in self.loader.rules.values():
            r = lr.rule
            on = self.loader.is_enabled(r.id)
            enabled_count += on
            hooks = "".join(
                f'<span class="hook">{h}</span>'
                for h, present in (("req", r.match_request), ("resp", r.match_response))
                if present
            )
            error = f'<div class="trace">{_esc(lr.runtime_error)}</div>' if lr.runtime_error else ""
            rows.append(
                render(
                    "rules_row.html",
                    id=_esc(r.id),
                    name=_esc(r.name or r.id),
                    source=_esc(lr.source),
                    description=_esc(r.description),
                    hooks=hooks or '<span class="hook">—</span>',
                    error=error,
                    pill_class="on" if on else "off",
                    state="enabled" if on else "disabled",
                    btn_class="" if on else "primary",
                    btn_label="Disable" if on else "Enable",
                )
            )
        if not rows:
            rows.append(
                '<tr><td colspan="4"><div class="empty-state">'
                "<strong>No rules yet</strong>"
                "Create your first rule to start modifying traffic."
                '<a class="btn primary" href="/rules/new">+ New rule</a></div></td></tr>'
            )
        load_errors = ""
        if self.loader.load_errors:
            items = "".join(
                f'<h3>{_esc(fn)} '
                f'<a class="edit-link" href="/rules/edit?file={_esc(fn)}">edit</a></h3>'
                f"<div class='trace'>{_esc(tb)}</div>"
                for fn, tb in self.loader.load_errors.items()
            )
            load_errors = f'<div class="load-errors"><h2>Load errors</h2>{items}</div>'
        return render(
            "rules.html",
            count=f"{len(self.loader.rules)} rule(s)",
            enabled_count=enabled_count,
            load_errors=load_errors,
            rows="".join(rows),
        )

    def _traffic_body(self, only_matched: bool, rule: str) -> str:
        rows = []
        for e in self.store.recent(200):
            if rule and rule not in e["matched"]:
                continue
            if only_matched and not e["matched"]:
                continue
            when = time.strftime("%H:%M:%S", time.localtime(e["ts"]))
            flag = '<span class="warn-mark">⚠</span>' if e["error"] else ""
            chips = "".join(
                f'<a class="chip" href="/traffic?rule={_esc(rid)}">{_esc(rid)}</a>'
                for rid in e["matched"]
            )
            rows.append(
                render(
                    "traffic_row.html",
                    id=e["id"],
                    time=_esc(when),
                    method=_esc(e["method"]),
                    status=_esc(e["status"] or "—"),
                    status_class=_status_class(e["status"]),
                    url=_esc(e["host"]) + _esc(e["path"]),
                    matched=flag + (chips or '<span class="sub">—</span>'),
                )
            )
        if not rows:
            hint = (
                "No traffic matches this filter."
                if (only_matched or rule)
                else "Point a client at the proxy and send a request."
            )
            rows.append(
                '<tr><td colspan="5"><div class="empty-state">'
                f"<strong>Nothing here yet</strong>{hint}</div></td></tr>"
            )
        filter_tag = ""
        if rule:
            filter_tag = (
                f'<span class="filter-tag">Filtered to <code>{_esc(rule)}</code> · '
                '<a href="/traffic">clear</a></span>'
            )
        return render(
            "traffic.html",
            all_active="" if (only_matched or rule) else "active",
            matched_active="active" if only_matched else "",
            filter_tag=filter_tag,
            rows="".join(rows),
        )

    def _entry(self, entry_id: int) -> None:
        e = self.store.get(entry_id)
        if not e:
            self._page("Not found", "/traffic", '<p class="sub">Entry not found</p>', 404)
            return

        def body_block(text: str) -> str:
            return f"<pre>{_esc(text)}</pre>" if text else '<pre class="empty">empty</pre>'

        error = f'<div class="trace">{_esc(e["error"])}</div>' if e["error"] else ""
        matched = ", ".join(e["matched"]) or "none"
        self._page(
            f"Entry {entry_id}", "/traffic",
            render(
                "entry.html",
                method=_esc(e["method"]),
                status=_esc(e["status"] or "—"),
                status_class=_status_class(e["status"]),
                url=_esc(e["host"]) + _esc(e["path"]),
                matched=_esc(matched),
                error=error,
                req_headers=_esc(json.dumps(e["req_headers"], indent=2)),
                req_body=body_block(e["req_body"]),
                resp_headers=_esc(json.dumps(e["resp_headers"], indent=2)),
                resp_body=body_block(e["resp_body"]),
            ),
        )


def start_web(
    loader: RuleLoader,
    store: TrafficStore,
    host: str,
    port: int,
    proxy_addr: str,
) -> None:
    Handler.loader = loader
    Handler.store = store
    Handler.proxy_addr = proxy_addr
    server = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
