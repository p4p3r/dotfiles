"""Offline generated-unit and packaged-caller checks; no activation."""

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]


class ControlNixCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="control-nix-")
        cls.root = Path(cls.temp.name)
        cls.env = os.environ.copy()
        cls.env.update({"HOME": str(cls.root), "XDG_CACHE_HOME": str(cls.root / "cache"),
                        "XDG_STATE_HOME": str(cls.root / "state"),
                        "XDG_CONFIG_HOME": str(cls.root / "config"),
                        "XDG_DATA_HOME": str(cls.root / "data"),
                        "PYTHONDONTWRITEBYTECODE": "1",
                        "CONTROL_PUBLIC_FLAKE": "path:" + str(REPO / "nix")})
        cls.fixture = '(import ./tests/agent_deck_control.nix { publicFlake = builtins.getEnv "CONTROL_PUBLIC_FLAKE"; })'
        cls.facts = json.loads(cls.run_nix("eval", "--json", "--expr", cls.fixture + ".facts").stdout)
        cls.runtime = Path(cls.run_nix("build", "--no-link", "--print-out-paths", "--expr", cls.fixture + ".runtime").stdout.strip())
        cls.render = Path(cls.run_nix("build", "--no-link", "--print-out-paths", "--expr", cls.fixture + ".render").stdout.strip())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def run_nix(cls, command, *args, success=True):
        result = subprocess.run(["nix", command, "--offline", "--impure", *args], cwd=REPO,
                                env=cls.env, capture_output=True, text=True, timeout=120)
        if success and result.returncode != 0:
            raise AssertionError(result.stderr)
        return result

    def test_generated_unit_has_finite_bounds_and_only_one_timer(self):
        service = self.facts["service"]["Service"]
        args = shlex.split(service["ExecStart"][0])
        self.assertEqual(service["Type"], "oneshot")
        self.assertEqual(service["TimeoutStartSec"], "90s")
        self.assertEqual(service["Restart"], "no")
        self.assertEqual(service["UMask"], "0077")
        self.assertEqual(service["StateDirectoryMode"], "0700")
        self.assertEqual(args[args.index("--profile") + 1], "fixture")
        self.assertEqual(args[args.index("--max-polls") + 1], "12")
        self.assertEqual(args[args.index("--poll-timeout") + 1], "5")
        self.assertEqual(args[args.index("--state") + 1], self.facts["registryState"])
        self.assertEqual(self.facts["timer"]["Timer"]["OnUnitInactiveSec"], "120s")
        self.assertEqual(self.facts["timer"]["Install"]["WantedBy"], ["timers.target"])
        self.assertNotIn("Install", self.facts["service"])
        self.assertEqual(self.facts["packageCount"], 1)
        service_name = self.facts["timer"]["Timer"]["Unit"]
        timer_name = service_name.removesuffix(".service") + ".timer"
        self.assertTrue((self.render / service_name).is_file())
        self.assertTrue((self.render / timer_name).is_file())
        verify = shutil.which("systemd-analyze")
        self.assertIsNotNone(verify, "generated-unit verification requires systemd-analyze")
        result = subprocess.run([verify, "--user", "verify", str(self.render / service_name),
                                 str(self.render / timer_name)], env=self.env, capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_numeric_options_fail_evaluation(self):
        for setting in ("maxPolls = 13;", "pollTimeoutSeconds = 6;", "cadenceSeconds = 0;"):
            with self.subTest(setting=setting):
                expr = f"({self.fixture}.evaluate true {{ {setting} }}).home.activationPackage.drvPath"
                result = self.run_nix("eval", "--raw", "--expr", expr, success=False)
                self.assertNotEqual(result.returncode, 0)

    def test_packaged_cli_polls_a_private_fixture_without_waking_an_agent(self):
        with tempfile.TemporaryDirectory(prefix="packaged-tick-", dir=self.root) as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            state = root / "registry.json"
            agent = root / "agent-deck"
            calls = root / "calls"
            agent.write_text("#!/bin/sh\n"
                             f"printf '%s\\n' \"$*\" >> {shlex.quote(str(calls))}\n"
                             "printf '%s\\n' '{\"id\":\"0123abcd-1700000000\",\"status\":\"running\",\"substate\":\"running\",\"output\":\"SYNTHETIC_PRIVATE_BODY\"}'\n")
            agent.chmod(0o700)
            registry = self.runtime / "bin/agent-deck-work-registry"
            registration = subprocess.run([str(registry), "--state", str(state), "--now", "2026-10-07T10:00:00Z",
                                            "register", "probe", "--owner-session-id", "0123abcd-1700000000",
                                            "--deadline", "2026-10-08T10:00:00Z"], env=self.env,
                                           capture_output=True, text=True, timeout=5)
            self.assertEqual(registration.returncode, 0, registration.stderr)
            result = subprocess.run([str(self.runtime / "bin/agent-deck-conductor-tick"),
                                     "--registry", str(registry), "--state", str(state), "--profile", "fixture",
                                     "--agent-deck", str(agent), "--now", "2026-10-07T10:00:00Z"],
                                    env=self.env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["polled"], 1)
            self.assertEqual(calls.read_text(), "-p fixture session show 0123abcd-1700000000 --json\n")
            self.assertNotIn("SYNTHETIC_PRIVATE_BODY", result.stdout + result.stderr + state.read_text())


if __name__ == "__main__":
    unittest.main()
