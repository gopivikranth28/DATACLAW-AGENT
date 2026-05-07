"""Pydantic models for dataclaw.config.json."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class AnthropicConfig(BaseModel):
    api_key: str = ""
    model: str = "claude-sonnet-4-20250514"


class OpenAIConfig(BaseModel):
    api_key: str = ""
    model: str = "gpt-4o"
    base_url: str = ""


class GeminiConfig(BaseModel):
    api_key: str = ""
    model: str = "gemini-2.5-flash"


class CodexConfig(BaseModel):
    model: str = "gpt-5.5"
    api_key: str = ""
    auth_mode: str = "default"  # "default" | "api_key"


class LLMConfig(BaseModel):
    backend: str = "openclaw"  # openclaw | anthropic | openai | gemini | codex
    anthropic: AnthropicConfig = AnthropicConfig()
    openai: OpenAIConfig = OpenAIConfig()
    gemini: GeminiConfig = GeminiConfig()
    codex: CodexConfig = CodexConfig()


class CompactionConfig(BaseModel):
    backend: str = "noop"  # noop | drop_old | llm_summarizer
    enabled: bool = False  # deprecated, kept for compat
    max_messages: int = 30
    # `keep_recent` accepts None (treated as "use the default" downstream) so
    # an existing config file with `"keep_recent": null` still parses cleanly.
    keep_recent: int | None = 8
    max_tokens: int = 100_000  # estimated token budget; 0 disables token-based trigger


class AppConfig(BaseModel):
    debug: bool = False
    max_turns: int = 30
    max_auto_turns: int = 10
    host: str = "0.0.0.0"
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
    llm: LLMConfig = LLMConfig()
    compaction: CompactionConfig = CompactionConfig()
    memory: MemoryConfig = MemoryConfig()
    app: AppConfig = AppConfig()
    plugins: dict[str, Any] = {}  # Plugin-specific config sections

    model_config = {"extra": "allow"}  # Allow unknown fields from plugins
