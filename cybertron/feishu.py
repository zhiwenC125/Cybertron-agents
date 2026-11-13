"""Feishu Wiki gateway: credential isolation, space binding, and document I/O."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol


@dataclass(frozen=True)
class FeishuWikiGovernanceConfig:
    """Bind every Wiki operation to one explicitly configured space."""

    app_id_env: str = "FEISHU_APP_ID"
    app_secret_env: str = "FEISHU_APP_SECRET"
    wiki_space_id_env: str = "FEISHU_WIKI_SPACE_ID"
    base_url: str = "https://open.feishu.cn/open-apis"
    refresh_safety_margin_sec: int = 300


@dataclass(frozen=True)
class WikiNode:
    space_id: str
    node_token: str
    document_id: str
    title: str


@dataclass(frozen=True)
class WikiDocument:
    node: WikiNode
    content: str


class FeishuTransport(Protocol):
    """Small seam for offline tests; production uses HTTPS without redirects."""

    def request(self, method: str, url: str, payload: Mapping[str, Any] | None,
                token: str | None) -> Mapping[str, Any]: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class HTTPSFeishuTransport:
    """Send JSON requests and keep credentials out of exceptions and logs."""

    def __init__(self, timeout_seconds: int = 10) -> None:
        self.timeout_seconds = timeout_seconds
        self._opener = urllib.request.build_opener(_NoRedirect)

    def request(self, method: str, url: str, payload: Mapping[str, Any] | None,
                token: str | None) -> Mapping[str, Any]:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Feishu often includes a numeric business code in HTTP 400 bodies.
            # Never echo the raw body: it could include request data or tokens.
            try:
                error_payload = json.loads(exc.read(8192).decode("utf-8"))
                business_code = error_payload.get("code") if isinstance(error_payload, dict) else None
            except (UnicodeError, json.JSONDecodeError, OSError):
                error_payload = None
                business_code = None
            detail = (f", Feishu code {business_code}"
                      if type(business_code) is int else "")
            if business_code == 99991672 and isinstance(error_payload, dict):
                error_info = error_payload.get("error")
                violations = error_info.get("permission_violations", []) \
                    if isinstance(error_info, dict) else []
                scopes = sorted({
                    item["subject"] for item in violations
                    if isinstance(item, dict)
                    and isinstance(item.get("subject"), str)
                    and re.fullmatch(r"[A-Za-z0-9:_-]{1,100}", item["subject"])
                }) if isinstance(violations, list) else []
                if scopes:
                    detail += ", acceptable scope(s) (grant one): " + ", ".join(scopes)
            if business_code == 131006 and isinstance(error_payload, dict):
                # Echo only a fixed, documented category. The raw message may
                # contain private node titles or request data.
                message = error_payload.get("msg")
                if isinstance(message, str):
                    normalized = message.lower()
                    categories = (
                        "wiki space permission denied",
                        "node permission denied",
                        "no source parent node permission",
                        "no destination parent node permission",
                    )
                    for category in categories:
                        if category in normalized:
                            detail += f", resource denial: {category}"
                            break
            raise RuntimeError(f"Feishu HTTP request failed: status {exc.code}{detail}") from None
        except (urllib.error.URLError, UnicodeError, json.JSONDecodeError):
            raise RuntimeError("Feishu HTTP request failed") from None
        if not isinstance(result, dict):
            raise RuntimeError("Feishu returned a non-object response")
        return result


class FeishuWikiKnowledgeClient:
    """Only alpha-trion may access Wiki docx content in the configured space."""

    _ID = re.compile(r"^[A-Za-z0-9_-]{3,128}$")

    def __init__(self, config: Optional[FeishuWikiGovernanceConfig] = None,
                 transport: FeishuTransport | None = None) -> None:
        self.config = config or FeishuWikiGovernanceConfig()
        self.transport = transport or HTTPSFeishuTransport()
        self._cached_token: Optional[str] = None
        self._token_expires_at = 0.0
        self._credentials_fingerprint: Optional[str] = None

    @classmethod
    def _identifier(cls, value: str, label: str) -> str:
        if not cls._ID.fullmatch(value):
            raise ValueError(f"Invalid {label}")
        return value

    @staticmethod
    def _require_actor(actor_id: str) -> None:
        if actor_id != "alpha-trion":
            raise PermissionError("Only alpha-trion may access Wiki document content")

    def _space_id(self) -> str:
        value = os.environ.get(self.config.wiki_space_id_env, "")
        if not value:
            raise RuntimeError(f"Missing Feishu Wiki space: {self.config.wiki_space_id_env}")
        if not value.isascii() or not value.isdigit():
            raise ValueError("Wiki space ID must contain only digits")
        return self._identifier(value, "Wiki space ID")

    def _request(self, method: str, path: str,
                 payload: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        token = self.get_access_token()
        result = self.transport.request(method, self.config.base_url.rstrip("/") + path,
                                        payload, token)
        if result.get("code") != 0:
            code = result.get("code")
            safe_code = code if isinstance(code, int) else "unknown"
            raise RuntimeError(f"Feishu API request failed: code {safe_code}")
        data = result.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Feishu API response has no data object")
        return data

    def get_access_token(self) -> str:
        """Get an application identity token without logging or persisting it."""
        return self.get_tenant_access_token()

    def get_tenant_access_token(self, mock_if_unset: bool = False) -> str:
        """Cache real tokens; a local mock token is never cached or used by Wiki I/O."""
        app_id = os.environ.get(self.config.app_id_env, "")
        app_secret = os.environ.get(self.config.app_secret_env, "")
        if not app_id or not app_secret:
            if mock_if_unset:
                return "t-mock_feishu_tenant_token_for_local_verification"
            raise RuntimeError(
                f"Missing Feishu credentials: export {self.config.app_id_env} and "
                f"{self.config.app_secret_env}"
            )
        fingerprint = hashlib.sha256(f"{app_id}|{app_secret}".encode()).hexdigest()
        now = time.time()
        if (self._cached_token and self._credentials_fingerprint == fingerprint
                and now < self._token_expires_at):
            return self._cached_token
        response = self.transport.request(
            "POST", self.config.base_url.rstrip("/") + "/auth/v3/tenant_access_token/internal",
            {"app_id": app_id, "app_secret": app_secret}, None,
        )
        if response.get("code") != 0:
            code = response.get("code")
            safe_code = code if isinstance(code, int) else "unknown"
            raise RuntimeError(f"Feishu authentication failed: code {safe_code}")
        token = response.get("tenant_access_token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("Feishu authentication returned no tenant token")
        try:
            lifetime = int(response.get("expire", 7200))
        except (TypeError, ValueError):
            raise RuntimeError("Feishu authentication returned invalid token lifetime") from None
        self._cached_token = token
        self._credentials_fingerprint = fingerprint
        self._token_expires_at = now + max(0, lifetime - self.config.refresh_safety_margin_sec)
        return token

    def _parse_node(self, data: Mapping[str, Any], expected_space: str) -> WikiNode:
        raw = data.get("node")
        if not isinstance(raw, dict) or str(raw.get("space_id")) != expected_space:
            raise PermissionError("Wiki node is outside the configured space")
        if raw.get("obj_type") != "docx":
            raise ValueError("Only docx Wiki nodes are supported")
        return WikiNode(
            expected_space,
            self._identifier(str(raw.get("node_token", "")), "node token"),
            self._identifier(str(raw.get("obj_token", "")), "document ID"),
            str(raw.get("title", "")),
        )

    def get_node(self, node_token: str, *, actor_id: str) -> WikiNode:
        self._require_actor(actor_id)
        space_id = self._space_id()
        token = self._identifier(node_token, "node token")
        query = urllib.parse.urlencode({"token": token})
        data = self._request("GET", f"/wiki/v2/spaces/node_by_token?{query}")
        return self._parse_node(data, space_id)

    def read_node(self, node_token: str, *, actor_id: str) -> WikiDocument:
        node = self.get_node(node_token, actor_id=actor_id)
        data = self._request("GET", f"/docx/v1/documents/{node.document_id}/raw_content")
        content = data.get("content")
        if not isinstance(content, str):
            raise RuntimeError("Feishu document response has no plain-text content")
        return WikiDocument(node, content)

    def create_node(self, title: str, *, actor_id: str,
                    parent_node_token: str | None = None) -> WikiNode:
        self._require_actor(actor_id)
        space_id = self._space_id()
        if not title.strip() or len(title) > 255:
            raise ValueError("Wiki title must contain 1–255 characters")
        payload: dict[str, Any] = {"obj_type": "docx", "node_type": "origin", "title": title}
        if parent_node_token is not None:
            parent = self.get_node(parent_node_token, actor_id=actor_id)
            payload["parent_node_token"] = parent.node_token
        data = self._request("POST", f"/wiki/v2/spaces/{space_id}/nodes", payload)
        raw = data.get("node")
        if not isinstance(raw, dict):
            raise RuntimeError("Feishu node creation returned no node")
        # Re-read the created node: responses may omit metadata needed to verify
        # the space and the docx object token.
        return self.get_node(self._identifier(str(raw.get("node_token", "")), "node token"),
                             actor_id=actor_id)

    def append_text(self, node_token: str, text: str, *, actor_id: str) -> WikiDocument:
        """Append a text block without replacing existing content or the page title."""
        self._require_actor(actor_id)
        if not text.strip():
            raise ValueError("Text to append cannot be empty")
        node = self.get_node(node_token, actor_id=actor_id)
        self._request(
            "POST", f"/docx/v1/documents/{node.document_id}/blocks/{node.document_id}/children",
            {"children": [{"block_type": 2, "text": {
                "elements": [{"text_run": {"content": text}}],
            }}], "index": -1},
        )
        return self.read_node(node_token, actor_id=actor_id)
