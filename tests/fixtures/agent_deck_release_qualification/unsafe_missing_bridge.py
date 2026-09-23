"""Deliberately flawed bridge fixture: absent metadata defaults to Claude."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path


CONDUCTOR_DIR = Path(os.environ["AGENT_DECK_CONDUCTOR_DIR"])
CONFIG_PATH = Path(os.environ["XDG_CONFIG_HOME"]) / "agent-deck/config.toml"
LOG_PATH = CONDUCTOR_DIR / "bridge.log"
ALLOWED_AGENTS = {"claude", "codex", "hermes", "pi"}


def conductor_session_title(name: str) -> str:
    return f"conductor-{name}"


def get_session_status(*_args, **_kwargs):
    raise AssertionError("probe must replace get_session_status")


def get_sessions_list(*_args, **_kwargs):
    raise AssertionError("probe must replace get_sessions_list")


def run_cli(*_args, **_kwargs):
    raise AssertionError("probe must replace run_cli")


def load_agent(name: str) -> str | None:
    meta_path = CONDUCTOR_DIR / name / "meta.json"
    if not meta_path.exists():
        return "claude"  # Deliberate regression under test.
    try:
        with open(meta_path, encoding="utf-8") as handle:
            meta = json.load(handle)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None
    if not isinstance(meta, dict):
        return None
    agent = meta.get("agent", "claude")
    if not isinstance(agent, str):
        return None
    agent = agent.strip().lower() or "claude"
    return agent if agent in ALLOWED_AGENTS else None


async def ensure_conductor_running(name: str, profile: str) -> bool:
    title = conductor_session_title(name)
    loop = asyncio.get_running_loop()
    status = await loop.run_in_executor(None, lambda: get_session_status(title, profile=profile))
    if status in ("waiting", "running", "idle", "active", "starting"):
        return True
    initial = await loop.run_in_executor(
        None,
        lambda: run_cli("session", "start", title, profile=profile, timeout=60),
    )
    if initial.returncode == 0:
        return True
    sessions = await loop.run_in_executor(
        None,
        lambda: get_sessions_list(profile=profile, fail_closed=True),
    )
    if sessions is None:
        return False
    agent = load_agent(name)
    if agent is None:
        return False
    created = await loop.run_in_executor(
        None,
        lambda: run_cli(
            "add",
            str(CONDUCTOR_DIR / name),
            "-t",
            title,
            "-c",
            agent,
            "-g",
            "conductor",
            "--title-lock",
            profile=profile,
            timeout=60,
        ),
    )
    if created.returncode != 0:
        return False
    started = await loop.run_in_executor(
        None,
        lambda: run_cli("session", "start", title, profile=profile, timeout=60),
    )
    if started.returncode != 0:
        return False
    await asyncio.sleep(5)
    final = await loop.run_in_executor(None, lambda: get_session_status(title, profile=profile))
    return final not in ("error", "unknown")
