# @WHO:   scripts/llm/provider.py
# @WHAT:  Multi-provider LLM dispatch — OpenAI / Anthropic / Bedrock / Google / DeepSeek / Z.ai GLM
# @PART:  llm
# @ENTRY: invoke_llm(), resolve_provider(), get_provider()
#
# Issue #63 Phase 1 — provider abstraction.
#
# Dispatch model:
#   provider = resolve_provider(model_name="glm-4.5")  # → "zai_glm"
#   raw_text, stats = invoke_llm(prompt="...", model="glm-4.5", api_key="...")
#
# Provider → model prefix mapping (first match wins, case-insensitive):
#   gpt-*, o1-*, o3-*             → openai
#   claude-*                       → anthropic
#   bedrock-* / amazon.*           → bedrock (AWS)
#   gemini-*                       → google
#   deepseek-*                     → deepseek
#   glm-*, glm4-*, zai-*           → zai_glm
#
# Lazy import per provider:
#   - The provider SDK is only imported when a call actually targets that
#     provider. A user with only the OpenAI SDK installed can still import
#     ``llm`` and dispatch to OpenAI; calls to Anthropic fail with
#     ``ProviderNotInstalledError`` (not ``ImportError`` at module load).
#
# Config:
#   - ``CODELENS_LLM_PROVIDER``  — force a provider (skip prefix dispatch)
#   - ``CODELENS_LLM_MODEL``     — default model name
#   - ``CODELENS_LLM_API_KEY``   — default API key (provider-agnostic fallback)
#   - Per-provider API key env vars also honoured (see ``_PROVIDER_API_KEY_ENV``).
#
# Retry + timeout:
#   - Default 60s per call, 3 retries with exponential backoff (1s, 2s, 4s).
#   - Only retryable errors trigger retry (``LLMError.retryable=True``).
#   - Non-retryable errors (missing config, missing SDK) propagate immediately.

"""Multi-provider LLM dispatch.

The public entry point is :func:`invoke_llm`. Most callers don't need
to call :func:`resolve_provider` or :func:`get_provider` directly —
``invoke_llm`` does it internally and returns the parsed text + telemetry.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Callable, Dict, Optional, Tuple

from utils import logger

from .base_tool import (
    InvocationStats,
    LLMError,
    LLMTimeoutError,
    ProviderNotConfiguredError,
    ProviderNotInstalledError,
)

# ─── Constants ─────────────────────────────────────────────────────────────

DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RETRIES = 3

# Base backoff in seconds for the first retry. Subsequent retries double it
# (1s → 2s → 4s ...). Kept small because LLM timeouts are usually transient.
_BASE_BACKOFF_SECONDS = 1.0

# Provider name → tuple of model-name prefixes (lowercase, no separator).
# First match wins, so put the most specific prefixes first within each tuple.
# (No two providers share a prefix today, but if they ever do, order matters.)
PROVIDER_PREFIX_MAP: Dict[str, Tuple[str, ...]] = {
    "openai": ("gpt-", "o1-", "o3-", "o4-", "chatgpt-"),
    "anthropic": ("claude-",),
    "bedrock": ("bedrock-", "amazon."),
    "google": ("gemini-",),
    "deepseek": ("deepseek-",),
    "zai_glm": ("glm-", "glm4-", "zai-"),
}

# Reverse index: prefix → provider. Built once at import time.
_PREFIX_TO_PROVIDER: Dict[str, str] = {
    prefix: provider
    for provider, prefixes in PROVIDER_PREFIX_MAP.items()
    for prefix in prefixes
}

# Per-provider API key env var names. The first non-empty one wins.
# ``CODELENS_LLM_API_KEY`` is the catch-all fallback for any provider.
_PROVIDER_API_KEY_ENV: Dict[str, Tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY", "CODELENS_LLM_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY", "CODELENS_LLM_API_KEY"),
    "bedrock": ("AWS_ACCESS_KEY_ID", "CODELENS_LLM_API_KEY"),  # secret via AWS_SECRET_ACCESS_KEY
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY", "CODELENS_LLM_API_KEY"),
    "deepseek": ("DEEPSEEK_API_KEY", "CODELENS_LLM_API_KEY"),
    "zai_glm": ("ZAI_API_KEY", "GLM_API_KEY", "CODELENS_LLM_API_KEY"),
}

# Per-provider pip-install name (for the install hint when SDK is missing).
_PROVIDER_PIP_NAME: Dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "bedrock": "boto3",
    "google": "google-generativeai",
    "deepseek": "openai",  # DeepSeek API is OpenAI-compatible — same SDK
    "zai_glm": "openai",   # Z.ai GLM API is OpenAI-compatible — same SDK
}


# ─── Provider resolution ───────────────────────────────────────────────────


def resolve_provider(model_name: str) -> str:
    """Resolve which provider a model name belongs to.

    Dispatch is by prefix (case-insensitive). If no prefix matches,
    raises ``ValueError`` — callers should validate the model name
    before reaching this point.

    The ``CODELENS_LLM_PROVIDER`` env var, when set, overrides this
    function entirely (returns that value verbatim). This lets users
    force a provider even if the model name doesn't match a known prefix
    (e.g. self-hosted OpenAI-compatible endpoints).
    """
    forced = os.environ.get("CODELENS_LLM_PROVIDER", "").strip().lower()
    if forced:
        if forced not in PROVIDER_PREFIX_MAP:
            raise ValueError(
                f"CODELENS_LLM_PROVIDER={forced!r} is not a known provider "
                f"(known: {sorted(PROVIDER_PREFIX_MAP)})"
            )
        return forced

    if not model_name:
        raise ValueError("model_name is required when CODELENS_LLM_PROVIDER is not set")

    lowered = model_name.lower()
    for prefix, provider in _PREFIX_TO_PROVIDER.items():
        if lowered.startswith(prefix):
            return provider

    raise ValueError(
        f"Could not resolve provider for model {model_name!r}. "
        f"Known prefixes: {sorted(_PREFIX_TO_PROVIDER)}. "
        f"Set CODELENS_LLM_PROVIDER to force one."
    )


def get_provider(model_name: str) -> str:
    """Alias for :func:`resolve_provider` — kept for callers that prefer the
    shorter name. Identical behaviour."""
    return resolve_provider(model_name)


# ─── Config helpers ────────────────────────────────────────────────────────


def _resolve_api_key(provider: str, explicit: Optional[str]) -> Optional[str]:
    """Resolve the API key for a provider.

    Order: explicit kwarg > per-provider env var(s) > CODELENS_LLM_API_KEY.
    Returns ``None`` if no key is found.
    """
    if explicit:
        return explicit
    env_names = _PROVIDER_API_KEY_ENV.get(provider, ("CODELENS_LLM_API_KEY",))
    for name in env_names:
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return None


def _resolve_model(explicit: Optional[str]) -> str:
    """Resolve the model name. ``CODELENS_LLM_MODEL`` env var is the fallback."""
    if explicit:
        return explicit
    env_val = os.environ.get("CODELENS_LLM_MODEL", "").strip()
    if env_val:
        return env_val
    raise ProviderNotConfiguredError(
        "No model name configured. Set CODELENS_LLM_MODEL or pass model= explicitly.",
        provider="(unknown)",
        env_var="CODELENS_LLM_MODEL",
    )


# ─── Per-provider call wrappers ────────────────────────────────────────────
#
# Each ``_call_<provider>`` function:
#   - Imports the provider SDK lazily (so a missing SDK doesn't break import
#     of ``provider.py`` — only the call fails).
#   - Builds the request in the SDK's expected shape.
#   - Returns the raw text response.
#   - Raises ``LLMError`` (or subclass) on any failure.
#
# All wrappers take the same kwargs so the dispatch site is uniform:
#   (prompt: str, model: str, api_key: str) -> str


def _call_openai(prompt: str, model: str, api_key: str) -> str:
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise ProviderNotInstalledError(
            f"OpenAI SDK not installed: {e}",
            provider="openai",
            pip_name=_PROVIDER_PIP_NAME["openai"],
        ) from e

    try:
        client = OpenAI(api_key=api_key)
        # ``o1-`` / ``o3-`` reasoning models don't accept ``temperature``;
        # the SDK auto-handles this since v1.40+, but we pass the minimal
        # shape to be safe.
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        # Re-raise non-LLMError exceptions as LLMError so the retry loop
        # can decide whether to retry.
        if isinstance(e, LLMError):
            raise
        raise LLMError(f"[llm.openai] request failed: {e}", retryable=True) from e


def _call_anthropic(prompt: str, model: str, api_key: str) -> str:
    try:
        import anthropic  # type: ignore
    except ImportError as e:
        raise ProviderNotInstalledError(
            f"Anthropic SDK not installed: {e}",
            provider="anthropic",
            pip_name=_PROVIDER_PIP_NAME["anthropic"],
        ) from e

    try:
        client = anthropic.Anthropic(api_key=api_key)
        # Anthropic separates ``max_tokens`` (required) from the prompt.
        # Use 4096 as a sane default — callers can override later via
        # tool subclasses if they need more.
        msg = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        # ``msg.content`` is a list of content blocks; concatenate text blocks.
        parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
        return "".join(parts)
    except Exception as e:
        if isinstance(e, LLMError):
            raise
        raise LLMError(f"[llm.anthropic] request failed: {e}", retryable=True) from e


def _call_bedrock(prompt: str, model: str, api_key: str) -> str:
    """Call AWS Bedrock via boto3.

    Bedrock uses AWS credentials (``AWS_ACCESS_KEY_ID`` +
    ``AWS_SECRET_ACCESS_KEY`` + optional ``AWS_REGION``) rather than a
    single API key. ``api_key`` here is the access key ID; the secret
    must be in ``AWS_SECRET_ACCESS_KEY``.
    """
    try:
        import boto3  # type: ignore
    except ImportError as e:
        raise ProviderNotInstalledError(
            f"boto3 not installed: {e}",
            provider="bedrock",
            pip_name=_PROVIDER_PIP_NAME["bedrock"],
        ) from e

    try:
        region = os.environ.get("AWS_REGION", "us-east-1")
        secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
        if not secret:
            raise ProviderNotConfiguredError(
                "AWS_SECRET_ACCESS_KEY not set (required for Bedrock)",
                provider="bedrock",
                env_var="AWS_SECRET_ACCESS_KEY",
            )
        client = boto3.client(
            "bedrock-runtime",
            region_name=region,
            aws_access_key_id=api_key,
            aws_secret_access_key=secret,
        )
        # Bedrock's InvokeModel API takes a JSON body whose shape depends
        # on the underlying model (Anthropic / Meta / etc.). Strip the
        # ``bedrock-`` prefix to get the real model ID, then send a minimal
        # Anthropic-style payload if the model ID looks like Claude.
        model_id = model[len("bedrock-"):] if model.startswith("bedrock-") else model
        if model_id.startswith("anthropic."):
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": prompt}],
            }
            import json as _json
            resp = client.invoke_model(
                modelId=model_id,
                body=_json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            payload = _json.loads(resp["body"].read())
            parts = [b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text"]
            return "".join(parts)
        # Non-Claude Bedrock models: surface a clear error rather than
        # guess the body shape. Phase 2 can add per-model body builders.
        raise LLMError(
            f"[llm.bedrock] model {model_id!r} body shape not implemented in Phase 1 "
            f"(only anthropic.* models supported).",
            retryable=False,
        )
    except LLMError:
        raise
    except Exception as e:
        raise LLMError(f"[llm.bedrock] request failed: {e}", retryable=True) from e


def _call_google(prompt: str, model: str, api_key: str) -> str:
    try:
        import google.generativeai as genai  # type: ignore
    except ImportError as e:
        raise ProviderNotInstalledError(
            f"google-generativeai SDK not installed: {e}",
            provider="google",
            pip_name=_PROVIDER_PIP_NAME["google"],
        ) from e

    try:
        genai.configure(api_key=api_key)
        gm = genai.GenerativeModel(model)
        resp = gm.generate_content(prompt)
        # ``resp.text`` raises if the response was blocked — fall back to
        # an empty string and let the caller's ``_parse_response`` decide.
        return getattr(resp, "text", "") or ""
    except Exception as e:
        if isinstance(e, LLMError):
            raise
        raise LLMError(f"[llm.google] request failed: {e}", retryable=True) from e


def _call_deepseek(prompt: str, model: str, api_key: str) -> str:
    """DeepSeek's API is OpenAI-compatible — reuse the OpenAI SDK pointed at
    DeepSeek's base URL."""
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise ProviderNotInstalledError(
            f"DeepSeek requires the OpenAI SDK (not installed): {e}",
            provider="deepseek",
            pip_name=_PROVIDER_PIP_NAME["deepseek"],
        ) from e

    try:
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        if isinstance(e, LLMError):
            raise
        raise LLMError(f"[llm.deepseek] request failed: {e}", retryable=True) from e


def _call_zai_glm(prompt: str, model: str, api_key: str) -> str:
    """Z.ai GLM API is OpenAI-compatible — reuse the OpenAI SDK pointed at
    Z.ai's base URL.

    Default base URL: ``https://open.bigmodel.cn/api/paas/v4/``. Override
    via ``ZAI_BASE_URL`` env var for self-hosted endpoints.
    """
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise ProviderNotInstalledError(
            f"Z.ai GLM requires the OpenAI SDK (not installed): {e}",
            provider="zai_glm",
            pip_name=_PROVIDER_PIP_NAME["zai_glm"],
        ) from e

    try:
        base_url = os.environ.get(
            "ZAI_BASE_URL",
            "https://open.bigmodel.cn/api/paas/v4/",
        )
        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        if isinstance(e, LLMError):
            raise
        raise LLMError(f"[llm.zai_glm] request failed: {e}", retryable=True) from e


_PROVIDER_CALL_TABLE: Dict[str, Callable[[str, str, str], str]] = {
    "openai": _call_openai,
    "anthropic": _call_anthropic,
    "bedrock": _call_bedrock,
    "google": _call_google,
    "deepseek": _call_deepseek,
    "zai_glm": _call_zai_glm,
}


# ─── Timeout helper ────────────────────────────────────────────────────────


def _run_with_timeout(fn: Callable[[], str], timeout_seconds: float) -> str:
    """Run ``fn`` in a worker thread with a hard timeout.

    Uses ``ThreadPoolExecutor`` so the timeout works on Windows as well
    as POSIX (``signal.SIGALRM`` is POSIX-only). On timeout, raises
    ``LLMTimeoutError`` — the worker thread continues to completion in
    the background, but the caller is unblocked immediately.

    Why a thread and not ``signal.SIGALRM``? CodeLens must run on
    Windows (see CONTEXT.md / pre-flight SKILL.md), and SIGALRM is
    POSIX-only. The thread-based approach is portable at the cost of
    one idle thread per timed-out call — acceptable for LLM use where
    calls are infrequent and bounded by max_retries.
    """
    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(fn)
        try:
            return future.result(timeout=timeout_seconds)
        except FuturesTimeoutError as e:
            raise LLMTimeoutError(
                f"LLM call exceeded {timeout_seconds}s timeout",
                timeout_seconds=timeout_seconds,
            ) from e


# ─── Public entry point ────────────────────────────────────────────────────


# @FLOW:    LLM_INVOKE
# @CALLS:   _PROVIDER_CALL_TABLE[provider](prompt, model, api_key) -> str
#           _run_with_timeout(call_fn, timeout) -> str
# @MUTATES: none
# @BEHAVIOR: Retries on LLMTimeoutError and any retryable LLMError.
#            Non-retryable errors (ProviderNotConfiguredError,
#            ProviderNotInstalledError) propagate on the first attempt.
#            Returns ``(raw_text, InvocationStats)`` even on the last
#            attempt's success — stats.attempts reflects how many calls
#            were made (1 = first try succeeded, 3 = first two failed).
def invoke_llm(
    *,
    prompt: str,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    max_retries: Optional[int] = None,
) -> Tuple[str, InvocationStats]:
    """Send a prompt to an LLM and return the raw response text + stats.

    Args:
        prompt: The user prompt to send. Required.
        model: Model name (e.g. ``"gpt-4o"``, ``"claude-3-7-sonnet"``,
            ``"glm-4.5"``). Falls back to ``CODELENS_LLM_MODEL`` if omitted.
        api_key: API key for the resolved provider. Falls back to
            provider-specific env vars (e.g. ``OPENAI_API_KEY``) and
            finally ``CODELENS_LLM_API_KEY``.
        provider: Force a provider, bypassing prefix dispatch. Must be a
            key in :data:`PROVIDER_PREFIX_MAP`.
        timeout_seconds: Per-call timeout. Defaults to 60s.
        max_retries: Max attempts (including the first). Defaults to 3.

    Returns:
        ``(raw_text, InvocationStats)``. ``raw_text`` is the model's text
        response; ``stats`` records provider/model/attempts/elapsed.

    Raises:
        ProviderNotConfiguredError: No model / API key configured.
        ProviderNotInstalledError: Provider SDK not importable.
        LLMTimeoutError: All retries exhausted due to timeouts.
        LLMError: All retries exhausted due to other retryable errors.
    """
    if not prompt:
        raise ValueError("prompt is required")

    resolved_model = _resolve_model(model)
    resolved_provider = provider or resolve_provider(resolved_model)
    resolved_timeout = timeout_seconds if timeout_seconds is not None else DEFAULT_TIMEOUT_SECONDS
    resolved_retries = max_retries if max_retries is not None else DEFAULT_MAX_RETRIES

    resolved_key = _resolve_api_key(resolved_provider, api_key)
    if not resolved_key:
        env_hint = " or ".join(_PROVIDER_API_KEY_ENV.get(resolved_provider, ("CODELENS_LLM_API_KEY",)))
        raise ProviderNotConfiguredError(
            f"No API key for provider {resolved_provider!r}. "
            f"Set {env_hint} or pass api_key= explicitly.",
            provider=resolved_provider,
            env_var=env_hint,
        )

    call_fn = _PROVIDER_CALL_TABLE.get(resolved_provider)
    if call_fn is None:  # pragma: no cover — defensive, resolve_provider validates
        raise LLMError(
            f"Provider {resolved_provider!r} has no call wrapper (internal bug).",
            retryable=False,
        )

    start = time.monotonic()
    last_err: Optional[Exception] = None
    timed_out = False
    attempts = 0

    for attempt in range(1, resolved_retries + 1):
        attempts = attempt
        try:
            raw = _run_with_timeout(
                lambda: call_fn(prompt, resolved_model, resolved_key),
                resolved_timeout,
            )
            elapsed = time.monotonic() - start
            stats = InvocationStats(
                provider=resolved_provider,
                model=resolved_model,
                attempts=attempts,
                elapsed_seconds=elapsed,
                timed_out=False,
                raw_response_preview=raw[:200],
            )
            return raw, stats
        except LLMTimeoutError as e:
            last_err = e
            timed_out = True
            logger.warning(
                f"[llm.invoke] attempt {attempt}/{resolved_retries} timed out "
                f"({resolved_timeout}s) for {resolved_provider}/{resolved_model}"
            )
        except LLMError as e:
            last_err = e
            if not e.retryable:
                # Non-retryable: propagate immediately.
                raise
            logger.warning(
                f"[llm.invoke] attempt {attempt}/{resolved_retries} failed "
                f"for {resolved_provider}/{resolved_model}: {e}"
            )
        except Exception as e:
            # Unexpected exception — wrap and propagate as non-retryable.
            last_err = e
            raise LLMError(
                f"[llm.invoke] unexpected error for {resolved_provider}/{resolved_model}: {e}",
                retryable=False,
            ) from e

        # Backoff before the next retry (skip on the last attempt).
        if attempt < resolved_retries:
            backoff = _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
            time.sleep(backoff)

    # All retries exhausted.
    elapsed = time.monotonic() - start
    if timed_out and isinstance(last_err, LLMTimeoutError):
        raise LLMTimeoutError(
            f"LLM call to {resolved_provider}/{resolved_model} timed out "
            f"{resolved_retries}× (last timeout: {resolved_timeout}s)",
            timeout_seconds=resolved_timeout,
        )
    if last_err is None:  # pragma: no cover — defensive
        raise LLMError(
            f"LLM call to {resolved_provider}/{resolved_model} failed with no error captured.",
            retryable=False,
        )
    raise LLMError(
        f"LLM call to {resolved_provider}/{resolved_model} failed after "
        f"{resolved_retries} attempts: {last_err}",
        retryable=False,
    ) from last_err


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_MAX_RETRIES",
    "PROVIDER_PREFIX_MAP",
    "invoke_llm",
    "resolve_provider",
    "get_provider",
]
