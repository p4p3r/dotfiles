#!/usr/bin/env python3
"""Focused acceptance tests for the report-only maintenance controller."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "private_dot_local/bin/private_executable_agent-deck-maintenance-controller"
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
CODEX_SESSION = "11111111-2222-4333-8444-555555555555"
TURN_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
RECEIPT_ID = "99999999-8888-4777-8666-555555555555"


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
        self.namespace = "v3-test-profile-report-only"
        self.state_root = self.root / "state" / self.namespace
        self.state_root.mkdir(parents=True, mode=0o700)
        self.state = self.state_root / "controller.json"
        self.collector_state = self.state_root / "collector.json"
        self.report_root = self.root / "reports" / self.namespace
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

                def emit_acceptance(session_id):
                    acceptance_case = os.environ.get("ACCEPTANCE_CASE", "accepted")
                    if acceptance_case in ("legacy-delivered", "legacy-unverified"):
                        delivery = (
                            "delivered"
                            if acceptance_case == "legacy-delivered"
                            else "unverified"
                        )
                        sys.stdout.write(json.dumps({{
                            "success": True,
                            "session_id": session_id,
                            "delivery": delivery,
                            "message": os.environ.get("PRIVATE_SENTINEL", "PRIVATE-BODY"),
                        }}))
                        raise SystemExit(0)
                    if acceptance_case == "indeterminate":
                        sys.stdout.write(json.dumps({{
                            "schema_version": 1,
                            "success": False,
                            "acceptance": "indeterminate",
                            "code": "ACCEPTANCE_INDETERMINATE",
                            "instance_id": session_id,
                            "delivery": "delivered",
                            "submitted": False,
                        }}))
                        raise SystemExit(1)
                    if acceptance_case == "ambiguous":
                        sys.stdout.write(
                            '{{"schema_version":1,"success":false,'
                            '"acceptance":"indeterminate",'
                            '"code":"ACCEPTANCE_INDETERMINATE",'
                            '"instance_id":"' + session_id + '",'
                            '"instance_id":"{OTHER_OWNER}"}}'
                        )
                        raise SystemExit(1)
                    if acceptance_case == "missing-id":
                        sys.stdout.write(json.dumps({{
                            "schema_version": 1,
                            "success": False,
                            "acceptance": "not_accepted",
                            "code": "INVALID_OPTIONS",
                        }}))
                        raise SystemExit(1)
                    if acceptance_case == "malformed":
                        sys.stdout.write(json.dumps({{
                            "schema_version": 1,
                            "success": "not-a-boolean",
                            "instance_id": session_id,
                        }}))
                        raise SystemExit(1)
                    if acceptance_case == "invalid-json":
                        sys.stdout.write("{{not-json")
                        raise SystemExit(1)
                    accepted_turn = {{
                        "receipt_id": "{RECEIPT_ID}",
                        "instance_id": session_id,
                        "codex_session_id": "{CODEX_SESSION}",
                        "turn_generation": "{CODEX_SESSION}:{TURN_ID}",
                        "accepted_at": "2026-09-20T01:00:00.123456789Z",
                    }}
                    payload = {{
                        "schema_version": 1,
                        "success": True,
                        "acceptance": "accepted",
                        "instance_id": session_id,
                        "delivery": "submitted",
                        "submitted": True,
                        "accepted_turn_kind": "codex_rollout",
                        "accepted_turn": accepted_turn,
                    }}
                    if acceptance_case == "mismatched-owner":
                        accepted_turn["instance_id"] = "{OTHER_OWNER}"
                    elif acceptance_case == "mismatched-session":
                        accepted_turn["codex_session_id"] = "22222222-3333-4444-8555-666666666666"
                    elif acceptance_case == "mismatched-generation":
                        accepted_turn["turn_generation"] = "{CODEX_SESSION}:../not-exact"
                    elif acceptance_case == "body-bearing":
                        payload["message"] = os.environ.get("PRIVATE_SENTINEL", "PRIVATE-BODY")
                    elif acceptance_case == "oversized":
                        payload["padding"] = "X" * 3000
                    sys.stdout.write(json.dumps(payload))
                    raise SystemExit(0)

                mode = os.environ.get("AGENT_MODE", "ok")
                if "launch" in argv:
                    if mode == "launch-failure":
                        sys.stderr.write(os.environ.get("PRIVATE_SENTINEL", "PRIVATE-BODY"))
                        raise SystemExit(1)
                    if mode == "launch-malformed":
                        sys.stdout.write(os.environ.get("PRIVATE_SENTINEL", "PRIVATE-BODY"))
                        raise SystemExit(0)
                    session_id = os.environ.get("LAUNCH_ID", "{OWNER}")
                    emit_acceptance(session_id)

                if "show" in argv:
                    session_id = argv[argv.index("show") + 1]
                    if session_id == "00000000-0000000000":
                        if mode == "show-bogus-valid":
                            sys.stdout.write(json.dumps({{"id": session_id, "status": "waiting"}}))
                            raise SystemExit(0)
                        sys.stdout.write(json.dumps({{"success": False, "code": "NOT_FOUND"}}))
                        raise SystemExit(2)
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
                    if mode == "send-failure":
                        sys.stderr.write(os.environ.get("PRIVATE_SENTINEL", "PRIVATE-BODY"))
                        raise SystemExit(1)
                    if mode == "send-unverified":
                        os.environ["ACCEPTANCE_CASE"] = "legacy-unverified"
                    emit_acceptance(session_id)
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
        if env and env.get("SESSION_STATUS") in {"waiting", "idle"}:
            self.write_report(env.get("REPORT_CASE", "valid"))
        command = [
            sys.executable,
            str(SCRIPT),
            "--state",
            str(self.state),
            "--collector-state",
            str(self.collector_state),
            "--state-namespace",
            self.namespace,
            "--report-root",
            str(self.report_root),
            "--collector",
            str(self.collector),
            "--agent-deck",
            str(self.agent_deck),
            "--codex-executable",
            str(self.root / "managed codex;touch SHOULD_NOT_EXIST_CODEX"),
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

    def write_report(self, case: str = "valid") -> None:
        if case == "missing" or not self.state.exists():
            return
        active = self.state_json().get("active_trigger")
        if not active or active.get("disposition") != "SUBMITTED":
            return
        self.report_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.report_root.chmod(0o700)
        alias = active["alias"]
        body = b"STATUS: COMPLETE\nOUTCOME: report-only inspection\n"
        body_path = self.report_root / f"{alias}.md"
        body_path.write_bytes(body)
        body_path.chmod(0o600)
        envelope = {
            "schema_version": 1,
            "trigger_alias": alias if case != "wrong-trigger" else "trigger-" + "0" * 64,
            "owner_session_id": OWNER if case != "wrong-owner" else OTHER_OWNER,
            "status": "COMPLETE",
            "report_ref": f"{alias}.md" if case != "wrong-ref" else "../other.md",
            "report_digest": fingerprint("wrong") if case == "digest-mismatch" else hashlib.sha256(body).hexdigest(),
            "completed_at": active["claimed_at"],
            "result_code": "SURVEY_RETAINED" if case != "bad-result" else "../../bad",
        }
        if case == "needs-user":
            envelope["status"] = "NEEDS_USER"
        envelope_path = self.report_root / f"{alias}.json"
        envelope_path.write_text(
            "{invalid" if case == "malformed" else json.dumps(envelope), encoding="utf-8"
        )
        envelope_path.chmod(0o600)
        if case == "world-readable":
            envelope_path.chmod(0o644)

    def agent_calls(self) -> list[list[str]]:
        if not self.agent_log.exists():
            return []
        return [json.loads(line) for line in self.agent_log.read_text().splitlines()]

    def reset_runtime(self) -> None:
        for path in (
            self.state,
            self.collector_state,
            Path(str(self.state) + ".lock"),
            self.agent_log,
            self.collector_log,
            self.prompt_log,
        ):
            if path.exists() or path.is_symlink():
                path.unlink()
        if self.report_root.exists():
            for path in self.report_root.iterdir():
                path.unlink()

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
        self.assertEqual(state["format_version"], 3)
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

    def test_changed_event_claims_once_and_requires_exact_acceptance(self) -> None:
        result = self.launch_change()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.agent_calls()
        self.assertEqual(len([row for row in calls if "launch" in row]), 1)
        self.assertEqual(len([row for row in calls if "show" in row]), 2)
        self.assertEqual(len([row for row in calls if "send" in row]), 0)
        launch = calls[0]
        self.assertEqual(launch[:2], ["-p", "test-profile"])
        self.assertIn("--no-parent", launch)
        self.assertIn("--message-file", launch)
        self.assertEqual(launch[launch.index("--message-file") + 1], "-")
        self.assertEqual(
            launch[launch.index("--cmd") + 1],
            f"'{self.root}/managed codex;touch SHOULD_NOT_EXIST_CODEX' "
            "--dangerously-bypass-approvals-and-sandbox",
        )
        self.assertEqual(launch.count("--acceptance-only"), 1)
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
        prompt_lines = self.prompt_log.read_text().splitlines()
        self.assertEqual(len(prompt_lines), 1)
        prompt = json.loads(prompt_lines[0])
        self.assertIn("KEEP", prompt)
        self.assertIn("NOT_VERIFIED", prompt)
        self.assertIn("never", prompt.lower())

    def test_accepted_launch_requires_exact_created_owner_before_submission(self) -> None:
        result = self.launch_change(env={"AGENT_MODE": "show-mismatch"})
        self.assertNotEqual(result.returncode, 0)
        calls = self.agent_calls()
        self.assertEqual(len([row for row in calls if "launch" in row]), 1)
        self.assertEqual(len([row for row in calls if "show" in row]), 2)
        self.assertEqual(len([row for row in calls if "send" in row]), 0)
        state = self.state_json()
        self.assertIsNone(state["owner_session_id"])
        self.assertEqual(state["unverified_session_id"], OWNER)
        self.assertEqual(state["active_trigger"]["disposition"], "NOT_VERIFIED")
        self.assertEqual(state["reason_code"], "OWNER_NOT_VERIFIED")

    def test_launch_success_without_accepted_turn_never_submits_or_retries(self) -> None:
        result = self.launch_change(env={"ACCEPTANCE_CASE": "indeterminate"})
        self.assertNotEqual(result.returncode, 0)
        calls = self.agent_calls()
        self.assertEqual(len([row for row in calls if "launch" in row]), 1)
        self.assertEqual(len([row for row in calls if "send" in row]), 0)
        state = self.state_json()
        self.assertIsNone(state["owner_session_id"])
        self.assertEqual(state["unverified_session_id"], OWNER)
        self.assertEqual(state["active_trigger"]["disposition"], "NOT_VERIFIED")
        self.assertEqual(state["reason_code"], "DELIVERY_NOT_VERIFIED")

        later = self.run_controller(now="2026-09-20T02:00:00Z")
        self.assertNotEqual(later.returncode, 0)
        later_calls = self.agent_calls()
        self.assertEqual(
            len([row for row in later_calls if "launch" in row]),
            len([row for row in calls if "launch" in row]),
        )
        self.assertEqual(
            len([row for row in later_calls if "send" in row]),
            len([row for row in calls if "send" in row]),
        )

    def test_existing_owner_legacy_delivered_result_is_not_verified(self) -> None:
        self.assertEqual(self.launch_change().returncode, 0)
        result = self.run_controller(
            now="2026-09-20T02:00:00Z",
            collector_mode="changed",
            env={
                "ACCEPTANCE_CASE": "legacy-delivered",
                "COLLECTOR_EVENT": json.dumps(change_event("c"), sort_keys=True),
                "SESSION_STATUS": "waiting",
                "SESSION_SUBSTATE": "idle-at-empty-prompt",
            },
        )
        self.assertNotEqual(result.returncode, 0)
        calls = self.agent_calls()
        self.assertEqual(len([row for row in calls if "launch" in row]), 1)
        self.assertEqual(len([row for row in calls if "send" in row]), 1)
        self.assertEqual(
            self.state_json()["active_trigger"]["disposition"], "NOT_VERIFIED"
        )

    def test_existing_owner_exact_receipt_submits_once_and_binds_owner(self) -> None:
        self.assertEqual(self.launch_change().returncode, 0)
        result = self.run_controller(
            now="2026-09-20T02:00:00Z",
            collector_mode="changed",
            env={
                "COLLECTOR_EVENT": json.dumps(change_event("c"), sort_keys=True),
                "SESSION_STATUS": "waiting",
                "SESSION_SUBSTATE": "idle-at-empty-prompt",
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.agent_calls()
        sends = [row for row in calls if "send" in row]
        self.assertEqual(len(sends), 1)
        for send in sends:
            send_at = send.index("send")
            self.assertEqual(send[send_at + 1], OWNER)
            self.assertEqual(send.count("--acceptance-only"), 1)
        state = self.state_json()
        self.assertEqual(state["owner_session_id"], OWNER)
        self.assertEqual(state["active_trigger"]["disposition"], "SUBMITTED")
        self.assertEqual(state["reason_code"], "TRIGGER_SUBMITTED")

    def test_invalid_acceptance_receipts_fail_closed_without_replacement(self) -> None:
        cases = {
            "ambiguous": None,
            "missing-id": None,
            "mismatched-owner": OWNER,
            "mismatched-session": OWNER,
            "mismatched-generation": OWNER,
            "malformed": OWNER,
            "invalid-json": None,
            "oversized": None,
            "body-bearing": OWNER,
        }
        for acceptance_case, retained_id in cases.items():
            with self.subTest(acceptance_case=acceptance_case):
                self.reset_runtime()
                result = self.launch_change(
                    env={
                        "ACCEPTANCE_CASE": acceptance_case,
                        "PRIVATE_SENTINEL": "SECRET-RECEIPT-BODY",
                    }
                )
                self.assertNotEqual(result.returncode, 0)
                calls = self.agent_calls()
                self.assertEqual(len([row for row in calls if "launch" in row]), 1)
                self.assertEqual(len([row for row in calls if "send" in row]), 0)
                state = self.state_json()
                self.assertIsNone(state["owner_session_id"])
                self.assertEqual(state["unverified_session_id"], retained_id)
                self.assertEqual(
                    state["active_trigger"]["disposition"], "NOT_VERIFIED"
                )
                rendered = self.state.read_text() + result.stdout + result.stderr
                self.assertNotIn("SECRET-RECEIPT-BODY", rendered)
                later = self.run_controller(now="2026-09-20T02:00:00Z")
                self.assertNotEqual(later.returncode, 0)
                later_calls = self.agent_calls()
                self.assertEqual(
                    len([row for row in later_calls if "launch" in row]),
                    len([row for row in calls if "launch" in row]),
                )
                self.assertEqual(
                    len([row for row in later_calls if "send" in row]),
                    len([row for row in calls if "send" in row]),
                )

    def test_due_occurrence_claims_once_and_launches(self) -> None:
        self.baseline()
        due = self.run_controller(now=DUE_AT)
        self.assertEqual(due.returncode, 0, due.stderr)
        self.assertEqual(len([row for row in self.agent_calls() if "launch" in row]), 1)
        state = self.state_json()
        self.assertEqual(state["active_trigger"]["kind"], "FULL_SURVEY")
        self.assertEqual(state["next_full_survey_at"], "2026-09-22T00:00:00Z")

    def test_terminal_report_verifies_exact_owner_and_returns_to_waiting(self) -> None:
        self.assertEqual(self.launch_change().returncode, 0)
        active = self.state_json()["active_trigger"]
        self.assertEqual(active["owner_session_id"], OWNER)
        self.assertRegex(active["alias"], r"^trigger-[0-9a-f]{64}$")
        completed = self.run_controller(
            now="2026-09-20T02:00:00Z",
            env={"SESSION_STATUS": "waiting", "SESSION_SUBSTATE": "idle-at-empty-prompt"},
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        state = self.state_json()
        self.assertEqual(state["lifecycle_state"], "WAITING")
        self.assertIsNone(state["active_trigger"])
        self.assertEqual(state["result_status"], "COMPLETE")
        self.assertEqual(state["result_code"], "SURVEY_RETAINED")
        self.assertEqual(state["report_ref"], active["alias"] + ".md")
        self.assertEqual(state["handoff_ref"], active["alias"] + ".json")
        self.assertEqual(stat.S_IMODE(self.report_root.stat().st_mode), 0o700)
        self.assertTrue(all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in self.report_root.iterdir()))
        self.assertNotIn(str(self.report_root), self.state.read_text())
        self.assertEqual(len([row for row in self.agent_calls() if "send" in row]), 0)

    def test_terminal_report_faults_escalate_without_retry(self) -> None:
        for case in (
            "missing", "malformed", "wrong-owner", "wrong-trigger", "digest-mismatch",
            "wrong-ref", "bad-result", "world-readable",
        ):
            with self.subTest(case=case):
                self.reset_runtime()
                self.assertEqual(self.launch_change().returncode, 0)
                failed = self.run_controller(
                    now="2026-09-20T02:00:00Z",
                    env={
                        "SESSION_STATUS": "waiting",
                        "SESSION_SUBSTATE": "idle-at-empty-prompt",
                        "REPORT_CASE": case,
                    },
                )
                self.assertEqual(failed.returncode, 77, failed.stderr)
                state = self.state_json()
                self.assertEqual(state["lifecycle_state"], "ESCALATED")
                self.assertEqual(state["reason_code"], "REPORT_NOT_VERIFIED")
                self.assertEqual(state["active_trigger"]["disposition"], "NOT_VERIFIED")
                self.assertIsNone(state["report_ref"])
                later = self.run_controller(now="2026-09-20T03:00:00Z")
                self.assertEqual(later.returncode, 77, later.stderr)
                self.assertEqual(len([row for row in self.agent_calls() if "launch" in row]), 1)
                self.assertEqual(len([row for row in self.agent_calls() if "send" in row]), 0)

    def test_verified_noncomplete_report_retains_owner_and_escalates(self) -> None:
        self.assertEqual(self.launch_change().returncode, 0)
        result = self.run_controller(
            now="2026-09-20T02:00:00Z",
            env={
                "SESSION_STATUS": "waiting",
                "SESSION_SUBSTATE": "idle-at-empty-prompt",
                "REPORT_CASE": "needs-user",
            },
        )
        self.assertEqual(result.returncode, 77, result.stderr)
        state = self.state_json()
        self.assertEqual(state["lifecycle_state"], "ESCALATED")
        self.assertEqual(state["result_status"], "NEEDS_USER")
        self.assertEqual(state["active_trigger"]["disposition"], "REPORTED")
        self.assertEqual(state["owner_session_id"], OWNER)
        self.assertIsNotNone(state["report_digest"])

    def test_report_timeout_and_invalid_session_control_escalate(self) -> None:
        self.assertEqual(self.launch_change().returncode, 0)
        timeout = self.run_controller(now="2026-09-21T02:00:00Z")
        self.assertEqual(timeout.returncode, 77, timeout.stderr)
        self.assertEqual(self.state_json()["reason_code"], "REPORT_TIMEOUT")
        self.reset_runtime()
        invalid = self.launch_change(env={"AGENT_MODE": "show-bogus-valid"})
        self.assertEqual(invalid.returncode, 77, invalid.stderr)
        self.assertEqual(self.state_json()["reason_code"], "OWNER_NOT_VERIFIED")
        shows = [row for row in self.agent_calls() if "show" in row]
        self.assertEqual(len(shows), 1)
        self.assertEqual(shows[0][shows[0].index("show") + 1], "00000000-0000000000")

    def test_profile_namespace_and_old_state_are_fail_closed(self) -> None:
        old_root = self.root / "state"
        old_files = {
            "controller.json": b'{"profile_alias":"fixture","overdue":true}\n',
            "collector.json": b'{"generation":0,"profile":"fixture"}\n',
            "controller.json.lock": b"",
        }
        for name, body in old_files.items():
            old_path = old_root / name
            old_path.write_bytes(body)
            old_path.chmod(0o600)
        self.baseline()
        for name, body in old_files.items():
            self.assertEqual((old_root / name).read_bytes(), body)
        self.assertEqual(self.state_json()["profile_alias"], "test-profile")
        self.assertEqual(self.state_json()["state_namespace"], self.namespace)
        before = self.state.read_bytes()
        mismatch = self.run_controller(now=EARLY_AT, extra=["--profile", "other-profile"])
        self.assertEqual(mismatch.returncode, 70)
        self.assertEqual(self.state.read_bytes(), before)
        traversal = self.run_controller(
            now=EARLY_AT,
            extra=["--report-root", str(self.root / "reports" / ".." / self.namespace)],
        )
        self.assertEqual(traversal.returncode, 70)
        self.assertEqual(self.state.read_bytes(), before)
        self.reset_runtime()
        self.collector_state.write_bytes(b'{"profile":"fixture"}\n')
        self.collector_state.chmod(0o600)
        reused = self.run_controller(now=BASELINE_AT)
        self.assertEqual(reused.returncode, 70)
        self.assertFalse(self.state.exists())
        self.assertEqual(self.collector_state.read_bytes(), b'{"profile":"fixture"}\n')

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
                self.reset_runtime()
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
            "unknown-version": ("format_version", 4),
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


class ReportFileSafetyCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.path = self.root / "report.md"
        self.path.write_bytes(b"ORIGINAL")
        self.path.chmod(0o600)
        controller = runpy.run_path(str(SCRIPT))
        self.read_report_file = controller["read_report_file"]
        self.ControllerError = controller["ControllerError"]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_mode_drift_after_open_is_rejected(self) -> None:
        real_open = os.open
        opened = []

        def drift(path: Path, flags: int) -> int:
            descriptor = real_open(path, flags)
            opened.append(descriptor)
            os.fchmod(descriptor, 0o644)
            return descriptor

        with mock.patch("os.open", side_effect=drift):
            with self.assertRaises(self.ControllerError):
                self.read_report_file(self.path, 64)
        self.assertEqual(len(opened), 1)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o644)

    def test_retained_path_replacement_during_read_is_rejected(self) -> None:
        before = self.path.stat()
        replacement = self.root / "replacement.md"
        replacement.write_bytes(b"REPLACED")
        replacement.chmod(0o600)
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        real_read = os.read
        replaced = []

        def swap(descriptor: int, length: int) -> bytes:
            part = real_read(descriptor, length)
            if part and not replaced:
                os.replace(self.path, self.root / "previous.md")
                os.replace(replacement, self.path)
                replaced.append(True)
            return part

        with mock.patch("os.read", side_effect=swap):
            with self.assertRaises(self.ControllerError):
                self.read_report_file(self.path, 64)
        self.assertTrue(replaced)
        after = self.path.stat()
        self.assertNotEqual(after.st_ino, before.st_ino)
        self.assertEqual((after.st_size, after.st_mtime_ns), (before.st_size, before.st_mtime_ns))

    def test_open_descriptor_metadata_drift_during_read_is_rejected(self) -> None:
        for drift_kind in ("mode", "size", "mtime"):
            with self.subTest(drift_kind=drift_kind):
                self.path.write_bytes(b"ORIGINAL")
                self.path.chmod(0o600)
                real_read = os.read
                drifted = []

                def drift(descriptor: int, length: int) -> bytes:
                    part = real_read(descriptor, length)
                    if part and not drifted:
                        if drift_kind == "mode":
                            os.fchmod(descriptor, 0o644)
                        elif drift_kind == "size":
                            os.truncate(self.path, 0)
                        else:
                            info = os.fstat(descriptor)
                            os.utime(self.path, ns=(info.st_atime_ns, info.st_mtime_ns + 1))
                        drifted.append(True)
                    return part

                with mock.patch("os.read", side_effect=drift):
                    with self.assertRaises(self.ControllerError):
                        self.read_report_file(self.path, 64)
                self.assertTrue(drifted)


class ModuleContractCase(unittest.TestCase):
    def test_module_repository_source_paths_exist(self) -> None:
        text = MODULE.read_text(encoding="utf-8")
        source_paths = re.findall(r"\$\{(\.\./\.\./[^}]+)\}", text)
        self.assertTrue(source_paths, "expected repository source path interpolations")
        for source_path in source_paths:
            with self.subTest(source_path=source_path):
                self.assertTrue((MODULE.parent / source_path).is_file())

    def test_public_maintenance_surface_contains_no_host_specific_material(self) -> None:
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        section = readme.split("## Report-only maintenance runtime", 1)[1]
        section = section.split("\n## ", 1)[0]
        public_surface = "\n".join(
            (
                SCRIPT.read_text(encoding="utf-8"),
                CHARTER.read_text(encoding="utf-8"),
                section,
            )
        )
        forbidden_patterns = {
            "local user path": r"/(?:home|Users)/(?!example(?:/|\b))[^\s\"']+",
            "private hostname": r"\b[a-z0-9][a-z0-9-]{1,62}\.(?:internal|local|lan|corp)\b",
            "private repository label": r"\b[a-z0-9][a-z0-9._-]*-(?:private|internal)\b",
            "provider or workspace ID": (
                r"\b[TWCG](?=[A-Z0-9]{8,}\b)(?=[A-Z0-9]*[0-9])"
                r"[A-Z0-9]{8,}\b"
            ),
            "provider token": r"(?:xox[baprs]-|gh[pousr]_|AKIA[0-9A-Z]{16})",
        }
        for label, pattern in forbidden_patterns.items():
            with self.subTest(label=label):
                flags = 0 if label == "provider or workspace ID" else re.IGNORECASE
                self.assertIsNone(re.search(pattern, public_surface, flags))

    def test_module_is_disabled_by_default_linux_only_and_portably_hardened(self) -> None:
        text = MODULE.read_text(encoding="utf-8")
        self.assertIn("mkEnableOption", text)
        self.assertIn("pkgs.stdenv.isLinux", text)
        self.assertIn("OnCalendar = \"hourly\"", text)
        self.assertIn("Persistent = true", text)
        self.assertIn("UMask = \"0077\"", text)
        self.assertIn("NoNewPrivileges = true", text)
        self.assertIn("ProtectControlGroups = true", text)
        self.assertIn("ProtectKernelTunables = true", text)
        self.assertIn("ProtectSystem = \"strict\"", text)
        self.assertIn("RestrictRealtime = true", text)
        self.assertIn("RestrictSUIDSGID = true", text)
        self.assertIn("LockPersonality = true", text)
        self.assertIn('SystemCallArchitectures = "native"', text)
        for directive in (
            "PrivateDevices",
            "ProtectClock",
            "ProtectKernelLogs",
            "ProtectKernelModules",
        ):
            with self.subTest(directive=directive):
                self.assertNotIn(f"{directive} = true", text)
        self.assertIn("ConditionFileIsExecutable", text)
        self.assertIn("codexExecutable", text)
        self.assertIn('"--codex-executable"', text)
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
