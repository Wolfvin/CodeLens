"""Tests for the LLM integration framework (issue #63 Phase 1).

Scope:

* ``llm.provider.resolve_provider`` — model-name → provider dispatch.
* ``llm.provider.invoke_llm`` — retry semantics, timeout handling,
  config resolution (env vars + explicit kwargs), error propagation.
* ``llm.base_tool.LLMTool`` — ABC contract, ``invoke`` wires prompt
  rendering → provider call → response parsing.
* ``commands.llm_framework`` — CLI registration + subcommand dispatch.

All tests are **network-free**: provider SDK calls are mocked so the
tests run in any environment without API keys or SDKs installed. The
goal is to verify the framework's *logic* (dispatch, retry, config
resolution), not the SDK call shapes — those are validated by the SDK
authors.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Optional
from unittest import mock

import pytest

# ─── Path setup (mirror other tests) ───────────────────────────────────────

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from commands import COMMAND_REGISTRY  # noqa: E402
from llm import (  # noqa: E402
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    PROVIDER_PREFIX_MAP,
    LLMError,
    LLMTimeoutError,
    LLMTool,
    LLMToolInput,
    LLMToolOutput,
    ProviderNotConfiguredError,
    ProviderNotInstalledError,
    invoke_llm,
    resolve_provider,
)
from llm import provider as provider_mod  # noqa: E402
from llm import base_tool as base_tool_mod  # noqa: E402


# ─── Constants ──────────────────────────────────────────────────────────────


ALL_KNOWN_PROVIDERS = {"openai", "anthropic", "bedrock", "google", "deepseek", "zai_glm"}


# ─── Test fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def clean_env(monkeypatch):
    """Strip all LLM env vars so each test starts from a known state.

    Tests that need specific env vars set them via ``monkeypatch.setenv``
    after this fixture runs — later ``setenv`` calls win.
    """
    for var in (
        "CODELENS_LLM_PROVIDER",
        "CODELENS_LLM_MODEL",
        "CODELENS_LLM_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "DEEPSEEK_API_KEY",
        "ZAI_API_KEY",
        "GLM_API_KEY",
        "ZAI_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


# ─── Provider prefix dispatch ───────────────────────────────────────────────


class TestResolveProvider:
    """``resolve_provider`` maps model names to providers by prefix."""

    @pytest.mark.parametrize(
        "model,expected",
        [
            ("gpt-4o", "openai"),
            ("gpt-3.5-turbo", "openai"),
            ("o1-preview", "openai"),
            ("o3-mini", "openai"),
            ("claude-3-7-sonnet", "anthropic"),
            ("claude-opus-4", "anthropic"),
            ("bedrock-anthropic.claude-3", "bedrock"),
            ("amazon.nova-pro", "bedrock"),
            ("gemini-1.5-pro", "google"),
            ("gemini-2.0-flash", "google"),
            ("deepseek-chat", "deepseek"),
            ("deepseek-reasoner", "deepseek"),
            ("glm-4.5", "zai_glm"),
            ("glm4-plus", "zai_glm"),
            ("zai-glm-4", "zai_glm"),
        ],
    )
    def test_known_prefixes(self, clean_env, model, expected):
        assert resolve_provider(model) == expected

    def test_case_insensitive(self, clean_env):
        assert resolve_provider("GPT-4o") == "openai"
        assert resolve_provider("Claude-3-7") == "anthropic"
        assert resolve_provider("GLM-4.5") == "zai_glm"

    def test_unknown_prefix_raises(self, clean_env):
        with pytest.raises(ValueError, match="Could not resolve provider"):
            resolve_provider("some-unknown-model-12345")

    def test_empty_model_raises(self, clean_env):
        with pytest.raises(ValueError, match="model_name is required"):
            resolve_provider("")

    def test_forced_provider_env_var(self, clean_env, monkeypatch):
        monkeypatch.setenv("CODELENS_LLM_PROVIDER", "openai")
        # Even with an unknown model name, the forced provider wins.
        assert resolve_provider("totally-unknown-model") == "openai"

    def test_forced_provider_unknown_raises(self, clean_env, monkeypatch):
        monkeypatch.setenv("CODELENS_LLM_PROVIDER", "not_a_real_provider")
        with pytest.raises(ValueError, match="not a known provider"):
            resolve_provider("gpt-4o")

    def test_all_six_providers_have_prefixes(self, clean_env):
        """All 6 providers from issue #63 must be in the dispatch table."""
        assert set(PROVIDER_PREFIX_MAP.keys()) == ALL_KNOWN_PROVIDERS

    def test_no_two_providers_share_a_prefix(self, clean_env):
        """Prefixes must be unique across providers (no ambiguity)."""
        all_prefixes = []
        for prefixes in PROVIDER_PREFIX_MAP.values():
            all_prefixes.extend(prefixes)
        assert len(all_prefixes) == len(set(all_prefixes)), (
            f"Duplicate prefixes: {all_prefixes}"
        )


# ─── Config resolution ─────────────────────────────────────────────────────


class TestConfigResolution:
    """API key + model resolution order."""

    def test_explicit_api_key_wins(self, clean_env, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        assert provider_mod._resolve_api_key("openai", "explicit-key") == "explicit-key"

    def test_provider_specific_env_var(self, clean_env, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "openai-env-key")
        assert provider_mod._resolve_api_key("openai", None) == "openai-env-key"

    def test_fallback_to_codelens_api_key(self, clean_env, monkeypatch):
        monkeypatch.setenv("CODELENS_LLM_API_KEY", "fallback-key")
        assert provider_mod._resolve_api_key("openai", None) == "fallback-key"

    def test_provider_env_takes_precedence_over_fallback(self, clean_env, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "provider-specific")
        monkeypatch.setenv("CODELENS_LLM_API_KEY", "fallback")
        assert provider_mod._resolve_api_key("openai", None) == "provider-specific"

    def test_no_key_returns_none(self, clean_env):
        assert provider_mod._resolve_api_key("openai", None) is None

    def test_model_explicit_wins(self, clean_env, monkeypatch):
        monkeypatch.setenv("CODELENS_LLM_MODEL", "env-model")
        assert provider_mod._resolve_model("explicit-model") == "explicit-model"

    def test_model_env_fallback(self, clean_env, monkeypatch):
        monkeypatch.setenv("CODELENS_LLM_MODEL", "env-model")
        assert provider_mod._resolve_model(None) == "env-model"

    def test_model_missing_raises_not_configured(self, clean_env):
        with pytest.raises(ProviderNotConfiguredError) as exc_info:
            provider_mod._resolve_model(None)
        assert exc_info.value.env_var == "CODELENS_LLM_MODEL"


# ─── invoke_llm: config errors ─────────────────────────────────────────────


class TestInvokeLlmConfigErrors:
    """``invoke_llm`` must fail fast on config errors."""

    def test_missing_model_raises_not_configured(self, clean_env):
        with pytest.raises(ProviderNotConfiguredError):
            invoke_llm(prompt="hello", api_key="k")

    def test_missing_api_key_raises_not_configured(self, clean_env, monkeypatch):
        monkeypatch.setenv("CODELENS_LLM_MODEL", "glm-4.5")
        with pytest.raises(ProviderNotConfiguredError) as exc_info:
            invoke_llm(prompt="hello")
        # Error must mention the provider + at least one env var name.
        assert exc_info.value.provider == "zai_glm"
        assert "ZAI_API_KEY" in exc_info.value.env_var

    def test_empty_prompt_raises_value_error(self, clean_env, monkeypatch):
        monkeypatch.setenv("CODELENS_LLM_MODEL", "glm-4.5")
        monkeypatch.setenv("ZAI_API_KEY", "k")
        with pytest.raises(ValueError, match="prompt is required"):
            invoke_llm(prompt="", api_key="k", model="glm-4.5")


# ─── invoke_llm: provider dispatch ─────────────────────────────────────────


class TestInvokeLlmDispatch:
    """``invoke_llm`` calls the right provider wrapper."""

    def test_dispatches_to_zai_glm(self, clean_env, monkeypatch):
        captured = {}

        def fake_call(prompt, model, api_key):
            captured["prompt"] = prompt
            captured["model"] = model
            captured["api_key"] = api_key
            return "GLM reply"

        monkeypatch.setattr(provider_mod, "_PROVIDER_CALL_TABLE", {"zai_glm": fake_call})
        monkeypatch.setenv("CODELENS_LLM_MODEL", "glm-4.5")
        raw, stats = invoke_llm(prompt="hi", api_key="k")
        assert raw == "GLM reply"
        assert captured["model"] == "glm-4.5"
        assert captured["api_key"] == "k"
        assert stats.provider == "zai_glm"
        assert stats.attempts == 1
        assert stats.timed_out is False

    def test_dispatches_to_openai_via_prefix(self, clean_env, monkeypatch):
        monkeypatch.setattr(
            provider_mod,
            "_PROVIDER_CALL_TABLE",
            {"openai": lambda p, m, k: "openai reply"},
        )
        raw, stats = invoke_llm(prompt="hi", model="gpt-4o", api_key="k")
        assert raw == "openai reply"
        assert stats.provider == "openai"

    def test_dispatches_to_anthropic_via_prefix(self, clean_env, monkeypatch):
        monkeypatch.setattr(
            provider_mod,
            "_PROVIDER_CALL_TABLE",
            {"anthropic": lambda p, m, k: "anthropic reply"},
        )
        raw, stats = invoke_llm(prompt="hi", model="claude-3-7", api_key="k")
        assert raw == "anthropic reply"
        assert stats.provider == "anthropic"

    def test_explicit_provider_overrides_prefix(self, clean_env, monkeypatch):
        """``provider=`` kwarg bypasses prefix dispatch entirely."""
        monkeypatch.setattr(
            provider_mod,
            "_PROVIDER_CALL_TABLE",
            {"openai": lambda p, m, k: "openai reply"},
        )
        # Use a model name that would normally resolve to anthropic,
        # but force provider=openai.
        raw, stats = invoke_llm(
            prompt="hi",
            model="claude-3-7",
            api_key="k",
            provider="openai",
        )
        assert stats.provider == "openai"


# ─── invoke_llm: retry semantics ───────────────────────────────────────────


class TestInvokeLlmRetry:
    """Retry behaviour: retryable errors trigger retry, non-retryable don't."""

    def test_retries_on_timeout(self, clean_env, monkeypatch):
        call_count = {"n": 0}

        def fake_call(prompt, model, api_key):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise LLMTimeoutError("timeout", timeout_seconds=1.0)
            return "success on attempt 3"

        monkeypatch.setattr(provider_mod, "_PROVIDER_CALL_TABLE", {"zai_glm": fake_call})
        monkeypatch.setattr(provider_mod.time, "sleep", lambda s: None)  # no real backoff
        raw, stats = invoke_llm(
            prompt="hi",
            model="glm-4.5",
            api_key="k",
            max_retries=3,
            timeout_seconds=1.0,
        )
        assert raw == "success on attempt 3"
        assert stats.attempts == 3
        assert call_count["n"] == 3

    def test_gives_up_after_max_retries(self, clean_env, monkeypatch):
        def fake_call(prompt, model, api_key):
            raise LLMTimeoutError("always timeout", timeout_seconds=1.0)

        monkeypatch.setattr(provider_mod, "_PROVIDER_CALL_TABLE", {"zai_glm": fake_call})
        monkeypatch.setattr(provider_mod.time, "sleep", lambda s: None)
        with pytest.raises(LLMTimeoutError, match="timed out"):
            invoke_llm(
                prompt="hi",
                model="glm-4.5",
                api_key="k",
                max_retries=2,
                timeout_seconds=1.0,
            )

    def test_non_retryable_error_propagates_immediately(self, clean_env, monkeypatch):
        call_count = {"n": 0}

        def fake_call(prompt, model, api_key):
            call_count["n"] += 1
            raise ProviderNotInstalledError(
                "missing SDK", provider="zai_glm", pip_name="openai"
            )

        monkeypatch.setattr(provider_mod, "_PROVIDER_CALL_TABLE", {"zai_glm": fake_call})
        with pytest.raises(ProviderNotInstalledError):
            invoke_llm(
                prompt="hi",
                model="glm-4.5",
                api_key="k",
                max_retries=3,
            )
        # Must NOT have retried — non-retryable.
        assert call_count["n"] == 1

    def test_retries_on_retryable_llm_error(self, clean_env, monkeypatch):
        call_count = {"n": 0}

        def fake_call(prompt, model, api_key):
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise LLMError("transient", retryable=True)
            return "ok"

        monkeypatch.setattr(provider_mod, "_PROVIDER_CALL_TABLE", {"zai_glm": fake_call})
        monkeypatch.setattr(provider_mod.time, "sleep", lambda s: None)
        raw, stats = invoke_llm(
            prompt="hi",
            model="glm-4.5",
            api_key="k",
            max_retries=3,
        )
        assert raw == "ok"
        assert stats.attempts == 2

    def test_max_retries_one_means_no_retry(self, clean_env, monkeypatch):
        call_count = {"n": 0}

        def fake_call(prompt, model, api_key):
            call_count["n"] += 1
            raise LLMTimeoutError("timeout", timeout_seconds=1.0)

        monkeypatch.setattr(provider_mod, "_PROVIDER_CALL_TABLE", {"zai_glm": fake_call})
        monkeypatch.setattr(provider_mod.time, "sleep", lambda s: None)
        with pytest.raises(LLMTimeoutError):
            invoke_llm(
                prompt="hi",
                model="glm-4.5",
                api_key="k",
                max_retries=1,
                timeout_seconds=1.0,
            )
        assert call_count["n"] == 1

    def test_backoff_doubles_between_retries(self, clean_env, monkeypatch):
        """Verify exponential backoff: 1s, 2s, 4s, ..."""
        sleeps = []

        def fake_call(prompt, model, api_key):
            raise LLMTimeoutError("timeout", timeout_seconds=1.0)

        monkeypatch.setattr(provider_mod, "_PROVIDER_CALL_TABLE", {"zai_glm": fake_call})
        monkeypatch.setattr(provider_mod.time, "sleep", lambda s: sleeps.append(s))
        with pytest.raises(LLMTimeoutError):
            invoke_llm(
                prompt="hi",
                model="glm-4.5",
                api_key="k",
                max_retries=4,
                timeout_seconds=1.0,
            )
        # 3 sleeps between 4 attempts (no sleep after the last attempt).
        assert sleeps == [1.0, 2.0, 4.0]


# ─── invoke_llm: timeout behaviour ─────────────────────────────────────────


class TestInvokeLlmTimeout:
    """The ``_run_with_timeout`` helper must enforce the timeout."""

    def test_slow_call_raises_timeout(self, clean_env, monkeypatch):
        def slow_call():
            time.sleep(0.5)
            return "should not get here"

        with pytest.raises(LLMTimeoutError) as exc_info:
            provider_mod._run_with_timeout(slow_call, timeout_seconds=0.1)
        assert exc_info.value.timeout_seconds == 0.1

    def test_fast_call_returns_normally(self, clean_env):
        def fast_call():
            return "ok"

        assert provider_mod._run_with_timeout(fast_call, timeout_seconds=5.0) == "ok"


# ─── invoke_llm: stats recording ───────────────────────────────────────────


class TestInvokeLlmStats:
    """``InvocationStats`` records the right fields."""

    def test_stats_contain_provider_and_model(self, clean_env, monkeypatch):
        monkeypatch.setattr(
            provider_mod,
            "_PROVIDER_CALL_TABLE",
            {"zai_glm": lambda p, m, k: "reply"},
        )
        _, stats = invoke_llm(prompt="hi", model="glm-4.5", api_key="k")
        assert stats.provider == "zai_glm"
        assert stats.model == "glm-4.5"
        assert stats.attempts == 1
        assert stats.elapsed_seconds >= 0.0
        assert stats.timed_out is False
        assert stats.raw_response_preview == "reply"

    def test_stats_preview_truncated_to_200_chars(self, clean_env, monkeypatch):
        long_reply = "x" * 500
        monkeypatch.setattr(
            provider_mod,
            "_PROVIDER_CALL_TABLE",
            {"zai_glm": lambda p, m, k: long_reply},
        )
        _, stats = invoke_llm(prompt="hi", model="glm-4.5", api_key="k")
        assert len(stats.raw_response_preview) == 200

    def test_stats_as_dict_round_trips(self, clean_env, monkeypatch):
        monkeypatch.setattr(
            provider_mod,
            "_PROVIDER_CALL_TABLE",
            {"zai_glm": lambda p, m, k: "reply"},
        )
        _, stats = invoke_llm(prompt="hi", model="glm-4.5", api_key="k")
        d = stats.as_dict()
        assert set(d.keys()) == {
            "provider",
            "model",
            "attempts",
            "elapsed_seconds",
            "timed_out",
            "raw_response_preview",
        }


# ─── Provider call wrappers (mocked) ───────────────────────────────────────


class TestProviderCallWrappers:
    """Each ``_call_<provider>`` wrapper handles import + call correctly."""

    def test_openai_missing_sdk_raises_not_installed(self, clean_env, monkeypatch):
        # Force the import to fail.
        monkeypatch.setitem(sys.modules, "openai", None)
        with pytest.raises(ProviderNotInstalledError) as exc_info:
            provider_mod._call_openai("hi", "gpt-4o", "k")
        assert exc_info.value.provider == "openai"
        assert exc_info.value.pip_name == "openai"

    def test_anthropic_missing_sdk_raises_not_installed(self, clean_env, monkeypatch):
        monkeypatch.setitem(sys.modules, "anthropic", None)
        with pytest.raises(ProviderNotInstalledError) as exc_info:
            provider_mod._call_anthropic("hi", "claude-3", "k")
        assert exc_info.value.provider == "anthropic"
        assert exc_info.value.pip_name == "anthropic"

    def test_bedrock_missing_sdk_raises_not_installed(self, clean_env, monkeypatch):
        monkeypatch.setitem(sys.modules, "boto3", None)
        with pytest.raises(ProviderNotInstalledError) as exc_info:
            provider_mod._call_bedrock("hi", "bedrock-anthropic.claude-3", "k")
        assert exc_info.value.provider == "bedrock"
        assert exc_info.value.pip_name == "boto3"

    def test_google_missing_sdk_raises_not_installed(self, clean_env, monkeypatch):
        monkeypatch.setitem(sys.modules, "google", None)
        monkeypatch.setitem(sys.modules, "google.generativeai", None)
        with pytest.raises(ProviderNotInstalledError) as exc_info:
            provider_mod._call_google("hi", "gemini-1.5-pro", "k")
        assert exc_info.value.provider == "google"
        assert exc_info.value.pip_name == "google-generativeai"

    def test_bedrock_missing_secret_raises_not_configured(
        self, clean_env, monkeypatch
    ):
        """Bedrock needs AWS_SECRET_ACCESS_KEY in addition to the access key."""
        # Mock boto3 so we get past the import, then verify the secret check.
        fake_boto3 = mock.MagicMock()
        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
        # No AWS_SECRET_ACCESS_KEY set (clean_env stripped it).
        with pytest.raises(ProviderNotConfiguredError) as exc_info:
            provider_mod._call_bedrock(
                "hi",
                "bedrock-anthropic.claude-3",
                "AKIATEST",
            )
        assert exc_info.value.env_var == "AWS_SECRET_ACCESS_KEY"

    def test_bedrock_non_anthropic_model_raises(self, clean_env, monkeypatch):
        """Phase 1 only supports anthropic.* models on Bedrock."""
        fake_boto3 = mock.MagicMock()
        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
        with pytest.raises(LLMError, match="body shape not implemented"):
            provider_mod._call_bedrock(
                "hi",
                "bedrock-amazon.nova-pro",
                "AKIATEST",
            )

    def test_openai_sdk_exception_wrapped_as_llm_error(
        self, clean_env, monkeypatch
    ):
        """A non-LLMError exception from the SDK becomes a retryable LLMError."""
        fake_openai_mod = mock.MagicMock()
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.side_effect = RuntimeError("API error")
        fake_openai_mod.OpenAI.return_value = fake_client
        monkeypatch.setitem(sys.modules, "openai", fake_openai_mod)
        with pytest.raises(LLMError) as exc_info:
            provider_mod._call_openai("hi", "gpt-4o", "k")
        assert exc_info.value.retryable is True
        assert "[llm.openai]" in str(exc_info.value)

    def test_zai_glm_uses_zai_base_url_env(self, clean_env, monkeypatch):
        """Z.ai GLM respects the ``ZAI_BASE_URL`` override."""
        fake_openai_mod = mock.MagicMock()
        fake_client = mock.MagicMock()
        fake_response = mock.MagicMock()
        fake_response.choices = [mock.MagicMock()]
        fake_response.choices[0].message.content = "glm reply"
        fake_client.chat.completions.create.return_value = fake_response
        fake_openai_mod.OpenAI.return_value = fake_client
        monkeypatch.setitem(sys.modules, "openai", fake_openai_mod)
        monkeypatch.setenv("ZAI_BASE_URL", "https://custom.example.com/v1/")
        provider_mod._call_zai_glm("hi", "glm-4.5", "k")
        fake_openai_mod.OpenAI.assert_called_once()
        _, kwargs = fake_openai_mod.OpenAI.call_args
        assert kwargs["base_url"] == "https://custom.example.com/v1/"

    def test_zai_glm_default_base_url(self, clean_env, monkeypatch):
        fake_openai_mod = mock.MagicMock()
        fake_client = mock.MagicMock()
        fake_response = mock.MagicMock()
        fake_response.choices = [mock.MagicMock()]
        fake_response.choices[0].message.content = "glm reply"
        fake_client.chat.completions.create.return_value = fake_response
        fake_openai_mod.OpenAI.return_value = fake_client
        monkeypatch.setitem(sys.modules, "openai", fake_openai_mod)
        provider_mod._call_zai_glm("hi", "glm-4.5", "k")
        _, kwargs = fake_openai_mod.OpenAI.call_args
        assert "open.bigmodel.cn" in kwargs["base_url"]


# ─── LLMTool ABC ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _FakeInput(LLMToolInput):
    text: str

    def __hash__(self) -> int:
        return hash(self.text)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _FakeInput) and self.text == other.text


@dataclass
class _FakeOutput(LLMToolOutput):
    reply: str

    def __hash__(self) -> int:
        return hash(self.reply)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _FakeOutput) and self.reply == other.reply


class _EchoTool(LLMTool):
    """Test double — echoes the prompt back as the response."""

    def _get_prompt(self, inp: _FakeInput) -> str:
        return f"echo: {inp.text}"

    def _parse_response(self, raw: str, inp: _FakeInput) -> _FakeOutput:
        return _FakeOutput(reply=raw)


class TestLLMTool:
    """The ``LLMTool`` ABC wires prompt → provider → response parsing."""

    def test_invoke_calls_get_prompt_then_parse_response(
        self, clean_env, monkeypatch
    ):
        captured = {}

        def fake_invoke_llm(**kwargs):
            captured["prompt"] = kwargs["prompt"]
            stats = base_tool_mod.InvocationStats(
                provider="zai_glm",
                model="glm-4.5",
                attempts=1,
                elapsed_seconds=0.01,
            )
            return "RAW MODEL OUTPUT", stats

        # Patch the lazy import inside LLMTool.invoke.
        monkeypatch.setattr(
            "llm.provider.invoke_llm", fake_invoke_llm, raising=True
        )

        tool = _EchoTool(model="glm-4.5", api_key="k")
        result = tool.invoke(_FakeInput(text="hello"))
        assert captured["prompt"] == "echo: hello"
        assert result.output.reply == "RAW MODEL OUTPUT"
        assert result.stats.provider == "zai_glm"

    def test_describe_does_not_leak_api_key(self, clean_env):
        tool = _EchoTool(model="glm-4.5", api_key="secret-key-12345")
        desc = tool.describe()
        # API key must never appear in describe() output.
        assert "secret-key-12345" not in str(desc)
        assert desc["model"] == "glm-4.5"
        assert desc["tool"] == "_EchoTool"

    def test_cannot_instantiate_abc_directly(self, clean_env):
        with pytest.raises(TypeError):
            LLMTool()  # type: ignore[abstract]

    def test_subclass_must_implement_get_prompt(self, clean_env):
        class _Incomplete(LLMTool):
            def _parse_response(self, raw, inp):
                return None
        with pytest.raises(TypeError):
            _Incomplete()  # type: ignore[abstract]

    def test_subclass_must_implement_parse_response(self, clean_env):
        class _Incomplete(LLMTool):
            def _get_prompt(self, inp):
                return ""
        with pytest.raises(TypeError):
            _Incomplete()  # type: ignore[abstract]

    def test_frozen_input_is_hashable(self, clean_env):
        """Inputs MUST be hashable so the Phase 2 cache can key off them."""
        inp = _FakeInput(text="hello")
        assert hash(inp) == hash(_FakeInput(text="hello"))
        assert inp == _FakeInput(text="hello")
        assert inp != _FakeInput(text="world")
        # Set membership works (this is what cache keys need).
        assert inp in {_FakeInput(text="hello")}


# ─── CLI command ───────────────────────────────────────────────────────────


class TestLlmCommand:
    """The ``codelens llm`` CLI command is registered and dispatches correctly."""

    def test_command_is_registered(self, clean_env):
        assert "llm" in COMMAND_REGISTRY
        info = COMMAND_REGISTRY["llm"]
        assert callable(info["execute"])
        assert callable(info["add_args"])

    def test_providers_subcommand_returns_six_providers(self, clean_env):
        from commands import llm_framework as cmd
        args = mock.MagicMock()
        args.llm_subcommand = "providers"
        args.json = True
        result = cmd.execute(args, "")
        assert result["status"] == "ok"
        assert result["count"] == 6
        names = {p["provider"] for p in result["providers"]}
        assert names == ALL_KNOWN_PROVIDERS

    def test_config_subcommand_shows_env_state(self, clean_env, monkeypatch):
        from commands import llm_framework as cmd
        monkeypatch.setenv("CODELENS_LLM_MODEL", "glm-4.5")
        monkeypatch.setenv("ZAI_API_KEY", "k")
        args = mock.MagicMock()
        args.llm_subcommand = "config"
        args.json = True
        result = cmd.execute(args, "")
        assert result["status"] == "ok"
        cfg = result["config"]
        assert cfg["model"] == "glm-4.5"
        assert cfg["provider_resolved"] == "zai_glm"
        assert cfg["api_key_sources"]["ZAI_API_KEY"] is True

    def test_config_does_not_leak_api_key_value(self, clean_env, monkeypatch):
        from commands import llm_framework as cmd
        monkeypatch.setenv("CODELENS_LLM_MODEL", "glm-4.5")
        monkeypatch.setenv("ZAI_API_KEY", "secret-value-xyz")
        args = mock.MagicMock()
        args.llm_subcommand = "config"
        args.json = True
        result = cmd.execute(args, "")
        # The actual key value must never appear in the output — only
        # which env vars are set/unset.
        assert "secret-value-xyz" not in str(result)

    def test_ping_subcommand_reports_not_configured(self, clean_env, monkeypatch):
        from commands import llm_framework as cmd
        monkeypatch.setenv("CODELENS_LLM_MODEL", "glm-4.5")
        # No API key set.
        args = mock.MagicMock()
        args.llm_subcommand = "ping"
        args.model = None
        args.provider = None
        args.timeout = 5.0
        args.json = True
        result = cmd.execute(args, "")
        assert result["status"] == "not_configured"
        assert result["provider"] == "zai_glm"

    def test_ping_subcommand_reports_sdk_missing(self, clean_env, monkeypatch):
        from commands import llm_framework as cmd
        monkeypatch.setenv("CODELENS_LLM_MODEL", "glm-4.5")
        monkeypatch.setenv("ZAI_API_KEY", "k")
        # openai SDK is not installed in test env, so we should get sdk_missing.
        args = mock.MagicMock()
        args.llm_subcommand = "ping"
        args.model = None
        args.provider = None
        args.timeout = 5.0
        args.json = True
        result = cmd.execute(args, "")
        assert result["status"] == "sdk_missing"
        assert result["pip_name"] == "openai"

    def test_no_subcommand_defaults_to_config(self, clean_env, monkeypatch):
        from commands import llm_framework as cmd
        args = mock.MagicMock()
        args.llm_subcommand = None
        result = cmd.execute(args, "")
        assert result["status"] == "ok"
        assert "config" in result

    def test_unknown_subcommand_returns_error(self, clean_env):
        from commands import llm_framework as cmd
        args = mock.MagicMock()
        args.llm_subcommand = "bogus"
        result = cmd.execute(args, "")
        assert result["status"] == "error"
        assert "bogus" in result["error"]


# ─── CLI subprocess smoke test ─────────────────────────────────────────────


class TestCLISmoke:
    """End-to-end: invoke ``codelens llm <subcommand>`` as a real subprocess."""

    def _run_cli(self, *extra_args):
        env = os.environ.copy()
        env["PYTHONPATH"] = _SCRIPTS_DIR
        env["PYTHONUTF8"] = "1"
        return subprocess.run(
            [sys.executable, os.path.join(_SCRIPTS_DIR, "codelens.py"), "llm", *extra_args],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

    def test_llm_providers_runs_cleanly(self):
        result = self._run_cli("providers", "--json")
        assert result.returncode == 0, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_llm_config_runs_cleanly(self):
        # Strip all LLM env vars for this subprocess so config is in default state.
        env = os.environ.copy()
        env["PYTHONPATH"] = _SCRIPTS_DIR
        env["PYTHONUTF8"] = "1"
        for var in (
            "CODELENS_LLM_PROVIDER",
            "CODELENS_LLM_MODEL",
            "CODELENS_LLM_API_KEY",
        ):
            env.pop(var, None)
        result = subprocess.run(
            [sys.executable, os.path.join(_SCRIPTS_DIR, "codelens.py"), "llm", "config", "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        assert result.returncode == 0
