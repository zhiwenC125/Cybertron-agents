"""Approval and idempotency fence for operations that may have side effects.

This module records plans and receipts. It never powers a device, writes Feishu,
flashes firmware, or launches a host tool itself.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Callable

from .runstore import RunStore, RunStoreError, _digest


SHA256 = re.compile(r"^[a-f0-9]{64}$")
SIDE_EFFECT_KINDS = {"flash", "power_on", "remote_deploy", "feishu_write"}


class ApprovalRequired(RunStoreError):
    pass


class OutcomeUnknown(RunStoreError):
    pass


def _timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


class SideEffectGuard:
    def __init__(self, store: RunStore,
                 verify_approval: Callable[[dict], bool] | None = None,
                 verify_tool_receipt: Callable[[dict], bool] | None = None) -> None:
        self.store = store
        self.verify_approval = verify_approval
        self.verify_tool_receipt = verify_tool_receipt

    def _events(self, run_id: str) -> list[dict]:
        directory, metadata = self.store._locate(run_id)
        self.store._replay(directory, metadata)
        return [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]

    def _plan(self, run_id: str, plan_id: str) -> dict:
        matches = [event["payload"] for event in self._events(run_id)
                   if event["type"] == "operation.planned" and event["payload"].get("plan_id") == plan_id]
        if len(matches) != 1:
            raise RunStoreError("Operation plan not found or ambiguous")
        return matches[0]

    def plan(self, run_id: str, *, kind: str, target_id: str, action: str,
             firmware_sha256: str = "", erase_ranges: tuple[str, ...] = (),
             rollback_sha256: str = "", scope: str = "") -> dict:
        if kind not in SIDE_EFFECT_KINDS or not target_id.strip() or not action.strip() or not scope.strip():
            raise ValueError("Operation kind, target, action, and scope are required")
        if kind != "feishu_write" and (
            not SHA256.fullmatch(firmware_sha256) or not SHA256.fullmatch(rollback_sha256)
            or not erase_ranges or not all(value.strip() for value in erase_ranges)
        ):
            raise ValueError("Hardware plans require firmware, erase range, and rollback digests")
        if kind == "feishu_write" and (firmware_sha256 or erase_ranges or rollback_sha256):
            raise ValueError("Feishu write plans cannot contain firmware fields")
        plan_id = str(uuid.uuid4())
        core = {
            "kind": kind,
            "target_id": target_id,
            "action": action,
            "firmware_sha256": firmware_sha256,
            "erase_ranges": list(erase_ranges),
            "rollback_sha256": rollback_sha256,
            "scope": scope,
        }
        payload = {
            "plan_id": plan_id,
            "plan_sha256": _digest(core),
            "idempotency_key": str(uuid.uuid4()),
            **core,
        }
        self.store.transition(run_id, "operation.planned", lambda ledger: None,
                              payload=payload)
        return payload

    def grant(self, run_id: str, plan_id: str, receipt: dict) -> dict:
        plan = self._plan(run_id, plan_id)
        required = ("approval_id", "run_id", "plan_id", "plan_sha256", "target_id", "action",
                    "scope", "host_request_id", "approver_id", "observed_at_utc")
        if not all(isinstance(receipt.get(key), str) and receipt[key] for key in required):
            raise ApprovalRequired("Approval receipt is incomplete")
        if not _timestamp(receipt["observed_at_utc"]):
            raise ApprovalRequired("Approval timestamp is invalid")
        if receipt["run_id"] != run_id or any(receipt[key] != plan[key] for key in
               ("plan_id", "plan_sha256", "target_id", "action", "scope")):
            raise ApprovalRequired("Approval does not bind this exact operation")
        if self.verify_approval is None or not self.verify_approval(receipt):
            raise ApprovalRequired("Host approval receipt is not verified")

        def validate(_ledger) -> None:
            events = self._events(run_id)
            if any(event["type"] == "approval.granted" and
                   (event["payload"].get("approval_id") == receipt["approval_id"] or
                    event["payload"].get("plan_id") == plan_id) for event in events):
                raise ApprovalRequired("Approval has already been used")

        self.store.transition(run_id, "approval.granted", validate, payload=receipt)
        return self.status(run_id, plan_id)

    def begin(self, run_id: str, plan_id: str) -> dict:
        plan = self._plan(run_id, plan_id)

        def validate(_ledger) -> None:
            state = self.status(run_id, plan_id)
            if state["status"] == "outcome_unknown":
                raise OutcomeUnknown("Operation was already started; reconcile before any retry")
            if state["status"] != "approved":
                raise ApprovalRequired("Operation needs a verified, unused approval")

        self.store.transition(run_id, "operation.started", validate, payload={
            "plan_id": plan_id,
            "plan_sha256": plan["plan_sha256"],
            "idempotency_key": plan["idempotency_key"],
        })
        return self.status(run_id, plan_id)

    def finish(self, run_id: str, plan_id: str, receipt: dict) -> dict:
        plan = self._plan(run_id, plan_id)
        required = ("run_id", "plan_id", "idempotency_key", "host_tool_call_id", "observed_at_utc",
                    "output_sha256", "reference")
        if not all(isinstance(receipt.get(key), str) and receipt[key] for key in required):
            raise RunStoreError("Tool receipt is incomplete")
        if receipt["run_id"] != run_id or receipt["plan_id"] != plan_id or receipt["idempotency_key"] != plan["idempotency_key"]:
            raise RunStoreError("Tool receipt does not bind this operation")
        if not SHA256.fullmatch(receipt["output_sha256"]) or not _timestamp(receipt["observed_at_utc"]):
            raise RunStoreError("Tool receipt digest or time is invalid")
        if not isinstance(receipt.get("exit_code"), int) or receipt.get("outcome") not in ("completed", "failed"):
            raise RunStoreError("Tool receipt outcome is invalid")
        if receipt["outcome"] == "completed" and receipt["exit_code"] != 0:
            raise RunStoreError("A nonzero exit code cannot claim completion")
        if self.verify_tool_receipt is None or not self.verify_tool_receipt(receipt):
            raise RunStoreError("Host tool receipt is not verified")

        def validate(_ledger) -> None:
            if self.status(run_id, plan_id)["status"] != "outcome_unknown":
                raise RunStoreError("Operation was not awaiting a receipt")

        self.store.transition(run_id, "operation.completed" if receipt["outcome"] == "completed"
                              else "operation.failed", validate, payload=receipt)
        return self.status(run_id, plan_id)

    def status(self, run_id: str, plan_id: str) -> dict:
        plan = self._plan(run_id, plan_id)
        events = [event for event in self._events(run_id) if event["payload"].get("plan_id") == plan_id]
        types = [event["type"] for event in events]
        if "operation.completed" in types:
            state = "completed"
        elif "operation.failed" in types:
            state = "failed"
        elif "operation.started" in types:
            state = "outcome_unknown"
        elif "approval.granted" in types:
            state = "approved"
        else:
            state = "planned"
        return {"plan_id": plan_id, "status": state,
                "target_id": plan["target_id"], "plan_sha256": plan["plan_sha256"],
                "idempotency_key": plan["idempotency_key"]}
