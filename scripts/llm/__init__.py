# @WHO:   scripts/llm/__init__.py
# @WHAT:  LLM integration framework package — multi-provider abstraction (issue #63 Phase 1)
# @PART:  llm
# @ENTRY: -
#
# Phase 1 scope (issue #63):
#   - ``base_tool.LLMTool`` ABC + ``LLMToolInput`` / ``LLMToolOutput`` ABCs
#   - ``provider.invoke_llm`` dispatch by ``model_name`` prefix
#   - 6 providers: OpenAI, Anthropic, Bedrock, Google, DeepSeek, Z.ai GLM
#   - Lazy import per provider, 60s timeout, 3-retry exponential backoff
#   - Config via ``CODELENS_LLM_PROVIDER`` / ``CODELENS_LLM_MODEL`` /
#     ``CODELENS_LLM_API_KEY`` env vars
#
# Phases 2-5 (cache, explanation generator, reasoning offload, MCP prompts)
# are deferred to follow-up issues.

"""LLM integration framework for CodeLens.

Re-exported entry points::

    from llm import LLMTool, LLMToolInput, LLMToolOutput, invoke_llm, get_provider

The high-level :func:`invoke_llm` is the only function most callers need.
Subclass :class:`LLMTool` to build a domain-specific tool (e.g. an
``ExplanationGenerator`` in Phase 3); the framework handles provider
dispatch, retry, and timeout.
"""

from .base_tool import (  # noqa: F401
    LLMError,
    LLMTimeoutError,
    LLMTool,
    LLMToolInput,
    LLMToolOutput,
    ProviderNotConfiguredError,
    ProviderNotInstalledError,
)
from .provider import (  # noqa: F401
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_MAX_RETRIES,
    PROVIDER_PREFIX_MAP,
    invoke_llm,
    resolve_provider,
    get_provider,
)

__all__ = [
    "LLMTool",
    "LLMToolInput",
    "LLMToolOutput",
    "LLMError",
    "LLMTimeoutError",
    "ProviderNotConfiguredError",
    "ProviderNotInstalledError",
    "invoke_llm",
    "resolve_provider",
    "get_provider",
    "PROVIDER_PREFIX_MAP",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_MAX_RETRIES",
]
