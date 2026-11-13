"""Explicit live read/write roundtrip in a developer-selected Feishu test space."""

from __future__ import annotations

import argparse
import datetime
import os

from .feishu import FeishuWikiKnowledgeClient


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create one Wiki docx node, append text, and read it back in the configured space"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-env", action="store_true",
                      help="Check required variable names without printing values or using network")
    mode.add_argument("--check-auth", action="store_true",
                      help="Exchange app credentials for a tenant token without creating a Wiki node")
    mode.add_argument("--live", action="store_true",
                      help="Create a test Wiki node, append text, and read it back")
    parser.add_argument("--parent-node-token",
                        help="Optional parent in FEISHU_WIKI_SPACE_ID; must be a docx Wiki node")
    args = parser.parse_args()
    client = FeishuWikiKnowledgeClient()
    required = (client.config.app_id_env, client.config.app_secret_env)
    if not args.check_auth:
        required += (client.config.wiki_space_id_env,)
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        parser.error(
            "Missing required environment variables: " + ", ".join(missing)
            + ". Export them again in this same terminal session; a new terminal does not "
              "inherit earlier exports. Keep the App Secret out of command history."
        )
    if args.check_auth:
        client.get_tenant_access_token()
        print("PASS: Feishu issued a tenant access token; the token was not displayed")
        return
    try:
        client._space_id()  # Validate before any Wiki network call.
    except ValueError:
        parser.error(
            "FEISHU_WIKI_SPACE_ID must contain only the space ID from the Wiki settings URL "
            "(digits only); do not use a node token, full URL, or placeholder text"
        )
    if args.check_env:
        print("PASS: Feishu app credentials are present and space ID format is valid; values were not displayed")
        return

    marker = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    title = f"Cybertron stage 6 acceptance {marker}"
    text = f"Cybertron stage 6 read/write roundtrip {marker}"
    node = client.create_node(title, actor_id="alpha-trion",
                              parent_node_token=args.parent_node_token)
    print(f"CREATED: space={node.space_id} node={node.node_token} document={node.document_id}",
          flush=True)
    result = client.append_text(node.node_token, text, actor_id="alpha-trion")
    if text not in result.content:
        raise RuntimeError("Feishu read-after-write did not contain the test marker")
    print(f"PASS: space={node.space_id} node={node.node_token} document={node.document_id}")
    print("One test document was created and retained for inspection; no deletion was attempted.")


if __name__ == "__main__":
    main()
