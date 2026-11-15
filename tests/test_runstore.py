import json
import itertools
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from cybertron.execution import QualityEvidence, QualityKind
from cybertron.runstore import ConfigChanged, RunCorrupt, RunLocked, RunStore


ROOT = Path(__file__).resolve().parent.parent


class RunStoreTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get("CYBERTRON_SANDBOX"):
            # sandbox-exec denies /dev/urandom. Only the test ID source changes;
            # production still uses UUIDv4 and the sandbox policy stays intact.
            numbers = itertools.count(1)
            patcher = patch("cybertron.runstore.uuid.uuid4",
                            side_effect=lambda: uuid.UUID(int=next(numbers)))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.scratch = tempfile.TemporaryDirectory(prefix="cybertron-runstore-")
        self.workspace = Path(self.scratch.name)
        (self.workspace / "opencode.jsonc").write_text('{"default_agent":"prima"}\n')
        self.store = RunStore(self.workspace)
        self.created = self.store.create("做一项可恢复的离线任务")
        self.run_id = self.created["run_id"]
        self.directory, _ = self.store._locate(self.run_id)

    def tearDown(self):
        self.scratch.cleanup()

    def test_reopens_run_and_preserves_progress_and_attempt_ids(self):
        self.store.transition(self.run_id, "stage.started", lambda ledger: ledger.start_step(1),
                              stage_id=1, dispatch_id="dispatch-one", attempt_id="attempt-one")
        self.store.transition(self.run_id, "dispatch.completed",
                              lambda ledger: ledger.complete_step(1, "澄清完成", ["local://spec"]),
                              stage_id=1, dispatch_id="dispatch-one", attempt_id="attempt-one")
        reopened = RunStore(self.workspace)
        state = reopened.verify(self.run_id)
        self.assertTrue(state["verified"])
        self.assertEqual((state["event_seq"], state["stage_id"], state["snapshot"]), (3, 2, "current"))
        events = [json.loads(line) for line in (self.directory / "events.jsonl").read_text().splitlines()]
        self.assertEqual(events[-1]["dispatch_id"], "dispatch-one")
        self.assertEqual(events[-1]["ledger"]["plan"][0]["evidence"], ["local://spec"])

    def test_rework_count_and_participant_progress_survive_replay(self):
        def reject_review(ledger):
            for step_id in range(1, 5):
                ledger.start_step(step_id)
                ledger.complete_step(step_id, "synthetic prerequisite", ["local://prerequisite"])
            ledger.start_step(5)
            ledger.reject_review("micronus-prime", "needs rework")

        self.store.transition(self.run_id, "review.rejected", reject_review, stage_id=5)
        state = RunStore(self.workspace).show(self.run_id)
        self.assertEqual(state["review_retry_count"], 1)
        self.assertEqual(state["stage_id"], 4)
        self.assertEqual(state["next_agent"], "solus-prime")

    def test_typed_quality_evidence_survives_replay(self):
        self.store.transition(self.run_id, "evidence.recorded",
                              lambda ledger: ledger.plan[0].quality_evidence.append(
                                  QualityEvidence(QualityKind.TEST, True, "sandbox://receipt")))
        ledger = RunStore(self.workspace).load_ledger(self.run_id)
        self.assertEqual(ledger.plan[0].quality_evidence[0].kind, QualityKind.TEST)
        self.assertEqual(ledger.plan[0].quality_evidence[0].source, "sandbox://receipt")

    def test_run_storage_symlink_is_rejected(self):
        events = self.directory / "events.jsonl"
        external = self.workspace / "external.jsonl"
        events.rename(external)
        events.symlink_to(external)
        with self.assertRaises(RunCorrupt):
            self.store.show(self.run_id)

    def test_event_survives_failed_snapshot_and_resume_rebuilds_without_dispatch(self):
        with patch.object(self.store, "_write_snapshot", side_effect=OSError("injected snapshot failure")):
            with self.assertRaises(OSError):
                self.store.transition(self.run_id, "stage.started", lambda ledger: ledger.start_step(1), stage_id=1)
        before = RunStore(self.workspace).verify(self.run_id)
        self.assertFalse(before["verified"])
        self.assertEqual(before["snapshot"], "stale")
        after = RunStore(self.workspace).resume(self.run_id)
        self.assertEqual(after["snapshot"], "current")
        self.assertFalse(after["dispatch_started"])
        self.assertEqual(after["stage_id"], 1)
        self.assertEqual(after["status"], "in_progress")

    def test_truncated_and_duplicate_events_block_recovery(self):
        log = self.directory / "events.jsonl"
        original = log.read_bytes()
        for bad in (original + b'{"seq":2', original + original):
            log.write_bytes(bad)
            with self.assertRaises(RunCorrupt):
                self.store.resume(self.run_id)
        log.write_bytes(original)
        self.assertTrue(self.store.verify(self.run_id)["verified"])

    def test_unsupported_schema_and_ahead_snapshot_block(self):
        log = self.directory / "events.jsonl"
        original = log.read_bytes()
        event = json.loads(original)
        event["schema_version"] = 99
        log.write_text(json.dumps(event) + "\n")
        with self.assertRaises(RunCorrupt):
            self.store.verify(self.run_id)
        log.write_bytes(original)
        snapshot = self.directory / "ledger.json"
        data = json.loads(snapshot.read_text())
        data["snapshot_seq"] = 2
        snapshot.write_text(json.dumps(data))
        with self.assertRaises(RunCorrupt):
            self.store.resume(self.run_id)

    def test_concurrent_writer_and_config_change_block(self):
        with self.store._writer(self.directory):
            with self.assertRaises(RunLocked):
                self.store.transition(self.run_id, "stage.started", lambda ledger: ledger.start_step(1))
        (self.workspace / "opencode.jsonc").write_text('{"default_agent":"build"}\n')
        with self.assertRaises(ConfigChanged):
            self.store.resume(self.run_id)
        self.assertEqual(self.store.show(self.run_id)["config"], "changed")

    def test_runtime_change_keeps_run_readable_but_blocks_resume(self):
        with patch.object(self.store, "_runtime_digest", return_value="changed"):
            self.assertEqual(self.store.show(self.run_id)["runtime"], "changed")
            with self.assertRaises(ConfigChanged):
                self.store.resume(self.run_id)

    def test_cli_create_show_verify_resume(self):
        if os.environ.get("CYBERTRON_SANDBOX"):
            self.skipTest("CLI UUID generation uses denied /dev/urandom in this macOS sandbox")
        def cli(*parts):
            return subprocess.run([sys.executable, "-m", "cybertron.installer", "run", *parts,
                                   "--project", str(self.workspace)], cwd=ROOT,
                                  capture_output=True, text=True)
        created = cli("create", "CLI 离线任务")
        self.assertEqual(created.returncode, 0, created.stderr)
        run_id = json.loads(created.stdout)["run_id"]
        for operation in ("show", "verify", "resume"):
            with self.subTest(operation=operation):
                result = cli(operation, run_id)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["run_id"], run_id)
        self.assertNotEqual(cli("show", "../unsafe").returncode, 0)


if __name__ == "__main__":
    unittest.main()
