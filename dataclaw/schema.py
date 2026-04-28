"""Canonical message types and tool definitions.

Dataclaw's own Message class — provider-neutral, used throughout the
pipeline. LangChain conversion happens only at the LLM provider boundary.

Plain text:
    Message(role="user", content="hello")
    Message(role="assistant", content="hi")

Tool calls (assistant):
    Message(role="assistant", content=[
        TextBlock(type="text", text="Looking that up..."),
        ToolCallBlock(type="tool_call", id="call_abc", name="search", input={"q": "foo"}),
    ])

Tool results (user):
    Message(role="user", content=[
        ToolResultBlock(type="tool_result", call_id="call_abc", content="result", is_error=False),
    ])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict


# ── Content blocks (still TypedDicts for lightweight serialization) ──────────

class TextBlock(TypedDict):
    type: Literal["text"]
    text: str


class ToolCallBlock(TypedDict):
    type: Literal["tool_call"]
    id: str
    name: str
    input: dict[str, Any]


class ToolResultBlock(TypedDict):
    type: Literal["tool_result"]
    call_id: str
    content: str
    is_error: bool


ContentBlock = TextBlock | ToolCallBlock | ToolResultBlock


# ── Message ─────────────────────────────────────────────────────────────────

@dataclass
class Message:
    """Dataclaw's canonical message type."""
    role: str  # "user" | "assistant" | "system"
    content: str | list[ContentBlock] = ""

    def text(self) -> str:
        """Extract plain text from content, regardless of format."""
        if isinstance(self.content, str):
            return self.content
        parts = []
        for block in self.content:
            if block.get("type") == "text":
                parts.append(block["text"])
            elif block.get("type") == "tool_call":
                parts.append(f"[tool_call: {block.get('name', '?')}]")
            elif block.get("type") == "tool_result":
                parts.append(f"[tool_result: {str(block.get('content', ''))[:200]}]")
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON storage."""
        return {"role": self.role, "content": self.content}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Message:
        """Deserialize from a plain dict."""
        return cls(role=d.get("role", "user"), content=d.get("content", ""))

    @classmethod
    def user(cls, text: str) -> Message:
        return cls(role="user", content=text)

    @classmethod
    def assistant(cls, text: str) -> Message:
        return cls(role="assistant", content=text)

    @classmethod
    def system(cls, text: str) -> Message:
        return cls(role="system", content=text)


# ── Tool definition ─────────────────────────────────────────────────────────

class ToolDefinition(TypedDict, total=False):
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
