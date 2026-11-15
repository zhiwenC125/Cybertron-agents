import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cybertron.installer import apply_install, resolve_payload

ROOT = Path(__file__).resolve().parent.parent


class InstallerCliTest(unittest.TestCase):
    @staticmethod
    def entries():
        # Current macOS sandbox-exec makes Node 26 abort before the CLI starts.
        # CI and the host-side matrix still exercise npm; the isolated QA run
        # checks the Python and Shell paths without weakening its profile.
        return ("python", "shell") if os.environ.get("CYBERTRON_SANDBOX") else ("python", "npm", "shell")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cybertron-installer-"))
        # Isolate the developer's global model profile; installers must match
        # the checked-in bundle, which follows registry defaults.
        self.config_home = self.tmp / "config-home"
        self.config_home.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env(self):
        return {**os.environ, "XDG_CONFIG_HOME": str(self.config_home)}

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "cybertron.installer", *args],
            cwd=ROOT,
            env=self.env(),
            capture_output=True,
            text=True,
        )

    def run_entry(self, entry, *args):
        commands = {
            "python": [sys.executable, "-m", "cybertron.installer", "init"],
            "npm": ["node", str(ROOT / "bin/cybertron.mjs"), "init"],
            "shell": ["bash", str(ROOT / "install.sh")],
        }
        if entry == "npm" and shutil.which("node") is None:
            self.skipTest("node is unavailable")
        return subprocess.run([*commands[entry], *args, "--project", str(self.tmp)],
                              cwd=ROOT, env=self.env(), capture_output=True, text=True)

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
        self.assertNotIn("default_agent", config)

    def test_apply_is_idempotent(self):
        self.run_cli("init", "--apply", "--project", str(self.tmp))
        result = self.run_cli("init", "--apply", "--project", str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"未变 [1-9][0-9]+")

    def test_doctor_reports_thirteen(self):
        self.run_cli("init", "--apply", "--project", str(self.tmp))
        result = self.run_cli("doctor", "--project", str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("13", result.stdout)

    def test_three_installers_match_and_keep_numbered_backups(self):
        expected = {(kind, path.name): path.read_bytes()
                    for kind in ("agents", "commands")
                    for path in (ROOT / ".opencode" / kind).glob("*.md")}
        self.assertEqual(len(expected), 14)
        for entry in self.entries():
            with self.subTest(entry=entry):
                project = self.tmp / entry
                project.mkdir()
                original = self.tmp
                self.tmp = project
                try:
                    preview = self.run_entry(entry, "--dry-run")
                    self.assertEqual(preview.returncode, 0, preview.stderr)
                    self.assertFalse((project / ".opencode").exists())
                    installed = self.run_entry(entry, "--apply")
                    self.assertEqual(installed.returncode, 0, installed.stderr)
                    for (kind, name), content in expected.items():
                        self.assertEqual((project / ".opencode" / kind / name).read_bytes(), content)
                    self.assertNotIn("default_agent", json.loads((project / ".opencode/opencode.jsonc").read_text()))
                    repeated = self.run_entry(entry, "--apply")
                    self.assertEqual(repeated.returncode, 0, repeated.stderr)
                    self.assertRegex(repeated.stdout, r"未变 [1-9][0-9]+")
                    self.assertTrue((project / ".opencode/plugins/cybertron.js").is_file())
                    self.assertTrue((project / ".opencode/cybertron-runtime/cybertron/plugin_cli.py").is_file())
                    agent = project / ".opencode/agents/prima.md"
                    agent.write_text("local edit one", encoding="utf-8")
                    self.assertEqual(self.run_entry(entry, "--apply").returncode, 0)
                    self.assertEqual((agent.parent / "prima.md.bak.1").read_text(), "local edit one")
                    agent.write_text("local edit two", encoding="utf-8")
                    self.assertEqual(self.run_entry(entry, "--apply").returncode, 0)
                    self.assertEqual((agent.parent / "prima.md.bak.2").read_text(), "local edit two")
                    self.assertEqual((agent.parent / "prima.md.bak.1").read_text(), "local edit one")
                    doctor_args = ["--doctor"] if entry == "shell" else ["doctor"]
                    if entry == "shell":
                        doctor = subprocess.run(["bash", str(ROOT / "install.sh"), *doctor_args,
                                                 "--project", str(project)], cwd=ROOT,
                                                env=self.env(), capture_output=True, text=True)
                    elif entry == "npm":
                        doctor = subprocess.run(["node", str(ROOT / "bin/cybertron.mjs"),
                                                 *doctor_args, "--project", str(project)], cwd=ROOT,
                                                env=self.env(), capture_output=True, text=True)
                    else:
                        doctor = self.run_cli(*doctor_args, "--project", str(project))
                    self.assertEqual(doctor.returncode, 0, doctor.stderr)
                finally:
                    self.tmp = original

    def test_existing_config_is_preserved_or_rejected_before_install(self):
        for entry in self.entries():
            with self.subTest(entry=entry):
                project = self.tmp / entry
                config_dir = project / ".opencode"
                config_dir.mkdir(parents=True)
                original = self.tmp
                self.tmp = project
                try:
                    raw = '// user comment\n{"default_agent":"build","custom":true}\n'
                    config = config_dir / "opencode.jsonc"
                    config.write_text(raw)
                    self.assertEqual(self.run_entry(entry, "--apply").returncode, 0)
                    self.assertEqual(config.read_text(), raw)
                    shutil.rmtree(config_dir / "agents")
                    shutil.rmtree(config_dir / "commands")
                    config.write_text('{"custom":true}\n')
                    result = self.run_entry(entry, "--apply")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(config.read_text(), '{"custom":true}\n')
                    self.assertEqual(len(list((config_dir / "agents").glob("*.md"))), 13)
                    shutil.rmtree(config_dir / "agents")
                    config.write_text('{broken jsonc\n')
                    rejected = self.run_entry(entry, "--apply")
                    self.assertNotEqual(rejected.returncode, 0)
                    self.assertFalse((config_dir / "agents").exists())
                finally:
                    self.tmp = original

    def test_python_install_rolls_back_mid_copy_failure(self):
        good = self.tmp / "good.md"
        good.write_text("good")
        missing = self.tmp / "missing.md"
        target = self.tmp / "installed" / "one.md"
        with self.assertRaises(FileNotFoundError):
            apply_install([("agents", good, target, "new"),
                           ("agents", missing, target.parent / "two.md", "new")])
        self.assertFalse(target.exists())

    def test_node_install_rolls_back_mid_copy_failure(self):
        if shutil.which("node") is None or os.environ.get("CYBERTRON_SANDBOX"):
            self.skipTest("Node installer is verified outside the macOS sandbox")
        code = """
import {applyInstall} from './lib/install.mjs';
import {existsSync, writeFileSync} from 'node:fs';
import path from 'node:path';
const base = process.argv[1];
const good = path.join(base, 'good.md');
writeFileSync(good, 'good');
const target = path.join(base, 'installed', 'one.md');
try {
  applyInstall({items: [
    {src: good, target, state: 'new'},
    {src: path.join(base, 'missing.md'), target: path.join(base, 'installed', 'two.md'), state: 'new'},
  ]});
  process.exit(2);
} catch {
  if (existsSync(target)) process.exit(3);
}
"""
        result = subprocess.run(["node", "--input-type=module", "-e", code, str(self.tmp)],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_shell_install_rolls_back_after_rejecting_symlink(self):
        project = self.tmp / "shell-rollback"
        agents = project / ".opencode/agents"
        agents.mkdir(parents=True)
        original = project / "original.md"
        original.write_text("original")
        (agents / "alpha-trion.md").symlink_to(original)
        result = subprocess.run(["bash", str(ROOT / "install.sh"), "--apply",
                                 "--project", str(project)], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((agents / "alchemist.md").exists())
        self.assertEqual(original.read_text(), "original")

    def test_explicit_ref_overrides_bundled_python_payload(self):
        with patch("cybertron.installer.download_payload", return_value=self.tmp) as download:
            self.assertEqual(resolve_payload("", "v0.1.1", "abc"), self.tmp)
            download.assert_called_once_with("v0.1.1", "abc")


if __name__ == "__main__":
    unittest.main()
