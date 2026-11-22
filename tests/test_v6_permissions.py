import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from cybertron.exporters import compile_opencode_v2_assets, shell_policy_module
from cybertron.policy import MegatronusCircuitBreaker, PermissionEffect
from cybertron.registry import PRIME_ROLES, THIRTEEN_PRIMES_REGISTRY


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
            generated = root / "cybertron" / "payload" / "plugins" / name
            with self.subTest(path=str(generated)):
                self.assertEqual(generated.read_bytes(), source)

    def test_shell_policy_module_matches_registry(self):
        root = Path(__file__).resolve().parent.parent
        expected = shell_policy_module()
        for path in (root / "cybertron" / "v6_plugin" / "shell_policy.mjs",
                     root / "cybertron" / "payload" / "plugins" / "shell_policy.mjs"):
            with self.subTest(path=str(path)):
                self.assertEqual(path.read_text(), expected)

    def test_only_prima_can_start_native_subagents(self):
        for agent in THIRTEEN_PRIMES_REGISTRY:
            breaker = MegatronusCircuitBreaker(agent.permissions)
            effect, _ = breaker.verify_tool_call("subagent", "alpha-trion", agent.agent_id)
            self.assertEqual(effect, PermissionEffect.ALLOW if agent.agent_id == "prima" else PermissionEffect.DENY)

    def test_prima_dispatches_but_does_not_author_plans(self):
        prima = THIRTEEN_PRIMES_REGISTRY[0]
        breaker = MegatronusCircuitBreaker(prima.permissions)
        for tool in ("cy_state", "cy_ask", "cy_templates", "cy_metrics",
                     "cy_runs", "cy_resume"):
            with self.subTest(tool=tool):
                self.assertEqual(breaker.verify_tool_call(tool, "*", tool)[0],
                                 PermissionEffect.ALLOW)
        self.assertEqual(breaker.verify_tool_call("cy_plan", "*", "plan")[0],
                         PermissionEffect.DENY)
        self.assertEqual(breaker.verify_tool_call(
            "cybertron_run", "*", "legacy")[0], PermissionEffect.DENY)

    def test_model_roles_do_not_call_plan_review(self):
        for agent in THIRTEEN_PRIMES_REGISTRY:
            with self.subTest(agent=agent.agent_id):
                effect, _ = MegatronusCircuitBreaker(agent.permissions).verify_tool_call(
                    "cy_plan_review", "*", agent.agent_id)
                self.assertEqual(effect, PermissionEffect.DENY)

    def test_thirteenth_owns_the_plan(self):
        thirteenth = next(agent for agent in THIRTEEN_PRIMES_REGISTRY
                          if agent.agent_id == "thirteenth")
        breaker = MegatronusCircuitBreaker(thirteenth.permissions)
        for tool in ("cy_plan", "cy_state", "cy_templates", "question"):
            with self.subTest(tool=tool):
                self.assertEqual(breaker.verify_tool_call(tool, "*", tool)[0],
                                 PermissionEffect.ALLOW)
        self.assertEqual(breaker.verify_tool_call("subagent", "onyx-prime", "dispatch")[0],
                         PermissionEffect.DENY)
        self.assertEqual(breaker.verify_tool_call("shell", "git push", "push")[0],
                         PermissionEffect.DENY)

    def test_learning_tools_follow_the_planner_dispatcher_split(self):
        for agent in THIRTEEN_PRIMES_REGISTRY:
            templates = MegatronusCircuitBreaker(agent.permissions).verify_tool_call(
                "cy_templates", "*", agent.agent_id)[0]
            metrics = MegatronusCircuitBreaker(agent.permissions).verify_tool_call(
                "cy_metrics", "*", agent.agent_id)[0]
            with self.subTest(agent=agent.agent_id):
                self.assertEqual(templates, PermissionEffect.ALLOW
                                 if agent.agent_id in {"prima", "thirteenth"}
                                 else PermissionEffect.DENY)
                self.assertEqual(metrics, PermissionEffect.ALLOW
                                 if agent.agent_id == "prima"
                                 else PermissionEffect.DENY)

    def test_prima_human_confirmation_requires_host_decision(self):
        prima = THIRTEEN_PRIMES_REGISTRY[0]
        breaker = MegatronusCircuitBreaker(prima.permissions)
        self.assertEqual(breaker.verify_tool_call(
            "cy_ask_decision", "Confirm?", "ask")[0], PermissionEffect.ASK)
        self.assertEqual(breaker.verify_tool_call(
            "question", "*", "question")[0], PermissionEffect.ALLOW)
        for role in THIRTEEN_PRIMES_REGISTRY:
            effect, _ = MegatronusCircuitBreaker(role.permissions).verify_tool_call(
                "cy_full_access_decision", "*", role.agent_id)
            self.assertEqual(effect, PermissionEffect.ASK
                             if role.agent_id in {"prima", "thirteenth"}
                             else PermissionEffect.DENY)

    def test_cy_check_is_granted_only_to_isolated_check_roles(self):
        allowed = {"quintus-prime", "micronus-prime", "nexus-prime", "alchemist"}
        for agent in THIRTEEN_PRIMES_REGISTRY:
            with self.subTest(agent=agent.agent_id):
                effect, _ = MegatronusCircuitBreaker(agent.permissions).verify_tool_call(
                    "cy_check", "*", agent.agent_id)
                self.assertEqual(effect, PermissionEffect.ALLOW if agent.agent_id in allowed
                                 else PermissionEffect.DENY)

    def test_only_l2_reviewer_can_record_rejection(self):
        for agent in THIRTEEN_PRIMES_REGISTRY:
            with self.subTest(agent=agent.agent_id):
                effect, _ = MegatronusCircuitBreaker(agent.permissions).verify_tool_call(
                    "cy_review_reject", "*", agent.agent_id)
                self.assertEqual(effect, PermissionEffect.ALLOW if agent.agent_id == "liege-maximo"
                                 else PermissionEffect.DENY)

    def test_alpha_can_write_root_notes_but_not_role_config(self):
        alpha = next(agent for agent in THIRTEEN_PRIMES_REGISTRY if agent.agent_id == "alpha-trion")
        breaker = MegatronusCircuitBreaker(alpha.permissions)
        self.assertEqual(breaker.verify_tool_call("edit", "notes.md", "notes")[0], PermissionEffect.ALLOW)
        self.assertEqual(breaker.verify_tool_call("edit", ".opencode/agents/prima.md", "agent")[0],
                         PermissionEffect.DENY)

    def test_l2_reviewer_can_read_every_code_and_build_input(self):
        liege = next(agent for agent in THIRTEEN_PRIMES_REGISTRY
                     if agent.agent_id == "liege-maximo")
        breaker = MegatronusCircuitBreaker(liege.permissions)
        for path in ("include/hal_uart.h", "app/main.py", "lib/core.c", "bsp/board.c",
                     "CMakeLists.txt", "platformio.ini", "links/flash.ld",
                     "boards/stm32.dts", "Dockerfile", "pyproject.toml",
                     ".github/workflows/ci.yml", "scripts/build.sh"):
            with self.subTest(path=path):
                self.assertEqual(breaker.verify_tool_call("read", path, path)[0],
                                 PermissionEffect.ALLOW)
        self.assertEqual(breaker.verify_tool_call("read", ".ssh/id_rsa", "secret")[0],
                         PermissionEffect.DENY)

    def test_alchemist_can_write_tests_and_simulation_assets(self):
        alchemist = next(agent for agent in THIRTEEN_PRIMES_REGISTRY
                         if agent.agent_id == "alchemist")
        breaker = MegatronusCircuitBreaker(alchemist.permissions)
        for path in ("tests/test_core.py", "sim/quadrotor.py", "sim.resc", "sim.expect"):
            with self.subTest(path=path):
                self.assertEqual(breaker.verify_tool_call("edit", path, path)[0],
                                 PermissionEffect.ALLOW)
        self.assertEqual(breaker.verify_tool_call("edit", "src/main.py", "code")[0],
                         PermissionEffect.DENY)

    def test_quintus_can_write_design_artifacts_but_not_kernel_run_state(self):
        quintus = next(agent for agent in THIRTEEN_PRIMES_REGISTRY
                       if agent.agent_id == "quintus-prime")
        breaker = MegatronusCircuitBreaker(quintus.permissions)
        self.assertEqual(breaker.verify_tool_call(
            "edit", ".cybertron/plans/dma.md", "design")[0], PermissionEffect.ALLOW)
        self.assertEqual(breaker.verify_tool_call(
            "edit", ".cybertron/runs/run/plan.json", "kernel")[0], PermissionEffect.DENY)
        self.assertIn(".cybertron/plans/**", PRIME_ROLES["quintus-prime"].write_roots)

    def test_read_only_analysts_can_discover_files(self):
        for agent_id in ("onyx-prime", "alpha-trion", "micronus-prime",
                         "quintus-prime", "liege-maximo"):
            agent = next(agent for agent in THIRTEEN_PRIMES_REGISTRY
                         if agent.agent_id == agent_id)
            with self.subTest(agent=agent_id):
                self.assertEqual(MegatronusCircuitBreaker(agent.permissions).verify_tool_call(
                    "glob", "*", agent_id)[0], PermissionEffect.ALLOW)

    def test_acceptance_officer_can_ask_the_human(self):
        thirteenth = next(agent for agent in THIRTEEN_PRIMES_REGISTRY
                          if agent.agent_id == "thirteenth")
        self.assertEqual(MegatronusCircuitBreaker(thirteenth.permissions).verify_tool_call(
            "question", "*", "clarify")[0], PermissionEffect.ALLOW)

    def test_shell_allow_lists_keep_roles_inside_their_charter(self):
        cases = {
            "vector-prime": [
                ("git show HEAD", PermissionEffect.ALLOW),
                ("git blame src/main.c", PermissionEffect.ALLOW),
                ("git push", PermissionEffect.DENY),
                ("git log --output=/tmp/x", PermissionEffect.DENY),
            ],
            "micronus-prime": [
                ("ruff check src", PermissionEffect.ALLOW),
                ("ruff check --fix src", PermissionEffect.DENY),
            ],
            "alchemist": [
                ("pytest tests", PermissionEffect.ALLOW),
                ("python3 -m unittest discover -s tests", PermissionEffect.ALLOW),
                ("rm -rf /", PermissionEffect.DENY),
            ],
            "nexus-prime": [
                ("cmake -S . -B build", PermissionEffect.ALLOW),
                ("pio run -t upload", PermissionEffect.ASK),
                ("openocd -f board.cfg", PermissionEffect.ASK),
                ("ssh board.local", PermissionEffect.ASK),
            ],
            "megatronus": [
                ("cat /dev/ttyACM0", PermissionEffect.DENY),
                ("openocd -f board.cfg", PermissionEffect.DENY),
                ("ssh board.local", PermissionEffect.DENY),
            ],
            "solus-prime": [
                ("clang-format -i src/main.c", PermissionEffect.ALLOW),
                ("git push", PermissionEffect.DENY),
            ],
            "amalgamous": [
                ("cargo fmt --all", PermissionEffect.DENY),
                ("openocd -f board.cfg", PermissionEffect.DENY),
            ],
        }
        for agent_id, commands in cases.items():
            agent = next(item for item in THIRTEEN_PRIMES_REGISTRY
                         if item.agent_id == agent_id)
            breaker = MegatronusCircuitBreaker(agent.permissions)
            for command, expected in commands:
                with self.subTest(agent=agent_id, command=command):
                    self.assertEqual(
                        breaker.verify_tool_call("shell", command, command)[0], expected)
