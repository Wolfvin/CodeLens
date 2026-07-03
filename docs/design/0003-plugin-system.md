# Design Doc 0003: Plugin System

> **Status:** Accepted
> **Date:** 2026-06-12 (retroactive — backfilled 2026-07-02)
> **Author:** Wolfvin
> **Related issues:** #46 (Semgrep-compat YAML rule engine)
> **Related PRs:** original implementation

---

## Problem

CodeLens shipped with built-in rules for OWASP Top 10 (36 rules) and
compliance (PCI-DSS + HIPAA, 53 rules). But users wanted to add:

- Custom security rules specific to their codebase (e.g., "flag every use
  of our internal `LegacyAuth` class")
- New analysis engines (e.g., a license-compatibility checker)
- Custom output formatters (e.g., a Jira-ticket formatter for findings)
- New CLI commands (e.g., a `deploy-check` command that runs pre-deploy
  quality gates)

Without a plugin system, every custom need required forking CodeLens. This
was unsustainable — users couldn't share customizations, and every CodeLens
update required re-applying forks.

## Goal

Provide a plugin system that:
- Supports four plugin types: `rule_pack`, `engine`, `formatter`, `command`
- Discovers plugins from three locations (priority: project > user > built-in)
- Isolates plugin failures — a broken plugin never crashes CodeLens
- Uses a standard manifest (`plugin.yaml`) so plugins are self-describing
- Allows plugins to be installed from a zip archive (marketplace foundation)

## Changes

### Architecture

```
Plugin discovery (at startup):
  1. .codelens/plugins/        (project-specific, highest priority)
  2. ~/.codelens/plugins/      (user-wide)
  3. scripts/plugins/          (shipped with CodeLens, lowest priority)

Each plugin has:
  plugin.yaml manifest:
    name: my-plugin
    version: 1.0.0
    type: rule_pack | engine | formatter | command
    entry: rules/my_rules.yaml  (for rule_pack)
    entry: my_engine.py         (for engine/formatter/command)
    description: ...
```

### New Files

- `scripts/plugin_system.py` — plugin loader, marketplace foundation (~1460 lines)
- `scripts/commands/plugin.py` — CLI command (`codelens plugin list/install/enable/disable`)
- `scripts/plugins/owasp_top10/plugin.yaml` — built-in OWASP rule pack
- `scripts/plugins/owasp_top10/rules/owasp_top10.yaml` — 36 OWASP rules
- `scripts/plugins/compliance/plugin.yaml` — built-in compliance rule pack
- `scripts/plugins/compliance/rules/pci_dss.yaml` — PCI-DSS rules
- `scripts/plugins/compliance/rules/hipaa.yaml` — HIPAA rules

### Plugin Types

| Type | Entry point | What it does |
|------|-------------|--------------|
| `rule_pack` | YAML file with rules | Adds rules to the rule engine (Semgrep-compat syntax) |
| `engine` | Python module with `analyze()` function | Adds a new analysis engine |
| `formatter` | Python module with `format()` function | Adds a new output format |
| `command` | Python module with `add_args()` + `execute()` | Adds a new CLI command |

### Isolation

Each plugin runs in its own namespace. Exceptions are caught and logged —
a failing plugin produces a warning on stderr but never crashes CodeLens.
This is critical because plugins may be untrusted (installed from
third-party marketplaces).

## Trade-offs

### Alternative A: No plugins — all rules built-in

- **Pros:** Simpler codebase, no plugin loading complexity
- **Cons:** Every custom need requires a fork; users can't share
  customizations; CodeLens becomes a monolith
- **Why rejected:** Unsustainable for a community tool. The OWASP + HIPAA
  rules are useful but every team has domain-specific rules.

### Alternative B: Python entry points (setuptools)

- **Pros:** Standard Python packaging, `pip install` integration
- **Cons:** Requires plugins to be pip-installable packages (too heavy for
  a single YAML rule file), doesn't support project-local plugins
  (`.codelens/plugins/`)
- **Why rejected:** Too heavyweight for the common case (a team wants to
  add one custom YAML rule file without packaging it).

### Alternative C: Dynamic import without manifests

- **Pros:** Simplest implementation — just `importlib.import_module()`
- **Cons:** No metadata (version, description, author), no type safety
  (can't tell if a module is a rule_pack vs engine without inspecting it),
  no marketplace foundation
- **Why rejected:** The manifest (`plugin.yaml`) is what makes plugins
  self-describing and enables future marketplace distribution.

### Chosen approach: YAML manifest + three-tier discovery

- **Why:** Supports the lightest case (drop a YAML file in
  `.codelens/plugins/`) and the heaviest case (install a zip from a
  marketplace). The manifest provides metadata for `codelens plugin list`
  and future marketplace features. Three-tier discovery respects the
  project > user > built-in priority chain.

## Open Questions

- [x] Q1: How to handle plugin versioning and updates? — **Resolved**: the
  `plugin.yaml` has a `version` field; `codelens plugin list` shows
  installed versions. Updates are manual (re-install) for now.
- [x] Q2: How to handle plugin dependencies? — **Resolved**: plugins
  declare dependencies in `plugin.yaml` (`depends_on: [other-plugin]`);
  the loader checks the dependency graph and warns on missing deps.
- [ ] Q3: Should there be a signed-plugin mechanism for untrusted
  marketplaces? — **Open**. Current implementation trusts all plugins
  (they run in-process). A sandboxed execution model (subprocess or WASM)
  would be needed for untrusted plugins.

## Migration / Rollout

The plugin system is additive — existing built-in rules (OWASP, compliance)
were converted to built-in plugins in `scripts/plugins/`. Users who
previously had custom rules in `scripts/rules/` can continue using them
(the rule engine still loads that directory) or migrate them to a
`.codelens/plugins/my-rules/` plugin.

No database migration — plugins are loaded at startup, not persisted.

## References

- Issue: #46 (Semgrep-compat YAML rule engine — Phase 1)
- Prior art: Semgrep's rule packs, ESLint's plugin system, pytest's plugin
  discovery via entry points
- Related design docs: [0001-taint-engine](0001-taint-engine.md) (taint
  rules can be shipped as a `rule_pack` plugin)
