"""Loads Rule objects from .py files in a directory, tracks enable/disable
state in a JSON file, and hot-reloads when files change.

Broken rule files are captured as errors, not raised — the proxy keeps running.
"""

import importlib.util
import json
import re
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from .rule_api import Rule

NEW_RULE_TEMPLATE = '''from tailor.rule_api import Ctx, Rule


def match_response(ctx: Ctx) -> bool:
    return ctx.host == "api.example.com" and ctx.path == "/v1/config"


def modify_response(ctx: Ctx) -> None:
    data = ctx.response.json()
    data["feature_enabled"] = True
    ctx.response.set_json(data)


rule = Rule(
    id="my_rule",
    name="My Rule",
    description="",
    match_response=match_response,
    modify_response=modify_response,
)
'''


@dataclass
class LoadedRule:
    rule: Rule
    source: str  # filename
    runtime_error: str = ""


@dataclass
class RuleLoader:
    rules_dir: Path
    state_path: Path
    hot_reload: bool = True

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    rules: dict[str, LoadedRule] = field(default_factory=dict)
    load_errors: dict[str, str] = field(default_factory=dict)  # filename -> traceback
    _mtimes: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.rules_dir = Path(self.rules_dir)
        self.state_path = Path(self.state_path)
        self.rules_dir.mkdir(parents=True, exist_ok=True)
        self.load()

    # --- loading -------------------------------------------------------
    def _snapshot_mtimes(self) -> dict[str, float]:
        m = {str(p): p.stat().st_mtime for p in sorted(self.rules_dir.glob("*.py"))}
        if self.state_path.exists():
            m[str(self.state_path)] = self.state_path.stat().st_mtime
        return m

    def load(self) -> None:
        with self._lock:
            rules: dict[str, LoadedRule] = {}
            errors: dict[str, str] = {}
            for path in sorted(self.rules_dir.glob("*.py")):
                if path.name.startswith("_"):
                    continue
                try:
                    for r in _rules_in_file(path):
                        rules[r.id] = LoadedRule(rule=r, source=path.name)
                except Exception:
                    errors[path.name] = traceback.format_exc()
            self.rules = rules
            self.load_errors = errors
            self._mtimes = self._snapshot_mtimes()

    def maybe_reload(self) -> None:
        if self.hot_reload and self._snapshot_mtimes() != self._mtimes:
            self.load()

    # --- enable/disable state -----------------------------------------
    def _state(self) -> dict[str, bool]:
        try:
            return json.loads(self.state_path.read_text())
        except Exception:
            return {}

    def is_enabled(self, rule_id: str) -> bool:
        return self._state().get(rule_id, True)  # default: enabled

    def set_enabled(self, rule_id: str, enabled: bool) -> None:
        with self._lock:
            state = self._state()
            state[rule_id] = enabled
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(state, indent=2))
            self._mtimes = self._snapshot_mtimes()

    def enabled_rules(self) -> list[Rule]:
        state = self._state()
        return [lr.rule for lr in self.rules.values() if state.get(lr.rule.id, True)]

    # --- file management (UI editor) ----------------------------------
    def _safe_path(self, filename: str) -> Path:
        if not re.match(r"^[A-Za-z0-9_-]+\.py$", filename):
            raise ValueError("Filename must be letters, numbers, _ or - and end in .py")
        path = (self.rules_dir / filename).resolve()
        if path.parent != self.rules_dir.resolve():
            raise ValueError("Invalid filename")
        return path

    def read_file(self, filename: str) -> str:
        return self._safe_path(filename).read_text()

    def save_file(self, filename: str, source: str, original: str = "") -> None:
        """Validate + write a rule file, then reload. Raises ValueError/SyntaxError
        with a user-facing message on bad input."""
        path = self._safe_path(filename)
        try:
            compile(source, filename, "exec")
        except SyntaxError as exc:
            raise ValueError(f"Line {exc.lineno}: {exc.msg}") from exc
        path.write_text(source)
        if original and original != filename:
            self._safe_path(original).unlink(missing_ok=True)
        self.load()

    def delete_file(self, filename: str) -> None:
        self._safe_path(filename).unlink(missing_ok=True)
        self.load()

    def record_error(self, rule_id: str, exc: Exception) -> None:
        lr = self.rules.get(rule_id)
        if lr:
            lr.runtime_error = "".join(traceback.format_exception(exc))


def _rules_in_file(path: Path) -> list[Rule]:
    """Exec a file and collect every module-level Rule instance."""
    spec = importlib.util.spec_from_file_location(f"tailor_rule_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    found = [v for v in vars(module).values() if isinstance(v, Rule)]
    if not found:
        raise ValueError(f"{path.name} defines no Rule instances")
    return found
