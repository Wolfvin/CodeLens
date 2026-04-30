# CodeLens Skill — Work Log

---
Task ID: 1
Agent: main
Task: Build CodeLens v1 skill (regex-based)

Work Log:
- Created initial skill structure with 5 parsers (regex-based)
- Built CLI with scan/query/list/watch/init commands
- Tested on sample workspace
- All basic features working

Stage Summary:
- v1 shipped with regex parsers for HTML, CSS, JS Frontend, JS Backend, Rust

---
Task ID: 2
Agent: main
Task: Overhaul to CodeLens v2 (Tree-sitter Edition)

Work Log:
- Installed tree-sitter + 6 grammar packages (html, css, js, ts, rust, python)
- Explored AST structures for all languages
- Built base_parser.py — shared tree-sitter parser class with walk/find/inspect utilities
- Built grammar_loader.py — lazy grammar loading with caching
- Built framework_detect.py — auto-detect React, Vue, Svelte, Tailwind, Next.js, Angular from package.json
- Built incremental.py — mtime-based incremental scan support
- Built edge_resolver.py — cross-file function tracking with proper resolution
- Rewrote HTML parser with tree-sitter-html (attribute-based extraction, auto-skip comments)
- Rewrote CSS parser with tree-sitter-css (class_selector, id_selector nodes, @keyframes skip, SCSS fallback)
- Rewrote JS Frontend parser with tree-sitter-javascript (call_expression AST, string arg extraction)
- Rewrote JS Backend parser with tree-sitter-javascript (function_declaration, variable_declarator, arrow_function, call_expression)
- Built TSX parser with tree-sitter-typescript (className extraction from JSX attributes, template literals, ternary, nested expressions; component detection)
- Rewrote Rust parser with tree-sitter-rust (function_item, impl_item, field_expression, scoped_identifier; self.method tracking, trait impl)
- Built Vue SFC parser (template class/:class/id extraction, scoped styles, SCSS/Less support)
- Built Svelte parser (class: directive, scoped styles, :global modifier)
- Built Tailwind detector (utility prefix matching, dynamic pattern flagging, config parsing, @apply tracking)
- Updated registry.py with support for TSX/Vue/Svelte data sources and Tailwind metadata
- Updated codelens.py CLI v2 with incremental scan, detect command, fallback parsers for missing grammars
- Updated SKILL.md, reference docs, setup.sh, skill.json for v2
- Full test on workspace with HTML+CSS+JS+TSX+Rust files:
  - btn-primary: duplicate_ref (2 JS + 1 TSX), duplicate_define (3 CSS)
  - duplicate-id: collision detected correctly
  - verify_token: backend query with caller + unresolved callee
  - processLogin: JS backend with callers + callees (validateUser, generateToken resolved)
  - Modal component: component: true flag, className from TSX
  - Incremental scan: "No changes detected" on unchanged workspace
  - Dead code: 9 entries (4 frontend IDs, 5 backend functions)

Stage Summary:
- CodeLens v2 fully shipped with tree-sitter based parsing
- 8 file types supported: HTML, CSS, JS, TS/TSX, Rust, Vue, Svelte, SCSS/Less
- 6 tree-sitter grammars + regex fallbacks
- Framework auto-detection (React, Vue, Svelte, Tailwind, Next.js, Angular)
- Incremental scan support
- Cross-file edge resolution
- All tests passing
