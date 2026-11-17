import tempfile
import unittest
import os
import socket
import errno
from pathlib import Path

from cybertron.scope_guard import ScopeGuard, ScopeGuardError


class ScopeGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "keep.txt").write_text("old")
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_existing.py").write_text("original")

    def test_out_of_scope_edit_create_and_delete_are_rolled_back(self):
        guard = ScopeGuard(self.root, ("src/**",))
        before = guard.snapshot()
        (self.root / "src" / "keep.txt").write_text("allowed")
        (self.root / "tests" / "test_existing.py").unlink()
        (self.root / "tests" / "new.py").write_text("forbidden")
        report = guard.verify_and_rollback(before)
        self.assertEqual(report.rejected_paths, ("tests/new.py", "tests/test_existing.py"))
        self.assertEqual((self.root / "tests" / "test_existing.py").read_text(), "original")
        self.assertFalse((self.root / "tests" / "new.py").exists())
        self.assertEqual((self.root / "src" / "keep.txt").read_text(), "allowed")

    def test_git_and_run_state_are_hard_denied_even_with_broad_scope(self):
        (self.root / ".git").mkdir()
        (self.root / ".git" / "config").write_text("old")
        run = self.root / ".cybertron" / "runs" / "r1"
        run.mkdir(parents=True)
        (run / "events.jsonl").write_text("old")
        guard = ScopeGuard(self.root, ("**",))
        before = guard.snapshot()
        (self.root / ".git" / "config").write_text("tampered")
        (run / "events.jsonl").write_text("tampered")
        report = guard.verify_and_rollback(before)
        self.assertEqual(report.rejected_paths, (".cybertron/runs/r1/events.jsonl", ".git/config"))
        self.assertEqual((self.root / ".git" / "config").read_text(), "old")
        self.assertEqual((run / "events.jsonl").read_text(), "old")

    def test_new_out_of_scope_directory_is_removed(self):
        guard = ScopeGuard(self.root, ("src/**",))
        before = guard.snapshot()
        (self.root / "other").mkdir()
        (self.root / "other" / "file.txt").write_text("bad")
        report = guard.verify_and_rollback(before)
        self.assertIn("other/file.txt", report.rejected_paths)
        self.assertFalse((self.root / "other").exists())

    def test_rollback_never_follows_replaced_directory_symlink(self):
        outside = Path(self.temp.name).parent / (self.root.name + "-outside")
        outside.mkdir()
        self.addCleanup(lambda: outside.rmdir())
        (outside / "test_existing.py").write_text("external")
        self.addCleanup(lambda: (outside / "test_existing.py").unlink(missing_ok=True))
        guard = ScopeGuard(self.root, ("src/**",))
        before = guard.snapshot()
        (self.root / "tests" / "test_existing.py").unlink()
        (self.root / "tests").rmdir()
        (self.root / "tests").symlink_to(outside, target_is_directory=True)
        report = guard.verify_and_rollback(before)
        self.assertTrue(report.rolled_back)
        self.assertEqual((outside / "test_existing.py").read_text(), "external")
        self.assertEqual((self.root / "tests" / "test_existing.py").read_text(), "original")

    def test_new_symlink_inside_write_scope_is_rejected(self):
        guard = ScopeGuard(self.root, ("src/**",))
        before = guard.snapshot()
        (self.root / "src" / "link").symlink_to(self.root / "tests", target_is_directory=True)
        report = guard.verify_and_rollback(before)
        self.assertEqual(report.rejected_paths, ("src/link",))
        self.assertFalse((self.root / "src" / "link").exists())

    def test_existing_symlink_inside_write_scope_blocks_dispatch(self):
        (self.root / "src" / "link").symlink_to(self.root / "tests", target_is_directory=True)
        guard = ScopeGuard(self.root, ("src/**",))
        with self.assertRaises(ScopeGuardError):
            guard.assert_safe_before_dispatch(guard.snapshot())

    def test_existing_symlink_outside_write_scope_also_blocks_dispatch(self):
        (self.root / "tests" / "link").symlink_to(self.root / "src", target_is_directory=True)
        guard = ScopeGuard(self.root, ("src/**",))
        with self.assertRaises(ScopeGuardError):
            guard.assert_safe_before_dispatch(guard.snapshot())

    def test_existing_socket_and_fifo_do_not_block_dispatch_or_diff(self):
        sock_path = self.root / "runtime.sock"
        fifo_path = self.root / "runtime.fifo"
        sock = socket.socket(socket.AF_UNIX)
        self.addCleanup(sock.close)
        previous_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            try:
                sock.bind(sock_path.name)
            except OSError as exc:
                if exc.errno != errno.EPERM:
                    raise
        finally:
            os.chdir(previous_cwd)
        os.mkfifo(fifo_path)
        guard = ScopeGuard(self.root, ("src/**",))
        before = guard.snapshot()
        guard.assert_safe_before_dispatch(before)
        if sock_path.exists():
            self.assertNotIn("runtime.sock", before.entries)
        self.assertNotIn("runtime.fifo", before.entries)
        (self.root / "src" / "keep.txt").write_text("allowed")
        self.assertEqual(guard.diff(before).changed_paths, ("src/keep.txt",))

    def test_special_file_cannot_hide_out_of_scope_regular_file_replacement(self):
        guard = ScopeGuard(self.root, ("src/**",))
        before = guard.snapshot()
        target = self.root / "tests" / "test_existing.py"
        target.unlink()
        os.mkfifo(target)
        report = guard.verify_and_rollback(before)
        self.assertEqual(report.rejected_paths, ("tests/test_existing.py",))
        self.assertEqual(target.read_text(), "original")


    def test_access_modes_control_writes_and_skip_full_snapshot(self):
        read_only = ScopeGuard(self.root, (), access_mode="read-only")
        self.assertFalse(read_only._allowed("src/keep.txt", is_dir=False))
        full = ScopeGuard(self.root, ("/tmp/outside.txt",), access_mode="danger-full-access")
        self.assertTrue(full._allowed("src/keep.txt", is_dir=False))
        self.assertTrue(full._allowed("/tmp/outside.txt", is_dir=False))
        self.assertFalse(full._allowed(".git/config", is_dir=False))
        self.assertEqual(full.snapshot().entries, {})
        with self.assertRaises(ScopeGuardError):
            ScopeGuard(self.root, ("/tmp/outside.txt",), access_mode="workspace-write")

    def test_pruned_dependency_tree_keeps_directory_entry(self):
        modules = self.root / "node_modules" / "pkg"
        modules.mkdir(parents=True)
        (modules / "index.js").write_text("vendored")
        guard = ScopeGuard(self.root, ("src/**",))
        before = guard.snapshot()
        self.assertIn("node_modules", before.entries)
        self.assertNotIn("node_modules/pkg/index.js", before.entries)
        (modules / "index.js").write_text("changed")
        self.assertEqual(guard.diff(before).changed_paths, ())

    def test_unreadable_file_is_opaque_instead_of_fatal(self):
        secret = self.root / "tests" / "secret.txt"
        secret.write_text("classified")
        os.chmod(secret, 0)
        self.addCleanup(os.chmod, secret, 0o600)
        if os.access(secret, os.R_OK):
            self.skipTest("file mode 000 is readable for this user")
        guard = ScopeGuard(self.root, ("src/**",))
        before = guard.snapshot()
        self.assertEqual(before.entries["tests/secret.txt"].kind, "opaque")
        guard.assert_safe_before_dispatch(before)
        (self.root / "src" / "keep.txt").write_text("allowed")
        self.assertEqual(guard.diff(before).changed_paths, ("src/keep.txt",))


if __name__ == "__main__":
    unittest.main()
