"""Slim a tool result for LLM consumption while leaving the original intact.

Cell-execution outputs include `image/png` base64 strings and HTML DataFrame
reprs that are useless to the LLM and chew through context. Tools capture
multiple MIME representations (e.g. `text/plain`, `text/markdown`) alongside
the heavy primary form; this helper picks the slim one for the LLM and
strips the bytes.

Pure function — never mutates the input. Result emit/persist paths keep
seeing the full original; only the LLM-bound copy is redacted.
"""

from __future__ import annotations

from typing import Any


def redact_for_llm(value: Any) -> Any:
    """Return a redacted copy of `value` suitable for LLM context.

    Recognized shapes (notebook cell outputs):
      * dict with type=="image" and data: drop `data`, leave a tiny note +
        any kernel-provided `summary` (typically a matplotlib repr line).
      * dict with type=="html": prefer `markdown` if non-empty, else
        `plain_text`. Drop the original HTML body either way.

    Other dicts/lists are recursed into structurally; scalars pass through.
    """
    if isinstance(value, dict):
        return _redact_dict(value)
    if isinstance(value, list):
        return [redact_for_llm(item) for item in value]
    return value


def _redact_dict(value: dict[str, Any]) -> dict[str, Any]:
    output_type = value.get("type")
    if output_type == "image" and "data" in value:
        return _redact_image(value)
    if output_type == "html":
        redacted = _redact_html(value)
        if redacted is not None:
            return redacted
    # Default: structural recursion so nested cell-output lists get redacted.
    return {k: redact_for_llm(v) for k, v in value.items()}


def _redact_image(value: dict[str, Any]) -> dict[str, Any]:
    mimetype = value.get("mimetype") or "image/?"
    summary = (value.get("summary") or "").strip()
    out: dict[str, Any] = {
        "type": "image",
        "elided": True,
        "note": f"<image elided for context: {mimetype}>",
    }
    if summary:
        out["summary"] = summary
    return out


def _redact_html(value: dict[str, Any]) -> dict[str, Any] | None:
    markdown = value.get("markdown") or ""
    if markdown.strip():
        # Preserve original indentation/layout — only strip() to test emptiness.
        return {"type": "markdown", "text": markdown}
    plain = value.get("plain_text") or ""
    if plain.strip():
        return {"type": "text", "text": plain}
    return None
