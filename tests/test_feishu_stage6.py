"""Offline contract tests for the stage 6 Wiki gateway."""

import os
import json
import tempfile
import io
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cybertron.feishu import (FeishuWikiGovernanceConfig, FeishuWikiKnowledgeClient,
                              HTTPSFeishuTransport)
from cybertron.exporters import compile_opencode_v2_assets
from cybertron.policy import MegatronusCircuitBreaker, PermissionEffect
from cybertron.registry import THIRTEEN_PRIMES_REGISTRY
from cybertron.stage6_verify import main as stage6_main


class FakeFeishuTransport:
    def __init__(self):
        self.calls = []
        self.content = {}
        self.nodes = {}
        self.next_node = 1
        self.outside_space = False

    def request(self, method, url, payload, token):
        self.calls.append((method, url, payload, token))
        if url.endswith("/auth/v3/tenant_access_token/internal"):
            return {"code": 0, "tenant_access_token": "tenant-token", "expire": 7200}
        if "/wiki/v2/spaces/7000000000000000001/nodes" in url and method == "POST":
            node_token = f"node{self.next_node}"
            document_id = f"doc{self.next_node}"
            self.next_node += 1
            node = {"space_id": 7000000000000000001, "node_token": node_token,
                    "obj_token": document_id, "obj_type": "docx", "title": payload["title"]}
            self.nodes[node_token] = node
            self.content[document_id] = ""
            return {"code": 0, "data": {"node": node}}
        if "/wiki/v2/spaces/node_by_token?token=" in url:
            node_token = url.split("token=", 1)[1]
            node = dict(self.nodes[node_token])
            if self.outside_space:
                node["space_id"] = "other-space"
            return {"code": 0, "data": {"node": node}}
        if url.endswith("/raw_content"):
            document_id = url.split("/documents/", 1)[1].split("/", 1)[0]
            return {"code": 0, "data": {"content": self.content[document_id]}}
        if url.endswith("/children") and method == "POST":
            document_id = url.split("/documents/", 1)[1].split("/", 1)[0]
            self.content[document_id] += payload["children"][0]["text"]["elements"][0]["text_run"]["content"]
            return {"code": 0, "data": {"children": [{"block_id": "block1"}]}}
        raise AssertionError(f"Unexpected request: {method} {url}")


class Stage6FeishuTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "CYBERTRON_TEST_FEISHU_ID": "cli-test",
            "CYBERTRON_TEST_FEISHU_SECRET": "secret-not-for-output",
            "CYBERTRON_TEST_FEISHU_SPACE": "7000000000000000001",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.transport = FakeFeishuTransport()
        config = FeishuWikiGovernanceConfig(
            app_id_env="CYBERTRON_TEST_FEISHU_ID",
            app_secret_env="CYBERTRON_TEST_FEISHU_SECRET",
            wiki_space_id_env="CYBERTRON_TEST_FEISHU_SPACE",
        )
        self.client = FeishuWikiKnowledgeClient(config, self.transport)

    def test_create_append_read_roundtrip_and_token_cache(self):
        node = self.client.create_node("Stage 6 test", actor_id="alpha-trion")
        result = self.client.append_text(node.node_token, "Hello Wiki", actor_id="alpha-trion")
        self.assertIn("Hello Wiki", result.content)
        self.assertEqual(result.node.document_id, node.document_id)
        self.assertEqual(sum("/auth/v3/" in call[1] for call in self.transport.calls), 1)
        self.assertEqual(self.transport.calls[-1][3], "tenant-token")

    def test_user_token_does_not_replace_missing_app_credentials(self):
        with patch.dict(os.environ, {
            "CYBERTRON_TEST_FEISHU_SECRET": "",
            "FEISHU_USER_ACCESS_TOKEN": "user-token-not-for-output",
        }):
            with self.assertRaisesRegex(RuntimeError, "Missing Feishu credentials"):
                self.client.create_node("No", actor_id="alpha-trion")
        self.assertEqual(self.transport.calls, [])

    def test_other_roles_rejected_before_network(self):
        for actor in ("prima", "nexus-prime", "megatronus"):
            with self.subTest(actor=actor):
                with self.assertRaises(PermissionError):
                    self.client.create_node("No", actor_id=actor)
                with self.assertRaises(PermissionError):
                    self.client.read_node("node1", actor_id=actor)
                with self.assertRaises(PermissionError):
                    self.client.append_text("node1", "No", actor_id=actor)
        self.assertEqual(self.transport.calls, [])

    def test_missing_credentials_fail_even_after_cached_token(self):
        self.client.get_tenant_access_token()
        with patch.dict(os.environ, {"CYBERTRON_TEST_FEISHU_SECRET": ""}):
            with self.assertRaisesRegex(RuntimeError, "Missing Feishu credentials"):
                self.client.get_tenant_access_token()

    def test_mock_token_never_enters_real_io_cache(self):
        with patch.dict(os.environ, {"CYBERTRON_TEST_FEISHU_SECRET": ""}):
            self.assertTrue(self.client.get_tenant_access_token(mock_if_unset=True).startswith("t-mock"))
            with self.assertRaisesRegex(RuntimeError, "Missing Feishu credentials"):
                self.client.create_node("No", actor_id="alpha-trion")
        self.assertEqual(self.transport.calls, [])

    def test_outside_space_is_rejected_before_docx_access(self):
        node = self.client.create_node("Test", actor_id="alpha-trion")
        self.transport.outside_space = True
        with self.assertRaisesRegex(PermissionError, "outside"):
            self.client.append_text(node.node_token, "No", actor_id="alpha-trion")
        self.assertFalse(any("/children" in url for _, url, _, _ in self.transport.calls))

    def test_path_injection_rejected_before_network(self):
        with self.assertRaises(ValueError):
            self.client.get_node("../other", actor_id="alpha-trion")
        self.assertEqual(self.transport.calls, [])

    def test_auth_error_does_not_echo_secret_or_response_body(self):
        class RejectingTransport:
            def request(self, method, url, payload, token):
                return {"code": 9999, "msg": "secret-not-for-output"}

        client = FeishuWikiKnowledgeClient(self.client.config, RejectingTransport())
        with self.assertRaisesRegex(RuntimeError, "code 9999") as caught:
            client.create_node("Test", actor_id="alpha-trion")
        self.assertNotIn("secret-not-for-output", str(caught.exception))

    def test_only_alpha_has_exact_mcp_read_permission(self):
        for action in ("feishu_wiki_wiki_v2_space_getNode",
                       "feishu_wiki_docx_v1_document_rawContent"):
            for spec in THIRTEEN_PRIMES_REGISTRY:
                effect, _ = MegatronusCircuitBreaker(spec.permissions).verify_tool_call(
                    action, "*", f"stage6:{action}:{spec.agent_id}"
                )
                expected = PermissionEffect.ALLOW if spec.agent_id == "alpha-trion" else PermissionEffect.DENY
                self.assertEqual(effect, expected, f"{spec.agent_id}: {action}")

    def test_optional_mcp_exports_only_two_read_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            compile_opencode_v2_assets(Path(directory), include_feishu=True)
            config = json.loads((Path(directory) / "opencode.jsonc").read_text())
        command = config["mcp"]["servers"]["feishu_wiki"]["command"]
        self.assertFalse(config["mcp"]["servers"]["feishu_wiki"]["codemode"])
        self.assertEqual(command[command.index("-t") + 1],
                         "wiki.v2.space.getNode,docx.v1.document.rawContent")
        self.assertEqual(command[command.index("--token-mode") + 1], "tenant_access_token")
        self.assertNotIn("-u", command)
        self.assertNotIn("FEISHU_USER_ACCESS_TOKEN", str(config))
        self.assertIn("{env:FEISHU_APP_SECRET}", command)
        self.assertNotIn("secret-not-for-output", str(config))

    def test_cli_env_check_does_not_print_secret_or_call_network(self):
        output = io.StringIO()
        with patch.dict(os.environ, {
            "FEISHU_APP_ID": "cli-test",
            "FEISHU_APP_SECRET": "secret-not-for-output",
            "FEISHU_WIKI_SPACE_ID": "7000000000000000001",
        }), patch("sys.argv", ["stage6_verify", "--check-env"]), \
                patch("cybertron.feishu.HTTPSFeishuTransport.request",
                      side_effect=AssertionError("network call")), redirect_stdout(output):
            stage6_main()
        self.assertIn("PASS", output.getvalue())
        self.assertNotIn("secret-not-for-output", output.getvalue())

    def test_cli_invalid_space_id_has_actionable_error_without_leak(self):
        errors = io.StringIO()
        with patch.dict(os.environ, {
            "FEISHU_APP_ID": "cli-test",
            "FEISHU_APP_SECRET": "secret-not-for-output",
            "FEISHU_WIKI_SPACE_ID": "https://tenant.feishu.cn/wiki/settings/123456",
        }), patch("sys.argv", ["stage6_verify", "--check-env"]), redirect_stderr(errors):
            with self.assertRaises(SystemExit) as caught:
                stage6_main()
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("space ID from the Wiki settings URL", errors.getvalue())
        self.assertNotIn("tenant.feishu.cn", errors.getvalue())
        self.assertNotIn("secret-not-for-output", errors.getvalue())

    def test_cli_auth_check_does_not_require_space_id(self):
        output = io.StringIO()
        with patch.dict(os.environ, {
            "FEISHU_APP_ID": "cli-test",
            "FEISHU_APP_SECRET": "secret-not-for-output",
            "FEISHU_WIKI_SPACE_ID": "not a valid ID",
        }), patch("sys.argv", ["stage6_verify", "--check-auth"]), \
                patch("cybertron.feishu.HTTPSFeishuTransport.request",
                      return_value={"code": 0, "tenant_access_token": "tenant-token", "expire": 7200}) as request, \
                redirect_stdout(output):
            stage6_main()
        self.assertIn("PASS", output.getvalue())
        self.assertNotIn("tenant-token", output.getvalue())
        self.assertIsNone(request.call_args.args[3])
        self.assertTrue(request.call_args.args[1].endswith("/auth/v3/tenant_access_token/internal"))

    def test_cli_live_roundtrip_uses_tenant_identity(self):
        output = io.StringIO()
        transport = FakeFeishuTransport()
        with patch.dict(os.environ, {
            "FEISHU_USER_ACCESS_TOKEN": "ignored-user-token",
            "FEISHU_WIKI_SPACE_ID": "7000000000000000001",
            "FEISHU_APP_ID": "cli-test", "FEISHU_APP_SECRET": "secret-not-for-output",
        }), patch("sys.argv", ["stage6_verify", "--live"]), \
                patch("cybertron.feishu.HTTPSFeishuTransport", return_value=transport), \
                redirect_stdout(output):
            stage6_main()
        self.assertIn("CREATED:", output.getvalue())
        self.assertIn("PASS:", output.getvalue())
        self.assertNotIn("secret-not-for-output", output.getvalue())
        self.assertNotIn("tenant-token", output.getvalue())
        self.assertEqual(sum("/auth/v3/" in url for _, url, _, _ in transport.calls), 1)
        self.assertTrue(all(token == "tenant-token"
                            for _, url, _, token in transport.calls if "/auth/v3/" not in url))

    def test_http_400_reports_business_code_without_raw_body(self):
        transport = HTTPSFeishuTransport()
        error = urllib.error.HTTPError(
            "https://open.feishu.cn/open-apis/wiki/v2/spaces/7000000000000000001/nodes",
            400, "Bad Request", {},
            io.BytesIO(b'{"code":99991672,"msg":"secret-not-for-output",'
                       b'"error":{"permission_violations":['
                       b'{"subject":"wiki:node:create"},'
                       b'{"subject":"secret-not-for-output/unsafe"}]}}'),
        )
        with patch.object(transport._opener, "open", side_effect=error):
            with self.assertRaisesRegex(RuntimeError,
                                        "status 400, Feishu code 99991672, acceptable scope") as caught:
                transport.request("POST", error.url, {"title": "test"}, "tenant-token")
        self.assertIn("wiki:node:create", str(caught.exception))
        self.assertNotIn("secret-not-for-output", str(caught.exception))

    def test_resource_denial_reports_only_documented_category(self):
        transport = HTTPSFeishuTransport()
        url = "https://open.feishu.cn/open-apis/wiki/v2/spaces/7000000000000000001/nodes"
        for message, category in (
            ("permission denied: wiki space permission denied", "wiki space permission denied"),
            ("permission denied: node permission denied", "node permission denied"),
            ("permission denied: no destination parent node permission",
             "no destination parent node permission"),
            ("secret-not-for-output", None),
        ):
            with self.subTest(message=message):
                error = urllib.error.HTTPError(
                    url, 400, "Bad Request", {},
                    io.BytesIO(json.dumps({"code": 131006, "msg": message}).encode()),
                )
                with patch.object(transport._opener, "open", side_effect=error):
                    with self.assertRaisesRegex(RuntimeError, "Feishu code 131006") as caught:
                        transport.request("POST", url, {"title": "test"}, "tenant-token")
                self.assertNotIn("secret-not-for-output", str(caught.exception))
                if category:
                    self.assertIn(f"resource denial: {category}", str(caught.exception))
                else:
                    self.assertNotIn("resource denial:", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
