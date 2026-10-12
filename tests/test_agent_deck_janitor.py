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
        self.write_agent_deck()
        write_executable(self.bin / "git",
                         "#!/bin/sh\necho \"git $*\" >> \"$CALLS/git\"\nexit 0\n")

    def write_agent_deck(self, cleanup_exit: int = 0) -> None:
        payload = json.dumps({"groups": self.groups})
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
    sys.exit({cleanup_exit})
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
        self.assertEqual(report["tasks"]["sessions"]["status"], "OK")
        line = [c for c in self.agent_deck_calls() if "session cleanup" in c]
        self.assertEqual(len(line), 1)
        self.assertIn("--days 30", line[0])
        self.assertNotIn("--yes", line[0],
                         "a preview must never pass --yes")

    def test_session_cleanup_applies_only_with_apply(self) -> None:
        _, report = self.run_janitor("--session-retention-days", "30", apply=True)
        self.assertTrue(report["tasks"]["sessions"]["applied"])
        line = [c for c in self.agent_deck_calls() if "session cleanup" in c][0]
        self.assertIn("--yes", line)

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
