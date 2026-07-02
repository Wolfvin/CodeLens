# @WHO:   scripts/llm/base_tool.py
# @WHAT:  LLMTool ABC + LLMToolInput / LLMToolOutput ABCs — domain-specific LLM tool base
# @PART:  llm
# @ENTRY: LLMTool.invoke()
#
# Issue #63 Phase 1 — LLMTool ABC + provider abstraction.
#
# Design:
# - ``LLMToolInput`` / ``LLMToolOutput`` are ABCs with ``__hash__`` / ``__eq__``
#   so cache keys (Phase 2) work directly off the input object. Subclasses
#   must be immutable dataclasses (frozen=True).
# - ``LLMTool`` is the ABC every domain tool (e.g. Phase 3 ``ExplanationGenerator``)
#   subclasses. It centralises the provider dispatch + retry + timeout
#   logic so subclasses only need to implement ``_get_prompt`` (input →
#   prompt string) and ``_parse_response`` (raw model output → typed output).
# - The actual provider call lives in ``provider.invoke_llm`` — keep
#   ``LLMTool.invoke`` thin so retry behaviour is testable in isolation.
#
# Error model:
# - ``LLMError`` is the base — never raised directly. Use one of the
#   subclasses so callers can do granular ``except`` clauses.
# - ``LLMTimeoutError`` — request exceeded the timeout. Retryable by default.
# - ``ProviderNotConfiguredError`` — no API key / endpoint configured.
#   NOT retryable; caller should report a config error.
# - ``ProviderNotInstalledError`` — provider SDK not importable. NOT
#   retryable; caller should report an install hint.

"""LLMTool ABC + LLMToolInput / LLMToolOutput ABCs.

The framework's contract::

    class MyTool(LLMTool):
        def _get_prompt(self, inp: MyInput) -> str: ...
        def _parse_response(self, raw: str, inp: MyInput) -> MyOutput: ...

    tool = MyTool(model="glm-4.5", api_key="...")
    result = tool.invoke(MyInput(...))   # → MyOutput

``invoke`` is the only public method on subclasses — everything else is
protected. The framework handles provider dispatch, retry, and timeout.
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass
from typing import Any, Dict, Generic, Optional, TypeVar

# ─── Errors ────────────────────────────────────────────────────────────────


class LLMError(Exception):
    """Base error for all LLM framework failures.

    Never raised directly — use one of the subclasses below. All LLM
    framework errors inherit from this so callers can catch the whole
    family with ``except LLMError``.
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLMTimeoutError(LLMError):
    """Request exceeded the per-call timeout.

    Retryable by default (transient network slowness).
    """

    def __init__(self, message: str, *, timeout_seconds: float) -> None:
        super().__init__(message, retryable=True)
        self.timeout_seconds = timeout_seconds


class ProviderNotConfiguredError(LLMError):
    """Provider has no API key / endpoint configured.

    NOT retryable — caller must surface a config hint.
    """

    def __init__(self, message: str, *, provider: str, env_var: str) -> None:
        super().__init__(message, retryable=False)
        self.provider = provider
        self.env_var = env_var


class ProviderNotInstalledError(LLMError):
    """Provider SDK is not importable.

    NOT retryable — caller must surface an install hint.
    """

    def __init__(self, message: str, *, provider: str, pip_name: str) -> None:
        super().__init__(message, retryable=False)
        self.provider = provider
        self.pip_name = pip_name


# ─── Input / Output ABCs ───────────────────────────────────────────────────
#
# Subclasses MUST be frozen dataclasses so __hash__ / __eq__ are stable
# for cache keys (Phase 2). The ABCs themselves don't enforce frozen=True
# because Python's dataclass machinery can't enforce it via ABC, but the
# contract is documented and tested.

InputT = TypeVar("InputT", bound="LLMToolInput")
OutputT = TypeVar("OutputT", bound="LLMToolOutput")


class LLMToolInput(abc.ABC):
    """Abstract base for typed LLM tool inputs.

    Subclasses MUST be ``@dataclass(frozen=True)`` so instances are
    hashable and equality is value-based — this is required for the
    disk cache (Phase 2) to key off the input object directly.

    The framework never inspects fields on the input — it just passes
    it to ``LLMTool._get_prompt`` and ``LLMTool._parse_response``.
    Subclasses are free to model their domain however they like.
    """

    @abc.abstractmethod
    def __hash__(self) -> int:  # pragma: no cover — abstract
        ...

    @abc.abstractmethod
    def __eq__(self, other: object) -> bool:  # pragma: no cover — abstract
        ...


class LLMToolOutput(abc.ABC):
    """Abstract base for typed LLM tool outputs.

    Subclasses are typically ``@dataclass`` (mutable is fine — outputs
    are not used as cache keys). The framework treats the output as
    opaque: it is whatever ``_parse_response`` returns.
    """

    @abc.abstractmethod
    def __hash__(self) -> int:  # pragma: no cover — abstract
        ...

    @abc.abstractmethod
    def __eq__(self, other: object) -> bool:  # pragma: no cover — abstract
        ...


# ─── Invocation metadata ───────────────────────────────────────────────────


@dataclass
class InvocationStats:
    """Per-invocation telemetry, returned alongside the typed output.

    Phase 1 keeps this minimal — Phase 2 will add cache hit/miss,
    Phase 3 will add cost (USD). All fields are populated by
    ``LLMTool.invoke`` and are read-only from the caller's perspective.
    """

    provider: str
    model: str
    attempts: int
    elapsed_seconds: float
    timed_out: bool = False
    raw_response_preview: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "attempts": self.attempts,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "timed_out": self.timed_out,
            "raw_response_preview": self.raw_response_preview,
        }


@dataclass
class InvocationResult(Generic[OutputT]):
    """Wraps the typed output + telemetry for a single invoke call."""

    output: OutputT
    stats: InvocationStats


# ─── LLMTool ABC ───────────────────────────────────────────────────────────


class LLMTool(abc.ABC, Generic[InputT, OutputT]):
    """Abstract base for domain-specific LLM tools.

    Subclasses implement::

        _get_prompt(inp)        -> str            # what to send to the model
        _parse_response(raw, inp) -> OutputT      # how to interpret the reply

    The base class provides ``invoke`` — the single public entry point.
    ``invoke`` resolves the provider from ``model_name``, calls
    ``provider.invoke_llm`` (which handles retry + timeout), then hands
    the raw response to ``_parse_response``.

    Config resolution order (first non-empty wins):
        1. Explicit kwargs to ``__init__`` / ``invoke``
        2. ``CODELENS_LLM_PROVIDER`` / ``CODELENS_LLM_MODEL`` / ``CODELENS_LLM_API_KEY``
        3. Workspace config (``.codelens/codelens.config.json`` — Phase 2)

    Phase 1 deliberately does NOT implement workspace config — env vars
    are sufficient for the abstraction. Workspace config lands with the
    cache layer in Phase 2.
    """

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        provider: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> None:
        self._model_override = model
        self._api_key_override = api_key
        self._provider_override = provider
        self._timeout_override = timeout_seconds
        self._retries_override = max_retries

    # ─── Subclass contract ────────────────────────────────────────

    @abc.abstractmethod
    def _get_prompt(self, inp: InputT) -> str:
        """Render the input as a single prompt string for the model."""

    @abc.abstractmethod
    def _parse_response(self, raw: str, inp: InputT) -> OutputT:
        """Parse the model's raw text response into a typed output."""

    # ─── Public API ───────────────────────────────────────────────

    # @FLOW:    LLM_TOOL_INVOKE
    # @CALLS:   llm.provider.invoke_llm() -> str
    # @MUTATES: none (pure — disk cache lands in Phase 2)
    # @BEHAVIOR: Retryable on LLMTimeoutError / retryable LLMError.
    #            After max_retries attempts, the last error is re-raised.
    #            Non-retryable errors (ProviderNotConfiguredError /
    #            ProviderNotInstalledError) propagate immediately on
    #            the first attempt — no point retrying a missing API key.
    def invoke(self, inp: InputT) -> InvocationResult[OutputT]:
        """Run the tool on the given input.

        Args:
            inp: Typed input — must be a frozen dataclass instance.

        Returns:
            ``InvocationResult`` wrapping the typed output + telemetry.

        Raises:
            LLMError (or subclass) on failure.
        """
        # Lazy import — keeps ``base_tool`` importable without the
        # provider module loaded (helps test isolation).
        from .provider import invoke_llm

        prompt = self._get_prompt(inp)
        raw, stats = invoke_llm(
            prompt=prompt,
            model=self._model_override,
            api_key=self._api_key_override,
            provider=self._provider_override,
            timeout_seconds=self._timeout_override,
            max_retries=self._retries_override,
        )
        output = self._parse_response(raw, inp)
        return InvocationResult(output=output, stats=stats)

    # ─── Introspection (used by `codelens llm config`) ───────────

    def describe(self) -> Dict[str, Any]:
        """Return a JSON-serialisable description of the tool's config.

        Used by ``codelens llm config`` to show what model / provider /
        timeout a tool will use. Does NOT include the API key.
        """
        return {
            "tool": self.__class__.__name__,
            "model": self._model_override or "(env default)",
            "provider": self._provider_override or "(auto from model)",
            "timeout_seconds": self._timeout_override or "(default)",
            "max_retries": self._retries_override or "(default)",
        }


__all__ = [
    "LLMError",
    "LLMTimeoutError",
    "ProviderNotConfiguredError",
    "ProviderNotInstalledError",
    "LLMToolInput",
    "LLMToolOutput",
    "LLMTool",
    "InvocationStats",
    "InvocationResult",
]
