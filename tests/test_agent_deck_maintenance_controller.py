#!/usr/bin/env python3
"""Focused acceptance tests for the report-only maintenance controller."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "private_dot_local/bin/executable_agent-deck-maintenance-controller"
CHARTER = REPO / "docs/agent-deck-fleet-custodian-charter.md"
MODULE = REPO / "nix/modules/agent-deck-maintenance.nix"
OWNER = "0123abcd-1700000000"
OTHER_OWNER = "89abcdef-1700000001"
BASELINE_AT = "2026-09-20T00:00:00Z"
EARLY_AT = "2026-09-20T01:00:00Z"
DUE_AT = "2026-09-21T00:00:00Z"
MAX_STATE_BYTES = 1_048_576
MAX_GENERATION = 9_223_372_036_854_775_807
COLLECTOR_INSTANCE = "0123456789abcdef0123456789abcdef"


def fingerprint(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def transition_event(
    old_label: str,
    new_label: str,
    *,
    old_generation: int = 0,
    instance_id: str = COLLECTOR_INSTANCE,
    include_change: bool = True,
) -> dict[str, object]:
    return {
        "event_version": 2,
        "event_type": "MAINTENANCE_CHANGE",
        "collector_instance_id": instance_id,
        "old_generation": old_generation,
        "new_generation": old_generation + 1,
        "old_fingerprint": fingerprint(old_label),
        "new_fingerprint": fingerprint(new_label),
        "changes": {
            "added": (
                [
                    {
                        "id": "session:0123abcd-1700000000",
                        "kind": "SESSION",
                        "reason_codes": ["SESSION_STOPPED"],
                    }
                ]
                if include_change
                else []
            ),
            "changed": [],
            "removed": [],
        },
        "health_transitions": [],
    }


def change_event(seed: str = "a") -> dict[str, object]:
    if seed == "c":
        return transition_event("b", "c", old_generation=1)
    new_seed = "b" if seed != "b" else "c"
    return transition_event(seed, new_seed)


class ControllerCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.chmod(self.root, 0o700)
        self.state = self.root / "controller.json"
        self.collector_state = self.root / "collector.json"
        self.collector_log = self.root / "collector-argv.jsonl"
        self.agent_log = self.root / "agent-argv.jsonl"
        self.prompt_log = self.root / "prompt.jsonl"
        self.workdir = self.root / "work tree"
        self.workdir.mkdir(mode=0o700)
        self.collector = self.root / "collector-stub"
        self.agent_deck = self.root / "agent-deck-stub"
        self.git = self.root / "git-stub"
        self.git.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
        self.git.chmod(0o700)
        self.collector.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys

                with open(os.environ["COLLECTOR_ARGV_LOG"], "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(sys.argv[1:]) + "\\n")
                mode = os.environ.get("COLLECTOR_MODE", "no-change")
                state_path = sys.argv[sys.argv.index("--state") + 1]
                event = json.loads(os.environ["COLLECTOR_EVENT"])

                def write_checkpoint(generation, checkpoint_fingerprint):
                    payload = {
                        "format_version": 2,
                        "collector_instance_id": event["collector_instance_id"],
                        "generation": generation,
                        "observations": {},
                        "candidates": [],
                        "fingerprint": checkpoint_fingerprint,
                    }
                    with open(state_path, "w", encoding="utf-8") as handle:
                        json.dump(payload, handle, sort_keys=True)
                    os.chmod(state_path, 0o600)

                if mode == "changed" or mode == "changed-degraded":
                    write_checkpoint(event["new_generation"], event["new_fingerprint"])
                    sys.stdout.write(os.environ["COLLECTOR_EVENT"] + "\\n")
                    if mode == "changed-degraded":
                        sys.stderr.write("STATUS: COLLECTION_DEGRADED\\n")
                    raise SystemExit(30 if mode == "changed-degraded" else 10)
                if mode == "degraded":
                    sys.stderr.write("STATUS: COLLECTION_DEGRADED\\n")
                    raise SystemExit(20)
                if mode == "malformed-event":
                    sys.stdout.write(os.environ.get("PRIVATE_SENTINEL", "PRIVATE-BODY"))
                    raise SystemExit(10)
                if mode == "failure":
                    sys.stderr.write(os.environ.get("PRIVATE_SENTINEL", "PRIVATE-BODY"))
                    raise SystemExit(70)
                if not os.path.exists(state_path):
                    write_checkpoint(event["old_generation"], event["old_fingerprint"])
                raise SystemExit(0)
                """
            ),
            encoding="utf-8",
        )
        self.collector.chmod(0o700)
        self.agent_deck.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import json
                import os
                import sys

                argv = sys.argv[1:]
                with open(os.environ["AGENT_ARGV_LOG"], "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(argv) + "\\n")
                prompt = sys.stdin.read()
                if prompt:
                    with open(os.environ["PROMPT_LOG"], "a", encoding="utf-8") as handle:
                        handle.write(json.dumps(prompt) + "\\n")

                mode = os.environ.get("AGENT_MODE", "ok")
                if "launch" in argv:
                    if mode == "launch-failure":
                        sys.stderr.write(os.environ.get("PRIVATE_SENTINEL", "PRIVATE-BODY"))
                        raise SystemExit(1)
                    if mode == "launch-malformed":
                        sys.stdout.write(os.environ.get("PRIVATE_SENTINEL", "PRIVATE-BODY"))
                        raise SystemExit(0)
                    session_id = os.environ.get("LAUNCH_ID", "{OWNER}")
                    payload = {{
                        "success": True,
                        "id": session_id,
                        "session_id": session_id,
                        "message": os.environ.get("PRIVATE_SENTINEL", "PRIVATE-BODY"),
                        "path": "/private/path",
                    }}
                    sys.stdout.write(json.dumps(payload))
                    raise SystemExit(0)

                if "show" in argv:
                    session_id = argv[argv.index("show") + 1]
                    if mode in ("show-not-found", "show-bogus"):
                        sys.stdout.write(json.dumps({{"success": False, "code": "NOT_FOUND"}}))
                        raise SystemExit(2)
                    returned = "{OTHER_OWNER}" if mode == "show-mismatch" else session_id
                    status = os.environ.get("SESSION_STATUS", "running")
                    substate = os.environ.get("SESSION_SUBSTATE", "running")
                    if mode == "show-unknown":
                        status = "private-unknown-status"
                    sys.stdout.write(json.dumps({{
                        "id": returned,
                        "status": status,
                        "substate": substate,
                        "title": os.environ.get("PRIVATE_SENTINEL", "PRIVATE-BODY"),
                        "output": os.environ.get("PRIVATE_SENTINEL", "PRIVATE-BODY"),
                    }}))
                    raise SystemExit(0)

                if "send" in argv:
                    session_id = argv[argv.index("send") + 1]
                    delivery = "unverified" if mode == "send-unverified" else "submitted"
                    if mode == "send-failure":
                        sys.stderr.write(os.environ.get("PRIVATE_SENTINEL", "PRIVATE-BODY"))
                        raise SystemExit(1)
                    sys.stdout.write(json.dumps({{
                        "success": True,
                        "session_id": session_id,
                        "delivery": delivery,
                        "message": os.environ.get("PRIVATE_SENTINEL", "PRIVATE-BODY"),
                    }}))
                    raise SystemExit(0)
                raise SystemExit(64)
                """
            ),
            encoding="utf-8",
        )
        self.agent_deck.chmod(0o700)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def environment(self, **updates: str) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "COLLECTOR_ARGV_LOG": str(self.collector_log),
                "AGENT_ARGV_LOG": str(self.agent_log),
                "PROMPT_LOG": str(self.prompt_log),
                "COLLECTOR_EVENT": json.dumps(change_event(), sort_keys=True),
            }
        )
        env.update(updates)
        return env

    def run_controller(
        self,
        *,
        now: str,
        collector_mode: str = "no-change",
        env: dict[str, str] | None = None,
        extra: list[str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(SCRIPT),
            "--state",
            str(self.state),
            "--collector-state",
            str(self.collector_state),
            "--collector",
            str(self.collector),
            "--agent-deck",
            str(self.agent_deck),
            "--git",
            str(self.git),
            "--charter",
            str(CHARTER),
            "--workdir",
            str(self.workdir),
            "--host-alias",
            "test-host",
            "--profile",
            "test-profile",
            "--repo",
            str(self.root / "repo;touch SHOULD_NOT_EXIST"),
            "--filesystem",
            str(self.root / "fs $(touch SHOULD_NOT_EXIST_EITHER)"),
            "--now",
            now,
        ]
        if extra:
            command.extend(extra)
        proc_env = self.environment(COLLECTOR_MODE=collector_mode)
        if env:
            proc_env.update(env)
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=proc_env,
        )

    def state_json(self) -> dict[str, object]:
        return json.loads(self.state.read_text(encoding="utf-8"))

    def agent_calls(self) -> list[list[str]]:
        if not self.agent_log.exists():
            return []
        return [json.loads(line) for line in self.agent_log.read_text().splitlines()]

    def baseline(self) -> subprocess.CompletedProcess[str]:
        result = self.run_controller(now=BASELINE_AT)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def launch_change(
        self, *, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        self.baseline()
        return self.run_controller(now=EARLY_AT, collector_mode="changed", env=env)

    def test_first_baseline_and_unchanged_early_tick_start_no_agent_turn(self) -> None:
        first = self.baseline()
        self.assertEqual(first.stdout, "")
        self.assertEqual(first.stderr, "")
        state = self.state_json()
        self.assertEqual(state["format_version"], 2)
        self.assertEqual(state["collector_instance_id"], COLLECTOR_INSTANCE)
        self.assertEqual(state["collector_generation"], 0)
        self.assertEqual(state["collector_fingerprint"], fingerprint("a"))
        self.assertEqual(state["lifecycle_state"], "ADMITTED")
        self.assertEqual(state["owner_kind"], "CONDUCTOR")
        self.assertEqual(state["next_full_survey_at"], DUE_AT)
        self.assertEqual(self.agent_calls(), [])
        before = self.state.read_bytes()

        early = self.run_controller(now=EARLY_AT)
        self.assertEqual(early.returncode, 0, early.stderr)
        self.assertEqual(self.agent_calls(), [])
        self.assertNotEqual(self.state.read_bytes(), before)
        self.assertEqual(self.state_json()["reason_code"], "NO_TRIGGER")

    def test_first_controller_baseline_suppresses_preexisting_collector_event(self) -> None:
        result = self.run_controller(now=BASELINE_AT, collector_mode="changed")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.agent_calls(), [])
        state = self.state_json()
        self.assertEqual(state["reason_code"], "BASELINE")
        self.assertEqual(state["collector_instance_id"], COLLECTOR_INSTANCE)
        self.assertEqual(state["collector_generation"], 1)
        self.assertEqual(state["collector_fingerprint"], fingerprint("b"))

    def test_changed_event_claims_once_launches_and_verifies_exact_owner(self) -> None:
        result = self.launch_change()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.agent_calls()
        self.assertEqual(len([row for row in calls if "launch" in row]), 1)
        self.assertEqual(len([row for row in calls if "show" in row]), 1)
        launch = calls[0]
        self.assertEqual(launch[:2], ["-p", "test-profile"])
        self.assertIn("--no-parent", launch)
        self.assertIn("--message-file", launch)
        self.assertIn("--json", launch)
        self.assertNotIn("SHOULD_NOT_EXIST", launch)
        state = self.state_json()
        self.assertEqual(state["owner_kind"], "SESSION")
        self.assertEqual(state["owner_session_id"], OWNER)
        self.assertEqual(state["lifecycle_state"], "ACTIVE")
        self.assertEqual(state["collector_generation"], 1)
        self.assertEqual(state["active_trigger"]["disposition"], "SUBMITTED")
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        prompt = json.loads(self.prompt_log.read_text().splitlines()[0])
        self.assertIn("KEEP", prompt)
        self.assertIn("NOT_VERIFIED", prompt)
        self.assertIn("never", prompt.lower())

    def test_due_occurrence_claims_once_and_launches(self) -> None:
        self.baseline()
        due = self.run_controller(now=DUE_AT)
        self.assertEqual(due.returncode, 0, due.stderr)
        self.assertEqual(len([row for row in self.agent_calls() if "launch" in row]), 1)
        state = self.state_json()
        self.assertEqual(state["active_trigger"]["kind"], "FULL_SURVEY")
        self.assertEqual(state["next_full_survey_at"], "2026-09-22T00:00:00Z")

    def test_duplicate_replayed_event_never_launches_or_sends_twice(self) -> None:
        self.assertEqual(self.launch_change().returncode, 0)
        before = self.agent_calls()
        state_before = self.state.read_bytes()
        replay = self.run_controller(
            now="2026-09-20T02:00:00Z",
            collector_mode="changed",
        )
        self.assertNotEqual(replay.returncode, 0)
        after = self.agent_calls()
        self.assertEqual(len([row for row in after if "launch" in row]), 1)
        self.assertEqual(len([row for row in after if "send" in row]), 0)
        self.assertEqual(len(after), len(before))
        self.assertEqual(self.state.read_bytes(), state_before)
        self.assertEqual(replay.stderr, "ERROR: COLLECTOR_EVENT_INVALID\n")

    def test_cyclic_replay_is_rejected_after_eviction_but_fresh_repeat_is_accepted(self) -> None:
        self.baseline()
        first = transition_event("a", "b", old_generation=0)
        launched = self.run_controller(
            now=EARLY_AT,
            collector_mode="changed",
            env={"COLLECTOR_EVENT": json.dumps(first, sort_keys=True)},
        )
        self.assertEqual(launched.returncode, 0, launched.stderr)
        first_trigger_id = self.state_json()["active_trigger"]["id"]

        old_label = "b"
        for index in range(1, 66):
            new_label = "a" if index == 65 else f"fingerprint-{index}"
            event = transition_event(
                old_label,
                new_label,
                old_generation=index,
            )
            result = self.run_controller(
                now="2026-09-20T02:00:00Z",
                collector_mode="changed",
                env={
                    "COLLECTOR_EVENT": json.dumps(event, sort_keys=True),
                    "SESSION_STATUS": "waiting",
                    "SESSION_SUBSTATE": "idle-at-empty-prompt",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            old_label = new_label

        cycled = self.state_json()
        self.assertEqual(cycled["collector_generation"], 66)
        self.assertEqual(cycled["collector_fingerprint"], fingerprint("a"))
        self.assertEqual(len(cycled["recent_triggers"]), 64)
        self.assertNotIn(
            first_trigger_id, {item["id"] for item in cycled["recent_triggers"]}
        )
        before = len([row for row in self.agent_calls() if "send" in row])
        state_before_replay = self.state.read_bytes()
        replay = self.run_controller(
            now="2026-09-20T03:00:00Z",
            collector_mode="changed",
            env={
                "COLLECTOR_EVENT": json.dumps(first, sort_keys=True),
                "SESSION_STATUS": "waiting",
                "SESSION_SUBSTATE": "idle-at-empty-prompt",
            },
        )
        self.assertNotEqual(replay.returncode, 0)
        after = len([row for row in self.agent_calls() if "send" in row])
        self.assertEqual(after, before)
        self.assertEqual(self.state.read_bytes(), state_before_replay)
        self.assertEqual(replay.stderr, "ERROR: COLLECTOR_EVENT_INVALID\n")

        fresh_repeat = transition_event("a", "b", old_generation=66)
        accepted = self.run_controller(
            now="2026-09-20T04:00:00Z",
            collector_mode="changed",
            env={
                "COLLECTOR_EVENT": json.dumps(fresh_repeat, sort_keys=True),
                "SESSION_STATUS": "waiting",
                "SESSION_SUBSTATE": "idle-at-empty-prompt",
            },
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        final = self.state_json()
        self.assertEqual(final["collector_generation"], 67)
        self.assertEqual(final["collector_fingerprint"], fingerprint("b"))
        self.assertNotEqual(final["active_trigger"]["id"], first_trigger_id)
        self.assertEqual(
            len([row for row in self.agent_calls() if "send" in row]), before + 1
        )

    def test_due_while_owner_runs_is_pending_then_dispatched_exactly_once(self) -> None:
        self.assertEqual(self.launch_change().returncode, 0)
        due = self.run_controller(now=DUE_AT)
        self.assertEqual(due.returncode, 0, due.stderr)
        state = self.state_json()
        self.assertEqual(state["pending_due_trigger"]["kind"], "FULL_SURVEY")
        self.assertEqual(state["pending_due_trigger"]["disposition"], "PENDING")
        self.assertEqual(state["next_full_survey_at"], DUE_AT)
        self.assertEqual(len([row for row in self.agent_calls() if "send" in row]), 0)

        delivered = self.run_controller(
            now="2026-09-21T01:00:00Z",
            collector_mode="changed",
            env={
                "COLLECTOR_EVENT": json.dumps(change_event("c"), sort_keys=True),
                "SESSION_STATUS": "waiting",
                "SESSION_SUBSTATE": "idle-at-empty-prompt",
            },
        )
        self.assertEqual(delivered.returncode, 0, delivered.stderr)
        state = self.state_json()
        self.assertIsNone(state["pending_due_trigger"])
        self.assertEqual(state["active_trigger"]["kind"], "FULL_SURVEY")
        self.assertIn(
            "COALESCED_FULL_SURVEY",
            {item["disposition"] for item in state["recent_triggers"]},
        )
        self.assertEqual(state["next_full_survey_at"], "2026-09-22T00:00:00Z")
        self.assertEqual(len([row for row in self.agent_calls() if "send" in row]), 1)

        later = self.run_controller(
            now="2026-09-21T02:00:00Z",
            env={
                "SESSION_STATUS": "waiting",
                "SESSION_SUBSTATE": "idle-at-empty-prompt",
            },
        )
        self.assertEqual(later.returncode, 0, later.stderr)
        self.assertEqual(len([row for row in self.agent_calls() if "send" in row]), 1)

    def test_no_change_event_evidence_is_rejected_and_visible(self) -> None:
        cases = {
            "equal-fingerprints": transition_event("same", "same"),
            "empty-delta": transition_event("old", "new", include_change=False),
        }
        for name, event in cases.items():
            with self.subTest(name=name):
                if self.state.exists():
                    self.state.unlink()
                lock = Path(str(self.state) + ".lock")
                if lock.exists():
                    lock.unlink()
                if self.agent_log.exists():
                    self.agent_log.unlink()
                self.baseline()
                before = self.state.read_bytes()
                result = self.run_controller(
                    now=EARLY_AT,
                    collector_mode="changed",
                    env={"COLLECTOR_EVENT": json.dumps(event, sort_keys=True)},
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.agent_calls(), [])
                self.assertEqual(self.state.read_bytes(), before)
                self.assertEqual(result.stderr, "ERROR: COLLECTOR_EVENT_INVALID\n")

    def test_invalid_occurrence_identity_and_generation_never_dispatch_or_advance(self) -> None:
        reversed_generation = transition_event("a", "b")
        reversed_generation["old_generation"] = 1
        reversed_generation["new_generation"] = 0
        boolean_old = transition_event("a", "b")
        boolean_old["old_generation"] = True
        boolean_new = transition_event("a", "b")
        boolean_new["new_generation"] = True
        wrong_type = transition_event("a", "b")
        wrong_type["old_generation"] = "0"
        v1_event = transition_event("a", "b")
        v1_event["event_version"] = 1
        unknown_event = transition_event("a", "b")
        unknown_event["event_version"] = 3
        cases = {
            "v1-event": v1_event,
            "unknown-event-version": unknown_event,
            "malformed-instance": transition_event(
                "a", "b", instance_id="0" * 31
            ),
            "instance-mismatch": transition_event(
                "a", "b", instance_id="f" * 32
            ),
            "generation-gap": transition_event("a", "b", old_generation=2),
            "generation-reversal": reversed_generation,
            "generation-negative": transition_event("a", "b", old_generation=-1),
            "generation-overflow": transition_event(
                "a", "b", old_generation=MAX_GENERATION
            ),
            "generation-boolean-old": boolean_old,
            "generation-boolean-new": boolean_new,
            "generation-wrong-type": wrong_type,
            "fingerprint-mismatch": transition_event("not-a", "b"),
        }
        for name, event in cases.items():
            with self.subTest(name=name):
                for path in (
                    self.state,
                    self.collector_state,
                    Path(str(self.state) + ".lock"),
                    self.agent_log,
                    self.prompt_log,
                ):
                    if path.exists():
                        path.unlink()
                self.baseline()
                before = self.state_json()
                before_bytes = self.state.read_bytes()
                result = self.run_controller(
                    now=EARLY_AT,
                    collector_mode="changed",
                    env={"COLLECTOR_EVENT": json.dumps(event, sort_keys=True)},
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(
                    [
                        row
                        for row in self.agent_calls()
                        if "launch" in row or "send" in row
                    ],
                    [],
                )
                after = self.state_json()
                self.assertEqual(self.state.read_bytes(), before_bytes)
                self.assertEqual(
                    (
                        after["collector_instance_id"],
                        after["collector_generation"],
                        after["collector_fingerprint"],
                    ),
                    (
                        before["collector_instance_id"],
                        before["collector_generation"],
                        before["collector_fingerprint"],
                    ),
                )
                self.assertEqual(result.stderr, "ERROR: COLLECTOR_EVENT_INVALID\n")

    def test_collector_instance_rollover_without_event_fails_closed(self) -> None:
        self.baseline()
        before = self.state.read_bytes()
        checkpoint = json.loads(self.collector_state.read_text(encoding="utf-8"))
        checkpoint["collector_instance_id"] = "f" * 32
        self.collector_state.write_text(json.dumps(checkpoint), encoding="utf-8")
        self.collector_state.chmod(0o600)

        result = self.run_controller(now=EARLY_AT)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "ERROR: COLLECTOR_EVENT_INVALID\n")
        self.assertEqual(self.state.read_bytes(), before)
        self.assertEqual(self.agent_calls(), [])

    def test_controller_state_rejects_v1_unknown_and_malformed_occurrence_fields(self) -> None:
        self.baseline()
        valid = self.state_json()
        cases = {
            "v1": ("format_version", 1),
            "unknown-version": ("format_version", 3),
            "boolean-version": ("format_version", True),
            "missing-instance": ("collector_instance_id", None),
            "short-instance": ("collector_instance_id", "0" * 31),
            "boolean-generation": ("collector_generation", True),
            "negative-generation": ("collector_generation", -1),
            "overflow-generation": (
                "collector_generation",
                MAX_GENERATION + 1,
            ),
            "string-generation": ("collector_generation", "0"),
            "boolean-fingerprint": ("collector_fingerprint", True),
        }
        for name, (field, value) in cases.items():
            with self.subTest(name=name):
                malformed = json.loads(json.dumps(valid))
                malformed[field] = value
                material = {
                    key: item
                    for key, item in malformed.items()
                    if key != "state_digest"
                }
                malformed["state_digest"] = hashlib.sha256(
                    json.dumps(
                        material,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    ).encode("ascii")
                ).hexdigest()
                self.state.write_text(json.dumps(malformed), encoding="utf-8")
                self.state.chmod(0o600)
                before = self.state.read_bytes()
                result = self.run_controller(now=EARLY_AT)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.state.read_bytes(), before)
                self.assertEqual(self.agent_calls(), [])

    def test_overlap_lock_and_active_owner_do_not_launch_another_session(self) -> None:
        self.baseline()
        lock = Path(str(self.state) + ".lock")
        with lock.open("r+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            overlap = self.run_controller(now=EARLY_AT, collector_mode="changed")
        self.assertNotEqual(overlap.returncode, 0)
        self.assertEqual(self.agent_calls(), [])

        self.assertEqual(
            self.run_controller(now=EARLY_AT, collector_mode="changed").returncode,
            0,
        )
        active = self.run_controller(
            now="2026-09-20T02:00:00Z",
            collector_mode="changed",
            env={"COLLECTOR_EVENT": json.dumps(change_event("c"), sort_keys=True)},
        )
        self.assertEqual(active.returncode, 0, active.stderr)
        calls = self.agent_calls()
        self.assertEqual(len([row for row in calls if "launch" in row]), 1)
        self.assertEqual(len([row for row in calls if "send" in row]), 0)
        self.assertEqual(self.state_json()["reason_code"], "ACTIVE_OWNER")

    def test_unknown_or_bogus_exact_owner_fails_closed(self) -> None:
        self.assertEqual(self.launch_change().returncode, 0)
        result = self.run_controller(
            now="2026-09-20T02:00:00Z",
            collector_mode="changed",
            env={
                "AGENT_MODE": "show-not-found",
                "COLLECTOR_EVENT": json.dumps(change_event("c"), sort_keys=True),
                "PRIVATE_SENTINEL": "SECRET-BOGUS-BODY",
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len([row for row in self.agent_calls() if "launch" in row]), 1)
        rendered = self.state.read_text() + result.stdout + result.stderr
        self.assertNotIn("SECRET-BOGUS-BODY", rendered)
        self.assertEqual(self.state_json()["reason_code"], "OWNER_NOT_VERIFIED")

    def test_launch_failure_and_malformed_launch_output_are_not_retried(self) -> None:
        for mode in ("launch-failure", "launch-malformed"):
            with self.subTest(mode=mode):
                if self.state.exists():
                    self.state.unlink()
                lock = Path(str(self.state) + ".lock")
                if lock.exists():
                    lock.unlink()
                if self.collector_state.exists():
                    self.collector_state.unlink()
                for log in (self.agent_log, self.collector_log, self.prompt_log):
                    if log.exists():
                        log.unlink()
                self.baseline()
                failed = self.run_controller(
                    now=EARLY_AT,
                    collector_mode="changed",
                    env={"AGENT_MODE": mode, "PRIVATE_SENTINEL": "SECRET-LAUNCH-BODY"},
                )
                self.assertNotEqual(failed.returncode, 0)
                self.assertEqual(self.state_json()["lifecycle_state"], "ESCALATED")
                retry = self.run_controller(
                    now="2026-09-20T02:00:00Z", collector_mode="changed"
                )
                self.assertNotEqual(retry.returncode, 0)
                self.assertEqual(
                    len([row for row in self.agent_calls() if "launch" in row]), 1
                )
                rendered = self.state.read_text() + failed.stdout + failed.stderr
                self.assertNotIn("SECRET-LAUNCH-BODY", rendered)

    def test_submission_uncertainty_is_visible_and_never_replaced(self) -> None:
        self.assertEqual(self.launch_change().returncode, 0)
        result = self.run_controller(
            now="2026-09-20T02:00:00Z",
            collector_mode="changed",
            env={
                "AGENT_MODE": "send-unverified",
                "SESSION_STATUS": "waiting",
                "SESSION_SUBSTATE": "idle-at-empty-prompt",
                "COLLECTOR_EVENT": json.dumps(change_event("c"), sort_keys=True),
            },
        )
        self.assertNotEqual(result.returncode, 0)
        calls = self.agent_calls()
        self.assertEqual(len([row for row in calls if "launch" in row]), 1)
        self.assertEqual(len([row for row in calls if "send" in row]), 1)
        state = self.state_json()
        self.assertEqual(state["lifecycle_state"], "ESCALATED")
        self.assertEqual(state["reason_code"], "DELIVERY_NOT_VERIFIED")

        later = self.run_controller(now="2026-09-20T03:00:00Z")
        self.assertNotEqual(later.returncode, 0)
        self.assertEqual(len([row for row in self.agent_calls() if "launch" in row]), 1)

    def test_restart_after_durable_claim_does_not_repeat_uncertain_launch(self) -> None:
        self.baseline()
        stopped = self.run_controller(
            now=EARLY_AT,
            collector_mode="changed",
            extra=["--test-stop-after-claim"],
        )
        self.assertNotEqual(stopped.returncode, 0)
        self.assertEqual(self.agent_calls(), [])
        self.assertEqual(self.state_json()["active_trigger"]["disposition"], "CLAIMED")

        restarted = self.run_controller(now="2026-09-20T02:00:00Z")
        self.assertNotEqual(restarted.returncode, 0)
        self.assertEqual(self.agent_calls(), [])
        self.assertEqual(self.state_json()["reason_code"], "CLAIM_RECOVERY_REQUIRED")

    def test_collector_failure_or_malformed_event_starts_no_turn_and_redacts_body(self) -> None:
        self.baseline()
        before = self.state.read_bytes()
        for mode in ("failure", "malformed-event"):
            with self.subTest(mode=mode):
                result = self.run_controller(
                    now=EARLY_AT,
                    collector_mode=mode,
                    env={"PRIVATE_SENTINEL": "SECRET-COLLECTOR-BODY"},
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.agent_calls(), [])
                self.assertNotIn("SECRET-COLLECTOR-BODY", result.stdout + result.stderr)
                self.assertNotIn("SECRET-COLLECTOR-BODY", self.state.read_text())
        self.assertNotEqual(self.state.read_bytes(), before)  # sanitized failure is durable

    def test_malformed_duplicate_oversized_and_unsafe_state_fail_without_launch(self) -> None:
        documents = (
            b"{not json",
            b'{"format_version":1,"format_version":1}\n',
            b" " * (MAX_STATE_BYTES + 1),
        )
        for index, body in enumerate(documents):
            with self.subTest(index=index):
                self.state.write_bytes(body)
                self.state.chmod(0o600)
                result = self.run_controller(now=BASELINE_AT)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.state.read_bytes(), body)
                self.assertEqual(self.agent_calls(), [])

        self.state.unlink()
        target = self.root / "target"
        target.write_text("do-not-change", encoding="utf-8")
        target.chmod(0o600)
        self.state.symlink_to(target)
        result = self.run_controller(now=BASELINE_AT)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_text(), "do-not-change")
        self.assertEqual(self.agent_calls(), [])

        self.state.unlink()
        self.state.write_text("{}\n", encoding="utf-8")
        self.state.chmod(0o644)
        before = self.state.read_bytes()
        result = self.run_controller(now=BASELINE_AT)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state.read_bytes(), before)

        self.state.unlink()
        real_parent = self.root / "real-parent"
        real_parent.mkdir(mode=0o700)
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        self.state = linked_parent / "controller.json"
        self.collector_state = linked_parent / "collector.json"
        result = self.run_controller(now=BASELINE_AT)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((real_parent / "controller.json").exists())
        self.assertFalse((real_parent / "controller.json.lock").exists())

    def test_atomic_failures_and_argv_injection_fail_closed(self) -> None:
        self.baseline()
        before = self.state.read_bytes()
        failed = self.run_controller(
            now=EARLY_AT,
            collector_mode="changed",
            extra=["--test-fail-write", "before-replace"],
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(self.state.read_bytes(), before)
        self.assertEqual(self.agent_calls(), [])

        after = self.run_controller(
            now=EARLY_AT,
            collector_mode="changed",
            extra=["--test-fail-write", "after-replace"],
        )
        self.assertNotEqual(after.returncode, 0)
        self.assertEqual(self.agent_calls(), [])
        self.assertEqual(self.state_json()["active_trigger"]["disposition"], "CLAIMED")
        self.assertFalse((self.workdir / "SHOULD_NOT_EXIST").exists())
        self.assertFalse((self.workdir / "SHOULD_NOT_EXIST_EITHER").exists())
        collector_argv = json.loads(self.collector_log.read_text().splitlines()[-1])
        self.assertIn(str(self.root / "repo;touch SHOULD_NOT_EXIST"), collector_argv)
        self.assertIn(str(self.root / "fs $(touch SHOULD_NOT_EXIST_EITHER)"), collector_argv)

    def test_state_contains_only_bounded_body_free_schema(self) -> None:
        sentinel = "SECRET-PROMPT-OUTPUT-TRANSCRIPT-PROVIDER-BODY"
        result = self.launch_change(env={"PRIVATE_SENTINEL": sentinel})
        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = self.state.read_text() + result.stdout + result.stderr
        self.assertNotIn(sentinel, rendered)
        self.assertNotIn(str(self.root), self.state.read_text())
        self.assertNotIn("command", self.state_json())
        self.assertLess(self.state.stat().st_size, MAX_STATE_BYTES)


class ModuleContractCase(unittest.TestCase):
    def test_module_is_disabled_by_default_linux_only_and_hardened(self) -> None:
        text = MODULE.read_text(encoding="utf-8")
        self.assertIn("mkEnableOption", text)
        self.assertIn("pkgs.stdenv.isLinux", text)
        self.assertIn("OnCalendar = \"hourly\"", text)
        self.assertIn("Persistent = true", text)
        self.assertIn("UMask = \"0077\"", text)
        self.assertIn("NoNewPrivileges = true", text)
        self.assertIn("ProtectSystem = \"strict\"", text)
        self.assertIn("ConditionFileIsExecutable", text)
        self.assertIn("TimeoutStartSec", text)
        self.assertIn('lib.replaceStrings [ "%" ] [ "%%" ]', text)
        self.assertNotIn("EnvironmentFile", text)

    def test_common_module_imports_maintenance_module(self) -> None:
        common = (REPO / "nix/modules/common.nix").read_text(encoding="utf-8")
        self.assertIn("./agent-deck-maintenance.nix", common)
        flake = (REPO / "nix/flake.nix").read_text(encoding="utf-8")
        self.assertIn("x86_64-linux.maintenance-runtime", flake)
        self.assertIn("/project/100%nice", flake)
        self.assertIn("--repo /project/100%%nice", flake)
        self.assertIn("systemd-analyze verify", flake)


if __name__ == "__main__":
    unittest.main()
