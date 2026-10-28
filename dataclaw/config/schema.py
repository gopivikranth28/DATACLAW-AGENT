"""Pydantic models for dataclaw.config.json."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class LLMBackendConfig(BaseModel):
    """Settings for one LLM backend under ``llm.backends.<id>``.

    Empty values fall back to env vars, the backend's preset, and the
    registry defaults (dataclaw.providers.llm.registry). Backend-specific
    keys (codex ``auth_mode``/``codex_bin``) are kept as extra fields.
    """

    api_key: str = ""
    base_url: str = ""
    model: str = ""
    headers: dict[str, str] = {}
    preset: str = ""
    reasoning_effort: str = ""
    api: str = ""  # openai only: "" (auto) | "responses" | "chat_completions"

    model_config = {"extra": "allow"}


class LLMConfig(BaseModel):
    # DataClaw-owned utility model. The selected agent runtime is configured
    # separately under agent.runtime. Any registered LLM backend id
    # (anthropic | openai | gemini | codex | openai_compatible | ...).
    backend: str = "codex"
    # Per-backend settings. Legacy llm.anthropic|openai|gemini|codex
    # sections are moved here by config.migrations on startup.
    backends: dict[str, LLMBackendConfig] = {}


class AgentConfig(BaseModel):
    runtime: str = "openclaw"  # dataclaw | hermes | openclaw | mock


class CompactionConfig(BaseModel):
    backend: str = "noop"  # noop | drop_old | llm_summarizer
    enabled: bool = False  # deprecated, kept for compat
    # Legacy key names are retained for config-file compatibility. The UI and
    # providers interpret both values as complete user conversation turns.
    max_messages: int = 30
    # `keep_recent` accepts None (treated as "use the default" downstream) so
    # an existing config file with `"keep_recent": null` still parses cleanly.
    keep_recent: int | None = 8
    max_tokens: int = 100_000  # estimated token budget; 0 disables token-based trigger


class AppConfig(BaseModel):
    debug: bool = False
    max_turns: int = 30
    max_auto_turns: int = 10
    host: str = "127.0.0.1"
    port: int = 8000


class KeywordMemoryConfig(BaseModel):
    top_k: int = 5
    min_score: float = 0.1


class RAGMemoryConfig(BaseModel):
    model: str = "all-MiniLM-L6-v2"
    top_k: int = 5


class GbrainMemoryConfig(BaseModel):
    location: str = "new"  # new | existing
    brain_home: str = "~/.dataclaw/memory"
    mode: str = "read_write"  # read_write | read_only
    top_k: int = 5
    gbrain_bin: str = "gbrain"


class MemoryConfig(BaseModel):
    backend: str = "noop"  # noop | keyword | rag | gbrain
    keyword: KeywordMemoryConfig = KeywordMemoryConfig()
    rag: RAGMemoryConfig = RAGMemoryConfig()
    gbrain: GbrainMemoryConfig = GbrainMemoryConfig()


class DataclawConfig(BaseModel):
    agent: AgentConfig = AgentConfig()
    llm: LLMConfig = LLMConfig()
    compaction: CompactionConfig = CompactionConfig()
    memory: MemoryConfig = MemoryConfig()
    app: AppConfig = AppConfig()
    plugins: dict[str, Any] = {}  # Plugin-specific config sections

    model_config = {"extra": "allow"}  # Allow unknown fields from plugins
