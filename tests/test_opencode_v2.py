import json
import tempfile
import unittest
from pathlib import Path

from cybertron.exporters import compile_opencode_v2_assets
from cybertron.opencode_v2 import validate_bundle


class OpenCodeV2BundleTests(unittest.TestCase):
    def test_default_bundle_loads_without_feishu_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compile_opencode_v2_assets(root)
            self.assertEqual(validate_bundle(root), [])
            config = json.loads((root / "opencode.jsonc").read_text())
            self.assertNotIn("mcp", config)
            self.assertEqual(len(config["agents"]), 13)

    def test_missing_agent_file_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compile_opencode_v2_assets(root)
            (root / ".opencode/agents/prima.md").unlink()
            self.assertTrue(any("prima" in error for error in validate_bundle(root)))

    def test_permission_drift_between_markdown_and_json_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compile_opencode_v2_assets(root)
            agent_file = root / ".opencode/agents/prima.md"
            content = agent_file.read_text()
            agent_file.write_text(content.replace('resource: "onyx-prime"',
                                                  'resource: "build"', 1))
            self.assertTrue(any("permissions differ" in error
                                for error in validate_bundle(root)))

    def test_exported_permissions_must_match_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compile_opencode_v2_assets(root)
            config_path = root / "opencode.jsonc"
            config = json.loads(config_path.read_text())
            config["agents"]["nexus-prime"]["permissions"].append(
                {"action": "edit", "resource": "opencode.jsonc", "effect": "allow"}
            )
            config_path.write_text(json.dumps(config))
            self.assertTrue(any("JSON permissions differ from registry" in error
                                for error in validate_bundle(root)))


if __name__ == "__main__":
    unittest.main()
