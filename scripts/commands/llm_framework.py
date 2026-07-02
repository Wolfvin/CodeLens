"""LLM command — inspect LLM framework config and test provider connectivity.

Issue #63 Phase 1. Provides three subcommands::

    codelens llm providers    # list known providers + their env vars
    codelens llm config       # show the currently resolved config (no API key)
    codelens llm ping         # send a 1-token smoke prompt to verify the chain

Why a command and not just tests?
---------------------------------
The LLM framework is opt-in and env-var driven. Users need a way to
answer "did I configure this right?" without reading the source. The
``ping`` subcommand is the canonical end-to-end smoke test — it fails
fast on missing API keys, missing SDKs, and timeouts, with actionable
error messages.

Phase 2 will add ``codelens llm-cache stats`` / ``clear`` here.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional

from commands import register_command


def add_args(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="llm_subcommand")

    p_providers = sub.add_parser(
        "providers",
        help="List known LLM providers and the env vars each one reads.",
    )
    p_providers.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of a human-readable table.",
    )

    p_config = sub.add_parser(
        "config",
        help="Show the currently resolved LLM config (model, provider, key sources).",
    )
    p_config.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of a human-readable block.",
    )

    p_ping = sub.add_parser(
        "ping",
        help="Send a 1-token smoke prompt to verify provider + API key + SDK.",
    )
    p_ping.add_argument(
        "--model",
        default=None,
        help="Model name (defaults to CODELENS_LLM_MODEL).",
    )
    p_ping.add_argument(
        "--provider",
        default=None,
        help="Force a provider (bypass prefix dispatch).",
    )
    p_ping.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Per-call timeout in seconds (default: 15).",
    )
    p_ping.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of a human-readable line.",
    )


def execute(args: argparse.Namespace, workspace: str) -> Dict[str, Any]:
    sub = getattr(args, "llm_subcommand", None)
    if sub is None:
        # No subcommand → behave like `codelens llm config` for discoverability.
        return _cmd_config(json_output=False)
    if sub == "providers":
        return _cmd_providers(json_output=getattr(args, "json", False))
    if sub == "config":
        return _cmd_config(json_output=getattr(args, "json", False))
    if sub == "ping":
        return _cmd_ping(
            model=args.model,
            provider=args.provider,
            timeout=args.timeout,
            json_output=args.json,
        )
    return {
        "status": "error",
        "error": f"unknown llm subcommand: {sub!r}",
        "available": ["providers", "config", "ping"],
    }


# ─── Subcommands ───────────────────────────────────────────────────────────


def _cmd_providers(*, json_output: bool) -> Dict[str, Any]:
    """List the 6 providers + their env var hints + SDK pip names."""
    # Lazy import so the command module is importable even if the llm
    # package itself failed to load (defensive — shouldn't happen).
    try:
        from llm.provider import PROVIDER_PREFIX_MAP, _PROVIDER_API_KEY_ENV, _PROVIDER_PIP_NAME
    except ImportError as e:
        return {
            "status": "error",
            "error": f"llm framework not importable: {e}",
        }

    rows: List[Dict[str, Any]] = []
    for provider in sorted(PROVIDER_PREFIX_MAP):
        prefixes = PROVIDER_PREFIX_MAP[provider]
        env_vars = list(_PROVIDER_API_KEY_ENV.get(provider, ("CODELENS_LLM_API_KEY",)))
        pip_name = _PROVIDER_PIP_NAME.get(provider, "?")
        rows.append({
            "provider": provider,
            "model_prefixes": list(prefixes),
            "api_key_env_vars": env_vars,
            "sdk_pip_name": pip_name,
        })

    if not json_output:
        print("CodeLens LLM providers (issue #63 Phase 1):")
        print()
        for r in rows:
            print(f"  {r['provider']}")
            print(f"    prefixes:    {', '.join(r['model_prefixes'])}")
            print(f"    api_key_env: {' or '.join(r['api_key_env_vars'])}")
            print(f"    sdk_install: pip install {r['sdk_pip_name']}")
            print()

    return {
        "status": "ok",
        "providers": rows,
        "count": len(rows),
    }


def _cmd_config(*, json_output: bool) -> Dict[str, Any]:
    """Show the currently resolved config (model, provider, key source)."""
    try:
        from llm.provider import (
            DEFAULT_MAX_RETRIES,
            DEFAULT_TIMEOUT_SECONDS,
            PROVIDER_PREFIX_MAP,
            _PROVIDER_API_KEY_ENV,
            resolve_provider,
        )
    except ImportError as e:
        return {"status": "error", "error": f"llm framework not importable: {e}"}

    model = os.environ.get("CODELENS_LLM_MODEL", "").strip() or None
    forced_provider = os.environ.get("CODELENS_LLM_PROVIDER", "").strip().lower() or None
    resolved_provider: Optional[str] = None
    resolve_error: Optional[str] = None
    if model:
        try:
            resolved_provider = forced_provider or resolve_provider(model)
        except ValueError as e:
            resolve_error = str(e)
    elif forced_provider:
        resolved_provider = forced_provider

    # Which env vars have values (do NOT print the values themselves).
    key_sources: Dict[str, bool] = {}
    if resolved_provider:
        for var in _PROVIDER_API_KEY_ENV.get(resolved_provider, ("CODELENS_LLM_API_KEY",)):
            key_sources[var] = bool(os.environ.get(var, "").strip())

    config_block = {
        "model": model or "(not set — set CODELENS_LLM_MODEL)",
        "model_env_var": "CODELENS_LLM_MODEL",
        "provider_forced": forced_provider or "(not set)",
        "provider_forced_env_var": "CODELENS_LLM_PROVIDER",
        "provider_resolved": resolved_provider or "(could not resolve)",
        "provider_resolve_error": resolve_error,
        "api_key_sources": key_sources,
        "timeout_seconds_default": DEFAULT_TIMEOUT_SECONDS,
        "max_retries_default": DEFAULT_MAX_RETRIES,
        "known_providers": sorted(PROVIDER_PREFIX_MAP),
    }

    if not json_output:
        print("CodeLens LLM config (issue #63 Phase 1):")
        print()
        for k, v in config_block.items():
            print(f"  {k}: {v}")

    return {"status": "ok", "config": config_block}


def _cmd_ping(
    *,
    model: Optional[str],
    provider: Optional[str],
    timeout: float,
    json_output: bool,
) -> Dict[str, Any]:
    """Send a 1-token smoke prompt to verify the chain end-to-end."""
    try:
        from llm.provider import invoke_llm
        from llm.base_tool import LLMError, ProviderNotConfiguredError, ProviderNotInstalledError
    except ImportError as e:
        return {"status": "error", "error": f"llm framework not importable: {e}"}

    smoke_prompt = "Reply with exactly: OK"
    try:
        raw, stats = invoke_llm(
            prompt=smoke_prompt,
            model=model,
            provider=provider,
            timeout_seconds=timeout,
            max_retries=1,  # ping should fail fast
        )
    except ProviderNotConfiguredError as e:
        msg = f"NOT CONFIGURED: {e} (provider={e.provider}, env_var={e.env_var})"
        if not json_output:
            print(msg, file=sys.stderr)
        return {"status": "not_configured", "error": str(e), "provider": e.provider, "env_var": e.env_var}
    except ProviderNotInstalledError as e:
        msg = f"SDK MISSING: {e} (provider={e.provider}, install with: pip install {e.pip_name})"
        if not json_output:
            print(msg, file=sys.stderr)
        return {"status": "sdk_missing", "error": str(e), "provider": e.provider, "pip_name": e.pip_name}
    except LLMError as e:
        if not json_output:
            print(f"LLM ERROR: {e}", file=sys.stderr)
        return {"status": "error", "error": str(e)}
    except Exception as e:
        if not json_output:
            print(f"UNEXPECTED ERROR: {e}", file=sys.stderr)
        return {"status": "error", "error": f"unexpected: {e}"}

    if not json_output:
        print(
            f"OK — {stats.provider}/{stats.model} "
            f"({stats.attempts} attempt, {stats.elapsed_seconds:.2f}s)"
        )
    return {
        "status": "ok",
        "provider": stats.provider,
        "model": stats.model,
        "attempts": stats.attempts,
        "elapsed_seconds": round(stats.elapsed_seconds, 3),
        "raw_preview": stats.raw_response_preview,
    }


register_command(
    "llm",
    "LLM framework: list providers, show config, ping model (issue #63)",
    add_args,
    execute,
)
