import json
import unittest

from cybertron.authority import (ROLE_AUTHORITY, assert_authority, can_escalate,
                                 denied_for_reviewer, snapshot)
from cybertron.exporters import shell_policy_module
from cybertron.registry import THIRTEEN_PRIMES_REGISTRY


class AuthorityTests(unittest.TestCase):
    def test_matrix_covers_all_roles(self):
        assert_authority()
        self.assertEqual(set(ROLE_AUTHORITY),
                         {prime.agent_id for prime in THIRTEEN_PRIMES_REGISTRY})
        self.assertEqual(len(snapshot()["roles"]), 13)

    def test_escalation_ceilings(self):
        self.assertTrue(can_escalate("vector-prime", "vcs.push"))
        self.assertTrue(can_escalate("megatronus", "device"))
        self.assertFalse(can_escalate("prima", "vcs.push"))
        self.assertFalse(can_escalate("solus-prime", "device"))
        self.assertFalse(can_escalate("liege-maximo", "vcs.write"))

    def test_reviewer_deny_list(self):
        for path in (".env", ".env.local", ".ssh/id_rsa", ".git/config",
                     "secrets/db.txt", "certs/client.pem"):
            with self.subTest(path=path):
                self.assertTrue(denied_for_reviewer(path))
        for path in ("src/app.py", "services/auth/a.py", "docs/README.md"):
            with self.subTest(path=path):
                self.assertFalse(denied_for_reviewer(path))

    def test_vector_owns_git_write_in_shell_policy(self):
        policy = json.loads(shell_policy_module().split("export default ", 1)[1].rstrip(";\n"))
        asks = policy["roles"]["vector-prime"]["ask"]
        self.assertIn("git commit *", asks)
        self.assertIn("git push *", asks)
        self.assertNotIn("git commit *", policy["roles"].get("nexus-prime", {}).get("ask", []))


if __name__ == "__main__":
    unittest.main()
