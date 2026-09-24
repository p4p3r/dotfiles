#!/usr/bin/env python3
"""Render-time contracts for the declarative Agent Deck configuration."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "private_dot_config/agent-deck/private_config.toml.tmpl"
UPDATER = REPO / "nix/modules/agent-cli-updates.nix"
CHEZMOI = shutil.which("chezmoi")

MANAGED_COMMANDS = {
    "claude": ".local/bin/claude",
    "codex": ".npm-global/bin/codex",
}


class AgentDeckConfigCase(unittest.TestCase):
    def test_updater_and_template_share_managed_cli_destinations(self) -> None:
        updater = UPDATER.read_text(encoding="utf-8")
        template = TEMPLATE.read_text(encoding="utf-8")

        for tool, relative_path in MANAGED_COMMANDS.items():
            with self.subTest(tool=tool):
                self.assertIn(
                    f'local {tool}="$HOME/{relative_path}"',
                    updater,
                )
                self.assertIn(
                    f'printf "%s/{relative_path}" .chezmoi.homeDir | quote',
                    template,
                )

    @unittest.skipUnless(CHEZMOI, "chezmoi is required for the render contract")
    def test_render_expands_managed_cli_commands_to_home(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-deck-config.") as temp:
            root = Path(temp)
            home = root / "home"
            home.mkdir()
            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home),
                    "SLACK_APP_TOKEN": "",
                    "SLACK_BOT_TOKEN": "",
                    "SLACK_DECK_CHANNEL": "",
                    "SLACK_DECK_USER": "",
                }
            )

            result = subprocess.run(
                [
                    CHEZMOI,
                    "--config",
                    str(root / "config.toml"),
                    "--cache",
                    str(root / "cache"),
                    "--persistent-state",
                    str(root / "state.boltdb"),
                    "--source",
                    str(REPO),
                    "--refresh-externals=never",
                    "execute-template",
                    "--file",
                    str(TEMPLATE),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                timeout=10,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            config = tomllib.loads(result.stdout)

            for tool, relative_path in MANAGED_COMMANDS.items():
                with self.subTest(tool=tool):
                    expected = str(home / relative_path)
                    self.assertTrue(Path(expected).is_absolute())
                    self.assertEqual(expected, config[tool]["command"])


if __name__ == "__main__":
    unittest.main()
