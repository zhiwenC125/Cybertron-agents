"""在模型上下文超预算时保留早期约束与近期消息，并保持工具调用和结果成组。"""

from __future__ import annotations
import json
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import List, Protocol, Set, Tuple, runtime_checkable
from .schema import Message

# MODULE 2: Alpha Trion Context Compaction Engine (Ref: picoagents/compaction.py)
# ============================================================================

@runtime_checkable
class CompactionStrategy(Protocol):
    """Protocol for context compaction executed INSIDE the agent tool loop."""

    @abstractmethod
    def compact(self, messages: List[Message]) -> List[Message]:
        ...


@dataclass
class AlphaTrionHeadTailCompaction:
    """
    Token-aware Head+Tail Compaction (Alpha Trion's Quill).
    Preserves:
      - Head (25% budget): System prompt, initial user requirement, and Feishu Wiki architectural/hardware constraints.
      - Tail (75% budget): Most recent tool calls and results (working memory).
    Crucially preserves 'atomic groups': an assistant message containing `tool_calls`
    is NEVER separated from its corresponding `ToolMessage` results.
    """
    token_budget: int = 64_000
    head_ratio: float = 0.25
    compaction_count: int = field(default=0, repr=False)
    total_tokens_saved: int = field(default=0, repr=False)

    @staticmethod
    def estimate_tokens(messages: List[Message]) -> int:
        total = 0
        for msg in messages:
            total += 4 + len(msg.content or "") // 4
            for tc in msg.tool_calls:
                total += 8 + len(tc.tool_name) + len(json.dumps(tc.parameters, ensure_ascii=False)) // 4
        return total

    @staticmethod
    def find_atomic_groups(messages: List[Message]) -> List[Tuple[int, ...]]:
        groups: List[Tuple[int, ...]] = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            if msg.role == "assistant" and msg.tool_calls:
                pending_ids: Set[str] = {tc.call_id for tc in msg.tool_calls}
                group_indices = [i]
                j = i + 1
                while j < len(messages) and pending_ids:
                    if messages[j].role == "tool" and messages[j].tool_call_id in pending_ids:
                        group_indices.append(j)
                        pending_ids.remove(messages[j].tool_call_id)  # type: ignore[arg-type]
                    j += 1
                groups.append(tuple(group_indices))
                i = max(group_indices) + 1
            else:
                groups.append((i,))
                i += 1
        return groups

    def compact(self, messages: List[Message]) -> List[Message]:
        if not messages:
            return messages
        current_tokens = self.estimate_tokens(messages)
        if current_tokens <= self.token_budget:
            return messages

        self.compaction_count += 1
        groups = self.find_atomic_groups(messages)
        head_budget = int(self.token_budget * self.head_ratio)
        tail_budget = self.token_budget - head_budget

        head_groups: List[Tuple[int, ...]] = []
        head_tokens = 0
        for grp in groups:
            grp_tokens = self.estimate_tokens([messages[idx] for idx in grp])
            if head_tokens + grp_tokens <= head_budget:
                head_groups.append(grp)
                head_tokens += grp_tokens
            else:
                break

        remaining = groups[len(head_groups):]
        tail_groups: List[Tuple[int, ...]] = []
        tail_tokens = 0
        for grp in reversed(remaining):
            grp_tokens = self.estimate_tokens([messages[idx] for idx in grp])
            if tail_tokens + grp_tokens <= tail_budget:
                tail_groups.insert(0, grp)
                tail_tokens += grp_tokens
            else:
                break

        kept_indices: Set[int] = set()
        for grp in head_groups + tail_groups:
            kept_indices.update(grp)

        compacted = [messages[idx] for idx in sorted(kept_indices)]
        self.total_tokens_saved += current_tokens - self.estimate_tokens(compacted)
        return compacted
