import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from cybertron.profiles import CheckRejected, detect_profile, run_check


class ProfilesV6Tests(unittest.TestCase):
    @unittest.skipIf(os.environ.get("CYBERTRON_SANDBOX") == "1",
                     "nested sandbox-exec is unsupported; run the host toolchain gate separately")
    def test_real_c_lint_and_build_are_isolated_and_receipted(self):
        with tempfile.TemporaryDirectory(prefix="cybertron-m2-test-") as directory:
            project = Path(directory)
            (project / "CMakeLists.txt").write_text(
                "cmake_minimum_required(VERSION 3.20)\nproject(hello C)\n"
                "add_executable(hello main.c)\n")
            (project / "main.c").write_text(
                '#include <stdio.h>\nint main(void){puts("hello");return 0;}\n')
            for target, binary in (("lint", "clang-tidy"), ("build", "cmake")):
                with self.subTest(target=target):
                    result = run_check(project, target)
                    self.assertEqual(result["status"], "pass")
                    self.assertIn(binary, result["receipts"][-1]["command"])
                    self.assertTrue(all(item["source"] == "sandbox" and item["exit"] == 0
                                        and item["sha256"] == hashlib.sha256(item["output"].encode()).hexdigest()
                                        for item in result["receipts"]))
            self.assertEqual({path.name for path in project.iterdir()}, {"CMakeLists.txt", "main.c"})

    def test_arbitrary_target_and_symlink_source_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="cybertron-m2-test-") as directory:
            project = Path(directory)
            (project / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)\n")
            with self.assertRaises(CheckRejected):
                run_check(project, "shell")
            (project / "main.c").symlink_to("/etc/passwd")
            with self.assertRaises(CheckRejected):
                run_check(project, "lint")

    def test_arm_project_uses_cross_compile_profile(self):
        with tempfile.TemporaryDirectory(prefix="cybertron-m2-test-") as directory:
            project = Path(directory)
            (project / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)\n")
            self.assertEqual(detect_profile(project), "cmake-c")
            (project / "board.ioc").write_text("# board config\n")
            self.assertEqual(detect_profile(project), "cmake-arm")

    @unittest.skipIf(os.environ.get("CYBERTRON_SANDBOX") == "1",
                     "nested sandbox-exec is unsupported; run the host toolchain gate separately")
    @unittest.skipUnless(shutil.which("renode"), "Renode is not installed")
    def test_real_renode_sim_receipt_for_heartbeat_fixture(self):
        fixture = Path(__file__).resolve().parent.parent / "stage7_fixture" / "stm32_minimal"
        if not (fixture / "build" / "heartbeat.elf").is_file():
            self.skipTest("heartbeat.elf has not been built")
        result = run_check(fixture, "sim")
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["profile"], "renode")
        receipt = result["receipts"][-1]
        self.assertIn("renode", receipt["command"])
        self.assertEqual(receipt["source"], "sandbox")
        self.assertEqual(receipt["exit"], 0)
        self.assertIn("CYBERTRON_SIM_PASS marker=C7B70001", receipt["output"])
        self.assertEqual(receipt["sha256"], hashlib.sha256(receipt["output"].encode()).hexdigest())
        self.assertEqual({path.name for path in fixture.iterdir()},
                         {"README.md", "app.ld", "build", "heartbeat.s", "sim.resc", "sim.expect"})

    def test_sim_target_requires_script_and_expectation(self):
        with tempfile.TemporaryDirectory(prefix="cybertron-m4-test-") as directory:
            project = Path(directory)
            (project / "sim.resc").write_text("echo hello\n")
            with self.assertRaises(CheckRejected):
                run_check(project, "sim")
            (project / "sim.expect").write_text("hello\n")
            self.assertEqual(detect_profile(project), "renode")

    @unittest.skipIf(os.environ.get("CYBERTRON_SANDBOX") == "1",
                     "nested sandbox-exec is unsupported; run the host toolchain gate separately")
    def test_zero_test_project_cannot_pass_test_gate(self):
        with tempfile.TemporaryDirectory(prefix="cybertron-m2-test-") as directory:
            project = Path(directory)
            (project / "pyproject.toml").write_text("[build-system]\nrequires = []\n")
            (project / "tests").mkdir()
            result = run_check(project, "test")
            self.assertEqual(result["status"], "fail")
            self.assertIn("Ran 0 tests", result["receipts"][-1]["output"])


if __name__ == "__main__":
    unittest.main()
