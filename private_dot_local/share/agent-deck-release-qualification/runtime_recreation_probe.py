#!/usr/bin/env python3
"""Black-box probe for a materialized candidate conductor bridge."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types


PASS = "PASS"
FAIL = "FAIL"
NOT_VERIFIED = "NOT_VERIFIED"
PATH_ENV = (
    "HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
    "XDG_CACHE_HOME",
    "TMPDIR",
    "TMP",
    "TEMP",
    "AGENT_DECK_CONDUCTOR_DIR",
    "CODEX_HOME",
    "CLAUDE_CONFIG_DIR",
    "XDG_RUNTIME_DIR",
)


def emit(verdict: str, summary: str, cases: list[dict] | None = None) -> int:
    payload = {"verdict": verdict, "summary": summary, "cases": cases or []}
    print("AGENT_DECK_RELEASE_QUALIFICATION=" + json.dumps(payload, sort_keys=True))
    return 0 if verdict in (PASS, FAIL) else 2


def inside(root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def completed(code: int, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout="", stderr=stderr)


async def no_sleep(_seconds: float) -> None:
    return None


def main() -> int:
    if len(sys.argv) != 2:
        return emit(NOT_VERIFIED, "runtime probe requires exactly one bridge path")
    root_text = os.environ.get("AGENT_DECK_TASK_ROOT", "")
    if not root_text:
        return emit(NOT_VERIFIED, "AGENT_DECK_TASK_ROOT is unset")
    root = Path(root_text).resolve()
    bridge_path = Path(sys.argv[1]).resolve()
    for key in PATH_ENV:
        value = os.environ.get(key, "")
        if not value or not Path(value).is_absolute() or not inside(root, Path(value)):
            return emit(NOT_VERIFIED, f"{key} is not isolated beneath the task root")
    if not inside(root, bridge_path):
        return emit(NOT_VERIFIED, "candidate bridge import path escapes the task root")
    if Path.home().resolve() != Path(os.environ["HOME"]).resolve():
        return emit(NOT_VERIFIED, "Python home resolution escaped the isolated HOME")
    if not inside(root, Path(tempfile.gettempdir())):
        return emit(NOT_VERIFIED, "Python temporary-directory resolution escaped the task root")

    # Prevent optional global packages from being imported. The required TOML
    # dependency is a minimal in-memory fixture because this probe never parses
    # messaging configuration.
    sys.modules["toml"] = types.SimpleNamespace(load=lambda *_args, **_kwargs: {})
    for optional in ("aiogram", "slack_bolt", "slack_sdk", "discord"):
        sys.modules[optional] = None

    try:
        spec = importlib.util.spec_from_file_location("candidate_bridge", bridge_path)
        if spec is None or spec.loader is None:
            return emit(NOT_VERIFIED, "could not create candidate bridge import spec")
        bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bridge)
    except Exception as exc:
        return emit(NOT_VERIFIED, f"candidate bridge import failed: {type(exc).__name__}: {exc}")
    if Path(bridge.__file__).resolve() != bridge_path:
        return emit(NOT_VERIFIED, "imported bridge does not resolve to the materialized candidate")
    for attribute in ("CONDUCTOR_DIR", "CONFIG_PATH", "LOG_PATH"):
        resolved = Path(getattr(bridge, attribute))
        if not inside(root, resolved):
            return emit(NOT_VERIFIED, f"candidate bridge resolved {attribute} outside the task root")

    conductor_dir = Path(bridge.CONDUCTOR_DIR)
    name_dir = conductor_dir / "qualification"
    cases: list[dict] = []

    def prepare(kind: str) -> None:
        shutil.rmtree(name_dir, ignore_errors=True)
        name_dir.mkdir(parents=True)
        meta = name_dir / "meta.json"
        if kind == "codex":
            meta.write_text('{"name":"qualification","profile":"fixture","agent":"codex"}', encoding="utf-8")
        elif kind == "missing":
            pass
        elif kind == "malformed":
            meta.write_text('{"agent":', encoding="utf-8")
        elif kind == "unreadable":
            meta.mkdir()
        elif kind == "invalid_utf8":
            meta.write_bytes(b'{"description":"\xff","agent":"codex"}')
        elif kind == "invalid_runtime":
            meta.write_text('{"agent":"fixture-unsupported"}', encoding="utf-8")
        else:
            raise AssertionError(kind)

    def run_case(kind: str) -> tuple[bool, list[tuple[tuple, dict]]]:
        prepare(kind)
        statuses = iter(("unknown", "running"))
        calls: list[tuple[tuple, dict]] = []

        def get_status(*_args, **_kwargs):
            return next(statuses, "running")

        def run_cli(*args, **kwargs):
            calls.append((args, kwargs))
            if args[:2] == ("session", "start") and len(calls) == 1:
                return completed(1, "fixture: absent")
            return completed(0)

        bridge.get_session_status = get_status
        bridge.get_sessions_list = lambda *_args, **_kwargs: []
        bridge.run_cli = run_cli
        bridge.asyncio.sleep = no_sleep
        ok = asyncio.run(bridge.ensure_conductor_running("qualification", "fixture"))
        return ok, calls

    try:
        ok, calls = run_case("codex")
        adds = [args for args, _kwargs in calls if args and args[0] == "add"]
        selected = None
        if adds and "-c" in adds[0]:
            selected = adds[0][adds[0].index("-c") + 1]
        valid_pass = ok is True and len(adds) == 1 and selected == "codex"
        cases.append({"name": "metadata-selected-codex", "passed": valid_pass})

        for kind in ("missing", "malformed", "unreadable", "invalid_utf8", "invalid_runtime"):
            ok, calls = run_case(kind)
            adds = [args for args, _kwargs in calls if args and args[0] == "add"]
            case_pass = ok is False and not adds
            name = "missing-meta.json" if kind == "missing" else kind
            cases.append({"name": name, "passed": case_pass})
    except Exception as exc:
        return emit(NOT_VERIFIED, f"runtime behavior probe failed: {type(exc).__name__}: {exc}", cases)

    failed = [case["name"] for case in cases if not case["passed"]]
    if failed:
        return emit(FAIL, "runtime recreation violated cases: " + ", ".join(failed), cases)
    return emit(PASS, "runtime recreation preserved the selected runtime and failed closed", cases)


if __name__ == "__main__":
    raise SystemExit(main())
