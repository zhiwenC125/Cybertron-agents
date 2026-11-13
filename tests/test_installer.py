import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class InstallerCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix=".tmp-installer-", dir=ROOT))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "cybertron.installer", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

    def test_dry_run_does_not_write(self):
        result = self.run_cli("init", "--dry-run", "--project", str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.tmp / ".opencode").exists())

    def test_apply_installs_thirteen_agents_and_config(self):
        result = self.run_cli("init", "--apply", "--project", str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stderr)
        agents = list((self.tmp / ".opencode" / "agents").glob("*.md"))
        self.assertEqual(len(agents), 13)
        commands = list((self.tmp / ".opencode" / "commands").glob("*.md"))
        self.assertEqual(len(commands), 1)
        config = json.loads(
            (self.tmp / ".opencode" / "opencode.jsonc").read_text()
        )
        self.assertEqual(config["default_agent"], "prima")

    def test_apply_is_idempotent(self):
        self.run_cli("init", "--apply", "--project", str(self.tmp))
        result = self.run_cli("init", "--apply", "--project", str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("未变 14", result.stdout)

    def test_doctor_reports_thirteen(self):
        self.run_cli("init", "--apply", "--project", str(self.tmp))
        result = self.run_cli("doctor", "--project", str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("13", result.stdout)


if __name__ == "__main__":
    unittest.main()
