# CodeLens × CodeGraph — Analisis Fitur & Issue Upgrade Plan

> **Repo referensi:** [`colbymchenry/codegraph`](https://github.com/colbymchenry/codegraph) (MIT, npm `@colbymchenry/codegraph` v1.1.2, released 2026-06-28)
> **Repo target:** `Wolfvin/CodeLens` (analisa commit `main` per 2026-06-28)
> **Tanggal analisa:** 2026-06-28
> **Bahasa dokumen:** Indonesia (sesuai input user)
> **Tujuan:** Identifikasi fitur CodeGraph yang bisa diserap ke CodeLens, daftar peningkatan yang *sudah di-adjust*, dan terbitkan template issue GitHub untuk masing-masing gap.

---

## 0. TL;DR — Ringkasan Eksekutif

CodeGraph adalah **AI-native semantic code intelligence** yang sangat dekat niche-nya dengan CodeLens — bahkan lebih dekat daripada opengrep atau UBS. Keduanya:
- AI-native (bukan SAST murni)
- MCP server untuk AI agent
- Tree-sitter powered
- Local-first (no cloud, no API key)
- Pre-write safety / context awareness

**Perbedaan filosofis kunci:**
- **CodeLens** = *command-driven platform* (58 CLI command, 41 engine, MCP 49 tools) — breadth-first, banyak command specialized
- **CodeGraph** = *single-tool philosophy* (1 MCP tool `codegraph_explore`, 17 CLI command) — depth-first, satu tool powerful yang jawab hampir semua question

CodeGraph **lebih matang di beberapa area yang CodeLens masih lemah**, terutama:

1. **Single-tool philosophy** — eksperimen CodeGraph menunjukkan 1 tool kuat > menu tool sempit. Agent less confused, fewer mis-picks. CodeLens saat ini expose 49 MCP tool (terlalu banyak).
2. **Auto-sync dengan native file watcher** (FSEvents/inotify/ReadDirectoryChangesW, debounce 2s, O(1) descriptor di macOS/Windows). CodeLens hanya `watch` command dengan watchdog Python.
3. **Per-file staleness banner** — saat file edited tapi belum re-indexed, response di-prepend `⚠️` banner + nama file. CodeLens tidak ada.
4. **Connect-time catch-up** — saat MCP reconnect, reconciliasi `(size, mtime)` + content-hash vs working tree sebelum answer pertama query. CodeLens tidak ada.
5. **Shared daemon architecture** — 1 daemon per project, N concurrent MCP client, 1 SQLite WAL, 1 inotify set, 1 tree-sitter warm-up. CodeLens setiap session = 1 process.
6. **Worker-thread pool untuk query** — CPU-heavy `codegraph_explore` dijalankan di worker thread, main loop tetap responsive. CodeLens single-threaded.
7. **Worker-thread pool untuk parse** — `codegraph index` parallel across cores, setiap worker punya tree-sitter WASM heap sendiri dengan recycle interval.
8. **WAL mode SQLite + FTS5** built-in — concurrent read tidak pernah block on writer. CodeLens pakai SQLite (di `migrate` command) tapi tanpa WAL explicit.
9. **PPID watchdog cross-platform** — detect parent process death (POSIX: ppid change, Windows: liveness poll). Kill orphan daemon. CodeLens tidak ada.
10. **Liveness watchdog (separate process)** — child process yang SIGKILL parent jika main thread wedged (V8 safepoint issue). CodeLens tidak ada.
11. **Stale stdin teardown** — socketpair stdin `error` event di Windows → destroy stream + shutdown, prevent 100% CPU spin. CodeLens tidak ada.
12. **Tree-sitter WASM** (web-tree-sitter) — universal cross-platform, no native build. CodeLens pakai tree-sitter Python binding (butuh compile native).
13. **8 agent integration** (Claude Code, Cursor, Codex, opencode, Hermes, Gemini, Antigravity, Kiro) dengan `AgentTarget` abstraction (interface-based, add new agent = 1 file + 1 entry registry). CodeLens belum ada installer integration.
14. **`codegraph install --print-config <id>`** — dump MCP config snippet untuk 1 agent, no file write. CodeLens tidak ada.
15. **`codegraph uninstall`** — inverse of install, remove CodeGraph dari semua agent dengan marker-fenced section (idempotent, preserve sibling config). CodeLens tidak ada.
16. **Library API** (npm package, embed di Electron app) — `import CodeGraph from '@colbymchenry/codegraph'`. CodeLens hanya CLI + MCP.
17. **`codegraph upgrade`** — in-place self-update, detect install method (bundle/npm/npx/source). CodeLens tidak ada.
18. **`codegraph affected`** — transitive import dependency trace untuk cari test file affected by changes. CodeLens `dependents` command beda (module-level only, bukan transitive).
19. **Framework-aware routes** (17 framework: Django, Flask, FastAPI, Express, NestJS, Laravel, Drupal, Rails, Spring, Play, Gin/chi/gorilla, Axum/actix/Rocket, ASP.NET, Vapor, React Router, SvelteKit, Vue/Nuxt, Astro). CodeLens `api-map` command hanya support beberapa.
20. **Mixed iOS/RN/Expo bridging** — Swift↔ObjC, RN legacy bridge, TurboModules, Fabric, native→JS events, Expo Modules. CodeLens tidak ada cross-language bridging.
21. **21 dynamic-dispatch synthesizer** — callback edge, observer pattern, EventEmitter, React re-render, JSX children, Flutter setState, C++ virtual, Java/Kotlin interface→impl, Spring @Autowired, Celery/Sidekiq dispatch, MediatR, Redux thunk, Pinia/Vuex store, RTK Query, Laravel event, Spring event, GoFrame, C function pointer, closure collection, object registry. CodeLens `callgraph_engine.py` ada inter-procedural tapi tanpa synthesizer ini.
22. **Dynamic-boundary detection** — saat static path putus, ANNOUNCE boundary honest (form, label, snippet, line, key). 9 form: computed-call, dynamic-import, ruby-send, php-dynamic, reflection, proxy-reflect, typed-bus, var-key-dispatch, selector. CodeLens tidak ada.
23. **Adaptive explore sizing** — output scale dengan project size + skeletonize interchangeable sibling implementations. CodeLens `--top N` lebih simple.
24. **Impact radius dengan blast radius summary** — `codegraph_explore` return source + call path + blast radius (siapa depend + test file coverage) in one call. CodeLens `impact` command separate.
25. **Value reference edges** — edge dari reader symbol ke file-scope `const`/`var` yang dibaca (impact analysis untuk config object/lookup table). CodeLens tidak ada.
26. **Anonymous class extraction** — Java/C# `new T() { ... }` dengan override method di-index sebagai real class node. CodeLens tidak ada.
27. **Interface→implementation linking** — Java/Kotlin/C#/TS/JS/Swift/Scala. CodeLens `callgraph_engine.py` ada inter-procedural tapi bukan interface→impl specific.
28. **Reasoning offload** (opt-in, BYO endpoint) — `codegraph_explore` retrieval local, lalu kirim context + query ke remote OpenAI-compatible model, return tight answer. CodeLens tidak ada.
29. **`codegraph login` device flow** — OAuth-style device authorization (RFC 8628). CodeLens tidak ada auth.
30. **Anonymous telemetry** (opt-in default, public worker code, `DO_NOT_TRACK=1` honored). CodeLens tidak ada telemetry.
31. **110 test files** dengan vitest, integration test di `__tests__/integration/`, evaluation harness di `__tests__/evaluation/`. CodeLens `benchmarks/` lebih simple.
32. **Search quality loop** dengan field-qualified query parser (`kind:function name:auth path:src/api authenticate`). CodeLens `search` hanya regex.
33. **Worktree mismatch detection** — detect jika run dari git worktree tapi resolve main checkout index (branch berbeda). CodeLens tidak ada.
34. **Git sync hooks** (post-commit, post-merge, post-checkout) — saat watcher disabled (WSL2 /mnt), install git hooks sebagai fallback. CodeLens hanya pre-commit hook.
35. **Self-contained binary** (bundled Node runtime, no native build, works on any Node version atau tanpa Node). CodeLens Python dengan `setup.sh`.
36. **`codegraph.json` config** dengan `exclude` (gitignore-style) dan `extensions` (custom file extension mapping). CodeLens hanya `.codelens/codelens.config.json`.
37. **`.gitignore` honored everywhere** — git repo via git, non-git via direct `.gitignore` read. CodeLens hanya `DEFAULT_IGNORE_DIRS` hardcoded.
38. **Generated file detection** — protobuf, gRPC stubs, mocks, build output rank last di search. CodeLens `is_bundled_file()` ada tapi lebih simple.
39. **Multi-platform binary** (6 target: darwin-arm64, darwin-x64, linux-x64, linux-arm64, win32-x64, win32-arm64) dengan SHA256SUMS verification. CodeLens tidak ada binary.
40. **Benchmark dengan 7 real-world codebase** (VS Code, Excalidraw, Django, Tokio, OkHttp, Gin, Alamofire) — 58% fewer tool calls, 22% faster, file reads → ~zero. CodeLens `benchmarks/` hanya akurasi engine, bukan agent benchmark.

**Verdict kunci:** CodeLens dan CodeGraph **direct competitor di niche yang sama**. CodeGraph menang di **architecture (daemon, worker pool, WAL), single-tool philosophy, auto-sync reliability, agent integration, framework coverage, dynamic-dispatch synthesizer, distribution**. CodeLens menang di **command breadth (58 vs 17), security analysis (secrets/taint/CVE/OWASP/compliance), frontend analysis (CSS/a11y/Tailwind), plugin ecosystem (4 tipe)**.

Yang harus diserap: **architecture patterns** (daemon, worker pool, WAL, watcher, staleness banner, catch-up, PPID/liveness watchdog), **single-tool philosophy** (refactor MCP dari 49 → 1-3 tool), **agent integration framework** (AgentTarget abstraction), **dynamic-dispatch synthesizer** (21 pattern), **framework-aware routes** (17 framework), **value reference edges**, **reasoning offload opt-in**, **distribution** (self-contained binary + multi-platform + agent installer/uninstaller).

Detail per-fitur dan issue template ada di Section 4 & 5.

---

## 1. Inventory Fitur CodeLens (recap)

Dari analisa dokumen sebelumnya (CodeLens vs opengrep + UBS), CodeLens punya:
- 58 CLI command (auto-import via `scripts/commands/__init__.py`)
- 41 file `*_engine.py` (avg 500-3700 LOC)
- 11 tree-sitter parser + 25 fallback regex parser (total 41 file)
- MCP server 49 tool (MCP 2025-03-26, JSON-RPC stdio + HTTP/SSE)
- Plugin system 4 tipe (`rule_pack`, `engine`, `formatter`, `command`), 3-tier discovery
- 2 formatter (markdown, sarif v2.1.0)
- OSV.dev integration (9 ecosystem, SQLite cache, native audit fallback)
- 4 GitHub Actions workflow
- 89 rule YAML builtin (OWASP 36 + HIPAA 26 + PCI-DSS 27)
- 4 GitHub Actions workflows
- `guard pre/post/snapshot/verify` command (killer feature)
- Auto-setup zero-config (auto `init` + `scan` jika registry belum ada)
- Workspace auto-detect (walk-up parent + last workspace cache)
- `--format ai` normalized, `--lite` minimal, `--top N`, `--max-tokens N`

CodeLens **belum punya** (yang relevan untuk serapan CodeGraph):
- Single-tool philosophy (49 MCP tool terlalu banyak)
- Auto-sync native file watcher (FSEvents/inotify/ReadDirectoryChangesW)
- Per-file staleness banner
- Connect-time catch-up
- Shared daemon architecture (1 daemon, N client)
- Worker-thread pool untuk query/parse
- WAL mode SQLite explicit
- PPID/liveness watchdog
- Stale stdin teardown
- Tree-sitter WASM (universal cross-platform)
- AgentTarget abstraction (interface-based installer)
- `codegraph install --print-config <id>`
- `codegraph uninstall` (inverse of install)
- Library API (embed di app lain)
- `codegraph upgrade` (in-place self-update)
- `codegraph affected` (transitive test file trace)
- Framework-aware routes (17 framework)
- Mixed iOS/RN/Expo bridging
- Dynamic-dispatch synthesizer (21 pattern)
- Dynamic-boundary detection (9 form)
- Adaptive explore sizing (skeletonize sibling)
- Value reference edges
- Anonymous class extraction
- Interface→implementation linking (multi-language)
- Reasoning offload (BYO endpoint)
- `codegraph login` device flow
- Anonymous telemetry
- Search quality loop dengan field-qualified parser
- Worktree mismatch detection
- Git sync hooks (post-commit/merge/checkout)
- Self-contained binary
- `codegraph.json` config (exclude + extensions)
- `.gitignore` honored everywhere
- Generated file detection (rank last)
- Multi-platform binary (6 target)
- Agent benchmark (7 real-world codebase)

---

## 2. Inventory Fitur CodeGraph

Dihimpun dari `README.md` (791 baris), `CLAUDE.md`, `CHANGELOG.md` (493 baris, v0.8.0 → v1.1.2), `TELEMETRY.md`, `BUNDLING.md`, `package.json`, source code `src/` (TypeScript, ~150 file), `__tests__/` (110 test file), `docs/` (12 design doc + 3 benchmark doc), `scripts/agent-eval/` (40+ eval script), `telemetry-worker/` (Cloudflare Worker).

### 2.1 Arsitektur

| Lapisan | Implementasi | Catatan |
|---|---|---|
| Language | TypeScript 5.x, Node.js 20-24 (bundled 22.5+ untuk `node:sqlite`) | ESM/CJS dual |
| Parser | web-tree-sitter (WASM) — universal cross-platform, no native build | 24 bahasa via .wasm grammar file |
| Storage | SQLite dengan WAL mode + FTS5 full-text search | `node:sqlite` built-in (Node 22.5+) |
| Schema | `src/db/schema.sql` — nodes, edges, files, schema_versions | Migration support |
| Query | `src/db/queries.ts` — prepared statement CRUD | `QueryBuilder` class |
| Graph | `src/graph/{traversal,queries}.ts` — `GraphTraverser`, `GraphQueryManager` | Callers/callees/impact/context |
| Extraction | `src/extraction/` — `ExtractionOrchestrator`, `parse-pool.ts` (worker thread pool), `parse-worker.ts` | Multi-core parse |
| Resolution | `src/resolution/` — import-resolver, name-matcher, path-aliases, 21 synthesizer | Cross-file + dynamic dispatch |
| Framework | `src/resolution/frameworks/` — 23 framework resolver | Route + handler linking |
| Context | `src/context/` — builder + formatter + markers | Markdown/JSON output |
| Search | `src/search/{query-parser,query-utils}.ts` — field-qualified parser + FTS5 | `kind:function name:auth path:src/api` |
| Sync | `src/sync/{watcher,git-hooks,worktree,watch-policy,index.ts}` | Native OS file events |
| MCP | `src/mcp/` — 19 file (engine, daemon, proxy, session, transport, tools, query-pool, ppid-watchdog, liveness-watchdog, stdin-teardown, daemon-registry, daemon-manager, daemon-paths, server-instructions, dynamic-boundaries, version) | stdio + socket |
| Installer | `src/installer/` — `index.ts` + `targets/` (8 agent + registry + types + shared) + `instructions-template.ts` + `config-writer.ts` | Multi-target, idempotent |
| Reasoning | `src/reasoning/` — `reasoner.ts`, `config.ts`, `login.ts`, `credentials.ts` | BYO endpoint opt-in |
| Telemetry | `src/telemetry/index.ts` + `telemetry-worker/` (Cloudflare Worker, public code) | Anonymous, opt-out |
| Upgrade | `src/upgrade/index.ts` — detect install method, in-place update | bundle/npm/npx/source |
| CLI | `src/bin/codegraph.ts` — commander.js | 17 command |
| Tests | `__tests__/` — 110 .test.ts (vitest) + `integration/` + `evaluation/` | Unit + integration + eval |
| Build | `scripts/build-bundle.sh` — self-contained bundle per platform | 6 target |
| Distribution | npm + curl install (install.sh/install.ps1) + GitHub Releases (SHA256SUMS) | Multi-channel |

### 2.2 Bahasa yang didukung (24 bahasa)

TypeScript, JavaScript, Python, Go, Rust, Java, C#, PHP, Ruby, C, C++, Objective-C (partial), Swift, Kotlin, Scala, Dart, Svelte, Vue, Astro, Liquid, Pascal/Delphi, Lua, R, Luau.

Untuk **masing-masing bahasa**, ada dedicated extractor di `src/extraction/languages/<lang>.ts` (16 file) + tree-sitter WASM grammar di `src/extraction/wasm/`.

**Measured cross-file coverage** (dari README, real benchmark per bahasa):
- TypeScript/JS: 95.8% (this repo)
- Python: 100% (psf/requests)
- Go: 96.6% (gin-gonic/gin)
- Rust: 86.7% (BurntSushi/ripgrep)
- Java: 93.3% (google/gson)
- C#: 85.2% (jbogard/MediatR)
- PHP: 100% (guzzle/guzzle)
- Ruby: 100% (sidekiq/sidekiq)
- C: 92.2% (redis/redis)
- C++: 94.8% (google/leveldb)
- ObjC: 91.6% (SDWebImage)
- Swift: 95.3% (Alamofire)
- Kotlin: 96.2% (square/okhttp)
- Scala: 91.2% (gatling/gatling)
- Dart: 92.4% (flutter/packages)
- Svelte: 100% (sveltejs/realworld)
- Vue: 93.5% (nuxt/movies)
- Astro: 93.0% (xingwangzhe/stalux)
- Lua: 84.2% (nvim-telescope/telescope.nvim)
- Luau: 92.2% (dphfox/Fusion)
- Liquid: 73.8% (Shopify/dawn)
- Pascal: 77.4% (PascalCoin)

### 2.3 Framework-aware routes (17 framework)

| Framework | Shapes recognized |
|---|---|
| Django | `path()`, `re_path()`, `url()`, `include()` in `urls.py` (CBV `.as_view()`, dotted paths) |
| Flask | `@app.route('/path', methods=[...])`, blueprint routes |
| FastAPI | `@app.get(...)`, `@router.post(...)`, all standard methods |
| Express | `app.get(...)`, `router.post(...)` with middleware chains |
| NestJS | `@Controller` + `@Get/@Post/...`, GraphQL `@Resolver` + `@Query/@Mutation`, `@MessagePattern`/`@EventPattern`, `@SubscribeMessage` |
| Laravel | `Route::get()`, `Route::resource()`, `Controller@action`, tuple syntax |
| Drupal | `*.routing.yml` routes (`_controller`, `_form`, entity handlers); `hook_*` implementations |
| Rails | `get '/x', to: 'users#index'`, hash-rocket `=>` syntax |
| Spring | `@GetMapping`, `@PostMapping`, `@RequestMapping` on methods |
| Play | `GET`/`POST`/… verb routes in `conf/routes` → `Controller.method` actions (Scala + Java) |
| Gin / chi / gorilla / mux | `r.GET(...)`, `router.HandleFunc(...)` |
| Axum / actix / Rocket | `.route("/x", get(handler))` |
| ASP.NET | `[HttpGet("/x")]` attributes on action methods |
| Vapor | `app.get("x", use: handler)` |
| React Router / SvelteKit | Route component nodes |
| Vue Router / Nuxt | `pages/` file-based routes, `server/api/` endpoints, route middleware |
| Astro | `src/pages/` file-based routes (`.astro` pages + `.ts` endpoints, `[param]`/`[...rest]` syntax) |

### 2.4 Mixed iOS / React Native / Expo bridging

Cross-language bridging yang tree-sitter alone tidak bisa:

| Boundary | JS/Swift side | Native side | How |
|---|---|---|---|
| Swift → ObjC | `obj.foo(bar:)` | `-fooWithBar:` | `@objc` auto-bridging + Cocoa preposition prefixes |
| ObjC → Swift | `[obj fooWithBar:]` | `@objc func foo(bar:)` | Reverse-bridge name candidates |
| RN legacy bridge | `NativeModules.X.fn(...)` | `RCT_EXPORT_METHOD` / `@ReactMethod` | Macro/annotation → JS-name map |
| RN TurboModules | `import M from './NativeM'; M.fn(...)` | Native impl (Codegen spec) | Spec interface as ground truth |
| RN native → JS events | `new NativeEventEmitter(...).addListener('e', cb)` | `sendEventWithName:@"e" body:...` | Synthesized event channel by literal name |
| Expo Modules | `requireNativeModule('X').fn(...)` | `Module { Name("X"); AsyncFunction("fn") }` | Parses Expo DSL literals |
| Fabric view components | `<MyView prop={v}/>` | TS Codegen spec + native impl | Spec → component node + name+suffix lookup |
| Legacy Paper view managers | `<MyView prop={v}/>` | `RCT_EXPORT_VIEW_PROPERTY` / `@ReactProp` | Same as Fabric |

Validated di real codebase (small + medium + large per bridge): Charts, realm-swift, Wikipedia-iOS, AsyncStorage, react-native-svg, react-native-firebase, RNGeolocation, expo-haptics, expo-camera, expo SDK, react-native-segmented-control, react-native-screens, react-native-skia.

### 2.5 Dynamic-dispatch synthesizer (21 pattern)

Dari `src/resolution/` + `__tests__/` (21 test file `*-synthesizer.test.ts`):

1. **Callback edge** — field-backed observer + string-keyed EventEmitter
2. **C function pointer** — `(*fn_ptr)(arg)` dispatch
3. **Celery dispatch** — Python `celery.send_task` / `@app.task`
4. **Sidekiq dispatch** — Ruby `Sidekiq::Worker.perform_async`
5. **Spring event** — `ApplicationEventPublisher.publishEvent` + `@EventListener`
6. **MediatR dispatch** — C# `IMediator.Send(new Command())` + `IRequestHandler`
7. **Laravel event** — `event(new MyEvent)` + `Listener::class`
8. **Pinia store** — Vue `defineStore` dengan state/getters/actions
9. **Vuex dispatch** — Vue `store.dispatch('action')`
10. **Redux thunk** — `dispatch(thunk())` + `createAsyncThunk`
11. **RTK Query** — Redux Toolkit `createApi` endpoint
12. **Closure collection** — `validators.append(closure)` + iterate later
13. **Object registry** — `registry['name'] = impl` + lookup
14. **GoFrame route** — Go `goframe` framework routing
15. **React re-render** — `setState` → `render` (Flutter `setState` → `build` juga)
16. **JSX children** — component tree traversal
17. **C++ virtual override** — virtual dispatch resolution
18. **Java/Kotlin interface→impl** — `@Autowired` service calls
19. **Gin middleware chain** — `.Use()` chain
20. **Swift handler array** — `.validate { ... }` closures
21. **Anonymous class override** — `new T() { ... }` method override

### 2.6 Dynamic-boundary detection (9 form)

Saat static path putus, `codegraph_explore` ANNOUNCE boundary honest (no guess):

| Form | Label | Example |
|---|---|---|
| `computed-call` | computed member call | `obj[method]()` |
| `dynamic-import` | dynamic import | `require(name)` / `import(name)` |
| `ruby-send` | send dispatch | `obj.send(:method)` |
| `php-dynamic` | dynamic call | `$obj->$method()` |
| `reflection` | reflective dispatch | `Method.invoke(target)` |
| `proxy-reflect` | Proxy/Reflect dispatch | `new Proxy(target, handler)` |
| `typed-bus` | typed message dispatch | `Send(new CreateCmd(...))` |
| `var-key-dispatch` | string-keyed dispatch (runtime key) | `handlers[varName]()` |
| `selector` | selector dispatch | `performSelector:` |

Setiap boundary match: `form`, `label`, `snippet` (1-line), `line` (1-based), `key?` (static-visible dispatch key), `keyIsType?` (untuk typed-bus), `moreSites?` (additional sites same form+key).

### 2.7 MCP server (1 tool philosophy)

**Default: 1 tool** — `codegraph_explore`. Measured agent behavior: 1 strong tool > menu of narrower tools (fewer mis-picks, save context).

`codegraph_explore` return dalam 1 call:
- Verbatim line-numbered source dari relevant symbols (grouped by file, Read-equivalent)
- Call path antara symbols (termasuk dynamic-dispatch hops)
- Blast radius summary (siapa depend + test file coverage)

Other tools (`codegraph_node`, `codegraph_search`, `codegraph_callers`, `codegraph_callees`, `codegraph_impact`, `codegraph_files`, `codegraph_status`) tetap functional tapi **unlisted by default**. Re-enable via `CODEGRAPH_MCP_TOOLS=explore,node,search,callers`.

Server instructions (`src/mcp/server-instructions.ts`, 70 baris) dikirim di MCP `initialize` response — single source of truth, anti-pattern guidance ("don't re-verify with grep", "don't reconstruct flow by hand", "check staleness banner after edits").

### 2.8 Auto-sync 3-layer

1. **File watcher dengan debounced auto-sync**:
   - macOS: SINGLE recursive `fs.watch(root, {recursive:true})` → 1 FSEvents stream, O(1) descriptor
   - Windows: SINGLE recursive → 1 ReadDirectoryChangesW handle, O(1)
   - Linux: per-directory inotify watch (O(directories), NOT O(files)), with watch cap
   - Debounce: `CODEGRAPH_WATCH_DEBOUNCE_MS` (default 2000ms, clamped [100ms, 60s])
   - Burst of edits collapse into single sync

2. **Per-file staleness banner**:
   - Saat debounce window, MCP response yang reference pending file → prepend `⚠️ Some files referenced below were edited since the last index sync…`
   - Pending file yang TIDAK di-reference → surface as small footer
   - Agent gets explicit signal → `Read` file tersebut directly

3. **Connect-time catch-up**:
   - Saat MCP server (re)connects, run fast `(size, mtime)` + content-hash reconciliation vs working tree
   - Absorb edits made while no MCP server running (`git pull` dari terminal, editor lain, previous session exited)
   - First query reflects current code

### 2.9 Shared daemon architecture

`src/mcp/daemon.ts` + `proxy.ts` + `daemon-registry.ts` + `daemon-manager.ts`:

- 1 detached `codegraph serve --mcp` daemon per project root
- Accept N concurrent MCP client over Unix-domain socket (atau named pipe di Windows)
- Setiap connection = 1 `MCPSession`, semua share 1 `MCPEngine`
- 1 engine = 1 file watcher (1 inotify set), 1 SQLite connection (1 WAL writer), 1 tree-sitter warm-up
- Daemon detached (bukan child dari MCP host) → close 1 terminal tidak take down lainnya
- Idle timeout: `CODEGRAPH_DAEMON_IDLE_TIMEOUT_MS` (default 300s) → exit cleanly setelah last client disconnect
- Version-pinned: upgrade CodeGraph tidak mix versions over connection
- `CODEGRAPH_NO_DAEMON=1` opt-out (1 independent server per client)
- Daemon registry di `~/.codegraph/daemons/` (global, hash-sha256 dari project root path)
- `codegraph daemon` / `codegraph daemons` command — list + stop interactive

### 2.10 Worker-thread pool

**Query pool** (`src/mcp/query-pool.ts`):
- CPU-heavy `codegraph_explore` dijalankan di worker thread
- Main event loop tetap responsive (MCP transport tidak starve)
- Lazy growth: 1 warm worker on construct, grows to `size` on demand
- Crash recovery: dead worker respawned, in-flight call retried once
- Poison call yang keeps crashing → fail gracefully (never wedge pool), circuit breaker (`healthy` → false)
- Soft timeout: call yang tidak ter-served dalam `softTimeoutMs` → SUCCESS-shaped "busy, retry" guidance (never `isError`)
- `CODEGRAPH_QUERY_POOL_SIZE=0` disable

**Parse pool** (`src/extraction/parse-pool.ts`):
- `codegraph index` parallel across cores
- Setiap worker punya tree-sitter WASM heap sendiri
- Per-worker recycle: WASM linear memory grows but never shrinks, jadi recycle setelah `recycleInterval` parses
- Reject, don't retry: parse yang crash → REJECT dengan message yang orchestrator's retry pass recognize
- Two-stage retry: fresh worker, then comment-stripped (clean WASM heap)
- `CODEGRAPH_PARSE_WORKERS=1` reproduce old single-worker path (conservative rollback)

### 2.11 Watchdog stack (3 layer)

1. **PPID watchdog** (`src/mcp/ppid-watchdog.ts`):
   - POSIX: `process.ppid` changes saat parent dies (reparent ke init pid 1)
   - Windows: poll original parent's liveness (Windows never reparents)
   - Default poll: `CODEGRAPH_PPID_POLL_MS` (5000ms)
   - Kill orphan proxy/server promptly

2. **Liveness watchdog** (`src/mcp/liveness-watchdog.ts`):
   - Separate PROCESS (bukan worker thread — V8 safepoint issue)
   - Parent writes heartbeat byte ke child's stdin setiap `checkMs`
   - Child resets kill-timer on each byte; if none for `timeoutMs` → SIGKILL parent
   - Default timeout: `CODEGRAPH_WATCHDOG_TIMEOUT_MS`
   - Opt-out: `CODEGRAPH_NO_WATCHDOG=1`
   - Catches: V8 stack-format pathology, runaway regex, accidental `while (true)`

3. **Stale stdin teardown** (`src/mcp/stdin-teardown.ts`):
   - Listen for stdin `error` event (bukan hanya `end`/`close`)
   - Socket-backed stdin (VS Code/Claude Code socketpair) → `error` (ECONNRESET) saat client dies
   - Without `error` listener → Node escalates ke `uncaughtException` → process orphaned
   - Linux: `POLLHUP` socket fd di epoll → 100% CPU spin
   - Fix: DESTROY stdin stream on terminal event → fd leave epoll → shutdown

### 2.12 Installer: AgentTarget abstraction

`src/installer/targets/types.ts` — interface-based, add new agent = 1 file + 1 entry registry:

```typescript
interface AgentTarget {
  readonly id: TargetId;
  readonly displayName: string;
  readonly docsUrl?: string;
  supportsLocation(loc: Location): boolean;
  detect(loc: Location): DetectionResult;
  install(loc: Location, opts: InstallOptions): WriteResult;
  uninstall(loc: Location): WriteResult;
  printConfig(loc: Location): string;
  describePaths(loc: Location): string[];
}
```

8 target: `claude`, `cursor`, `codex`, `opencode`, `hermes`, `gemini`, `antigravity`, `kiro`.

Installer features:
- Auto-detect installed agents (multiselect prompt dengan installed pre-checked)
- `--target=auto|all|none|csv` flag
- `--location=global|local` flag
- `--yes` non-interactive
- `--no-permissions` skip Claude auto-allow
- `--print-config <id>` dump snippet, no file writes
- Marker-fenced section (`<!-- CODEGRAPH_START -->` / `<!-- CODEGRAPH_END -->`) — idempotent, preserve sibling config
- Inverse: `codegraph uninstall` remove only what install wrote
- Front-load prompt hook (Claude `UserPromptSubmit`) — inject codegraph_explore context for structural prompts

### 2.13 Library API (embed)

```typescript
import CodeGraph from '@colbymchenry/codegraph';

const cg = await CodeGraph.init('/path/to/project');
await cg.indexAll({ onProgress: (p) => console.log(`${p.phase}: ${p.current}/${p.total}`) });
const results = cg.searchNodes('UserService');
const callers = cg.getCallers(results[0].node.id);
const context = await cg.buildContext('fix login bug', { maxNodes: 20, includeCode: true, format: 'markdown' });
const impact = cg.getImpactRadius(results[0].node.id, 2);
cg.watch();   // auto-sync on file changes
cg.unwatch();
cg.close();
```

Building blocks juga di-export: `DatabaseConnection`, `QueryBuilder`, `getDatabasePath`, `initGrammars`/`loadGrammarsForLanguages`, `FileLock`.

Embedding requirements: Node 22.5+ (untuk `node:sqlite` built-in).

### 2.14 `codegraph upgrade` (in-place self-update)

Detect install method:
- **bundle** — self-contained runtime+app via `install.sh`/`install.ps1`. Upgrade re-run SAME canonical installer script.
- **npm** — `npm i -g`. Upgrade shells out ke npm.
- **npx** — ephemeral, nothing to upgrade.
- **source** — git checkout, `git pull` + rebuild.

Windows wrinkle: running `node.exe` locked, jadi spawn DETACHED helper yang wait for process exit, lalu run `install.ps1` (rustup/nvm-windows pattern).

Flags: `--check` (lihat available), `--force`, `codegraph upgrade <version>` (pin version).

### 2.15 `codegraph affected` (transitive test file trace)

```bash
codegraph affected src/utils.ts src/api.ts         # Pass files as arguments
git diff --name-only | codegraph affected --stdin   # Pipe from git diff
codegraph affected src/auth.ts --filter "e2e/*"     # Custom test file pattern
```

Options: `--stdin`, `-d/--depth <n>` (default 5), `-f/--filter <glob>`, `-j/--json`, `-q/--quiet`.

CI/hook pattern:
```bash
AFFECTED=$(git diff --name-only HEAD | codegraph affected --stdin --quiet)
if [ -n "$AFFECTED" ]; then
  npx vitest run $AFFECTED
fi
```

### 2.16 CLI Reference (17 command)

```bash
codegraph                         # Run interactive installer
codegraph install                 # Run installer (explicit)
codegraph uninstall               # Remove CodeGraph from agents (inverse of install)
codegraph init [path]             # Initialize project + build graph (one step)
codegraph uninit [path]           # Remove CodeGraph from project (--force)
codegraph index [path]            # Full index (--force, --quiet)
codegraph sync [path]             # Incremental update
codegraph status [path]           # Show statistics
codegraph unlock [path]           # Remove stale lock file
codegraph query <search>          # Search symbols (--kind, --limit, --json)
codegraph explore <query>         # Relevant symbols' source + call paths (same as MCP tool)
codegraph node <symbol|file>      # One symbol's source + callers, or read file with line numbers
codegraph files [path]            # Show file structure (--format, --filter, --max-depth, --json)
codegraph callers <symbol>        # Find what calls a function/method (--limit, --json)
codegraph callees <symbol>        # Find what a function/method calls (--limit, --json)
codegraph impact <symbol>         # Analyze affected code (--depth, --json)
codegraph affected [files...]     # Find test files affected by changes
codegraph daemon                  # Manage background daemons (alias: daemons)
codegraph telemetry [on|off]      # Show or change anonymous usage telemetry
codegraph upgrade [version]       # Update to latest release (--check, --force)
codegraph version                 # Print installed version
codegraph help [command]          # Show help
```

### 2.17 Reasoning offload (opt-in, BYO endpoint)

`src/reasoning/reasoner.ts` + `config.ts` + `login.ts` + `credentials.ts`:

- `codegraph_explore` retrieval LOCAL, lalu kirim assembled source context + user's query ke remote OpenAI-compatible reasoning model
- Model returns tight, self-contained answer → THAT answer jadi result of tool call
- Calling agent sees answer, not raw source dump
- Trades network round-trip for far fewer main-context tokens

Configuration:
- **Managed tier** ("CodeGraph AI") — `codegraph login` device flow (OAuth RFC 8628), metered gateway `https://ai.getcodegraph.com/v1`, default model `openai/gpt-oss-120b`
- **BYO endpoint** — `CODEGRAPH_OFFLOAD_URL`, `CODEGRAPH_OFFLOAD_MODEL`, `CODEGRAPH_OFFLOAD_API_KEY` (atau `keyEnv` env var name, API key NEVER written to disk)

Properties:
- Strictly degradable: any failure (no endpoint, network, timeout, non-2xx, empty answer) → return null → caller falls back to local source verbatim
- NEVER throws to tool layer, NEVER yields `isError` (one isError early → agent abandon tool entirely)
- Calibration prompt: correctness-first (relevance check + leading coverage verdict + cite-don't-guess), `file:line` citations

### 2.18 Anonymous telemetry

`src/telemetry/index.ts` + `telemetry-worker/` (Cloudflare Worker, public code):

4 invariants:
1. Zero hot-path cost: in-memory increment, disk write di process exit, network send opportunistic
2. Zero stdout: stdio is MCP protocol channel, notices ke stderr only
3. Off is off: disabled → nothing recorded, nothing sent, no "opted out" ping, delete buffered data
4. Fail silent: offline/down/disk full → silence, no retry loop, no error surfaced

Collected: which tools/commands used, which languages indexed, which agents drive usage, file count bucket (`<100`/`100-1k`/`1k-10k`/`10k+`). NEVER: code, paths, file/symbol names, queries, IP addresses.

Off-switches: `codegraph telemetry off`, `CODEGRAPH_TELEMETRY=0`, `DO_NOT_TRACK=1` (cross-tool standard).

### 2.19 Search quality loop

`src/search/query-parser.ts` — field-qualified query parser:

```
kind:function name:auth path:src/api authenticate
```

Parsed:
- `kinds: [function]` (OR'd)
- `languages: []`
- `name: "auth"` (case-insensitive substring)
- `path: "src/api"` (case-insensitive substring of file_path)
- `text: "authenticate"` (free-text ke FTS5)

Unknown field (`foo:bar`) → pass through to FTS as plain text.

Features:
- Quoting: `path:"src/some path/with spaces"`
- Edit distance for fuzzy matching (`boundedEditDistance`)
- Path relevance scoring (`scorePathRelevance`)
- Name match bonus (`nameMatchBonus`)
- Kind bonus (`kindBonus`)
- Test file deprioritization (`isTestFile`)
- Generated file rank last (`isGeneratedFile`)
- Corroboration ranking (how well each result di-corroborate oleh rest of query)

### 2.20 Worktree mismatch detection

`src/sync/worktree.ts`:

- Saat run dari git worktree nested inside main checkout (e.g. `.claude/worktrees/<name>/`), walk-up ke parent `.codegraph/` resolve MAIN checkout index (branch berbeda)
- Setiap query return results dari main tree's code, bukan worktree yang user edit
- Detection: `git rev-parse --show-toplevel` return per-worktree root
- Warning di `codegraph status` + setiap read tool call
- Saran: `codegraph init -i` di worktree

### 2.21 Git sync hooks (fallback saat watcher disabled)

`src/sync/git-hooks.ts`:

- Saat watcher disabled (WSL2 `/mnt/*`, sandboxed env, `CODEGRAPH_NO_WATCH=1`)
- Install git hooks: `post-commit`, `post-merge` (covers `git pull`), `post-checkout`
- Hooks run `codegraph sync` di background (never block git)
- Guarded by `command -v codegraph` (no-op saat CLI not on PATH)
- Marker-fenced (`# >>> codegraph sync hook >>>` / `# <<< codegraph sync hook <<<`) — idempotent, preserve user-authored hook content

### 2.22 Configuration: `codegraph.json`

```json
{
  "exclude": ["static/", "**/vendor/**"],
  "extensions": {
    ".dota_lua": "lua",
    ".tpl": "php"
  }
}
```

- `exclude`: gitignore-style patterns, matched against repo-root-relative paths, honored on index/sync/watch. Untuk committed directory yang `.gitignore` tidak bisa drop.
- `extensions`: custom file extension → language id mapping. Merge on top of built-in defaults, win on conflict. Bisa re-point built-in (e.g. `".h": "cpp"`).

Default-excluded (built-in, tanpa config):
- Dependency/build/cache dirs: `node_modules`, `vendor`, `dist`, `build`, `target`, `.venv`, `Pods`, `.next`, dll.
- Anything di `.gitignore` (git repo via git, non-git via direct read)
- Files larger than 1 MB

### 2.23 Distribution: self-contained bundle

`BUNDLING.md` + `scripts/build-bundle.sh`:

- Vendored Node runtime (Node 22.5+ untuk `node:sqlite`)
- No native build (better-sqlite3 gone)
- No wasm fallback (no more "database is locked")
- No Node-version dependence

6 target:
- `darwin-arm64`, `darwin-x64` (`.tar.gz` + shell launcher)
- `linux-x64`, `linux-arm64` (`.tar.gz` + shell launcher)
- `win32-x64`, `win32-arm64` (`.zip` + `node.exe` + `.cmd` launcher)

Bundle structure:
```
codegraph-<target>/
  node | node.exe          # official Node runtime
  lib/
    dist/                  # compiled app (+ tree-sitter .wasm grammars, schema.sql)
    node_modules/          # production deps only (pure JS / wasm — portable)
  bin/
    codegraph | codegraph.cmd   # launcher
```

Release: GitHub Releases dengan `SHA256SUMS` file. npm launcher verify bundle download against SHA256SUMS, abort on mismatch.

### 2.24 Benchmark results (7 real-world codebase)

Tested: Claude Code headless, median of 4 runs per arm, WITH vs WITHOUT CodeGraph:

| Codebase | Language | Tool calls | Time | File reads | Tokens | Cost |
|---|---|---|---|---|---|---|
| VS Code | TS · ~10k files | 81% fewer | 11% faster | 0 vs 9 | 64% fewer | 18% cheaper |
| Excalidraw | TS · ~640 | 40% fewer | 27% faster | 0 vs 7 | 25% fewer | even |
| Django | Python · ~3k | 77% fewer | 13% faster | 0 vs 9 | 60% fewer | 8% cheaper |
| Tokio | Rust · ~790 | 57% fewer | 18% faster | 0 vs 8 | 38% fewer | even |
| OkHttp | Java · ~645 | 50% fewer | 31% faster | 0 vs 4 | 54% fewer | 25% cheaper |
| Gin | Go · ~110 | 44% fewer | 24% faster | 1 vs 6 | 23% fewer | 19% cheaper |
| Alamofire | Swift · ~110 | 58% fewer | 33% faster | 0 vs 9 | 64% fewer | 40% cheaper |

**Universal win: 58% fewer tool calls, 22% faster, file reads cut to ~zero.**

### 2.25 Test infrastructure (110 test file)

`__tests__/` dengan vitest:
- Unit test: 100+ file (`*.test.ts`)
- Integration test: `__tests__/integration/` (full-pipeline, mcp-input-limits, lru-cache)
- Evaluation harness: `__tests__/evaluation/` (test-cases, scoring, runner, types)

Test coverage area:
- 21 synthesizer test (callback, celery, sidekiq, spring-event, mediatr, laravel-event, pinia-store, vuex-dispatch, redux-thunk, rtk-query, closure-collection, object-registry, c-fnptr, goframe, gin-middleware-chain, rn-event-channel, fabric-view, expo-modules, react-native-bridge, swift-objc-bridge, lombok)
- MCP test: daemon, proxy-connect, ppid-watchdog, liveness-watchdog, stdin-teardown, query-pool, staleness-banner, tool-annotations, tool-allowlist, roots, initialize, unindexed, catchup-gate, files-path-normalization, debounce-env, daemon-attach-log, daemon-bind-failure, daemon-client-liveness, daemon-registry, daemon-socket-fallback
- Sync test: watcher, watch-policy, worktree-detection, git-hooks, concurrent-locking, db-reopen-on-replace, index-orphan-watchdog
- Search test: query-parser, context-ranking, same-name-disambiguation, symbol-lookup, explore-blast-radius, explore-corroboration-ranking, explore-output-budget, explore-synth-constant-endpoints, adaptive-explore-sizing
- Extraction test: extraction, function-ref, parse-pool, generated-detection, is-test-file, extension-mapping, ts-field-classification, object-literal-methods, react-hoc-component, vue-store-extraction, value-reference-edges
- Resolution test: resolution, frameworks, frameworks-integration, drupal, goframe, swift-objc-bridge, swift-objc-bridge-resolver, c-fnptr-synthesizer, gin-middleware-chain, lombok, mediatr-dispatch-synthesizer, rtk-query-synthesizer
- DB test: sqlite-backend, node-sqlite-backend, db-perf, db-reopen-on-replace
- Installer test: installer, installer-targets, npm-sdk, npm-shim
- Security test: security, config-secret-redaction, unsafe-index-root
- CLI test: cli-affected-paths, cli-version, index-command, status-json
- Upgrade test: upgrade, prepare-release
- Misc: glyphs, fatal-handler, frontload-hook, mcp-debounce-env, mcp-initialize, mcp-require-project-path, multi-repo-workspace, offload, pr19-improvements, strip-comments, telemetry, dynamic-boundaries, foundation, include-ignored-config, exclude-config, iterate-nodes-by-kind, node-version-check, node-file-view

### 2.26 Agent-eval harness

`scripts/agent-eval/` (40+ script):
- `run-agent.sh`, `run-arms.sh`, `run-all.sh` — orchestrator
- `ab-*.sh` — A/B test (new-vs-baseline, adoption, sufficiency, hook, impl)
- `arms-*.sh`, `arms-matrix.sh` — multi-arm test
- `offload-eval-*.sh` / `.mjs` — offload accuracy & adoption eval
- `probe-*.mjs` — probe (explore, sweep, context, trace, node)
- `parse-*.mjs` — parser (session, run, arms, bench-readme)
- `repro-*.mjs` — reproduction (concurrent-explore, daemon-clients)
- `seq-matrix.mjs` — sequential matrix
- `itrun.sh` — interactive TUI runner (tmux-based)
- `audit.sh` — audit script
- `bench-*.sh` — benchmark (readme, why-repo)
- `hook-settings.json` — hook config
- `offload-eval-ground-truth.json` — verified ground-truth flows

---

## 3. Gap Analysis — CodeLens vs CodeGraph

Skala: 🔴 (CodeLens tidak punya, CodeGraph punya matang) · 🟡 (CodeLens punya sebagian/lo-fi) · 🟢 (CodeLens sudah setara atau lebih baik)

| # | Kapabilitas | CodeLens | CodeGraph | Gap severity |
|---|---|---|---|---|
| 1 | **Single-tool MCP philosophy** (1 strong tool > menu) | 🔴 49 MCP tool (terlalu banyak) | 🟢 1 tool `codegraph_explore` default, lain unlisted | 🔴 high |
| 2 | **Auto-sync native file watcher** (FSEvents/inotify/ReadDirectoryChangesW, O(1) descriptor) | 🟡 `watch` command dengan watchdog Python, mtime-based | 🟢 native OS events, debounce 2s, O(1) descriptor di macOS/Windows | 🔴 high |
| 3 | **Per-file staleness banner** (saat file edited, prepend warning) | 🔴 tidak ada | 🟢 `⚠️` banner + nama file pending | 🔴 high |
| 4 | **Connect-time catch-up** (reconcile vs working tree sebelum first query) | 🔴 tidak ada | 🟢 `(size, mtime)` + content-hash reconciliation | 🔴 high |
| 5 | **Shared daemon architecture** (1 daemon, N client, 1 WAL, 1 watcher) | 🔴 setiap session = 1 process | 🟢 detached daemon, Unix socket, idle timeout 300s | 🔴 high |
| 6 | **Worker-thread pool untuk query** (CPU-heavy di worker, main loop responsive) | 🔴 single-threaded | 🟢 `query-pool.ts`, lazy growth, crash recovery, circuit breaker | 🔴 high (perf) |
| 7 | **Worker-thread pool untuk parse** (parallel across cores) | 🔴 single-threaded scan | 🟢 `parse-pool.ts`, per-worker recycle, two-stage retry | 🔴 high (perf) |
| 8 | **WAL mode SQLite explicit** (concurrent read tidak block writer) | 🟡 pakai SQLite di `migrate` command, tanpa WAL explicit | 🟢 `node:sqlite` built-in WAL mode | 🟡 medium |
| 9 | **PPID watchdog cross-platform** (detect parent death, kill orphan) | 🔴 tidak ada | 🟢 POSIX ppid change + Windows liveness poll | 🔴 high |
| 10 | **Liveness watchdog (separate process)** (SIGKILL parent jika main thread wedged) | 🔴 tidak ada | 🟢 child process, heartbeat byte, kernel SIGKILL | 🟡 medium |
| 11 | **Stale stdin teardown** (socketpair `error` event, prevent 100% CPU spin) | 🔴 tidak ada | 🟢 listen `error`, destroy stream, fd leave epoll | 🟡 medium |
| 12 | **Tree-sitter WASM** (universal cross-platform, no native build) | 🔴 tree-sitter Python binding (butuh compile) | 🟢 `web-tree-sitter`, 24 .wasm grammar file | 🔴 high (distrib) |
| 13 | **AgentTarget abstraction** (interface-based installer, add agent = 1 file) | 🔴 tidak ada installer integration | 🟢 `targets/types.ts` + 8 target file + registry | 🔴 high |
| 14 | **`install --print-config <id>`** (dump MCP snippet, no write) | 🔴 tidak ada | 🟢 print snippet untuk 1 agent | 🟡 medium |
| 15 | **`uninstall`** (inverse of install, marker-fenced, idempotent) | 🔴 tidak ada | 🟢 remove only what install wrote, preserve sibling | 🔴 high |
| 16 | **Library API** (embed di app lain) | 🔴 hanya CLI + MCP | 🟢 `import CodeGraph from '@colbymchenry/codegraph'` | 🟡 medium |
| 17 | **`upgrade` in-place self-update** (detect install method) | 🔴 tidak ada | 🟢 bundle/npm/npx/source detection | 🟡 medium |
| 18 | **`affected` transitive test file trace** | 🟡 `dependents` command beda (module-level, bukan transitive test file) | 🟢 transitive import dependency, `--filter` glob, `--stdin` | 🔴 high |
| 19 | **Framework-aware routes** (17 framework) | 🟡 `api-map` command support beberapa framework | 🟢 17 framework dengan validated coverage per framework | 🔴 high |
| 20 | **Mixed iOS/RN/Expo bridging** (Swift↔ObjC, RN legacy/TurboModules/Fabric, Expo Modules) | 🔴 tidak ada cross-language bridging | 🟢 7 bridge type, validated di 13 real codebase | 🟡 medium (niche) |
| 21 | **Dynamic-dispatch synthesizer** (21 pattern) | 🟡 `callgraph_engine.py` inter-procedural, tanpa synthesizer | 🟢 21 synthesizer (callback, celery, sidekiq, spring, mediatr, laravel, pinia, vuex, redux-thunk, rtk-query, closure, registry, c-fnptr, goframe, react-render, jsx, cpp-virtual, java-interface, gin-middleware, swift-handler, anonymous-class) | 🔴 high |
| 22 | **Dynamic-boundary detection** (9 form, announce honest saat path putus) | 🔴 tidak ada | 🟢 computed-call, dynamic-import, ruby-send, php-dynamic, reflection, proxy-reflect, typed-bus, var-key-dispatch, selector | 🔴 high |
| 23 | **Adaptive explore sizing** (skeletonize interchangeable sibling) | 🟡 `--top N` sort + truncate, lebih simple | 🟢 skeletonize off-spine polymorphic sibling, spare named-callable, override untuk supertype family | 🟡 medium |
| 24 | **Value reference edges** (reader → file-scope const/var) | 🔴 tidak ada | 🟢 `references` edge `metadata: { valueRef: true }`, same-file, 15 bahasa | 🔴 high |
| 25 | **Anonymous class extraction** (Java/C# `new T() { ... }`) | 🔴 tidak ada | 🟢 di-index sebagai real class node, override method visible | 🟡 medium |
| 26 | **Interface→implementation linking** (multi-language) | 🟡 `callgraph_engine.py` inter-procedural, bukan interface→impl specific | 🟢 Java/Kotlin/C#/TS/JS/Swift/Scala | 🟡 medium |
| 27 | **Reasoning offload** (BYO endpoint, agent sees answer not raw source) | 🔴 tidak ada | 🟢 opt-in, OpenAI-compatible, strictly degradable, never `isError` | 🟡 medium |
| 28 | **`login` device flow** (OAuth RFC 8628) | 🔴 tidak ada auth | 🟢 device authorization, org-scoped token | 🟡 low (jika tidak butuh auth) |
| 29 | **Anonymous telemetry** (opt-in default, public worker code, `DO_NOT_TRACK=1`) | 🔴 tidak ada | 🟢 4 invariant, field allowlist, public audit | 🟡 medium |
| 30 | **Search quality loop** (field-qualified parser `kind:function name:auth path:src/api`) | 🟡 `search` hanya regex | 🟢 field-qualified + FTS5 + corroboration ranking + edit distance + path relevance + name/kind bonus | 🔴 high |
| 31 | **Worktree mismatch detection** | 🔴 tidak ada | 🟢 `git rev-parse --show-toplevel`, warning di status + read tool | 🟡 medium |
| 32 | **Git sync hooks** (post-commit/merge/checkout, fallback saat watcher disabled) | 🟡 hanya pre-commit hook | 🟢 3 hook type, marker-fenced, background sync | 🟡 medium |
| 33 | **Self-contained binary** (bundled Node, no native build) | 🔴 Python dengan `setup.sh` | 🟢 vendored Node 22.5+, 6 platform target | 🔴 high (distrib) |
| 34 | **`codegraph.json` config** (exclude + extensions) | 🟡 `.codelens/codelens.config.json` beda schema | 🟢 gitignore-style exclude + custom extension mapping | 🟡 medium |
| 35 | **`.gitignore` honored everywhere** (git repo via git, non-git via direct read) | 🔴 hanya `DEFAULT_IGNORE_DIRS` hardcoded | 🟢 universal, root + nested `.gitignore` | 🔴 high |
| 36 | **Generated file detection** (protobuf, gRPC stubs, mocks, rank last) | 🟡 `is_bundled_file()` di `utils.py`, lebih simple | 🟢 `isGeneratedFile`, rank last di search/trace/explore | 🟡 medium |
| 37 | **Multi-platform binary** (6 target dengan SHA256SUMS) | 🔴 tidak ada binary | 🟢 darwin-arm64/x64, linux-x64/arm64, win32-x64/arm64 | 🔴 high (distrib) |
| 38 | **Agent benchmark** (7 real-world codebase, 58% fewer tool calls) | 🟡 `benchmarks/` hanya akurasi engine, bukan agent benchmark | 🟢 7 codebase, median of 4 runs, tool calls + time + file reads + tokens + cost | 🔴 high |
| 39 | **MCP server-instructions** (single source of truth, anti-pattern guidance) | 🟡 MCP tool description per-tool, tidak ada server-level playbook | 🟢 `server-instructions.ts` 70 baris, kirim di `initialize` response | 🟡 medium |
| 40 | **Lazy-load heavy chain off MCP startup** (`require()` sync + cached) | 🔴 semua import di startup, cold start lambat | 🟢 CodeGraph lazy-load di first tool call, bind socket di ~Node-startup time | 🟡 medium (perf) |
| 41 | **`MAX_OUTPUT_LENGTH` + `MAX_INPUT_LENGTH`** bounds (prevent OOM dari hostile client) | 🔴 tidak ada | 🟢 15000 char output, 10000 char input, 4096 char path | 🟡 medium (security) |
| 42 | **Path traversal protection** (resolve symlinks, refuse out-of-root) | 🟡 tidak ada explicit check | 🟢 resolve symlinks, validate file access within project root | 🔴 high (security) |
| 43 | **Spring config secret redaction** (index key only, never value) | 🔴 tidak ada | 🟢 `application.properties`/`.yml` indexed by key only, never include value di explore/node output | 🔴 high (security) |
| 44 | **Low-confidence marker** (honest handoff saat weak/isolated match) | 🔴 tidak ada | 🟢 `### ⚠️ Low-confidence match` heading, suppress contradictory footer | 🟡 medium |
| 45 | **Multi-repo workspace** (query any indexed project via `projectPath`) | 🔴 tidak ada | 🟢 pass `projectPath` ke tool, resolve nearest `.codegraph/` at or above | 🟡 medium |
| 46 | **`CODEGRAPH_MCP_TOOLS` env var** (expose subset tool) | 🔴 tidak ada | 🟢 `explore,node,search,callers` CSV | 🟡 medium |
| 47 | **`codegraph_explore` Read-equivalent** (line-numbered, safe to `Edit` from) | 🟡 `context` command beda format | 🟢 verbatim source grouped by file, `<n>\t<line>` shape, safe to Edit | 🟡 medium |
| 48 | **Blast radius summary** (siapa depend + test file coverage in 1 call) | 🟡 `impact` command separate | 🟢 inline di `codegraph_explore` response | 🟡 medium |
| 49 | **Overload resolution** (return all matching definitions for ambiguous name) | 🟡 `query` command return first match | 🟢 `codegraph_node` return every definition when name ambiguous | 🟡 medium |
| 50 | **Skeletonize container node** (class/interface/struct → member outline, bukan full body) | 🔴 tidak ada | 🟢 `CONTAINER_NODE_KINDS`, structural outline (fields + method signatures + line numbers) | 🟡 medium |
| 51 | **CLI command breadth** (58 command) | 🟢 58 command (init, scan, query, list, detect, watch, search, symbols, trace, impact, context, outline, missing-refs, dependents, validate, dataflow, smell, complexity, dead-code, debug-leak, entrypoints, api-map, state-map, diff, circular, refactor-safe, side-effect, stack-trace, test-map, config-drift, type-infer, ownership, regex-audit, a11y, perf-hint, css-deep, secrets, vuln-scan, taint, env-check, fix, guard, handbook, ask, migrate, lsp-status, binary-scan, artifact-scan, plugin, benchmark, history, dashboard, serve, self-analyze, summary, check, watch) | 🟡 17 command | 🟢 **CodeLens unggul** |
| 52 | **Security analysis** (secrets, taint, CVE, OWASP, compliance) | 🟢 `secrets_engine.py`, `ast_taint_engine.py`, `vulnscan_engine.py` + OSV, 89 rule YAML (OWASP 36 + HIPAA 26 + PCI-DSS 27) | 🔴 tidak ada (CodeGraph bukan security tool) | 🟢 **CodeLens unggul** |
| 53 | **Frontend analysis** (CSS deep, a11y, Tailwind, Vue/Svelte parser) | 🟢 `cssdeep_engine.py`, `a11y_engine.py`, `tailwind_detector.py`, Vue/Svelte parser | 🔴 tidak ada | 🟢 **CodeLens unggul** |
| 54 | **Plugin system** (4 tipe: rule_pack/engine/formatter/command) | 🟢 4 tipe + 3-tier discovery | 🔴 tidak ada plugin | 🟢 **CodeLens unggul** |
| 55 | **Live CVE/OSV scanning** (9 ecosystem, SQLite cache) | 🟢 `osv_client.py` 1616 LOC | 🔴 tidak ada | 🟢 **CodeLens unggul** |
| 56 | **Guard pre/post-write hook** (killer feature) | 🟢 `guard pre/post/snapshot/verify` | 🔴 tidak ada | 🟢 **CodeLens unggul** |
| 57 | **AI-optimized output** (`--format ai`, `--lite`, `--top N`, `--max-tokens N`) | 🟢 native | 🟡 adaptive explore sizing, tapi bukan per-command lite | 🟢 **CodeLens unggul** |
| 58 | **Auto-setup zero-config** (auto init+scan jika registry belum ada) | 🟢 native | 🟡 `codegraph init` one-step, tapi tidak auto-bootstrap jika tidak ada | 🟢 **CodeLens unggul** |
| 59 | **Code intelligence** (call graph, impact, refactor-safe, trace, dependents) | 🟢 5 engine khusus | 🟡 `codegraph_explore` + impact/callers/callees/affected | 🟢 **CodeLens setara** |
| 60 | **MCP server** | 🟢 49 tool, MCP 2025-03-26, stdio + HTTP/SSE | 🟢 1 tool default (7 unlisted), MCP, stdio + socket | 🟡 **CodeGraph lebih focused** |

### Ringkasan gap count

- 🔴 critical/high gap: **25 item** (arsitektur daemon, worker pool, single-tool philosophy, auto-sync, agent integration, dynamic-dispatch synthesizer, framework routes, value reference edges, distribution)
- 🟡 medium gap: **22 item**
- 🟢 CodeLens unggul: **9 item** (command breadth, security analysis, frontend analysis, plugin system, CVE scanning, guard hook, AI output, auto-setup, code intelligence)

CodeGraph menang di: **architecture, MCP design philosophy, auto-sync reliability, agent integration framework, dynamic-dispatch coverage, framework breadth, distribution, benchmark rigor**.
CodeLens menang di: **command breadth, security analysis, frontend analysis, plugin ecosystem, CVE scanning, guard hook, AI output**.

**CodeGraph adalah direct competitor yang lebih matang di arsitektur core** — CodeLens perlu serap arsitektur patterns agar tidak kalah, sambil pertahankan differentiator di security + frontend + plugin + guard.

---

## 4. Peningkatan yang SUDAH Di-adjust untuk CodeLens

Berikut fitur CodeGraph yang **secara konseptual sudah ada di CodeLens** dengan pendekatan berbeda, atau sudah disesuaikan dengan niche CodeLens:

### 4.1 ✅ MCP server — sudah ada, tapi filosofi berbeda
- **CodeLens:** 49 tool, MCP 2025-03-26, stdio + HTTP/SSE
- **CodeGraph:** 1 tool default (`codegraph_explore`), 7 unlisted, stdio + socket
- **Sudah adjusted:** CodeLens expose granular control (49 tool specialized). Yang perlu diserap: **single-tool philosophy** — refactor agar `codelens_explore` jadi primary tool, lain unlisted by default (Issue #1).

### 4.2 ✅ Auto-setup zero-config — CodeLens unggul
- **CodeLens:** Auto `init` + `scan` jika registry belum ada, dengan `--max-files 3000` cap
- **CodeGraph:** `codegraph init` one-step (init + build graph), tapi tidak auto-bootstrap jika tidak ada
- **Sudah adjusted:** CodeLens lebih smart. Tidak perlu serap.

### 4.3 ✅ Workspace auto-detect — CodeLens unggul
- **CodeLens:** Walk-up 10 level parent + last workspace cache (`~/.codelens/.codelens_last_workspace`)
- **CodeGraph:** Default current directory, resolve `.codegraph/` via walk-up parent
- **Sudah adjusted:** CodeLens lebih sophisticated. Tidak perlu serap.

### 4.4 ✅ Code intelligence (call graph, impact, refactor-safe, trace, dependents) — CodeLens setara
- **CodeLens:** `callgraph_engine.py` (3540 LOC), `impact_engine.py`, `refactor_safe_engine.py`, `trace_engine.py` (bidirectional, depth-controlled), `dependents_engine.py`
- **CodeGraph:** `codegraph_explore` (1 tool return source + call path + blast radius), `impact`, `callers`, `callees`, `affected`
- **Sudah adjusted:** CodeLens punya 5 engine khusus, CodeGraph integrate ke 1 tool. Yang perlu diserap: blast radius summary inline di response (Issue #15).

### 4.5 ✅ Plugin system (4 tipe) — CodeLens unggul
- **CodeLens:** 4 tipe (`rule_pack`, `engine`, `formatter`, `command`), 3-tier discovery
- **CodeGraph:** Tidak ada plugin system
- **Sudah adjusted:** differentiator. Tidak perlu serap.

### 4.6 ✅ Security analysis (secrets, taint, CVE, OWASP, compliance) — CodeLens unggul
- **CodeLens:** `secrets_engine.py`, `ast_taint_engine.py`, `vulnscan_engine.py` + OSV, 89 rule YAML (OWASP + HIPAA + PCI-DSS)
- **CodeGraph:** Tidak ada (CodeGraph bukan security tool)
- **Sudah adjusted:** differentiator. Tidak perlu serap. Yang bisa diserap: **path traversal protection** + **Spring config secret redaction** (Issue #17).

### 4.7 ✅ Frontend analysis (CSS deep, a11y, Tailwind, Vue/Svelte) — CodeLens unggul
- **CodeLens:** `cssdeep_engine.py`, `a11y_engine.py` (WCAG 2.1), `tailwind_detector.py`, Vue/Svelte parser
- **CodeGraph:** Tidak ada (CodeGraph fokus code intelligence, bukan frontend analysis)
- **Sudah adjusted:** differentiator. Tidak perlu serap.

### 4.8 ✅ Guard pre/post-write hook — CodeLens unggul (killer feature)
- **CodeLens:** `guard pre --file X --symbol Y --action create`, `guard post --file X --diff ...`, `guard snapshot`, `guard verify`
- **CodeGraph:** Tidak ada equivalent
- **Sudah adjusted:** differentiator. Tidak perlu serap.

### 4.9 ✅ AI-optimized output (`--format ai`, `--lite`, `--top N`, `--max-tokens N`) — CodeLens unggul
- **CodeLens:** Normalized schema `{stats, items[], truncated, recommendations}`, per-command lite mode, smart sort
- **CodeGraph:** Adaptive explore sizing, tapi bukan per-command lite
- **Sudah adjusted:** CodeLens lebih sophisticated untuk AI consumption. Yang bisa diserap: **adaptive skeletonize** (Issue #14).

### 4.10 ✅ Live CVE/OSV scanning — CodeLens unggul
- **CodeLens:** `osv_client.py` (1616 LOC) + SQLite cache + 9 ecosystem + native audit fallback
- **CodeGraph:** Tidak ada (CodeGraph bukan dependency scanner)
- **Sudah adjusted:** differentiator. Tidak perlu serap.

### 4.11 ✅ CLI command breadth (58 command) — CodeLens unggul
- **CodeLens:** 58 command (init, scan, query, list, detect, watch, search, symbols, trace, impact, context, outline, missing-refs, dependents, validate, dataflow, smell, complexity, dead-code, debug-leak, entrypoints, api-map, state-map, diff, circular, refactor-safe, side-effect, stack-trace, test-map, config-drift, type-infer, ownership, regex-audit, a11y, perf-hint, css-deep, secrets, vuln-scan, taint, env-check, fix, guard, handbook, ask, migrate, lsp-status, binary-scan, artifact-scan, plugin, benchmark, history, dashboard, serve, self-analyze, summary, check, watch)
- **CodeGraph:** 17 command
- **Sudah adjusted:** CodeLens lebih broad. Yang bisa diserap: `affected` command pattern (Issue #10), `upgrade` command (Issue #12), `uninstall` command (Issue #7).

### 4.12 ✅ GitHub Actions workflows — sudah ada (4 workflow)
- **CodeLens:** `codelens-ci.yml`, `codelens-quality-gate.yml`, `codelens-sarif.yml`, `codelens-benchmark.yml`
- **CodeGraph:** Tidak ship workflow
- **Sudah adjusted:** CodeLens ship workflow siap pakai. Yang perlu ditambah: agent benchmark workflow (Issue #20).

### 4.13 ✅ Pre-commit hook — sudah ada
- **CodeLens:** `scripts/pre_commit_hook.py` (131 LOC, config `.codelens/pre-commit.yaml`)
- **CodeGraph:** Git sync hooks (post-commit, post-merge, post-checkout) sebagai fallback saat watcher disabled
- **Sudah adjusted:** CodeLens punya pre-commit. Yang bisa diserap: **post-commit/merge/checkout hooks** untuk auto-sync setelah git operation (Issue #11).

### 4.14 ✅ Auto-detect framework — sudah ada
- **CodeLens:** `framework_detect.py` — React/Next.js, Vue/Nuxt, Svelte/SvelteKit, Tailwind, Express, Fastify, Koa, Hono, Django, Flask, FastAPI, pytest, poetry, setuptools, tox, sphinx, nox, hatch, Tauri, Drupal, C/CMake, Lua
- **CodeGraph:** 23 framework resolver (termasuk routing linking)
- **Sudah adjusted:** CodeLens deteksi framework, CodeGraph link route ke handler. Yang perlu diserap: **framework-aware route linking** (Issue #13).

---

## 5. Issue Template — Serap Fitur CodeGraph ke CodeLens

Setiap issue di bawah sudah diformat siap copy-paste ke GitHub issue tracker `Wolfvin/CodeLens`. Urutan berdasarkan prioritas (P0 = critical, P1 = high, P2 = medium, P3 = low).

### 📋 Issue #1 [P0] — Single-Tool MCP Philosophy (refactor 49 → 1-3 tool)

```markdown
**Title:** [P0] Refactor MCP server: single-tool philosophy (1 primary tool, others unlisted)

## Motivation
CodeLens saat ini expose 49 MCP tool ke AI agent. CodeGraph eksperimen dan menemukan bahwa **1 tool kuat > menu tool sempit**:
- Agent less confused (fewer mis-picks)
- Save context every session (tool description tidak di-load untuk 49 tool)
- Measured agent behavior: 1 strong tool steers agents better

CodeGraph punya `codegraph_explore` sebagai satu-satunya tool default (lain unlisted, re-enable via env var). Hasilnya: 58% fewer tool calls, 22% faster, file reads → ~zero di 7 real-world codebase benchmark.

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/mcp/tools.ts` (`DEFAULT_MCP_TOOLS`, `getStaticTools()`)
  - `src/mcp/server-instructions.ts` (70 baris, single source of truth playbook)
  - README "MCP Tools" section
  - CHANGELOG v0.9.9: "`codegraph_explore` is now the primary tool, and one call is usually all an agent needs"

## Current State
- CodeLens: 49 MCP tool, semua listed by default
- CodeLens: tidak ada server-level instructions (hanya per-tool description)

## Acceptance Criteria
- [ ] Primary tool: `codelens_explore` — answer almost any question in 1 call
  - Input: natural-language question atau bag of symbol/file names
  - Output: verbatim line-numbered source of relevant symbols (grouped by file, Read-equivalent), call path between them (dynamic-dispatch hops included), blast radius summary (siapa depend + test file coverage)
- [ ] Unlisted by default (tetap functional via CLI): `codelens_node`, `codelens_search`, `codelens_callers`, `codelens_callees`, `codelens_impact`, `codelens_files`, `codelens_status`, `codelens_query`, `codelens_smell`, `codelens_secrets`, dll.
- [ ] Env var `CODELENS_MCP_TOOLS=explore,node,search` untuk re-enable subset
- [ ] Server-level instructions (`src/mcp/server_instructions.py`, port dari CodeGraph `server-instructions.ts`):
  - Lead agent ke `codelens_explore` for structural/flow question
  - Reinforce "explore instead of Read/Grep" untuk indexed code
  - Anti-patterns: "don't re-verify with grep", "don't reconstruct flow by hand", "check staleness banner after edits"
  - Kirim di MCP `initialize` response (single source of truth)
- [ ] Anti-pattern: `isError: true` early in session → agent abandon tool entirely. Gunakan `isError` hanya untuk "stop trying" cases (security refusal, genuine malfunction). Recoverable condition → SUCCESS-shaped guidance.
- [ ] Test: A/B benchmark dengan 7 real-world codebase (Issue #20) — verify fewer tool calls + faster + zero file reads

## Implementation Notes
- `codelens_explore` = super-set dari `context` + `trace` + `impact` + `query` + `outline` (5 command CodeLens saat ini, merge ke 1)
- Output budget: `MAX_OUTPUT_LENGTH = 15000` char (CodeGraph value)
- Input bounds: `MAX_INPUT_LENGTH = 10000` char, `MAX_PATH_LENGTH = 4096` char
- Lazy-load heavy chain off MCP startup: `require()` sync + cached, defer ke first tool call
- Backward compat: env var `CODELENS_MCP_LEGACY=1` expose all 49 tool (untuk user yang sudah depend on granular tool)

## Priority
P0 — critical untuk agent adoption. 49 tool terlalu banyak, agent confused.
```

---

### 📋 Issue #2 [P0] — Auto-Sync dengan Native File Watcher

```markdown
**Title:** [P0] Auto-sync dengan native file watcher (FSEvents/inotify/ReadDirectoryChangesW, O(1) descriptor)

## Motivation
CodeLens `watch` command saat ini pakai `watchdog` Python library. Masalah:
- Tidak O(1) descriptor di macOS (hold 1 fd per watched file → exhaust `kern.maxfiles`)
- Tidak integrate dengan MCP server (user harus run `watch` terpisah)
- Tidak auto-start saat MCP server start

CodeGraph pakai Node `fs.watch` dengan per-platform strategy:
- macOS: SINGLE recursive `fs.watch(root, {recursive:true})` → 1 FSEvents stream, O(1) descriptor
- Windows: SINGLE recursive → 1 ReadDirectoryChangesW handle, O(1)
- Linux: per-directory inotify watch (O(directories), NOT O(files)), with watch cap

Debounce: `CODEGRAPH_WATCH_DEBOUNCE_MS` (default 2000ms, clamped [100ms, 60s]). Burst of edits collapse into single sync.

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/sync/watcher.ts` (FileWatcher class, native fs.watch)
  - `src/sync/watch-policy.ts` (disable reason logic, WSL2 detection)
  - `src/sync/index.ts` (barrel export)
  - CHANGELOG v0.9.5: "The file watcher no longer exhausts the OS file-watch budget on large repos"
  - CHANGELOG v0.9.7: "watcher no longer marks edited files as fresh when another process holds the index lock"

## Current State
- CodeLens: `watch` command dengan `watchdog` Python library, mtime-based
- CodeLens: tidak integrate dengan MCP server (user run `watch` terpisah)

## Acceptance Criteria
- [ ] Native file watcher di `scripts/sync/watcher.py` (atau port logica CodeGraph):
  - macOS: 1 FSEvents stream via `watchdog` `FSEventsObserver` (sudah O(1))
  - Windows: 1 ReadDirectoryChangesW handle via `watchdog` `WindowsApiObserver`
  - Linux: per-directory inotify via `watchdog` `InotifyObserver`
- [ ] Debounce: `CODELENS_WATCH_DEBOUNCE_MS` env var (default 2000ms, clamp [100ms, 60s])
- [ ] Auto-start saat MCP server start (issue #3 shared daemon)
- [ ] Filter: only source files (match `--include-ext`), exclude `DEFAULT_IGNORE_DIRS` + `.gitignore`
- [ ] Watch cap di Linux: `CODELENS_MAX_INOTIFY_WATCHES` (default 8192)
- [ ] WSL2 `/mnt/*` detection: auto-disable watcher (too slow, bisa break MCP startup), offer git hooks fallback (Issue #11)
- [ ] `CODELENS_NO_WATCH=1` opt-out
- [ ] `CODELENS_FORCE_WATCH=1` override WSL auto-detect
- [ ] Lock contention retry: `MAX_LOCK_RETRIES = 5`, exponential backoff, cap `MAX_LOCK_RETRY_DELAY_MS = 30000`
- [ ] Actionable degrade message: "OS watch/file limit exhausted; auto-sync disabled. Run `codelens scan --incremental` to refresh."

## Implementation Notes
- `watchdog` Python library sudah cross-platform dengan observer per-OS:
  - `from watchdog.observers import Observer`
  - `Observer()` auto-pick FSEventsObserver (macOS) / InotifyObserver (Linux) / WindowsApiObserver (Windows)
- Tapi `watchdog` default recursive=True sudah O(1) di macOS/Windows, O(directories) di Linux
- Untuk O(1) descriptor: pastikan `watchdog` version terbaru, gunakan `recursive=True`
- Filter di event handler: cek `is_source_file(path)` sebelum schedule sync
- Debounce: `threading.Timer` dengan cancel-reschedule pattern

## Priority
P0 — critical untuk always-fresh index. Tanpa ini, agent dapat stale result.
```

---

### 📋 Issue #3 [P0] — Per-File Staleness Banner + Connect-Time Catch-Up

```markdown
**Title:** [P0] Per-file staleness banner + connect-time catch-up (reconcile vs working tree)

## Motivation
CodeLens tidak ada way untuk tell agent bahwa file tertentu sudah edited tapi belum re-indexed. Agent gets stale result silently, salah answer.

CodeGraph punya 2-layer:

**1. Per-file staleness banner:**
- Saat debounce window (file edited tapi belum sync), MCP response yang reference pending file → prepend `⚠️ Some files referenced below were edited since the last index sync…`
- Pending file yang TIDAK di-reference → surface as small footer
- Agent gets explicit signal → `Read` file tersebut directly ( bypass CodeLens)

**2. Connect-time catch-up:**
- Saat MCP server (re)connects, run fast `(size, mtime)` + content-hash reconciliation vs working tree
- Absorb edits made while no MCP server running (`git pull` dari terminal, editor lain, previous session exited)
- First query reflects current code, bukan stale snapshot

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/sync/index.ts` (`PendingFile` type, staleness logic)
  - `src/mcp/tools.ts` (banner prepend logic, `detectWorktreeIndexMismatch`)
  - README "How auto-syncing works — and why you don't need to run codegraph sync manually" section
  - CHANGELOG v0.9.5: "CodeGraph responses now tell the agent which files are pending re-index"
  - CHANGELOG v0.9.7: "MCP tools no longer return results for files that were deleted while no server was running"

## Current State
- CodeLens: tidak ada staleness detection
- CodeLens: tidak ada catch-up saat reconnect

## Acceptance Criteria
- [ ] Pending file tracking di `scripts/sync/pending.py`:
  - Setiap file edit detected by watcher → add ke `pending_files: Dict[path, edit_timestamp]`
  - Setelah sync selesai → remove dari `pending_files`
- [ ] Staleness banner di MCP response:
  - Saat `codelens_explore` (atau tool lain) return result, cek apakah ada file di result yang ada di `pending_files`
  - Jika ya → prepend `⚠️ Some files referenced below were edited since the last index sync. Read these files directly for accurate content:`
  - List nama file + edit age (e.g., "src/Widget.ts (edited 3s ago)")
  - Pending file yang TIDAK di-reference → surface as footer: "Pending sync (not referenced): src/Other.ts"
- [ ] Connect-time catch-up:
  - Saat MCP server start (atau reconnect), run `(size, mtime)` check untuk semua indexed file
  - Jika `size` atau `mtime` berubah → re-compute content-hash (SHA-256)
  - Jika content-hash berubah → schedule sync untuk file tersebut
  - Block first query sampai catch-up selesai (atau timeout 5s, lalu proceed dengan stale + banner)
- [ ] `codegraph status` equivalent: `codelens status` show `### Pending sync:` section dengan file names + edit age
- [ ] Test: edit file saat MCP running → verify banner muncul di next query

## Implementation Notes
- Pending file store: in-memory `Dict[str, float]` (path → edit_timestamp), thread-safe dengan `threading.Lock`
- Staleness check di output layer: sebelum return result, iterate `result.referenced_files`, cek intersection dengan `pending_files`
- Catch-up: walk indexed file list, `os.stat(path)`, compare `(st_size, st_mtime_ns)` dengan stored value
- Content-hash: `hashlib.sha256(file_content_bytes).hexdigest()`, cached di registry

## Priority
P0 — critical untuk agent trust. Silent stale result = agent wrong answer.
```

---

### 📋 Issue #4 [P0] — Shared Daemon Architecture (1 daemon, N client)

```markdown
**Title:** [P0] Shared daemon architecture — 1 daemon per project, N concurrent MCP client

## Motivation
CodeLens setiap MCP session = 1 process. Untuk multi-agent workflow (Claude Code + Cursor + Codex di project yang sama), ini berarti:
- 3 process, 3 file watcher (3× inotify set)
- 3 SQLite connection (3× WAL writer contention)
- 3 tree-sitter warm-up (3× startup cost)

CodeGraph punya shared daemon:
- 1 detached `codegraph serve --mcp` daemon per project root
- Accept N concurrent MCP client over Unix-domain socket (atau named pipe di Windows)
- Setiap connection = 1 session, semua share 1 engine (1 watcher, 1 SQLite, 1 tree-sitter warm-up)
- Daemon detached (bukan child MCP host) → close 1 terminal tidak take down lainnya
- Idle timeout 300s → exit cleanly setelah last client disconnect

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/mcp/daemon.ts` (DaemonServer, socket listen, hello handshake)
  - `src/mcp/proxy.ts` (stdio↔socket pipe, near-transparent)
  - `src/mcp/daemon-registry.ts` (global registry `~/.codegraph/daemons/`, hash-sha256 dari project root)
  - `src/mcp/daemon-manager.ts` (interactive list/stop)
  - `src/mcp/daemon-paths.ts` (socket path resolution, lockfile)
  - `src/mcp/engine.ts` (MCPEngine shared state)
  - `src/mcp/session.ts` (MCPSession per connection)
  - `src/mcp/transport.ts` (StdioTransport + SocketTransport, same JSON-RPC 2.0)
  - CHANGELOG v0.9.5: "Running multiple AI agents in the same project no longer multiplies the cost"

## Current State
- CodeLens: setiap MCP session = 1 process (`python3 scripts/codelens.py serve`)
- CodeLens: tidak ada socket transport, hanya stdio

## Acceptance Criteria
- [ ] Daemon mode: `codelens serve --mcp --daemon` (atau auto-spawn saat first client connect)
  - Detached process (own session/process group, stdio decoupled)
  - Listen di Unix-domain socket (Linux/macOS) atau named pipe (Windows)
  - Socket path: `~/.codelens/daemons/<hash>.sock` (hash = SHA-256 dari project root path, first 16 char)
- [ ] Proxy mode: `codelens serve --mcp` (default) — spawn daemon if not running, lalu pipe stdio↔socket
  - Near-transparent: every byte MCP host writes to stdin → daemon socket, every byte daemon emits → host stdout
  - Server-initiated JSON-RPC requests (e.g., `roots/list`) flow through transparently
- [ ] Hello handshake: proxy verify daemon's hello line (same major.minor.patch as ours) before piping
- [ ] Shared engine: 1 `CodelensEngine` instance, N `CodelensSession`
  - 1 file watcher (1 inotify set)
  - 1 SQLite connection (1 WAL writer)
  - 1 tree-sitter warm-up
- [ ] Idle timeout: `CODELENS_DAEMON_IDLE_TIMEOUT_MS` (default 300000 = 5 menit)
  - Setelah last client disconnect, wait 5 menit, lalu exit cleanly
  - Back-to-back session skip startup cost
- [ ] Version-pinned: upgrade CodeLens tidak mix versions over connection (daemon refuse connection dari different version)
- [ ] Opt-out: `CODELENS_NO_DAEMON=1` (1 independent server per client, untuk debugging atau sandbox)
- [ ] `codelens daemon` / `codelens daemons` command — list + stop interactive
  - Registry: `~/.codelens/daemons/` (global, hash-sha256 dari project root)
  - Prune dead pid (SIGKILL'd daemon tidak remove record-nya sendiri)
- [ ] Cross-platform: Unix signal (macOS/Linux) + Windows TerminateProcess

## Implementation Notes
- Unix socket: `socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)`, bind ke path
- Named pipe Windows: `win32pipe.CreateNamedPipe`
- Python `multiprocessing` untuk detached daemon (atau `subprocess.Popen` dengan `start_new_session=True`)
- Thread-per-connection: `threading.Thread` handle setiap client socket
- SQLite WAL: `PRAGMA journal_mode=WAL` (concurrent read tidak block writer)
- Hello handshake: daemon write `{"version": "X.Y.Z", "pid": ...}\n` ke socket setelah accept

## Priority
P0 — critical untuk multi-agent workflow + resource efficiency. Tanpa ini, 3 agent di project yang sama = 3× resource.
```

---

### 📋 Issue #5 [P0] — Worker-Thread Pool untuk Query + Parse

```markdown
**Title:** [P0] Worker-thread pool untuk CPU-heavy query + parse (main loop tetap responsive)

## Motivation
CodeLens single-threaded. Untuk:
- `codegraph_explore` di repo besar (5000+ file) → CPU-heavy query bisa 2-5 detik
- `codelens scan` di repo besar → parse tree-sitter bisa 30-120 detik

Main loop single-threaded = MCP transport starve saat query berat. Client timeout.

CodeGraph punya 2 worker pool:

**1. Query pool** (`src/mcp/query-pool.ts`):
- CPU-heavy `codegraph_explore` di worker thread
- Main event loop tetap responsive (MCP transport tidak starve)
- Lazy growth: 1 warm worker on construct, grows to `size` on demand
- Crash recovery: dead worker respawned, in-flight call retried once
- Poison call yang keeps crashing → fail gracefully, circuit breaker
- Soft timeout: call tidak ter-served dalam `softTimeoutMs` → SUCCESS-shaped "busy, retry" (never `isError`)

**2. Parse pool** (`src/extraction/parse-pool.ts`):
- `codegraph index` parallel across cores
- Setiap worker punya tree-sitter WASM heap sendiri
- Per-worker recycle: WASM memory grows but never shrinks, recycle setelah N parses
- Two-stage retry: fresh worker, then comment-stripped

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/mcp/query-pool.ts` (QueryPool class, idle-list dispatch, lazy growth, crash recovery, circuit breaker)
  - `src/mcp/query-worker.ts` (worker entry point)
  - `src/extraction/parse-pool.ts` (ParsePool class, per-worker recycle, two-stage retry)
  - `src/extraction/parse-worker.ts` (worker entry point)
  - CHANGELOG v0.9.8: parallel parse across cores

## Current State
- CodeLens: single-threaded scan + query
- CodeLens: `--jobs=N` tidak ada

## Acceptance Criteria
- [ ] Query pool di `scripts/mcp/query_pool.py`:
  - `concurrent.futures.ThreadPoolExecutor` (atau `ProcessPoolExecutor` untuk CPU-bound)
  - Lazy growth: 1 warm worker on construct
  - Default size: `min(cpu_count, 4)` (CodeGraph default)
  - `CODELENS_QUERY_POOL_SIZE=N` env var (0 = disable)
  - Crash recovery: dead worker respawned, in-flight call retried once
  - Circuit breaker: `healthy: bool`, trip setelah N crash → fall back to in-process dispatch
  - Soft timeout: `CODELENS_QUERY_SOFT_TIMEOUT_MS` (default 25000), return "busy, retry" guidance
- [ ] Parse pool di `scripts/extraction/parse_pool.py`:
  - `ProcessPoolExecutor` (tree-sitter tidak thread-safe di Python, perlu process)
  - Per-worker recycle: setelah `CODELENS_PARSE_RECYCLE_INTERVAL` (default 100 files), terminate + respawn worker
  - Two-stage retry: fresh worker, then comment-stripped (clean tree-sitter state)
  - `CODELENS_PARSE_WORKERS=N` env var (1 = conservative rollback, 0 = auto-detect cores)
- [ ] Integrasi dengan MCP server: query pool untuk `codelens_explore` + tool berat lain
- [ ] Integrasi dengan `scan` command: parse pool untuk `codelens scan`
- [ ] Performance benchmark: 2-4x faster di 8-core machine

## Implementation Notes
- Python `concurrent.futures.ProcessPoolExecutor` untuk CPU-bound (tree-sitter parsing)
- Python `concurrent.futures.ThreadPoolExecutor` untuk I/O-bound (SQLite query, dengan WAL concurrent read)
- Worker entry point: terima `(task_id, file_path, language)`, return `(task_id, ExtractionResult)`
- Crash detection: `Future.exception()` tidak None → respawn worker
- Circuit breaker: counter `crash_count`, trip setelah `MAX_CRASHES = 3` dalam window 60s

## Priority
P0 — critical untuk performance di large repo. Single-threaded = bottleneck.
```

---

### 📋 Issue #6 [P0] — PPID Watchdog + Liveness Watchdog + Stale Stdin Teardown

```markdown
**Title:** [P0] Watchdog stack: PPID watchdog + liveness watchdog + stale stdin teardown

## Motivation
CodeLens MCP server bisa orphaned:
- Parent process (MCP host) dies → server terus jalan, leak resource
- Main thread wedged (V8 safepoint, runaway regex, `while(true)`) → no self-recovery
- Socketpair stdin `error` di Windows → 100% CPU spin

CodeGraph punya 3-layer watchdog stack:

**1. PPID watchdog** (`src/mcp/ppid-watchdog.ts`):
- POSIX: `process.ppid` changes saat parent dies (reparent ke init pid 1)
- Windows: poll original parent's liveness (Windows never reparents)
- Kill orphan proxy/server promptly

**2. Liveness watchdog** (`src/mcp/liveness-watchdog.ts`):
- Separate PROCESS (bukan worker thread — V8 safepoint issue)
- Parent writes heartbeat byte ke child's stdin setiap `checkMs`
- Child resets kill-timer on each byte; if none for `timeoutMs` → SIGKILL parent
- Catches: V8 stack-format pathology, runaway regex, accidental `while (true)`

**3. Stale stdin teardown** (`src/mcp/stdin-teardown.ts`):
- Listen for stdin `error` event (bukan hanya `end`/`close`)
- Socket-backed stdin (VS Code/Claude Code socketpair) → `error` (ECONNRESET) saat client dies
- Without `error` listener → Node escalates ke `uncaughtException` → process orphaned
- Linux: `POLLHUP` socket fd di epoll → 100% CPU spin
- Fix: DESTROY stdin stream on terminal event → fd leave epoll → shutdown

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/mcp/ppid-watchdog.ts` (supervisionLostReason, POSIX ppid change + Windows liveness poll)
  - `src/mcp/liveness-watchdog.ts` (separate process, heartbeat byte, SIGKILL)
  - `src/mcp/stdin-teardown.ts` (treatStdinFailureAsShutdown, destroy stream)
  - CHANGELOG v0.9.4: "codegraph serve --mcp no longer keeps running after its parent agent is force-killed"

## Current State
- CodeLens: tidak ada PPID watchdog (orphan possible)
- CodeLens: tidak ada liveness watchdog (wedge possible)
- CodeLens: tidak ada stdin error handler (CPU spin possible)

## Acceptance Criteria
- [ ] PPID watchdog di `scripts/mcp/ppid_watchdog.py`:
  - Capture `os.getppid()` at startup
  - Poll setiap `CODELENS_PPID_POLL_MS` (default 5000ms)
  - POSIX: jika `os.getppid()` != original (reparented ke init) → shutdown
  - Windows: poll original parent liveness via `psutil.pid_exists(original_ppid)` (atau `os.kill(pid, 0)`)
  - `CODELENS_HOST_PPID` env var: thread past intermediate launcher
- [ ] Liveness watchdog di `scripts/mcp/liveness_watchdog.py`:
  - Spawn child process: `python3 scripts/mcp/liveness_child.py`
  - Parent writes heartbeat byte ke child's stdin setiap `checkMs` (default 1000ms)
  - Child resets kill-timer on each byte; if none for `timeoutMs` (default 30000ms) → `os.kill(parent_pid, SIGKILL)`
  - `CODELENS_NO_WATCHDOG=1` opt-out
  - `CODELENS_WATCHDOG_TIMEOUT_MS` tune
- [ ] Stale stdin teardown di `scripts/mcp/stdin_teardown.py`:
  - Listen for `sys.stdin` `error` event (tambahan ke `end`/`close`)
  - On terminal event: `sys.stdin.close()` + `sys.stdin = None` + run shutdown
  - Single-shot guard: `fired: bool`, max 1 invocation
- [ ] Integrasi: 3 layer aktif saat MCP server start di daemon mode
- [ ] Test: simulate parent death (kill -9 parent) → verify daemon shutdown dalam 10s
- [ ] Test: simulate main thread wedge (infinite loop) → verify SIGKILL dalam 30s

## Implementation Notes
- PPID watchdog: `threading.Thread` dengan `time.sleep(poll_ms)` loop
- Liveness child: `subprocess.Popen([sys.executable, 'liveness_child.py'], stdin=PIPE)` — child baca stdin byte, if no byte dalam timeout → `os.kill(parent_pid, signal.SIGKILL)`
- Stdin error: Python `select` module atau `asyncio` untuk detect stdin error
- Cross-platform signal: `signal.SIGTERM` (graceful) → fallback `signal.SIGKILL` (force)

## Priority
P0 — critical untuk reliability. Orphan process = resource leak + zombie daemon.
```

---

### 📋 Issue #7 [P1] — AgentTarget Abstraction + 8 Agent Installer

```markdown
**Title:** [P1] AgentTarget abstraction + installer untuk 8 agent (Claude, Cursor, Codex, opencode, Hermes, Gemini, Antigravity, Kiro)

## Motivation
CodeLens tidak ada installer integration. User harus manual configure `mcp_config.json` per agent. CodeGraph punya `AgentTarget` interface-based installer — add new agent = 1 file + 1 entry registry.

8 agent didukung CodeGraph: Claude Code, Cursor, Codex CLI, opencode, Hermes Agent, Gemini CLI, Antigravity IDE, Kiro.

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/installer/targets/types.ts` (AgentTarget interface)
  - `src/installer/targets/registry.ts` (ALL_TARGETS array)
  - `src/installer/targets/{claude,cursor,codex,opencode,hermes,gemini,antigravity,kiro}.ts` (8 target file)
  - `src/installer/index.ts` (orchestrator, @clack/prompts UI)
  - `src/installer/instructions-template.ts` (marker-fenced section)
  - `src/installer/config-writer.ts` (backwards-compat shim)

## Current State
- CodeLens: `mcp_config.json` manual untuk Claude Desktop / VS Code Copilot
- CodeLens: tidak ada installer untuk agent lain

## Acceptance Criteria
- [ ] `AgentTarget` abstract interface di `scripts/installer/targets/base.py`:
  ```python
  class AgentTarget(ABC):
      id: str
      display_name: str
      docs_url: Optional[str]
      
      @abstractmethod
      def supports_location(self, loc: str) -> bool: ...
      @abstractmethod
      def detect(self, loc: str) -> DetectionResult: ...
      @abstractmethod
      def install(self, loc: str, opts: InstallOptions) -> WriteResult: ...
      @abstractmethod
      def uninstall(self, loc: str) -> WriteResult: ...
      @abstractmethod
      def print_config(self, loc: str) -> str: ...
      @abstractmethod
      def describe_paths(self, loc: str) -> List[str]: ...
  ```
- [ ] 8 target implementation di `scripts/installer/targets/{claude,cursor,codex,opencode,hermes,gemini,antigravity,kiro}.py`
- [ ] Registry di `scripts/installer/targets/registry.py`:
  ```python
  ALL_TARGETS = [claude_target, cursor_target, codex_target, opencode_target, hermes_target, gemini_target, antigravity_target, kiro_target]
  ```
- [ ] `codelens install` command:
  - Auto-detect installed agents (multiselect prompt dengan installed pre-checked)
  - `--target=auto|all|none|csv` flag
  - `--location=global|local` flag
  - `--yes` non-interactive
  - `--no-permissions` skip Claude auto-allow
  - `--print-config <id>` dump MCP snippet, no file writes
- [ ] Marker-fenced section untuk instructions file (`<!-- CODELENS_START -->` / `<!-- CODELENS_END -->`):
  - Idempotent: re-run tidak duplicate
  - Preserve sibling config (other MCP servers, other markdown sections)
  - Write ke `CLAUDE.md` / `AGENTS.md` / `GEMINI.md` / `.cursor/rules/` / `~/.codex/rules/` / dll.
- [ ] `codelens uninstall` command (inverse of install):
  - Remove only what install wrote
  - `--target=csv` specific agents
  - `--location=global|local`
  - `--yes` non-interactive
  - Preserve `.codelens/` index (project data)
- [ ] Front-load prompt hook (Claude `UserPromptSubmit`): inject `codelens_explore` context untuk structural prompts
- [ ] Setup auto-allow permissions saat Claude Code target (settings.json `permissions.allow: ["mcp__codelens__*"]`)
- [ ] Test: 8 target test di `tests/installer/test_targets.py`

## Implementation Notes
- Python abstract class: `from abc import ABC, abstractmethod`
- UI: gunakan `questionary` atau `rich` (sudah common Python dependency) untuk interactive prompt
- Marker-fenced: regex replace antara `<!-- CODELENS_START -->` dan `<!-- CODELENS_END -->`
- Per-agent config format: JSON (Claude, Cursor, Codex), YAML (Hermes, Gemini), TOML (Kiro)
- For YAML: `ruamel.yaml` (preserve comment + formatting)

## Priority
P1 — critical untuk agent ecosystem adoption. Manual config = barrier.
```

---

### 📋 Issue #8 [P1] — Dynamic-Dispatch Synthesizer (21 Pattern)

```markdown
**Title:** [P1] Dynamic-dispatch synthesizer — 21 pattern untuk close static-analysis hole

## Motivation
CodeLens `callgraph_engine.py` punya inter-procedural taint analysis, tapi tidak ada synthesizer untuk dynamic-dispatch pattern yang static parsing tidak bisa follow:
- Callback registration + later invocation
- EventEmitter string-keyed dispatch
- React re-render (setState → render)
- C++ virtual override
- Java/Kotlin interface→impl (`@Autowired`)
- Framework-specific dispatch (Celery, Sidekiq, MediatR, Spring Event, Laravel Event, Redux Thunk, RTK Query, Pinia, Vuex, GoFrame, Gin middleware chain, Swift handler array)
- Anonymous class override
- Closure collection iteration

CodeGraph punya 21 synthesizer yang synthesize edge untuk pattern ini, tagged `provenance:'heuristic'` dengan `metadata.synthesizedBy:` stable channel name.

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/resolution/callback-synthesizer.ts` (callback + observer + EventEmitter)
  - `src/resolution/c-fnptr-synthesizer.ts` (C function pointer)
  - `src/resolution/goframe-synthesizer.ts` (GoFrame route)
  - `src/resolution/swift-objc-bridge.ts` (Swift↔ObjC)
  - `src/resolution/frameworks/react-native.ts` (RN bridge)
  - `src/resolution/frameworks/expo-modules.ts` (Expo Modules)
  - `src/resolution/frameworks/fabric.ts` (Fabric view)
  - 21 test file di `__tests__/*-synthesizer.test.ts`
  - `docs/design/callback-edge-synthesis.md`
  - `docs/design/dispatch-synthesizer-backlog.md`
  - `docs/design/dynamic-dispatch-coverage-playbook.md`

## Current State
- CodeLens: `callgraph_engine.py` (3540 LOC) inter-procedural, import resolution, cross-file taint
- CodeLens: tidak ada synthesizer untuk dynamic-dispatch pattern

## Acceptance Criteria
- [ ] 21 synthesizer di `scripts/resolution/synthesizers/`:
  1. `callback_synthesizer.py` — field-backed observer + string-keyed EventEmitter
  2. `c_fnptr_synthesizer.py` — C function pointer `(*fn_ptr)(arg)`
  3. `celery_dispatch_synthesizer.py` — Python `celery.send_task` / `@app.task`
  4. `sidekiq_dispatch_synthesizer.py` — Ruby `Sidekiq::Worker.perform_async`
  5. `spring_event_synthesizer.py` — `ApplicationEventPublisher.publishEvent` + `@EventListener`
  6. `mediatr_dispatch_synthesizer.py` — C# `IMediator.Send(new Command())` + `IRequestHandler`
  7. `laravel_event_synthesizer.py` — `event(new MyEvent)` + `Listener::class`
  8. `pinia_store_synthesizer.py` — Vue `defineStore` state/getters/actions
  9. `vuex_dispatch_synthesizer.py` — `store.dispatch('action')`
  10. `redux_thunk_synthesizer.py` — `dispatch(thunk())` + `createAsyncThunk`
  11. `rtk_query_synthesizer.py` — Redux Toolkit `createApi` endpoint
  12. `closure_collection_synthesizer.py` — `validators.append(closure)` + iterate
  13. `object_registry_synthesizer.py` — `registry['name'] = impl` + lookup
  14. `goframe_synthesizer.py` — Go `goframe` routing
  15. `react_render_synthesizer.py` — `setState` → `render` (Flutter `setState` → `build` juga)
  16. `jsx_children_synthesizer.py` — component tree traversal
  17. `cpp_virtual_synthesizer.py` — C++ virtual dispatch
  18. `java_interface_impl_synthesizer.py` — Java/Kotlin interface→impl, `@Autowired`
  19. `gin_middleware_chain_synthesizer.py` — `.Use()` chain
  20. `swift_handler_array_synthesizer.py` — `.validate { ... }` closures
  21. `anonymous_class_synthesizer.py` — `new T() { ... }` method override
- [ ] Setiap synthesizer: whole-graph pass setelah base resolution, high-precision/low-recall by design
- [ ] Synthesized edge tagged `provenance: 'heuristic'` dengan `metadata.synthesized_by: '<channel-name>'`
- [ ] Integrasi dengan `callgraph_engine.py`: synthesized edge masuk ke call graph, affect callers/callees/impact
- [ ] Integrasi dengan `codelens_explore` (Issue #1): dynamic-dispatch hops visible di call path
- [ ] Test: 21 test file (port dari CodeGraph `__tests__/*-synthesizer.test.ts`)

## Implementation Notes
- Python AST module (`ast`) untuk Python pattern
- Tree-sitter Python binding untuk bahasa lain (sudah ada di CodeLens)
- Regex over comment/string-stripped body (CodeGraph approach: `stripCommentsForRegex` + `blankStringContents`)
- Cap: `MAX_CALLBACKS_PER_CHANNEL = 40`, `EVENT_FANOUT_CAP = 6` (skip generic names like 'error')
- Per-synthesizer config: enable/disable via `scripts/plugins/synthesizers/<name>.yaml`

## Priority
P1 — critical untuk call graph completeness. Tanpa ini, 30-50% flow putus di dynamic-dispatch site.
```

---

### 📋 Issue #9 [P1] — Dynamic-Boundary Detection (9 Form)

```markdown
**Title:** [P1] Dynamic-boundary detection — announce honest saat static path putus (9 form)

## Motivation
Saat `codelens_explore` tidak connect flow statically, cause hampir selalu dynamic-dispatch site: computed member call, getattr, reflection, string-keyed bus, typed command/mediator dispatch.

CodeGraph tidak guess missing edge (silent beats wrong — wrong edge poison map + teach abandonment). Sebaliknya, **ANNOUNCE boundary honest**: exact site where static path ends, dispatch form, dan key (jika statically visible).

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/mcp/dynamic-boundaries.ts` (`scanDynamicDispatch`, `BoundaryMatch` interface, `FormSpec`)
  - `__tests__/dynamic-boundaries.test.ts`
  - `docs/design/dynamic-dispatch-coverage-playbook.md`

## Current State
- CodeLens: tidak ada boundary detection (saat path putus, return "no path found")

## Acceptance Criteria
- [ ] Boundary detection di `scripts/mcp/dynamic_boundaries.py`:
  - Detect 9 form:
    1. `computed-call` — `obj[method]()` (computed member access)
    2. `dynamic-import` — `require(name)` / `import(name)` (dynamic import)
    3. `ruby-send` — `obj.send(:method)` (Ruby send dispatch)
    4. `php-dynamic` — `$obj->$method()` (PHP dynamic call)
    5. `reflection` — `Method.invoke(target)` (Java/C# reflection)
    6. `proxy-reflect` — `new Proxy(target, handler)` (JS Proxy/Reflect)
    7. `typed-bus` — `Send(new CreateCmd(...))` (typed message dispatch)
    8. `var-key-dispatch` — `handlers[varName]()` (string-keyed dispatch, runtime key)
    9. `selector` — `performSelector:` (ObjC selector dispatch)
  - Per match: `form`, `label`, `snippet` (1-line dari original source), `line` (1-based), `key?` (static-visible dispatch key), `keyIsType?` (untuk typed-bus), `moreSites?` (additional sites same form+key)
- [ ] Detection deterministic regex over comment/string-stripped body
  - Strip comment (`strip_comments_for_regex`)
  - Blank string contents (`blank_string_contents`) — string-embedded dispatch shape = false positive
  - Snippet sliced dari ORIGINAL source at same offset (stripper blank in place, preserve offset)
- [ ] Run at QUERY TIME only (graph never mutated; unbroken flow never trigger scan)
- [ ] Integrasi dengan `codelens_explore`: saat flow tidak connect, scan endpoint body untuk boundary, announce di response
- [ ] Output format:
  ```
  ⚠️ Static path ends at dynamic-dispatch boundary:
  
  Form: computed member call
  Site: src/handler.ts:42
  Snippet: obj[method]()
  Key: (runtime value — no static candidate)
  
  Hint: The dispatch target is determined at runtime. Look for:
  - Where `method` is assigned
  - What values `obj` can be
  ```
- [ ] Jika key statically visible (string literal, `:symbol`, `new Type`): shortlist candidate targets
- [ ] Test: 30+ case per form (port dari `__tests__/dynamic-boundaries.test.ts`)

## Implementation Notes
- Regex pattern per form (lihat CodeGraph `FormSpec` di `src/mcp/dynamic-boundaries.ts`)
- Python `re` module, run di stripped body
- Strip comment: regex per bahasa (`#` Python/Ruby, `//` JS/TS/C/C++/Java/Rust/Go/Swift, `<!-- -->` HTML, `/* */` CSS)
- Blank string: replace string content dengan space (preserve offset, keep quote)

## Priority
P1 — critical untuk honest failure. Agent tahu kenapa path putus, bisa investigate manual.
```

---

### 📋 Issue #10 [P1] — `affected` Command (Transitive Test File Trace)

```markdown
**Title:** [P1] `codelens affected` command — transitive test file trace dari changed source files

## Motivation
CodeLens `dependents` command saat ini module-level import tracking, bukan transitive test file trace. Untuk CI/hook "test files affected by changes", CodeLens tidak bisa.

CodeGraph punya `codegraph affected`:
```bash
codegraph affected src/utils.ts src/api.ts         # Pass files as arguments
git diff --name-only | codegraph affected --stdin   # Pipe from git diff
codegraph affected src/auth.ts --filter "e2e/*"     # Custom test file pattern
```

CI/hook pattern:
```bash
AFFECTED=$(git diff --name-only HEAD | codegraph affected --stdin --quiet)
if [ -n "$AFFECTED" ]; then
  npx vitest run $AFFECTED
fi
```

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/bin/codegraph.ts` (`affected` command handler)
  - `src/graph/queries.ts` (transitive dependency traversal)
  - README "codegraph affected" section
  - `__tests__/cli-affected-paths.test.ts`

## Current State
- CodeLens: `dependents` command module-level import tracking, bukan transitive test file

## Acceptance Criteria
- [ ] Command baru: `codelens affected [files...]`
- [ ] Input:
  - Pass file sebagai arguments: `codelens affected src/utils.ts src/api.ts`
  - Pipe dari git diff: `git diff --name-only | codelens affected --stdin`
- [ ] Traversal: trace import dependency transitif dari changed source files
- [ ] Test file identification: `--filter <glob>` (default: auto-detect `*test*`, `*spec*`, `__tests__/`, `tests/`)
- [ ] Options:
  - `--stdin` — read file list dari stdin
  - `-d, --depth <n>` — max dependency traversal depth (default 5)
  - `-f, --filter <glob>` — custom test file pattern
  - `-j, --json` — output as JSON
  - `-q, --quiet` — output file paths only (untuk pipe ke test runner)
- [ ] Output: list of test file paths yang transitively depend on changed source files
- [ ] CI/hook pattern documented di README:
  ```bash
  AFFECTED=$(git diff --name-only HEAD | codelens affected --stdin --quiet)
  if [ -n "$AFFECTED" ]; then
    pytest $AFFECTED  # atau npx vitest run $AFFECTED, dll
  fi
  ```
- [ ] Test: `tests/commands/test_affected.py`

## Implementation Notes
- Reuse `dependents_engine.py` tapi extend ke transitive (depth-controlled BFS)
- Test file detection: `is_test_file(path)` heuristic (filename pattern + directory pattern)
- Performance: cache dependency graph in-memory, invalidate saat registry update

## Priority
P1 — critical untuk CI selective test running. High value untuk large repo.
```

---

### 📋 Issue #11 [P1] — Git Sync Hooks (post-commit/merge/checkout)

```markdown
**Title:** [P1] Git sync hooks (post-commit, post-merge, post-checkout) — fallback saat watcher disabled

## Motivation
CodeLens hanya punya pre-commit hook (block commit jika critical finding). Tidak ada post-commit/merge/checkout hooks untuk auto-sync setelah git operation.

CodeGraph install git sync hooks sebagai fallback saat watcher disabled (WSL2 `/mnt/*`, sandboxed env, `CODEGRAPH_NO_WATCH=1`):
- `post-commit` — sync setelah commit
- `post-merge` — sync setelah `git pull` (merge)
- `post-checkout` — sync setelah branch switch

Hooks run `codegraph sync` di background (never block git), guarded by `command -v codegraph` (no-op saat CLI not on PATH).

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/sync/git-hooks.ts` (installGitSyncHook, isSyncHookInstalled, DEFAULT_SYNC_HOOKS)
  - `src/installer/index.ts` (installer offer git hooks saat watcher disabled)
  - CHANGELOG v0.8.0: "On WSL2 /mnt/* drives, CodeGraph now skips the watcher and offers to keep the index fresh with git hooks instead"

## Current State
- CodeLens: `pre_commit_hook.py` (block commit jika critical finding)
- CodeLens: tidak ada post-commit/merge/checkout hooks

## Acceptance Criteria
- [ ] 3 git hook type: `post-commit`, `post-merge`, `post-checkout`
- [ ] Hook content: `codelens scan --incremental` di background (`&` suffix, `nohup`, atau `disown`)
- [ ] Guarded by `command -v codelens` (no-op saat CLI not on PATH)
- [ ] Marker-fenced (`# >>> codelens sync hook >>>` / `# <<< codelens sync hook <<<`) — idempotent, preserve user-authored hook content
- [ ] Install via `codelens install --git-hooks` atau `codelens init --git-hooks`
- [ ] Uninstall via `codelens uninstall --git-hooks` (remove only marker-fenced section)
- [ ] Detect: tawarkan install saat `codegraph status` show watcher disabled
- [ ] Hook jalan di background, never block git (output ke logfile `~/.codelens/logs/sync-hook.log`)
- [ ] Test: `tests/sync/test_git_hooks.py`

## Implementation Notes
- Hook path: `.git/hooks/post-commit` (atau `core.hooksPath` jika set)
- Hook script bash:
  ```bash
  #!/bin/sh
  # >>> codelens sync hook >>>
  if command -v codelens >/dev/null 2>&1; then
    nohup codelens scan --incremental >/dev/null 2>&1 &
  fi
  # <<< codelens sync hook <<<
  ```
- Marker-fenced install: read existing hook, regex replace antara marker, write back
- Background: `nohup ... &` + `disown` agar tidak block git

## Priority
P1 — critical untuk WSL2 + sandboxed env where watcher unreliable.
```

---

### 📋 Issue #12 [P1] — `upgrade` Command (In-Place Self-Update)

```markdown
**Title:** [P1] `codelens upgrade` command — in-place self-update (detect install method)

## Motivation
CodeLens saat ini user harus manual `git pull` + `bash setup.sh` untuk update. Tidak ada in-place self-update.

CodeGraph punya `codegraph upgrade` yang detect install method (bundle/npm/npx/source) dan update accordingly:
- bundle: re-run SAME canonical installer script
- npm: shell out ke `npm i -g @colbymchenry/codegraph@latest`
- npx: ephemeral, nothing to upgrade (next `npx` fetches latest)
- source: `git pull` + rebuild

Flags: `--check` (lihat available), `--force`, `codegraph upgrade <version>` (pin version).

Windows wrinkle: running `node.exe` locked, spawn DETACHED helper yang wait for process exit, lalu run installer (rustup/nvm-windows pattern).

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/upgrade/index.ts` (detectInstallMethod, upgrade logic)
  - `__tests__/upgrade.test.ts`
  - README "Get Started" section

## Current State
- CodeLens: tidak ada self-update (manual `git pull` + `setup.sh`)

## Acceptance Criteria
- [ ] Command `codelens upgrade [version]`
- [ ] Detect install method:
  - **pip** — `pip show codelens` (jika install via PyPI di Issue #19 opengrep doc)
  - **homebrew** — `brew list codelens` (jika install via Homebrew di Issue #11 UBS doc)
  - **source** — git checkout (detect `.git` di install dir)
  - **binary** — self-contained binary (jika adopt di Issue #12 opengrep doc)
- [ ] Upgrade logic per method:
  - pip: `pip install --upgrade codelens`
  - homebrew: `brew upgrade codelens`
  - source: `git pull` + `bash setup.sh`
  - binary: download latest dari GitHub Releases, replace binary
- [ ] `--check` flag: check if update available (compare current version vs latest GitHub Release), exit 0/1
- [ ] `--force` flag: force update even if already latest
- [ ] `codelens upgrade <version>`: pin specific version
- [ ] Windows wrinkle: spawn DETACHED helper (`subprocess.Popen` dengan `CREATE_NEW_PROCESS_GROUP`) yang wait for current process exit, lalu run installer
- [ ] Version check: fetch `https://api.github.com/repos/Wolfvin/CodeLens/releases/latest`, compare `tag_name` dengan current `CODELENS_VERSION`
- [ ] Test: `tests/commands/test_upgrade.py` (mock install method detection)

## Implementation Notes
- Install method detection: check `sys.executable` path, `pip show`, `brew list`, `.git` existence
- Version comparison: `packaging.version.parse` (already common dependency)
- GitHub API: `urllib.request.urlopen('https://api.github.com/repos/Wolfvin/CodeLens/releases/latest')`
- Windows detached helper: `subprocess.Popen([sys.executable, 'upgrade_helper.py'], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS)`

## Priority
P1 — critical untuk keep user up-to-date. Manual update = user stuck di old version.
```

---

### 📋 Issue #13 [P1] — Framework-Aware Routes (17 Framework)

```markdown
**Title:** [P1] Framework-aware routes — link URL pattern ke handler (17 framework)

## Motivation
CodeLens `api-map` command support beberapa framework, tapi tidak comprehensive. CodeGraph support 17 framework dengan validated coverage per framework (85-100%):

Django, Flask, FastAPI, Express, NestJS, Laravel, Drupal, Rails, Spring, Play, Gin/chi/gorilla/mux, Axum/actix/Rocket, ASP.NET, Vapor, React Router, SvelteKit, Vue Router/Nuxt, Astro.

CodeGraph emit `route` nodes linked by `references` edges ke handler classes/functions. Querying callers of a view/controller surface URL pattern yang bind it.

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/resolution/frameworks/index.ts` (FRAMEWORK_RESOLVERS array)
  - `src/resolution/frameworks/{laravel,drupal,express,nestjs,react,svelte,vue,astro,python,ruby,java,play,go,goframe,rust,csharp,swift,swift-objc,react-native,expo-modules,fabric}.ts` (23 file)
  - README "Framework-aware Routes" section
  - README "Measured cross-file coverage" section (per-framework coverage %)

## Current State
- CodeLens: `apimap_engine.py` support beberapa framework (React/Next.js, Vue/Nuxt, Express, FastAPI, dll dari `framework_detect.py`)
- CodeLens: tidak link URL pattern ke handler secara eksplisit

## Acceptance Criteria
- [ ] 17 framework resolver di `scripts/resolution/frameworks/`:
  1. Django — `path()`, `re_path()`, `url()`, `include()` di `urls.py` (CBV `.as_view()`, dotted paths)
  2. Flask — `@app.route('/path', methods=[...])`, blueprint routes
  3. FastAPI — `@app.get(...)`, `@router.post(...)`, all standard methods
  4. Express — `app.get(...)`, `router.post(...)` with middleware chains
  5. NestJS — `@Controller` + `@Get/@Post/...`, GraphQL `@Resolver` + `@Query/@Mutation`, `@MessagePattern`/`@EventPattern`, `@SubscribeMessage`
  6. Laravel — `Route::get()`, `Route::resource()`, `Controller@action`, tuple syntax
  7. Drupal — `*.routing.yml` routes (`_controller`, `_form`, entity handlers); `hook_*` implementations di `.module`/`.theme`/`.install`/`.inc`
  8. Rails — `get '/x', to: 'users#index'`, hash-rocket `=>` syntax
  9. Spring — `@GetMapping`, `@PostMapping`, `@RequestMapping` on methods
  10. Play — `GET`/`POST`/… verb routes di `conf/routes` → `Controller.method` actions (Scala + Java)
  11. Gin / chi / gorilla / mux — `r.GET(...)`, `router.HandleFunc(...)`
  12. Axum / actix / Rocket — `.route("/x", get(handler))`
  13. ASP.NET — `[HttpGet("/x")]` attributes on action methods
  14. Vapor — `app.get("x", use: handler)`
  15. React Router / SvelteKit — Route component nodes
  16. Vue Router / Nuxt — `pages/` file-based routes, `server/api/` endpoints, route middleware
  17. Astro — `src/pages/` file-based routes (`.astro` pages + `.ts` endpoints, `[param]`/`[...rest]` syntax)
- [ ] Emit `route` node untuk setiap URL pattern
- [ ] Link `route` node ke handler via `references` edge
- [ ] Integrasi dengan `api-map` command: `codelens api-map` return route-to-handler map
- [ ] Integrasi dengan `callers` command: querying callers of view/controller surface URL pattern
- [ ] Integrasi dengan `codelens_explore` (Issue #1): route visible di call path
- [ ] Test: per-framework fixture (port dari CodeGraph `__tests__/frameworks.test.ts` + `frameworks-integration.test.ts`)

## Implementation Notes
- Tree-sitter query per framework (extract route declaration AST node)
- Framework detection: dari `framework_detect.py` (sudah ada di CodeLens)
- Route node schema: `{ kind: 'route', name: '/api/users/:id', method: 'GET', handler: 'UserController.show', file_path, line }`
- Edge: `{ kind: 'references', source: route_node, target: handler_node }`

## Priority
P1 — critical untuk web framework project. Route-to-handler linking = impact analysis untuk API endpoint.
```

---

### 📋 Issue #14 [P2] — Adaptive Explore Sizing (Skeletonize Sibling)

```markdown
**Title:** [P2] Adaptive explore sizing — skeletonize interchangeable sibling implementations

## Motivation
CodeLens `--top N` sort + truncate, lebih simple` `references` edge.
```

---

### 📋 Issue #14 [P2] — Adaptive Explore Sizing (Skeletonize Sibling)

```markdown
**Title:** [P2] Adaptive explore sizing — skeletonize interchangeable sibling implementations

## Motivation
CodeLens `--top N` sort + truncate, simple. Tapi untuk flow dengan banyak interchangeable implementations (HTTP interceptor chain, query-compiler family), semua impl di-return full → bloat context.

CodeGraph punya adaptive explore sizing:
- Skeletonize off-spine polymorphic sibling (collapse ke 1-line signature)
- Spare named-callable (agent named it → keep full)
- Override untuk supertype family (file yang define ≥3-impl supertype → skeletonize, free budget)
- Disable dengan `CODEGRAPH_ADAPTIVE_EXPLORE=0`

Refinement (2026-05-29): 2 condition — file skeletonize hanya jika **not spared**, where spared = agent named callable in it, UNLESS file define ≥3-impl supertype.

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `docs/design/adaptive-explore-sizing.md` (design + refinement history)
  - `__tests__/adaptive-explore-sizing.test.ts`
  - CHANGELOG v0.9.8: "codegraph_explore now sizes its response to the answer instead of the file count"

## Current State
- CodeLens: `--top N` sort + truncate, simple

## Acceptance Criteria
- [ ] Adaptive sizing di `codelens_explore` output layer:
  - Detect polymorphic sibling group (interface dengan ≥3 implementation)
  - Skeletonize off-spine file (collapse ke 1-line signature + file:line)
  - Spare named-callable (agent named symbol di file itu → keep full source)
  - Override: file yang define ≥3-impl supertype → skeletonize (free budget untuk sibling)
- [ ] Skeletonize format:
  ```
  src/interceptors/AuthInterceptor.ts (skeletonized — implements HttpInterceptor)
    L12: class AuthInterceptor implements HttpInterceptor { ... }
    L45: intercept(req: HttpRequest): HttpResponse { ... }
  ```
- [ ] Disable: `CODELENS_ADAPTIVE_EXPLORE=0`
- [ ] List dropped files di response footer (agar agent bisa ask di call lain)
- [ ] Test: `tests/mcp/test_adaptive_explore_sizing.py`

## Implementation Notes
- Polymorphic sibling detection: query graph untuk interface→impl edges, count impl per interface
- Named-callable spare: parse query untuk symbol names, cek apakah ada di file
- Supertype family: cek apakah file define class/interface dengan ≥3 subclass
- Budget: `MAX_OUTPUT_LENGTH = 15000` char, allocate berdasarkan relevance

## Priority
P2 — improve context efficiency untuk polymorphic codebase.
```

---

### 📋 Issue #15 [P2] — Blast Radius Summary Inline di `codelens_explore`

```markdown
**Title:** [P2] Blast radius summary inline di `codelens_explore` response (siapa depend + test file coverage)

## Motivation
CodeLens `impact` command separate dari `context`/`query`. Agent harus 2 call untuk dapat source + blast radius.

CodeGraph inline blast radius di `codegraph_explore` response:
- Who depends on each symbol (just locations, not source)
- Which test files cover it
- Symbols nothing depends on → skipped (stay short)

Sehingga 1 call = source + call path + blast radius. Agent bisa see what else to update + which tests to run, tanpa separate impact lookup.

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/mcp/tools.ts` (blast radius section di `codegraph_explore` response)
  - CHANGELOG v0.9.9: "codegraph_explore now includes a compact 'Blast radius' for the symbols you're looking at"

## Current State
- CodeLens: `impact` command separate
- CodeLens: `context` command tidak include blast radius

## Acceptance Criteria
- [ ] Blast radius section di `codelens_explore` response:
  ```
  ## Blast radius
  
  ### Dependents (who calls these symbols):
  - src/api/UserController.ts:45 → UserService.getUser
  - src/jobs/SyncJob.ts:12 → UserService.syncUser
  - src/tests/UserService.test.ts:8 → UserService.getUser (test)
  
  ### Test files covering these symbols:
  - tests/unit/UserService.test.ts
  - tests/integration/UserAPI.test.ts
  ```
- [ ] Symbols nothing depends on → skip (stay short)
- [ ] Just locations (file:line), not full source
- [ ] Integrasi dengan `codelens affected` (Issue #10) untuk test file coverage
- [ ] Test: `tests/mcp/test_blast_radius.py`

## Implementation Notes
- Dependents: reuse `dependents_engine.py` (sudah ada)
- Test file: `is_test_file(path)` heuristic
- Format: markdown section di response

## Priority
P2 — improve agent workflow (1 call vs 2 call).
```

---

### 📋 Issue #16 [P2] — Value Reference Edges (Reader → File-Scope Const/Var)

```markdown
**Title:** [P2] Value reference edges — edge dari reader symbol ke file-scope const/var yang dibaca

## Motivation
CodeLens edges: calls, imports, inheritance. Tidak ada edge dari constant ke symbol yang read it. Sehingga changing config object / lookup table / shared constant looks like "nothing depends on this" — padahal banyak reader.

CodeGraph emit `references` edge (`metadata: { valueRef: true }`) dari reader symbol ke file/package-scope `const`/`var` yang dibaca, same-file only, untuk 15 bahasa.

Edge flow straight ke `getImpactRadius` / `codegraph impact` + impact trail di `codegraph_explore` / `codegraph_node`.

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `docs/design/value-reference-edges.md` (design + status)
  - `docs/design/value-reference-edges-playbook.md`
  - `src/extraction/tree-sitter.ts` (`flushValueRefs` emitter)
  - `__tests__/value-reference-edges.test.ts`
  - CHANGELOG: shipped default-on untuk 15 bahasa

## Current State
- CodeLens: tidak ada value reference edge (impact analysis hole untuk value consumer)

## Acceptance Criteria
- [ ] Emit `references` edge dengan `metadata: { value_ref: true }` dari reader symbol ke file-scope const/var
- [ ] Target: file-scope `const`/`var` dengan "distinctive" name (≥3 char + contains uppercase letter atau `_`) — dodge local-shadowing precision trap
- [ ] Reader: any `function` / `method` / `const` / `var` symbol yang body reference target name
- [ ] Same-file only — resolution unambiguous tanpa import/scope analysis
- [ ] Deduped per `(reader, target)`
- [ ] Additive — adds edges, never nodes
- [ ] 15 bahasa awal: TS/JS/tsx, Go, Python, Rust, Ruby, C, Java, C#, PHP, Scala, Kotlin, Swift, Dart, Pascal
- [ ] Disable: `CODELENS_VALUE_REFS=0`
- [ ] Integrasi dengan `impact` command: value reference edge flow ke impact radius
- [ ] Integrasi dengan `codelens_explore` (Issue #1): value reference visible di blast radius
- [ ] Test: `tests/extraction/test_value_reference_edges.py`

## Implementation Notes
- Tree-sitter query: extract `identifier` node yang reference file-scope const/var
- Distinctive name filter: regex `^[A-Z_][A-Z0-9_]{2,}$` atau camelCase dengan ≥3 char
- Same-file: cek `node.file_path == target.file_path`

## Priority
P2 — close impact-analysis hole untuk config/lookup-table change.
```

---

### 📋 Issue #17 [P2] — Path Traversal Protection + Config Secret Redaction

```markdown
**Title:** [P2] Security hardening — path traversal protection + Spring/Liquid config secret redaction

## Motivation
CodeLens tidak ada explicit path traversal protection. Symbolic link inside indexed project yang point outside project root bisa serve out-of-root file content ke AI agent.

CodeGraph closed hole ini (v1.0.0 security):
- Resolve symlinks saat validate file access
- Refuse read anything whose real location outside project
- Still allow symlinks yang stay within project

Juga: Spring configuration files (`application.properties` / `application.yml`) di-index by key only, never include value di `codegraph_explore` / `codegraph_node` output. Sebelumnya secret committed ke file ini (database password, API key, connection string) bisa surface ke AI agent. Shopify Liquid `{% schema %}` blocks juga indexed by name only.

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - CHANGELOG v1.0.0 security section (#527 path traversal, #383 config secret)
  - `src/mcp/tools.ts` (`validatePathWithinRoot`, symlink resolve)
  - `__tests__/security.test.ts`
  - `__tests__/config-secret-redaction.test.ts`
  - `__tests__/unsafe-index-root.test.ts`

## Current State
- CodeLens: tidak ada explicit path traversal check
- CodeLens: tidak ada config secret redaction

## Acceptance Criteria
- [ ] Path traversal protection:
  - Resolve symlinks (`os.path.realpath`) saat validate file access
  - Refuse read anything whose real location outside project root
  - Allow symlinks yang stay within project
  - Apply ke semua MCP tool yang return file content (`codelens_explore`, `codelens_node`, dll.)
- [ ] Config secret redaction:
  - Spring `application.properties` / `application.yml` — index by key only, never include value
  - Shopify Liquid `{% schema %}` blocks — index by name only
  - Apply di extraction layer (jangan store value di DB)
  - Agent yang genuinely need value → read file itself (CodeLens tidak surface)
- [ ] `PathRefusalError` exception class — `isError: true` tanpa retry guidance (abandoning path is desired reaction)
- [ ] Test: `tests/security/test_path_traversal.py`, `tests/security/test_config_secret_redaction.py`

## Implementation Notes
- Path validation: `os.path.realpath(path).startswith(project_root)`
- Config file detection: filename pattern (`application.properties`, `application.yml`, `*.liquid`)
- Config parser: extract key only, skip value
- For YAML: `yaml.safe_load` tapi hanya store key path, not value

## Priority
P2 — critical security hardening. Path traversal = data leak ke AI agent.
```

---

### 📋 Issue #18 [P2] — Search Quality Loop (Field-Qualified Query Parser)

```markdown
**Title:** [P2] Search quality loop — field-qualified query parser + FTS5 + corroboration ranking

## Motivation
CodeLens `search` command hanya regex. Tidak support field-qualified query (`kind:function name:auth path:src/api authenticate`).

CodeGraph punya sophisticated search:
- Field-qualified parser (`kind:`, `lang:`, `path:`, `name:`)
- FTS5 full-text search untuk free-text portion
- Corroboration ranking (how well each result di-corroborate oleh rest of query)
- Edit distance untuk fuzzy matching
- Path relevance scoring
- Name match bonus + kind bonus
- Test file deprioritization
- Generated file rank last

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/search/query-parser.ts` (parseQuery, boundedEditDistance)
  - `src/search/query-utils.ts` (kindBonus, nameMatchBonus, scorePathRelevance, isTestFile, isGeneratedFile)
  - `src/db/queries.ts` (FTS5 integration)
  - `__tests__/search-query-parser.test.ts`
  - `__tests__/context-ranking.test.ts`
  - `__tests__/same-name-disambiguation.test.ts`
  - `__tests__/symbol-lookup.test.ts`
  - `docs/SEARCH_QUALITY_LOOP.md`

## Current State
- CodeLens: `search` command regex only
- CodeLens: `symbols` command dengan `--fuzzy` flag, basic

## Acceptance Criteria
- [ ] Field-qualified query parser di `scripts/search/query_parser.py`:
  - Recognized fields: `kind:`, `lang:` (alias `language:`), `path:`, `name:`
  - Unknown field (`foo:bar`) → pass through to FTS as plain text
  - Quoting: `path:"src/some path/with spaces"`
  - Free-text portion → FTS5
- [ ] FTS5 full-text search untuk free-text (SQLite FTS5 module)
- [ ] Corroboration ranking: weigh how well each result di-corroborate oleh rest of query (avoid common word hijack)
- [ ] Edit distance fuzzy matching (`boundedEditDistance`)
- [ ] Path relevance scoring (`scorePathRelevance`)
- [ ] Name match bonus (`nameMatchBonus`) + kind bonus (`kindBonus`)
- [ ] Test file deprioritization (`isTestFile` — `*test*`, `*spec*`, `__tests__/`, `tests/`)
- [ ] Generated file rank last (`isGeneratedFile` — `*.pb.go`, `*.pulsar.go`, mock outputs)
- [ ] Integrasi dengan `search` dan `symbols` command
- [ ] Integrasi dengan `codelens_explore` (Issue #1) — query parsing untuk natural language
- [ ] Test: `tests/search/test_query_parser.py`, `tests/search/test_ranking.py`

## Implementation Notes
- Python FTS5: `sqlite3` module dengan FTS5 extension (built-in di Python 3.9+)
- Edit distance: `difflib.SequenceMatcher` atau implement Levenshtein
- Field parser: regex `(\w+):"([^"]+)"|(\w+):(\S+)`
- Corroboration: untuk setiap result, score = sum of (result relevance to each query term)

## Priority
P2 — improve search precision, reduce false positive.
```

---

### 📋 Issue #19 [P2] — Reasoning Offload (BYO Endpoint, Opt-In)

```markdown
**Title:** [P2] Reasoning offload — BYO endpoint, agent sees answer not raw source

## Motivation
CodeLens `codelens_explore` return raw source + call path + blast radius. Agent harus read + reason sendiri. Untuk query complex, ini banyak token.

CodeGraph punya reasoning offload (opt-in, BYO endpoint):
- `codegraph_explore` retrieval LOCAL (sama seperti sekarang)
- Lalu kirim assembled source context + user's query ke remote OpenAI-compatible reasoning model
- Model returns tight, self-contained answer → THAT answer jadi result of tool call
- Calling agent sees answer, not raw source dump
- Trades network round-trip for far fewer main-context tokens

Strictly degradable: any failure → return null → caller falls back to local source verbatim. NEVER throws, NEVER `isError` (one isError early → agent abandon tool).

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/reasoning/reasoner.ts` (Reasoner class, offload logic)
  - `src/reasoning/config.ts` (OffloadConfig, env var parsing)
  - `src/reasoning/login.ts` (device flow OAuth RFC 8628)
  - `src/reasoning/credentials.ts` (token storage)
  - `scripts/agent-eval/offload-eval.md` (eval harness)
  - `scripts/agent-eval/offload-eval-*.sh` / `.mjs`

## Current State
- CodeLens: tidak ada reasoning offload (return raw source, agent reason sendiri)

## Acceptance Criteria
- [ ] Reasoning offload di `scripts/mcp/reasoner.py`:
  - Config: `~/.codelens/config.json` under `offload` key (per-machine, not per-project)
  - **Managed tier** ("CodeLens AI") — `codelens login` device flow, metered gateway
  - **BYO endpoint** — `CODELENS_OFFLOAD_URL`, `CODELENS_OFFLOAD_MODEL`, `CODELENS_OFFLOAD_API_KEY` (atau `keyEnv` env var name, API key NEVER written to disk)
- [ ] Flow:
  1. `codelens_explore` retrieval local (sama seperti sekarang)
  2. Assemble source context + user's query
  3. Send ke remote OpenAI-compatible endpoint (`POST /v1/chat/completions`)
  4. Model return tight answer
  5. THAT answer jadi result of tool call (agent sees answer, not raw source)
- [ ] Calibration prompt: correctness-first (relevance check + leading coverage verdict + cite-don't-guess), `file:line` citations
- [ ] Strictly degradable:
  - No endpoint configured → return local source verbatim (current behavior)
  - Network/timeout/non-2xx/empty answer → return null → caller fall back to local source
  - NEVER throws to tool layer
  - NEVER `isError` (one isError early → agent abandon tool)
- [ ] Env var override file config (CI / ephemeral / advanced use)
- [ ] `codelens offload set-endpoint <url>` CLI
- [ ] `codelens offload status` CLI
- [ ] `codelens login` device flow (OAuth RFC 8628) untuk managed tier
- [ ] Test: `tests/mcp/test_reasoner.py` (mock endpoint)

## Implementation Notes
- HTTP client: `urllib.request` atau `httpx` (sudah common dependency)
- OpenAI-compatible API: `POST /v1/chat/completions` dengan `model`, `messages`, `temperature`, `max_tokens`
- Token storage: `~/.codelens/credentials.json` (revocable, org-scoped)
- API key in env var: `keyEnv: "CODELENS_OFFLOAD_API_KEY"` (nama env var disimpan, bukan value)

## Priority
P2 — opt-in feature untuk user yang mau maximize token efficiency. Default off (local source).
```

---

### 📋 Issue #20 [P2] — Agent Benchmark Harness (7 Real-World Codebase)

```markdown
**Title:** [P2] Agent benchmark harness — 7 real-world codebase, measure tool calls + time + tokens + cost

## Motivation
CodeLens `benchmarks/` hanya measure akurasi engine (precision/recall vs ground truth). Tidak measure **agent behavior** dengan CodeLens:
- Berapa tool call untuk answer question?
- Berapa wall-clock time?
- Berapa file read?
- Berapa token consumed?
- Berapa cost?

CodeGraph punya agent benchmark dengan 7 real-world codebase (VS Code, Excalidraw, Django, Tokio, OkHttp, Gin, Alamofire), median of 4 runs per arm, WITH vs WITHOUT CodeGraph. Result: 58% fewer tool calls, 22% faster, file reads → ~zero.

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `scripts/agent-eval/` (40+ script: run-agent.sh, run-arms.sh, ab-*.sh, probe-*.mjs, parse-*.mjs, offload-eval-*.sh)
  - `docs/benchmarks/answer-directly-vs-explore-agent.md`
  - `docs/benchmarks/call-sequence-analysis.md`
  - `docs/benchmarks/codegraph-ab-matrix.md`
  - README "Benchmark Results" section

## Current State
- CodeLens: `benchmarks/` dengan fixture + ground_truth.yaml, measure engine akurasi only
- CodeLens: tidak ada agent behavior benchmark

## Acceptance Criteria
- [ ] Benchmark harness di `benchmarks/agent_eval/`:
  - 7 real-world codebase fixture (port dari CodeGraph atau pilih sendiri):
    1. VS Code (TypeScript, ~10k files)
    2. Excalidraw (TypeScript, ~640 files)
    3. Django (Python, ~3k files)
    4. Tokio (Rust, ~790 files)
    5. OkHttp (Java, ~645 files)
    6. Gin (Go, ~110 files)
    7. Alamofire (Swift, ~110 files)
  - Setiap codebase: 1 canonical architecture question (e.g., "How does the extension host communicate with the main process?")
- [ ] Harness: `claude -p` (atau `codex -p`) headless, `--strict-mcp-config`:
  - **WITH** = CodeLens MCP server enabled
  - **WITHOUT** = empty MCP config (built-in Read/Grep/Bash tetap available)
  - 4 runs per arm, median reported
- [ ] Metrics per run:
  - Wall-clock time
  - File reads (count)
  - Grep/Bash calls (count)
  - Tool calls total (count, including sub-agent)
  - Total tokens (input + output + cache)
  - Cost (`total_cost_usd`)
- [ ] Output: per-repo breakdown table + summary
- [ ] CI integration: `codelens-benchmark.yml` workflow, run saat release tag
- [ ] Regression: jika CodeLens dengan CodeLens result worse dari baseline → fail CI
- [ ] Script: `benchmarks/agent_eval/run_benchmark.sh` (orchestrator), `parse_session.py` (transcript parser)

## Implementation Notes
- Headless agent: `claude -p` (Claude Code) atau `codex -p` (Codex CLI)
- `--strict-mcp-config`: force MCP config, disable auto-discovery
- Transcript parsing: JSONL output dari `claude -p`, parse untuk tool call count + token usage
- Cost: `total_cost_usd` field di transcript
- Codebase fixture: `git clone --depth 1` saat benchmark run, cache di `~/.codelens-benchmark/`

## Priority
P2 — critical untuk measure agent impact. Tanpa ini, tidak tahu apakah CodeLens benar-benar help agent.
```

---

### 📋 Issue #21 [P2] — Tree-Sitter WASM (Universal Cross-Platform)

```markdown
**Title:** [P2] Tree-sitter WASM — universal cross-platform, no native build

## Motivation
CodeLens pakai tree-sitter Python binding (`tree-sitter` PyPI package). Masalah:
- Butuh compile native extension (C library)
- Tidak work di environment tanpa compiler (alpine, slim Docker, sandboxed CI)
- Grammar package per-bahasa butuh compile juga (`tree-sitter-python`, `tree-sitter-javascript`, dll.)
- Tidak portable cross-platform (binary platform-specific)

CodeGraph pakai `web-tree-sitter` (WASM):
- Universal cross-platform (WASM run di mana saja)
- No native build (WASM file portable)
- Grammar file `.wasm` pre-compiled, tinggal download
- 24 bahasa didukung

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/extraction/tree-sitter.ts` (web-tree-sitter integration)
  - `src/extraction/grammars.ts` (WASM_GRAMMAR_FILES map, lazy load)
  - `src/extraction/wasm/` (24 .wasm grammar file, dari `tree-sitter-wasms` npm package)
  - `src/extraction/parse-worker.ts` (worker entry, each worker own WASM heap)
  - `package.json` (`web-tree-sitter` + `tree-sitter-wasms` dependency)
  - `BUNDLING.md` (bundled Node runtime + WASM)

## Current State
- CodeLens: `tree-sitter` Python binding (native compile required)
- CodeLens: `setup.sh` install grammar packages via pip (compile each)

## Acceptance Criteria
- [ ] Switch dari `tree-sitter` Python binding ke `tree-sitter-wasms` (PyPI package, WASM runtime untuk Python) atau `py-tree-sitter` dengan WASM backend
- [ ] Atau: bundle `web-tree-sitter` (Node.js WASM runtime) sebagai subprocess (CodeLens Python invoke Node subprocess untuk parse)
- [ ] 24 .wasm grammar file di `scripts/extraction/wasm/` (port dari CodeGraph atau dari `tree-sitter-wasms` npm package)
- [ ] Lazy load: hanya load grammar untuk bahasa yang ada di project
- [ ] No native build step (WASM file pre-compiled, portable)
- [ ] Test di environment tanpa compiler: Alpine Linux, `python:3-slim` Docker, sandboxed CI
- [ ] Performance: WASM sedikit lebih lambat dari native (~20%), tapi acceptable untuk trade-off portability
- [ ] Fallback: jika WASM tidak available, fallback ke regex parser (sudah ada di CodeLens)
- [ ] Test: `tests/extraction/test_wasm_parser.py`

## Implementation Notes
- Python WASM runtime: `wasmer` atau `wasmtime` PyPI package (run .wasm file)
- Atau: `py-tree-sitter` versi terbaru yang support WASM backend
- Atau: subprocess ke `node` dengan `web-tree-sitter` (tapi butuh Node installed)
- Grammar file: download dari `tree-sitter-wasms` npm package atau dari CodeGraph repo (MIT license, compatible)
- Cache: `~/.codelens/grammars/` (lazy download saat first use, SHA-256 verify)

## Priority
P2 — critical untuk distribution (Issue #12 opengrep doc, self-contained binary). Tanpa WASM, binary perlu compile per-platform.
```

---

### 📋 Issue #22 [P2] — Self-Contained Binary (Bundled Python Runtime)

```markdown
**Title:** [P2] Self-contained binary — bundled Python runtime, no native build

## Motivation
CodeLens saat ini hanya bisa dijalankan dengan `python3 scripts/codelens.py <command>`, yang require:
1. Python 3.8+ terinstall
2. `pip install tree-sitter pyyaml watchdog` + 10 grammar package
3. `bash setup.sh` (1-3 menit install)

Barrier adopsi tinggi untuk: CI/CD pipeline (cold start lambat), user non-Python, pre-commit hook (setup manual per repo).

CodeGraph ship self-contained bundle: vendored Node runtime + compiled app + tree-sitter WASM grammars. No native build, no Node-version dependence, works on any platform.

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `BUNDLING.md` (bundle structure, 6 target)
  - `scripts/build-bundle.sh` (build script per platform)
  - `install.sh` (Linux/macOS installer)
  - `install.ps1` (Windows installer)
  - `package.json` (`bin`, `files`, `scripts.build`)

## Current State
- CodeLens: `python3 scripts/codelens.py` only, require Python 3.8+ + setup.sh
- CodeLens: tidak ada binary release

## Acceptance Criteria
- [ ] Build script `scripts/build-binary.sh` — produce single binary `codelens` (Linux x64/arm64, macOS x64/arm64, Windows x64/arm64)
- [ ] Bundle include:
  - Python runtime (statically linked, ~30MB)
  - All CodeLens source (`scripts/`)
  - PyYAML + watchdog + tree-sitter (atau tree-sitter WASM dari Issue #21)
  - All grammar packages (atau .wasm file dari Issue #21)
- [ ] Binary size target: <80MB (compressed)
- [ ] Cold start time: <500ms (vs 200-500ms per CLI invocation saat ini via python3)
- [ ] 6 platform target:
  - `codelens-linux-x64`
  - `codelens-linux-arm64`
  - `codelens-darwin-x64` (macOS Intel)
  - `codelens-darwin-arm64` (macOS Apple Silicon)
  - `codelens-win32-x64.exe`
  - `codelens-win32-arm64.exe`
- [ ] `install.sh` (Linux/macOS) + `install.ps1` (Windows) — download binary dari GitHub Releases, install ke `/usr/local/bin/codelens` (atau `%LOCALAPPDATA%\Programs\codelens\`)
- [ ] GitHub Actions release workflow: build 6 target, upload ke Releases, sign dengan SHA256SUMS (atau minisign dari Issue #12 UBS doc)
- [ ] Test binary di fresh Docker container (Ubuntu, Debian, Alpine, macOS, Windows) untuk verify no system dependency
- [ ] `codelens upgrade` (Issue #12) support bundle install method

## Implementation Notes
- Python binary builder: **PyInstaller** (most common, mature) atau **Nuitka** (compile ke C, lebih cepat)
- PyInstaller: `pyinstaller --onefile --add-data 'scripts:scripts' --add-data 'data:data' scripts/codelens.py`
- Tree-sitter native: bundle `.so`/`.dll` explicit via `--add-binary`
- Tree-sitter WASM (Issue #21): bundle `.wasm` file via `--add-data`, lebih portable
- Watchdog: lazy-import (hanya untuk `watch` command) agar tidak wajib di binary
- Test: `docker run --rm -v $(pwd):/workspace ubuntu:22.04 /workspace/codelens --help`

## Priority
P2 — high UX impact, critical untuk adopsi non-Python user. Depend on Issue #21 (WASM) untuk portability maksimal.
```

---

### 📋 Issue #23 [P2] — Worktree Mismatch Detection

```markdown
**Title:** [P2] Worktree mismatch detection — warn saat run dari worktree tapi resolve main checkout index

## Motivation
CodeLens tidak ada worktree awareness. Saat run dari git worktree nested inside main checkout (e.g. `.claude/worktrees/<name>/`), walk-up ke parent `.codelens/` resolve MAIN checkout index (branch berbeda). Setiap query return results dari main tree's code, bukan worktree yang user edit. Symbols added/changed hanya di worktree invisible.

CodeGraph detect ini dan warning di `codegraph status` + setiap read tool call.

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/sync/worktree.ts` (gitWorktreeRoot, detectWorktreeIndexMismatch, worktreeMismatchWarning)
  - `__tests__/worktree-detection.test.ts`
  - CHANGELOG v0.9.5: "Git worktrees no longer silently borrow another tree's index"
  - CHANGELOG v0.9.7: "running CodeGraph from a worktree nested inside the main checkout used to return the wrong branch's code with no warning"

## Current State
- CodeLens: tidak ada worktree detection (silent wrong result possible)

## Acceptance Criteria
- [ ] `gitWorktreeRoot(dir)` function: `git rev-parse --show-toplevel` return per-worktree root
- [ ] `detectWorktreeIndexMismatch(project_root)`:
  - Cek apakah `.codelens/` resolve ke parent directory (bukan current worktree root)
  - Return mismatch info: `{ worktree_root, main_checkout_root, index_root }`
- [ ] Warning di `codelens status` output:
  ```
  ⚠️ Worktree index mismatch detected:
    You are in worktree: /path/to/.claude/worktrees/feature-x
    But .codelens/ resolves to: /path/to/main-checkout (different branch)
  
  Run `codelens init -i` in the worktree to build its own index.
  ```
- [ ] Warning di setiap MCP tool response (read tool): prepend banner
- [ ] Saran: `codelens init -i` di worktree untuk build own index
- [ ] Test: `tests/sync/test_worktree_detection.py`

## Implementation Notes
- `subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=dir)`
- Walk up parent directory untuk find `.codelens/`
- Compare worktree root vs `.codelens/` location

## Priority
P2 — critical untuk git worktree user. Silent wrong result = agent trust broken.
```

---

### 📋 Issue #24 [P3] — Anonymous Telemetry (Opt-In, Public Worker Code)

```markdown
**Title:** [P3] Anonymous telemetry — opt-in default, public worker code, DO_NOT_TRACK honored

## Motivation
CodeLens tidak ada telemetry. Tidak tahu:
- Command/tool mana yang paling used
- Bahasa mana yang paling indexed
- Agent mana yang drive usage
- File count distribution user

CodeGraph punya anonymous telemetry dengan 4 invariant:
1. Zero hot-path cost (in-memory increment, disk write di process exit, network opportunistic)
2. Zero stdout (stdio is MCP channel, stderr only)
3. Off is off (disabled → nothing recorded, nothing sent, no "opted out" ping, delete buffered)
4. Fail silent (offline/down → silence, no retry, no error surfaced)

Collected: which tools/commands used, which languages indexed, which agents, file count bucket. NEVER: code, paths, file/symbol names, queries, IP.

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/telemetry/index.ts` (client side)
  - `telemetry-worker/` (Cloudflare Worker, public code, ingest endpoint)
  - `TELEMETRY.md` (full field list, off-switches, data-handling story)
  - `docs/design/telemetry.md`

## Current State
- CodeLens: tidak ada telemetry

## Acceptance Criteria
- [ ] Telemetry module di `scripts/telemetry/__init__.py`:
  - In-memory increment (counter per event)
  - Disk write di process exit (`atexit` handler, sync append ke `~/.codelens/telemetry-buffer.json`)
  - Network send opportunistic (startup of long-running command, daemon interval, bounded await di end of install/init)
  - Fire-and-forget everywhere else
- [ ] 4 invariant:
  1. Zero hot-path cost (in-memory, no I/O di critical path)
  2. Zero stdout (stderr only, stdio is MCP channel)
  3. Off is off (disabled → nothing recorded, no "opted out" ping, delete buffered)
  4. Fail silent (offline/down/disk full → silence, no retry loop, no error surfaced)
- [ ] Collected fields (allowlist, enforced by ingest endpoint):
  - `event_type`: `mcp_tool` | `cli_command` | `lifecycle` (install/index/uninstall)
  - `event_name`: tool name / command name / lifecycle stage
  - `language`: bahasa yang di-index (jika relevan)
  - `agent`: agent yang drive usage (jika detected)
  - `file_count_bucket`: `<100` | `100-1k` | `1k-10k` | `10k+`
  - `schema_version`: integer
  - `machine_id`: random UUID (anonymous, per-machine)
  - `timestamp`: UTC date (per-day rollup, only completed days sent)
- [ ] NEVER collected: code, paths, file/symbol names, queries, IP addresses
- [ ] Off-switches:
  - `codelens telemetry off` (store choice, delete unsent data)
  - `CODELENS_TELEMETRY=0` (per-shell/CI override)
  - `DO_NOT_TRACK=1` (cross-tool standard, always honored)
- [ ] `codelens telemetry status` — show current state, what decided it, machine ID
- [ ] Installer asks up front (visible default-on toggle, never re-ask)
- [ ] If user never saw installer (e.g. `npx` straight into `init`): 1-line notice ke stderr before first send
- [ ] Ingest endpoint: public code (Cloudflare Worker atau simple FastAPI), enforce field allowlist
- [ ] Test: `tests/telemetry/test_telemetry.py`

## Implementation Notes
- Per-day rollup: aggregate count per (event_type, event_name, language, agent) per UTC day
- Only completed UTC days sent (today's data stays in buffer until tomorrow)
- Network: `urllib.request` POST JSON, fire-and-forget dengan `threading.Thread` daemon
- Machine ID: `random.uuid4()`, store di `~/.codelens/machine_id`
- Buffer file: `~/.codelens/telemetry-buffer.json`, max 256KB, rotate if exceed

## Priority
P3 — nice-to-have untuk product intelligence. Default opt-in, easy opt-out.
```

---

### 📋 Issue #25 [P3] — `codegraph.json` Config (Exclude + Extensions)

```markdown
**Title:** [P3] `codelens.json` config — exclude (gitignore-style) + extensions (custom mapping)

## Motivation
CodeLens `.codelens/codelens.config.json` saat ini terbatas. Tidak support:
- `exclude` gitignore-style untuk committed directory yang `.gitignore` tidak bisa drop
- `extensions` custom file extension → language mapping

CodeGraph punya `codegraph.json` di project root:
```json
{
  "exclude": ["static/", "**/vendor/**"],
  "extensions": {
    ".dota_lua": "lua",
    ".tpl": "php"
  }
}
```

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - README "Configuration" section
  - `src/project-config.ts` (loadExtensionOverrides, config parsing)
  - CHANGELOG v1.1.2: "exclude committed directories from the index with an exclude list in codegraph.json"
  - CHANGELOG v0.9.2: ".codegraphignore marker is no longer supported; use .gitignore instead"

## Current State
- CodeLens: `.codelens/codelens.config.json` dengan schema berbeda
- CodeLens: `DEFAULT_IGNORE_DIRS` hardcoded di `utils.py`
- CodeLens: tidak ada custom extension mapping

## Acceptance Criteria
- [ ] `codelens.json` di project root (bukan di `.codelens/`)
- [ ] Field `exclude`: gitignore-style patterns, matched against repo-root-relative paths
  - Honor di index, sync, watch
  - Untuk committed directory yang `.gitignore` tidak bisa drop (vendored theme, bundled SDK)
  - Pattern: `**` recursive, `*` wildcard, `?` single char
- [ ] Field `extensions`: custom file extension → language id mapping
  - Merge on top of built-in defaults, win on conflict
  - Bisa re-point built-in (e.g. `".h": "cpp"`)
  - Commit file untuk share mapping dengan team
  - Typo'd language or malformed file → warned and skipped (never breaks indexing)
- [ ] Project dengan no `codelens.json` → behave exactly as before
- [ ] Re-index (`codelens scan`) required after adding/changing mappings
- [ ] Test: `tests/test_project_config.py`

## Implementation Notes
- Config schema: JSON dengan 2 optional field (`exclude`, `extensions`)
- Pattern matching: `pathspec` PyPI package (gitignore spec compliant)
- Extension override: merge dict, custom override default

## Priority
P3 — nice-to-have untuk project dengan custom convention.
```

---

### 📋 Issue #26 [P3] — Generated File Detection (Rank Last)

```markdown
**Title:** [P3] Generated file detection — protobuf, gRPC stubs, mocks rank last di search

## Motivation
CodeLens `is_bundled_file()` di `utils.py` detect bundled file, tapi tidak detect generated file (protobuf, gRPC stubs, mocks, build output). Generated file sering punya huge in-file edge count yang dwarf real source (e.g. etcd's `rpc.pb.go` 4× edge dari `server.go`).

CodeGraph `isGeneratedFile` rank last di search, trace, explore — result land di real implementation, bukan auto-generated placeholder.

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/extraction/generated-detection.ts` (isGeneratedFile)
  - `src/db/queries.ts` (`isLowValueFile` heuristic untuk test + generated)
  - `__tests__/generated-detection.test.ts`
  - CHANGELOG v0.9.7: "Generated files (protobuf, gRPC stubs, mocks, build output) now rank last in search, trace, and explore"

## Current State
- CodeLens: `is_bundled_file()` detect dist/build/vendor, tapi tidak generated
- CodeLens: tidak ada rank-last logic di search

## Acceptance Criteria
- [ ] `is_generated_file(path)` function di `scripts/utils.py`:
  - Detect pattern:
    - `*.pb.go` (protobuf Go)
    - `*.pulsar.go` (Pulsar Go)
    - `*_generated.go` (Go generated)
    - `*.pb.ts` (protobuf TypeScript)
    - `*.generated.js` (JS generated)
    - `*_mock.go` / `*_mock.py` / `*.mock.js` (mock)
    - `*/gen/*` (generated directory)
    - `*/autogen/*` (autogen directory)
    - `*/build/*` (build output, jika tidak di-ignore)
  - Return `True` jika match
- [ ] Rank last di search: `codelens search` result sort dengan generated file di akhir
- [ ] Rank last di trace: `codelens trace` skip generated file kecuali explicitly named
- [ ] Rank last di `codelens_explore`: generated file skeletonized atau skipped
- [ ] `is_low_value_file(path)` heuristic: test/spec file + generated file → tidak kandidat untuk "dominant file" detection
- [ ] Test: `tests/test_generated_detection.py`

## Implementation Notes
- Regex pattern per file extension
- Untuk content-based detection (e.g. `// Code generated by protoc-gen-go`): baca first 5 lines, cek comment
- Rank-last: sort key `(is_generated, relevance_score)` — generated file selalu di akhir

## Priority
P3 — improve search precision untuk project dengan generated code.
```

---

### 📋 Issue #27 [P3] — Library API (Embed di App Lain)

```markdown
**Title:** [P3] Library API — embed CodeLens di app lain (Electron, custom tool)

## Motivation
CodeLens saat ini hanya CLI + MCP server. Tidak bisa di-embed di app lain (Electron main process, custom dev tool, IDE plugin).

CodeGraph re-export programmatic API dari npm package:
```typescript
import CodeGraph from '@colbymchenry/codegraph';
const cg = await CodeGraph.init('/path/to/project');
await cg.indexAll({ onProgress: (p) => console.log(`${p.phase}: ${p.current}/${p.total}`) });
const results = cg.searchNodes('UserService');
const callers = cg.getCallers(results[0].node.id);
cg.watch();
cg.close();
```

## Reference
- Repo: https://github.com/colbymchenry/codegraph
- File referensi:
  - `src/index.ts` (CodeGraph class, public API surface)
  - README "Library Usage" section
  - CHANGELOG v0.9.8: "CodeGraph is usable as an embedded library again"

## Current State
- CodeLens: hanya CLI + MCP, tidak ada library API

## Acceptance Criteria
- [ ] Library API di `scripts/codelens_lib.py` (atau `codelens/__init__.py` jika restructure ke package):
  ```python
  from codelens import CodeLens
  
  cg = CodeLens.init('/path/to/project')
  cg.index_all(on_progress=lambda p: print(f"{p.phase}: {p.current}/{p.total}"))
  results = cg.search_nodes('UserService')
  callers = cg.get_callers(results[0].node.id)
  context = cg.build_context('fix login bug', max_nodes=20, include_code=True, format='markdown')
  impact = cg.get_impact_radius(results[0].node.id, 2)
  cg.watch()  # auto-sync on file changes
  cg.unwatch()
  cg.close()
  ```
- [ ] Building blocks juga di-export: `DatabaseConnection`, `QueryBuilder`, `get_database_path`, `init_grammars`, `FileLock`
- [ ] PyPI package `codelens` (publish via Issue #11 opengrep doc atau #19 opengrep doc)
- [ ] Embedding requirements: Python 3.8+, tree-sitter + grammar packages installed
- [ ] TypeScript types untuk user yang pakai dari TypeScript (via `pyright` stubs)
- [ ] Dokumentasi: `references/library-api.md` dengan 20+ contoh
- [ ] Test: `tests/test_library_api.py`

## Implementation Notes
- Restructure CodeLens ke Python package (`codelens/` directory, bukan `scripts/`)
- `setup.py` atau `pyproject.toml` dengan `entry_points` untuk CLI + `codelens` package untuk library
- Public API surface: hanya `CodeLens` class + building blocks, hide internal implementation
- Reuse semua engine yang sudah ada (`callgraph_engine.py`, `impact_engine.py`, dll.)

## Priority
P3 — nice-to-have untuk embed di Electron/IDE plugin. Low effort jika restructure package sudah dilakukan.
```

---

## 6. Prioritas & Roadmap

### 6.1 Rekomendasi urutan eksekusi (quarter-based)

**Q3 2026 (P0 — Architecture Foundation):**
1. Issue #1 — Single-tool MCP philosophy (refactor 49 → 1-3 tool)
2. Issue #2 — Auto-sync native file watcher
3. Issue #3 — Per-file staleness banner + connect-time catch-up
4. Issue #4 — Shared daemon architecture
5. Issue #5 — Worker-thread pool untuk query + parse
6. Issue #6 — Watchdog stack (PPID + liveness + stdin)

**Q4 2026 (P1 — Agent Integration & Coverage):**
7. Issue #7 — AgentTarget abstraction + 8 agent installer
8. Issue #8 — Dynamic-dispatch synthesizer (21 pattern)
9. Issue #9 — Dynamic-boundary detection (9 form)
10. Issue #10 — `affected` command (transitive test file trace)
11. Issue #11 — Git sync hooks (post-commit/merge/checkout)
12. Issue #12 — `upgrade` command (in-place self-update)
13. Issue #13 — Framework-aware routes (17 framework)

**Q1 2027 (P2 — Depth & Distribution):**
14. Issue #14 — Adaptive explore sizing (skeletonize sibling)
15. Issue #15 — Blast radius summary inline di `codelens_explore`
16. Issue #16 — Value reference edges
17. Issue #17 — Path traversal protection + config secret redaction
18. Issue #18 — Search quality loop (field-qualified parser)
19. Issue #19 — Reasoning offload (BYO endpoint)
20. Issue #20 — Agent benchmark harness (7 real-world codebase)
21. Issue #21 — Tree-sitter WASM (universal cross-platform)
22. Issue #22 — Self-contained binary (bundled Python runtime)
23. Issue #23 — Worktree mismatch detection

**Q2 2027 (P3 — Polish & DX):**
24. Issue #24 — Anonymous telemetry
25. Issue #25 — `codelens.json` config (exclude + extensions)
26. Issue #26 — Generated file detection (rank last)
27. Issue #27 — Library API (embed di app lain)

### 6.2 Dependency graph

```
Issue #1 (single-tool MCP) ──→ Issue #14 (adaptive sizing, di explore)
                          ──→ Issue #15 (blast radius inline, di explore)
                          ──→ Issue #19 (reasoning offload, di explore)

Issue #2 (native watcher) ──→ Issue #3 (staleness banner, depend on watcher)
                         ──→ Issue #4 (daemon, share 1 watcher)
                         ──→ Issue #11 (git hooks, fallback saat watcher disabled)

Issue #3 (staleness + catch-up) ──→ Issue #4 (daemon, catch-up saat reconnect)

Issue #4 (shared daemon) ──→ Issue #5 (worker pool, daemon butuh pool untuk concurrent client)
                       ──→ Issue #6 (watchdog, daemon butuh orphan detection)

Issue #5 (worker pool) ──→ Issue #21 (WASM, worker butuh WASM heap)

Issue #6 (watchdog) ──→ Issue #4 (daemon, watchdog kill orphan daemon)

Issue #7 (agent installer) ──→ Issue #12 (upgrade, installer detect method)
                           ──→ Issue #22 (binary, installer download binary)

Issue #8 (dynamic-dispatch synthesizer) ──→ Issue #9 (boundary detection, complement synthesizer)
                                       ──→ Issue #1 (explore, surface synthesized edge)

Issue #10 (affected) ──→ Issue #15 (blast radius, test file coverage)

Issue #13 (framework routes) ──→ Issue #8 (synthesizer, framework dispatch)

Issue #16 (value reference edges) ──→ Issue #15 (blast radius, value consumer)

Issue #17 (security) — independen

Issue #18 (search quality) ──→ Issue #1 (explore, query parsing)

Issue #19 (reasoning offload) ──→ Issue #1 (explore, offload di explore)

Issue #20 (agent benchmark) ──→ Issue #1 (explore, benchmark explore)

Issue #21 (WASM) ──→ Issue #22 (binary, WASM untuk portability)
                ──→ Issue #5 (worker pool, WASM heap per worker)

Issue #22 (binary) ──→ Issue #7 (installer, download binary)
                  ──→ Issue #12 (upgrade, binary upgrade)

Issue #23 (worktree) — independen
Issue #24 (telemetry) — independen
Issue #25 (codelens.json) — independen
Issue #26 (generated detection) ──→ Issue #18 (search, rank last)
Issue #27 (library API) — depend on package restructure
```

### 6.3 Yang TIDAK perlu diserap dari CodeGraph

Untuk menjaga niche CodeLens sebagai code intelligence + security + frontend platform:

1. ❌ **Reasoning offload managed tier** ("CodeLens AI" metered gateway) — CodeLens tidak butuh SaaS revenue model. Cukup BYO endpoint saja (Issue #19).
2. ❌ **`codegraph login` device flow** untuk managed tier — sama, tidak butuh auth. Tapi jika user request auth untuk plugin marketplace (Issue #23 opengrep doc), bisa adopt.
3. ❌ **Mixed iOS/RN/Expo bridging** — terlalu niche (hanya untuk mobile cross-platform project). Skip kecuali ada demand tinggi dari iOS/RN user.
4. ❌ **Anonymous class extraction** untuk Java/C# — terlalu spesifik. CodeLens `callgraph_engine.py` sudah handle case umum.
5. ❌ **Interface→implementation linking** multi-language — CodeLens `callgraph_engine.py` inter-procedural sudah cukup untuk case umum. Hanya adopt jika ada gap di real-world test.
6. ❌ **Telemetry Cloudflare Worker** — overkill untuk CodeLens. Simple Python telemetry endpoint cukup.
7. ❌ **Codex CLI v0.77.0+ format migration** — terlalu spesifik ke Codex, biarkan user manual migrate.
8. ❌ **Adaptive explore sizing refinement** (supertype family override) — terlalu sophisticated, start simple (Issue #14 v1).

### 6.4 Synergy dengan dokumen opengrep + UBS (sebelumnya)

Beberapa issue di dokumen ini overlap dengan dokumen sebelumnya. Mapping:

| Issue CodeGraph doc | Issue opengrep doc | Issue UBS doc | Notes |
|---|---|---|---|
| #1 (single-tool MCP) | — | — | Baru, hanya di CodeGraph doc |
| #2 (native watcher) | — | — | Baru, hanya di CodeGraph doc |
| #3 (staleness + catch-up) | — | — | Baru, hanya di CodeGraph doc |
| #4 (shared daemon) | — | — | Baru, hanya di CodeGraph doc |
| #5 (worker pool) | #21 (UBS: --jobs + --only) | — | Mirip, gabungkan |
| #6 (watchdog stack) | — | — | Baru, hanya di CodeGraph doc |
| #7 (agent installer) | — | #4 (UBS: 12+ agent) | Mirip, gabungkan — CodeGraph lebih sophisticated (AgentTarget abstraction) |
| #8 (dynamic-dispatch synthesizer) | — | — | Baru, hanya di CodeGraph doc |
| #9 (boundary detection) | — | — | Baru, hanya di CodeGraph doc |
| #10 (affected) | — | — | Baru, hanya di CodeGraph doc |
| #11 (git sync hooks) | — | — | Baru, hanya di CodeGraph doc |
| #12 (upgrade) | — | #25 (UBS: --dry-run + --self-test + --uninstall) | Mirip, gabungkan |
| #13 (framework routes) | — | — | Baru, hanya di CodeGraph doc |
| #14 (adaptive sizing) | — | — | Baru, hanya di CodeGraph doc |
| #15 (blast radius inline) | — | — | Baru, hanya di CodeGraph doc |
| #16 (value reference edges) | — | — | Baru, hanya di CodeGraph doc |
| #17 (path traversal + secret redaction) | — | — | Baru, hanya di CodeGraph doc |
| #18 (search quality) | — | — | Baru, hanya di CodeGraph doc |
| #19 (reasoning offload) | — | — | Baru, hanya di CodeGraph doc |
| #20 (agent benchmark) | — | — | Baru, hanya di CodeGraph doc |
| #21 (tree-sitter WASM) | #12 (opengrep: self-contained binary) | #11 (UBS: distribution) | Mirip, gabungkan |
| #22 (self-contained binary) | #12 (opengrep: self-contained binary) | #11 (UBS: distribution) | Mirip, gabungkan |
| #23 (worktree detection) | — | — | Baru, hanya di CodeGraph doc |
| #24 (telemetry) | — | — | Baru, hanya di CodeGraph doc |
| #25 (codelens.json config) | #20 (opengrep: metadata + paths) | #2 (UBS: .codelensignore) | Mirip, gabungkan |
| #26 (generated detection) | — | — | Baru, hanya di CodeGraph doc |
| #27 (library API) | — | — | Baru, hanya di CodeGraph doc |

**Rekomendasi:** saat create GitHub issue, reference ketiga dokumen (CodeGraph + opengrep + UBS) jika overlap. Untuk issue yang sama, pilih satu issue number (bukan duplicate). Priority: **CodeGraph doc issue number menang** untuk architecture-related (single-tool MCP, daemon, watcher, watchdog, synthesizer, boundary), **opengrep/UBS doc** untuk SAST/security/distribution-related.

---

## 7. Catatan Implementasi & Risiko

### 7.1 License compliance

- CodeGraph: **MIT license** — boleh copy-paste code ke CodeLens (juga MIT). Tapi attribution recommended.
- CodeLens MIT: aman reference + port code dari CodeGraph.
- `web-tree-sitter`: MIT license — boleh bundle WASM runtime.
- `tree-sitter-wasms`: MIT license — boleh bundle .wasm grammar file.
- Untuk port module TypeScript (`watcher.ts`, `daemon.ts`, `ppid-watchdog.ts`, dll): include attribution `# Ported from CodeGraph (https://github.com/colbymchenry/codegraph) MIT license`.

### 7.2 Backward compatibility

- **Issue #1 (single-tool MCP)**: refactor 49 → 1-3 tool adalah breaking change. Mitigasi:
  - Env var `CODELENS_MCP_LEGACY=1` expose all 49 tool (untuk user yang sudah depend)
  - Deprecation warning 1 version sebelum remove
  - Document migration path di `CHANGELOG.md` + `references/mcp-migration.md`
- **Issue #4 (shared daemon)**: default behavior change (sebelumnya 1 process per session). Mitigasi:
  - `CODELENS_NO_DAEMON=1` opt-out (1 independent server per client)
  - Document di README + SKILL.md
- **Issue #21 (tree-sitter WASM)**: backend change. Mitigasi:
  - Fallback ke native tree-sitter Python binding jika WASM unavailable
  - Document trade-off (portability vs performance) di `references/tree-sitter-backend.md`
- Semua fitur baru harus opt-in via flag atau file baru. Default behavior CodeLens tidak boleh break.

### 7.3 Performance budget

- **Issue #1 (single-tool MCP)**: `codelens_explore` response time <500ms untuk <1000 file project, <2s untuk 5000+ file
- **Issue #2 (native watcher)**: debounce 2s default, O(1) descriptor di macOS/Windows
- **Issue #4 (shared daemon)**: daemon startup <1s, idle timeout 300s
- **Issue #5 (worker pool)**: 2-4x speedup di 8-core machine, soft timeout 25s
- **Issue #6 (watchdog)**: PPID poll 5s, liveness heartbeat 1s, kill timeout 30s
- **Issue #8 (synthesizer)**: whole-graph pass <10s untuk 5000 file
- **Issue #14 (adaptive sizing)**: output budget 15000 char, skeletonize <100ms per file
- **Issue #21 (WASM)**: parse 20% slower dari native, acceptable
- **Issue #22 (binary)**: cold start <500ms, binary size <80MB

### 7.4 Testing strategy

- Setiap fitur baru harus ship dengan:
  1. Unit test (pytest, di `tests/unit/`)
  2. Integration test (di `tests/integration/` dengan fixture)
  3. Manifest test case (Issue #9 UBS doc, jika relevan)
  4. Agent benchmark (Issue #20, untuk fitur yang affect agent behavior)
- Real-world validation: run di repo test yang sudah ada di CHANGELOG CodeLens (spacedrive, redis, neovim, fastapi, exercism/python) + 7 codebase benchmark CodeGraph (VS Code, Excalidraw, Django, Tokio, OkHttp, Gin, Alamofire).
- Port test dari CodeGraph `__tests__/` (110 test file) untuk fitur yang di-port.

### 7.5 Security consideration

- **Issue #4 (shared daemon)**: Unix socket permission 0600 (hanya owner read/write), named pipe ACL
- **Issue #6 (watchdog)**: SIGKILL last resort, pastikan tidak kill wrong process (verify pid before kill)
- **Issue #17 (path traversal)**: resolve symlinks, refuse out-of-root, test dengan 30+ attack vector
- **Issue #19 (reasoning offload)**: API key in env var (never disk), strictly degradable (never isError), calibration prompt (cite-don't-guess)
- **Issue #24 (telemetry)**: 4 invariant (zero hot-path, zero stdout, off is off, fail silent), public worker code untuk audit, `DO_NOT_TRACK=1` honored

### 7.6 Documentation plan

Untuk setiap issue yang merged, update:
- `README.md` — user-facing documentation, quick start example
- `SKILL.md` — AI agent reference, command list
- `SKILL-QUICK.md` — quick reference card
- `CHANGELOG.md` — version history entry
- `references/<topic>.md` — detailed reference:
  - `references/mcp-single-tool-philosophy.md` (Issue #1)
  - `references/auto-sync-architecture.md` (Issue #2, #3, #4)
  - `references/worker-pool.md` (Issue #5)
  - `references/watchdog-stack.md` (Issue #6)
  - `references/agent-installer.md` (Issue #7)
  - `references/dynamic-dispatch-synthesizer.md` (Issue #8)
  - `references/dynamic-boundary-detection.md` (Issue #9)
  - `references/framework-routes.md` (Issue #13)
  - `references/reasoning-offload.md` (Issue #19)
  - `references/tree-sitter-wasm.md` (Issue #21)
- `CLAUDE.md` / `AGENTS.md` — jika fitur relevant untuk AI agent workflow
- `docs/architecture/` — design doc untuk fitur complex (port dari CodeGraph `docs/design/`)

---

## 8. Penutup

Analisis ini mengidentifikasi **27 issue upgrade** dari CodeGraph ke CodeLens, dengan breakdown:
- 6 issue P0 (architecture foundation: single-tool MCP, native watcher, staleness, daemon, worker pool, watchdog)
- 7 issue P1 (agent integration & coverage: installer, synthesizer, boundary, affected, git hooks, upgrade, framework routes)
- 10 issue P2 (depth & distribution: adaptive sizing, blast radius, value ref, security, search, reasoning, benchmark, WASM, binary, worktree)
- 4 issue P3 (polish & DX: telemetry, config, generated detection, library API)

CodeLens sudah unggul di 9 area (command breadth, security analysis, frontend analysis, plugin system, CVE scanning, guard hook, AI output, auto-setup, code intelligence) — pertahankan dan double-down di situ sebagai differentiator. Yang diserap dari CodeGraph adalah **architecture patterns, MCP design philosophy, auto-sync reliability, agent integration framework, dynamic-dispatch coverage, distribution** — area di mana CodeGraph lebih matang.

CodeGraph dan CodeLens **direct competitor di niche yang sama** (AI-native code intelligence). CodeGraph menang di **architecture core** (daemon, worker pool, WAL, watcher, watchdog stack, single-tool philosophy). CodeLens menang di **breadth** (58 command, security, frontend, plugin, guard).

CodeLens tidak boleh kalah di architecture core — serap patterns CodeGraph agar tidak left behind. Setelah serapan ini, CodeLens akan menjadi **code intelligence + security + frontend platform yang juga punya architecture reliability CodeGraph** — best of both worlds.

Eksekusi sesuai roadmap Q3 2026 → Q2 2027, dengan dependency graph sebagai panduan urutan. Patoki backward compatibility (terutama Issue #1 single-tool MCP adalah breaking change), performance budget, testing strategy, dan security consideration agar tidak break adoption existing.

**Prioritas tertinggi (P0 — Q3 2026):** Issue #1 sampai #6 — architecture foundation. Tanpa ini, CodeLens akan semakin tertinggal dari CodeGraph di reliability + performance. Mulai dari Issue #1 (single-tool MCP) karena itu adalah differentiator terbesar CodeGraph dan breaking change terbesar CodeLens — butuh waktu untuk migrate user.

**Quick win paralel:** Issue #10 (affected command), #11 (git sync hooks), #12 (upgrade command) — independen, bisa mulai paralel dengan P0. High UX impact, low effort.

Kalau mau saya buatkan GitHub issue dalam format `gh issue create --body-file ...` payload, atau pisah jadi 27 file markdown terpisah per issue, tinggal bilang.

---

*Dokumen ini dihasilkan dari analisa source code `Wolfvin/CodeLens` (commit `main` per 2026-06-28) dan `colbymchenry/codegraph` v1.1.2 (released 2026-06-28, 110 test file, 24 bahasa, 17 framework, 21 dynamic-dispatch synthesizer, 7 real-world benchmark). Semua reference path file merujuk ke struktur repo masing-masing saat tanggal analisa.*
