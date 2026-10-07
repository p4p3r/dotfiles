#!/usr/bin/env python3
"""Focused isolated tests for the Agent Deck Slack gateway watchdog."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "private_dot_local/bin/executable_agent-deck-slack-watchdog"
MODULE = REPO / "nix/modules/agent-deck-slack-watchdog.nix"
BINARY_A = "a" * 64
CONFIG_A = "b" * 64
ROW_A = "row_alias_fixture_0000000000000001"


def read_frame(connection: socket.socket) -> dict[str, object]:
    data = bytearray()
    while not data.endswith(b"\n"):
        chunk = connection.recv(4096)
        if not chunk:
            raise RuntimeError("unexpected EOF")
        data.extend(chunk)
    return json.loads(data.decode("utf-8"))


class FakeControl:
    def __init__(
        self,
        path: Path,
        response: dict[str, object],
        *,
        delay: float = 0,
        close_reply: bool = True,
        socket_mode: int = 0o600,
    ) -> None:
        self.path = path
        self.response = response
        self.delay = delay
        self.close_reply = close_reply
        self.socket_mode = socket_mode
        self.ready = threading.Event()
        self.finished = threading.Event()
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def __enter__(self) -> "FakeControl":
        self.path.unlink(missing_ok=True)
        self.thread.start()
        if not self.ready.wait(2):
            raise RuntimeError("fake control did not start")
        return self

    def __exit__(self, *_: object) -> None:
        self.thread.join(2)
        if self.thread.is_alive():
            raise RuntimeError("fake control did not stop")
        if self.error is not None:
            raise self.error
        self.path.unlink(missing_ok=True)

    def run(self) -> None:
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(self.path))
            os.chmod(self.path, self.socket_mode)
            server.listen(1)
            server.settimeout(0.5)
            self.ready.set()
            connection, _ = server.accept()
            with connection:
                hello = read_frame(connection)
                if self.delay:
                    time.sleep(self.delay)
                response = dict(self.response)
                response["nonce"] = hello["nonce"]
                connection.sendall(
                    json.dumps(response, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
                )
                close = read_frame(connection)
                if self.close_reply:
                    connection.sendall(
                        json.dumps(
                            {"version": 1, "type": "closed", "nonce": close["nonce"]},
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("ascii")
                        + b"\n"
                    )
                else:
                    time.sleep(0.5)
        except (BrokenPipeError, ConnectionResetError, RuntimeError, socket.timeout):
            # Fail-closed clients may leave at any protocol boundary.
            pass
        except BaseException as exc:  # surfaced in the owning test
            self.error = exc
        finally:
            self.finished.set()
            server.close()


def base_pong() -> dict[str, object]:
    return {
        "version": 1,
        "type": "pong",
        "nonce": "replaced",
        "identity": {
            "binary_sha256": BINARY_A,
            "config_sha256": CONFIG_A,
            "row_binding_alias": ROW_A,
        },
        "runner": {"state": "running", "exit_code": None, "terminal": False, "degraded": False},
        "pump": {"state": "fresh", "last_progress_age_seconds": 2},
        "backlog": {"state": "pending", "oldest_age_seconds": 4},
        "egress": {"state": "clear"},
        "conductor": {"state": "working", "turn_age_seconds": 7200},
    }


class WatchdogCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="slack-watchdog-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        os.chmod(self.root, 0o700)
        self.socket = self.root / "control.sock"
        self.settings = self.root / "settings.json"
        self.state = self.root / "state" / "watchdog.json"
        self.systemctl_log = self.root / "systemctl.jsonl"
        self.systemctl = self.root / "systemctl"
        self.write_systemctl()
        self.write_settings()

    def write_systemctl(self, *, sleep: float = 0, exit_code: int = 0) -> None:
        self.systemctl.write_text(
            f"#!{sys.executable}\n"
            "import json, pathlib, sys, time\n"
            f"pathlib.Path({str(self.systemctl_log)!r}).open('a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
            f"time.sleep({sleep!r})\n"
            f"raise SystemExit({exit_code})\n",
            encoding="utf-8",
        )
        self.systemctl.chmod(0o700)

    def write_settings(
        self,
        *,
        binary: str = BINARY_A,
        config: str = CONFIG_A,
        row: str = ROW_A,
        io_ms: int = 100,
        restart_ms: int = 200,
    ) -> None:
        value = {
            "version": 1,
            "control_socket": str(self.socket),
            "gateway_unit": "fixture-gateway.service",
            "expected_incarnation": {
                "binary_sha256": binary,
                "config_sha256": config,
                "row_binding_alias": row,
            },
            "timeouts": {"connect_ms": 100, "io_ms": io_ms, "restart_ms": restart_ms},
        }
        self.settings.write_text(json.dumps(value), encoding="utf-8")
        self.settings.chmod(0o600)

    def run_watchdog(self, response: dict[str, object] | None = None, **server_args: object) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(SCRIPT),
            "--settings",
            str(self.settings),
            "--state",
            str(self.state),
            "--systemctl",
            str(self.systemctl),
            "--now",
            "2026-10-07T10:00:00Z",
        ]
        if response is None:
            return subprocess.run(command, check=False, capture_output=True, text=True, timeout=3)
        with FakeControl(self.socket, response, **server_args):
            return subprocess.run(command, check=False, capture_output=True, text=True, timeout=3)

    def result_json(self, result: subprocess.CompletedProcess[str]) -> dict[str, object]:
        self.assertEqual(result.stderr, "")
        value = json.loads(result.stdout)
        self.assertEqual(set(value), {
            "version", "status", "reason", "action", "runner", "terminal", "degraded", "pump", "backlog",
            "backlog_age_band", "egress", "conductor", "conductor_age_band",
        })
        return value

    def systemctl_calls(self) -> list[list[str]]:
        if not self.systemctl_log.exists():
            return []
        return [json.loads(line) for line in self.systemctl_log.read_text(encoding="utf-8").splitlines()]

    def test_healthy_handshake_accepts_long_conductor_turn_without_systemd_probe(self) -> None:
        result = self.run_watchdog(base_pong())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        value = self.result_json(result)
        self.assertEqual((value["status"], value["reason"], value["action"]), ("HEALTHY", "OK", "none"))
        self.assertEqual(value["conductor_age_band"], "gte_1h")
        self.assertEqual(value["backlog_age_band"], "lt_1m")
        self.assertEqual(self.systemctl_calls(), [], "systemd active/status is not a health signal")
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.state.parent.stat().st_mode & 0o777, 0o700)

    def test_retryable_75_consumes_one_persistent_restart_budget(self) -> None:
        response = base_pong()
        response["runner"] = {"state": "exited", "exit_code": 75, "terminal": False, "degraded": False}
        first = self.run_watchdog(response)
        second = self.run_watchdog(response)
        self.assertEqual(first.returncode, 0, first.stdout)
        self.assertEqual(self.result_json(first)["reason"], "RESTART_REQUESTED")
        self.assertEqual(second.returncode, 1, second.stdout)
        self.assertEqual(self.result_json(second)["reason"], "RETRY_BUDGET_USED")
        self.assertEqual(self.systemctl_calls(), [["--user", "restart", "fixture-gateway.service"]])
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertTrue(state["retry_used"])
        self.assertEqual(state["restart_attempted_at"], "2026-10-07T10:00:00Z")
        self.assertNotIn(BINARY_A, self.state.read_text(encoding="utf-8"))
        self.assertNotIn(ROW_A, self.state.read_text(encoding="utf-8"))

    def test_new_pinned_incarnation_gets_a_new_one_shot_budget(self) -> None:
        response = base_pong()
        response["runner"] = {"state": "exited", "exit_code": 75, "terminal": False, "degraded": False}
        self.assertEqual(self.run_watchdog(response).returncode, 0)
        binary_b = "c" * 64
        row_b = "row_alias_fixture_0000000000000002"
        self.write_settings(binary=binary_b, row=row_b)
        changed = base_pong()
        changed["identity"] = {
            "binary_sha256": binary_b,
            "config_sha256": CONFIG_A,
            "row_binding_alias": row_b,
        }
        changed["runner"] = {"state": "exited", "exit_code": 75, "terminal": False, "degraded": False}
        self.assertEqual(self.run_watchdog(changed).returncode, 0)
        self.assertEqual(len(self.systemctl_calls()), 2)

    def test_restart_timeout_consumes_budget_before_ambiguous_call(self) -> None:
        self.write_systemctl(sleep=0.5)
        self.write_settings(restart_ms=100)
        response = base_pong()
        response["runner"] = {"state": "exited", "exit_code": 75, "terminal": False, "degraded": False}
        first = self.run_watchdog(response)
        second = self.run_watchdog(response)
        self.assertEqual(self.result_json(first)["reason"], "RESTART_TIMEOUT")
        self.assertEqual(self.result_json(second)["reason"], "RETRY_BUDGET_USED")
        self.assertEqual(len(self.systemctl_calls()), 1)

    def test_status_timeout_is_bounded_and_never_restarts(self) -> None:
        self.write_settings(io_ms=100)
        start = time.monotonic()
        result = self.run_watchdog(base_pong(), delay=0.5)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 1.5)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.result_json(result)["reason"], "STATUS_TIMEOUT")
        self.assertEqual(self.systemctl_calls(), [])

    def test_close_ack_is_required_before_retry(self) -> None:
        response = base_pong()
        response["runner"] = {"state": "exited", "exit_code": 75, "terminal": False, "degraded": False}
        result = self.run_watchdog(response, close_reply=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn(self.result_json(result)["reason"], {"STATUS_TIMEOUT", "STATUS_PROTOCOL"})
        self.assertEqual(self.systemctl_calls(), [])

    def test_unqualified_socket_mode_is_rejected(self) -> None:
        result = self.run_watchdog(base_pong(), socket_mode=0o660)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.result_json(result)["reason"], "CONTROL_UNSAFE")
        self.assertEqual(self.systemctl_calls(), [])

    def test_missing_socket_and_unsafe_settings_fail_closed(self) -> None:
        missing = self.run_watchdog()
        self.assertEqual(self.result_json(missing)["reason"], "CONTROL_UNAVAILABLE")
        self.settings.chmod(0o644)
        unsafe = self.run_watchdog()
        self.assertEqual(self.result_json(unsafe)["reason"], "SETTINGS_UNSAFE")
        self.assertEqual(self.systemctl_calls(), [])

    def test_terminal_degraded_stale_stalled_unknown_uncertain_and_identity_mismatch_never_restart(self) -> None:
        cases: list[tuple[str, dict[str, object], str]] = []
        terminal = base_pong()
        terminal["runner"] = {"state": "exited", "exit_code": 78, "terminal": True, "degraded": False}
        cases.append(("terminal", terminal, "TERMINAL"))
        degraded = base_pong()
        degraded["runner"] = {"state": "running", "exit_code": None, "terminal": False, "degraded": True}
        cases.append(("degraded", degraded, "DEGRADED"))
        for pump_state, reason in (("stale", "PUMP_STALE"), ("stalled", "PUMP_STALLED")):
            value = base_pong()
            value["pump"] = {"state": pump_state, "last_progress_age_seconds": 900}
            if pump_state == "stale":
                value["runner"] = {
                    "state": "exited",
                    "exit_code": 75,
                    "terminal": False,
                    "degraded": False,
                }
            cases.append((pump_state, value, reason))
        unknown = base_pong()
        unknown["pump"] = {"state": "unknown", "last_progress_age_seconds": None}
        cases.append(("unknown", unknown, "UNKNOWN"))
        uncertain = base_pong()
        uncertain["egress"] = {"state": "uncertain"}
        cases.append(("uncertain", uncertain, "EGRESS_UNCERTAIN"))
        mismatch = base_pong()
        mismatch["identity"] = dict(mismatch["identity"], binary_sha256="d" * 64)  # type: ignore[arg-type]
        cases.append(("identity", mismatch, "IDENTITY_MISMATCH"))
        for name, response, reason in cases:
            with self.subTest(name=name):
                result = self.run_watchdog(response)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertEqual(self.result_json(result)["reason"], reason)
        self.assertEqual(self.systemctl_calls(), [])

    def test_protocol_is_strict_and_body_free(self) -> None:
        sentinel = "SENTINEL-PRIVATE-BODY-DO-NOT-LOG"
        response = base_pong()
        response["unexpected"] = sentinel
        result = self.run_watchdog(response)
        self.assertEqual(self.result_json(result)["reason"], "STATUS_PROTOCOL")
        self.assertNotIn(sentinel, result.stdout + result.stderr)
        self.assertNotIn(BINARY_A, result.stdout + result.stderr)
        self.assertNotIn(ROW_A, result.stdout + result.stderr)

    def test_concurrent_state_lock_never_probes_or_restarts(self) -> None:
        self.state.parent.mkdir(mode=0o700)
        lock = self.state.with_name(self.state.name + ".lock")
        with lock.open("w", encoding="utf-8") as handle:
            os.chmod(lock, 0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_watchdog()
        self.assertEqual(self.result_json(result)["reason"], "CONCURRENT_RUN")
        self.assertEqual(self.systemctl_calls(), [])


class ModuleContractCase(unittest.TestCase):
    def test_module_is_generic_disabled_by_default_and_has_no_restart_loop(self) -> None:
        text = MODULE.read_text(encoding="utf-8")
        self.assertIn("mkEnableOption", text)
        self.assertIn("pkgs.stdenv.isLinux", text)
        self.assertIn('default = null;', text)
        self.assertIn('OnUnitInactiveSec = cfg.interval;', text)
        self.assertIn('UMask = "0077"', text)
        self.assertIn('StateDirectoryMode = "0700"', text)
        self.assertIn('RestrictAddressFamilies = [ "AF_UNIX" ]', text)
        self.assertNotIn("Restart =", text)
        self.assertNotIn("RestartSec", text)
        self.assertNotIn("EnvironmentFile", text)
        self.assertNotIn("SLACK_", text)

    def test_common_and_flake_expose_exact_offline_check(self) -> None:
        common = (REPO / "nix/modules/common.nix").read_text(encoding="utf-8")
        flake = (REPO / "nix/flake.nix").read_text(encoding="utf-8")
        self.assertIn("./agent-deck-slack-watchdog.nix", common)
        self.assertIn("x86_64-linux.slack-watchdog-runtime", flake)
        self.assertIn("systemd-analyze verify", flake)
        self.assertIn("! ${pkgs.gnugrep}/bin/grep -q '^Restart='", flake)

    def test_public_surface_has_no_private_or_provider_material(self) -> None:
        text = "\n".join(
            [
                SCRIPT.read_text(encoding="utf-8"),
                MODULE.read_text(encoding="utf-8"),
                (REPO / "docs/agent-deck-slack-watchdog.md").read_text(encoding="utf-8"),
            ]
        )
        for marker in ("xoxb-", "xapp-", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"):
            self.assertNotIn(marker, text)


if __name__ == "__main__":
    unittest.main()
