"""Chat Completions client for third-party OpenAI-compatible servers."""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI


class CompatibleChatOpenAI(ChatOpenAI):
    """ChatOpenAI that keeps the request shape every compatible server accepts.

    ChatOpenAI rewrites the system message to the ``developer`` role for
    model names that look like OpenAI o-series models.  Ollama, vLLM, Groq
    and most gateways only understand ``system``, so the rewrite is undone.
    """

    def _get_request_payload(self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        for message in payload.get("messages", []):
            if isinstance(message, dict) and message.get("role") == "developer":
                message["role"] = "system"
        return payload
