"""Every M1 role-directory invariant has a rejecting counterexample."""

import copy
import unittest
from dataclasses import replace

from cybertron.policy import PermissionEffect, PermissionRule
from cybertron.registry import PRIME_ROLES, THIRTEEN_PRIMES_REGISTRY, assert_catalog


class CatalogM1Tests(unittest.TestCase):
    def test_real_catalog(self):
        assert_catalog()

    def reject_role(self, agent_id, **changes):
        roles = dict(PRIME_ROLES)
        roles[agent_id] = replace(roles[agent_id], **changes)
        with self.assertRaises(ValueError):
            assert_catalog(roles)

    def test_only_prima_dispatches(self):
        self.reject_role("solus-prime", can_dispatch=True)
        self.assertEqual(PRIME_ROLES["prima"].read_roots, ())
        specs = copy.deepcopy(THIRTEEN_PRIMES_REGISTRY)
        specs[0].permissions.append(PermissionRule("read", "docs/**", PermissionEffect.ALLOW))
        with self.assertRaises(ValueError):
            assert_catalog(PRIME_ROLES, specs)

    def test_device_external_and_git_write_owners(self):
        self.reject_role("solus-prime", device="broker")
        self.reject_role("solus-prime", external_write=("feishu",))
        self.reject_role("solus-prime", command_mode="git-write")

    def test_implementation_and_test_roots(self):
        self.reject_role("solus-prime", write_roots=("tests/**",))
        self.reject_role("amalgamous", write_roots=("tests/**",))
        self.reject_role("alchemist", write_roots=("src/**",))

    def test_review_and_acceptance_artifact_only(self):
        self.reject_role("micronus-prime", write_roots=("docs/**",))
        self.reject_role("liege-maximo", write_roots=("docs/**",))
        self.reject_role("thirteenth", write_roots=("docs/**",))

    def test_run_state_cannot_be_written(self):
        self.reject_role("alpha-trion", write_roots=(".cybertron/runs/**",))

    def test_writer_and_reviewer_separation(self):
        self.reject_role("solus-prime", capabilities=("code.write", "review.l1"))

    def test_unknown_tool_fails_closed(self):
        self.reject_role("solus-prime", tool_classes=("arbitrary_shell",))
        specs = copy.deepcopy(THIRTEEN_PRIMES_REGISTRY)
        specs[0].permissions.append(PermissionRule("unknown_tool", "*", PermissionEffect.ALLOW))
        with self.assertRaises(ValueError):
            assert_catalog(PRIME_ROLES, specs)

    def test_host_write_root_must_cover_catalog(self):
        self.reject_role("solus-prime", write_roots=("secrets/**",))
        specs = copy.deepcopy(THIRTEEN_PRIMES_REGISTRY)
        specs[1].permissions.append(PermissionRule("edit", ".opencode/agents/prima.md",
                                                 PermissionEffect.ALLOW))
        with self.assertRaises(ValueError):
            assert_catalog(PRIME_ROLES, specs)
        specs[-1].permissions.append(PermissionRule("edit", ".cybertron/runs/**",
                                                  PermissionEffect.ALLOW))
        with self.assertRaises(ValueError):
            assert_catalog(PRIME_ROLES, specs)


if __name__ == "__main__":
    unittest.main()
