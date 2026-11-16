import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from cybertron.exporters import compile_opencode_v2_assets
from cybertron.policy import MegatronusCircuitBreaker, PermissionEffect
from cybertron.registry import THIRTEEN_PRIMES_REGISTRY


class V6PermissionTests(unittest.TestCase):
    def test_host_fixture_disables_legacy_plugin_without_disabling_v6(self):
        with TemporaryDirectory() as directory:
            compile_opencode_v2_assets(Path(directory), disable_legacy_cybertron=True)
            config = json.loads((Path(directory) / "opencode.jsonc").read_text())
            self.assertIn("-cybertron.runtime", config["plugins"])
        source = (Path(__file__).resolve().parent.parent / "cybertron" / "v6_plugin" / "cybertron.js").read_text()
        self.assertIn("id: 'cybertron.v6.runtime'", source)

    def test_plugin_generated_copies_match_source(self):
        root = Path(__file__).resolve().parent.parent
        for name in ("cybertron.js", "hook_logic.mjs"):
            source = (root / "cybertron" / "v6_plugin" / name).read_bytes()
            for generated in (root / ".opencode" / "plugins" / name,
                              root / "cybertron" / "payload" / "plugins" / name):
                with self.subTest(path=str(generated)):
                    self.assertEqual(generated.read_bytes(), source)

    def test_only_prima_can_start_native_subagents(self):
        for agent in THIRTEEN_PRIMES_REGISTRY:
            breaker = MegatronusCircuitBreaker(agent.permissions)
            effect, _ = breaker.verify_tool_call("subagent", "alpha-trion", agent.agent_id)
            self.assertEqual(effect, PermissionEffect.ALLOW if agent.agent_id == "prima" else PermissionEffect.DENY)

    def test_prima_has_minimal_cy_tools_and_no_legacy_run_tool(self):
        prima = THIRTEEN_PRIMES_REGISTRY[0]
        for tool in ("cy_state", "cy_plan", "cy_ask"):
            with self.subTest(tool=tool):
                self.assertEqual(MegatronusCircuitBreaker(prima.permissions).verify_tool_call(tool, "*", tool)[0],
                                 PermissionEffect.ALLOW)
        self.assertEqual(MegatronusCircuitBreaker(prima.permissions).verify_tool_call(
            "cybertron_run", "*", "legacy")[0], PermissionEffect.DENY)

    def test_alpha_can_write_root_notes_but_not_role_config(self):
        alpha = next(agent for agent in THIRTEEN_PRIMES_REGISTRY if agent.agent_id == "alpha-trion")
        breaker = MegatronusCircuitBreaker(alpha.permissions)
        self.assertEqual(breaker.verify_tool_call("edit", "notes.md", "notes")[0], PermissionEffect.ALLOW)
        self.assertEqual(breaker.verify_tool_call("edit", ".opencode/agents/prima.md", "agent")[0],
                         PermissionEffect.DENY)
