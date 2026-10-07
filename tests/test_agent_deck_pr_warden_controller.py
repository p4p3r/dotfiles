#!/usr/bin/env python3
"""Isolated acceptance tests for the fake-only PR-warden controller."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
CONTROLLER = REPO / "private_dot_local/bin/private_executable_agent-deck-pr-warden-controller"
PROVIDER = REPO / "tests/fixtures/agent_deck_pr_warden/fake_github_facts.py"
NOW = "2030-01-01T00:00:00Z"
OWNER = "0123abcd-1700000000"
OBJECT = "a" * 52
URL_MARKER = "fixture-sensitive.invalid/object/7"


INGRESS = r'''#!/usr/bin/env python3
import fcntl, json, os, sys
from pathlib import Path

def write(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)

args = sys.argv[1:]
if len(args) < 3 or args[0] != "--socket":
    raise SystemExit(64)
path = Path(args[1])
lock = path.with_suffix(path.suffix + ".fake-lock")
fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
with os.fdopen(fd, "r+") as held:
    fcntl.flock(held.fileno(), fcntl.LOCK_EX)
    ledger = json.loads(path.read_text(encoding="utf-8"))
    calls = path.with_suffix(path.suffix + ".calls")
    history = json.loads(calls.read_text(encoding="utf-8")) if calls.exists() else []
    op = args[2]
    history.append({"op": op, "alias": args[3] if len(args) > 3 and op != "list" else None})
    write(calls, history)
    if op == "list" and args[3:] == ["--limit", "100"]:
        reply = {"code": "OK", "rows": ledger["rows"][:100]}
    elif op == "claim" and len(args) == 4:
        row = next((item for item in ledger["rows"] if item["event_alias"] == args[3]), None)
        if row is not None and row["state"] == "accepted":
            row["state"], row["claimed_at"] = "claimed", "2030-01-01T00:00:00.000Z"
            reply = {"code": "CLAIMED"}
        else:
            reply = {"code": "CONFLICT"}
        write(path, ledger)
    elif op == "settle" and len(args) == 6 and args[4] == "--result":
        row = next((item for item in ledger["rows"] if item["event_alias"] == args[3]), None)
        result = args[5]
        if row is not None and row["state"] == "claimed" and result in {"completed", "api_unavailable", "indeterminate"}:
            row["state"] = "completed" if result == "completed" else "uncertain"
            row["result"], row["settled_at"] = result, "2030-01-01T00:00:01.000Z"
            reply = {"code": "SETTLED"}
        else:
            reply = {"code": "CONFLICT"}
        write(path, ledger)
    else:
        reply = {"code": "INVALID"}
print(json.dumps(reply, separators=(",", ":")))
raise SystemExit(0 if reply["code"] in {"OK", "CLAIMED", "SETTLED"} else 1)
'''


AGENT = r'''#!/usr/bin/env python3
import json, os, re, sys, uuid
from pathlib import Path

root = Path(__file__).resolve().parent
state_path = root / "agent-state.json"
calls_path = root / "agent-calls.json"
state = json.loads(state_path.read_text(encoding="utf-8"))
calls = json.loads(calls_path.read_text(encoding="utf-8")) if calls_path.exists() else []
args = sys.argv[1:]
stdin = sys.stdin.buffer.read().decode("utf-8", errors="strict")
op = "unknown"
if "launch" in args: op = "launch"
elif "send" in args: op = "send"
elif "show" in args: op = "show"
elif "archive" in args: op = "archive"
alias_match = re.search(r"^TRIGGER_ALIAS: (.+)$", stdin, re.MULTILINE)
calls.append({"op": op, "alias": alias_match.group(1) if alias_match else None, "stdin_bytes": len(stdin.encode())})
calls_path.write_text(json.dumps(calls, sort_keys=True), encoding="utf-8")
calls_path.chmod(0o600)

owner = state["owner"]
if op in {"launch", "send"}:
    if state.get("write_result", True):
        location = re.search(r"^RESULT_LOCATION: (.+)$", stdin, re.MULTILINE).group(1)
        alias = alias_match.group(1)
        object_alias = re.search(r"^OBJECT_ALIAS: (.+)$", stdin, re.MULTILINE).group(1)
        result = {
            "schema_version": 1, "trigger_alias": alias, "object_alias": object_alias,
            "owner_session_id": owner, "status": state.get("result_status", "COMPLETE"),
            "result_code": state.get("result_code", "CURRENT_FACTS_READY"),
            "completed_at": state.get("result_completed_at", "2030-01-01T00:00:00Z"),
            "provider_code": "READY",
            "local_git_code": "READY",
        }
        path = Path(location)
        path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
        path.chmod(0o600)
    mode = state.get("acceptance", "accepted")
    accepted = mode == "accepted" or state.get("unsafe_indeterminate_shape", False)
    payload = {
        "schema_version": 1, "success": accepted, "acceptance": mode,
        "instance_id": owner, "delivery": "submitted" if accepted else "unknown",
        "submitted": accepted, "accepted_turn_kind": "codex_rollout" if accepted else "none",
        "accepted_turn": {
            "receipt_id": str(uuid.UUID("00000000-0000-4000-8000-000000000001")),
            "instance_id": owner, "codex_session_id": "fixture-codex-session",
            "turn_generation": "fixture-codex-session:fixture-turn", "accepted_at": "2030-01-01T00:00:00Z",
        },
    }
    if op == "send":
        ledger = json.loads((root.parent / "ingress-ledger.json").read_text(encoding="utf-8"))
        calls[-1]["ledger_state_at_send"] = next(
            (row["state"] for row in ledger["rows"] if row["event_alias"] == calls[-1]["alias"]),
            "missing",
        )
        calls_path.write_text(json.dumps(calls, sort_keys=True), encoding="utf-8")
        calls_path.chmod(0o600)
    print(json.dumps(payload, separators=(",", ":")))
    raise SystemExit(0)
if op == "show":
    target = args[args.index("show") + 1]
    statuses = state.get("show_statuses", [])
    status = statuses.pop(0) if statuses else state["status"]
    if "show_statuses" in state:
        state["show_statuses"] = statuses
        state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        state_path.chmod(0o600)
    print(json.dumps({"id": "ffffffff-1700000001" if state.get("wrong_show_id") else target,
                      "profile": "fixture-profile", "status": status, "substate": ""}))
    raise SystemExit(0)
if op == "archive":
    if not state.get("archive_success", True):
        raise SystemExit(1)
    state["status"] = "stopped"
    state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    state_path.chmod(0o600)
    print(json.dumps({"id": owner, "archived": True}, separators=(",", ":")))
    raise SystemExit(0)
raise SystemExit(64)
'''


LOCAL = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

request = json.loads(sys.stdin.buffer.read())
fixture_path = Path(request["fixture"])
fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
binding = request["binding"]
mode = fixture["mode"]
if mode == "MALFORMED":
    sys.stdout.write("{")
    raise SystemExit(0)
value = {
    "schema_version": 1, "code": "OK",
    "head_repository_id": binding["head_repository_id"], "head_ref": binding["head_ref"],
    "head_sha": fixture["head_sha"], "remote_name": binding["remote_name"],
    "remote_url": binding["remote_url"], "dirty": mode == "DIRTY",
    "untracked": mode == "UNTRACKED", "unpushed": mode == "UNPUSHED",
    "observed_at": "2030-01-01T00:00:00Z",
}
if mode == "IDENTITY_MISMATCH": value["remote_name"] = "other"
print(json.dumps(value, separators=(",", ":")))
'''


def write_json(path: Path, value: object, mode: int = 0o600) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    path.chmod(mode)


class WardenCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        for name in ("bin", "worktree"):
            (self.root / name).mkdir(mode=0o700)
        self.ingress = self.make_executable("fake-ingress", INGRESS)
        self.agent = self.make_executable("fake-agent-deck", AGENT)
        self.codex = self.make_executable("fake-codex", "#!/bin/sh\nexit 0\n")
        self.local = self.make_executable("fake-local-git", LOCAL)
        self.provider = self.root / "bin/fake-github-facts"
        provider_source = PROVIDER.read_text(encoding="utf-8").replace(
            "#!/usr/bin/env python3", f"#!{sys.executable}", 1
        )
        self.provider.write_text(provider_source, encoding="utf-8")
        self.provider.chmod(0o700)
        self.ledger = self.root / "ingress-ledger.json"
        write_json(self.ledger, {"rows": []})
        self.agent_state = self.root / "bin/agent-state.json"
        self.agent_calls = self.root / "bin/agent-calls.json"
        write_json(self.agent_state, {
            "owner": OWNER, "status": "waiting", "acceptance": "accepted",
            "write_result": True, "archive_success": True,
        })
        self.provider_fixture = self.root / "provider.json"
        self.local_fixture = self.root / "local.json"
        self.set_provider("OK")
        self.set_local("OK")
        self.config_path = self.root / "config.json"
        self.config = self.configuration()
        write_json(self.config_path, self.config)
        self.environment = os.environ.copy()
        self.environment.update({
            "HOME": str(self.root), "XDG_CONFIG_HOME": str(self.root / "xdg-config"),
            "XDG_STATE_HOME": str(self.root / "xdg-state"),
            "XDG_RUNTIME_DIR": str(self.root / "xdg-runtime"),
            "TMPDIR": str(self.root / "tmp"), "PYTHONDONTWRITEBYTECODE": "1",
        })

    def make_executable(self, name: str, source: str) -> Path:
        path = self.root / "bin" / name
        if source.startswith("#!/usr/bin/env python3"):
            source = source.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1)
        path.write_text(source, encoding="utf-8")
        path.chmod(0o700)
        return path

    def configuration(self) -> dict[str, object]:
        return {
            "schema_version": 1, "service_instance": "fixture-instance", "work_id": "fixture-work",
            "owner": {"host": "fixture-host", "conductor": "0123abcd-1700000000"},
            "paths": {
                "state_dir": str(self.root / "state"), "runtime_dir": str(self.root / "runtime"),
                "result_dir": str(self.root / "results"), "handoff_dir": str(self.root / "handoffs"),
            },
            "agent_deck": {
                "executable": str(self.agent), "profile": "fixture-profile",
                "codex_executable": str(self.codex), "work_directory": str(self.root / "worktree"),
                "start_timeout_seconds": 5, "wake_timeout_seconds": 5, "parent_policy": "NO_PARENT",
            },
            "ingress": {
                "executable": str(self.ingress), "socket": str(self.ledger),
                "owner_host": "fixture-host", "owner_conductor": "0123abcd-1700000000",
                "provider": "github", "event": "pull_request", "object_alias": OBJECT,
            },
            "lifecycle": {
                "specialist_kind": "pr-warden", "repository_id": 1001, "pull_request_id": 3001,
                "pull_request_number": 7, "url": "https://" + URL_MARKER,
                "deadline": "2030-01-03T00:00:00Z", "next_check_at": NOW,
                "retention": "RETAIN", "rotation": {
                    "context_measurement": "UNAVAILABLE", "owner_age_at": "2030-01-02T00:00:00Z",
                    "health_failure_limit": 3,
                },
            },
            "binding": {
                "head_repository_id": 1001, "head_ref": "refs/heads/fixture-branch",
                "worktree": str(self.root / "worktree"), "remote_name": "origin",
                "remote_url": "https://fixture.invalid/repository.git",
            },
            "provider": {
                "kind": "FAKE", "executable": str(self.provider), "fixture": str(self.provider_fixture),
                "timeout_seconds": 5,
            },
            "local_git": {
                "kind": "FAKE", "executable": str(self.local), "fixture": str(self.local_fixture),
                "timeout_seconds": 5,
            },
            "authority": {
                "read_only": True, "edit": False, "push": False, "comment": False, "reply": False,
                "resolve_thread": False, "bot_request": False, "body_rewrite": False, "merge": False,
                "close": False, "enqueue": False, "force_push": False, "branch_delete": False,
                "deploy": False, "takeover": False,
            },
        }

    def set_provider(self, mode: str, *, state: str = "OPEN") -> None:
        write_json(self.provider_fixture, {
            "schema_version": 1, "mode": mode, "state": state, "draft": False,
            "head_sha": "1" * 40, "mergeability": "MERGEABLE", "review_decision": "APPROVED",
            "check_counts": {"pending": 0, "success": 2, "failure": 0, "total": 2},
            "unresolved_review_threads": 0, "updated_at": NOW, "observed_at": NOW,
        })

    def set_local(self, mode: str, sha: str = "1" * 40) -> None:
        write_json(self.local_fixture, {"schema_version": 1, "mode": mode, "head_sha": sha})

    def invoke(
        self, command: str, *, stop: str | None = None, controller: Path = CONTROLLER,
        now: str = NOW,
    ) -> subprocess.CompletedProcess[str]:
        argv = [sys.executable, str(controller), "--config", str(self.config_path), "--now", now]
        if stop is not None:
            argv += ["--test-stop-after", stop]
        argv.append(command)
        return subprocess.run(argv, capture_output=True, text=True, timeout=20, env=self.environment, check=False)

    def mutant(self, replacements: list[tuple[str, str]]) -> Path:
        source = CONTROLLER.read_text(encoding="utf-8")
        for old, new in replacements:
            self.assertEqual(source.count(old), 1, old)
            source = source.replace(old, new, 1)
        path = self.root / "bin/mutated-controller"
        path.write_text(source, encoding="utf-8")
        path.chmod(0o700)
        return path

    def admit(self) -> None:
        result = self.invoke("admit")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state()["lifecycle_state"], "WAITING")

    def state(self) -> dict[str, object]:
        return json.loads((self.root / "state/lifecycle.json").read_text(encoding="utf-8"))

    def ledger_value(self) -> dict[str, object]:
        return json.loads(self.ledger.read_text(encoding="utf-8"))

    def agent_history(self) -> list[dict[str, object]]:
        if not self.agent_calls.exists():
            return []
        return json.loads(self.agent_calls.read_text(encoding="utf-8"))

    def ingress_history(self) -> list[dict[str, object]]:
        path = self.ledger.with_suffix(self.ledger.suffix + ".calls")
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def update_agent(self, **values: object) -> None:
        state = json.loads(self.agent_state.read_text(encoding="utf-8"))
        state.update(values)
        write_json(self.agent_state, state)

    def add_event(
        self, alias: str = "b" * 52, *, object_alias: str = OBJECT,
        owner_host: str = "fixture-host", owner_conductor: str = "0123abcd-1700000000",
        action: str = "synchronize",
    ) -> None:
        ledger = self.ledger_value()
        ledger["rows"].append({
            "version": 2, "provider": "github", "event": "pull_request", "action": action,
            "event_alias": alias, "object_type": "pull_request", "object_alias": object_alias,
            "owner_host": owner_host, "owner_conductor": owner_conductor,
            "received_at": "2030-01-01T00:00:00.000Z", "accepted_at": "2030-01-01T00:00:00.000Z",
            "claimed_at": None, "settled_at": None, "state": "accepted", "result": "none",
        })
        write_json(self.ledger, ledger)

    def test_exact_admission_duplicate_and_private_artifacts(self) -> None:
        self.admit()
        state = self.state()
        self.assertEqual(state["owner_session_id"], OWNER)
        self.assertEqual(state["owner_kind"], "SESSION")
        duplicate = self.invoke("admit")
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn("DUPLICATE_ADMISSION", duplicate.stderr)
        self.assertEqual([call["op"] for call in self.agent_history()].count("launch"), 1)
        for directory in ("state", "runtime", "results", "handoffs"):
            path = self.root / directory
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
            for artifact in path.iterdir():
                self.assertEqual(stat.S_IMODE(artifact.stat().st_mode), 0o600)

    def test_running_admission_reconciles_before_event_delivery(self) -> None:
        for command in ("reconcile", "tick"):
            with self.subTest(command=command):
                self.tearDown()
                self.setUp()
                self.update_agent(show_statuses=["running", "waiting"])
                admitted = self.invoke("admit")
                self.assertEqual(admitted.returncode, 0, admitted.stdout + admitted.stderr)
                state = self.state()
                self.assertEqual(state["lifecycle_state"], "ACTIVE")
                self.assertEqual(state["current_trigger"]["disposition"], "SUBMITTED")
                self.add_event()

                reconciled = self.invoke(command, now="2030-01-01T00:00:01Z")
                self.assertEqual(reconciled.returncode, 0, reconciled.stdout + reconciled.stderr)
                state = self.state()
                self.assertEqual(state["lifecycle_state"], "WAITING")
                self.assertEqual(state["current_trigger"]["disposition"], "COMPLETED")
                self.assertEqual(self.ledger_value()["rows"][0]["state"], "accepted")
                self.assertEqual(len([call for call in self.agent_history() if call["op"] == "send"]), 0)

                self.update_agent(result_completed_at="2030-01-01T00:00:02Z")
                self.assertEqual(self.invoke("tick", now="2030-01-01T00:00:02Z").returncode, 0)
                self.assertEqual(self.ledger_value()["rows"][0]["state"], "completed")
                sends = [call for call in self.agent_history() if call["op"] == "send"]
                self.assertEqual(len(sends), 1)
                self.assertEqual(sends[0]["alias"], "b" * 52)

                turns = [call for call in self.agent_history() if call["op"] in {"launch", "send"}]
                self.assertEqual(self.invoke("reconcile", now="2030-01-01T00:00:03Z").returncode, 0)
                self.assertEqual(
                    [call for call in self.agent_history() if call["op"] in {"launch", "send"}], turns,
                )

    def test_running_admission_reconcile_mutation_is_observable(self) -> None:
        self.update_agent(show_statuses=["running", "waiting"])
        admitted = self.invoke("admit")
        self.assertEqual(admitted.returncode, 0, admitted.stdout + admitted.stderr)
        skips_admission = self.mutant([(
            "        return finish_admission(config, state, state_path, now_text)\n",
            "        return None  # mutation: admission reconciliation removed\n",
        )])
        reconciled = self.invoke(
            "reconcile", controller=skips_admission, now="2030-01-01T00:00:01Z",
        )
        self.assertEqual(reconciled.returncode, 0, reconciled.stdout + reconciled.stderr)
        self.assertEqual(self.state()["lifecycle_state"], "ACTIVE")
        self.assertEqual(self.state()["current_trigger"]["disposition"], "SUBMITTED")
        self.assertEqual(len([call for call in self.agent_history() if call["op"] == "send"]), 0)

    def test_unchanged_heartbeat_creates_no_turn(self) -> None:
        self.admit()
        before = len(self.agent_history())
        result = self.invoke("tick")
        self.assertEqual(result.returncode, 0, result.stderr)
        history = self.agent_history()[before:]
        self.assertEqual([call["op"] for call in history], ["show"])
        self.assertEqual(self.state()["reason_code"], "NO_TRIGGER")

    def test_delivery_duplicate_and_reordered_events_use_one_owner_serially(self) -> None:
        self.admit()
        self.add_event("c" * 52, action="closed")
        self.add_event("b" * 52, action="opened")
        for _ in range(2):
            result = self.invoke("tick")
            self.assertEqual(result.returncode, 0, result.stderr)
        rows = self.ledger_value()["rows"]
        self.assertTrue(all(row["state"] == "completed" for row in rows))
        sends = [call for call in self.agent_history() if call["op"] == "send"]
        self.assertEqual([call["alias"] for call in sends], ["c" * 52, "b" * 52])
        self.assertEqual(self.state()["owner_session_id"], OWNER)
        # A replay is represented by the same immutable row, so another tick has no turn.
        self.assertEqual(self.invoke("tick").returncode, 0)
        self.assertEqual(len([call for call in self.agent_history() if call["op"] == "send"]), 2)

    def test_competing_ticks_have_one_claim_and_one_send(self) -> None:
        self.admit()
        self.add_event()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.invoke("tick"), range(2)))
        self.assertTrue(all(item.returncode in {0, 75} for item in results))
        self.assertEqual(len([call for call in self.agent_history() if call["op"] == "send"]), 1)
        self.assertEqual(len([call for call in self.ingress_history() if call["op"] == "claim"]), 1)

    def test_crash_before_claim_is_retryable_without_prior_wake(self) -> None:
        self.admit()
        self.add_event()
        self.assertEqual(self.invoke("tick", stop="before-claim").returncode, 78)
        self.assertEqual(self.ledger_value()["rows"][0]["state"], "accepted")
        self.assertFalse(any(call["op"] == "send" for call in self.agent_history()))
        self.assertEqual(self.invoke("tick").returncode, 0)
        self.assertEqual(len([call for call in self.agent_history() if call["op"] == "send"]), 1)

    def test_crash_after_claim_before_lifecycle_write_never_sends(self) -> None:
        self.admit()
        self.add_event()
        self.assertEqual(self.invoke("tick", stop="after-claim").returncode, 78)
        self.assertEqual(self.invoke("reconcile").returncode, 77)
        self.assertEqual(self.state()["reason_code"], "CLAIM_RECOVERY_REQUIRED")
        self.assertFalse(any(call["op"] == "send" for call in self.agent_history()))

    def test_crash_after_lifecycle_claim_before_send_never_sends(self) -> None:
        self.admit()
        self.add_event()
        self.assertEqual(self.invoke("tick", stop="after-trigger-write").returncode, 78)
        self.assertEqual(self.invoke("reconcile").returncode, 77)
        self.assertEqual(self.state()["reason_code"], "CLAIM_RECOVERY_REQUIRED")
        self.assertFalse(any(call["op"] == "send" for call in self.agent_history()))

    def test_crash_after_send_before_receipt_becomes_uncertain_without_resend(self) -> None:
        self.admit()
        self.add_event()
        self.assertEqual(self.invoke("tick", stop="after-send").returncode, 78)
        self.assertEqual(self.invoke("reconcile").returncode, 77)
        row = self.ledger_value()["rows"][0]
        self.assertEqual((row["state"], row["result"]), ("uncertain", "indeterminate"))
        self.assertEqual(len([call for call in self.agent_history() if call["op"] == "send"]), 1)

    def test_crash_after_result_and_after_settle_reconcile_forward(self) -> None:
        for stop in ("after-result", "after-settle"):
            with self.subTest(stop=stop):
                self.tearDown()
                self.setUp()
                self.admit()
                self.add_event()
                self.assertEqual(self.invoke("tick", stop=stop).returncode, 78)
                self.assertEqual(self.invoke("reconcile").returncode, 0)
                self.assertEqual(self.ledger_value()["rows"][0]["state"], "completed")
                self.assertEqual(self.state()["lifecycle_state"], "WAITING")
                self.assertEqual(len([call for call in self.agent_history() if call["op"] == "send"]), 1)

    def test_wrong_ingress_owner_object_and_session_fail_closed(self) -> None:
        self.admit()
        self.add_event(owner_host="other-host")
        self.assertEqual(self.invoke("tick").returncode, 77)
        self.assertEqual(self.state()["reason_code"], "WRONG_INGRESS_OWNER")
        self.assertEqual(self.ledger_value()["rows"][0]["state"], "accepted")
        self.assertFalse(any(call["op"] == "send" for call in self.agent_history()))

        self.tearDown(); self.setUp(); self.admit()
        self.add_event(object_alias="z" * 52)
        self.assertEqual(self.invoke("tick").returncode, 0)
        self.assertEqual(self.ledger_value()["rows"][0]["state"], "accepted")

        self.tearDown(); self.setUp(); self.admit(); self.add_event()
        self.update_agent(wrong_show_id=True)
        self.assertEqual(self.invoke("tick").returncode, 77)
        self.assertEqual(self.state()["reason_code"], "OWNER_NOT_VERIFIED")
        self.assertEqual(self.ledger_value()["rows"][0]["state"], "accepted")

    def test_provider_outage_malformed_identity_stale_and_dirty(self) -> None:
        fixtures = (
            ("API_UNAVAILABLE", "OK", "uncertain", "api_unavailable", "API_UNAVAILABLE"),
            ("MALFORMED", "OK", "uncertain", "indeterminate", "FACTS_NOT_VERIFIED"),
            ("IDENTITY_MISMATCH", "OK", "uncertain", "indeterminate", "FACTS_NOT_VERIFIED"),
            ("STALE_HEAD", "OK", "completed", "completed", "STALE_HEAD"),
            ("OK", "DIRTY", "completed", "completed", "DIRTY_BRANCH"),
            ("OK", "UNTRACKED", "completed", "completed", "DIRTY_BRANCH"),
            ("OK", "UNPUSHED", "completed", "completed", "DIRTY_BRANCH"),
        )
        for provider_mode, local_mode, row_state, result_code, reason in fixtures:
            with self.subTest(provider=provider_mode, local=local_mode):
                self.tearDown(); self.setUp(); self.admit(); self.add_event()
                self.set_provider(provider_mode)
                self.set_local(local_mode)
                self.assertEqual(self.invoke("tick").returncode, 77)
                row = self.ledger_value()["rows"][0]
                self.assertEqual((row["state"], row["result"]), (row_state, result_code))
                self.assertEqual(self.state()["reason_code"], reason)
                self.assertEqual(self.state()["lifecycle_state"], "ESCALATED")

    def test_uncertain_wake_busy_and_stopped_owner(self) -> None:
        self.admit(); self.add_event(); self.update_agent(acceptance="indeterminate")
        self.assertEqual(self.invoke("tick").returncode, 77)
        self.assertEqual(self.ledger_value()["rows"][0]["result"], "indeterminate")
        self.assertEqual(self.invoke("reconcile").returncode, 77)
        self.assertEqual(len([call for call in self.agent_history() if call["op"] == "send"]), 1)

        self.tearDown(); self.setUp(); self.admit(); self.add_event(); self.update_agent(status="running")
        self.assertEqual(self.invoke("tick").returncode, 0)
        self.assertEqual(self.ledger_value()["rows"][0]["state"], "accepted")
        self.assertFalse(any(call["op"] == "send" for call in self.agent_history()))

        self.tearDown(); self.setUp(); self.admit(); self.add_event(); self.update_agent(status="stopped")
        self.assertEqual(self.invoke("tick").returncode, 77)
        self.assertEqual(self.state()["reason_code"], "OWNER_TERMINAL")
        self.assertEqual(self.ledger_value()["rows"][0]["state"], "accepted")
        self.assertFalse(any(call["op"] == "send" for call in self.agent_history()))

    def test_merged_archive_clears_owner_only_after_exact_confirmation(self) -> None:
        self.admit(); self.add_event(); self.set_provider("OK", state="MERGED")
        self.assertEqual(self.invoke("tick").returncode, 0)
        state = self.state()
        self.assertEqual(state["lifecycle_state"], "ARCHIVED")
        self.assertEqual(state["owner_kind"], "NONE")
        self.assertIsNone(state["owner_session_id"])
        self.assertIn("archive", [call["op"] for call in self.agent_history()])

        self.tearDown(); self.setUp(); self.admit(); self.add_event(); self.set_provider("OK", state="MERGED")
        self.update_agent(archive_success=False)
        self.assertEqual(self.invoke("tick").returncode, 77)
        state = self.state()
        self.assertEqual(state["owner_session_id"], OWNER)
        self.assertNotEqual(state["lifecycle_state"], "ARCHIVED")

        self.tearDown(); self.setUp(); self.admit(); self.add_event(); self.set_provider("OK", state="MERGED")
        self.assertEqual(self.invoke("tick", stop="before-archive").returncode, 78)
        before = self.state()
        self.assertEqual(before["owner_session_id"], OWNER)
        self.assertEqual(before["lifecycle_state"], "WAITING")
        self.assertEqual(self.invoke("reconcile").returncode, 0)
        self.assertEqual(self.state()["lifecycle_state"], "ARCHIVED")

    def test_closed_unmerged_never_archives(self) -> None:
        self.admit(); self.add_event(); self.set_provider("OK", state="CLOSED")
        self.assertEqual(self.invoke("tick").returncode, 77)
        self.assertEqual(self.state()["reason_code"], "CLOSED_UNMERGED")
        self.assertEqual(self.state()["owner_session_id"], OWNER)
        self.assertNotIn("archive", [call["op"] for call in self.agent_history()])

    def test_list_bound_starvation_is_not_absence(self) -> None:
        self.admit()
        for index in range(100):
            alphabet = "bcdefghijklmnopqrstuvwxyz234567"
            alias = alphabet[index % len(alphabet)] * 51 + alphabet[(index // len(alphabet)) % len(alphabet)]
            self.add_event(alias, object_alias="z" * 52)
        self.assertEqual(self.invoke("tick").returncode, 77)
        self.assertEqual(self.state()["reason_code"], "LIST_BOUND_NOT_VERIFIED")
        self.assertFalse(any(call["op"] == "send" for call in self.agent_history()))

    def test_missing_result_settles_uncertainty_and_never_retries(self) -> None:
        self.admit(); self.add_event(); self.update_agent(write_result=False)
        self.assertEqual(self.invoke("tick").returncode, 77)
        self.assertEqual(self.state()["reason_code"], "RESULT_NOT_VERIFIED")
        self.assertEqual(self.ledger_value()["rows"][0]["result"], "indeterminate")
        self.assertEqual(self.invoke("reconcile").returncode, 77)
        self.assertEqual(len([call for call in self.agent_history() if call["op"] == "send"]), 1)

    def test_body_log_argv_isolation_and_owner_modes(self) -> None:
        self.admit(); self.add_event(); self.assertEqual(self.invoke("tick").returncode, 0)
        approved = {self.config_path, self.provider_fixture}
        inspected = 0
        for path in self.root.rglob("*"):
            if not path.is_file() or path in approved or path.name.startswith("fake-"):
                continue
            inspected += 1
            self.assertNotIn(URL_MARKER.encode(), path.read_bytes(), str(path))
        self.assertGreater(inspected, 5)
        for directory in (self.root / "state", self.root / "runtime", self.root / "results", self.root / "handoffs"):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            for path in directory.iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        source = CONTROLLER.read_text(encoding="utf-8")
        self.assertNotIn("requests", source)
        self.assertNotIn("urllib", source)
        self.assertGreater(source.count("UNAVAILABLE"), 0)

    def test_live_provider_and_authority_expansion_are_rejected(self) -> None:
        for mutate in (
            lambda value: value["provider"].__setitem__("kind", "GITHUB"),
            lambda value: value["authority"].__setitem__("push", True),
            lambda value: value["agent_deck"].__setitem__("parent_policy", "DIRECT_PARENT"),
        ):
            config = copy.deepcopy(self.config)
            mutate(config)
            write_json(self.config_path, config)
            result = self.invoke("admit")
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.root / "state/lifecycle.json").exists())

    def test_targeted_mutations_are_killed_by_narrow_fixtures(self) -> None:
        # Claim moved after send: the fake observes the row still accepted at delivery time.
        self.admit(); self.add_event()
        moved_claim = self.mutant([
            ('    claim(config, row["event_alias"])\n', '    pass  # mutation: claim delayed\n'),
            ('    if test_stop(args, "after-send"):\n',
             '    claim(config, row["event_alias"])  # mutation: after send\n'
             '    if test_stop(args, "after-send"):\n'),
        ])
        self.invoke("tick", controller=moved_claim)
        send = [call for call in self.agent_history() if call["op"] == "send"][-1]
        self.assertEqual(send["ledger_state_at_send"], "accepted")

        # An indeterminate acceptance with otherwise plausible fields must remain uncertain.
        self.tearDown(); self.setUp(); self.admit(); self.add_event()
        self.update_agent(acceptance="indeterminate", unsafe_indeterminate_shape=True)
        accepts_indeterminate = self.mutant([
            ('value["acceptance"] == "accepted"', 'value["acceptance"] in {"accepted", "indeterminate"}'),
        ])
        self.invoke("tick", controller=accepts_indeterminate)
        self.assertEqual(self.ledger_value()["rows"][0]["state"], "completed")

        # Retrying an ATTEMPTED trigger produces a second exact-owner send.
        self.tearDown(); self.setUp(); self.admit(); self.add_event()
        self.assertEqual(self.invoke("tick", stop="after-send").returncode, 78)
        retry = self.mutant([(
            '    if trigger["disposition"] == "ATTEMPTED":\n'
            '        return uncertain_trigger(config, state, state_path, now_text)\n',
            '    if trigger["disposition"] == "ATTEMPTED":\n'
            '        deck = config["agent_deck"]\n'
            '        run_command([deck["executable"], "-p", deck["profile"], "session", "send", '
            'state["owner_session_id"], "--message-file", "-", "--acceptance-only", "--json", '
            '"--timeout", f"{deck[\'wake_timeout_seconds\']}s"], deck["wake_timeout_seconds"] + 5, '
            'prompt(config, trigger["event_alias"], admission=False))\n'
            '        return uncertain_trigger(config, state, state_path, now_text)\n',
        )])
        self.invoke("reconcile", controller=retry)
        self.assertEqual(len([call for call in self.agent_history() if call["op"] == "send"]), 2)

        # Removing the owner comparison permits a foreign-owner row to wake the specialist.
        self.tearDown(); self.setUp(); self.admit(); self.add_event(owner_host="other-host")
        no_owner_match = self.mutant([(
            'row["owner_host"] == expected["owner_host"]', 'True  # mutation: owner ignored',
        )])
        self.invoke("tick", controller=no_owner_match)
        self.assertTrue(any(call["op"] == "send" for call in self.agent_history()))

        # Ignoring the fresh provider/local head comparison incorrectly returns to WAITING.
        self.tearDown(); self.setUp(); self.admit(); self.add_event(); self.set_provider("STALE_HEAD")
        trusts_stale = self.mutant([(
            'elif facts["head_sha"] != local["head_sha"]:',
            'elif False and facts["head_sha"] != local["head_sha"]:  # mutation',
        )])
        self.invoke("tick", controller=trusts_stale)
        self.assertEqual(self.state()["lifecycle_state"], "WAITING")

        # Dropping dirty refusal likewise turns unsafe branch evidence into a clean disposition.
        self.tearDown(); self.setUp(); self.admit(); self.add_event(); self.set_local("DIRTY")
        ignores_dirty = self.mutant([(
            'elif local_code == "DIRTY_BRANCH":',
            'elif False and local_code == "DIRTY_BRANCH":  # mutation',
        )])
        self.invoke("tick", controller=ignores_dirty)
        self.assertEqual(self.state()["lifecycle_state"], "WAITING")

        # Adding a send to the no-trigger branch makes an unchanged heartbeat spend a turn.
        self.tearDown(); self.setUp(); self.admit()
        heartbeat_send = self.mutant([(
            '        state["reason_code"] = "NO_TRIGGER"\n',
            '        deck = config["agent_deck"]\n'
            '        run_command([deck["executable"], "-p", deck["profile"], "session", "send", owner, '
            '"--message-file", "-", "--acceptance-only", "--json", "--timeout", '
            'f"{deck[\'wake_timeout_seconds\']}s"], deck["wake_timeout_seconds"] + 5, '
            'prompt(config, admission_alias(config), admission=False))\n'
            '        state["reason_code"] = "NO_TRIGGER"\n',
        )])
        self.invoke("tick", controller=heartbeat_send)
        self.assertTrue(any(call["op"] == "send" for call in self.agent_history()))

        # Clearing ownership before archive confirmation persists a false ARCHIVED state on failure.
        self.tearDown(); self.setUp(); self.admit(); self.add_event(); self.set_provider("OK", state="MERGED")
        self.update_agent(archive_success=False)
        early_clear = self.mutant([(
            '    deck = config["agent_deck"]\n'
            '    try:\n'
            '        result = run_command(\n'
            '            [deck["executable"], "-p", deck["profile"], "session", "archive", owner, "--json"],\n',
            '    deck = config["agent_deck"]\n'
            '    state["owner_kind"] = "NONE"\n'
            '    state["owner_session_id"] = None\n'
            '    state["lifecycle_state"] = "ARCHIVED"\n'
            '    state["archived_at"] = now_text\n'
            '    write_state(state_path, state, config)\n'
            '    try:\n'
            '        result = run_command(\n'
            '            [deck["executable"], "-p", deck["profile"], "session", "archive", owner, "--json"],\n',
        )])
        self.invoke("tick", controller=early_clear)
        self.assertEqual(self.state()["lifecycle_state"], "ARCHIVED")
        self.assertIsNone(self.state()["owner_session_id"])


class SourceContractCase(unittest.TestCase):
    def test_required_guards_and_mutation_targets_are_nonempty(self) -> None:
        source = CONTROLLER.read_text(encoding="utf-8")
        targets = {
            "claim-before-send": 'claim(config, row["event_alias"])',
            "reject-indeterminate": 'value["acceptance"] == "accepted"',
            "no-retry-after-attempt": 'trigger["disposition"] == "ATTEMPTED"',
            "owner-object-match": 'row["owner_host"] == expected["owner_host"]',
            "fresh-head": 'facts["head_sha"] != local["head_sha"]',
            "dirty-refusal": 'local_code == "DIRTY_BRANCH"',
            "unchanged-heartbeat": 'state["reason_code"] = "NO_TRIGGER"',
            "archive-before-clear": 'payload.get("id") == owner and payload.get("archived") is True',
            "admission-running-reconcile": "return finish_admission(config, state, state_path, now_text)",
        }
        self.assertEqual(len(targets), 9)
        for name, marker in targets.items():
            with self.subTest(mutation=name):
                self.assertEqual(source.count(marker), 1)
                mutated = source.replace(marker, "MUTATION_REMOVED_GUARD", 1)
                self.assertNotIn(marker, mutated)
                self.assertNotEqual(mutated, source)

    def test_public_candidate_has_only_synthetic_identity_material(self) -> None:
        paths = (
            CONTROLLER,
            REPO / "nix/modules/agent-deck-pr-warden.nix",
            REPO / "docs/agent-deck-pr-warden.md",
            PROVIDER,
        )
        public_surface = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        forbidden = {
            "local user path": r"/(?:home|Users)/(?!example(?:/|\b)|fixture(?:/|\b))[^\s\"']+",
            "private hostname": r"\b[a-z0-9][a-z0-9-]{1,62}\.(?:internal|local|lan|corp)\b",
            "provider token": r"(?:xox[baprs]-|gh[pousr]_|AKIA[0-9A-Z]{16})",
        }
        for label, pattern in forbidden.items():
            with self.subTest(label=label):
                self.assertIsNone(re.search(pattern, public_surface, re.IGNORECASE))
        self.assertTrue(CONTROLLER.name.startswith("private_executable_"))


if __name__ == "__main__":
    unittest.main()
