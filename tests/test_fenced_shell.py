import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cybertron.fenced_shell import ShellRejected, allowed_commands, run_fenced_shell


class FencedShellTests(unittest.TestCase):
    def test_role_prefixes_do_not_allow_generic_shell_or_command_evaluation(self):
        self.assertEqual(allowed_commands("alchemist", [["python3", "-m", "unittest"]]),
                         [["python3", "-m", "unittest"]])
        for role, argv in (
            ("prima", ["make"]),
            ("solus-prime", ["make --version"]),
            ("solus-prime", ["make", "--eval=foo"]),
            ("alchemist", ["python3", "-c", "print(1)"]),
            ("alchemist", ["python3", "-m", "unittest\n"]),
            ("nexus-prime", ["openocd", "--version"]),
            ("nexus-prime", ["ssh", "device"]),
        ):
            with self.subTest(role=role, argv=argv), self.assertRaises(ShellRejected):
                allowed_commands(role, [argv])

    def test_no_fallback_and_workdir_stays_relative(self):
        with patch("cybertron.fenced_shell.sys.platform", "linux"):
            with self.assertRaisesRegex(ShellRejected, "project-relative"):
                run_fenced_shell(Path.cwd(), "solus-prime", [["make"]], "../")
            with self.assertRaisesRegex(ShellRejected, "requires the macOS"):
                run_fenced_shell(Path.cwd(), "solus-prime", [["make"]])

    @unittest.skipUnless(sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file(),
                         "requires macOS sandbox-exec")
    @unittest.skipIf(os.environ.get("CYBERTRON_SANDBOX") == "1", "nested sandbox-exec is unsupported")
    def test_real_role_runner_keeps_writes_and_reads_inside_the_fence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            project = root / "project"
            project.mkdir()
            outside = root / "outside.txt"
            outside.write_text("outside\n")
            original = project / "source.txt"
            original.write_text("source\n")
            (project / ".env").write_text("TEST_SECRET=fixture\n")
            (project / ".git").mkdir()
            (project / ".git" / "config").write_text("[core]\n")
            (project / "local-link").symlink_to(outside)
            (project / "test_fence.py").write_text(f"""
import os
import socket
import unittest
from pathlib import Path

class Fence(unittest.TestCase):
    def test_fence(self):
        self.assertEqual(Path("source.txt").read_text(), "source\\n")
        for hidden in (".git", ".env", "local-link"):
            self.assertFalse(Path(hidden).exists())
        self.assertNotIn("CYBERTRON_TEST_FIXTURE_SECRET", os.environ)
        with self.assertRaises(PermissionError):
            Path("source.txt").write_text("changed")
        outside = Path({str(outside)!r})
        with self.assertRaises(PermissionError):
            outside.read_text()
        with self.assertRaises(PermissionError):
            outside.write_text("changed")
        with self.assertRaises(OSError):
            with socket.socket() as channel:
                channel.bind(("127.0.0.1", 0))
        with self.assertRaises(PermissionError):
            Path("/dev/tty").open("rb")
        Path("build/report.txt").write_text("generated")

    def test_temp_directory_is_writable(self):
        Path(os.environ["TMPDIR"], "scratch.txt").write_text("generated")
""")
            with patch.dict(os.environ, {"CYBERTRON_TEST_FIXTURE_SECRET": "fixture-only"}):
                result = run_fenced_shell(project, "alchemist",
                                          [["python3", "-m", "unittest", "discover"]])
            receipt = result["receipts"][0]
            self.assertEqual(receipt["exit"], 0, receipt["output"])
            self.assertIn("Ran 2 tests", receipt["output"])
            self.assertEqual(result["status"], "pass")
            self.assertTrue(result["source_intact"])
            self.assertEqual(original.read_text(), "source\n")
            self.assertEqual(outside.read_text(), "outside\n")
            self.assertFalse((project / "build").exists())

    @unittest.skipUnless(sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file(),
                         "requires macOS sandbox-exec")
    @unittest.skipIf(os.environ.get("CYBERTRON_SANDBOX") == "1", "nested sandbox-exec is unsupported")
    def test_timeout_stops_the_batch_and_returns_a_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve()
            (project / "Makefile").write_text("all:\n\t/bin/sleep 15\n")
            result = run_fenced_shell(project, "solus-prime", [["make"], ["make"]],
                                      timeout_seconds=1)
            self.assertEqual(result["status"], "fail")
            self.assertEqual(len(result["receipts"]), 1)
            self.assertEqual(result["receipts"][0]["outcome"], "timeout")
