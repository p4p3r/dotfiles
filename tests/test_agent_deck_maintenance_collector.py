#!/usr/bin/env python3
"""Focused acceptance tests for the read-only maintenance collector."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "private_dot_local/bin/executable_agent-deck-maintenance-collector"
MAX_INPUT_BYTES = 4_194_304
MAX_STATE_BYTES = 1_048_576


def session(
    session_id: str = "0123abcd-1700000000",
    *,
    status: str = "running",
    substate: str = "running",
    path: str | None = "/private/project",
    archived: bool = False,
) -> dict[str, object]:
    return {
        "id": session_id,
        "status": status,
        "substate": substate,
        "path": path,
        "parent_project_path": None,
        "archived": archived,
    }


def fixture(
    *,
    sessions: list[dict[str, object]] | None = None,
    agent_deck_status: str = "OK",
    repositories: list[dict[str, object]] | None = None,
    filesystems: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if repositories is None:
        repositories = [
            {
                "repo_path": "/private/repository",
                "status": "OK",
                "worktrees": [
                    {
                        "path": "/private/repository",
                        "status": "CLEAN",
                        "prunable": False,
                        "locked": False,
                    }
                ],
            }
        ]
    if filesystems is None:
        filesystems = [
            {
                "path": "/",
                "status": "OK",
                "total_bytes": 1_000,
                "used_bytes": 500,
            }
        ]
    return {
        "fixture_version": 1,
        "agent_deck": {
            "status": agent_deck_status,
            "sessions": sessions if sessions is not None else [session()],
        },
        "git_repositories": repositories,
        "filesystems": filesystems,
    }


class CollectorCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.chmod(self.root, 0o700)
        self.state = self.root / "collector-state.json"
        self.input = self.root / "fixture.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_collector(
        self,
        payload: dict[str, object] | None = None,
        *,
        extra: list[str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if payload is not None:
            self.input.write_text(
                json.dumps(payload, sort_keys=True), encoding="utf-8"
            )
        command = [
            sys.executable,
            str(SCRIPT),
            "--state",
            str(self.state),
            "--fixture",
            str(self.input),
        ]
        if extra:
            command.extend(extra)
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def read_state(self) -> dict[str, object]:
        return json.loads(self.state.read_text(encoding="utf-8"))

    @staticmethod
    def recompute_fingerprint(state: dict[str, object]) -> None:
        material = {
            "candidates": state["candidates"],
            "health": [
                {"id": item["id"], "band": item["band"]}
                for item in state["observations"]["filesystems"]
            ],
        }
        encoded = json.dumps(
            material, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
        state["fingerprint"] = hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def event(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
        lines = result.stdout.splitlines()
        if len(lines) != 1:
            raise AssertionError(f"expected one event line, got {lines!r}")
        return json.loads(lines[0])

    def test_help_declares_read_only_and_candidate_boundary(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = result.stdout.lower()
        self.assertIn("read-only", rendered)
        self.assertIn("inspection", rendered)
        self.assertIn("never authorizes cleanup", rendered)
        self.assertIn("first run", rendered)

    def test_first_successful_run_is_silent_and_private(self) -> None:
        result = self.run_collector(fixture())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        state = self.read_state()
        self.assertEqual(state["format_version"], 1)
        self.assertEqual(state["candidates"], [])
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)

    def test_semantically_equivalent_reordered_observation_is_silent(self) -> None:
        first = fixture(
            sessions=[
                session("0123abcd-1700000000"),
                session("89abcdef-1700000001", path="/another/project"),
            ],
            repositories=[
                {
                    "repo_path": "/repo/a",
                    "status": "OK",
                    "worktrees": [
                        {
                            "path": "/repo/a",
                            "status": "CLEAN",
                            "prunable": False,
                            "locked": False,
                        },
                        {
                            "path": "/repo/a/wt",
                            "status": "CLEAN",
                            "prunable": False,
                            "locked": False,
                        },
                    ],
                },
                {"repo_path": "/repo/b", "status": "OK", "worktrees": []},
            ],
        )
        self.assertEqual(self.run_collector(first).returncode, 0)
        before = self.state.read_bytes()
        second = fixture(
            sessions=list(reversed(first["agent_deck"]["sessions"])),
            repositories=list(reversed(first["git_repositories"])),
        )
        second["git_repositories"][1]["worktrees"].reverse()
        result = self.run_collector(second)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.state.read_bytes(), before)

    def test_candidate_add_change_and_remove_each_emit_one_event(self) -> None:
        self.assertEqual(self.run_collector(fixture()).returncode, 0)

        added = self.run_collector(fixture(sessions=[session(status="error", substate="")]))
        self.assertEqual(added.returncode, 10, added.stderr)
        add_event = self.event(added)
        self.assertEqual(add_event["event_type"], "MAINTENANCE_CHANGE")
        self.assertEqual(len(add_event["changes"]["added"]), 1)
        self.assertEqual(add_event["changes"]["removed"], [])
        self.assertNotEqual(add_event["old_fingerprint"], add_event["new_fingerprint"])

        changed = self.run_collector(
            fixture(sessions=[session(status="waiting", substate="auth-401")])
        )
        self.assertEqual(changed.returncode, 10, changed.stderr)
        change_event = self.event(changed)
        self.assertEqual(len(change_event["changes"]["changed"]), 1)

        removed = self.run_collector(fixture())
        self.assertEqual(removed.returncode, 10, removed.stderr)
        remove_event = self.event(removed)
        self.assertEqual(remove_event["changes"]["added"], [])
        self.assertEqual(len(remove_event["changes"]["removed"]), 1)

    def test_threshold_band_transitions_emit_and_stable_band_is_silent(self) -> None:
        def with_usage(used: int) -> dict[str, object]:
            return fixture(
                filesystems=[
                    {
                        "path": "/",
                        "status": "OK",
                        "total_bytes": 1_000,
                        "used_bytes": used,
                    }
                ]
            )

        self.assertEqual(self.run_collector(with_usage(500)).returncode, 0)
        warning = self.run_collector(with_usage(850))
        self.assertEqual(warning.returncode, 10, warning.stderr)
        event = self.event(warning)
        self.assertEqual(
            event["health_transitions"],
            [{"id": event["health_transitions"][0]["id"], "new": "WARN", "old": "NORMAL"}],
        )

        still_warning = self.run_collector(with_usage(899))
        self.assertEqual(still_warning.returncode, 0, still_warning.stderr)
        self.assertEqual(still_warning.stdout, "")

        critical = self.run_collector(with_usage(900))
        self.assertEqual(critical.returncode, 10, critical.stderr)
        self.assertEqual(self.event(critical)["health_transitions"][0]["new"], "CRITICAL")

    def test_unavailable_and_malformed_sources_are_visible_and_fail_closed(self) -> None:
        degraded = fixture(agent_deck_status="UNAVAILABLE", sessions=[])
        degraded["git_repositories"] = [
            {"repo_path": "/repo", "status": "MALFORMED", "worktrees": []}
        ]
        degraded["filesystems"] = [
            {
                "path": "/",
                "status": "UNAVAILABLE",
                "total_bytes": 0,
                "used_bytes": 0,
            }
        ]
        result = self.run_collector(degraded)
        self.assertEqual(result.returncode, 20)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "STATUS: COLLECTION_DEGRADED\n")
        reasons = {
            reason
            for candidate in self.read_state()["candidates"]
            for reason in candidate["reason_codes"]
        }
        self.assertEqual(
            reasons,
            {
                "AGENT_DECK_UNAVAILABLE",
                "FILESYSTEM_UNAVAILABLE",
                "GIT_REPOSITORY_MALFORMED",
            },
        )

        # An unavailable source becoming a differently degraded source is a change,
        # so it emits exactly one event and keeps the degraded exit class.
        degraded["agent_deck"]["status"] = "MALFORMED"
        changed = self.run_collector(degraded)
        self.assertEqual(changed.returncode, 30)
        self.assertEqual(len(changed.stdout.splitlines()), 1)
        self.assertEqual(changed.stderr, "STATUS: COLLECTION_DEGRADED\n")

    def test_malformed_fixture_schema_is_rejected_without_state_rewrite(self) -> None:
        self.assertEqual(self.run_collector(fixture()).returncode, 0)
        before = self.state.read_bytes()
        malformed = fixture()
        malformed["unexpected"] = True
        result = self.run_collector(malformed)
        self.assertEqual(result.returncode, 64)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "ERROR: INVALID_INPUT\n")
        self.assertEqual(self.state.read_bytes(), before)

        self.input.write_text(
            '{"fixture_version":1,"fixture_version":1}', encoding="utf-8"
        )
        duplicate = self.run_collector(None)
        self.assertEqual(duplicate.returncode, 64)
        self.assertEqual(self.state.read_bytes(), before)

    def test_oversize_input_and_state_fail_without_false_success(self) -> None:
        self.input.write_bytes(b" " * (MAX_INPUT_BYTES + 1))
        oversized_input = self.run_collector(None)
        self.assertEqual(oversized_input.returncode, 64)
        self.assertEqual(oversized_input.stdout, "")
        self.assertFalse(self.state.exists())

        self.state.write_bytes(b" " * (MAX_STATE_BYTES + 1))
        self.state.chmod(0o600)
        oversized_state = self.run_collector(fixture())
        self.assertEqual(oversized_state.returncode, 70)
        self.assertEqual(oversized_state.stdout, "")
        self.assertEqual(oversized_state.stderr, "ERROR: INVALID_STATE\n")
        self.assertEqual(self.state.stat().st_size, MAX_STATE_BYTES + 1)

        self.state.unlink()
        oversized_candidate = fixture(
            sessions=[
                session(f"{index:08x}-1700000000", status="stopped", substate="")
                for index in range(6_000)
            ]
        )
        candidate_result = self.run_collector(oversized_candidate)
        self.assertEqual(candidate_result.returncode, 70)
        self.assertEqual(candidate_result.stdout, "")
        self.assertEqual(
            candidate_result.stderr, "ERROR: STATE_WRITE_NOT_VERIFIED\n"
        )
        self.assertFalse(self.state.exists())

    def test_state_schema_types_nan_and_permissions_are_strict(self) -> None:
        self.assertEqual(self.run_collector(fixture()).returncode, 0)
        valid = self.read_state()
        invalid_states = []
        with_extra = dict(valid)
        with_extra["extra"] = 1
        invalid_states.append(json.dumps(with_extra))
        wrong_type = dict(valid)
        wrong_type["format_version"] = True
        invalid_states.append(json.dumps(wrong_type))
        nested_wrong_type = json.loads(json.dumps(valid))
        nested_wrong_type["observations"]["agent_deck"]["status"] = []
        invalid_states.append(json.dumps(nested_wrong_type))
        fabricated_candidate = json.loads(json.dumps(valid))
        fabricated_candidate["candidates"] = [
            {
                "id": "source:agent-deck",
                "kind": "SOURCE",
                "reason_codes": ["AGENT_DECK_UNAVAILABLE"],
            }
        ]
        self.recompute_fingerprint(fabricated_candidate)
        invalid_states.append(json.dumps(fabricated_candidate))
        invalid_states.append('{"format_version":1,"format_version":1}')
        invalid_states.append('{"format_version":1,"observations":NaN}')

        for raw in invalid_states:
            with self.subTest(raw=raw[:40]):
                self.state.write_text(raw, encoding="utf-8")
                self.state.chmod(0o600)
                before = self.state.read_bytes()
                result = self.run_collector(fixture())
                self.assertEqual(result.returncode, 70)
                self.assertEqual(result.stdout, "")
                self.assertEqual(self.state.read_bytes(), before)

        self.assertEqual(self.run_collector(fixture()).returncode, 70)
        self.state.unlink()
        self.assertEqual(self.run_collector(fixture()).returncode, 0)
        self.state.chmod(0o644)
        broad = self.run_collector(fixture())
        self.assertEqual(broad.returncode, 70)
        self.assertEqual(broad.stdout, "")

    def test_atomic_failures_emit_no_event_or_success_claim(self) -> None:
        self.assertEqual(self.run_collector(fixture()).returncode, 0)
        before = self.state.read_bytes()
        changed = fixture(sessions=[session(status="error", substate="")])

        before_replace = self.run_collector(
            changed, extra=["--test-fail-write", "before-replace"]
        )
        self.assertEqual(before_replace.returncode, 70)
        self.assertEqual(before_replace.stdout, "")
        self.assertEqual(before_replace.stderr, "ERROR: STATE_WRITE_NOT_VERIFIED\n")
        self.assertEqual(self.state.read_bytes(), before)

        after_replace = self.run_collector(
            changed, extra=["--test-fail-write", "after-replace"]
        )
        self.assertEqual(after_replace.returncode, 70)
        self.assertEqual(after_replace.stdout, "")
        self.assertEqual(after_replace.stderr, "ERROR: STATE_WRITE_NOT_VERIFIED\n")

    def test_event_and_state_redact_raw_paths_and_provider_fields(self) -> None:
        sentinel = "SENTINEL-RAW-PATH-OR-BODY"
        base = fixture(
            sessions=[session(path=f"/private/{sentinel}")],
            repositories=[
                {
                    "repo_path": f"/private/repo-{sentinel}",
                    "status": "OK",
                    "worktrees": [
                        {
                            "path": f"/private/wt-{sentinel}",
                            "status": "CLEAN",
                            "prunable": False,
                            "locked": False,
                        }
                    ],
                }
            ],
        )
        self.assertEqual(self.run_collector(base).returncode, 0)
        self.assertNotIn(sentinel, self.state.read_text(encoding="utf-8"))
        base["git_repositories"][0]["worktrees"][0]["status"] = "DIRTY"
        result = self.run_collector(base)
        self.assertEqual(result.returncode, 10, result.stderr)
        rendered = result.stdout + result.stderr + self.state.read_text(encoding="utf-8")
        self.assertNotIn(sentinel, rendered)
        event = self.event(result)
        self.assertEqual(
            set(event),
            {
                "changes",
                "event_type",
                "event_version",
                "health_transitions",
                "new_fingerprint",
                "old_fingerprint",
            },
        )

    def test_no_candidate_never_emits_for_non_candidate_session_state_change(self) -> None:
        self.assertEqual(self.run_collector(fixture()).returncode, 0)
        waiting = self.run_collector(
            fixture(sessions=[session(status="waiting", substate="idle-at-empty-prompt")])
        )
        self.assertEqual(waiting.returncode, 0, waiting.stderr)
        self.assertEqual(waiting.stdout, "")

    def test_injected_live_collectors_use_only_frozen_read_only_argv(self) -> None:
        loader = importlib.machinery.SourceFileLoader("maintenance_collector", str(SCRIPT))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        calls: list[list[str]] = []

        class Result:
            def __init__(self, stdout: bytes) -> None:
                self.returncode = 0
                self.stdout = stdout
                self.stderr = b""

        def runner(argv: list[str], _timeout: float, _limit: int) -> object:
            calls.append(argv)
            if argv[-2:] == ["list", "--json"]:
                return Result(
                    json.dumps(
                        [
                            {
                                "id": "0123abcd-1700000000",
                                "status": "running",
                                "substate": "running",
                                "path": "/repo/wt",
                                "parent_project_path": "",
                                "archived": False,
                                "created_at": "volatile-and-ignored",
                                "title": "provider-body-like-and-ignored",
                            }
                        ]
                    ).encode()
                )
            if argv[-3:] == ["list", "--porcelain", "-z"]:
                return Result(
                    b"worktree /repo/wt\0HEAD 0123456789012345678901234567890123456789\0"
                    b"branch refs/heads/main\0\0"
                )
            if "status" in argv:
                return Result(b"")
            raise AssertionError(argv)

        class Usage:
            total = 1_000
            used = 500
            free = 500

        observation = module.collect_live(
            agent_deck="agent-deck-stub",
            profile="default",
            git="git-stub",
            repositories=["/repo"],
            filesystems=["/"],
            runner=runner,
            disk_usage=lambda _path: Usage(),
        )
        self.assertEqual(observation["agent_deck"]["status"], "OK")
        self.assertEqual(
            calls,
            [
                ["agent-deck-stub", "-p", "default", "list", "--json"],
                ["git-stub", "-C", "/repo", "worktree", "list", "--porcelain", "-z"],
                [
                    "git-stub",
                    "-C",
                    "/repo/wt",
                    "status",
                    "--porcelain=v1",
                    "-z",
                    "--untracked-files=normal",
                ],
            ],
        )


if __name__ == "__main__":
    unittest.main()
