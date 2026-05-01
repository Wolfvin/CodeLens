---
Task ID: 1
Agent: main
Task: Implement 10 new CodeLens v3 tools (P0-P3)

Work Log:
- Read and analyzed current codebase (codelens.py, registry.py, 11 existing engines)
- Created dataflow_engine.py (P0) - source→sink taint tracking with 5 source types, 5 sink types, 3 sanitizer types
- Created smell_engine.py (P0) - 10 code smell categories with health score
- Created sideeffect_engine.py (P1) - pure vs impure function classification with 7 effect types
- Created refactor_safe_engine.py (P1) - pre-flight rename/move check with 9 risk categories
- Created deadcode_engine.py (P1) - enhanced dead code: unreachable, unused exports, zombie CSS, unused vars, dead listeners
- Created stacktrace_engine.py (P2) - error propagation simulation with handled/unhandled analysis
- Created testmap_engine.py (P2) - test coverage mapping with 4 matching strategies
- Created configdrift_engine.py (P2) - dependency drift detection for Node/Rust/Python
- Created typeinfer_engine.py (P3) - lightweight type inference for JS/Python
- Created ownership_engine.py (P3) - git blame-based code ownership analysis
- Added all 10 new CLI commands with argparse definitions to codelens.py
- Added all 10 dispatch handlers to codelens.py
- Updated version from v2 to v3 in codelens.py description and skill.json
- Updated skill.json version to 3.0.0 with new tags
- Updated SKILL.md with v3 sections, 10 new tool docs, 2 new workflow flows

Stage Summary:
- CodeLens v3 is complete with 27 total CLI commands
- 10 new engine modules created (~4000+ lines total)
- CLI fully integrated with argparse + dispatch for all 27 commands
- Documentation updated (SKILL.md, skill.json)
