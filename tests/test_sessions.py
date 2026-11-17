import itertools
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from cybertron.runstore import RunStore, RunStoreError
from cybertron.sessions import SessionStore, normalize_slug


ROOT = Path(__file__).resolve().parent.parent


class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get("CYBERTRON_SANDBOX"):
            numbers = itertools.count(100)
            patcher = patch("cybertron.sessions.uuid.uuid4",
                            side_effect=lambda: uuid.UUID(int=next(numbers)))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.scratch = tempfile.TemporaryDirectory(prefix="cybertron-session-")
        self.workspace = Path(self.scratch.name)
        (self.workspace / "opencode.jsonc").write_text('{"default_agent":"prima"}\n')
        self.sessions = SessionStore(self.workspace)

    def tearDown(self):
        self.scratch.cleanup()

    def test_multiple_runs_survive_rename_and_old_alias(self):
        created = self.sessions.create("Motor_Control", "电机控制")
        self.assertEqual(created["slug"], "motor-control")
        self.assertTrue(created["directory"].startswith("motor-control--"))
        self.assertTrue((self.sessions.root / created["directory"]).is_dir())
        first = self.sessions.create_run("motor-control", "任务一")
        renamed = self.sessions.rename("MOTOR-CONTROL", "drive-controller", "驱动控制")
        second = self.sessions.create_run("motor-control", "任务二")
        self.assertEqual(first["session_id"], second["session_id"])
        self.assertEqual(renamed["session_id"], created["session_id"])
        self.assertEqual(renamed["aliases"], ["motor-control"])
        self.assertEqual(self.sessions.show("drive-controller")["run_count"], 2)
        self.assertEqual(self.sessions.show("motor-control")["title"], "驱动控制")
        renamed_dir = self.sessions.show("drive-controller")["directory"]
        self.assertTrue(renamed_dir.startswith("drive-controller--"))
        self.assertFalse((self.sessions.root / created["directory"]).exists())
        self.assertEqual({item["run_id"] for item in self.sessions.list_runs("drive-controller")},
                         {first["run_id"], second["run_id"]})

    def test_collision_reserved_and_path_inputs_fail(self):
        self.sessions.create("firmware")
        with self.assertRaises(RunStoreError):
            self.sessions.create("FIRMWARE")
        self.sessions.rename("firmware", "firmware-v2")
        with self.assertRaises(RunStoreError):
            self.sessions.create("firmware")  # alias remains reserved
        for slug in ("../escape", "/absolute", "run", "a/b", "..", "测试"):
            with self.subTest(slug=slug), self.assertRaises(ValueError):
                normalize_slug(slug)

    def test_archived_session_is_readable_but_rejects_new_run(self):
        created = self.sessions.create("archivable")
        self.sessions.create_run("archivable", "before archive")
        self.sessions.archive("archivable")
        self.assertTrue(self.sessions.show(created["session_id"])["archived"])
        with self.assertRaises(RunStoreError):
            self.sessions.create_run("archivable", "after archive")
        self.assertEqual(len(self.sessions.list_runs("archivable")), 1)
        self.sessions.archive("archivable", False)
        self.sessions.create_run("archivable", "after unarchive")
        self.assertEqual(len(self.sessions.list_runs("archivable")), 2)

    def test_legacy_run_session_can_receive_slug_without_moving_events(self):
        old = RunStore(self.workspace).create("旧任务")
        directory, _ = RunStore(self.workspace)._locate(old["run_id"])
        self.assertIsNone(self.sessions.show(old["session_id"])["slug"])
        self.sessions.rename(old["session_id"], "legacy-task")
        self.assertEqual(self.sessions.list_runs("legacy-task")[0]["run_id"], old["run_id"])
        self.assertTrue(directory.is_dir())

    def test_symlink_session_directory_is_rejected(self):
        external = self.workspace / "external"
        external.mkdir()
        self.sessions.root.mkdir(parents=True)
        (self.sessions.root / str(uuid.UUID(int=42))).symlink_to(external, target_is_directory=True)
        with self.assertRaises(Exception):
            self.sessions.list()

    def test_cli_session_and_run_list(self):
        if os.environ.get("CYBERTRON_SANDBOX"):
            self.skipTest("CLI UUID generation uses denied /dev/urandom in this macOS sandbox")

        def cli(*parts):
            return subprocess.run([sys.executable, "-m", "cybertron.installer", *parts,
                                   "--project", str(self.workspace)], cwd=ROOT,
                                  capture_output=True, text=True)

        created = cli("session", "create", "Robot-Arm", "--title", "机械臂")
        self.assertEqual(created.returncode, 0, created.stderr)
        session_id = json.loads(created.stdout)["session_id"]
        run = cli("run", "create", "检查电机控制", "--session", "robot-arm")
        self.assertEqual(run.returncode, 0, run.stderr)
        listed = cli("run", "list", "--session", "robot-arm")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(json.loads(listed.stdout)[0]["session_id"], session_id)
        renamed = cli("session", "rename", "robot-arm", "arm-control")
        self.assertEqual(renamed.returncode, 0, renamed.stderr)
        self.assertEqual(json.loads(cli("session", "show", "robot-arm").stdout)["slug"], "arm-control")


if __name__ == "__main__":
    unittest.main()
