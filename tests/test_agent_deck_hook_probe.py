#!/usr/bin/env python3
"""Isolated acceptance tests for the Agent Deck hook configuration probe."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
PROBE = REPO / "private_dot_local/bin/executable_agent-deck-hook-probe"

CLAUDE_EVENTS = {
    "SessionStart": ("", True),
    "UserPromptSubmit": ("", True),
    "Stop": ("", False),
    "PermissionRequest": ("", False),
    "Notification": ("permission_prompt|elicitation_dialog", True),
    "SessionEnd": ("", True),
    "PreCompact": ("", False),
}


def claude_hooks(command: str = "agent-deck hook-handler") -> dict[str, list[dict]]:
    return {
        event: [
            {
                **({"matcher": matcher} if matcher else {}),
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                        **({"async": True} if asynchronous else {}),
                    }
                ],
            }
        ]
        for event, (matcher, asynchronous) in CLAUDE_EVENTS.items()
    }


class ProbeCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.cwd = self.home / "work/project"
        self.bin = self.root / "bin"
        self.ad_config = self.root / "agent-deck.toml"
        self.home.mkdir()
        self.cwd.mkdir(parents=True)
        self.bin.mkdir()
        self.ad_config.write_text("", encoding="utf-8")
        for name in ("agent-deck", "codex", "claude"):
            executable = self.bin / name
            executable.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
            executable.chmod(0o755)

    def write_codex(self, text: str, *, project: bool = False) -> Path:
        directory = self.cwd / ".codex" if project else self.home / ".codex"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "config.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def write_claude(self, value: object, *, scope: str = "user") -> Path:
        if scope == "user":
            path = self.home / ".claude/settings.json"
        elif scope == "project":
            path = self.cwd / ".claude/settings.json"
        elif scope == "local":
            path = self.cwd / ".claude/settings.local.json"
        else:
            raise AssertionError(scope)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, str):
            path.write_text(value, encoding="utf-8")
        else:
            path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def run_probe(
        self, *extra: str, remove_exec: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        if remove_exec:
            (self.bin / remove_exec).unlink()
        env = {
            "HOME": str(self.home),
            "PATH": str(self.bin),
            "LANG": "C.UTF-8",
        }
        return subprocess.run(
            [
                sys.executable,
                str(PROBE),
                "--home",
                str(self.home),
                "--cwd",
                str(self.cwd),
                "--agent-deck-config",
                str(self.ad_config),
                "--fixture",
                *extra,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
        )

    def make_other_runtime_valid(self, runtime: str) -> None:
        if runtime != "codex":
            self.write_codex('notify = ["agent-deck", "codex-notify"]\n')
        if runtime != "claude":
            self.write_claude({"hooks": claude_hooks()})

    def assert_status(
        self, result: subprocess.CompletedProcess[str], runtime: str, status: str, reason: str
    ) -> None:
        needle = f"runtime={runtime} surface=config status={status} reason={reason}"
        self.assertIn(needle, result.stdout, result.stdout + result.stderr)

    def test_valid_codex_top_level_notify(self) -> None:
        self.make_other_runtime_valid("codex")
        self.write_codex('notify = ["agent-deck", "codex-notify"]\n[notice]\nhide = true\n')
        result = self.run_probe()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assert_status(result, "codex", "VERIFIED", "EXPECTED_NOTIFY")

    def test_agent_deck_profile_config_dirs_are_effective(self) -> None:
        codex_dir = self.root / "profile-codex"
        claude_dir = self.root / "profile-claude"
        codex_dir.mkdir()
        claude_dir.mkdir()
        (codex_dir / "config.toml").write_text(
            'notify = ["agent-deck", "codex-notify"]\n', encoding="utf-8"
        )
        (claude_dir / "settings.json").write_text(
            json.dumps({"hooks": claude_hooks()}), encoding="utf-8"
        )
        self.ad_config.write_text(
            "[profiles.default.codex]\n"
            f'config_dir = "{codex_dir}"\n'
            "[profiles.default.claude]\n"
            f'config_dir = "{claude_dir}"\n',
            encoding="utf-8",
        )
        result = self.run_probe()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assert_status(result, "codex", "VERIFIED", "EXPECTED_NOTIFY")
        self.assert_status(result, "claude", "VERIFIED", "EXPECTED_HOOKS")

    def test_nested_codex_notify_is_not_effective(self) -> None:
        self.make_other_runtime_valid("codex")
        self.write_codex('[notice]\nnotify = ["agent-deck", "codex-notify"]\n')
        result = self.run_probe()
        self.assertNotEqual(0, result.returncode)
        self.assert_status(result, "codex", "NOT_VERIFIED", "MISPLACED_NOTIFY")

    def test_project_only_codex_notify_is_ignored(self) -> None:
        self.make_other_runtime_valid("codex")
        self.write_codex('notify = ["agent-deck", "codex-notify"]\n', project=True)
        result = self.run_probe()
        self.assertNotEqual(0, result.returncode)
        self.assert_status(result, "codex", "NOT_VERIFIED", "MISSING_EFFECTIVE_NOTIFY")
        self.assertIn(
            "runtime=codex surface=project-notify status=UNSUPPORTED "
            "reason=INEFFECTIVE_PROJECT_SCOPE",
            result.stdout,
        )

    def test_malformed_codex_toml(self) -> None:
        self.make_other_runtime_valid("codex")
        self.write_codex("notify = [\n")
        result = self.run_probe()
        self.assertNotEqual(0, result.returncode)
        self.assert_status(result, "codex", "NOT_VERIFIED", "MALFORMED_TOML")

    def test_missing_notify_executable(self) -> None:
        self.make_other_runtime_valid("codex")
        self.write_codex('notify = ["agent-deck", "codex-notify"]\n')
        result = self.run_probe(remove_exec="agent-deck")
        self.assertNotEqual(0, result.returncode)
        self.assert_status(result, "codex", "NOT_VERIFIED", "NOTIFY_EXECUTABLE_MISSING")

    def test_valid_claude_hooks(self) -> None:
        self.make_other_runtime_valid("claude")
        self.write_claude({"hooks": claude_hooks(), "unrelated": "FIXTURE_SECRET_DO_NOT_PRINT"})
        result = self.run_probe()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assert_status(result, "claude", "VERIFIED", "EXPECTED_HOOKS")
        self.assertNotIn("FIXTURE_SECRET_DO_NOT_PRINT", result.stdout + result.stderr)

    def test_claude_hook_arrays_merge_across_user_and_project_layers(self) -> None:
        self.make_other_runtime_valid("claude")
        hooks = claude_hooks()
        user_events = {name: value for name, value in hooks.items() if name != "PreCompact"}
        self.write_claude({"hooks": user_events})
        self.write_claude({"hooks": {"PreCompact": hooks["PreCompact"]}}, scope="project")
        result = self.run_probe()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assert_status(result, "claude", "VERIFIED", "EXPECTED_HOOKS")

    def test_malformed_claude_json(self) -> None:
        self.make_other_runtime_valid("claude")
        self.write_claude('{"hooks":')
        result = self.run_probe()
        self.assertNotEqual(0, result.returncode)
        self.assert_status(result, "claude", "NOT_VERIFIED", "MALFORMED_JSON")

    def test_missing_claude_event(self) -> None:
        self.make_other_runtime_valid("claude")
        hooks = claude_hooks()
        hooks.pop("PreCompact")
        self.write_claude({"hooks": hooks})
        result = self.run_probe()
        self.assertNotEqual(0, result.returncode)
        self.assert_status(result, "claude", "NOT_VERIFIED", "MISSING_EVENT_PRECOMPACT")

    def test_wrong_claude_command(self) -> None:
        self.make_other_runtime_valid("claude")
        self.write_claude({"hooks": claude_hooks("other-hook")})
        result = self.run_probe()
        self.assertNotEqual(0, result.returncode)
        self.assert_status(result, "claude", "NOT_VERIFIED", "WRONG_COMMAND_SESSIONSTART")

    def test_local_disable_shadows_valid_user_hooks(self) -> None:
        self.make_other_runtime_valid("claude")
        self.write_claude({"hooks": claude_hooks()})
        self.write_claude({"disableAllHooks": True}, scope="local")
        result = self.run_probe()
        self.assertNotEqual(0, result.returncode)
        self.assert_status(result, "claude", "NOT_VERIFIED", "HOOKS_DISABLED_BY_LOCAL")

    def test_managed_only_policy_rejects_user_hooks(self) -> None:
        self.make_other_runtime_valid("claude")
        self.write_claude({"hooks": claude_hooks()})
        managed = self.root / "managed.json"
        managed.write_text(json.dumps({"allowManagedHooksOnly": True}), encoding="utf-8")
        result = self.run_probe("--claude-managed-settings", str(managed))
        self.assertNotEqual(0, result.returncode)
        self.assert_status(result, "claude", "NOT_VERIFIED", "MANAGED_HOOKS_ONLY")

    def test_optional_missing_runtime_is_skipped(self) -> None:
        self.write_codex('notify = ["agent-deck", "codex-notify"]\n')
        result = self.run_probe("--optional-runtime", "claude", remove_exec="claude")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assert_status(result, "claude", "SKIPPED", "OPTIONAL_RUNTIME_ABSENT")

    def test_proof_boundaries_are_explicit(self) -> None:
        self.make_other_runtime_valid("")
        result = self.run_probe()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        for runtime, surface in (
            ("codex", "hook-invocation"),
            ("claude", "hook-invocation"),
            ("agent-deck", "inbox-delivery"),
            ("agent-deck", "child-completion"),
            ("slack", "end-to-end-delivery"),
        ):
            self.assertIn(
                f"runtime={runtime} surface={surface} status=NOT_VERIFIED reason=OUT_OF_SCOPE",
                result.stdout,
            )
        lowered = result.stdout.lower()
        self.assertNotIn("inbox-delivery status=verified", lowered)
        self.assertNotIn("end-to-end-delivery status=verified", lowered)

    def test_probe_never_executes_configured_commands(self) -> None:
        marker = self.root / "executed"
        dangerous = self.bin / "agent-deck"
        dangerous.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
        dangerous.chmod(0o755)
        self.make_other_runtime_valid("")
        result = self.run_probe()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
