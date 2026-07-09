"""Built-in guardrail definitions."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from dataclaw.guardrails.base import GuardrailVerdict
from dataclaw.state import AgentState

# ── Credential patterns ────────────────────────────────────────────────────

_CREDENTIAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("AWS secret key", re.compile(r"(?i)aws.{0,20}secret.{0,20}['\"][0-9a-zA-Z/+]{40}['\"]")),
    ("Generic API key", re.compile(r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}['\"]?")),
    ("Bearer token", re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*")),
    ("Private key block", re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,}")),
    ("Generic secret", re.compile(r"(?i)(password|secret|token)\s*[:=]\s*['\"][^\s'\"]{8,}['\"]")),
    ("Connection string", re.compile(r"(?i)(postgres|mysql|mongodb|redis)://[^\s]{10,}")),
]

# ── Workspace tool names ───────────────────────────────────────────────────

_WORKSPACE_PATH_TOOLS = {"ws_read_file", "ws_write_file", "ws_update_file", "ws_list_files", "open_notebook"}


# ── Pre-phase guardrails ──────────────────────────────────────────────────


class FileDeleteGuardrail:
    """Triggers when the agent tries to delete a file via ws_exec."""

    id = "file_delete"
    phase = "pre"
    mode = "user_approval"

    _DELETE_PATTERNS = re.compile(
        r"\b(rm\s|rm\b|rmdir\b|del\s|unlink\b|shutil\.rmtree|os\.remove|os\.unlink)",
        re.IGNORECASE,
    )

    def evaluate(self, tool_call: dict[str, Any], state: AgentState) -> GuardrailVerdict | None:
        if tool_call.get("tool_name") != "ws_exec":
            return None

        command = tool_call.get("tool_input", {}).get("command", "")
        if not self._DELETE_PATTERNS.search(command):
            return None

        return GuardrailVerdict(
            tool_call_id=tool_call.get("call_id", ""),
            guardrail_id=self.id,
            message=f"The agent wants to run a destructive command: `{command}`. Approve or deny this action.",
            mode=self.mode,
            phase=self.phase,
            severity="danger",
        )


class OutsideProjectGuardrail:
    """Triggers when the agent operates outside the project directory."""

    id = "outside_project"
    phase = "pre"
    mode = "user_approval"

    def evaluate(self, tool_call: dict[str, Any], state: AgentState) -> GuardrailVerdict | None:
        tool_name = tool_call.get("tool_name", "")
        if tool_name not in _WORKSPACE_PATH_TOOLS:
            return None

        path_arg = tool_call.get("tool_input", {}).get("path", "")
        if not path_arg:
            return None

        # Detect obvious traversal attempts
        normalized = str(Path(path_arg))
        if ".." in normalized or path_arg.startswith("/"):
            return GuardrailVerdict(
                tool_call_id=tool_call.get("call_id", ""),
                guardrail_id=self.id,
                message=(
                    f"The agent wants to access '{path_arg}' which points outside the project workspace. "
                    "Approve to allow this access, or deny to block it."
                ),
                mode=self.mode,
                phase=self.phase,
                severity="danger",
            )
        return None




class CodeOutsideWorkspaceGuardrail:
    """Triggers when code being executed references files outside the workspace.

    Checks execute_code (code in tool_input) and execute_cell (reads cell
    source from the notebook manager at evaluation time).
    """

    id = "code_outside_workspace"
    phase = "pre"
    mode = "user_approval"

    # Patterns that indicate outside-workspace file access in Python code.
    # Matches string literals containing absolute paths or ../ traversal
    # inside common file-access calls.
    _OUTSIDE_PATH_PATTERNS = re.compile(
        r"""(?x)
        # Absolute paths in string literals: open("/etc/..."), Path("/tmp/...")
        (?:open|Path|read_csv|read_json|read_excel|read_parquet|to_csv|to_json|
           to_excel|to_parquet|read_text|write_text|read_bytes|write_bytes|
           load|save|savefig|imread|imwrite)\s*\(\s*
            (?:f?['"])(/[^\s'\"]+)['"]
        |
        # Parent traversal in string literals: open("../../secret")
        (?:open|Path|read_csv|read_json|read_excel|read_parquet|to_csv|to_json|
           to_excel|to_parquet|read_text|write_text|read_bytes|write_bytes|
           load|save|savefig|imread|imwrite)\s*\(\s*
            (?:f?['"])((?:\.\./)+[^\s'\"]+)['"]
        |
        # os.path / os module file ops with absolute or traversal paths
        os\.(?:path\.join|remove|unlink|rename|makedirs|listdir|chdir)\s*\(\s*
            (?:f?['"])((?:/|\.\./)[^\s'\"]+)['"]
        |
        # shutil operations with absolute or traversal paths
        shutil\.(?:copy|copy2|copytree|move|rmtree)\s*\(\s*
            (?:f?['"])((?:/|\.\./)[^\s'\"]+)['"]
        |
        # subprocess / os.system with file access
        (?:subprocess\.(?:run|call|Popen)|os\.system)\s*\(\s*
            (?:f?['"])[^'\"]*(?:cat|rm|cp|mv|ls|head|tail|chmod)\s+((?:/|\.\./)[^\s'\"]+)
        """
    )

    def _get_code(self, tool_call: dict[str, Any]) -> str | None:
        """Extract the code string from the tool call."""
        tool_name = tool_call.get("tool_name", "")
        tool_input = tool_call.get("tool_input", {})

        if tool_name == "execute_code":
            return tool_input.get("code", "")

        if tool_name == "execute_cell":
            # Read cell source from the notebook manager
            try:
                from dataclaw_notebooks.tools import _mgr
                nb_state = _mgr().get_current()
                cell_index = tool_input.get("cell_index", -1)
                cells = nb_state.notebook.cells
                if 0 <= cell_index < len(cells):
                    cell = cells[cell_index]
                    if cell.cell_type == "code":
                        return cell.source
            except Exception:
                pass  # Plugin not loaded or no active notebook

        return None

    def evaluate(self, tool_call: dict[str, Any], state: AgentState) -> GuardrailVerdict | None:
        code = self._get_code(tool_call)
        if not code or len(code) < 3:
            return None

        matches = self._OUTSIDE_PATH_PATTERNS.findall(code)
        # findall returns tuples for multiple groups — flatten to non-empty strings
        paths = [p for group in matches for p in (group if isinstance(group, tuple) else (group,)) if p]
        if not paths:
            return None

        unique_paths = sorted(set(paths))
        paths_str = ", ".join(f"`{p}`" for p in unique_paths[:5])
        preview = code[:200] + ("..." if len(code) > 200 else "")

        return GuardrailVerdict(
            tool_call_id=tool_call.get("call_id", ""),
            guardrail_id=self.id,
            message=(
                f"Code references paths outside the workspace: {paths_str}\n\n"
                f"```python\n{preview}\n```"
            ),
            mode=self.mode,
            phase=self.phase,
            severity="danger",
        )


class PlanCompletionGuardrail:
    """Triggers when the agent tries to complete a plan with incomplete steps."""

    id = "plan_completion"
    phase = "pre"
    mode = "auto_reply"

    def evaluate(self, tool_call: dict[str, Any], state: AgentState) -> GuardrailVerdict | None:
        if tool_call.get("tool_name") != "update_plan":
            return None

        tool_input = tool_call.get("tool_input", {})
        new_status = tool_input.get("status", "")
        if new_status != "completed":
            return None

        # Check step_patches for incomplete steps
        patches = tool_input.get("step_patches", [])
        incomplete_steps: list[str] = []
        for patch in patches:
            step_status = patch.get("status", "")
            if step_status and step_status != "completed":
                incomplete_steps.append(patch.get("name", "unnamed"))

        if incomplete_steps:
            names = ", ".join(incomplete_steps)
            return GuardrailVerdict(
                tool_call_id=tool_call.get("call_id", ""),
                guardrail_id=self.id,
                message=(
                    f"Cannot mark plan as completed — the following steps are not complete: {names}. "
                    "Complete all steps before finalizing the plan."
                ),
                mode=self.mode,
                phase=self.phase,
                severity="warning",
            )
        proposal_id = tool_input.get("proposal_id", "")
        if proposal_id:
            try:
                from dataclaw_plans.gates import plan_completion_warnings_sync

                gate_warnings = plan_completion_warnings_sync(proposal_id)
            except Exception:
                gate_warnings = []
            if gate_warnings:
                return GuardrailVerdict(
                    tool_call_id=tool_call.get("call_id", ""),
                    guardrail_id=self.id,
                    message=(
                        "Plan has required validation gates that are not ready: "
                        + "; ".join(gate_warnings)
                        + ". Resolve the gates or explicitly accept the risk before finalizing."
                    ),
                    mode=self.mode,
                    phase=self.phase,
                    severity="warning",
                )
        return None


# ── Post-phase guardrails ─────────────────────────────────────────────────


class CredentialDetectionGuardrail:
    """Redacts tool results that contain credentials or secrets."""

    id = "credential_detection"
    phase = "post"
    mode = "auto_reply"

    def evaluate(self, tool_call: dict[str, Any], state: AgentState) -> GuardrailVerdict | None:
        result = tool_call.get("result", "")
        if not isinstance(result, str) or len(result) < 10:
            return None

        found: list[str] = []
        for label, pattern in _CREDENTIAL_PATTERNS:
            if pattern.search(result):
                found.append(label)

        if not found:
            return None

        labels = ", ".join(found)
        return GuardrailVerdict(
            tool_call_id=tool_call.get("call_id", ""),
            guardrail_id=self.id,
            message=(
                f"[REDACTED] Tool result contained sensitive data ({labels}). "
                "The output has been withheld. If you need this data, ask the user to "
                "provide it directly or access it through a secure channel."
            ),
            mode=self.mode,
            phase=self.phase,
            severity="danger",
            original_result=result,
        )


class ResponseTruncationGuardrail:
    """Truncates tool results that exceed the size threshold."""

    id = "response_truncation"
    phase = "post"
    mode = "auto_reply"

    MAX_RESULT_BYTES = 50_000  # 50 KB default

    def evaluate(self, tool_call: dict[str, Any], state: AgentState) -> GuardrailVerdict | None:
        result = tool_call.get("result", "")
        if not isinstance(result, str):
            return None

        size = len(result.encode("utf-8", errors="replace"))
        if size <= self.MAX_RESULT_BYTES:
            return None

        # Truncate to threshold and append notice
        truncated = result[: self.MAX_RESULT_BYTES]
        # Try to cut at a line boundary
        last_newline = truncated.rfind("\n")
        if last_newline > self.MAX_RESULT_BYTES // 2:
            truncated = truncated[: last_newline + 1]

        return GuardrailVerdict(
            tool_call_id=tool_call.get("call_id", ""),
            guardrail_id=self.id,
            message=(
                f"{truncated}\n\n[TRUNCATED — response was {size:,} bytes, "
                f"exceeding the {self.MAX_RESULT_BYTES:,} byte limit. "
                "Request a smaller portion of the data if needed.]"
            ),
            mode=self.mode,
            phase=self.phase,
            severity="info",
            original_result=result,
        )
