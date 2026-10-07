#!/usr/bin/env python3
"""Chezmoi target-mode tests for the generic Agent Deck companion tools."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
SOURCE_BIN = REPO / "private_dot_local/bin"
TOOL_NAMES = (
    "agent-deck-hook-probe",
    "agent-deck-maintenance-collector",
    "agent-deck-maintenance-controller",
    "agent-deck-work-registry",
)


class OwnerOnlyToolCase(unittest.TestCase):
    def test_private_executable_sources_materialize_owner_only_and_idempotently(
        self,
    ) -> None:
        chezmoi = shutil.which("chezmoi")
        self.assertIsNotNone(chezmoi, "chezmoi is required for target-mode coverage")

        expected_sources = {
            SOURCE_BIN / f"private_executable_{name}" for name in TOOL_NAMES
        }
        legacy_sources = {SOURCE_BIN / f"executable_{name}" for name in TOOL_NAMES}
        self.assertTrue(all(path.is_file() for path in expected_sources))
        self.assertTrue(all(not path.exists() for path in legacy_sources))

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            os.chmod(root, 0o700)
            source = root / "source"
            source_bin = source / "private_dot_local" / "bin"
            destination = root / "destination"
            cache = root / "cache"
            home = root / "home"
            for directory in (
                source,
                source / "private_dot_local",
                source_bin,
                destination,
                cache,
                home,
            ):
                directory.mkdir(mode=0o700)

            source_bytes: dict[str, bytes] = {}
            for path in sorted(expected_sources):
                payload = path.read_bytes()
                source_bytes[path.name.removeprefix("private_executable_")] = payload
                isolated_source = source_bin / path.name
                isolated_source.write_bytes(payload)
                isolated_source.chmod(0o600)

            config = root / "chezmoi.toml"
            config.write_text("", encoding="utf-8")
            config.chmod(0o600)
            persistent_state = root / "chezmoi-state.boltdb"
            command = [
                chezmoi,
                "--source",
                str(source),
                "--destination",
                str(destination),
                "--config",
                str(config),
                "--cache",
                str(cache),
                "--persistent-state",
                str(persistent_state),
                "--no-tty",
                "--no-pager",
                "--color=false",
                "--refresh-externals=never",
                "apply",
                "--force",
            ]
            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home),
                    "XDG_CACHE_HOME": str(cache),
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "XDG_STATE_HOME": str(root / "state"),
                }
            )

            first = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                env=env,
                timeout=10,
            )
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)

            expected_targets = {
                Path(".local/bin") / name for name in TOOL_NAMES
            }
            actual_targets = {
                path.relative_to(destination)
                for path in destination.rglob("*")
                if path.is_file()
            }
            self.assertEqual(actual_targets, expected_targets)
            for relative in expected_targets:
                target = destination / relative
                self.assertEqual(target.read_bytes(), source_bytes[target.name])
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)

            second = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                env=env,
                timeout=10,
            )
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            second_targets = {
                path.relative_to(destination)
                for path in destination.rglob("*")
                if path.is_file()
            }
            self.assertEqual(second_targets, expected_targets)
            for relative in expected_targets:
                target = destination / relative
                self.assertEqual(target.read_bytes(), source_bytes[target.name])
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)


if __name__ == "__main__":
    unittest.main()
