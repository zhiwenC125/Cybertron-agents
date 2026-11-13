"""管理飞书租户令牌的获取与缓存；Wiki 正文操作将在阶段 6 接入。"""

from __future__ import annotations
import json
import os
import time
import urllib.request
from dataclasses import dataclass
from typing import Optional

# MODULE 4: Feishu (Lark) Wiki Knowledge Base Governance & Token Manager
# ============================================================================

@dataclass
class FeishuWikiGovernanceConfig:
    """
    Dual-Phase Feishu Knowledge Base Governance:
      - Content & Documentation Steward: ONLY `alpha-trion` reads/writes Feishu Wiki & writes local `AGENTS.md`/`README.md`/`docs/**`.
      - Gateway Operator: ONLY `nexus-prime` manages MCP transport health and token refresh config.
      - Deletion Guard: ONLY `megatronus` can approve Wiki node deletion via human `ask`.
    """
    app_id_env: str = "FEISHU_APP_ID"
    app_secret_env: str = "FEISHU_APP_SECRET"
    wiki_space_id_env: str = "FEISHU_WIKI_SPACE_ID"
    token_mode: str = "tenant_access_token"
    base_url: str = "https://open.feishu.cn/open-apis"
    refresh_safety_margin_sec: int = 300


class FeishuWikiKnowledgeClient:
    """
    Zero-dependency Feishu OpenAPI Client with automatic `tenant_access_token` lifecycle caching.
    """

    def __init__(self, config: Optional[FeishuWikiGovernanceConfig] = None) -> None:
        self.config = config or FeishuWikiGovernanceConfig()
        self._cached_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    def get_tenant_access_token(self, mock_if_unset: bool = False) -> str:
        now = time.time()
        if self._cached_token and now < self._token_expires_at:
            return self._cached_token

        app_id = os.environ.get(self.config.app_id_env, "")
        app_secret = os.environ.get(self.config.app_secret_env, "")
        if not app_id or not app_secret:
            if mock_if_unset:
                self._cached_token = "t-mock_feishu_tenant_token_for_local_verification"
                self._token_expires_at = now + 7200 - self.config.refresh_safety_margin_sec
                return self._cached_token
            raise RuntimeError(
                f"Missing Feishu credentials: please export {self.config.app_id_env} and {self.config.app_secret_env}"
            )

        url = f"{self.config.base_url}/auth/v3/tenant_access_token/internal"
        payload = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("code") != 0:
            raise RuntimeError(f"Feishu auth failed: {data}")

        self._cached_token = str(data["tenant_access_token"])
        expire_sec = int(data.get("expire", 7200))
        self._token_expires_at = now + expire_sec - self.config.refresh_safety_margin_sec
        return self._cached_token
