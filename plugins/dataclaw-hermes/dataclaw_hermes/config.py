"""Resolved Hermes adapter configuration."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from dataclaw.config.resolver import (
    resolve,
    resolve_utility_backend,
    resolve_utility_model,
)

HERMES_COMPAT_VERSION = "0.19.0"
HERMES_COMPAT_TAG = "v2026.7.20"
HERMES_COMPAT_REVISION = "3ef6bbd201263d354fd83ec55b3c306ded2eb72a"
APPROVAL_WAIT_SECONDS = 300
CALLBACK_SAFETY_MARGIN_SECONDS = 5


@dataclass(frozen=True)
class HermesConfig:
    url: str
    api_key: str
    dataclaw_api_url: str
    profile: str
    model: str
    provider: str
    utility_backend: str
    utility_model: str
    cli_path: str
    request_timeout_seconds: float
    reconnect_timeout_seconds: float
    tool_callback_timeout_seconds: float

    @classmethod
    def resolve(cls) -> "HermesConfig":
        return cls(
            url=str(
                resolve(
                    "plugins.hermes.url",
                    "DATACLAW_HERMES_URL",
                    "http://127.0.0.1:8642",
                )
            ).rstrip("/"),
            api_key=str(
                resolve(
                    "plugins.hermes.api_key",
                    "HERMES_API_SERVER_KEY",
                    "",
                )
            ),
            dataclaw_api_url=str(
                resolve(
                    "plugins.hermes.dataclaw_api_url",
                    "DATACLAW_API_URL",
                    "http://127.0.0.1:8000",
                )
            ).rstrip("/"),
            profile=str(
                resolve(
                    "plugins.hermes.profile",
                    "DATACLAW_HERMES_PROFILE",
                    "dataclaw",
                )
            ),
            model=str(
                resolve(
                    "plugins.hermes.model",
                    "DATACLAW_HERMES_MODEL",
                    "",
                )
            ),
            provider=str(
                resolve(
                    "plugins.hermes.provider",
                    "DATACLAW_HERMES_PROVIDER",
                    "",
                )
            ),
            utility_backend=resolve_utility_backend(),
            utility_model=resolve_utility_model(),
            cli_path=str(
                resolve(
                    "plugins.hermes.cli_path",
                    "DATACLAW_HERMES_CLI",
                    "hermes",
                )
            ),
            request_timeout_seconds=float(
                resolve(
                    "plugins.hermes.request_timeout_seconds",
                    "DATACLAW_HERMES_REQUEST_TIMEOUT",
                    "60",
                )
            ),
            reconnect_timeout_seconds=float(
                resolve(
                    "plugins.hermes.reconnect_timeout_seconds",
                    "DATACLAW_HERMES_RECONNECT_TIMEOUT",
                    "30",
                )
            ),
            tool_callback_timeout_seconds=float(
                resolve(
                    "plugins.hermes.tool_callback_timeout_seconds",
                    "DATACLAW_HERMES_TOOL_CALLBACK_TIMEOUT",
                    "330",
                )
            ),
        )

    def validate(self) -> None:
        for label, url in (
            ("url", self.url),
            ("dataclaw_api_url", self.dataclaw_api_url),
        ):
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"plugins.hermes.{label} must be an HTTP URL")
        if not self.profile.strip():
            raise ValueError("plugins.hermes.profile is required")
        if not self.api_key.strip():
            raise ValueError(
                "plugins.hermes.api_key is required because Hermes 0.19.0 "
                "requires API_SERVER_KEY even for loopback-only servers"
            )
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if self.reconnect_timeout_seconds <= 0:
            raise ValueError("reconnect_timeout_seconds must be positive")
        minimum = APPROVAL_WAIT_SECONDS + CALLBACK_SAFETY_MARGIN_SECONDS
        if self.tool_callback_timeout_seconds < minimum:
            raise ValueError(
                "tool_callback_timeout_seconds must be at least "
                f"{minimum} seconds so approval can complete"
            )
        if bool(self.utility_backend) != bool(self.utility_model):
            raise ValueError(
                "DataClaw utility backend and model must be configured together"
            )
        if not self.utility_backend:
            raise ValueError(
                "Hermes 0.19.0 does not expose a raw utility LLM contract; "
                "configure llm.backend and the selected provider model"
            )
        from dataclaw.providers.llm.registry import utility_backend_ids

        backends = utility_backend_ids()
        if self.utility_backend not in backends:
            raise ValueError(
                "utility_backend must be one of: " + ", ".join(sorted(backends))
            )
        if self.provider:
            raise ValueError(
                "Hermes 0.19.0 /v1/runs does not accept a provider override; "
                "configure the provider in the Hermes profile/model route and "
                "leave plugins.hermes.provider empty"
            )
