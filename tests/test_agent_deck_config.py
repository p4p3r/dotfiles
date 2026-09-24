#!/usr/bin/env python3
"""Render-time contracts for the declarative Agent Deck configuration."""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
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

EXISTING_AGENT_DECK_GATES = (
    (
        "internal/session/codex_output.go",
        'event.Payload.Phase != "final_answer"',
    ),
    ("cmd/agent-deck/session_cmd.go", "freshWait = *timeout"),
    ("internal/tmux/detector.go", "HasCodexBusyIndicator(content)"),
    (
        "internal/session/conductor_bridge.py",
        "conductor_agent_command(name),",
    ),
    (
        "internal/session/conductor_bridge.py",
        "codex output freshness timeout",
    ),
    (
        "internal/session/conductor_bridge.py",
        '_resolve_secret(str(sl.get("channel_id"',
    ),
    (
        "internal/session/conductor_bridge.py",
        "_resolve_secret(str(user_id",
    ),
)

ACCEPTANCE_ONLY_GATES = (
    (
        "cmd/agent-deck/session_cmd.go",
        'fs.Bool("acceptance-only", false,',
    ),
    ("cmd/agent-deck/session_cmd.go", "type acceptanceOnlyResult struct {"),
    (
        "cmd/agent-deck/session_cmd.go",
        "acceptanceOnlySchemaVersion    = 1",
    ),
    (
        "cmd/agent-deck/session_cmd.go",
        "acceptanceOnlyResultMaxBytes   = 2048",
    ),
    (
        "cmd/agent-deck/session_cmd.go",
        "if len(raw)+1 > acceptanceOnlyResultMaxBytes {",
    ),
    (
        "cmd/agent-deck/main.go",
        "acceptanceOnlyDiagnostics := acceptanceOnlyCommandRequested(os.Args[1:])",
    ),
    (
        "cmd/agent-deck/launch_cmd.go",
        'fs.Bool("acceptance-only", false,',
    ),
    (
        "cmd/agent-deck/launch_cmd.go",
        "result := runFreshLaunchAcceptance(&liveFreshLaunchAcceptanceOps{",
    ),
    (
        "cmd/agent-deck/launch_acceptance.go",
        "target.SendKeysAndEnterPrivate(o.message)",
    ),
    (
        "cmd/agent-deck/launch_acceptance.go",
        "return retainFreshLaunchInstance(ops.AcceptedVerdict(delivery), instanceID)",
    ),
)

ACCEPTANCE_ONLY_DIAGNOSTIC_BOUNDARY = (
    "cmd/agent-deck/main.go",
    "acceptanceOnlyDiagnostics := acceptanceOnlyCommandRequested(os.Args[1:])",
)
ACCEPTANCE_ONLY_STARTUP_PROBE = ("cmd/agent-deck/main.go", "ensureTmuxOnPath()")


class AgentDeckConfigCase(unittest.TestCase):
    @staticmethod
    def _extract_updater_functions(*names: str) -> str:
        lines = UPDATER.read_text(encoding="utf-8").splitlines()
        functions: list[str] = []
        for name in names:
            signature = f"      {name}() {{"
            try:
                start = lines.index(signature)
            except ValueError as error:
                raise AssertionError(f"missing updater function {name}") from error

            for end in range(start + 1, len(lines)):
                if lines[end] == "      }":
                    break
            else:
                raise AssertionError(f"unterminated updater function {name}")

            functions.append("\n".join(line[6:] for line in lines[start : end + 1]))

        return "\n\n".join(functions).replace("''${", "${")

    @staticmethod
    def _write_release_source(root: Path, omitted_needle: str | None = None) -> None:
        by_path: dict[str, list[str]] = {}
        for relative_path, needle in EXISTING_AGENT_DECK_GATES + ACCEPTANCE_ONLY_GATES:
            if needle != omitted_needle:
                by_path.setdefault(relative_path, []).append(needle)

        main_path, startup_probe = ACCEPTANCE_ONLY_STARTUP_PROBE
        by_path.setdefault(main_path, []).append(startup_probe)

        for relative_path, needles in by_path.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(needles) + "\n", encoding="utf-8")

    def _run_release_gate(self, source: Path) -> subprocess.CompletedProcess[str]:
        functions = self._extract_updater_functions(
            "log",
            "check_agent_deck_feature",
            "check_agent_deck_feature_before",
            "agent_deck_release_is_safe",
        )
        return subprocess.run(
            ["bash", "-c", f'{functions}\nagent_deck_release_is_safe "$1"', "gate", str(source)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def _run_offline_agent_deck_update(
        self, root: Path, omitted_needle: str
    ) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
        home = root / "home"
        fake_bin = root / "fake-bin"
        source = root / "release-source"
        archive = root / "release.tar.gz"
        update_sentinel = root / "update-called"
        agent_deck = home / ".local/bin/agent-deck"
        fake_bin.mkdir(parents=True)
        agent_deck.parent.mkdir(parents=True)
        self._write_release_source(source, omitted_needle)

        with tarfile.open(archive, "w:gz") as tar:
            tar.add(source, arcname="agent-deck-v1.1.0")

        agent_deck.write_text(
            "#!/usr/bin/env bash\n"
            'if [[ "${1:-}" == "--version" ]]; then\n'
            '  printf "%s\\n" "agent-deck 1.0.0"\n'
            "  exit 0\n"
            "fi\n"
            'printf "%s\\n" called >"$TEST_UPDATE_SENTINEL"\n'
            "exit 99\n",
            encoding="utf-8",
        )
        agent_deck.chmod(0o755)

        (fake_bin / "timeout").write_text(
            '#!/bin/sh\nshift\nexec "$@"\n', encoding="utf-8"
        )
        (fake_bin / "jq").write_text(
            '#!/bin/sh\ncat >/dev/null\nprintf "%s\\n" "v1.1.0"\n',
            encoding="utf-8",
        )
        (fake_bin / "curl").write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            'output=""\n'
            "while (( $# )); do\n"
            '  if [[ "$1" == "-o" ]]; then\n'
            '    output="$2"\n'
            "    shift 2\n"
            "  else\n"
            "    shift\n"
            "  fi\n"
            "done\n"
            'if [[ -z "$output" ]]; then\n'
            '  printf "%s\\n" \'{"tag_name":"v1.1.0"}\'\n'
            "else\n"
            '  cp "$TEST_RELEASE_ARCHIVE" "$output"\n'
            "fi\n",
            encoding="utf-8",
        )
        for command in ("timeout", "jq", "curl"):
            (fake_bin / command).chmod(0o755)

        functions = self._extract_updater_functions(
            "log",
            "check_agent_deck_feature",
            "check_agent_deck_feature_before",
            "agent_deck_release_is_safe",
            "update_agent_deck",
        )
        script = f"""
set -u
state_dir="$HOME/state"
deferred_marker="$state_dir/deferred-agent-deck-release"
restart_marker="$state_dir/restart-agent-deck-services"
mkdir -p "$state_dir"
{functions}
update_agent_deck
"""
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "PATH": f"{fake_bin}:{env['PATH']}",
                "TEST_RELEASE_ARCHIVE": str(archive),
                "TEST_UPDATE_SENTINEL": str(update_sentinel),
            }
        )
        result = subprocess.run(
            ["bash", "-c", script],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        return result, home / "state/deferred-agent-deck-release", update_sentinel

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

    def test_updater_pins_each_acceptance_only_release_invariant(self) -> None:
        updater = UPDATER.read_text(encoding="utf-8")

        for relative_path, needle in ACCEPTANCE_ONLY_GATES:
            with self.subTest(relative_path=relative_path, needle=needle):
                self.assertIn(f'"{relative_path}"', updater)
                self.assertIn(f"'{needle}'", updater)

        path, startup_probe = ACCEPTANCE_ONLY_STARTUP_PROBE
        self.assertIn(f'"{path}"', updater)
        self.assertIn(f"'{startup_probe}'", updater)

    def test_release_gate_rejects_each_missing_acceptance_only_invariant(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-deck-release-gate.") as temp:
            root = Path(temp)
            complete = root / "complete"
            self._write_release_source(complete)
            accepted = self._run_release_gate(complete)
            self.assertEqual(0, accepted.returncode, accepted.stdout + accepted.stderr)

            for _, needle in ACCEPTANCE_ONLY_GATES:
                with self.subTest(needle=needle):
                    source = root / f"missing-{len(needle)}"
                    if source.exists():
                        shutil.rmtree(source)
                    self._write_release_source(source, needle)
                    rejected = self._run_release_gate(source)
                    self.assertNotEqual(0, rejected.returncode)
                    self.assertIn("Agent Deck safety gate missing:", rejected.stdout)

    def test_release_gate_requires_diagnostic_boundary_before_startup_probe(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-deck-release-order.") as temp:
            source = Path(temp) / "source"
            self._write_release_source(source)
            main_path, startup_probe = ACCEPTANCE_ONLY_STARTUP_PROBE
            boundary_path, boundary = ACCEPTANCE_ONLY_DIAGNOSTIC_BOUNDARY
            self.assertEqual(main_path, boundary_path)
            main = source / main_path
            text = main.read_text(encoding="utf-8")
            main.write_text(
                text.replace(
                    f"{boundary}\n{startup_probe}\n",
                    f"{startup_probe}\n{boundary}\n",
                ),
                encoding="utf-8",
            )

            rejected = self._run_release_gate(source)
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("pre-startup acceptance-only diagnostic boundary", rejected.stdout)

    @unittest.skipUnless(
        shutil.which("bash") and shutil.which("tar"),
        "bash and tar are required",
    )
    def test_updater_defers_offline_release_missing_each_invariant(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-deck-update-defer.") as temp:
            root = Path(temp)
            for index, (_, needle) in enumerate(ACCEPTANCE_ONLY_GATES):
                with self.subTest(needle=needle):
                    case = root / str(index)
                    case.mkdir()
                    result, marker, update_sentinel = self._run_offline_agent_deck_update(
                        case, needle
                    )
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertEqual("v1.1.0\n", marker.read_text(encoding="utf-8"))
                    self.assertFalse(update_sentinel.exists())
                    self.assertIn("Deferring Agent Deck v1.1.0", result.stdout)


if __name__ == "__main__":
    unittest.main()
