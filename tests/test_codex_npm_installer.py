#!/usr/bin/env python3
"""Deterministic coverage for the fail-closed Codex npm installer."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
INSTALLER = REPO / "nix/scripts/codex-npm-install.sh"


FAKE_NPM = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import sys

config = json.loads(os.environ["TEST_NPM_CONFIG"])
live_prefix = Path(os.environ["TEST_LIVE_PREFIX"])
log_path = Path(os.environ["TEST_NPM_LOG"])
suffix = os.environ.get("TEST_PLATFORM_SUFFIX", "linux-x64")


def record(message):
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(message + "\n")


def install(prefix, version, *, binary=True, companion=True):
    root = prefix / "lib/node_modules/@openai/codex"
    shutil.rmtree(root, ignore_errors=True)
    (root / "node_modules/@openai").mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(
        json.dumps({"name": "@openai/codex", "version": version}),
        encoding="utf-8",
    )
    bin_dir = prefix / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    executable = bin_dir / "codex"
    executable.unlink(missing_ok=True)
    if binary:
        executable.write_text(
            "#!/bin/sh\nprintf '%s\\n' 'codex-cli " + version + "'\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
    if companion:
        platform = root / "node_modules/@openai" / ("codex-" + suffix)
        platform.mkdir()
        (platform / "package.json").write_text(
            json.dumps(
                {"name": "@openai/codex", "version": version + "-" + suffix}
            ),
            encoding="utf-8",
        )


args = sys.argv[1:]
record(" ".join(args))
if args[:1] == ["view"]:
    spec = args[1]
    field = args[2]
    if spec == "@openai/codex@latest" and field == "version":
        print(json.dumps(config["latest"]))
        raise SystemExit(0)
    if spec == "@openai/codex" and field == "versions":
        print(json.dumps(config["versions"] + config["companions"]))
        raise SystemExit(0)
    marker = "@openai/codex@"
    if spec.startswith(marker) and field == "version":
        exact = spec[len(marker):]
        if exact in config["companions"]:
            print(json.dumps(exact))
            raise SystemExit(0)
    raise SystemExit(1)

if args[:1] == ["install"]:
    prefix = Path(args[args.index("--prefix") + 1])
    version = args[-1].split("@", 2)[-1]
    is_live = prefix == live_prefix
    if is_live and version in config.get("live_fail", []):
        install(prefix, version, binary=False, companion=False)
        raise SystemExit(1)
    binary = version not in config.get("temp_missing_binary", []) or is_live
    install(
        prefix,
        version,
        binary=binary,
        companion=(version + "-" + suffix) in config["companions"],
    )
    raise SystemExit(0)

raise SystemExit(2)
'''


FAKE_UNAME = r'''#!/bin/sh
case "$1" in
  -s) printf '%s\n' "$TEST_UNAME_S" ;;
  -m) printf '%s\n' "$TEST_UNAME_M" ;;
  *) exit 2 ;;
esac
'''


class CodexNpmInstallerCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="codex-npm-installer.")
        self.root = Path(self.temp.name)
        self.live = self.root / "live"
        self.fake_bin = self.root / "fake-bin"
        self.fake_bin.mkdir()
        self.log = self.root / "npm.log"
        (self.fake_bin / "npm").write_text(FAKE_NPM, encoding="utf-8")
        (self.fake_bin / "uname").write_text(FAKE_UNAME, encoding="utf-8")
        (self.fake_bin / "npm").chmod(0o755)
        (self.fake_bin / "uname").chmod(0o755)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def config(
        self,
        *,
        latest: str = "2.0.0",
        versions: list[str] | None = None,
        companions: list[str] | None = None,
        **extra: object,
    ) -> dict[str, object]:
        value: dict[str, object] = {
            "latest": latest,
            "versions": versions or ["1.0.0", "2.0.0"],
            "companions": companions
            or ["1.0.0-linux-x64", "2.0.0-linux-x64"],
        }
        value.update(extra)
        return value

    def environment(self, config: dict[str, object], **extra: str) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{self.fake_bin}:{env['PATH']}",
                "TEST_NPM_CONFIG": json.dumps(config),
                "TEST_LIVE_PREFIX": str(self.live),
                "TEST_NPM_LOG": str(self.log),
                "TEST_PLATFORM_SUFFIX": "linux-x64",
                "TEST_UNAME_S": "Linux",
                "TEST_UNAME_M": "x86_64",
            }
        )
        env.update(extra)
        return env

    def write_install(
        self,
        version: str,
        *,
        binary: bool = True,
        companion: bool = True,
    ) -> None:
        root = self.live / "lib/node_modules/@openai/codex"
        platform = root / "node_modules/@openai/codex-linux-x64"
        platform.mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(
            json.dumps({"name": "@openai/codex", "version": version}),
            encoding="utf-8",
        )
        if companion:
            (platform / "package.json").write_text(
                json.dumps(
                    {
                        "name": "@openai/codex",
                        "version": f"{version}-linux-x64",
                    }
                ),
                encoding="utf-8",
            )
        bin_dir = self.live / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        if binary:
            executable = bin_dir / "codex"
            executable.write_text(
                f"#!/bin/sh\nprintf '%s\\n' 'codex-cli {version}'\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)

    def run_update(
        self, config: dict[str, object]
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(INSTALLER), "update", str(self.live)],
            check=False,
            capture_output=True,
            text=True,
            env=self.environment(config),
            timeout=10,
        )

    def installed_version(self) -> str:
        result = subprocess.run(
            [str(self.live / "bin/codex"), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result.stdout.strip().split()[-1]

    def test_complete_upgrade_is_qualified_then_installed(self) -> None:
        self.write_install("1.0.0")

        result = self.run_update(self.config())

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("2.0.0", self.installed_version())
        self.assertIn("Codex 2.0.0 is installed and healthy", result.stdout)
        installs = [line for line in self.log.read_text().splitlines() if "install" in line]
        self.assertEqual(2, len(installs))
        self.assertNotIn(str(self.live), installs[0])
        self.assertIn(str(self.live), installs[1])

    def test_incomplete_latest_retains_current_healthy_version(self) -> None:
        self.write_install("1.0.0")
        config = self.config(companions=["1.0.0-linux-x64"])

        result = self.run_update(config)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("1.0.0", self.installed_version())
        self.assertIn("Deferring Codex 2.0.0", result.stdout)
        self.assertNotIn("install --global", self.log.read_text())

    def test_npm_zero_without_candidate_binary_is_rejected_before_live_prefix(self) -> None:
        self.write_install("1.0.0")
        config = self.config(temp_missing_binary=["2.0.0"])

        result = self.run_update(config)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("1.0.0", self.installed_version())
        self.assertIn("isolated installation did not produce", result.stdout)
        installs = [line for line in self.log.read_text().splitlines() if "install" in line]
        self.assertEqual(1, len(installs))
        self.assertNotIn(str(self.live), installs[0])

    def test_failed_live_install_restores_previous_exact_version(self) -> None:
        self.write_install("1.0.0")
        config = self.config(live_fail=["2.0.0"])

        result = self.run_update(config)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertEqual("1.0.0", self.installed_version())
        self.assertIn("Codex 1.0.0 was restored and proven healthy", result.stdout)

    def test_failed_rollback_reports_that_no_healthy_live_install_is_proven(self) -> None:
        self.write_install("1.0.0")
        config = self.config(live_fail=["2.0.0", "1.0.0"])

        result = self.run_update(config)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("Rollback failed", result.stdout)
        self.assertFalse((self.live / "bin/codex").exists())

    def test_broken_live_install_recovers_to_newest_complete_stable(self) -> None:
        self.write_install("1.0.0", binary=False)
        config = self.config(
            latest="3.0.0",
            versions=["1.0.0", "2.0.0", "3.0.0", "4.0.0-beta.1"],
            companions=["1.0.0-linux-x64", "2.0.0-linux-x64"],
        )

        result = self.run_update(config)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("2.0.0", self.installed_version())
        self.assertIn("Recovering broken Codex with complete version 2.0.0", result.stdout)

    def test_supported_platform_mapping(self) -> None:
        cases = (
            ("Linux", "x86_64", "@openai/codex-linux-x64 linux-x64"),
            ("Linux", "aarch64", "@openai/codex-linux-arm64 linux-arm64"),
            ("Darwin", "x86_64", "@openai/codex-darwin-x64 darwin-x64"),
            ("Darwin", "arm64", "@openai/codex-darwin-arm64 darwin-arm64"),
        )
        for operating_system, machine, expected in cases:
            with self.subTest(operating_system=operating_system, machine=machine):
                result = subprocess.run(
                    ["bash", str(INSTALLER), "platform"],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=self.environment(
                        self.config(),
                        TEST_UNAME_S=operating_system,
                        TEST_UNAME_M=machine,
                    ),
                    timeout=5,
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual(expected, result.stdout.strip())

    def test_unsupported_platform_fails_before_npm_is_called(self) -> None:
        result = subprocess.run(
            ["bash", str(INSTALLER), "update", str(self.live)],
            check=False,
            capture_output=True,
            text=True,
            env=self.environment(
                self.config(), TEST_UNAME_S="Plan9", TEST_UNAME_M="mips"
            ),
            timeout=5,
        )

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("do not support platform Plan9/mips", result.stdout)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
