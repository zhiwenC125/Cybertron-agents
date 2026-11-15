import json
import tempfile
import unittest
from pathlib import Path

from cybertron.installer import strip_jsonc
from cybertron.model_config import ModelConfigError
from cybertron.provider_config import add_provider, provider_entry


class ProviderConfigTests(unittest.TestCase):
    def test_custom_gateway_can_add_many_models_without_a_key(self):
        entry = provider_entry("company", "https://models.company.example/v1", "COMPANY_API_KEY",
                               [f"model-{number:02d}" for number in range(38)])
        self.assertEqual(len(entry["models"]), 38)
        self.assertEqual(entry["env"], ["COMPANY_API_KEY"])
        self.assertNotIn("secret", json.dumps(entry))
        with tempfile.TemporaryDirectory(prefix="cybertron-provider-") as directory:
            config = Path(directory) / "opencode.jsonc"
            original = '// preserve this comment\n{"$schema":"https://opencode.ai/config.json","theme":"dark"}\n'
            config.write_text(original)
            backup = add_provider(config, "company", entry)
            self.assertEqual(backup.read_text(), original)
            self.assertIn("// preserve this comment", config.read_text())
            data = json.loads(strip_jsonc(config.read_text()))
            self.assertEqual(data["theme"], "dark")
            self.assertEqual(len(data["providers"]["company"]["models"]), 38)
            with self.assertRaises(ModelConfigError):
                add_provider(config, "company", entry)

    def test_add_to_existing_providers_preserves_comments(self):
        with tempfile.TemporaryDirectory(prefix="cybertron-provider-") as directory:
            config = Path(directory) / "opencode.jsonc"
            raw = '{\n // company settings\n "providers": {"existing":{"name":"Existing"},},\n}\n'
            config.write_text(raw)
            entry = provider_entry("other", "https://gateway.example/v1", "OTHER_KEY", ["coder"])
            add_provider(config, "other", entry)
            self.assertIn("// company settings", config.read_text())
            providers = json.loads(strip_jsonc(config.read_text()))["providers"]
            self.assertIn("existing", providers)
            self.assertIn("other", providers)

    def test_reject_credentials_in_endpoint(self):
        with self.assertRaises(ModelConfigError):
            provider_entry("company", "https://user:secret@example.com/v1", "COMPANY_KEY", ["coder"])
        with self.assertRaises(ModelConfigError):
            provider_entry("company", "http://example.com/v1", "COMPANY_KEY", ["coder"])


if __name__ == "__main__":
    unittest.main()
