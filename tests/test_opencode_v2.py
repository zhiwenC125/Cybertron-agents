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


if __name__ == "__main__":
    unittest.main()
