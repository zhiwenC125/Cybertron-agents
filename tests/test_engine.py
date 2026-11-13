import json
import tempfile
import unittest
from pathlib import Path

from cybertron import (
    FeishuWikiGovernanceConfig,
    FeishuWikiKnowledgeClient,
    MegatronusCircuitBreaker,
    PermissionEffect,
    PrimaPlanOrchestrator,
    THIRTEEN_PRIMES_REGISTRY,
    compile_deepseek_harness_assets,
    compile_opencode_v2_assets,
    function_to_json_schema,
)


class EngineTests(unittest.TestCase):
    def test_tool_schema_resolves_postponed_annotations(self):
        def example(count: int, enabled: bool = False) -> None:
            pass

        schema = function_to_json_schema(example)["function"]["parameters"]
        self.assertEqual(schema["properties"]["count"]["type"], "integer")
        self.assertEqual(schema["properties"]["enabled"]["type"], "boolean")
        self.assertEqual(schema["required"], ["count"])

    def test_registry_and_exports(self):
        self.assertEqual(len(THIRTEEN_PRIMES_REGISTRY), 13)
        self.assertEqual(len({agent.agent_id for agent in THIRTEEN_PRIMES_REGISTRY}), 13)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            opencode_files = compile_opencode_v2_assets(root)
            dsh_files = compile_deepseek_harness_assets(root)
            self.assertEqual(len(opencode_files), 14)
            self.assertEqual(len(dsh_files), 1)
            config = json.loads((root / "opencode.jsonc").read_text())
            preset = json.loads((root / ".dsh/cybertron-primes-preset.json").read_text())
            self.assertEqual(set(config["agents"]), {agent.agent_id for agent in THIRTEEN_PRIMES_REGISTRY})
            self.assertEqual({agent["id"] for agent in preset["agents"]}, set(config["agents"]))

    def test_ledger_requires_order_and_evidence(self):
        ledger = PrimaPlanOrchestrator().create_full_sdlc_hardware_ledger("demo")
        self.assertEqual(ledger.next_step().assigned_prime, "thirteenth")
        with self.assertRaises(ValueError):
            ledger.start_step(2)
        ledger.start_step(1)
        with self.assertRaises(ValueError):
            ledger.complete_step(1, " ")
        ledger.block_step(1, "missing hardware target")
        with self.assertRaises(ValueError):
            ledger.start_step(2)
        ledger.resume_step(1)
        ledger.complete_step(1, "hardware target confirmed")
        self.assertEqual(ledger.next_step().step_id, 2)

    def test_hardware_permissions_require_approval(self):
        agents = {agent.agent_id: agent for agent in THIRTEEN_PRIMES_REGISTRY}
        nexus = MegatronusCircuitBreaker(agents["nexus-prime"].permissions)
        megatronus = MegatronusCircuitBreaker(agents["megatronus"].permissions)
        self.assertEqual(nexus.verify_tool_call("shell", "openocd -f board.cfg", "n")[0], PermissionEffect.DENY)
        self.assertEqual(nexus.verify_tool_call("shell", "make all", "build")[0], PermissionEffect.DENY)
        self.assertEqual(megatronus.verify_tool_call("shell", "openocd -f board.cfg", "m")[0], PermissionEffect.ASK)
        self.assertEqual(
            nexus.verify_tool_call("shell", "cmake .; rm -rf build", "chained")[0],
            PermissionEffect.DENY,
        )

    def test_test_and_lint_commands_are_held_until_sandboxed(self):
        agents = {agent.agent_id: agent for agent in THIRTEEN_PRIMES_REGISTRY}
        for agent_id, command in (("alchemist", "pytest -q"),
                                  ("alchemist", "python3 -m pytest"),
                                  ("micronus-prime", "ruff check .")):
            with self.subTest(agent=agent_id, command=command):
                breaker = MegatronusCircuitBreaker(agents[agent_id].permissions)
                self.assertEqual(breaker.verify_tool_call("shell", command, command)[0],
                                 PermissionEffect.DENY)

    def test_agents_cannot_rewrite_their_own_permissions(self):
        for agent in THIRTEEN_PRIMES_REGISTRY:
            breaker = MegatronusCircuitBreaker(agent.permissions)
            for path in ("opencode.jsonc", ".opencode/agents/prima.md",
                         ".dsh/cordis-cybertron-plugin.mjs", ".github/workflows/ci.yml"):
                with self.subTest(agent=agent.agent_id, path=path):
                    self.assertEqual(
                        breaker.verify_tool_call("edit", path, f"{agent.agent_id}:{path}")[0],
                        PermissionEffect.DENY,
                    )

    def test_prima_subagent_access_is_explicit(self):
        prima = next(agent for agent in THIRTEEN_PRIMES_REGISTRY if agent.agent_id == "prima")
        breaker = MegatronusCircuitBreaker(prima.permissions)
        self.assertEqual(breaker.verify_tool_call("subagent", "onyx-prime", "known")[0],
                         PermissionEffect.ALLOW)
        self.assertEqual(breaker.verify_tool_call("subagent", "build", "builtin")[0],
                         PermissionEffect.DENY)

    def test_l2_can_read_project_sources_but_not_env_files(self):
        liege = next(agent for agent in THIRTEEN_PRIMES_REGISTRY
                     if agent.agent_id == "liege-maximo")
        breaker = MegatronusCircuitBreaker(liege.permissions)
        for path in ("cybertron/registry.py", "opencode.jsonc", "README.md",
                     "design/cybertron_13_primes_architecture.md"):
            with self.subTest(path=path):
                self.assertEqual(breaker.verify_tool_call("read", path, path)[0],
                                 PermissionEffect.ALLOW)
        self.assertEqual(breaker.verify_tool_call("read", ".env", "secret")[0],
                         PermissionEffect.DENY)

    def test_local_policy_rejects_path_traversal_and_symlink_escape(self):
        agents = {agent.agent_id: agent for agent in THIRTEEN_PRIMES_REGISTRY}
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as external:
            root = Path(directory)
            (root / "tests").mkdir()
            (root / "src").mkdir()
            outside = Path(external)
            (root / "tests" / "outside").symlink_to(outside, target_is_directory=True)
            cases = (
                ("alchemist", "tests/../cybertron/policy.py"),
                ("solus-prime", "src/../opencode.jsonc"),
                ("alpha-trion", "docs/../opencode.jsonc"),
                ("alchemist", "tests/outside/escape.py"),
                ("alchemist", "/tmp/escape.py"),
                ("alchemist", "tests\\..\\opencode.jsonc"),
            )
            for agent_id, path in cases:
                with self.subTest(agent=agent_id, path=path):
                    breaker = MegatronusCircuitBreaker(agents[agent_id].permissions,
                                                        workspace_root=root)
                    self.assertEqual(breaker.verify_tool_call("edit", path, path)[0],
                                     PermissionEffect.DENY)
            valid = MegatronusCircuitBreaker(agents["alchemist"].permissions,
                                             workspace_root=root)
            self.assertEqual(valid.verify_tool_call("edit", "tests/safe.py", "safe")[0],
                             PermissionEffect.ALLOW)

    def test_feishu_missing_credentials_fail_closed(self):
        config = FeishuWikiGovernanceConfig(
            app_id_env="CYBERTRON_TEST_UNSET_ID",
            app_secret_env="CYBERTRON_TEST_UNSET_SECRET",
        )
        with self.assertRaises(RuntimeError):
            FeishuWikiKnowledgeClient(config).get_tenant_access_token()


if __name__ == "__main__":
    unittest.main()
