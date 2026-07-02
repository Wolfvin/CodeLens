# LLM Integration Framework (issue #63 Phase 1)

> **Status:** Phase 1 shipped. Phases 2–5 are tracked as follow-up issues.
> **Last updated:** 2026-07-02

## Alasan Dibuat

CodeLens punya banyak fitur yang secara alami bisa di-enhance dengan LLM
reasoning: taint validation (FP check pada path yang dilaporkan sebagai
vulnerable), secret false-positive check, smell justification, dead-code
reason, dan bug explanation. Sebelum Phase 1, setiap fitur yang ingin
memakai LLM harus mengimplementasikan dispatch + retry + timeout-nya
sendiri — duplikasi yang error-prone.

Phase 1 membangun abstraksi tunggal:

- 6 provider (OpenAI / Anthropic / Bedrock / Google / DeepSeek / Z.ai GLM)
- Lazy import per provider (SDK hanya di-import saat benar-benar dipakai)
- 60s timeout, 3-retry exponential backoff (1s → 2s → 4s)
- Config via env vars (`CODELENS_LLM_PROVIDER`, `CODELENS_LLM_MODEL`,
  `CODELENS_LLM_API_KEY`) atau explicit kwargs
- Error model yang membedakan retryable vs non-retryable

## Arsitektur

```
scripts/llm/
├── __init__.py         # Re-exports public API
├── base_tool.py        # LLMTool ABC + LLMToolInput/Output ABCs + errors
└── provider.py         # invoke_llm() + resolve_provider() + 6 _call_* wrappers

scripts/commands/
└── llm_framework.py    # `codelens llm providers|config|ping` command
                        # (file di-nama `llm_framework.py` — bukan `llm.py` —
                        # supaya tidak shadow package `scripts/llm/` saat
                        # `commands/__init__.py` auto-import semua submodule)

tests/
└── test_llm.py         # 73 tests — semua network-free (SDK calls di-mock)
```

## Public API

```python
from llm import (
    # ABCs untuk bikin tool domain-specific
    LLMTool, LLMToolInput, LLMToolOutput,
    # High-level entry point
    invoke_llm,
    # Provider dispatch
    resolve_provider, get_provider,
    # Errors
    LLMError, LLMTimeoutError,
    ProviderNotConfiguredError, ProviderNotInstalledError,
)
```

### Quick example

```python
from dataclasses import dataclass
from llm import LLMTool, LLMToolInput, LLMToolOutput, invoke_llm

@dataclass(frozen=True)
class TaintInput(LLMToolInput):
    bug_type: str
    tainted_value: str

    def __hash__(self): return hash((self.bug_type, self.tainted_value))
    def __eq__(self, other):
        return isinstance(other, TaintInput) and \
            (self.bug_type, self.tainted_value) == (other.bug_type, other.tainted_value)

@dataclass
class TaintOutput(LLMToolOutput):
    is_false_positive: bool
    explanation: str

    def __hash__(self): return hash(self.explanation)
    def __eq__(self, other):
        return isinstance(other, TaintOutput) and self.explanation == other.explanation


class TaintValidator(LLMTool):
    def _get_prompt(self, inp: TaintInput) -> str:
        return f"Is this {inp.bug_type} finding a false positive? Tainted value: {inp.tainted_value}"

    def _parse_response(self, raw: str, inp: TaintInput) -> TaintOutput:
        # Parse the model's reply into a typed output.
        is_fp = "false positive" in raw.lower()
        return TaintOutput(is_false_positive=is_fp, explanation=raw)


# Usage — provider + retry + timeout are handled by the framework.
tool = TaintValidator()  # reads CODELENS_LLM_MODEL + CODELENS_LLM_API_KEY from env
result = tool.invoke(TaintInput(bug_type="SQL injection", tainted_value="user_input"))
print(result.output.is_false_positive)
print(result.stats.attempts, result.stats.elapsed_seconds)
```

Atau langsung tanpa subclass, untuk one-shot call:

```python
from llm import invoke_llm

raw, stats = invoke_llm(
    prompt="Explain this bug: ...",
    model="glm-4.5",      # dispatch ke zai_glm provider
    api_key="...",         # atau set ZAI_API_KEY env var
)
```

## Provider dispatch

Dispatch by model name prefix (case-insensitive, first match wins):

| Prefix                          | Provider    | SDK                |
|---------------------------------|-------------|--------------------|
| `gpt-`, `o1-`, `o3-`, `o4-`, `chatgpt-` | `openai`    | `openai`           |
| `claude-`                       | `anthropic` | `anthropic`        |
| `bedrock-`, `amazon.`           | `bedrock`   | `boto3`            |
| `gemini-`                       | `google`    | `google-generativeai` |
| `deepseek-`                     | `deepseek`  | `openai` (OpenAI-compatible endpoint) |
| `glm-`, `glm4-`, `zai-`         | `zai_glm`   | `openai` (OpenAI-compatible endpoint, base URL `https://open.bigmodel.cn/api/paas/v4/`) |

Force a provider regardless of model name: set `CODELENS_LLM_PROVIDER=openai`
(useful for self-hosted OpenAI-compatible endpoints).

## Config (env vars)

| Variable                  | Purpose                                                     |
|---------------------------|-------------------------------------------------------------|
| `CODELENS_LLM_MODEL`      | Default model name (e.g. `glm-4.5`).                        |
| `CODELENS_LLM_API_KEY`    | Fallback API key for any provider.                          |
| `CODELENS_LLM_PROVIDER`   | Force a provider (skip prefix dispatch).                   |
| `OPENAI_API_KEY`          | OpenAI-specific key (preferred over the fallback).          |
| `ANTHROPIC_API_KEY`       | Anthropic-specific key.                                     |
| `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` + `AWS_REGION` | Bedrock credentials. |
| `GOOGLE_API_KEY` / `GEMINI_API_KEY` | Google-specific key.                              |
| `DEEPSEEK_API_KEY`        | DeepSeek-specific key.                                      |
| `ZAI_API_KEY` / `GLM_API_KEY` | Z.ai GLM-specific key.                                  |
| `ZAI_BASE_URL`            | Override the Z.ai GLM base URL (for self-hosted endpoints). |

API key resolution order: explicit kwarg > provider-specific env var > `CODELENS_LLM_API_KEY`.

## Error model

```
LLMError (base)
├── LLMTimeoutError              — retryable (transient network slowness)
├── ProviderNotConfiguredError   — NOT retryable (missing API key / model)
└── ProviderNotInstalledError    — NOT retryable (SDK not importable)
```

The `LLMError.retryable` flag drives the retry loop. Non-retryable errors
propagate on the first attempt — no point retrying a missing API key.

## CLI command

```bash
# List all 6 providers + their env var hints + SDK pip names
codelens llm providers

# Show currently resolved config (model, provider, which env vars are set)
# — does NOT print API key values, only which env vars have non-empty values
codelens llm config

# Send a 1-token smoke prompt to verify provider + API key + SDK end-to-end
codelens llm ping [--model MODEL] [--provider PROVIDER] [--timeout 15]
```

## Default behaviour

| Setting              | Default            | Override                                |
|----------------------|--------------------|-----------------------------------------|
| Timeout per call     | 60 seconds         | `timeout_seconds=` kwarg                |
| Max retries          | 3 (including first)| `max_retries=` kwarg                    |
| Backoff              | Exponential 1s → 2s → 4s | (not configurable in Phase 1)     |

## Phases 2–5 (deferred)

| Phase | Scope                                                    | Status         |
|-------|----------------------------------------------------------|----------------|
| 2     | Disk cache + cost tracking + `llm-cache` command         | Not started    |
| 3     | `ExplanationGenerator` tool + SARIF embedding            | Not started    |
| 4     | Reasoning offload for `codelens_explore` MCP tool        | Not started    |
| 5     | MCP prompts for rule authoring (`write_custom_codelens_rule`) | Not started |

Phase 2 will add:

- Cache at `~/.codelens/llm_cache/<tool_name>/<input_hash>.json`
- Cache key = SHA-256 of `(tool_name, model_name, input_hash)` —
  invalidates automatically when the model changes
- `codelens llm-cache stats` / `clear` subcommands
- `--no-cache` and `--max-cost-usd N` flags
- Auto-evict entries >30 days
- Thread-safe for concurrent agents

The `LLMToolInput` ABC already requires `__hash__` / `__eq__` so the
Phase 2 cache can key off input objects directly — no API change needed
when the cache lands.

## Testing

```
PYTHONUTF8=1 PYTHONPATH=scripts python3 -m pytest tests/test_llm.py -v
```

73 tests, all network-free. Provider SDK calls are mocked so the tests
run in any environment without API keys or SDKs installed. The tests
verify the framework's *logic* (dispatch, retry, config resolution),
not the SDK call shapes — those are validated by the SDK authors.

## Design decisions

1. **Why `commands/llm_framework.py` instead of `commands/llm.py`?**
   The `commands/__init__.py` auto-imports every `.py` in `commands/`
   via `importlib.import_module`. When the file was named `llm.py`, the
   import shadowed the `scripts/llm/` package — `import llm` resolved
   to `commands/llm.py` (a single module), not the `scripts/llm/`
   package. Renaming the file to `llm_framework.py` fixed the
   collision. The user-facing command name (`codelens llm ...`) is
   unaffected — it's set by `register_command("llm", ...)`.

2. **Why thread-based timeout instead of `signal.SIGALRM`?**
   CodeLens runs on Windows (per CONTEXT.md), and `signal.SIGALRM` is
   POSIX-only. A `ThreadPoolExecutor` with `future.result(timeout=)`
   works on both platforms. The tradeoff is one idle thread per
   timed-out call — acceptable for LLM use where calls are infrequent
   and bounded by `max_retries`.

3. **Why dispatch by prefix, not by an explicit provider field?**
   Most users know the model name (`gpt-4o`, `claude-3-7`, `glm-4.5`)
   but not which "provider" it belongs to. Prefix dispatch makes the
   common case (just set `CODELENS_LLM_MODEL`) work out of the box.
   The `CODELENS_LLM_PROVIDER` env var and `provider=` kwarg exist for
   the edge case where the user knows better (self-hosted endpoints).

4. **Why is the cache deferred to Phase 2?**
   Phase 1 establishes the abstraction contract — `LLMToolInput`
   requires `__hash__` / `__eq__` so cache keys "just work" when the
   cache lands. Building the cache before the abstraction would have
   meant retrofitting it into N callers later. Phase 1 = foundation,
   Phase 2 = persistence.

5. **Why is the default provider "Z.ai GLM"?**
   The issue spec says "Use Z.ai GLM provider as default for CodeLens
   (matches existing `z-ai-web-dev-sdk` integration pattern)." Users
   who want OpenAI just set `CODELENS_LLM_MODEL=gpt-4o`.
