#!/usr/bin/env python3
"""Focused acceptance tests for the host-local Agent Deck work registry."""

from __future__ import annotations

import fcntl
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
SCRIPT = REPO / "private_dot_local/bin/executable_agent-deck-work-registry"
NOW = "2026-09-15T12:00:00Z"
OWNER_A = "0123abcd-1700000000"
OWNER_B = "89abcdef-1700000001"
MAX_STATE_BYTES = 1_048_576


class RegistryCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.chmod(self.root, 0o700)
        self.state = self.root / "registry.json"
        self.argv_log = self.root / "argv.jsonl"
        self.stub = self.root / "agent-deck-stub"
        self.stub.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                import time

                with open(os.environ["STUB_ARGV_LOG"], "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(sys.argv[1:]) + "\\n")
                mode = os.environ.get("STUB_MODE", "ok")
                if mode == "timeout":
                    time.sleep(5)
                if mode == "failure":
                    sys.stderr.write(os.environ.get("STUB_SECRET", "private-error-body"))
                    raise SystemExit(int(os.environ.get("STUB_EXIT", "1")))
                if mode == "missing":
                    raise SystemExit(2)
                if mode == "invalid-utf8":
                    sys.stdout.buffer.write(b"\\xff\\xfe")
                    raise SystemExit(0)
                if mode == "raw":
                    sys.stdout.write(os.environ["STUB_RAW"])
                    raise SystemExit(0)
                owner = sys.argv[sys.argv.index("show") + 1]
                status_map = json.loads(os.environ.get("STUB_STATUS_MAP", "{}"))
                status = status_map.get(owner, os.environ.get("STUB_STATUS", "running"))
                payload = {
                    "id": os.environ.get("STUB_RETURN_ID", owner),
                    "status": status,
                    "substate": os.environ.get("STUB_SUBSTATE", "running"),
                    "title": "mutable-title",
                    "path": "/private/repository",
                    "output": os.environ.get("STUB_SECRET", "SENTINEL-SECRET-BODY"),
                }
                sys.stdout.write(json.dumps(payload))
                """
            ),
            encoding="utf-8",
        )
        self.stub.chmod(0o700)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_registry(
        self,
        *args: str,
        env: dict[str, str] | None = None,
        now: str = NOW,
        timeout: float = 10,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(SCRIPT),
            "--state",
            str(self.state),
            "--now",
            now,
            "--agent-deck",
            str(self.stub),
            *args,
        ]
        proc_env = os.environ.copy()
        proc_env["STUB_ARGV_LOG"] = str(self.argv_log)
        if env:
            proc_env.update(env)
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=proc_env,
        )

    def register(
        self,
        work_id: str = "work-a",
        owner: str = OWNER_A,
        deadline: str = "2026-09-16T12:00:00Z",
    ) -> subprocess.CompletedProcess[str]:
        return self.run_registry(
            "register",
            work_id,
            "--owner-session-id",
            owner,
            "--deadline",
            deadline,
        )

    def read_state(self) -> dict[str, object]:
        return json.loads(self.state.read_text(encoding="utf-8"))

    @staticmethod
    def sized_record(work_id: str) -> dict[str, object]:
        return {
            "work_id": work_id,
            "owner_session_id": OWNER_A,
            "requested_status": "ACTIVE",
            "observed_status": "NOT_CHECKED",
            "observed_substate": "NONE",
            "deadline": "2026-09-16T12:00:00Z",
            "last_checked_at": None,
            "reason_code": "REGISTERED",
        }

    @staticmethod
    def encoded_state(state: dict[str, object]) -> bytes:
        return (json.dumps(state, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()

    def maximal_state(self) -> dict[str, object]:
        def candidate(count: int) -> dict[str, object]:
            records = {
                f"w{index:05d}": self.sized_record(f"w{index:05d}")
                for index in range(count)
            }
            return {"format_version": 1, "records": records}

        low, high = 0, 10_000
        while low < high:
            middle = (low + high + 1) // 2
            if len(self.encoded_state(candidate(middle))) <= MAX_STATE_BYTES:
                low = middle
            else:
                high = middle - 1
        return candidate(low)

    def test_help_states_proof_and_unsupported_boundaries(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        help_text = result.stdout.lower()
        self.assertIn("host-local", help_text)
        self.assertIn("single writer", help_text)
        self.assertIn("cross-host", help_text)
        self.assertIn("does not prove work completion", help_text)

    def test_register_reopen_preserves_minimal_state_and_private_modes(self) -> None:
        created = self.register()
        self.assertEqual(created.returncode, 0, created.stderr)
        first = self.read_state()
        shown = self.run_registry("show", "work-a")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertEqual(first, self.read_state())
        self.assertEqual(first["format_version"], 1)
        record = first["records"]["work-a"]
        self.assertEqual(
            set(record),
            {
                "deadline",
                "last_checked_at",
                "observed_status",
                "observed_substate",
                "owner_session_id",
                "reason_code",
                "requested_status",
                "work_id",
            },
        )
        self.assertEqual(record["owner_session_id"], OWNER_A)
        self.assertIsNone(record["last_checked_at"])
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)

    def test_upsert_keeps_owner_immutable(self) -> None:
        self.assertEqual(self.register().returncode, 0)
        updated = self.register(deadline="2026-09-17T12:00:00+00:00")
        self.assertEqual(updated.returncode, 0, updated.stderr)
        self.assertEqual(
            self.read_state()["records"]["work-a"]["deadline"],
            "2026-09-17T12:00:00Z",
        )
        before = self.state.read_bytes()
        refused = self.register(owner=OWNER_B)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(self.state.read_bytes(), before)

    def test_reconcile_uses_exact_immutable_id_argv_and_sanitizes_output(self) -> None:
        self.assertEqual(self.register().returncode, 0)
        secret = "SENTINEL-DO-NOT-PERSIST-OR-PRINT"
        result = self.run_registry("reconcile", "work-a", env={"STUB_SECRET": secret})
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = json.loads(self.argv_log.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(argv, ["session", "show", OWNER_A, "--json"])
        self.assertNotIn(secret, self.state.read_text(encoding="utf-8"))
        self.assertNotIn(secret, result.stdout + result.stderr)
        record = self.read_state()["records"]["work-a"]
        self.assertEqual(record["observed_status"], "ACTIVE")
        self.assertEqual(record["observed_substate"], "RUNNING")
        self.assertEqual(record["reason_code"], "SESSION_RUNNING")

    def test_waiting_idle_error_stopped_and_queued_mappings(self) -> None:
        expected = {
            "waiting": ("WAITING", "SESSION_WAITING"),
            "idle": ("WAITING", "SESSION_IDLE"),
            "error": ("FAILED", "SESSION_ERROR"),
            "stopped": ("CANCELLED", "SESSION_STOPPED"),
            "queued": ("ACTIVE", "SESSION_QUEUED"),
        }
        for index, (status, want) in enumerate(expected.items()):
            with self.subTest(status=status):
                work_id = f"work-{index}"
                owner = f"{index:08x}-17000000{index:02d}"
                self.assertEqual(self.register(work_id, owner).returncode, 0)
                result = self.run_registry(
                    "reconcile",
                    work_id,
                    env={"STUB_STATUS": status, "STUB_SUBSTATE": ""},
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                record = self.read_state()["records"][work_id]
                self.assertEqual((record["observed_status"], record["reason_code"]), want)

    def test_missing_failed_timed_out_and_malformed_poll_are_visible(self) -> None:
        cases = {
            "missing": ({"STUB_MODE": "missing"}, "SESSION_NOT_FOUND"),
            "failure": ({"STUB_MODE": "failure"}, "POLL_COMMAND_FAILED"),
            "timeout": ({"STUB_MODE": "timeout"}, "POLL_TIMEOUT"),
            "malformed": ({"STUB_MODE": "raw", "STUB_RAW": "not-json"}, "POLL_MALFORMED_JSON"),
            "duplicate": (
                {"STUB_MODE": "raw", "STUB_RAW": '{"id":"x","id":"y","status":"running"}'},
                "POLL_MALFORMED_JSON",
            ),
        }
        for name, (env, reason) in cases.items():
            with self.subTest(case=name):
                work_id = f"work-{name}"
                self.assertEqual(self.register(work_id).returncode, 0)
                env["STUB_SECRET"] = f"SECRET-{name}"
                result = self.run_registry(
                    "--timeout",
                    "0.05",
                    "reconcile",
                    work_id,
                    env=env,
                )
                self.assertNotEqual(result.returncode, 0)
                record = self.read_state()["records"][work_id]
                self.assertEqual(record["owner_session_id"], OWNER_A)
                self.assertEqual(record["observed_status"], "UNKNOWN")
                self.assertEqual(record["reason_code"], reason)
                self.assertEqual(record["last_checked_at"], NOW)
                combined = self.state.read_text(encoding="utf-8") + result.stdout + result.stderr
                self.assertNotIn(f"SECRET-{name}", combined)

    def test_returned_title_or_wrong_id_cannot_establish_identity(self) -> None:
        self.assertEqual(self.register().returncode, 0)
        result = self.run_registry(
            "reconcile",
            "work-a",
            env={"STUB_RETURN_ID": OWNER_B},
        )
        self.assertNotEqual(result.returncode, 0)
        record = self.read_state()["records"]["work-a"]
        self.assertEqual(record["owner_session_id"], OWNER_A)
        self.assertEqual(record["observed_status"], "UNKNOWN")
        self.assertEqual(record["reason_code"], "SESSION_ID_MISMATCH")

    def test_unknown_status_or_substate_fails_closed_without_raw_value(self) -> None:
        self.assertEqual(self.register().returncode, 0)
        result = self.run_registry(
            "reconcile",
            "work-a",
            env={"STUB_STATUS": "SECRET-STATUS", "STUB_SUBSTATE": "SECRET-SUBSTATE"},
        )
        self.assertNotEqual(result.returncode, 0)
        combined = self.state.read_text(encoding="utf-8") + result.stdout + result.stderr
        self.assertNotIn("SECRET-STATUS", combined)
        self.assertNotIn("SECRET-SUBSTATE", combined)
        self.assertEqual(
            self.read_state()["records"]["work-a"]["reason_code"],
            "POLL_UNKNOWN_STATUS",
        )

    def test_malformed_duplicate_unknown_version_and_unknown_field_registry_do_not_rewrite(self) -> None:
        invalid_documents = {
            "malformed": b"{not json",
            "duplicate": b'{"format_version":1,"records":{},"records":{}}\n',
            "version": b'{"format_version":2,"records":{}}\n',
            "field": b'{"format_version":1,"records":{},"extra":"SECRET-FIELD"}\n',
        }
        for name, body in invalid_documents.items():
            with self.subTest(case=name):
                self.state.write_bytes(body)
                self.state.chmod(0o600)
                result = self.run_registry("list")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.state.read_bytes(), body)
                self.assertNotIn("SECRET-FIELD", result.stdout + result.stderr)

    def test_overdue_is_derived_without_changing_observed_status(self) -> None:
        self.assertEqual(self.register(deadline="2026-09-15T11:59:59Z").returncode, 0)
        shown = self.run_registry("show", "work-a")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        projected = json.loads(shown.stdout)
        self.assertTrue(projected["overdue"])
        record = self.read_state()["records"]["work-a"]
        self.assertEqual(record["observed_status"], "NOT_CHECKED")
        self.assertNotIn("overdue", record)

    def test_lock_contention_fails_without_mutation(self) -> None:
        self.assertEqual(self.register().returncode, 0)
        before = self.state.read_bytes()
        lock_path = Path(str(self.state) + ".lock")
        with lock_path.open("r+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_registry(
                "mark-terminal",
                "work-a",
                "--status",
                "FAILED",
                "--reason",
                "ACCEPTANCE_FAILED",
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state.read_bytes(), before)

    def test_atomic_replace_preserves_mode_and_leaves_no_temporary_file(self) -> None:
        self.assertEqual(self.register().returncode, 0)
        first_inode = self.state.stat().st_ino
        self.assertEqual(self.register(deadline="2026-09-18T00:00:00Z").returncode, 0)
        self.assertNotEqual(self.state.stat().st_ino, first_inode)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o600)
        self.assertEqual(list(self.root.glob(".registry.json.*.tmp")), [])

    def test_atomic_write_failure_never_reports_registration_success(self) -> None:
        self.assertEqual(self.register().returncode, 0)
        before = self.state.read_bytes()
        self.root.chmod(0o500)
        try:
            result = self.register(deadline="2026-09-18T00:00:00Z")
        finally:
            self.root.chmod(0o700)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.state.read_bytes(), before)

    def test_oversize_candidate_fails_before_register_or_reconcile_replace(self) -> None:
        state = self.maximal_state()
        raw = self.encoded_state(state)
        self.assertLessEqual(len(raw), MAX_STATE_BYTES)
        self.state.write_bytes(raw)
        self.state.chmod(0o600)
        long_work_id = "x" * 128
        result = self.register(long_work_id, OWNER_B)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.state.read_bytes(), raw)
        self.assertIn("size limit", result.stderr)

        records = state["records"]
        target_id = sorted(records)[0]
        target = records[target_id]
        before_len = len(self.encoded_state(state))
        prior_target = dict(target)
        target.update(
            {
                "observed_status": "UNKNOWN",
                "observed_substate": "UNKNOWN",
                "last_checked_at": NOW,
                "reason_code": "POLL_COMMAND_FAILED",
            }
        )
        failure_growth = len(self.encoded_state(state)) - before_len
        target.clear()
        target.update(prior_target)
        self.assertGreater(failure_growth, 0)

        gap = MAX_STATE_BYTES - before_len
        consume = max(0, gap - failure_growth + 1)
        for old_id in sorted(records)[-2:]:
            extra = min(127 - len(old_id), consume // 2)
            if extra:
                record = records.pop(old_id)
                new_id = old_id + ("x" * extra)
                record["work_id"] = new_id
                records[new_id] = record
                consume -= extra * 2
        if consume:
            filler = records[sorted(records)[-1]]
            prefix, suffix = filler["owner_session_id"].split("-", 1)
            filler["owner_session_id"] = prefix + "0" + "-" + suffix
            consume -= 1
        self.assertEqual(consume, 0)
        tuned = self.encoded_state(state)
        self.assertLessEqual(len(tuned), MAX_STATE_BYTES)
        target = records[target_id]
        prior_target = dict(target)
        target.update(
            {
                "observed_status": "UNKNOWN",
                "observed_substate": "UNKNOWN",
                "last_checked_at": NOW,
                "reason_code": "POLL_COMMAND_FAILED",
            }
        )
        self.assertGreater(len(self.encoded_state(state)), MAX_STATE_BYTES)
        target.clear()
        target.update(prior_target)
        self.state.write_bytes(tuned)
        self.state.chmod(0o600)

        result = self.run_registry("reconcile", target_id, env={"STUB_MODE": "failure"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.state.read_bytes(), tuned)
        self.assertIn("size limit", result.stderr)
        self.assertEqual(list(self.root.glob(".registry.json.*.tmp")), [])

    def test_symlink_nonregular_and_insecure_existing_state_are_refused(self) -> None:
        target = self.root / "target"
        target.write_text("do-not-change", encoding="utf-8")
        target.chmod(0o600)
        self.state.symlink_to(target)
        result = self.run_registry("list")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_text(encoding="utf-8"), "do-not-change")

        self.state.unlink()
        self.state.mkdir(mode=0o700)
        result = self.run_registry("list")
        self.assertNotEqual(result.returncode, 0)

        self.state.rmdir()
        self.state.write_text('{"format_version":1,"records":{}}\n', encoding="utf-8")
        self.state.chmod(0o644)
        before = self.state.read_bytes()
        result = self.run_registry("list")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state.read_bytes(), before)

    def test_unhashable_and_nonstring_record_enums_fail_sanitized_without_rewrite(self) -> None:
        self.assertEqual(self.register().returncode, 0)
        valid = self.read_state()
        fields = ("requested_status", "observed_status", "observed_substate", "reason_code")
        for field in fields:
            for invalid in ({}, [], True):
                with self.subTest(field=field, kind=type(invalid).__name__):
                    candidate = json.loads(json.dumps(valid))
                    candidate["records"]["work-a"][field] = invalid
                    raw = (json.dumps(candidate) + "\n").encode()
                    self.state.write_bytes(raw)
                    self.state.chmod(0o600)
                    result = self.run_registry("list")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(self.state.read_bytes(), raw)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertNotIn(str(self.state), result.stderr)

    def test_nonfinite_timeout_fails_before_state_or_lock_creation(self) -> None:
        for value in ("nan", "inf", "-inf"):
            with self.subTest(timeout=value):
                self.state = self.root / f"timeout-{value.replace('-', 'neg')}.json"
                result = self.run_registry("--timeout", value, "list")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.state.exists())
                self.assertFalse(Path(str(self.state) + ".lock").exists())
                self.assertNotIn("Traceback", result.stderr)
                self.assertNotIn(str(self.state), result.stderr)

    def test_strict_rfc3339_rejects_iso8601_extensions_and_bounds_overflow(self) -> None:
        self.assertEqual(self.register().returncode, 0)
        valid = self.read_state()
        invalid_times = (
            "20260916T120000Z",
            "2026-W38-3T12:00:00Z",
            "2026-09-16X12:00:00Z",
            "2026-09-16T12:00Z",
            "0001-01-01T00:00:00+23:59",
            "9999-12-31T23:59:59-23:59",
        )
        for value in invalid_times:
            with self.subTest(source="cli", value=value):
                before = self.state.read_bytes()
                result = self.register("work-new", OWNER_B, value)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.state.read_bytes(), before)
                self.assertNotIn("Traceback", result.stderr)
                self.assertNotIn(str(self.state), result.stderr)

            with self.subTest(source="loaded", value=value):
                candidate = json.loads(json.dumps(valid))
                candidate["records"]["work-a"]["deadline"] = value
                raw = (json.dumps(candidate) + "\n").encode()
                self.state.write_bytes(raw)
                self.state.chmod(0o600)
                result = self.run_registry("list")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.state.read_bytes(), raw)
                self.assertNotIn("Traceback", result.stderr)

            self.state.write_text(json.dumps(valid) + "\n", encoding="utf-8")
            self.state.chmod(0o600)

        result = self.register(
            "work-offset",
            OWNER_B,
            "2026-09-16T12:00:00.125+02:00",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.read_state()["records"]["work-offset"]["deadline"],
            "2026-09-16T10:00:00.125Z",
        )

    def test_invalid_utf8_poll_durably_replaces_stale_observation(self) -> None:
        self.assertEqual(self.register().returncode, 0)
        prior = self.run_registry(
            "reconcile",
            "work-a",
            env={"STUB_STATUS": "waiting", "STUB_SUBSTATE": ""},
        )
        self.assertEqual(prior.returncode, 0, prior.stderr)
        later = "2026-09-15T13:00:00Z"
        result = self.run_registry(
            "reconcile",
            "work-a",
            env={"STUB_MODE": "invalid-utf8"},
            now=later,
        )
        self.assertNotEqual(result.returncode, 0)
        record = self.read_state()["records"]["work-a"]
        self.assertEqual(record["observed_status"], "UNKNOWN")
        self.assertEqual(record["observed_substate"], "UNKNOWN")
        self.assertEqual(record["reason_code"], "POLL_MALFORMED_JSON")
        self.assertEqual(record["last_checked_at"], later)
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn(str(self.state), result.stderr)

    def test_deployed_usage_limit_substate_is_sanitized_and_preserved(self) -> None:
        self.assertEqual(self.register().returncode, 0)
        result = self.run_registry(
            "reconcile",
            "work-a",
            env={"STUB_STATUS": "waiting", "STUB_SUBSTATE": "usage-limit"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        record = self.read_state()["records"]["work-a"]
        self.assertEqual(record["observed_status"], "WAITING")
        self.assertEqual(record["observed_substate"], "USAGE_LIMIT")
        self.assertEqual(record["reason_code"], "SESSION_WAITING")

    def test_insecure_or_symlinked_parent_is_refused(self) -> None:
        insecure = self.root / "insecure"
        insecure.mkdir(mode=0o755)
        self.state = insecure / "registry.json"
        result = self.register()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.state.exists())

        real_parent = self.root / "real"
        real_parent.mkdir(mode=0o700)
        linked_parent = self.root / "linked"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        self.state = linked_parent / "registry.json"
        result = self.register()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((real_parent / "registry.json").exists())

    def test_mark_terminal_validates_status_reason_and_skips_future_polling(self) -> None:
        self.assertEqual(self.register().returncode, 0)
        invalid = self.run_registry(
            "mark-terminal",
            "work-a",
            "--status",
            "COMPLETE",
            "--reason",
            "ARBITRARY-BODY",
        )
        self.assertNotEqual(invalid.returncode, 0)
        marked = self.run_registry(
            "mark-terminal",
            "work-a",
            "--status",
            "COMPLETE",
            "--reason",
            "CONDUCTOR_VERIFIED",
        )
        self.assertEqual(marked.returncode, 0, marked.stderr)
        record = self.read_state()["records"]["work-a"]
        self.assertEqual(record["requested_status"], "COMPLETE")
        self.assertEqual(record["reason_code"], "CONDUCTOR_VERIFIED")
        before_log = self.argv_log.read_text(encoding="utf-8") if self.argv_log.exists() else ""
        reconciled = self.run_registry("reconcile", "--all")
        self.assertEqual(reconciled.returncode, 0, reconciled.stderr)
        after_log = self.argv_log.read_text(encoding="utf-8") if self.argv_log.exists() else ""
        self.assertEqual(after_log, before_log)

    def test_reconcile_all_is_sorted_and_keeps_each_owner(self) -> None:
        self.assertEqual(self.register("work-z", OWNER_B).returncode, 0)
        self.assertEqual(self.register("work-a", OWNER_A).returncode, 0)
        status_map = json.dumps({OWNER_A: "waiting", OWNER_B: "running"})
        result = self.run_registry(
            "reconcile",
            "--all",
            env={"STUB_STATUS_MAP": status_map, "STUB_SUBSTATE": ""},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads(result.stdout)["records"]
        self.assertEqual([row["work_id"] for row in rows], ["work-a", "work-z"])
        argv_rows = [json.loads(line) for line in self.argv_log.read_text().splitlines()]
        self.assertEqual(
            argv_rows[-2:],
            [
                ["session", "show", OWNER_A, "--json"],
                ["session", "show", OWNER_B, "--json"],
            ],
        )

    def test_invalid_identifiers_deadline_and_registry_record_fail_closed(self) -> None:
        invalid_id = self.register(owner="mutable title")
        self.assertNotEqual(invalid_id.returncode, 0)
        self.assertFalse(self.state.exists())
        bad_deadline = self.register(deadline="tomorrow")
        self.assertNotEqual(bad_deadline.returncode, 0)
        self.assertFalse(self.state.exists())

        body = {
            "format_version": 1,
            "records": {
                "work-a": {
                    "work_id": "different",
                    "owner_session_id": OWNER_A,
                    "requested_status": "ACTIVE",
                    "observed_status": "NOT_CHECKED",
                    "observed_substate": "NONE",
                    "deadline": "2026-09-16T12:00:00Z",
                    "last_checked_at": None,
                    "reason_code": "REGISTERED",
                }
            },
        }
        raw = (json.dumps(body) + "\n").encode()
        self.state.write_bytes(raw)
        self.state.chmod(0o600)
        result = self.run_registry("list")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state.read_bytes(), raw)

        body["records"]["work-a"]["work_id"] = "work-a"
        body["records"]["work-a"]["requested_status"] = "COMPLETE"
        raw = (json.dumps(body) + "\n").encode()
        self.state.write_bytes(raw)
        self.state.chmod(0o600)
        result = self.run_registry("list")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
