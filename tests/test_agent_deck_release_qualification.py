#!/usr/bin/env python3
"""Focused controls for the non-live Agent Deck qualification harness."""

from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
HARNESS = REPO / "private_dot_local/bin/executable_agent-deck-release-qualify"
FIXTURES = REPO / "private_dot_local/share/agent-deck-release-qualification"
UNSAFE_MISSING_BRIDGE = (
    REPO
    / "tests/fixtures/agent_deck_release_qualification/unsafe_missing_bridge.py"
)


class ReleaseQualificationHarnessTest(unittest.TestCase):
    def isolated_env(self, root: Path) -> dict[str, str]:
        env = dict(os.environ)
        paths = {
            "HOME": root / "home",
            "XDG_CONFIG_HOME": root / "xdg/config",
            "XDG_DATA_HOME": root / "xdg/data",
            "XDG_STATE_HOME": root / "xdg/state",
            "XDG_CACHE_HOME": root / "xdg/cache",
            "XDG_RUNTIME_DIR": root / "xdg/runtime",
            "TMPDIR": root / "tmp",
            "TMP": root / "tmp",
            "TEMP": root / "tmp",
            "AGENT_DECK_CONDUCTOR_DIR": root / "conductor",
            "CODEX_HOME": root / "home/.codex",
            "CLAUDE_CONFIG_DIR": root / "home/.claude",
        }
        for path in paths.values():
            path.mkdir(parents=True, exist_ok=True)
        env.update({key: str(value) for key, value in paths.items()})
        env["AGENT_DECK_RELEASE_QUALIFICATION_FIXTURES"] = str(FIXTURES)
        return env

    def run_harness(
        self, *args: str, extra_env: dict[str, str] | None = None
    ) -> tuple[subprocess.CompletedProcess, dict]:
        with tempfile.TemporaryDirectory(prefix="release-qualification-test.") as tmp:
            root = Path(tmp)
            env = self.isolated_env(root)
            if extra_env:
                env.update(extra_env)
            completed = subprocess.run(
                [str(HARNESS), *args],
                cwd=REPO,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )
        return completed, json.loads(completed.stdout)

    def minimal_candidate(self, root: Path) -> Path:
        source = root / "candidate"
        for relative in ("cmd/agent-deck", "internal/tmux", "internal/session"):
            (source / relative).mkdir(parents=True, exist_ok=True)
        (source / "go.mod").write_text("module fixture.invalid/agent-deck\n", encoding="utf-8")
        (source / "cmd/agent-deck/launch_acceptance.go").write_text(
            "package main\n", encoding="utf-8"
        )
        (source / "internal/tmux/detector.go").write_text("package tmux\n", encoding="utf-8")
        (source / "internal/session/conductor_bridge.py").write_text("# fixture\n", encoding="utf-8")
        return source

    def harness_namespace(self, root: Path) -> dict:
        previous = dict(os.environ)
        try:
            os.environ.clear()
            os.environ.update(self.isolated_env(root))
            return runpy.run_path(str(HARNESS))
        finally:
            os.environ.clear()
            os.environ.update(previous)

    def test_self_test_rejects_invalid_instruments(self) -> None:
        completed, payload = self.run_harness("--self-test")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["failures"], [])

    def test_invalid_source_is_not_verified(self) -> None:
        with tempfile.TemporaryDirectory(prefix="invalid-agent-deck-source.") as tmp:
            cache = Path(tmp) / "module-cache"
            cache.mkdir()
            completed, payload = self.run_harness(
                "--source", tmp, "--go-mod-cache", str(cache)
            )
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(payload["verdict"], "NOT_VERIFIED")
        self.assertEqual(payload["checks"][0]["name"], "candidate_source")

    def test_missing_candidate_selector_is_not_verified(self) -> None:
        completed, payload = self.run_harness()
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(payload["verdict"], "NOT_VERIFIED")

    def test_true_cannot_fake_busy_probe_success(self) -> None:
        with tempfile.TemporaryDirectory(prefix="true-busy-control.") as tmp:
            root = Path(tmp)
            source = self.minimal_candidate(root)
            cache = root / "module-cache"
            cache.mkdir()
            completed, payload = self.run_harness(
                "--source",
                str(source),
                "--go",
                "/usr/bin/true",
                "--go-mod-cache",
                str(cache),
            )
        busy = next(check for check in payload["checks"] if check["name"] == "codex_busy_provenance")
        launch = next(
            check
            for check in payload["checks"]
            if check["name"] == "fresh_launch_acceptance"
        )
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(busy["verdict"], "NOT_VERIFIED")
        self.assertEqual(launch["verdict"], "NOT_VERIFIED")

    def test_busy_json_requires_every_exact_test_to_pass(self) -> None:
        with tempfile.TemporaryDirectory(prefix="busy-json-control.") as tmp:
            namespace = self.harness_namespace(Path(tmp))
        parse = namespace["_parse_busy_go_test_json"]
        expected = namespace["BUSY_TEST_IDS"]
        package = "fixture.invalid/agent-deck/internal/tmux"

        events = [{"Action": "start", "Package": package}]
        for test_id in expected:
            events.append({"Action": "run", "Package": package, "Test": test_id})
            events.append({"Action": "pass", "Package": package, "Test": test_id})
        events.append({"Action": "pass", "Package": package})
        output = "\n".join(json.dumps(event) for event in events)
        proof, error = parse(output)
        self.assertIsNone(error)
        self.assertEqual(proof["passed_tests"], list(expected))

        proof, error = parse("")
        self.assertIsNone(proof)
        self.assertIn("no JSON events", error)

        skipped = list(events)
        target = expected[-1]
        skipped = [
            ({**event, "Action": "skip"} if event.get("Test") == target and event["Action"] == "pass" else event)
            for event in skipped
        ]
        proof, error = parse("\n".join(json.dumps(event) for event in skipped))
        self.assertIsNone(proof)
        self.assertIn(target, error)

    def test_fresh_launch_json_requires_every_exact_test_to_pass(self) -> None:
        with tempfile.TemporaryDirectory(prefix="launch-json-control.") as tmp:
            namespace = self.harness_namespace(Path(tmp))
        parse = namespace["_parse_launch_go_test_json"]
        expected = namespace["FRESH_LAUNCH_TEST_IDS"]
        package = "fixture.invalid/agent-deck/cmd/agent-deck"

        events = [{"Action": "start", "Package": package}]
        for test_id in expected:
            events.append({"Action": "run", "Package": package, "Test": test_id})
            events.append({"Action": "pass", "Package": package, "Test": test_id})
        events.append({"Action": "pass", "Package": package})
        proof, error = parse("\n".join(json.dumps(event) for event in events))
        self.assertIsNone(error)
        self.assertEqual(proof["passed_tests"], list(expected))

        missing = [
            event
            for event in events
            if event.get("Test") != expected[-1]
        ]
        proof, error = parse("\n".join(json.dumps(event) for event in missing))
        self.assertIsNone(proof)
        self.assertIn("unexpected or incomplete", error)

    def test_fresh_launch_probe_owns_schema_bound_and_real_transport(self) -> None:
        probe = (FIXTURES / "fresh_launch_acceptance_probe_test.go").read_text(
            encoding="utf-8"
        )
        self.assertIn("const releaseQualificationReceiptMaxBytes = 2048", probe)
        self.assertIn("decoder.DisallowUnknownFields()", probe)
        self.assertIn("(&liveFreshLaunchAcceptanceOps{", probe)
        self.assertIn("}).SendOnce()", probe)
        self.assertIn('counts["load-buffer"] != 1', probe)
        self.assertNotIn("acceptanceOnlyResultMaxBytes", probe)

    def test_sandbox_drops_inherited_test_helpers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="helper-env-control.") as tmp:
            root = Path(tmp)
            namespace = self.harness_namespace(root)
            cache = root / "module-cache"
            cache.mkdir()
            env = namespace["_sandbox_env"](
                root / "task",
                {
                    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                    "SOFTKILL_TEST_HELPER": "eof_clean",
                    "ORPHAN_CONTROL_CLIENT_HELPER": "fixture",
                    "GO_WANT_HELPER_PROCESS": "1",
                },
                str(cache),
            )
        self.assertNotIn("SOFTKILL_TEST_HELPER", env)
        self.assertNotIn("ORPHAN_CONTROL_CLIENT_HELPER", env)
        self.assertNotIn("GO_WANT_HELPER_PROCESS", env)

    def test_runtime_pass_schema_is_complete_and_consistent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="runtime-schema-control.") as tmp:
            namespace = self.harness_namespace(Path(tmp))
        validate = namespace["_validate_runtime_document"]
        expected = namespace["EXPECTED_RUNTIME_CASE_IDS"]

        valid = {
            "verdict": "PASS",
            "summary": "fixture complete",
            "cases": [{"name": name, "passed": True} for name in expected],
        }
        self.assertIsNone(validate(valid))

        invalid_documents = (
            {"verdict": "PASS"},
            {**valid, "cases": [{"name": name, "passed": name != expected[0]} for name in expected]},
            {**valid, "cases": valid["cases"] + [{"name": "extra", "passed": True}]},
            {**valid, "cases": valid["cases"][:-1] + [valid["cases"][0]]},
            {**valid, "cases": [{"name": name, "passed": 1} for name in expected]},
        )
        for document in invalid_documents:
            with self.subTest(document=document):
                self.assertIsNotNone(validate(document))

    def test_runtime_probe_rejects_missing_metadata_recreation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="missing-meta-control.") as tmp:
            root = Path(tmp)
            env = self.isolated_env(root)
            env["AGENT_DECK_TASK_ROOT"] = str(root)
            bridge = root / "unsafe_missing_bridge.py"
            bridge.write_bytes(UNSAFE_MISSING_BRIDGE.read_bytes())
            completed = subprocess.run(
                [
                    os.environ.get("PYTHON", "python3"),
                    "-I",
                    str(FIXTURES / "runtime_recreation_probe.py"),
                    str(bridge),
                ],
                cwd=root,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=10,
            )
        marker = "AGENT_DECK_RELEASE_QUALIFICATION="
        document = json.loads(next(line[len(marker) :] for line in completed.stdout.splitlines() if line.startswith(marker)))
        cases = {case["name"]: case["passed"] for case in document["cases"]}
        self.assertEqual(document["verdict"], "FAIL", completed.stderr)
        self.assertIs(cases["missing-meta.json"], False)

    def test_missing_cache_never_executes_go(self) -> None:
        with tempfile.TemporaryDirectory(prefix="offline-cache-control.") as tmp:
            root = Path(tmp)
            source = self.minimal_candidate(root)
            marker = root / "go-ran"
            fake_go = root / "go"
            fake_go.write_text(
                f"#!/bin/sh\nprintf ran > {marker}\nexit 9\n",
                encoding="utf-8",
            )
            fake_go.chmod(0o755)
            completed, payload = self.run_harness(
                "--source", str(source), "--go", str(fake_go)
            )
            marker_exists = marker.exists()
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(payload["verdict"], "NOT_VERIFIED")
        self.assertFalse(marker_exists, "Go ran before offline task isolation")


if __name__ == "__main__":
    unittest.main()
