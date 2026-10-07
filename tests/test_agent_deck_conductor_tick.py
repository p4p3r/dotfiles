"""Offline ticks through the real registry and private Agent Deck fixtures."""

import fcntl
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
TICK = REPO / "private_dot_local/bin/executable_agent-deck-conductor-tick"
REGISTRY = REPO / "private_dot_local/bin/private_executable_agent-deck-work-registry"
NOW = "2026-10-07T10:00:00Z"
OWNER = "0123abcd-1700000000"
MARKER = "SYNTHETIC_PRIVATE_BODY"


class TickCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="conductor-tick-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.state = self.root / "registry.json"
        self.argv = self.root / "agent-deck-argv.jsonl"
        self.stub = self.root / "agent-deck"
        self.stub.write_text(textwrap.dedent("""\
            #!/usr/bin/env python3
            import json, os, sys, time
            args = sys.argv[1:]
            with open(os.environ['STUB_ARGV'], 'a') as log:
                log.write(json.dumps(args) + '\\n')
            if len(args) != 6 or args[:3] != ['-p', 'fixture', 'session'] or args[3] != 'show' or args[5] != '--json':
                raise SystemExit(9)
            owner = args[4]
            scenario = json.loads(os.environ.get('STUB_SCENARIOS', '{}')).get(owner, {})
            if scenario.get('mode') == 'timeout':
                time.sleep(1)
            if scenario.get('mode') == 'missing':
                raise SystemExit(2)
            print(json.dumps({'id': scenario.get('id', owner),
                              'status': scenario.get('status', 'running'),
                              'substate': scenario.get('substate', 'running'),
                              'output': 'SYNTHETIC_PRIVATE_BODY'}))
            """), encoding="utf-8")
        self.stub.chmod(0o700)
        self.env = os.environ.copy()
        self.env.update({"HOME": str(self.root), "XDG_STATE_HOME": str(self.root / "state"),
                         "XDG_CONFIG_HOME": str(self.root / "config"),
                         "XDG_DATA_HOME": str(self.root / "data"),
                         "XDG_CACHE_HOME": str(self.root / "cache"),
                         "PYTHONDONTWRITEBYTECODE": "1", "STUB_ARGV": str(self.argv)})

    def registry(self, *args, now=NOW):
        result = subprocess.run([sys.executable, str(REGISTRY), "--state", str(self.state),
                                 "--now", now, *args], env=self.env, capture_output=True,
                                text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def register(self, work="work-a", owner=OWNER, deadline="2026-10-08T10:00:00Z"):
        return self.registry("register", work, "--owner-session-id", owner,
                             "--deadline", deadline)

    def tick(self, *args, now=NOW, scenarios=None, registry=None):
        env = self.env.copy()
        env["STUB_SCENARIOS"] = json.dumps(scenarios or {})
        result = subprocess.run([sys.executable, str(TICK), "--state", str(self.state),
                                 "--registry", str(registry or REGISTRY),
                                 "--agent-deck", str(self.stub), "--profile", "fixture",
                                 "--now", now, *args], env=env, capture_output=True,
                                text=True, timeout=8)
        self.assertNotIn(MARKER, result.stdout + result.stderr)
        return result

    def rows(self):
        return [json.loads(line) for line in self.argv.read_text().splitlines()] if self.argv.exists() else []

    def records(self):
        return json.loads(self.state.read_bytes())["records"]

    def test_exact_profile_id_and_only_show_are_used(self):
        self.register()
        result = self.tick()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.rows(), [["-p", "fixture", "session", "show", OWNER, "--json"]])
        event = json.loads(result.stdout)["events"][0]
        self.assertEqual(event["work_id"], "work-a")
        self.assertEqual(event["dispositions"], ["CHANGED"])
        self.assertNotIn(MARKER, self.state.read_text())
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)

    def test_batches_are_oldest_first_with_work_id_tie_break_and_fair(self):
        owners = {}
        for index in reversed(range(26)):
            work = f"w{index:02d}"
            owners[work] = f"{index:08x}-1700000000"
            self.register(work, owners[work])
        for minute, expected in enumerate((range(12), range(12, 24), (24, 25, *range(10)))):
            before = len(self.rows())
            result = self.tick(now=f"2026-10-07T10:{minute:02d}:00Z")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual([row[4] for row in self.rows()[before:]],
                             [owners[f"w{index:02d}"] for index in expected])
            self.assertEqual(json.loads(result.stdout)["polled"], 12)
        self.assertTrue(all(row["last_checked_at"] for row in self.records().values()))

    def test_poll_timeout_preserves_earlier_and_later_observations_on_restart(self):
        owners = [f"{index:08x}-1700000000" for index in range(3)]
        for index, owner in enumerate(owners):
            self.register(f"w{index}", owner)
        result = self.tick("--poll-timeout", "0.3", scenarios={owners[1]: {"mode": "timeout"}})
        self.assertEqual(result.returncode, 4, result.stderr)
        records = self.records()
        self.assertEqual([records[f"w{i}"]["observed_status"] for i in range(3)],
                         ["ACTIVE", "UNKNOWN", "ACTIVE"])
        self.assertEqual(records["w1"]["reason_code"], "POLL_TIMEOUT")
        restart = self.tick(now="2026-10-07T10:02:00Z")
        self.assertEqual(restart.returncode, 0, restart.stderr)
        self.assertEqual(self.records()["w1"]["observed_status"], "ACTIVE")
        self.assertEqual(len(self.rows()), 6)

    def test_lock_contention_has_no_poll_or_state_rewrite(self):
        self.register()
        before = self.state.read_bytes()
        with self.state.with_name("registry.json.lock").open("r+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.tick()
        self.assertEqual(result.returncode, 4)
        self.assertEqual(json.loads(result.stdout)["code"], "REGISTRY_BUSY")
        self.assertEqual(self.state.read_bytes(), before)
        self.assertEqual(self.rows(), [])

    def test_terminal_records_are_skipped_and_waiting_never_completes_work(self):
        self.register("done")
        self.registry("mark-terminal", "done", "--status", "COMPLETE", "--reason", "CONDUCTOR_VERIFIED")
        self.register("pending", "89abcdef-1700000001")
        result = self.tick(scenarios={"89abcdef-1700000001": {"status": "waiting", "substate": ""}})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.records()["done"]["last_checked_at"], None)
        self.assertEqual(self.records()["pending"]["requested_status"], "ACTIVE")
        self.assertEqual(self.records()["pending"]["observed_status"], "WAITING")

    def test_bogus_id_missing_and_unknown_status_remain_visible_and_owned(self):
        scenarios = ({"id": "89abcdef-1700000001"}, {"mode": "missing"}, {"status": MARKER})
        reasons = ("SESSION_ID_MISMATCH", "SESSION_NOT_FOUND", "POLL_UNKNOWN_STATUS")
        self.register()
        for index, (scenario, reason) in enumerate(zip(scenarios, reasons)):
            with self.subTest(reason=reason):
                result = self.tick(now=f"2026-10-07T10:{index:02d}:00Z", scenarios={OWNER: scenario})
                self.assertEqual(result.returncode, 4, result.stderr)
                event = json.loads(result.stdout)["events"][0]
                self.assertEqual(event["dispositions"], ["UNKNOWN"])
                self.assertEqual(event["reason_code"], reason)
                self.assertEqual(self.records()["work-a"]["owner_session_id"], OWNER)
                self.assertNotIn(MARKER, self.state.read_text())

    def test_overdue_transition_is_reported_once_without_terminal_inference(self):
        self.register(deadline="2026-10-07T10:01:00Z")
        self.assertEqual(self.tick().returncode, 0)
        late = self.tick(now="2026-10-07T10:02:00Z")
        event = json.loads(late.stdout)["events"][0]
        self.assertEqual(event["dispositions"], ["OVERDUE"])
        self.assertTrue(event["overdue"])
        unchanged = self.tick(now="2026-10-07T10:04:00Z")
        self.assertEqual(json.loads(unchanged.stdout)["events"], [])
        self.assertEqual(self.records()["work-a"]["requested_status"], "ACTIVE")

    def test_unchanged_observations_only_poll_and_emit_no_events(self):
        self.register()
        self.assertEqual(self.tick().returncode, 0)
        for index in range(1, 3):
            result = self.tick(now=f"2026-10-07T10:0{index}:00Z")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["events"], [])
        self.assertEqual(len(self.rows()), 3)

    def test_configured_batch_limit_and_empty_registry(self):
        result = self.tick()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["polled"], 0)
        for index in range(3):
            self.register(f"w{index}")
        result = self.tick("--max-polls", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["polled"], 2)
        self.assertEqual(json.loads(result.stdout)["remaining"], 1)

    def test_invalid_options_fail_before_registry_or_agent_invocation(self):
        for args in (("--max-polls", "13"), ("--max-polls", "0"),
                     ("--poll-timeout", "6"), ("--poll-timeout", "nan"),
                     ("--budget-seconds", "90"), ("--profile", MARKER + "!"),
                     ("--unexpected", MARKER)):
            with self.subTest(args=args):
                result = self.tick(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stderr, "conductor-tick: INVOCATION\n")
                self.assertFalse(self.state.exists())
                self.assertEqual(self.rows(), [])

    def test_time_budget_keeps_committed_progress_and_next_tick_finishes(self):
        self.register("w0")
        self.register("w1", "89abcdef-1700000001")
        loader = importlib.machinery.SourceFileLoader("tick_budget_fixture", str(TICK))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        args = mock.Mock(registry=str(REGISTRY), state=str(self.state), agent_deck=str(self.stub),
                         profile="fixture", now=NOW, poll_timeout=5.0, budget_seconds=80.0,
                         max_polls=12)
        clock = mock.Mock()
        clock.monotonic.side_effect = [0, 0, 79]
        with mock.patch.object(module, "time", clock), mock.patch.dict(os.environ, self.env):
            result, code = module.tick(args)
        self.assertEqual(code, 4)
        self.assertEqual(result["code"], "TIME_BUDGET")
        self.assertEqual((result["polled"], result["remaining"]), (1, 1))
        self.assertEqual(self.records()["w0"]["observed_status"], "ACTIVE")
        self.assertEqual(self.records()["w1"]["observed_status"], "NOT_CHECKED")
        resumed = self.tick("--max-polls", "1", now="2026-10-07T10:02:00Z")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(self.rows()[-1][4], "89abcdef-1700000001")

    def test_outer_registry_timeout_retains_previous_poll(self):
        self.register("w0")
        self.register("w1", "89abcdef-1700000001")
        wrapper = self.root / "slow-registry"
        wrapper.write_text("#!/usr/bin/env python3\nimport os, sys, time\n"
                           "if sys.argv[-2:] == ['reconcile', 'w1']: time.sleep(6)\n"
                           f"os.execv({str(REGISTRY)!r}, [{str(REGISTRY)!r}, *sys.argv[1:]])\n")
        wrapper.chmod(0o700)
        result = self.tick("--poll-timeout", "0.3", registry=wrapper)
        self.assertEqual(result.returncode, 4, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual((output["code"], output["polled"], output["remaining"]),
                         ("REGISTRY_TIMEOUT", 1, 1))
        self.assertEqual(self.records()["w0"]["observed_status"], "ACTIVE")
        self.assertEqual(self.records()["w1"]["observed_status"], "NOT_CHECKED")
        self.assertEqual(len(self.rows()), 1)

    def test_outer_timeout_does_not_wait_for_detached_pipe_holder(self):
        hold = self.root / "hold-detached-child"
        hold.touch()
        leader_pid = self.root / "leader.pid"
        holder_pid = self.root / "holder.pid"
        wrapper = self.root / "detached-pipe-registry"
        holder_code = (f"import os, time\nmarker = {str(hold)!r}\n"
                       "while os.path.exists(marker):\n    time.sleep(0.05)\n")
        wrapper.write_text(textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import os
            from pathlib import Path
            import subprocess
            import sys
            import time

            Path({str(leader_pid)!r}).write_text(str(os.getpid()))
            child = subprocess.Popen(
                [sys.executable, '-c', {holder_code!r}],
                start_new_session=True,
            )
            Path({str(holder_pid)!r}).write_text(str(child.pid))
            time.sleep(30)
            """), encoding="utf-8")
        wrapper.chmod(0o700)
        started = time.monotonic()
        try:
            result = self.tick("--budget-seconds", "0.3", registry=wrapper)
        finally:
            hold.unlink(missing_ok=True)
            for path in (leader_pid, holder_pid):
                if path.exists():
                    try:
                        os.kill(int(path.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        elapsed = time.monotonic() - started
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertEqual(json.loads(result.stdout)["code"], "REGISTRY_TIMEOUT")
        self.assertLess(elapsed, 2.0)

    def test_malformed_duplicate_and_private_registry_payloads_fail_closed(self):
        self.register()
        snapshot = self.registry("list")
        before = self.state.read_bytes()
        fake = self.root / "malformed-registry"
        fake.write_text("#!/usr/bin/env python3\nimport os\nprint(os.environ['FAKE_RESPONSE'])\n")
        fake.chmod(0o700)
        duplicate = {**snapshot, "records": snapshot["records"] * 2}
        body = {**snapshot, "body": MARKER}
        bad_enum = json.loads(json.dumps(snapshot))
        bad_enum["records"][0]["reason_code"] = MARKER
        wrong_version = {**snapshot, "format_version": True}
        cases = (MARKER, '{"format_version":1,"format_version":1,"records":[]}',
                 json.dumps(duplicate), json.dumps(body), json.dumps(bad_enum),
                 json.dumps(wrong_version))
        for raw in cases:
            with self.subTest(raw=raw[:32]):
                self.env["FAKE_RESPONSE"] = raw
                result = self.tick(registry=fake)
                self.assertEqual(result.returncode, 4)
                self.assertEqual(json.loads(result.stdout)["code"], "REGISTRY_INVALID")
                self.assertEqual(self.state.read_bytes(), before)
                self.assertEqual(self.rows(), [])

    def test_reconcile_response_cannot_replace_registered_owner(self):
        self.register()
        snapshot = self.registry("list")
        after = {**snapshot["records"][0], "owner_session_id": "89abcdef-1700000001",
                 "observed_status": "ACTIVE", "observed_substate": "RUNNING",
                 "reason_code": "SESSION_RUNNING", "last_checked_at": NOW}
        fake = self.root / "mismatched-registry"
        fake.write_text("#!/usr/bin/env python3\nimport json, os, sys\n"
                        "print(os.environ['FAKE_AFTER' if sys.argv[-2] == 'reconcile' else 'FAKE_LIST'])\n")
        fake.chmod(0o700)
        self.env.update(FAKE_LIST=json.dumps(snapshot), FAKE_AFTER=json.dumps(after))
        result = self.tick(registry=fake)
        self.assertEqual(result.returncode, 4)
        self.assertEqual(json.loads(result.stdout)["code"], "REGISTRY_INVALID")
        self.assertEqual(json.loads(result.stdout)["events"], [])
        self.assertEqual(self.records()["work-a"]["owner_session_id"], OWNER)

    def test_unchanged_unknown_repeats_no_event_but_remains_unverified(self):
        self.register()
        scenario = {OWNER: {"mode": "missing"}}
        self.assertEqual(self.tick(scenarios=scenario).returncode, 4)
        again = self.tick(now="2026-10-07T10:02:00Z", scenarios=scenario)
        self.assertEqual(again.returncode, 4)
        output = json.loads(again.stdout)
        self.assertEqual(output["code"], "NOT_VERIFIED")
        self.assertEqual(output["events"], [])


if __name__ == "__main__":
    unittest.main()
