"""Runtime selection, immutable bundles, and per-run bundle leases.

The core knows about Direct runtimes and the runtime-factory protocol only.
External runtimes register factories from plugins; this module never imports a
runtime plugin package.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Protocol, runtime_checkable

from dataclaw.config.resolver import (
    resolve_agent_runtime,
    resolve_utility_backend,
    resolve_utility_model,
)
from dataclaw.hooks.registry import HookRegistry
from dataclaw.providers.agent.implementations.langchain_agent import (
    LangChainAgentProvider,
)
from dataclaw.providers.agent.provider import AgentProvider
from dataclaw.providers.compaction.provider import CompactionProvider
from dataclaw.providers.llm.provider import LLMProvider
from dataclaw.providers.llm.registry import llm_backend_ids
from dataclaw.providers.memory.provider import MemoryProvider
from dataclaw.providers.skill.provider import SkillProvider
from dataclaw.providers.sub_agent.registry import SubAgentRegistry
from dataclaw.providers.system_prompt.provider import SystemPromptProvider
from dataclaw.providers.tool.provider import ToolAvailabilityProvider

logger = logging.getLogger(__name__)


class RuntimeSelectionError(RuntimeError):
    """A configured runtime could not be constructed or validated."""


class RuntimeUnavailableError(RuntimeError):
    """The selected runtime is unavailable and cannot accept a turn."""


@runtime_checkable
class RuntimeControl(Protocol):
    async def cancel(self, runtime_run_id: str) -> dict[str, Any]:
        """Request cancellation of an external runtime run."""

    async def status(self, runtime_run_id: str) -> dict[str, Any]:
        """Return the external runtime's current status."""


@dataclass(frozen=True)
class RuntimeIdentity:
    runtime: str
    version: str = ""
    model: str = ""
    provider: str = ""


@dataclass(frozen=True)
class RuntimeDiagnostics:
    health: str = "healthy"
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeFactoryContext:
    providers: Any
    hooks: HookRegistry
    backend: str
    base_bundle: "RuntimeBundle"


@dataclass(frozen=True)
class RuntimeBundle:
    """One internally consistent snapshot used for a complete run."""

    agent: AgentProvider
    utility_llm: LLMProvider
    compaction: CompactionProvider
    tool_availability: ToolAvailabilityProvider
    sub_agent_registry: SubAgentRegistry
    sub_agent_hooks: Any
    memory: MemoryProvider
    system_prompt: SystemPromptProvider
    skill: SkillProvider
    hooks: HookRegistry
    runtime_control: RuntimeControl | None
    identity: RuntimeIdentity
    diagnostics: RuntimeDiagnostics
    availability: bool = True

    @property
    def llm(self) -> LLMProvider:
        """Compatibility alias used by the existing chat loop."""
        return self.utility_llm

    async def aclose(self) -> None:
        """Close each distinct component that owns async resources once."""
        seen: set[int] = set()
        for component in (self.agent, self.utility_llm, self.runtime_control):
            if component is None or id(component) in seen:
                continue
            seen.add(id(component))
            close = getattr(component, "aclose", None)
            if close is None:
                continue
            result = close()
            if inspect.isawaitable(result):
                await result


RuntimeFactory = Callable[
    [RuntimeFactoryContext], RuntimeBundle | Awaitable[RuntimeBundle]
]


class UnavailableAgentProvider:
    """Typed failure provider used when startup selection cannot succeed."""

    def __init__(self, message: str) -> None:
        self.message = message

    @classmethod
    def config_schema(cls) -> list[Any]:
        return []

    async def stream_turn(self, state: Any) -> AsyncIterator[Any]:
        del state
        raise RuntimeUnavailableError(self.message)
        yield  # pragma: no cover - makes this an async generator


def clone_sub_agent_registry(
    source: SubAgentRegistry,
    llm: LLMProvider,
) -> SubAgentRegistry:
    """Preserve plugin agent types while rebinding the built-in LLM provider."""
    from dataclaw.providers.sub_agent.implementations.default import (
        DefaultSubAgentProvider,
    )

    cloned = SubAgentRegistry()
    for agent_type, provider in source.items():
        if agent_type != "llm":
            cloned.register(provider)
    cloned.register(DefaultSubAgentProvider(llm))
    return cloned


def build_utility_llm(
    backend: str | None = None,
    model: str | None = None,
) -> LLMProvider:
    """Build and validate the DataClaw-owned utility model."""

    from dataclaw.providers.llm.implementations.factory import llm_from_config

    selected_backend = backend or resolve_utility_backend()
    selected_model = model or resolve_utility_model(selected_backend)
    try:
        utility = llm_from_config(
            backend=selected_backend,
            model=selected_model or None,
        )
    except Exception as exc:
        # Includes LLMConfigurationError for a missing API key; the message
        # names the env var / config path and surfaces as the runtime's
        # selection error instead of a silent mock fallback.
        raise RuntimeSelectionError(
            "DataClaw utility model could not initialize "
            f"({selected_backend}/{selected_model or 'no model'}): {exc}"
        ) from exc
    return utility


def build_direct_bundle(
    providers: Any,
    hooks: HookRegistry,
    backend: str | None = None,
) -> RuntimeBundle:
    """Build a fresh DataClaw bundle while preserving plugin registrations."""
    from dataclaw.providers.compaction.implementations.factory import (
        compaction_from_config,
    )
    from dataclaw.providers.memory.implementations.factory import (
        memory_from_config,
    )

    selected_runtime = backend or resolve_agent_runtime()
    if selected_runtime == "mock":
        utility_backend = "mock"
        identity = "mock"
    elif selected_runtime == "dataclaw":
        utility_backend = resolve_utility_backend()
        identity = "dataclaw"
    elif selected_runtime in llm_backend_ids():
        # Compatibility for callers that still pass a direct model backend.
        utility_backend = selected_runtime
        identity = "dataclaw"
    else:
        raise RuntimeSelectionError(
            f"Cannot build DataClaw bundle for runtime {selected_runtime!r}"
        )

    utility_model = (
        None
        if utility_backend == "mock"
        else resolve_utility_model(utility_backend)
    )
    if utility_backend == "mock":
        from dataclaw.providers.llm.implementations.factory import llm_from_config

        llm = llm_from_config(backend="mock")
    else:
        llm = build_utility_llm(utility_backend, utility_model)
    return RuntimeBundle(
        agent=LangChainAgentProvider(llm),
        utility_llm=llm,
        compaction=compaction_from_config(llm),
        tool_availability=providers.tool_availability,
        sub_agent_registry=clone_sub_agent_registry(
            providers.sub_agent_registry, llm
        ),
        sub_agent_hooks=providers.sub_agent_hooks,
        memory=memory_from_config(),
        system_prompt=providers.system_prompt,
        skill=providers.skill,
        hooks=hooks.clone(),
        runtime_control=None,
        identity=RuntimeIdentity(
            runtime=identity,
            model=utility_model or "",
            provider=utility_backend,
        ),
        diagnostics=RuntimeDiagnostics(),
    )


async def build_runtime_bundle(
    providers: Any,
    hooks: HookRegistry,
    backend: str | None = None,
) -> RuntimeBundle:
    """Select a runtime after plugins have registered their factories."""
    selected = backend or resolve_agent_runtime()
    if selected == "dataclaw" or selected in llm_backend_ids():
        return build_direct_bundle(providers, hooks, selected)

    factory = providers.get_runtime_factory(selected)
    if factory is None:
        raise RuntimeSelectionError(
            f"Runtime {selected!r} is selected but its plugin is not installed"
        )
    # External runtimes still need a fresh snapshot of the reloadable core
    # providers. Build that base in the same selection pass so factories do
    # not accidentally capture aliases from the previously active bundle.
    base_bundle = build_direct_bundle(providers, hooks, "dataclaw")
    try:
        result = factory(
            RuntimeFactoryContext(
                providers=providers,
                hooks=hooks,
                backend=selected,
                base_bundle=base_bundle,
            )
        )
        bundle = await result if inspect.isawaitable(result) else result
        if not isinstance(bundle, RuntimeBundle):
            raise RuntimeSelectionError(
                f"Runtime factory {selected!r} did not return RuntimeBundle"
            )
        if bundle.identity.runtime != selected:
            raise RuntimeSelectionError(
                f"Runtime factory {selected!r} returned identity "
                f"{bundle.identity.runtime!r}"
            )
    except Exception:
        await base_bundle.aclose()
        raise
    return bundle


@dataclass
class ActiveRunContext:
    """Process-local state shared by a chat task and callback tasks."""

    run_id: str
    bundle: RuntimeBundle
    owner_active: bool = True
    callbacks: int = 0
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    execution_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    idempotency_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    tool_futures: dict[tuple[str, str], asyncio.Future[dict[str, Any]]] = field(
        default_factory=dict
    )
    tool_identities: dict[tuple[str, str], tuple[str, str]] = field(
        default_factory=dict
    )


class RuntimeManager:
    """Atomically publishes bundles and keeps captured bundles alive."""

    def __init__(
        self,
        providers: Any,
        hooks: HookRegistry,
        initial_bundle: RuntimeBundle,
    ) -> None:
        self.providers = providers
        self.hooks = hooks
        self.active_bundle = initial_bundle
        self.configured_runtime = initial_bundle.identity.runtime
        self.active_runtime = initial_bundle.identity.runtime
        self.last_selection_error: str | None = None
        self._runs: dict[str, ActiveRunContext] = {}
        self._retired: dict[int, RuntimeBundle] = {}
        self._closed: set[int] = set()
        self._lock = asyncio.Lock()
        self._selection_lock = asyncio.Lock()
        providers.publish_bundle(initial_bundle)

    @property
    def diagnostics(self) -> dict[str, Any]:
        return {
            "configured_runtime": self.configured_runtime,
            "active_runtime": self.active_runtime,
            "last_selection_error": self.last_selection_error,
            "available": self.active_bundle.availability,
            "runtime": self.active_bundle.identity.runtime,
            "runtime_diagnostics": {
                "health": self.active_bundle.diagnostics.health,
                "message": self.active_bundle.diagnostics.message,
                **self.active_bundle.diagnostics.details,
            },
        }

    async def select(
        self,
        *,
        backend: str | None = None,
        startup: bool = False,
    ) -> RuntimeBundle:
        async with self._selection_lock:
            return await self._select(backend=backend, startup=startup)

    async def _select(
        self,
        *,
        backend: str | None = None,
        startup: bool = False,
    ) -> RuntimeBundle:
        configured = backend or resolve_agent_runtime()
        self.configured_runtime = configured
        try:
            candidate = await build_runtime_bundle(
                self.providers, self.hooks, configured
            )
        except Exception as exc:
            self.last_selection_error = str(exc)
            if not startup:
                logger.exception(
                    "Runtime reload failed; retaining active runtime %s",
                    self.active_runtime,
                )
                return self.active_bundle

            # Startup must surface the configured runtime as unavailable rather
            # than silently running the provisional Direct bundle.
            provisional = self.active_bundle
            unavailable = RuntimeBundle(
                agent=UnavailableAgentProvider(str(exc)),
                utility_llm=provisional.utility_llm,
                compaction=provisional.compaction,
                tool_availability=provisional.tool_availability,
                sub_agent_registry=provisional.sub_agent_registry,
                sub_agent_hooks=provisional.sub_agent_hooks,
                memory=provisional.memory,
                system_prompt=provisional.system_prompt,
                skill=provisional.skill,
                hooks=provisional.hooks,
                runtime_control=None,
                identity=RuntimeIdentity(runtime=configured),
                diagnostics=RuntimeDiagnostics(
                    health="unavailable", message=str(exc)
                ),
                availability=False,
            )
            await self._swap(unavailable)
            return unavailable

        self.last_selection_error = None
        await self._swap(candidate)
        return candidate

    async def _swap(self, candidate: RuntimeBundle) -> None:
        async with self._lock:
            previous = self.active_bundle
            self.active_bundle = candidate
            self.active_runtime = candidate.identity.runtime
            self.providers.publish_bundle(candidate)
            if previous is not candidate:
                self._retired[id(previous)] = previous
        await self._close_unused_retired()

    def acquire_run(self, run_id: str) -> ActiveRunContext:
        if run_id in self._runs:
            raise RuntimeError(f"Run lease already exists: {run_id}")
        ctx = ActiveRunContext(run_id=run_id, bundle=self.active_bundle)
        self._runs[run_id] = ctx
        return ctx

    def get_run(self, run_id: str) -> ActiveRunContext | None:
        return self._runs.get(run_id)

    @asynccontextmanager
    async def callback_scope(
        self, run_id: str
    ) -> AsyncIterator[ActiveRunContext]:
        ctx = self._runs.get(run_id)
        if ctx is None:
            raise KeyError(run_id)
        ctx.callbacks += 1
        try:
            yield ctx
        finally:
            ctx.callbacks -= 1
            await self._maybe_release(ctx)

    async def release_run(self, run_id: str) -> None:
        ctx = self._runs.get(run_id)
        if ctx is None:
            return
        ctx.owner_active = False
        await self._maybe_release(ctx)

    async def _maybe_release(self, ctx: ActiveRunContext) -> None:
        if ctx.owner_active or ctx.callbacks:
            return
        self._runs.pop(ctx.run_id, None)
        await self._close_unused_retired()

    async def _close_unused_retired(self) -> None:
        in_use = {id(ctx.bundle) for ctx in self._runs.values()}
        closable = [
            (key, bundle)
            for key, bundle in self._retired.items()
            if key not in in_use and key not in self._closed
        ]
        for key, bundle in closable:
            self._closed.add(key)
            self._retired.pop(key, None)
            try:
                await bundle.aclose()
            except Exception:
                logger.exception(
                    "Failed closing retired runtime bundle %s",
                    bundle.identity.runtime,
                )

    async def aclose(self) -> None:
        bundles = [self.active_bundle, *self._retired.values()]
        for bundle in bundles:
            key = id(bundle)
            if key in self._closed:
                continue
            self._closed.add(key)
            await bundle.aclose()
