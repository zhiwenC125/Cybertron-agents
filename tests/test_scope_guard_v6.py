import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
