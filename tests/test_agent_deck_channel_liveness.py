"""Execute the liveness monitor against a real database and a fake systemctl."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MONITOR = REPO / "private_dot_local" / "bin" / "executable_agent-deck-channel-liveness"


class LivenessCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.state = self.tmp / "state"
        self.calls = self.tmp / "systemctl-calls"
        self.db = self.tmp / "gateway.sqlite"
        self.write_db(seen_at=time.time(), turn_status="completed")
        self.write_systemctl("active")

    def write_db(self, seen_at, turn_status="completed", empty=False) -> None:
        if self.db.exists():
            self.db.unlink()
        c = sqlite3.connect(self.db)
        c.execute("create table inbound_events (ordinal integer, seen_at real)")
        c.execute("create table turns (number integer, status text)")
        if not empty:
            c.execute("insert into inbound_events values (1, ?)", (seen_at,))
            c.execute("insert into turns values (1, ?)", (turn_status,))
        c.commit()
        c.close()

    def write_systemctl(self, active_state, restart_ok=True) -> None:
        path = self.tmp / "systemctl"
        path.write_text(f"""#!/usr/bin/env python3
import os, pathlib, sys
argv = sys.argv[1:]
calls = pathlib.Path({str(self.calls)!r})
with calls.open("a") as fh:
    fh.write(" ".join(argv) + chr(10))
if "show" in argv:
    print({active_state!r}); sys.exit(0)
if "restart" in argv:
    sys.exit(0 if {restart_ok!r} else 1)
sys.exit(0)
""")
        path.chmod(0o755)

    def run_monitor(self, *extra, apply=True):
        argv = [sys.executable, str(MONITOR),
                "--unit", "agent-deck-conductor-slack-v2.service",
                "--database", str(self.db),
                "--state-dir", str(self.state),
                "--systemctl", str(self.tmp / "systemctl"),
                *extra]
        if apply:
            argv.append("--apply")
        done = subprocess.run(argv, capture_output=True, text=True, timeout=60,
                              check=False)
        report = json.loads(done.stdout) if done.stdout.strip() else None
        return done, report

    def systemctl_calls(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def restarts(self):
        return [c for c in self.systemctl_calls() if "restart" in c]

    # -- the quiet-channel question ----------------------------------------

    def test_recent_inbound_is_left_alone(self) -> None:
        _, report = self.run_monitor()
        self.assertEqual(report["verdict"], "OK")
        self.assertEqual(self.restarts(), [])

    def test_long_silence_recycles_the_unit(self) -> None:
        self.write_db(seen_at=time.time() - 60 * 60)
        _, report = self.run_monitor("--max-silence-minutes", "45")
        self.assertEqual(report["verdict"], "RESTART")
        self.assertTrue(report["restarted"])
        self.assertEqual(len(self.restarts()), 1)

    def test_silence_below_the_threshold_is_left_alone(self) -> None:
        self.write_db(seen_at=time.time() - 10 * 60)
        _, report = self.run_monitor("--max-silence-minutes", "45")
        self.assertEqual(report["verdict"], "OK")
        self.assertEqual(self.restarts(), [])

    def test_a_turn_in_flight_proves_the_path_is_live(self) -> None:
        # A long turn is not silence: the inbound path demonstrably worked.
        self.write_db(seen_at=time.time() - 60 * 60, turn_status="active")
        _, report = self.run_monitor("--max-silence-minutes", "45")
        self.assertEqual(report["verdict"], "OK")
        self.assertTrue(report["turn_in_flight"])
        self.assertEqual(self.restarts(), [])

    def test_a_never_used_conductor_is_not_recycled(self) -> None:
        self.write_db(seen_at=None, empty=True)
        _, report = self.run_monitor("--max-silence-minutes", "45")
        self.assertEqual(report["verdict"], "OK")
        self.assertEqual(self.restarts(), [])

    # -- the dead-unit case -------------------------------------------------

    def test_a_failed_unit_is_restarted(self) -> None:
        # The unit is Restart=no, so nothing else brings it back.
        self.write_systemctl("failed")
        _, report = self.run_monitor()
        self.assertEqual(report["verdict"], "RESTART")
        self.assertEqual(len(self.restarts()), 1)

    def test_an_inactive_unit_is_not_started(self) -> None:
        # Deliberately stopped is not the same as broken.
        self.write_systemctl("inactive")
        _, report = self.run_monitor()
        self.assertEqual(report["verdict"], "SKIPPED")
        self.assertEqual(self.restarts(), [])

    # -- safety -------------------------------------------------------------

    def test_without_apply_nothing_is_restarted(self) -> None:
        self.write_db(seen_at=time.time() - 60 * 60)
        _, report = self.run_monitor("--max-silence-minutes", "45", apply=False)
        self.assertEqual(report["verdict"], "RESTART")
        self.assertFalse(report["restarted"])
        self.assertEqual(self.restarts(), [])

    def test_restarts_are_capped_per_day(self) -> None:
        self.state.mkdir(parents=True)
        now = time.time()
        (self.state / "restarts").write_text(
            "\n".join(f"{now - 60 * i:.0f}" for i in range(3)) + "\n")
        self.write_db(seen_at=now - 60 * 60)
        _, report = self.run_monitor("--max-silence-minutes", "45",
                                     "--daily-restart-cap", "3")
        self.assertEqual(report["verdict"], "CAPPED")
        self.assertEqual(self.restarts(), [],
                         "a unit that is not recovering must not be flapped")

    def test_restarts_older_than_a_day_do_not_count(self) -> None:
        self.state.mkdir(parents=True)
        now = time.time()
        (self.state / "restarts").write_text(f"{now - 86400 * 2:.0f}\n")
        self.write_db(seen_at=now - 60 * 60)
        _, report = self.run_monitor("--max-silence-minutes", "45",
                                     "--daily-restart-cap", "1")
        self.assertEqual(report["verdict"], "RESTART")
        self.assertEqual(report["restarts_last_24h"], 0)

    def test_a_failing_restart_degrades(self) -> None:
        self.write_systemctl("failed", restart_ok=False)
        done, report = self.run_monitor()
        self.assertEqual(report["verdict"], "DEGRADED")
        self.assertEqual(done.returncode, 1)

    def test_a_missing_database_degrades_rather_than_restarting(self) -> None:
        self.db.unlink()
        _, report = self.run_monitor()
        self.assertEqual(report["verdict"], "DEGRADED")
        self.assertEqual(self.restarts(), [])

    def test_an_absurd_silence_window_is_refused(self) -> None:
        done, _ = self.run_monitor("--max-silence-minutes", "1")
        self.assertEqual(done.returncode, 2)
        self.assertIn("REJECTED", done.stderr)

    def test_the_database_is_never_opened_in_place(self) -> None:
        # The gateway owns it in WAL mode; a monitor must not take locks on it.
        body = MONITOR.read_text()
        self.assertIn("shutil.copy", body)
        self.assertNotIn("sqlite3.connect(args.database", body)

    def test_the_script_names_nothing_host_or_company_specific(self) -> None:
        body = MONITOR.read_text().lower()
        for token in ("semgrep", "claudio", "box-1", "box-2", "mandoline", "xoxb"):
            self.assertNotIn(token, body)


if __name__ == "__main__":
    unittest.main()
