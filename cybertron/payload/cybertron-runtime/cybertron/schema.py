"""定义跨角色消息、工具调用，以及函数签名到工具 JSON Schema 的转换。"""

from __future__ import annotations
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, get_type_hints

# MODULE 1: Core Message & Tool Schema Protocol (Ref: ch04_v2_tools.py)
# ============================================================================

@dataclass
class ToolCallRequest:
    call_id: str
    tool_name: str
    parameters: Dict[str, Any]


@dataclass
class Message:
    role: str  # "system", "user", "assistant", "tool"
    content: str
    source: str = "system"
    tool_calls: List[ToolCallRequest] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None


def function_to_json_schema(func: Callable) -> Dict[str, Any]:
    """Introspects a Python function into an OpenAI/DeepSeek compatible tool schema."""
    sig = inspect.signature(func)
    doc = inspect.getdoc(func) or f"Execute {func.__name__}"
    type_map = {str: "string", int: "integer", float: "number", bool: "boolean"}
    resolved_hints = get_type_hints(func)
    properties: Dict[str, Any] = {}
    required: List[str] = []

    for name, param in sig.parameters.items():
        py_type = resolved_hints.get(name, str)
        json_type = type_map.get(py_type, "string")
        properties[name] = {"type": json_type, "description": f"Parameter {name}"}
        if param.default == inspect.Parameter.empty:
            required.append(name)

    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": doc,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }
