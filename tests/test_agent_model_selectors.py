#!/usr/bin/env python3
"""Render the agent defaults without accessing the live home or calling a provider."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest


REPO = Path(__file__).resolve().parents[1]
CHEZMOI = shutil.which("chezmoi")


@unittest.skipUnless(CHEZMOI, "chezmoi is required for the render contract")
class AgentModelSelectorsCase(unittest.TestCase):
    def render(self, relative: str) -> str:
        with tempfile.TemporaryDirectory(prefix="agent-model-selectors.") as temp:
            root = Path(temp)
            home = root / "home"
            home.mkdir()
            result = subprocess.run(
                [
                    CHEZMOI,
                    "--config", str(root / "config.toml"),
                    "--cache", str(root / "cache"),
                    "--persistent-state", str(root / "state.boltdb"),
                    "--source", str(REPO),
                    "--refresh-externals=never",
                    "execute-template", "--file", str(REPO / relative),
                ],
                env={"HOME": str(home), "PATH": os.environ["PATH"], "USER": "synthetic-user"},
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(result.stdout.strip(), relative)
            return result.stdout

    def test_codex_defaults_to_luna_with_separate_high_effort(self) -> None:
        config = tomllib.loads(self.render("private_dot_codex/private_config.toml.tmpl"))
        self.assertEqual("gpt-6-luna", config["model"])
        self.assertEqual("high", config["model_reasoning_effort"])

    def test_claude_settings_default_to_sonnet(self) -> None:
        settings = json.loads(self.render("dot_claude/settings.json.tmpl"))
        self.assertEqual("sonnet", settings["model"])

    def test_agent_deck_claude_default_is_sonnet(self) -> None:
        config = tomllib.loads(self.render("private_dot_config/agent-deck/private_config.toml.tmpl"))
        self.assertEqual("sonnet", config["claude"]["default_model"])


if __name__ == "__main__":
    unittest.main()
