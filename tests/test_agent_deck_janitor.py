"""Execute the janitor against fake tools and a real temporary filesystem.

The destructive tasks are tested by letting them actually delete things under a
temporary root, because a test that only inspects the argv it would have run
proves nothing about what reaches the disk.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
JANITOR = REPO / "private_dot_local" / "bin" / "executable_agent-deck-janitor"


def write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def age(path: Path, days: float) -> None:
    stamp = time.time() - days * 86400
    os.utime(path, (stamp, stamp), follow_symlinks=False)


class JanitorCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.state = self.tmp / "state"
        self.calls = self.tmp / "calls"
        self.calls.mkdir()

        self.groups = [
            {"name": "conductor", "path": "conductor", "session_count": 2},
            {"name": "empty", "path": "empty", "session_count": 0},
            {"name": "parent", "path": "parent", "session_count": 0},
            {"name": "child", "path": "parent/child", "session_count": 1},
            {"name": "keepme", "path": "keepme", "session_count": 0},
        ]
        self.candidates = [
            {"id": "dead-0001", "title": "old-work", "idle_days": 40,
             "status": "stopped", "archived": False},
            {"id": "dead-0002", "title": "conductor-semgrep", "idle_days": 99,
             "status": "stopped", "archived": False},
        ]
        self.write_agent_deck()
        write_executable(self.bin / "git",
                         "#!/bin/sh\necho \"git $*\" >> \"$CALLS/git\"\nexit 0\n")

    def write_agent_deck(self, cleanup_exit: int = 0) -> None:
        payload = json.dumps({"groups": self.groups,
                              "candidates": getattr(self, "candidates", [])})
        write_executable(self.bin / "agent-deck", f"""#!/usr/bin/env python3
import json, os, pathlib, sys
argv = sys.argv[1:]
calls = pathlib.Path(os.environ["CALLS"]) / "agent-deck"
with calls.open("a") as fh:
    fh.write(" ".join(argv) + "\\n")
if argv[2:] == ["group", "list", "--json"]:
    sys.stdout.write({payload!r}); sys.exit(0)
if argv[2:4] == ["group", "delete"]:
    sys.exit(0)
if argv[2:4] == ["session", "cleanup"]:
    if {cleanup_exit}:
        sys.exit({cleanup_exit})
    sys.stdout.write({payload!r}); sys.exit(0)
if argv[2:4] == ["session", "remove"]:
    sys.exit(0)
sys.exit(9)
""")

    def run_janitor(self, *extra, apply=False):
        argv = [sys.executable, str(JANITOR),
                "--agent-deck", str(self.bin / "agent-deck"),
                "--git", str(self.bin / "git"),
                "--state-dir", str(self.state),
                "--profile", "default",
                *extra]
        if apply:
            argv.append("--apply")
        env = dict(os.environ, CALLS=str(self.calls))
        done = subprocess.run(argv, capture_output=True, text=True, env=env,
                              timeout=120, check=False)
        report = json.loads(done.stdout) if done.stdout.strip() else None
        return done, report

    def agent_deck_calls(self):
        path = self.calls / "agent-deck"
        return path.read_text().splitlines() if path.exists() else []

    # -- sessions -----------------------------------------------------------

    def test_session_cleanup_is_a_preview_without_apply(self) -> None:
        done, report = self.run_janitor("--session-retention-days", "30")
        self.assertEqual(done.returncode, 0, done.stderr)
        task = report["tasks"]["sessions"]
        self.assertEqual(task["status"], "OK")
        self.assertEqual([r["id"] for r in task["profiles"]["default"]["removed"]],
                         ["dead-0001", "dead-0002"])
        line = [c for c in self.agent_deck_calls() if "session cleanup" in c][0]
        self.assertIn("--days 30", line)
        self.assertIn("--dry-run", line)
        self.assertEqual([c for c in self.agent_deck_calls() if "session remove" in c],
                         [], "a preview must remove nothing")

    def test_session_cleanup_removes_candidates_with_apply(self) -> None:
        _, report = self.run_janitor("--session-retention-days", "30", apply=True)
        self.assertTrue(report["tasks"]["sessions"]["applied"])
        removals = [c for c in self.agent_deck_calls() if "session remove" in c]
        self.assertEqual(removals, ["-p default session remove dead-0001",
                                    "-p default session remove dead-0002"])

    def test_an_empty_candidate_reply_is_not_a_failure(self) -> None:
        # With nothing to purge the CLI answers in a different shape, with no
        # candidates key at all. The first armed run read that as malformed.
        self.candidates = None
        write_executable(self.bin / "agent-deck", """#!/usr/bin/env python3
import json, os, pathlib, sys
argv = sys.argv[1:]
(pathlib.Path(os.environ["CALLS"]) / "agent-deck").open("a").write(" ".join(argv) + chr(10))
if argv[2:4] == ["session", "cleanup"]:
    json.dump({"count": 0, "removed": [], "skipped": 0, "success": True}, sys.stdout)
    sys.exit(0)
sys.exit(0)
""")
        _, report = self.run_janitor(apply=True)
        task = report["tasks"]["sessions"]
        self.assertEqual(task["status"], "OK")
        self.assertEqual(task["profiles"]["default"]["removed"], [])

    def test_a_protected_title_is_never_purged(self) -> None:
        _, report = self.run_janitor("--protect-session-title", "conductor-semgrep",
                                     apply=True)
        profile = report["tasks"]["sessions"]["profiles"]["default"]
        self.assertEqual([r["id"] for r in profile["removed"]], ["dead-0001"])
        self.assertEqual([r["title"] for r in profile["exempt"]], ["conductor-semgrep"])
        removals = [c for c in self.agent_deck_calls() if "session remove" in c]
        self.assertEqual(removals, ["-p default session remove dead-0001"],
                         "the conductor row must survive even when dead and idle")

    def test_worktrees_are_never_pruned_by_the_session_sweep(self) -> None:
        # --prune-worktree destroys uncommitted work and is not this tool's call.
        self.run_janitor(apply=True)
        self.assertNotIn("--prune-worktree", " ".join(self.agent_deck_calls()))

    def test_a_failing_profile_degrades_without_aborting_later_tasks(self) -> None:
        self.write_agent_deck(cleanup_exit=4)
        root = self.tmp / "scratch"
        root.mkdir()
        stale = root / "stale"
        stale.mkdir()
        age(stale, 40)
        _, report = self.run_janitor("--artifact", f"{root}:30", apply=True)
        self.assertEqual(report["tasks"]["sessions"]["status"], "DEGRADED")
        self.assertEqual(report["status"], "DEGRADED")
        self.assertFalse(stale.exists(), "a failed task must not stop the next one")

    # -- groups -------------------------------------------------------------

    def test_empty_group_sweep_respects_descendants_and_protection(self) -> None:
        _, report = self.run_janitor("--empty-groups", "--protect-group", "keepme",
                                     apply=True)
        groups = report["tasks"]["groups"]["profiles"]["default"]
        self.assertEqual(groups["removed"], ["empty"])
        kept = {entry["path"]: entry["reason"] for entry in groups["kept"]}
        self.assertEqual(kept.get("parent"), "has descendants")
        self.assertEqual(kept.get("keepme"), "protected")
        deletes = [c for c in self.agent_deck_calls() if "group delete" in c]
        self.assertEqual(deletes, ["-p default group delete empty"])

    def test_group_sweep_is_off_unless_requested(self) -> None:
        _, report = self.run_janitor(apply=True)
        self.assertEqual(report["tasks"]["groups"]["status"], "SKIPPED")
        self.assertEqual([c for c in self.agent_deck_calls() if "group" in c], [])

    def test_group_preview_deletes_nothing(self) -> None:
        _, report = self.run_janitor("--empty-groups")
        self.assertCountEqual(
            report["tasks"]["groups"]["profiles"]["default"]["removed"],
            ["empty", "keepme"])
        self.assertEqual([c for c in self.agent_deck_calls() if "group delete" in c], [])

    # -- artifacts ----------------------------------------------------------

    def artifact_root(self):
        root = self.tmp / "scratch"
        root.mkdir()
        stale_dir = root / "stale-dir"
        stale_dir.mkdir()
        payload = stale_dir / "payload"
        payload.write_text("x" * 100)
        age(payload, 45)
        fresh_dir = root / "fresh-dir"
        fresh_dir.mkdir()
        stale_file = root / "stale-file"
        stale_file.write_text("y" * 10)
        keep = root / "keep-this"
        keep.mkdir()
        for path in (stale_dir, stale_file, keep):
            age(path, 45)
        age(fresh_dir, 1)
        return root, stale_dir, fresh_dir, stale_file, keep

    def test_artifacts_expire_by_age_and_honour_keep_patterns(self) -> None:
        root, stale_dir, fresh_dir, stale_file, keep = self.artifact_root()
        _, report = self.run_janitor("--artifact", f"{root}:30",
                                     "--keep-pattern", r"^keep-", apply=True)
        self.assertFalse(stale_dir.exists())
        self.assertFalse(stale_file.exists())
        self.assertTrue(fresh_dir.exists(), "an entry inside the window survives")
        self.assertTrue(keep.exists(), "a kept pattern survives regardless of age")
        entry = report["tasks"]["artifacts"]["roots"][str(root)]
        self.assertGreater(entry["bytes"], 100)

    def test_artifact_preview_deletes_nothing_but_reports_what_it_would(self) -> None:
        root, stale_dir, _, stale_file, keep = self.artifact_root()
        _, report = self.run_janitor("--artifact", f"{root}:30")
        self.assertTrue(stale_dir.exists())
        self.assertTrue(stale_file.exists())
        removed = report["tasks"]["artifacts"]["roots"][str(root)]["removed"]
        # No keep pattern here, so the aged keep-this is a candidate too.
        self.assertCountEqual(removed,
                              [str(stale_dir), str(stale_file), str(keep)])

    def test_a_symlink_is_removed_as_a_link_and_never_followed(self) -> None:
        root = self.tmp / "scratch"
        root.mkdir()
        outside = self.tmp / "precious"
        outside.mkdir()
        (outside / "keepme").write_text("important")
        link = root / "escape"
        link.symlink_to(outside)
        age(link, 90)
        self.run_janitor("--artifact", f"{root}:30", apply=True)
        self.assertFalse(link.exists())
        self.assertTrue((outside / "keepme").exists(),
                        "following the link would delete outside the root")

    def test_a_directory_is_aged_by_its_newest_immediate_child(self) -> None:
        # A build tree whose churn happens below the top level must not look
        # abandoned just because its own mtime is old.
        root = self.tmp / "scratch"
        root.mkdir()
        target = root / "build"
        target.mkdir()
        recent = target / "fresh-object"
        recent.write_text("o")
        age(target, 400)
        age(recent, 1)
        self.run_janitor("--artifact", f"{root}:30", apply=True)
        self.assertTrue(target.exists(),
                        "an actively written tree must survive an old top-level mtime")

    def test_only_immediate_children_are_considered(self) -> None:
        root = self.tmp / "scratch"
        nested = root / "fresh-parent" / "ancient-child"
        nested.mkdir(parents=True)
        age(nested, 365)
        age(root / "fresh-parent", 1)
        self.run_janitor("--artifact", f"{root}:30", apply=True)
        self.assertTrue(nested.exists(),
                        "a stale grandchild under a fresh parent is out of scope")

    def test_unsafe_artifact_roots_are_refused(self) -> None:
        home = os.path.expanduser("~")
        for rule in ("/:30", "/home:30", "/usr:30", "/nix:30", "/etc:30",
                     "relative/path:30", f"{home}:30", f"{self.tmp}:0",
                     f"{self.tmp}:notanumber"):
            done, _ = self.run_janitor("--artifact", rule, apply=True)
            self.assertEqual(done.returncode, 2, f"{rule!r} must be refused")
            self.assertIn("REJECTED", done.stderr)

    def test_a_scratch_root_like_tmp_is_allowed(self) -> None:
        # The first guard was a path-depth heuristic, which refused /tmp -- the
        # single largest thing worth sweeping -- while accepting /home/someone.
        scratch = self.tmp / "tmplike"
        scratch.mkdir()
        done, report = self.run_janitor("--artifact", f"{scratch}:30")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(report["tasks"]["artifacts"]["status"], "OK")

    # -- expiring paths -----------------------------------------------------

    def test_an_expiring_path_removes_itself_not_its_children(self) -> None:
        target = self.tmp / "build-cache"
        (target / "inner").mkdir(parents=True)
        age(target / "inner", 200)
        age(target, 200)
        _, report = self.run_janitor("--expiring", f"{target}:30", apply=True)
        self.assertFalse(target.exists())
        self.assertTrue(report["tasks"]["expiring_paths"]["paths"][str(target)]["removed"])

    def test_an_expiring_path_inside_the_window_survives(self) -> None:
        target = self.tmp / "build-cache"
        target.mkdir()
        _, report = self.run_janitor("--expiring", f"{target}:30", apply=True)
        self.assertTrue(target.exists())
        entry = report["tasks"]["expiring_paths"]["paths"][str(target)]
        self.assertEqual(entry["skipped"], "within the window")

    def test_an_expiring_path_is_a_preview_without_apply(self) -> None:
        target = self.tmp / "build-cache"
        target.mkdir()
        age(target, 400)
        _, report = self.run_janitor("--expiring", f"{target}:30")
        self.assertTrue(target.exists())
        self.assertTrue(report["tasks"]["expiring_paths"]["paths"][str(target)]["removed"])

    def test_an_absent_expiring_path_is_not_an_error(self) -> None:
        _, report = self.run_janitor("--expiring", f"{self.tmp}/gone:30", apply=True)
        self.assertEqual(report["tasks"]["expiring_paths"]["status"], "OK")

    def test_a_root_larger_than_the_cap_is_flagged_not_silently_partial(self) -> None:
        # A live /tmp exceeded the original 4096 cap, so the sweep stopped at an
        # alphabetical prefix and never reached the rest on any run.
        import importlib.util
        spec = importlib.util.spec_from_loader(
            "janitor", importlib.machinery.SourceFileLoader("janitor", str(JANITOR)))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertGreaterEqual(module.MAX_ENTRIES_PER_ROOT, 65536)

        root = self.tmp / "scratch"
        root.mkdir()
        for index in range(12):
            entry = root / f"entry-{index:04d}"
            entry.write_text("x")
            age(entry, 90)
        _, report = self.run_janitor("--artifact", f"{root}:30")
        entry = report["tasks"]["artifacts"]["roots"][str(root)]
        self.assertEqual(len(entry["removed"]), 12)
        self.assertFalse(entry["truncated"])

    def test_owned_entries_are_swept_and_a_foreign_count_is_reported(self) -> None:
        # /tmp is shared. The first armed run reported 40 PermissionErrors on
        # other users' files as faults, when leaving them alone is correct.
        # A test cannot create a file owned by another user without privilege,
        # so this covers the accounting and the owned path; the ownership
        # branch itself is exercised by the live run on a shared /tmp.
        root = self.tmp / "scratch"
        root.mkdir()
        mine = root / "mine"
        mine.mkdir()
        age(mine, 90)
        _, report = self.run_janitor("--artifact", f"{root}:30", apply=True)
        entry = report["tasks"]["artifacts"]["roots"][str(root)]
        self.assertEqual(report["tasks"]["artifacts"]["status"], "OK")
        self.assertEqual(entry["foreign"], 0)
        self.assertFalse(mine.exists())

    def test_a_keep_pattern_may_begin_with_a_dash(self) -> None:
        # The first armed run died here: argparse read the regular expression
        # -1000$ as an option name and the whole janitor exited before acting.
        root = self.tmp / "scratch"
        root.mkdir()
        keep = root / "codex-1000"
        keep.mkdir()
        drop = root / "other"
        drop.mkdir()
        age(keep, 90)
        age(drop, 90)
        done, report = self.run_janitor("--artifact", f"{root}:30",
                                        "--keep-pattern=-1000$", apply=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(keep.exists())
        self.assertFalse(drop.exists())

    def test_a_missing_artifact_root_is_not_an_error(self) -> None:
        _, report = self.run_janitor("--artifact", f"{self.tmp}/absent/root:30")
        self.assertEqual(report["tasks"]["artifacts"]["status"], "OK")

    # -- worktrees and drift ------------------------------------------------

    def test_worktree_prune_is_dry_run_without_apply(self) -> None:
        repo = self.tmp / "repo"
        (repo / ".git").mkdir(parents=True)
        self.run_janitor("--repo", str(repo))
        calls = (self.calls / "git").read_text()
        self.assertIn("worktree prune -v --dry-run", calls)

    def test_worktree_prune_drops_dry_run_with_apply(self) -> None:
        repo = self.tmp / "repo"
        (repo / ".git").mkdir(parents=True)
        self.run_janitor("--repo", str(repo), apply=True)
        calls = (self.calls / "git").read_text()
        self.assertIn("worktree prune -v\n", calls)
        self.assertNotIn("--dry-run", calls)

    def test_drift_is_reported_and_never_pulled_or_applied(self) -> None:
        repo = self.tmp / "repo"
        (repo / ".git").mkdir(parents=True)
        self.run_janitor("--repo", str(repo), apply=True)
        calls = (self.calls / "git").read_text()
        self.assertIn("status --porcelain=v1 --branch", calls)
        for forbidden in ("pull", "fetch", "reset", "checkout", "clean"):
            self.assertNotIn(f"git {forbidden}", calls)

    # -- locking and reports ------------------------------------------------

    def test_a_second_invocation_refuses_rather_than_racing(self) -> None:
        import fcntl
        self.state.mkdir(parents=True)
        handle = os.open(self.state / "janitor.lock", os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, handle)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        done, _ = self.run_janitor(apply=True)
        self.assertEqual(done.returncode, 3)
        self.assertIn("LOCKED", done.stderr)

    def test_a_report_is_written_private_under_the_report_root(self) -> None:
        reports = self.tmp / "reports"
        self.run_janitor("--report-root", str(reports))
        written = list(reports.glob("janitor-*.json"))
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(written[0].read_text())["version"], 1)

    def test_the_script_names_nothing_host_or_company_specific(self) -> None:
        # This file lives in the public repository.
        body = JANITOR.read_text().lower()
        for token in ("semgrep", "claudio", "box-1", "box-2", "box-3", "box-4",
                      "mandoline", "xoxb", "slack"):
            self.assertNotIn(token, body)


if __name__ == "__main__":
    unittest.main()


class ReclaimCase(unittest.TestCase):
    """Real git repositories, real worktrees, a fake `gh`."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.calls = self.tmp / "calls"
        self.calls.mkdir()
        self.state = self.tmp / "state"
        self.repo = self.tmp / "repo"
        self.git("init", "-q", "-b", "main", str(self.repo), cwd=self.tmp)
        (self.repo / ".gitignore").write_text("target/\n")
        (self.repo / "file").write_text("one")
        self.git("add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
        self.sessions = []

    def git(self, *args, cwd=None):
        done = subprocess.run(["git", *args], cwd=str(cwd or self.repo),
                              capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def add_worktree(self, name, *, branch=None, ignored_bytes=0, extra_commit=False,
                     dirty=False):
        branch = branch or f"user/{name}"
        path = self.tmp / name
        self.git("worktree", "add", "-q", str(path), "-b", branch)
        if ignored_bytes:
            (path / "target").mkdir()
            (path / "target" / "big").write_text("x" * ignored_bytes)
        if extra_commit:
            (path / "file").write_text("later")
            self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam",
                     "after the merge", cwd=path)
        head = self.git("rev-parse", "HEAD", cwd=path).strip()
        if dirty:
            (path / "file").write_text("uncommitted")
        return path, branch, head

    def write_gh(self, prs):
        payload = json.dumps(prs)
        write_executable(self.bin / "gh", f"""#!/usr/bin/env python3
import sys
sys.stdout.write({payload!r})
""")

    def write_agent_deck(self):
        payload = json.dumps(self.sessions)
        write_executable(self.bin / "agent-deck", f"""#!/usr/bin/env python3
import sys
argv = sys.argv[1:]
if argv[2:] == ["list", "--json"]:
    sys.stdout.write({payload!r}); sys.exit(0)
if argv[2:4] == ["session", "cleanup"]:
    sys.exit(0)
sys.exit(0)
""")

    def run_janitor(self, *extra, apply=False):
        self.write_agent_deck()
        argv = [sys.executable, str(JANITOR),
                "--agent-deck", str(self.bin / "agent-deck"),
                "--gh", str(self.bin / "gh"),
                "--git", "git",
                "--state-dir", str(self.state),
                "--profile", "default",
                "--reclaim-repo", str(self.repo),
                *extra]
        if apply:
            argv.append("--apply")
        done = subprocess.run(argv, capture_output=True, text=True, timeout=180,
                              check=False)
        self.assertTrue(done.stdout.strip(), done.stderr)
        return done, json.loads(done.stdout)["tasks"]["merged_worktrees"]

    def outcome(self, task):
        entry = task["repositories"][str(self.repo)]
        reclaimed = {item["branch"] for item in entry["reclaimed"]}
        retained = {item["branch"]: item["reason"] for item in entry["retained"]}
        return reclaimed, retained, entry

    # -- the rule -----------------------------------------------------------

    def test_a_merged_untouched_worktree_is_reclaimed_with_its_ignored_build_dir(self):
        path, branch, head = self.add_worktree("merged", ignored_bytes=5000)
        self.write_gh([{"headRefName": branch, "headRefOid": head, "state": "MERGED",
                        "number": 1, "mergedAt": "2026-01-01T00:00:00Z"}])
        _, task = self.run_janitor(apply=True)
        reclaimed, _, entry = self.outcome(task)
        self.assertEqual(reclaimed, {branch})
        self.assertFalse(path.exists(),
                         "an ignored build directory must not block removal")
        self.assertGreater(entry["bytes"], 5000)

    def test_commits_after_the_merged_head_are_retained(self):
        path, branch, _ = self.add_worktree("diverged", extra_commit=True)
        stale = self.git("rev-parse", "HEAD~1", cwd=path).strip()
        self.write_gh([{"headRefName": branch, "headRefOid": stale, "state": "MERGED",
                        "number": 2, "mergedAt": "2026-01-01T00:00:00Z"}])
        _, task = self.run_janitor(apply=True)
        reclaimed, retained, _ = self.outcome(task)
        self.assertEqual(reclaimed, set())
        self.assertEqual(retained[branch], "commits after the merged head")
        self.assertTrue(path.exists())

    def test_uncommitted_changes_are_retained(self):
        path, branch, head = self.add_worktree("dirty", dirty=True)
        self.write_gh([{"headRefName": branch, "headRefOid": head, "state": "MERGED",
                        "number": 3, "mergedAt": "2026-01-01T00:00:00Z"}])
        _, task = self.run_janitor(apply=True)
        reclaimed, retained, _ = self.outcome(task)
        self.assertEqual(reclaimed, set())
        self.assertEqual(retained[branch], "uncommitted changes")
        self.assertTrue(path.exists())

    def test_an_open_pull_request_is_retained(self):
        path, branch, head = self.add_worktree("open")
        self.write_gh([{"headRefName": branch, "headRefOid": head, "state": "OPEN",
                        "number": 4, "mergedAt": None}])
        _, task = self.run_janitor(apply=True)
        _, retained, _ = self.outcome(task)
        self.assertEqual(retained[branch], "open")
        self.assertTrue(path.exists())

    def test_a_branch_with_no_pull_request_is_retained(self):
        path, branch, _ = self.add_worktree("nopr")
        self.write_gh([])
        _, task = self.run_janitor(apply=True)
        _, retained, _ = self.outcome(task)
        self.assertEqual(retained[branch], "no pull request")
        self.assertTrue(path.exists())

    def test_a_worktree_held_by_a_session_is_retained(self):
        path, branch, head = self.add_worktree("busy")
        self.sessions = [{"id": "a-1", "path": str(path), "tool": "codex",
                          "status": "running"}]
        self.write_gh([{"headRefName": branch, "headRefOid": head, "state": "MERGED",
                        "number": 5, "mergedAt": "2026-01-01T00:00:00Z"}])
        _, task = self.run_janitor(apply=True)
        _, retained, _ = self.outcome(task)
        self.assertEqual(retained[branch], "a session is using it")
        self.assertTrue(path.exists())

    def test_the_primary_worktree_is_never_reclaimed(self):
        self.write_gh([])
        _, task = self.run_janitor(apply=True)
        _, retained, _ = self.outcome(task)
        self.assertEqual(retained.get("main"), "primary worktree")
        self.assertTrue((self.repo / "file").exists())

    def test_a_recent_merge_is_held_by_the_grace_window(self):
        path, branch, head = self.add_worktree("fresh")
        merged = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.write_gh([{"headRefName": branch, "headRefOid": head, "state": "MERGED",
                        "number": 6, "mergedAt": merged}])
        _, task = self.run_janitor("--reclaim-grace-days", "3", apply=True)
        _, retained, _ = self.outcome(task)
        self.assertEqual(retained[branch], "inside the grace window")
        self.assertTrue(path.exists())

    def test_reclaim_is_a_preview_without_apply(self):
        path, branch, head = self.add_worktree("merged", ignored_bytes=2000)
        self.write_gh([{"headRefName": branch, "headRefOid": head, "state": "MERGED",
                        "number": 7, "mergedAt": "2026-01-01T00:00:00Z"}])
        _, task = self.run_janitor()
        reclaimed, _, entry = self.outcome(task)
        self.assertEqual(reclaimed, {branch})
        self.assertTrue(path.exists(), "a preview must delete nothing")
        self.assertGreater(entry["bytes"], 2000)

    def test_a_transient_api_failure_is_retried_then_degrades_safely(self):
        # The first live run met HTTP 502/504 on most repositories at once.
        path, branch, head = self.add_worktree("merged")
        counter = self.tmp / "gh-attempts"
        write_executable(self.bin / "gh", f"""#!/usr/bin/env python3
import pathlib, sys
c = pathlib.Path({str(counter)!r})
n = int(c.read_text()) + 1 if c.exists() else 1
c.write_text(str(n))
if n < 3:
    sys.stderr.write("HTTP 502: Bad Gateway" + chr(10)); sys.exit(1)
import json
sys.stdout.write(json.dumps([{{"headRefName": {branch!r}, "headRefOid": {head!r},
                              "state": "MERGED", "number": 9,
                              "mergedAt": "2026-01-01T00:00:00Z"}}]))
""")
        _, task = self.run_janitor("--gh-attempts", "3", apply=True)
        self.assertEqual(int(counter.read_text()), 3, "the query must be retried")
        reclaimed, _, _ = self.outcome(task)
        self.assertEqual(reclaimed, {branch})
        self.assertFalse(path.exists())

    def test_an_api_failure_that_persists_retains_everything(self):
        path, branch, _ = self.add_worktree("merged")
        write_executable(self.bin / "gh",
                         "#!/bin/sh\necho 'HTTP 504' >&2\nexit 1\n")
        _, task = self.run_janitor("--gh-attempts", "2", apply=True)
        self.assertEqual(task["status"], "DEGRADED")
        self.assertTrue(path.exists(),
                        "an unreadable pull request state must never reclaim")

    def test_unreadable_session_occupancy_stops_reclaim_entirely(self):
        path, branch, head = self.add_worktree("merged")
        self.write_gh([{"headRefName": branch, "headRefOid": head, "state": "MERGED",
                        "number": 8, "mergedAt": "2026-01-01T00:00:00Z"}])
        write_executable(self.bin / "agent-deck", "#!/bin/sh\nexit 7\n")
        argv = [sys.executable, str(JANITOR),
                "--agent-deck", str(self.bin / "agent-deck"),
                "--gh", str(self.bin / "gh"), "--git", "git",
                "--state-dir", str(self.state), "--profile", "default",
                "--reclaim-repo", str(self.repo), "--apply"]
        done = subprocess.run(argv, capture_output=True, text=True, timeout=180,
                              check=False)
        task = json.loads(done.stdout)["tasks"]["merged_worktrees"]
        self.assertEqual(task["status"], "DEGRADED")
        self.assertTrue(path.exists(),
                        "unknown occupancy must never be treated as empty")


class TmuxSweepCase(unittest.TestCase):
    """The tmux reaper, against real socket files and a scripted tmux."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.state = self.tmp / "state"
        self.root = self.tmp / "tmux-1000"
        self.root.mkdir()
        self.servers = self.tmp / "servers.json"
        self.servers.write_text("{}")
        self.rows: list[dict] = []
        self.write_agent_deck()
        self.write_tmux()

    # -- fakes --------------------------------------------------------------

    def write_agent_deck(self, exit_code: int = 0) -> None:
        payload = json.dumps(self.rows)
        write_executable(self.bin / "agent-deck", f"""#!/usr/bin/env python3
import sys
argv = sys.argv[1:]
if argv[2:] == ["list", "--json"]:
    if {exit_code}:
        sys.exit({exit_code})
    sys.stdout.write({payload!r}); sys.exit(0)
if argv[2:4] == ["session", "cleanup"]:
    sys.stdout.write('{{"candidates": []}}'); sys.exit(0)
sys.exit(0)
""")

    def write_tmux(self, kill_exit: int = 0) -> None:
        """A tmux whose servers live in a JSON file keyed by socket path."""
        write_executable(self.bin / "tmux", f"""#!/usr/bin/env python3
import json, pathlib, sys
state = pathlib.Path({str(self.servers)!r})
argv = sys.argv[1:]
servers = json.loads(state.read_text())
socket = argv[1] if argv[0] == "-S" else ""
rest = argv[2:]
sessions = servers.get(socket)
if sessions is None:
    sys.stderr.write("no server running on " + socket + chr(10)); sys.exit(1)
if rest[0] == "list-sessions":
    for name, attached, activity in sessions:
        sys.stdout.write("%s\\t%s\\t%s" % (name, attached, activity) + chr(10))
    sys.exit(0)
if rest[0] == "kill-session":
    if {kill_exit}:
        sys.stderr.write("kill failed" + chr(10)); sys.exit({kill_exit})
    target = rest[2]
    kept = [s for s in sessions if s[0] != target]
    if kept:
        servers[socket] = kept
    else:
        # A tmux server exits with its last session.
        servers.pop(socket)
    state.write_text(json.dumps(servers))
    sys.exit(0)
sys.exit(2)
""")

    # -- fixtures -----------------------------------------------------------

    def add_socket(self, name: str, sessions=None) -> Path:
        path = self.root / name
        handle = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(handle.close)
        handle.bind(str(path))
        if sessions is not None:
            servers = json.loads(self.servers.read_text())
            servers[str(path)] = sessions
            self.servers.write_text(json.dumps(servers))
        return path

    @staticmethod
    def idle(days: float) -> int:
        return int(time.time() - days * 86400)

    def run_janitor(self, *extra, apply=False):
        argv = [sys.executable, str(JANITOR),
                "--agent-deck", str(self.bin / "agent-deck"),
                "--git", "git",
                "--state-dir", str(self.state),
                "--profile", "default",
                "--tmux", str(self.bin / "tmux"),
                "--tmux-socket-root", str(self.root),
                *extra]
        if apply:
            argv.append("--apply")
        done = subprocess.run(argv, capture_output=True, text=True, timeout=120,
                              check=False)
        report = json.loads(done.stdout) if done.stdout.strip() else None
        task = report["tasks"]["tmux"] if report else None
        return done, task

    def entry(self, task):
        return task["roots"][str(self.root)]

    # -- tests --------------------------------------------------------------

    def test_without_a_root_the_task_is_skipped(self) -> None:
        argv = [sys.executable, str(JANITOR),
                "--agent-deck", str(self.bin / "agent-deck"),
                "--state-dir", str(self.state), "--profile", "default"]
        done = subprocess.run(argv, capture_output=True, text=True, timeout=120,
                              check=False)
        self.assertEqual(json.loads(done.stdout)["tasks"]["tmux"]["status"], "SKIPPED")

    def test_a_dead_server_socket_is_deleted(self) -> None:
        path = self.add_socket("native-1789306680015920948")
        _, task = self.run_janitor(apply=True)
        self.assertEqual(task["status"], "OK")
        self.assertEqual(self.entry(task)["sockets_removed"],
                         ["native-1789306680015920948"])
        self.assertFalse(path.exists())

    def test_a_preview_deletes_nothing(self) -> None:
        path = self.add_socket("native-1789306680015920948")
        live = self.add_socket("parity-1789487772393964951",
                               [["agentdeck_test-svcok-04c15a74_6511100d", 0,
                                 self.idle(30)]])
        _, task = self.run_janitor()
        entry = self.entry(task)
        # A preview kills nothing, so the second server is still answering and
        # its socket is not yet a candidate. Only the already-dead one is.
        self.assertEqual(entry["sockets_removed"], ["native-1789306680015920948"])
        self.assertEqual([k["session"] for k in entry["killed"]],
                         ["agentdeck_test-svcok-04c15a74_6511100d"])
        self.assertTrue(path.exists())
        self.assertTrue(live.exists())

    def test_an_abandoned_session_is_killed_and_its_socket_removed(self) -> None:
        path = self.add_socket("agent-deck-tests",
                               [["agentdeck_test-svcok-04c15a74_6511100d", 0,
                                 self.idle(30)]])
        _, task = self.run_janitor(apply=True)
        entry = self.entry(task)
        self.assertEqual([k["session"] for k in entry["killed"]],
                         ["agentdeck_test-svcok-04c15a74_6511100d"])
        self.assertEqual(entry["sockets_removed"], ["agent-deck-tests"])
        self.assertFalse(path.exists())

    def test_a_session_an_agent_deck_row_claims_is_never_killed(self) -> None:
        self.rows = [{"id": "row-1", "tmux_session": "agentdeck_conductor-semgrep_cae48990"}]
        self.write_agent_deck()
        path = self.add_socket("agent-deck",
                               [["agentdeck_conductor-semgrep_cae48990", 0,
                                 self.idle(400)]])
        _, task = self.run_janitor(apply=True)
        entry = self.entry(task)
        self.assertEqual(entry["killed"], [])
        self.assertEqual(entry["retained"], 1)
        self.assertEqual(entry["sockets_removed"], [])
        self.assertTrue(path.exists(), "a claimed pane must survive any idle time")

    def test_an_attached_session_is_never_killed(self) -> None:
        self.add_socket("watched", [["agentdeck_old_1", 1, self.idle(400)]])
        _, task = self.run_janitor(apply=True)
        self.assertEqual(self.entry(task)["killed"], [])
        self.assertEqual(self.entry(task)["retained"], 1)

    def test_a_recently_active_session_is_never_killed(self) -> None:
        self.add_socket("recent", [["agentdeck_old_1", 0, self.idle(2)]])
        _, task = self.run_janitor("--tmux-idle-days", "7", apply=True)
        self.assertEqual(self.entry(task)["killed"], [])
        self.assertEqual(self.entry(task)["retained"], 1)

    def test_a_protected_socket_file_is_never_removed(self) -> None:
        path = self.add_socket("agent-deck")
        _, task = self.run_janitor("--protect-tmux-socket", "agent-deck", apply=True)
        entry = self.entry(task)
        self.assertEqual(entry["protected"], 1)
        self.assertEqual(entry["sockets_removed"], [])
        self.assertTrue(path.exists(),
                        "the conductor's socket must survive a dead-server probe")

    def test_litter_on_a_protected_socket_is_still_reaped(self) -> None:
        # The conductor's socket is also where a test harness left 45 abandoned
        # sessions. Protecting the file must not protect what runs on it.
        self.rows = [{"id": "row-1", "tmux_session": "agentdeck_conductor-semgrep_cae48990"}]
        self.write_agent_deck()
        path = self.add_socket("agent-deck",
                               [["agentdeck_conductor-semgrep_cae48990", 0, self.idle(400)],
                                ["agentdeck_test-svcok-04c15a74_6511100d", 0, self.idle(30)]])
        _, task = self.run_janitor("--protect-tmux-socket", "agent-deck", apply=True)
        entry = self.entry(task)
        self.assertEqual([k["session"] for k in entry["killed"]],
                         ["agentdeck_test-svcok-04c15a74_6511100d"])
        self.assertEqual(entry["retained"], 1, "the claimed conductor pane stays")
        self.assertEqual(entry["sockets_removed"], [])
        self.assertTrue(path.exists())

    def test_only_one_session_of_a_server_is_killed_and_the_socket_stays(self) -> None:
        path = self.add_socket("mixed", [["agentdeck_old_1", 0, self.idle(30)],
                                         ["agentdeck_live_2", 1, self.idle(30)]])
        _, task = self.run_janitor(apply=True)
        entry = self.entry(task)
        self.assertEqual([k["session"] for k in entry["killed"]], ["agentdeck_old_1"])
        self.assertEqual(entry["sockets_removed"], [],
                         "a server with sessions left must keep its socket")
        self.assertTrue(path.exists())

    def test_a_plain_file_in_the_root_is_ignored(self) -> None:
        plain = self.root / "notes.txt"
        plain.write_text("x")
        _, task = self.run_janitor(apply=True)
        self.assertEqual(self.entry(task)["sockets_removed"], [])
        self.assertTrue(plain.exists())

    def test_unreadable_rows_reap_nothing(self) -> None:
        self.write_agent_deck(exit_code=7)
        path = self.add_socket("native-1", [["agentdeck_old_1", 0, self.idle(99)]])
        _, task = self.run_janitor(apply=True)
        self.assertEqual(task["status"], "DEGRADED")
        self.assertNotIn("roots", task)
        self.assertTrue(path.exists(),
                        "an unknown claim set must never kill a pane")

    def test_a_failing_kill_degrades_and_keeps_the_socket(self) -> None:
        self.write_tmux(kill_exit=1)
        path = self.add_socket("stubborn", [["agentdeck_old_1", 0, self.idle(30)]])
        _, task = self.run_janitor(apply=True)
        self.assertEqual(task["status"], "DEGRADED")
        entry = self.entry(task)
        self.assertEqual(entry["killed"], [])
        self.assertEqual(len(entry["failed"]), 1)
        self.assertEqual(entry["sockets_removed"], [])
        self.assertTrue(path.exists())

    def test_a_system_root_is_rejected_before_anything_runs(self) -> None:
        argv = [sys.executable, str(JANITOR),
                "--agent-deck", str(self.bin / "agent-deck"),
                "--state-dir", str(self.state),
                "--tmux-socket-root", "/run"]
        done = subprocess.run(argv, capture_output=True, text=True, timeout=120,
                              check=False)
        self.assertEqual(done.returncode, 2)
        self.assertEqual(json.loads(done.stderr)["status"], "REJECTED")


class IdleStopCase(JanitorCase):
    """Rows parked at a prompt never die, so nothing ever reclaimed them."""

    def write_rows(self, rows) -> None:
        payload = json.dumps(rows)
        write_executable(self.bin / "agent-deck", f"""#!/usr/bin/env python3
import json, os, pathlib, sys
argv = sys.argv[1:]
(pathlib.Path(os.environ["CALLS"]) / "agent-deck").open("a").write(" ".join(argv) + chr(10))
if argv[2:] == ["list", "--json"]:
    sys.stdout.write({payload!r}); sys.exit(0)
if argv[2:4] == ["session", "stop"]:
    sys.exit(0)
if argv[2:4] == ["session", "cleanup"]:
    sys.stdout.write('{{"candidates": []}}'); sys.exit(0)
sys.exit(0)
""")

    @staticmethod
    def stamp(days_ago):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ",
                             time.gmtime(time.time() - days_ago * 86400))

    def stopped_ids(self, report):
        return [r["id"] for r in report["tasks"]["idle_sessions"]["profiles"]["default"]["stopped"]]

    def test_only_long_parked_unwatched_rows_are_stopped(self) -> None:
        self.write_rows([
            {"id": "parked-old", "title": "orchestrator", "status": "waiting",
             "last_activity_at": self.stamp(34), "viewers": []},
            {"id": "idle-old", "title": "reviewer", "status": "idle",
             "last_activity_at": self.stamp(20), "viewers": []},
            {"id": "parked-young", "title": "impl", "status": "waiting",
             "last_activity_at": self.stamp(3), "viewers": []},
            {"id": "running", "title": "worker", "status": "running",
             "last_activity_at": self.stamp(40), "viewers": []},
            {"id": "watched", "title": "paired", "status": "waiting",
             "last_activity_at": self.stamp(40), "viewers": ["tty1"]},
            {"id": "already-stopped", "title": "done", "status": "stopped",
             "last_activity_at": self.stamp(40), "viewers": []},
        ])
        _, report = self.run_janitor("--stop-idle-days", "14", apply=True)
        self.assertEqual(["parked-old", "idle-old"], self.stopped_ids(report))
        stops = [c for c in self.agent_deck_calls() if "session stop" in c]
        self.assertEqual(["-p default session stop parked-old",
                          "-p default session stop idle-old"], stops)
        kept = report["tasks"]["idle_sessions"]["profiles"]["default"]["kept"]
        self.assertEqual(1, kept["running"])
        self.assertEqual(1, kept["watched"], "a pane someone is watching is never stopped")
        self.assertEqual(1, kept["young"])

    def test_a_protected_title_is_never_stopped(self) -> None:
        self.write_rows([{"id": "conductor", "title": "conductor-semgrep", "status": "waiting",
                          "last_activity_at": self.stamp(99), "viewers": []}])
        _, report = self.run_janitor("--stop-idle-days", "14",
                                     "--protect-session-title", "conductor-semgrep", apply=True)
        self.assertEqual([], self.stopped_ids(report))
        self.assertEqual([], [c for c in self.agent_deck_calls() if "session stop" in c])

    def test_an_unreadable_age_is_not_an_old_one(self) -> None:
        self.write_rows([
            {"id": "no-stamp", "title": "mystery", "status": "waiting", "viewers": []},
            {"id": "bad-stamp", "title": "mystery", "status": "waiting",
             "last_activity_at": "not-a-date", "viewers": []},
        ])
        _, report = self.run_janitor("--stop-idle-days", "14", apply=True)
        self.assertEqual([], self.stopped_ids(report))

    def test_a_preview_stops_nothing(self) -> None:
        self.write_rows([{"id": "parked-old", "title": "orchestrator", "status": "waiting",
                          "last_activity_at": self.stamp(34), "viewers": []}])
        _, report = self.run_janitor("--stop-idle-days", "14")
        self.assertEqual(["parked-old"], self.stopped_ids(report))
        self.assertEqual([], [c for c in self.agent_deck_calls() if "session stop" in c])

    def test_stopping_runs_before_the_sweep_so_nothing_is_stopped_and_purged_at_once(self) -> None:
        # A row stopped today is reclaimed by a later run, which leaves a few
        # days to notice that stopping it was wrong.
        self.write_rows([{"id": "parked-old", "title": "orchestrator", "status": "waiting",
                          "last_activity_at": self.stamp(34), "viewers": []}])
        self.run_janitor("--stop-idle-days", "14", "--session-retention-days", "7", apply=True)
        calls = self.agent_deck_calls()
        stop_at = next(i for i, c in enumerate(calls) if "session stop" in c)
        cleanup_at = next(i for i, c in enumerate(calls) if "session cleanup" in c)
        self.assertLess(stop_at, cleanup_at)
        self.assertEqual([], [c for c in calls if "session remove" in c])

    def test_a_failed_stop_degrades_without_stopping_the_rest(self) -> None:
        self.write_rows([{"id": "a", "title": "x", "status": "waiting",
                          "last_activity_at": self.stamp(30), "viewers": []}])
        write_executable(self.bin / "agent-deck", """#!/usr/bin/env python3
import json, os, pathlib, sys
argv = sys.argv[1:]
(pathlib.Path(os.environ["CALLS"]) / "agent-deck").open("a").write(" ".join(argv) + chr(10))
if argv[2:] == ["list", "--json"]:
    json.dump([{"id": "a", "title": "x", "status": "waiting",
                "last_activity_at": "2020-01-01T00:00:00Z", "viewers": []}], sys.stdout)
    sys.exit(0)
if argv[2:4] == ["session", "stop"]:
    sys.stderr.write("tmux refused"); sys.exit(1)
if argv[2:4] == ["session", "cleanup"]:
    sys.stdout.write('{"candidates": []}'); sys.exit(0)
sys.exit(0)
""")
        _, report = self.run_janitor("--stop-idle-days", "14", apply=True)
        task = report["tasks"]["idle_sessions"]
        self.assertEqual("DEGRADED", task["status"])
        self.assertEqual(1, len(task["profiles"]["default"]["failed"]))
        self.assertEqual("OK", report["tasks"]["sessions"]["status"],
                         "one failing task never suppresses another")


class RetentionWindowCase(JanitorCase):
    """Different kinds of row age out at different rates."""

    def write_cleanup(self, rows) -> None:
        payload = json.dumps({"candidates": rows, "groups": self.groups})
        write_executable(self.bin / "agent-deck", f"""#!/usr/bin/env python3
import json, os, pathlib, sys
argv = sys.argv[1:]
(pathlib.Path(os.environ["CALLS"]) / "agent-deck").open("a").write(" ".join(argv) + chr(10))
if argv[2:4] == ["session", "cleanup"]:
    sys.stdout.write({payload!r}); sys.exit(0)
if argv[2:4] == ["session", "remove"]:
    sys.exit(0)
sys.stdout.write({payload!r}); sys.exit(0)
""")

    def removed_ids(self, report):
        return [r["id"] for r in report["tasks"]["sessions"]["profiles"]["default"]["removed"]]

    def test_a_stopped_row_ages_out_faster_than_a_quiet_one(self) -> None:
        # A conductor fleet makes stopped rows by the dozen for one piece of
        # work and never returns to them; a merely quiet row may still be live
        # work an operator left running.
        self.write_cleanup([
            {"id": "stopped-old", "title": "impl", "status": "stopped", "idle_days": 4, "archived": False},
            {"id": "stopped-young", "title": "impl", "status": "stopped", "idle_days": 1, "archived": False},
            {"id": "quiet-mid", "title": "orch", "status": "waiting", "idle_days": 4, "archived": False},
            {"id": "quiet-old", "title": "orch", "status": "waiting", "idle_days": 9, "archived": False},
        ])
        _, report = self.run_janitor("--session-retention-days", "7",
                                     "--stopped-retention-days", "3", apply=True)
        self.assertEqual(["stopped-old", "quiet-old"], self.removed_ids(report))
        self.assertEqual(2, report["tasks"]["sessions"]["profiles"]["default"]["young"])

    def test_archived_rows_are_purged_only_when_a_window_exists(self) -> None:
        # Nothing has ever reclaimed an archived row: the CLI does not offer
        # one unless asked, so they are invisible in the TUI and permanent in
        # the registry.
        rows = [{"id": "archived-old", "title": "old", "status": "stopped",
                 "idle_days": 40, "archived": True}]
        self.write_cleanup(rows)
        _, without = self.run_janitor("--session-retention-days", "7", apply=True)
        self.assertEqual([], self.removed_ids(without))
        self.assertNotIn("--include-archived", " ".join(self.agent_deck_calls()))

        self.write_cleanup(rows)
        _, with_window = self.run_janitor("--session-retention-days", "7",
                                          "--archived-retention-days", "30", apply=True)
        self.assertEqual(["archived-old"], self.removed_ids(with_window))
        self.assertIn("--include-archived", " ".join(self.agent_deck_calls()))

    def test_an_archived_row_inside_its_window_is_kept(self) -> None:
        self.write_cleanup([{"id": "archived-young", "title": "recent", "status": "stopped",
                             "idle_days": 10, "archived": True}])
        _, report = self.run_janitor("--session-retention-days", "7",
                                     "--stopped-retention-days", "3",
                                     "--archived-retention-days", "30", apply=True)
        self.assertEqual([], self.removed_ids(report))

    def test_the_widest_window_is_asked_for_once(self) -> None:
        # Asking per window would race: a row can change status between two
        # listings, and then belong to neither answer.
        self.write_cleanup([])
        self.run_janitor("--session-retention-days", "7", "--stopped-retention-days", "3",
                         "--archived-retention-days", "30", apply=True)
        cleanups = [c for c in self.agent_deck_calls() if "session cleanup" in c]
        self.assertEqual(1, len(cleanups), cleanups)
        self.assertIn("--days 3", cleanups[0])

    def test_a_stopped_window_longer_than_the_general_one_is_rejected(self) -> None:
        done, _ = self.run_janitor("--session-retention-days", "7",
                                   "--stopped-retention-days", "30")
        self.assertEqual(2, done.returncode)
        self.assertEqual("REJECTED", json.loads(done.stderr)["status"])

    def test_a_protected_title_survives_every_window(self) -> None:
        self.write_cleanup([{"id": "conductor", "title": "conductor-semgrep",
                             "status": "stopped", "idle_days": 99, "archived": True}])
        _, report = self.run_janitor("--session-retention-days", "7",
                                     "--stopped-retention-days", "3",
                                     "--archived-retention-days", "30",
                                     "--protect-session-title", "conductor-semgrep", apply=True)
        self.assertEqual([], self.removed_ids(report))
        profile = report["tasks"]["sessions"]["profiles"]["default"]
        self.assertEqual(["conductor-semgrep"], [r["title"] for r in profile["exempt"]])


class RemovalEdgeCase(JanitorCase):
    """Two failures seen on the first armed run of a live box."""

    def test_a_read_only_directory_is_still_removed(self) -> None:
        root = self.tmp / "scratch"
        root.mkdir()
        tree = root / "fixture"
        (tree / "inner").mkdir(parents=True)
        (tree / "inner" / "file").write_text("x")
        os.chmod(tree / "inner", 0o500)
        os.chmod(tree, 0o500)
        age(tree / "inner", 40)
        age(tree, 40)
        _, report = self.run_janitor("--artifact", f"{root}:30", apply=True)
        entry = report["tasks"]["artifacts"]["roots"][str(root)]
        self.assertEqual(entry["failed"], [])
        self.assertEqual(entry["removed"], [str(tree)])
        self.assertFalse(tree.exists())

    def test_a_row_that_woke_up_is_not_a_failure(self) -> None:
        write_executable(self.bin / "agent-deck", """#!/usr/bin/env python3
import json, sys
argv = sys.argv[1:]
if argv[2:4] == ["session", "cleanup"]:
    json.dump({"candidates": [{"id": "woke-0001", "title": "busy",
                               "idle_days": 40, "status": "stopped",
                               "archived": False}]}, sys.stdout)
    sys.exit(0)
if argv[2:4] == ["session", "remove"]:
    sys.stderr.write("Error: session 'busy' is in state 'waiting'; "
                     "only stopped/error sessions may be removed without --force")
    sys.exit(1)
sys.exit(0)
""")
        _, report = self.run_janitor(apply=True)
        task = report["tasks"]["sessions"]
        profile = task["profiles"]["default"]
        self.assertEqual(task["status"], "OK",
                         "a row coming back to life is the rail working")
        self.assertEqual(profile["failed"], [])
        self.assertEqual([r["id"] for r in profile["revived"]], ["woke-0001"])
        self.assertEqual(profile["removed"], [])


class StaleAgentCase(unittest.TestCase):
    """Recycling rows whose agent binary was replaced under them.

    The fixture builds a /proc of its own: a directory per pid holding `comm`,
    `stat` and an `exe` symlink. A deleted binary is modelled the way Linux
    reports it, with the " (deleted)" suffix on the link target.
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.state = self.tmp / "state"
        self.proc = self.tmp / "proc"
        self.proc.mkdir()
        self.calls = self.tmp / "calls"
        self.calls.mkdir()
        self.panes: list[tuple[str, int]] = []
        self.rows: list[dict] = []
        self.write_tmux()

    # -- fakes --------------------------------------------------------------

    def write_agent_deck(self, restart_exit: int = 0) -> None:
        payload = json.dumps(self.rows)
        write_executable(self.bin / "agent-deck", f"""#!/usr/bin/env python3
import os, pathlib, sys
argv = sys.argv[1:]
calls = pathlib.Path(os.environ["CALLS"]) / "agent-deck"
with calls.open("a") as fh:
    fh.write(" ".join(argv) + chr(10))
if argv[2:] == ["list", "--json"]:
    sys.stdout.write({payload!r}); sys.exit(0)
if argv[2:4] == ["session", "restart"]:
    if {restart_exit}:
        sys.stderr.write("restart failed" + chr(10)); sys.exit({restart_exit})
    sys.exit(0)
if argv[2:4] == ["session", "cleanup"]:
    sys.stdout.write('{{"candidates": []}}'); sys.exit(0)
sys.exit(0)
""")

    def write_tmux(self) -> None:
        panes = json.dumps(self.panes)
        write_executable(self.bin / "tmux", f"""#!/usr/bin/env python3
import json, sys
argv = sys.argv[1:]
if argv[0] == "-L" and argv[2:3] == ["list-panes"]:
    for name, pid in json.loads({panes!r}):
        sys.stdout.write("%s\\t%s" % (name, pid) + chr(10))
    sys.exit(0)
sys.exit(0)
""")

    # -- fixtures -----------------------------------------------------------

    def add_process(self, pid: int, comm: str, ppid: int = 1,
                    deleted: bool = False) -> None:
        entry = self.proc / str(pid)
        entry.mkdir()
        (entry / "comm").write_text(comm + "\n")
        # Field two is the name in parentheses; a real one can contain spaces.
        (entry / "stat").write_text(f"{pid} ({comm}) S {ppid} 0 0\n")
        target = self.tmp / f"{comm}-binary"
        if not target.exists():
            target.write_text("#!/bin/sh\n")
        link = str(target) + (" (deleted)" if deleted else "")
        os.symlink(link, entry / "exe")

    def add_pane(self, session: str, pid: int) -> None:
        self.panes.append((session, pid))
        self.write_tmux()

    def add_row(self, **row) -> None:
        self.rows.append(row)
        self.write_agent_deck()

    def run_janitor(self, *extra, apply=False):
        argv = [sys.executable, str(JANITOR),
                "--agent-deck", str(self.bin / "agent-deck"),
                "--git", "git",
                "--state-dir", str(self.state),
                "--profile", "default",
                "--tmux", str(self.bin / "tmux"),
                "--proc-root", str(self.proc),
                "--protect-tmux-socket", "agent-deck",
                *extra]
        if apply:
            argv.append("--apply")
        env = dict(os.environ, CALLS=str(self.calls))
        done = subprocess.run(argv, capture_output=True, text=True, timeout=120,
                              check=False, env=env)
        report = json.loads(done.stdout) if done.stdout.strip() else None
        return done, report

    def agent_deck_calls(self):
        path = self.calls / "agent-deck"
        return path.read_text().splitlines() if path.exists() else []

    def stale_task(self, *extra, apply=False):
        done, report = self.run_janitor("--recycle-stale-agents", *extra, apply=apply)
        self.assertEqual(done.returncode, 0 if report["status"] == "OK" else 1,
                         done.stderr)
        return report["tasks"]["stale_agents"]

    # -- tests --------------------------------------------------------------

    def test_the_task_is_skipped_unless_asked_for(self) -> None:
        self.write_agent_deck()
        _, report = self.run_janitor()
        self.assertEqual(report["tasks"]["stale_agents"]["status"], "SKIPPED")

    def test_a_deleted_binary_is_found_through_the_pane_that_owns_it(self) -> None:
        self.add_process(4100, "bash", ppid=1)
        self.add_process(4200, "codex", ppid=4100, deleted=True)
        self.add_pane("agentdeck_fixround_abc", 4100)
        self.add_row(id="row-0001", title="fixround", status="waiting",
                     tmux_session="agentdeck_fixround_abc")
        task = self.stale_task()
        profile = task["profiles"]["default"]
        self.assertEqual(task["stale_processes"], 1)
        self.assertEqual([r["id"] for r in profile["restarted"]], ["row-0001"])
        self.assertEqual([r["tools"] for r in profile["restarted"]], [["codex"]])

    def test_a_preview_restarts_nothing(self) -> None:
        self.add_process(4100, "bash", ppid=1)
        self.add_process(4200, "codex", ppid=4100, deleted=True)
        self.add_pane("agentdeck_fixround_abc", 4100)
        self.add_row(id="row-0001", title="fixround", status="waiting",
                     tmux_session="agentdeck_fixround_abc")
        self.stale_task()
        self.assertEqual([c for c in self.agent_deck_calls() if "session restart" in c],
                         [])

    def test_applying_restarts_the_row(self) -> None:
        self.add_process(4100, "bash", ppid=1)
        self.add_process(4200, "claude", ppid=4100, deleted=True)
        self.add_pane("agentdeck_review_abc", 4100)
        self.add_row(id="row-0002", title="review", status="idle",
                     tmux_session="agentdeck_review_abc")
        self.stale_task(apply=True)
        line = [c for c in self.agent_deck_calls() if "session restart" in c][0]
        self.assertIn("row-0002", line)
        self.assertIn("--force", line)

    def test_a_current_binary_is_left_alone(self) -> None:
        self.add_process(4100, "bash", ppid=1)
        self.add_process(4200, "codex", ppid=4100, deleted=False)
        self.add_pane("agentdeck_fresh_abc", 4100)
        self.add_row(id="row-0003", title="fresh", status="waiting",
                     tmux_session="agentdeck_fresh_abc")
        task = self.stale_task(apply=True)
        self.assertEqual(task["stale_processes"], 0)
        self.assertEqual(task["profiles"]["default"]["restarted"], [])
        self.assertEqual([c for c in self.agent_deck_calls() if "session restart" in c],
                         [])

    def test_running_watched_and_protected_rows_are_kept(self) -> None:
        for pid, session, row in ((4200, "agentdeck_busy_a", "row-run"),
                                  (4300, "agentdeck_seen_b", "row-watch"),
                                  (4400, "agentdeck_keep_c", "row-protect")):
            self.add_process(pid, "codex", ppid=1, deleted=True)
            self.add_pane(session, pid)
        self.add_row(id="row-run", title="busy", status="running",
                     tmux_session="agentdeck_busy_a")
        self.add_row(id="row-watch", title="seen", status="waiting",
                     tmux_session="agentdeck_seen_b", viewers=["tty1"])
        self.add_row(id="row-protect", title="conductor-semgrep", status="waiting",
                     tmux_session="agentdeck_keep_c")
        task = self.stale_task("--protect-session-title", "conductor-semgrep",
                               apply=True)
        profile = task["profiles"]["default"]
        self.assertEqual(profile["restarted"], [])
        self.assertEqual(profile["kept"], {"running": 1, "watched": 1,
                                           "protected": 1, "other": 0})
        self.assertEqual([c for c in self.agent_deck_calls() if "session restart" in c],
                         [])

    def test_a_failed_restart_degrades_without_stopping_the_rest(self) -> None:
        self.add_process(4200, "codex", ppid=1, deleted=True)
        self.add_process(4300, "codex", ppid=1, deleted=True)
        self.add_pane("agentdeck_one_a", 4200)
        self.add_pane("agentdeck_two_b", 4300)
        self.rows = [{"id": "row-a", "title": "one", "status": "waiting",
                      "tmux_session": "agentdeck_one_a"},
                     {"id": "row-b", "title": "two", "status": "waiting",
                      "tmux_session": "agentdeck_two_b"}]
        self.write_agent_deck(restart_exit=1)
        done, report = self.run_janitor("--recycle-stale-agents", apply=True)
        self.assertEqual(done.returncode, 1)
        task = report["tasks"]["stale_agents"]
        self.assertEqual(task["status"], "DEGRADED")
        self.assertEqual([f["id"] for f in task["profiles"]["default"]["failed"]],
                         ["row-a", "row-b"])

    def test_a_pane_with_no_row_is_not_restarted(self) -> None:
        self.add_process(4200, "codex", ppid=1, deleted=True)
        self.add_pane("agentdeck_orphan_a", 4200)
        self.write_agent_deck()
        task = self.stale_task(apply=True)
        self.assertEqual(task["stale_panes"], 1)
        self.assertEqual(task["profiles"]["default"]["restarted"], [])

    def test_an_unreadable_proc_root_is_reported_not_assumed_clean(self) -> None:
        self.write_agent_deck()
        _, report = self.run_janitor("--recycle-stale-agents",
                                     "--proc-root", str(self.tmp / "absent"))
        task = report["tasks"]["stale_agents"]
        self.assertEqual(task["status"], "SKIPPED")
        self.assertIn("not readable", task["summary"])


class ForeignScratchCase(unittest.TestCase):
    """A scratch tree another uid wrote into is not ours to delete.

    Box 3 carried one on 2026-10-15: a Claude scratchpad holding files a
    container had written, which the chmod retry refuses to touch by design,
    so rmtree could not finish and the run reported DEGRADED every night.
    """

    @staticmethod
    def janitor_module():
        import importlib.util
        spec = importlib.util.spec_from_loader(
            "agent_deck_janitor",
            importlib.machinery.SourceFileLoader("agent_deck_janitor", str(JANITOR)),
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.module = self.janitor_module()

    def test_our_own_tree_is_not_foreign(self) -> None:
        tree = self.tmp / "ours"
        (tree / "inner").mkdir(parents=True)
        (tree / "inner" / "file").write_text("x")
        self.assertFalse(self.module.Janitor.holds_foreign_entries(str(tree)))

    def test_a_tree_owned_by_someone_else_is_foreign(self) -> None:
        tree = self.tmp / "theirs"
        (tree / "inner").mkdir(parents=True)
        (tree / "inner" / "file").write_text("x")
        # Creating a file as another uid needs root, so the comparison moves
        # instead: every entry here belongs to someone who is not us.
        original = self.module.os.getuid
        self.module.os.getuid = lambda: original() + 1
        self.addCleanup(setattr, self.module.os, "getuid", original)
        self.assertTrue(self.module.Janitor.holds_foreign_entries(str(tree)))
