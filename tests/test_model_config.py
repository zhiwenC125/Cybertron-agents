import json
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from cybertron import model_cli
from cybertron.model_config import (AGENTS, DEFAULTS, ModelConfigError, apply_to_install,
                                    effective_profile, make_profile, missing_models,
                                    profile_digest, profile_path, save_profile,
                                    tier_mapping)
from cybertron.runstore import RunStore


ROOT = Path(__file__).resolve().parent.parent


class ModelConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cybertron-models-")
        self.project = Path(self.temp.name)
        self.base = self.project / ".opencode"
        for kind in ("agents", "commands"):
            shutil.copytree(ROOT / ".opencode" / kind, self.base / kind)

    def tearDown(self):
        self.temp.cleanup()

    def test_one_company_key_catalog_can_feed_thirteen_roles(self):
        catalog = {f"company/model-{index:02d}" for index in range(38)}
        models = tier_mapping("company/model-37", "company/model-18", "company/model-00")
        profile = make_profile(models, {"high": "company/model-37",
                                        "middle": "company/model-18", "low": "company/model-00"})
        self.assertEqual(len(models), 13)
        self.assertEqual(profile["allowed_providers"], ["company"])
        self.assertFalse(missing_models(profile, catalog))
        path = profile_path(self.project)
        save_profile(path, profile, self.base)
        self.assertEqual(effective_profile(self.project), profile)
        self.assertIn("model: company/model-37", (self.base / "agents/prima.md").read_text())
        self.assertIn("model: company/model-37", (self.base / "commands/cybertron.md").read_text())
        self.assertEqual(profile_digest(self.project), __import__("hashlib").sha256(path.read_bytes()).hexdigest())

    def test_private_cross_provider_change_one_role_and_rollback(self):
        path = profile_path(self.project)
        initial = make_profile({agent: "vendor-a/opus" for agent in AGENTS})
        save_profile(path, initial, self.base)
        updated = dict(initial["agents"])
        updated["solus-prime"] = "vendor-b/gpt"
        save_profile(path, make_profile(updated), self.base)
        self.assertEqual(sum(a != b for a, b in zip(initial["agents"].values(), updated.values())), 1)
        self.assertEqual(len(list(path.parent.glob("models.json.bak.*"))), 1)
        self.assertIn("model: vendor-b/gpt", (self.base / "agents/solus-prime.md").read_text())
        self.assertIn("model: vendor-a/opus", (self.base / "agents/prima.md").read_text())
        old = json.loads(next(path.parent.glob("models.json.bak.*")).read_text())
        save_profile(path, old, self.base)
        self.assertEqual(effective_profile(self.project)["agents"], initial["agents"])

    def test_invalid_or_missing_models_cannot_be_saved(self):
        models = dict(DEFAULTS)
        models["prima"] = "bad-model-id"
        with self.assertRaises(ModelConfigError):
            make_profile(models)
        models["prima"] = "company/coder"
        profile = make_profile(models)
        self.assertEqual(missing_models(profile, {"company/coder"}),
                         set(DEFAULTS.values()))

    def test_local_profile_overrides_global_without_merging_private_roles(self):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.project / "config")}, clear=False):
            global_profile = make_profile({agent: "private/model" for agent in AGENTS})
            global_path = profile_path(self.project, True)
            global_path.parent.mkdir(parents=True)
            global_path.write_text(json.dumps(global_profile))
            self.assertEqual(effective_profile(self.project)["agents"]["prima"], "private/model")
            local_profile = make_profile({agent: "company/model" for agent in AGENTS})
            save_profile(profile_path(self.project), local_profile, self.base)
            self.assertEqual(effective_profile(self.project)["allowed_providers"], ["company"])

    def test_setup_repeat_and_cancel_preserve_files(self):
        catalog = {"vendor/one", "vendor/two"}
        args = ["setup", "--project", str(self.project), "--single", "vendor/one", "--yes"]
        with patch.object(model_cli, "available_models", return_value=catalog), \
             patch.object(model_cli, "_doctor", return_value=0):
            self.assertEqual(model_cli.main(args), 0)
            snapshot = profile_path(self.project).read_bytes()
            with patch("builtins.input", return_value="n"):
                self.assertEqual(model_cli.main(["setup", "--project", str(self.project),
                                                 "--set", "prima=vendor/two"]), 0)
            self.assertEqual(profile_path(self.project).read_bytes(), snapshot)
            self.assertEqual(model_cli.main(["setup", "--project", str(self.project),
                                             "--set", "prima=vendor/two", "--yes"]), 0)
        self.assertEqual(effective_profile(self.project)["agents"]["prima"], "vendor/two")
        self.assertEqual(effective_profile(self.project)["agents"]["alchemist"], "vendor/one")

    def test_failed_opencode_load_restores_previous_fleet(self):
        catalog = {"vendor/one", "vendor/two"}
        with patch.object(model_cli, "available_models", return_value=catalog), \
             patch.object(model_cli, "_doctor", return_value=0):
            self.assertEqual(model_cli.main(["setup", "--project", str(self.project),
                                             "--single", "vendor/one", "--yes"]), 0)
        before = profile_path(self.project).read_bytes()
        prima = (self.base / "agents/prima.md").read_bytes()
        with patch.object(model_cli, "available_models", return_value=catalog), \
             patch.object(model_cli, "_doctor", return_value=1):
            self.assertEqual(model_cli.main(["setup", "--project", str(self.project),
                                             "--set", "prima=vendor/two", "--yes"]), 2)
        self.assertEqual(profile_path(self.project).read_bytes(), before)
        self.assertEqual((self.base / "agents/prima.md").read_bytes(), prima)

    def test_optional_probe_reads_only_a_synthetic_file(self):
        profile = make_profile({agent: "vendor/one" for agent in AGENTS})
        def runner(command, **kwargs):
            cwd = Path(kwargs["cwd"])
            self.assertNotEqual(cwd, self.project)
            self.assertEqual((cwd / "probe.txt").read_text(), "cybertron-probe-ok\n")
            self.assertFalse((cwd / "private-project.txt").exists())
            events = [
                {"type": "tool_use", "part": {"tool": "read", "state": {"status": "completed"}}},
                {"type": "text", "part": {"text": '{"status":"ok","value":"cybertron-probe-ok"}'}},
            ]
            return subprocess.CompletedProcess(command, 0, "\n".join(json.dumps(e) for e in events), "")
        (self.project / "private-project.txt").write_text("do not upload")
        with patch.object(model_cli, "available_models", return_value={"vendor/one"}), \
             patch.object(model_cli.subprocess, "run", side_effect=runner):
            model_cli._probe(profile)

    def test_existing_run_detects_model_switch(self):
        store = RunStore(self.project)
        with patch("cybertron.runstore.uuid.uuid4", return_value=uuid.UUID(int=1)):
            run_id = store.create("开发示例软件功能", mode="software")["run_id"]
        self.assertEqual(store.show(run_id)["config"], "current")
        profile = make_profile({agent: "company/model" for agent in AGENTS})
        save_profile(profile_path(self.project), profile, self.base)
        self.assertEqual(store.show(run_id)["config"], "changed")


if __name__ == "__main__":
    unittest.main()
