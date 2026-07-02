# Design Doc — Plugin System

> **Status:** Accepted
> **Author:** Wolfvin
> **Created:** 2026-06-20 (backfilled 2026-07-02)
> **Related issues:** —
> **Related PRs:** —
> **Implementation plan:** (none — feature shipped before plan convention existed)

## Problem

CodeLens v1 shipped with a fixed set of analysis rules: built-in YAML
security rules in `scripts/rules/python_security.yaml` and
`scripts/rules/javascript_security.yaml`. Three problems emerged:

1. **Users could not add custom rules without forking.** A team with an
   internal coding standard ("all database queries must go through
   `safe_query()`, never raw `cursor.execute()`) had no way to enforce
   that rule with CodeLens. They either forked the repo (painful to
   maintain across upstream releases) or wrote a separate lint tool
   (which meant running two tools, with two config formats, two output
   streams, two CI integrations).

2. **Compliance rules were conflated with security rules.** The built-in
   rules mixed OWASP Top 10 (security) with PCI-DSS / HIPAA (compliance).
   A user who only cared about OWASP had to either tolerate the noise or
   manually filter findings. There was no way to say "run only the
   HIPAA-relevant rules against this codebase."

3. **Engines could not be extended without a release.** A user who wanted
   a custom analysis (e.g., "flag every function that calls a
   microservice without a circuit breaker") had to either wait for
   CodeLens to ship that engine, or fork. There was no extension point
   for third-party engines.

The cost of inaction: every team with a non-default need would either
fork or use a different tool. CodeLens would be "the security scanner
for Python and JS" rather than "the extensible code intelligence
platform" — limiting growth.

## Goal

Ship a plugin system that supports four plugin types (rule_pack, engine,
formatter, command), discovers plugins from three locations
(project-local, user-global, built-in) with deterministic priority, and
isolates plugin failures so a buggy plugin never crashes CodeLens.

### Non-goals

- A plugin marketplace / registry. Plugins are distributed as directories
  or zip files; discovery is filesystem-based. A central registry (like
  npm or PyPI) is out of scope for v1.
- Sandboxed plugin execution. Plugins run in the same Python process as
  CodeLens. A malicious plugin can do anything CodeLens can do. Trust
  model: only install plugins from sources you trust. (Sandboxing via
  subprocess or WASM was considered and rejected as too much complexity
  for v1.)
- Cross-language plugins. Plugins are Python modules. A rule_pack can
  target any language (rules are YAML), but an engine or formatter plugin
  must be Python.
- Plugin versioning beyond `min_codelens_version`. There is no semver
  contract between plugins and CodeLens internals — plugin authors are
  expected to test against the CodeLens version they target.

## Changes

### Surface area

- **New module:** `scripts/plugin_system.py` (~1,463 lines)
  - `class PluginManifest` — parsed `plugin.yaml` representation.
  - `class PluginRule` — a single rule loaded from a rule_pack.
  - `class PluginValidationResult` — manifest validation outcome.
  - `class PluginManager` — discovery, loading, and dispatch.
  - `parse_manifest()`, `validate_manifest()`, `load_rules_from_dir()`
    — public helpers for tooling.
  - `get_plugin_manager()`, `get_plugin_rules()`, `install_plugin()`,
    `list_plugins()` — public API for the `codelens plugin` CLI command.
- **New CLI command:** `codelens plugin <subcommand>`
  - `codelens plugin list` — list installed plugins.
  - `codelens plugin install <source>` — install from path or zip.
  - `codelens plugin validate <dir>` — validate a manifest before install.
  - `codelens plugin rules` — list rules from all active plugins.
- **New built-in plugins:** `scripts/plugins/`
  - `owasp_top10/` — 36 OWASP Top 10 rules (rule_pack type).
  - `compliance/` — 53 compliance rules: HIPAA + PCI-DSS (rule_pack type).
- **Plugin manifest schema:** `plugin.yaml` with fields:
  - `name`, `version`, `type` (rule_pack|engine|formatter|command),
    `description`, `author`, `tags`, `min_codelens_version`
  - type-specific: `rules_dir` (rule_pack), `entrypoint` (engine),
    `formatter_module` (formatter), `command_module` (command)
- **No new dependencies.** YAML parsing was already a dependency. Zip
  install uses stdlib `zipfile`. No external plugin SDK required.

### Data flow

```
CodeLens startup (CLI or MCP server)
       │
       ▼
get_plugin_manager(workspace)
       │
       ├─ discover plugins in priority order:
       │   1. .codelens/plugins/   (project-local, highest priority)
       │   2. ~/.codelens/plugins/ (user-global)
       │   3. scripts/plugins/     (built-in, lowest priority)
       │
       ├─ for each plugin dir:
       │     parse plugin.yaml → PluginManifest
       │     validate: required fields, type-specific fields,
       │                min_codelens_version compatibility
       │     if invalid: log warning, skip (do NOT crash)
       │
       └─ return PluginManager with loaded manifests

When `codelens scan` runs:
       │
       ├─ built-in rules from scripts/rules/*.yaml
       │
       ├─ plugin rules from all rule_pack plugins
       │     (loaded via load_rules_from_dir, deduped by rule id)
       │
       ├─ plugin engines from all engine plugins
       │     (loaded via importlib, called in addition to built-in engines)
       │
       └─ findings merged, de-duplicated by (rule_id, file, line)

When `codelens plugin install <source>` runs:
       │
       ├─ source is a path or zip
       ├─ if zip: extract to tempdir, validate, move to target dir
       ├─ target: .codelens/plugins/ (local) or ~/.codelens/plugins/ (user)
       ├─ validate manifest before install
       └─ on success: log "Installed <name> v<version> to <target>"
          on failure: log error, do not modify filesystem
```

### Touch points

- `scripts/plugin_system.py` — new file (the plugin system itself).
- `scripts/commands/plugin.py` — new command module dispatching
  `codelens plugin list|install|validate|rules`.
- `scripts/plugins/owasp_top10/plugin.yaml` — built-in OWASP plugin
  manifest.
- `scripts/plugins/owasp_top10/rules/owasp_top10.yaml` — 36 rules.
- `scripts/plugins/compliance/plugin.yaml` — built-in compliance plugin
  manifest.
- `scripts/plugins/compliance/rules/hipaa.yaml`, `pci_dss.yaml` — 53 rules.
- `scripts/commands/scan.py` — modified to load plugin rules in addition
  to built-in rules.
- `scripts/commands/rule_test.py`, `scripts/commands/rule_validate.py`
  — modified to operate on plugin rules when `--plugin <name>` is passed.
- `tests/test_command_registry.py` — extended to assert the `plugin`
  command is registered.
- `CONTRIBUTING.md` — new section "Adding New Parsers or Engines"
  updated to mention plugin-first approach for self-contained analysis.

## Trade-offs

- **Option A: No plugins — accept patches only** — users who want custom
  rules submit PRs to the CodeLens repo.
  - Pros: zero new code; all rules reviewed by maintainers.
  - Cons: PR review latency (days to weeks) makes iteration impossible;
    internal/private rules cannot be contributed; the rules directory
    becomes a junk drawer of every team's domain-specific rules.
  - Why rejected: the issue thread on the original feature request had
    12+ users asking for custom rule support. Inaction was not viable.

- **Option B: Adopt Semgrep rule format** — CodeLens rule_pack plugins
  use Semgrep's YAML schema, so users can reuse existing Semgrep rules.
  - Pros: instant access to thousands of community rules; no need to
  invent a schema.
  - Cons: Semgrep's schema is large and includes features CodeLens
    cannot support (e.g., metavariable-pattern with nested patterns)
    without a Semgrep engine; users would write rules that silently
    no-op. Coupling CodeLens to Semgrep's schema also means tracking
    their breaking changes.
  - Why rejected: the schema compatibility surface is too large for v1.
  CodeLens's native rule format covers the 80% case (sources/sinks/
  sanitizers + pattern + message + severity) with a much smaller
  surface. A Semgrep-compatible importer was filed as future work.

- **Option C: Four plugin types with filesystem discovery (chosen)** —
  rule_pack / engine / formatter / command, discovered from
  `.codelens/plugins/`, `~/.codelens/plugins/`, `scripts/plugins/`.
  - Pros: covers the four real extension points; filesystem discovery is
  simple and matches user expectations (drop a directory, restart
  CodeLens, it works); three-tier priority gives teams a "project-local
  overrides user-global overrides built-in" model that mirrors
  `.gitconfig` and is intuitive.
  - Cons: no sandboxing; a buggy plugin can crash CodeLens if the bug is
  in import time (after that, the try/except in dispatch catches
  runtime errors). Plugin authors must know Python to write engine /
  formatter / command plugins (rule_pack plugins are YAML-only).
  - Why chosen: the four-type model maps cleanly to the four extension
  points users actually asked for; the three-tier discovery matches
  industry convention (git, npm, vscode all do this); the
  implementation cost was bounded (~1,400 lines for the loader + CLI).

- **Option D: Dynamic plugin loading via entry points (rejected)** —
  use `importlib.metadata.entry_points` so plugins are pip-installable
  Python packages that register themselves as CodeLens plugins.
  - Pros: plugins can be installed via `pip install codelens-plugin-foo`;
    versioning handled by pip; no manual file management.
  - Cons: requires CodeLens to be pip-installed (which it was not, until
    issue #54 Phase 1 shipped PyPI distribution in PR #144); requires
    plugin authors to publish to PyPI; couples plugin distribution to
    Python packaging, which is hostile to non-Python users (e.g., a
    security team that just wants to drop a YAML file).
  - Why rejected: at design time (v8.0) CodeLens was not pip-installable,
    so entry-point discovery was not viable. The filesystem-based model
    was chosen for v1; entry-point support can be added later as a
    fourth discovery tier without breaking the existing three.

## Open questions

None at design time. Post-implementation follow-ups:

- Plugin sandboxing: a user requested that engine plugins run in a
  subprocess so a crash does not take down CodeLens. Filed as future
  work; no issue yet. The current `try/except` in
  `PluginManager._dispatch_engine()` catches runtime errors but not
  import-time errors or segfaults in C extensions.
- Plugin signing: a user asked for signed plugins (verify GPG signature
  on install). Not implemented; trust model is "only install from
  sources you trust." Tracked as a note in `SECURITY.md`.

## Findings (post-implementation)

Shipped 2026-06-20 in v8.1.0. As of v8.2.0, the built-in plugin
directory ships 2 plugins (owasp_top10, compliance) totaling 89 rules.
No third-party plugins have been published yet, but the install path
has been tested with zip-based plugins up to 50 rules.

One surprise: the `compliance` plugin's `pci_dss.yaml` file is the
single most-edited file in the repo (per `git log --follow`), because
PCI-DSS requirements are revised annually and users submit PRs to
update the rule-to-requirement mapping. This validated the decision to
separate compliance rules from security rules — the compliance file
can churn without affecting the more stable security rules.

The `PluginManager` caches loaded manifests across CLI invocations
within the same MCP server process (via a module-level singleton), but
the cache is per-process — a fresh `codelens plugin list` invocation
re-parses all manifests. For workspaces with 20+ plugins this adds
~200ms to startup. Not yet a problem, but if it becomes one, the fix
is to persist the parsed manifests to SQLite alongside the registry.
