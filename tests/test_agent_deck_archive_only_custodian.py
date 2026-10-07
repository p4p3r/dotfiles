#!/usr/bin/env python3
"""Isolated archive and restore acceptance tests."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "private_dot_local/bin/executable_agent-deck-archive-only-custodian"


def load_tool():
    loader = importlib.machinery.SourceFileLoader("archive_only_custodian", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ArchiveCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source_dir = self.root / "source"
        self.archive_root = self.root / "archive"
        self.destination_root = self.root / "destination"
        for path in (self.source_dir, self.archive_root, self.destination_root):
            path.mkdir(mode=0o700)
        self.source = self.source_dir / "sample"
        self.body = b"private fixture\x00contents\n"
        self.source.write_bytes(self.body)
        self.source.chmod(0o600)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def invoke(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def archive(self, *, source: Path | None = None, root: Path | None = None, label: str = "one"):
        return self.invoke(
            "archive", "--source", str(source or self.source),
            "--archive-root", str(root or self.archive_root), "--label", label,
        )

    def restore(self, *, root: Path | None = None, label: str = "one", destination: str = "copy"):
        return self.invoke(
            "restore", "--archive-root", str(root or self.archive_root),
            "--label", label, "--destination-root", str(self.destination_root),
            "--destination", destination,
        )

    def assert_rejected(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stderr, "")
        outcome = json.loads(result.stdout)
        self.assertEqual(set(outcome), {"status", "code"})
        self.assertEqual(outcome["status"], "REJECTED")
        self.assertNotIn(self.body.decode("latin1"), result.stdout)

    def test_roundtrip_preserves_source_and_restores_exact_bytes(self) -> None:
        before = self.source.stat()
        result = self.archive()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {"status": "ARCHIVED", "code": "OK"})
        after = self.source.stat()
        self.assertEqual((after.st_ino, after.st_dev, after.st_atime_ns, after.st_mtime_ns, after.st_ctime_ns),
                         (before.st_ino, before.st_dev, before.st_atime_ns, before.st_mtime_ns, before.st_ctime_ns))
        label = self.archive_root / "one"
        self.assertEqual(stat.S_IMODE(label.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((label / "content").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((label / "manifest.json").stat().st_mode), 0o600)
        self.assertEqual((label / "content").read_bytes(), self.body)
        manifest = json.loads((label / "manifest.json").read_text())
        self.assertEqual(manifest["sha256"], hashlib.sha256(self.body).hexdigest())
        self.assertEqual(manifest["size"], len(self.body))
        self.assertEqual(manifest["mode"], 0o600)
        self.assertEqual(manifest["owner_uid"], os.getuid())
        self.assertEqual(self.restore().returncode, 0)
        copy = self.destination_root / "copy"
        self.assertEqual(copy.read_bytes(), self.body)
        self.assertEqual(stat.S_IMODE(copy.stat().st_mode), 0o600)
        self.assertEqual(self.source.read_bytes(), self.body)

    def test_missing_relative_escaping_and_source_symlink(self) -> None:
        self.assert_rejected(self.archive(source=self.source_dir / "missing"))
        self.assert_rejected(self.invoke("archive", "--source", "relative", "--archive-root", str(self.archive_root), "--label", "one"))
        self.assert_rejected(self.archive(source=self.source_dir / ".." / "sample"))
        (self.source_dir / "link").symlink_to(self.source)
        self.assert_rejected(self.archive(source=self.source_dir / "link"))
        (self.root / "source-link").symlink_to(self.source_dir)
        self.assert_rejected(self.archive(source=self.root / "source-link" / "sample"))
        self.assert_rejected(self.restore(destination="../escape"))

    def test_nonregular_foreign_owner_modes_links_and_size(self) -> None:
        self.assert_rejected(self.archive(source=self.source_dir))
        tool = load_tool()
        with mock.patch.object(tool.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaises(tool.Rejected):
                tool.safe_file(self.source.stat())
        self.source.chmod(0o640)
        self.assert_rejected(self.archive())
        self.source.chmod(0o600)
        os.link(self.source, self.source_dir / "second-link")
        self.assert_rejected(self.archive())
        (self.source_dir / "second-link").unlink()
        self.source.write_bytes(b"x" * (1_048_576 + 1))
        self.assert_rejected(self.archive())
        self.source.write_bytes(self.body)
        self.archive_root.chmod(0o755)
        self.assert_rejected(self.archive())
        self.archive_root.chmod(0o700)
        self.source_dir.chmod(0o777)
        self.assert_rejected(self.archive())
        self.source_dir.chmod(0o700)
        self.assertEqual(self.archive().returncode, 0)
        self.destination_root.chmod(0o755)
        self.assert_rejected(self.restore())

    def test_label_collision_and_prepublication_temp_state(self) -> None:
        pending = self.archive_root / ".pending-interrupted"
        pending.mkdir(mode=0o700)
        (pending / "content").write_bytes(b"incomplete")
        self.assert_rejected(self.restore(label=".pending-interrupted"))
        self.assertEqual(self.archive().returncode, 0)
        original = (self.archive_root / "one" / "content").read_bytes()
        self.assert_rejected(self.archive())
        self.assertEqual((self.archive_root / "one" / "content").read_bytes(), original)

    def test_concurrent_label_collision_has_one_winner(self) -> None:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _index: self.archive(), range(2)))
        self.assertEqual(sorted(result.returncode for result in results), [0, 1])
        self.assertEqual((self.archive_root / "one" / "content").read_bytes(), self.body)

    def test_archive_write_failure_stays_unpublished(self) -> None:
        tool = load_tool()
        with mock.patch.object(tool.os, "write", side_effect=OSError("fixture write failure")):
            with self.assertRaises(tool.Rejected):
                tool.archive(str(self.source), str(self.archive_root), "one")
        self.assertFalse((self.archive_root / "one").exists())
        self.assertEqual(self.source.read_bytes(), self.body)
        self.assertEqual(len(list(self.archive_root.glob(".pending-*"))), 1)

    def test_manifest_and_content_corruption_fail_closed(self) -> None:
        self.assertEqual(self.archive().returncode, 0)
        label = self.archive_root / "one"
        manifest_file = label / "manifest.json"
        original = manifest_file.read_bytes()
        manifest = json.loads(original)
        variants = [b"{", b"x" * 2049]
        for changes in ({"version": 9}, {"extra": 1}, {"sha256": "0" * 64},
                        {"size": len(self.body) + 1}, {"mode": 0o644},
                        {"owner_uid": os.getuid() + 1}):
            variants.append(json.dumps({**manifest, **changes}).encode())
        for raw in variants:
            manifest_file.write_bytes(raw)
            self.assert_rejected(self.restore())
            self.assertFalse((self.destination_root / "copy").exists())
        manifest_file.write_bytes(original)
        content = label / "content"
        content.write_bytes(b"altered")
        self.assert_rejected(self.restore())
        content.write_bytes(self.body)
        content.chmod(0o644)
        self.assert_rejected(self.restore())
        content.chmod(0o400)
        self.assert_rejected(self.restore())

    def test_archive_component_replacement_and_restore_collision(self) -> None:
        self.assertEqual(self.archive().returncode, 0)
        label = self.archive_root / "one"
        content = label / "content"
        content.unlink()
        content.symlink_to(self.source)
        self.assert_rejected(self.restore())
        content.unlink()
        content.write_bytes(self.body)
        content.chmod(0o600)
        (self.destination_root / "copy").write_bytes(b"keep")
        self.assert_rejected(self.restore())
        self.assertEqual((self.destination_root / "copy").read_bytes(), b"keep")
        (self.destination_root / "copy").unlink()
        self.assertEqual(self.restore().returncode, 0)
        self.assert_rejected(self.restore())

    def test_metadata_and_path_replacement_during_read(self) -> None:
        tool = load_tool()
        original_read = tool.os.read
        changed = False

        def mutate_mode(fd, count):
            nonlocal changed
            data = original_read(fd, count)
            if data and not changed:
                changed = True
                self.source.chmod(0o400)
            return data

        with mock.patch.object(tool.os, "read", side_effect=mutate_mode):
            with self.assertRaises(tool.Rejected):
                tool.archive(str(self.source), str(self.archive_root), "one")
        self.source.chmod(0o600)
        self.assertFalse((self.archive_root / "one").exists())

        changed = False

        def replace_path(fd, count):
            nonlocal changed
            data = original_read(fd, count)
            if data and not changed:
                changed = True
                os.rename(self.source, self.source_dir / "old")
                self.source.write_bytes(self.body)
                self.source.chmod(0o600)
            return data

        with mock.patch.object(tool.os, "read", side_effect=replace_path):
            with self.assertRaises(tool.Rejected):
                tool.archive(str(self.source), str(self.archive_root), "two")
        self.assertFalse((self.archive_root / "two").exists())

    def test_restore_write_failure_leaves_no_published_destination(self) -> None:
        self.assertEqual(self.archive().returncode, 0)
        tool = load_tool()
        original_write = tool.os.write
        calls = 0

        def fail_write(fd, data):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("fixture write failure")
            return original_write(fd, data)

        with mock.patch.object(tool.os, "write", side_effect=fail_write):
            with self.assertRaises(tool.Rejected):
                tool.restore(str(self.archive_root), "one", str(self.destination_root), "copy")
        self.assertFalse((self.destination_root / "copy").exists())

    def test_mutation_controls_detect_source_change_and_overwrite(self) -> None:
        self.assertEqual(self.archive().returncode, 0)
        source_before = self.source.read_bytes()
        self.assertEqual(source_before, self.body)
        self.assertTrue(self.source.exists())
        self.assertEqual((self.archive_root / "one" / "content").read_bytes(), source_before)
        # The same observations must fail if a source is moved or a label overwritten.
        moved = self.source_dir / "moved"
        self.source.rename(moved)
        with self.assertRaises(AssertionError):
            self.assertTrue(self.source.exists())
        moved.rename(self.source)
        disposable = self.source_dir / "deletion-control"
        disposable.write_bytes(source_before)
        disposable.unlink()
        with self.assertRaises(AssertionError):
            self.assertTrue(disposable.exists())
        (self.archive_root / "one" / "content").write_bytes(b"overwrite")
        with self.assertRaises(AssertionError):
            self.assertEqual((self.archive_root / "one" / "content").read_bytes(), source_before)
        self.source.write_bytes(b"overwrite")
        with self.assertRaises(AssertionError):
            self.assertEqual(self.source.read_bytes(), source_before)


if __name__ == "__main__":
    unittest.main()
