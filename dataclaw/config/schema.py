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


class LLMConfig(BaseModel):
    backend: str = "openclaw"  # openclaw | anthropic | openai | gemini
    anthropic: AnthropicConfig = AnthropicConfig()
    openai: OpenAIConfig = OpenAIConfig()
    gemini: GeminiConfig = GeminiConfig()


class CompactionConfig(BaseModel):
    enabled: bool = False
    max_messages: int = 30
    keep_recent: int = 8


class AppConfig(BaseModel):
    debug: bool = False
    max_turns: int = 30
    host: str = "0.0.0.0"
    port: int = 8000


class DataclawConfig(BaseModel):
    llm: LLMConfig = LLMConfig()
    compaction: CompactionConfig = CompactionConfig()
    app: AppConfig = AppConfig()
    plugins: dict[str, Any] = {}  # Plugin-specific config sections

    model_config = {"extra": "allow"}  # Allow unknown fields from plugins
