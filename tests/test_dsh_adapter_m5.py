import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "cybertron" / "dsh_adapter"


class DshAdapterBundleTests(unittest.TestCase):
    def test_manifest_and_display_resources_are_loadable(self):
        manifest = json.loads((BUNDLE / "package.json").read_text())
        self.assertEqual(manifest["name"], "@local/cybertron-dsh")
        self.assertEqual(manifest["type"], "module")
        self.assertEqual(manifest["dsh"]["bundle"]["patch"], "./cordis.patch.yml")
        self.assertIn("./icon", manifest["exports"])
        self.assertIn("./locale/*.json", manifest["exports"])
        for name in ("index.js", "bridge.js", "cordis.patch.yml", "docs"):
            self.assertIn(name, manifest["files"])
        for locale in ("en", "zh"):
            meta = json.loads((BUNDLE / "locale" / f"{locale}.json").read_text())["meta"]
            self.assertEqual(meta["title"], "Cybertron")
            self.assertTrue(meta["description"])
            self.assertTrue((BUNDLE / meta["detail"]).is_file())
        self.assertIn("<svg", (BUNDLE / "icon.svg").read_text())

    def test_patch_adds_only_a_preset_and_mounts_the_bundle_inside_it(self):
        patch = (BUNDLE / "cordis.patch.yml").read_text()
        self.assertIn("id: preset-cybertron", patch)
        self.assertIn("name: '@deepseek-ai/dsh-agent-preset'", patch)
        self.assertIn("id: cybertron-dsh", patch)
        self.assertIn("name: '@local/cybertron-dsh'", patch)
        self.assertIn("provider: spawn", patch)
        self.assertIn("name: Cybertron", patch)
        self.assertNotIn("Cybertron v6", patch)
        # The cy_* plugin is mounted under the preset, not as a host row.
        host_rows = [line for line in patch.splitlines()
                     if line.strip().startswith("- id:") and "preset-cybertron" not in line
                     and "cybertron-dsh" not in line and not line.startswith("          ")]
        self.assertEqual(host_rows, [])
        self.assertIn("python: python3", patch)

    def test_plugin_uses_the_transport_bridge_and_registers_five_tools(self):
        source = (BUNDLE / "index.js").read_text()
        self.assertIn("from './bridge.js'", source)
        self.assertNotIn("import { defineTool } from '@deepseek-ai/dsh-tools'", source)
        self.assertIn("const defineTool = definition => definition", source)
        for tool in ("cy_plan", "cy_state", "cy_ask", "cy_templates", "cy_metrics"):
            self.assertIn(f"name: '{tool}'", source)
        # Node syntax and the real bridge contract run under `node --test`
        # (tests/dsh_adapter_bridge.test.mjs). The stage-5 sandbox cannot start
        # Node, so the Python suite stays structural and host-neutral.
        self.assertIn('from \'./bridge.js\'', source)
        self.assertIn('spawn(', (BUNDLE / "bridge.js").read_text())


if __name__ == "__main__":
    unittest.main()
