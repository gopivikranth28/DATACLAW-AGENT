"""Tests for the guardrail system."""

import pytest

from dataclaw.guardrails.base import GuardrailVerdict
from dataclaw.guardrails.config import (
    GuardrailConfig,
    ProjectGuardrailConfig,
    SessionGuardrailConfig,
    is_guardrail_enabled,
)
from dataclaw.guardrails.registry import GuardrailRegistry
from dataclaw.guardrails.definitions import (
    FileDeleteGuardrail,
    OutsideProjectGuardrail,
    CodeOutsideWorkspaceGuardrail,
    PlanCompletionGuardrail,
    CredentialDetectionGuardrail,
    ResponseTruncationGuardrail,
)
from dataclaw.state import AgentState


# ── FileDeleteGuardrail ──────────────────────────────────────────────────


class TestFileDeleteGuardrail:
    def setup_method(self):
        self.g = FileDeleteGuardrail()

    def test_triggers_on_rm(self):
        v = self.g.evaluate(
            {"tool_name": "ws_exec", "tool_input": {"command": "rm -f test.txt"}, "call_id": "1"}, {}
        )
        assert v is not None
        assert v.mode == "user_approval"
        assert v.severity == "danger"

    def test_triggers_on_rmdir(self):
        v = self.g.evaluate(
            {"tool_name": "ws_exec", "tool_input": {"command": "rmdir old_dir"}, "call_id": "2"}, {}
        )
        assert v is not None

    def test_ignores_non_exec(self):
        v = self.g.evaluate(
            {"tool_name": "ws_read_file", "tool_input": {"path": "file.txt"}, "call_id": "3"}, {}
        )
        assert v is None

    def test_ignores_safe_commands(self):
        v = self.g.evaluate(
            {"tool_name": "ws_exec", "tool_input": {"command": "echo hello"}, "call_id": "4"}, {}
        )
        assert v is None


# ── OutsideProjectGuardrail ──────────────────────────────────────────────


class TestOutsideProjectGuardrail:
    def setup_method(self):
        self.g = OutsideProjectGuardrail()

    def test_triggers_on_traversal(self):
        v = self.g.evaluate(
            {"tool_name": "ws_read_file", "tool_input": {"path": "../../etc/passwd"}, "call_id": "1"}, {}
        )
        assert v is not None
        assert v.mode == "user_approval"
        assert v.severity == "danger"

    def test_triggers_on_absolute_path(self):
        v = self.g.evaluate(
            {"tool_name": "ws_write_file", "tool_input": {"path": "/tmp/evil.txt"}, "call_id": "2"}, {}
        )
        assert v is not None

    def test_triggers_on_open_notebook_traversal(self):
        v = self.g.evaluate(
            {"tool_name": "open_notebook", "tool_input": {"path": "/tmp/evil.ipynb"}, "call_id": "3"}, {}
        )
        assert v is not None

    def test_ignores_safe_relative_path(self):
        v = self.g.evaluate(
            {"tool_name": "ws_read_file", "tool_input": {"path": "data/output.csv"}, "call_id": "4"}, {}
        )
        assert v is None

    def test_ignores_unrelated_tool(self):
        v = self.g.evaluate(
            {"tool_name": "execute_code", "tool_input": {"code": "x = 1"}, "call_id": "5"}, {}
        )
        assert v is None


# ── CodeOutsideWorkspaceGuardrail ────────────────────────────────────────


class TestCodeOutsideWorkspaceGuardrail:
    def setup_method(self):
        self.g = CodeOutsideWorkspaceGuardrail()

    def test_triggers_execute_code_absolute_path(self):
        v = self.g.evaluate(
            {"tool_name": "execute_code", "tool_input": {"code": 'pd.read_csv("/etc/passwd")'}, "call_id": "1"}, {}
        )
        assert v is not None
        assert v.mode == "user_approval"
        assert "/etc/passwd" in v.message

    def test_triggers_execute_code_traversal(self):
        v = self.g.evaluate(
            {"tool_name": "execute_code", "tool_input": {"code": 'open("../../secret.key")'}, "call_id": "2"}, {}
        )
        assert v is not None
        assert "../../secret.key" in v.message

    def test_triggers_shutil_absolute(self):
        v = self.g.evaluate(
            {"tool_name": "execute_code", "tool_input": {"code": 'shutil.copy("/etc/hosts", "local.txt")'}, "call_id": "3"}, {}
        )
        assert v is not None

    def test_triggers_os_system_absolute(self):
        v = self.g.evaluate(
            {"tool_name": "execute_code", "tool_input": {"code": 'os.system("cat /etc/shadow")'}, "call_id": "4"}, {}
        )
        assert v is not None

    def test_ignores_safe_relative_path(self):
        v = self.g.evaluate(
            {"tool_name": "execute_code", "tool_input": {"code": 'df = pd.read_csv("data.csv")'}, "call_id": "5"}, {}
        )
        assert v is None

    def test_ignores_normal_code(self):
        v = self.g.evaluate(
            {"tool_name": "execute_code", "tool_input": {"code": "x = 1 + 2\nprint(x)"}, "call_id": "6"}, {}
        )
        assert v is None

    def test_ignores_unrelated_tool(self):
        v = self.g.evaluate(
            {"tool_name": "ws_read_file", "tool_input": {"path": "/etc/passwd"}, "call_id": "7"}, {}
        )
        assert v is None

    def test_execute_cell_graceful_without_manager(self):
        """execute_cell should gracefully return None when notebook manager isn't loaded."""
        v = self.g.evaluate(
            {"tool_name": "execute_cell", "tool_input": {"cell_index": 0}, "call_id": "8"}, {}
        )
        assert v is None

    def test_ignores_edit_cell(self):
        """Edit operations should not trigger — only execution matters."""
        v = self.g.evaluate(
            {"tool_name": "edit_cell", "tool_input": {"new_source": 'open("/etc/passwd")'}, "call_id": "9"}, {}
        )
        assert v is None

    def test_ignores_insert_cell(self):
        v = self.g.evaluate(
            {"tool_name": "insert_cell", "tool_input": {"source": 'open("/etc/passwd")'}, "call_id": "10"}, {}
        )
        assert v is None


# ── PlanCompletionGuardrail ──────────────────────────────────────────────


class TestPlanCompletionGuardrail:
    def setup_method(self):
        self.g = PlanCompletionGuardrail()

    def test_triggers_incomplete_steps(self):
        v = self.g.evaluate(
            {
                "tool_name": "update_plan",
                "tool_input": {
                    "proposal_id": "p1",
                    "status": "completed",
                    "step_patches": [
                        {"name": "Step 1", "status": "completed"},
                        {"name": "Step 2", "status": "in_progress"},
                    ],
                },
                "call_id": "1",
            },
            {},
        )
        assert v is not None
        assert v.mode == "auto_reply"
        assert "Step 2" in v.message

    def test_ignores_all_completed(self):
        v = self.g.evaluate(
            {
                "tool_name": "update_plan",
                "tool_input": {
                    "proposal_id": "p1",
                    "status": "completed",
                    "step_patches": [
                        {"name": "Step 1", "status": "completed"},
                        {"name": "Step 2", "status": "completed"},
                    ],
                },
                "call_id": "2",
            },
            {},
        )
        assert v is None

    def test_ignores_non_completion(self):
        v = self.g.evaluate(
            {
                "tool_name": "update_plan",
                "tool_input": {"proposal_id": "p1", "status": "running"},
                "call_id": "3",
            },
            {},
        )
        assert v is None

    def test_ignores_unrelated_tool(self):
        v = self.g.evaluate(
            {"tool_name": "ws_exec", "tool_input": {"command": "ls"}, "call_id": "4"}, {}
        )
        assert v is None


# ── CredentialDetectionGuardrail ─────────────────────────────────────────


class TestCredentialDetectionGuardrail:
    def setup_method(self):
        self.g = CredentialDetectionGuardrail()

    def test_triggers_on_password(self):
        v = self.g.evaluate(
            {"tool_name": "ws_read_file", "call_id": "1", "result": 'password="s3cr3t_v4lue!"'}, {}
        )
        assert v is not None
        assert "REDACTED" in v.message
        assert v.original_result is not None

    def test_triggers_on_aws_key(self):
        v = self.g.evaluate(
            {"tool_name": "ws_read_file", "call_id": "2", "result": "AKIAIOSFODNN7EXAMPLE"}, {}
        )
        assert v is not None

    def test_triggers_on_private_key(self):
        v = self.g.evaluate(
            {"tool_name": "ws_read_file", "call_id": "3", "result": "-----BEGIN PRIVATE KEY-----\nMIIE..."}, {}
        )
        assert v is not None

    def test_triggers_on_github_token(self):
        v = self.g.evaluate(
            {"tool_name": "ws_read_file", "call_id": "4", "result": "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl"}, {}
        )
        assert v is not None

    def test_ignores_safe_content(self):
        v = self.g.evaluate(
            {"tool_name": "ws_read_file", "call_id": "5", "result": "Hello world\nJust normal text"}, {}
        )
        assert v is None

    def test_ignores_short_content(self):
        v = self.g.evaluate(
            {"tool_name": "ws_read_file", "call_id": "6", "result": "ok"}, {}
        )
        assert v is None


# ── ResponseTruncationGuardrail ──────────────────────────────────────────


class TestResponseTruncationGuardrail:
    def setup_method(self):
        self.g = ResponseTruncationGuardrail()

    def test_triggers_on_large_result(self):
        big = "x" * 100_000
        v = self.g.evaluate(
            {"tool_name": "ws_read_file", "call_id": "1", "result": big}, {}
        )
        assert v is not None
        assert "TRUNCATED" in v.message
        assert v.original_result == big
        assert len(v.message) < len(big)

    def test_ignores_small_result(self):
        v = self.g.evaluate(
            {"tool_name": "ws_read_file", "call_id": "2", "result": "small content"}, {}
        )
        assert v is None


# ── GuardrailRegistry ────────────────────────────────────────────────────


class TestGuardrailRegistry:
    def setup_method(self):
        self.reg = GuardrailRegistry()

    @pytest.mark.asyncio
    async def test_pre_hook_blocks_and_adds_verdict(self):
        self.reg.register(FileDeleteGuardrail())
        hook = self.reg.as_pre_hook()

        state: AgentState = {
            "session_id": "test",
            "messages": [],
            "pending_tool_calls": [
                {"tool_name": "ws_exec", "tool_input": {"command": "rm -f data.csv"}, "call_id": "tc1"},
                {"tool_name": "ws_exec", "tool_input": {"command": "echo done"}, "call_id": "tc2"},
            ],
            "guardrail_verdicts": [],
        }

        result = await hook(state)
        # rm command should be removed, echo should remain
        assert len(result["pending_tool_calls"]) == 1
        assert result["pending_tool_calls"][0]["call_id"] == "tc2"
        # One verdict should be added
        assert len(result["guardrail_verdicts"]) == 1
        assert result["guardrail_verdicts"][0]["tool_call_id"] == "tc1"

    @pytest.mark.asyncio
    async def test_post_hook_redacts_result(self):
        self.reg.register(CredentialDetectionGuardrail())
        hook = self.reg.as_post_hook()

        state: AgentState = {
            "session_id": "test",
            "messages": [],
            "tool_results": [
                {"tool_name": "ws_read_file", "call_id": "tc1", "result": 'password="s3cr3t_v4lue!"'},
                {"tool_name": "ws_read_file", "call_id": "tc2", "result": "safe content"},
            ],
            "guardrail_verdicts": [],
        }

        result = await hook(state)
        # First result should be redacted
        assert "REDACTED" in result["tool_results"][0]["result"]
        assert result["tool_results"][0].get("guardrail_redacted") is True
        # Second result should be unchanged
        assert result["tool_results"][1]["result"] == "safe content"

    def test_register_and_unregister(self):
        g = FileDeleteGuardrail()
        self.reg.register(g)
        assert len(self.reg._guardrails) == 1
        self.reg.unregister("file_delete")
        assert len(self.reg._guardrails) == 0

    @pytest.mark.asyncio
    async def test_no_guardrails_passthrough(self):
        hook = self.reg.as_pre_hook()
        state: AgentState = {
            "session_id": "test",
            "messages": [],
            "pending_tool_calls": [
                {"tool_name": "ws_exec", "tool_input": {"command": "ls"}, "call_id": "tc1"},
            ],
        }
        result = await hook(state)
        assert result is state  # unchanged — early return


# ── Config Resolution ────────────────────────────────────────────────────


class TestGuardrailConfigResolution:
    def test_default_enabled(self):
        assert is_guardrail_enabled("file_delete", GuardrailConfig()) is True

    def test_global_disabled(self):
        cfg = GuardrailConfig(disabled={"file_delete"})
        assert is_guardrail_enabled("file_delete", cfg) is False
        assert is_guardrail_enabled("outside_project", cfg) is True

    def test_project_overrides_global(self):
        global_cfg = GuardrailConfig(disabled={"file_delete"})
        project_cfg = ProjectGuardrailConfig(enabled={"file_delete"})
        assert is_guardrail_enabled("file_delete", global_cfg, project_cfg) is True

    def test_project_disables(self):
        global_cfg = GuardrailConfig()
        project_cfg = ProjectGuardrailConfig(disabled={"file_delete"})
        assert is_guardrail_enabled("file_delete", global_cfg, project_cfg) is False

    def test_session_overrides_project(self):
        global_cfg = GuardrailConfig()
        project_cfg = ProjectGuardrailConfig(disabled={"file_delete"})
        session_cfg = SessionGuardrailConfig(enabled={"file_delete"})
        assert is_guardrail_enabled("file_delete", global_cfg, project_cfg, session_cfg) is True

    def test_session_disables(self):
        global_cfg = GuardrailConfig()
        project_cfg = ProjectGuardrailConfig(enabled={"file_delete"})
        session_cfg = SessionGuardrailConfig(disabled={"file_delete"})
        assert is_guardrail_enabled("file_delete", global_cfg, project_cfg, session_cfg) is False

    def test_session_overrides_global(self):
        global_cfg = GuardrailConfig(disabled={"file_delete"})
        session_cfg = SessionGuardrailConfig(enabled={"file_delete"})
        assert is_guardrail_enabled("file_delete", global_cfg, None, session_cfg) is True

    def test_unmentioned_guardrail_uses_global_default(self):
        """A guardrail not mentioned in session or project uses global default."""
        global_cfg = GuardrailConfig()
        project_cfg = ProjectGuardrailConfig(disabled={"other"})
        session_cfg = SessionGuardrailConfig(disabled={"another"})
        assert is_guardrail_enabled("file_delete", global_cfg, project_cfg, session_cfg) is True


class TestGuardrailRegistryFiltering:
    @pytest.mark.asyncio
    async def test_disabled_guardrail_skipped(self, tmp_path, monkeypatch):
        """A globally disabled guardrail should not trigger."""
        # Write a global config that disables file_delete
        import json
        config_path = tmp_path / "guardrail-config.json"
        config_path.write_text(json.dumps({"disabled": ["file_delete"]}))
        monkeypatch.setattr(
            "dataclaw.guardrails.config.guardrail_config_path",
            lambda: config_path,
        )

        reg = GuardrailRegistry()
        reg.register(FileDeleteGuardrail())
        hook = reg.as_pre_hook()

        state: AgentState = {
            "session_id": "",
            "messages": [],
            "pending_tool_calls": [
                {"tool_name": "ws_exec", "tool_input": {"command": "rm -f data.csv"}, "call_id": "tc1"},
            ],
            "guardrail_verdicts": [],
        }

        result = await hook(state)
        # file_delete is disabled, so the rm command should NOT be blocked
        assert len(result["pending_tool_calls"]) == 1
        assert result["pending_tool_calls"][0]["call_id"] == "tc1"
        assert len(result.get("guardrail_verdicts", [])) == 0
