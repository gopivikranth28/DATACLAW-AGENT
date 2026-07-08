"""Artifact publish validation and self-containment helpers."""

from __future__ import annotations

import base64
import mimetypes
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dataclaw_artifacts.store import MAX_ARTIFACT_BYTES, resolve_workspace_path

FORBIDDEN_TAGS = {"iframe", "object", "embed", "base"}
FORBIDDEN_JS_PATTERNS = [
    (re.compile(r"\bfetch\s*\(", re.I), "fetch_call"),
    (re.compile(r"\bXMLHttpRequest\b", re.I), "xml_http_request"),
    (re.compile(r"\bWebSocket\s*\(", re.I), "web_socket"),
    (re.compile(r"\bEventSource\s*\(", re.I), "event_source"),
    (re.compile(r"\bnavigator\.sendBeacon\s*\(", re.I), "send_beacon"),
]


class ArtifactValidationError(ValueError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": self.details}


@dataclass(frozen=True)
class _Reference:
    tag: str
    attr: str
    value: str


class _Scanner(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.references: list[_Reference] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._scan_tag(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._scan_tag(tag, attrs)

    def _scan_tag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_by_name = {name.lower(): value or "" for name, value in attrs}
        if tag in FORBIDDEN_TAGS:
            raise ArtifactValidationError(
                "forbidden_tag",
                f"Artifact HTML cannot contain <{tag}>",
                {"tag": tag},
            )
        for attr_name in attrs_by_name:
            if attr_name.startswith("on"):
                raise ArtifactValidationError(
                    "inline_event_handler",
                    f"Inline event handlers are not allowed: {attr_name}",
                    {"tag": tag, "attribute": attr_name},
                )
        if tag == "script" and attrs_by_name.get("src"):
            self.references.append(_Reference(tag=tag, attr="src", value=attrs_by_name["src"]))
        elif tag == "link" and attrs_by_name.get("href"):
            rel = attrs_by_name.get("rel", "").lower()
            if "stylesheet" in rel or attrs_by_name.get("as", "").lower() == "style":
                self.references.append(_Reference(tag=tag, attr="href", value=attrs_by_name["href"]))
            elif _is_remote(attrs_by_name["href"]):
                raise ArtifactValidationError(
                    "external_link_asset",
                    "Remote link assets are not allowed",
                    {"href": attrs_by_name["href"]},
                )
        elif tag == "img" and attrs_by_name.get("src"):
            self.references.append(_Reference(tag=tag, attr="src", value=attrs_by_name["src"]))


def _is_remote(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} or value.strip().startswith("//")


def _is_inline(value: str) -> bool:
    stripped = value.strip().lower()
    return stripped.startswith("data:")


def _is_root_relative(value: str) -> bool:
    return value.strip().startswith("/")


def _asset_path(ref_value: str, base_dir: Path | None, session_id: str, project_id: str | None) -> Path:
    value = ref_value.strip()
    if _is_remote(value):
        raise ArtifactValidationError("external_asset", "Remote assets are not allowed", {"src": ref_value})
    if _is_inline(value):
        raise ArtifactValidationError("unsupported_asset_reference", "Only relative file assets can be inlined", {"src": ref_value})
    if _is_root_relative(value):
        raise ArtifactValidationError("root_relative_asset", "Root-relative assets are not allowed", {"src": ref_value})
    path = (base_dir / value).resolve() if base_dir is not None else resolve_workspace_path(value, session_id=session_id, project_id=project_id)
    if not path.exists() or not path.is_file():
        raise ArtifactValidationError("asset_not_found", f"Asset not found: {ref_value}", {"src": ref_value})
    return path


def _asset_data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _inline_script_sources(html: str, base_dir: Path | None, session_id: str, project_id: str | None) -> str:
    pattern = re.compile(r"<script\b([^>]*?)\bsrc=(['\"])([^'\"]+)\2([^>]*)>\s*</script>", re.I | re.S)

    def repl(match: re.Match[str]) -> str:
        src = match.group(3)
        path = _asset_path(src, base_dir, session_id, project_id)
        code = path.read_text(encoding="utf-8", errors="replace")
        for rx, code_name in FORBIDDEN_JS_PATTERNS:
            if rx.search(code):
                raise ArtifactValidationError("live_data_call", "Artifact JavaScript cannot call network APIs", {"pattern": code_name})
        return f"<script>{code}</script>"

    return pattern.sub(repl, html)


def _inline_stylesheets(html: str, base_dir: Path | None, session_id: str, project_id: str | None) -> str:
    pattern = re.compile(r"<link\b([^>]*?)\bhref=(['\"])([^'\"]+)\2([^>]*)>", re.I | re.S)

    def repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        if not re.search(r"\brel=(['\"])[^'\"]*stylesheet[^'\"]*\1", tag, re.I):
            return tag
        href = match.group(3)
        path = _asset_path(href, base_dir, session_id, project_id)
        css = path.read_text(encoding="utf-8", errors="replace")
        return f"<style>{css}</style>"

    return pattern.sub(repl, html)


def _inline_images(html: str, base_dir: Path | None, session_id: str, project_id: str | None) -> str:
    pattern = re.compile(r"(<img\b[^>]*?\bsrc=)(['\"])([^'\"]+)\2", re.I | re.S)

    def repl(match: re.Match[str]) -> str:
        src = match.group(3)
        if _is_inline(src):
            return match.group(0)
        path = _asset_path(src, base_dir, session_id, project_id)
        return f"{match.group(1)}{match.group(2)}{_asset_data_uri(path)}{match.group(2)}"

    return pattern.sub(repl, html)


def validate_and_prepare_html(
    html: str,
    *,
    base_dir: Path | None = None,
    session_id: str = "default",
    project_id: str | None = None,
) -> str:
    encoded = html.encode("utf-8")
    if len(encoded) > MAX_ARTIFACT_BYTES:
        raise ArtifactValidationError(
            "size_limit",
            f"Artifact is too large ({len(encoded)} bytes, max {MAX_ARTIFACT_BYTES})",
        )

    scanner = _Scanner()
    try:
        scanner.feed(html)
    except ArtifactValidationError:
        raise
    except Exception as exc:
        raise ArtifactValidationError("html_parse_error", f"Could not parse artifact HTML: {exc}") from exc

    for ref in scanner.references:
        if _is_remote(ref.value):
            raise ArtifactValidationError("external_asset", "Remote assets are not allowed", {"tag": ref.tag, ref.attr: ref.value})
        if _is_root_relative(ref.value):
            raise ArtifactValidationError("root_relative_asset", "Root-relative assets are not allowed", {"tag": ref.tag, ref.attr: ref.value})

    for rx, code in FORBIDDEN_JS_PATTERNS:
        if rx.search(html):
            raise ArtifactValidationError("live_data_call", "Artifact JavaScript cannot call network APIs", {"pattern": code})

    prepared = _inline_script_sources(html, base_dir, session_id, project_id)
    prepared = _inline_stylesheets(prepared, base_dir, session_id, project_id)
    prepared = _inline_images(prepared, base_dir, session_id, project_id)

    size = len(prepared.encode("utf-8"))
    if size > MAX_ARTIFACT_BYTES:
        raise ArtifactValidationError("size_limit", f"Prepared artifact is too large ({size} bytes, max {MAX_ARTIFACT_BYTES})")
    return prepared
