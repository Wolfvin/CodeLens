# Parser Rules per Bahasa — v3 (Tree-sitter + Regex Fallback Edition)

CodeLens menggunakan dua lapisan parser:

1. **Tree-sitter parsers** (AST-level, akurat) — untuk 9 bahasa utama: HTML, CSS, JS, TS/TSX, Rust, Python, Vue SFC, Svelte, Blade. Lihat `scripts/parsers/*.py` (kecuali `fallback_*.py`).
2. **Regex fallback parsers** (line-based, lebih longgar) — untuk 28+ bahasa lain. Lihat `scripts/parsers/fallback_*.py`. Auto-aktif ketika tree-sitter grammar tidak tersedia atau untuk bahasa yang belum punya tree-sitter parser.

Tree-sitter lebih akurat (scope-aware, comment-aware, multi-line aware). Fallback regex lebih cepat tapi rentan false positive pada konstruksi kompleks (generics, macros, string-embedded code).

---

## HTML Parser (tree-sitter-html)

**Target:** Extract `id` dan `class` dari elemen HTML.

**Rules:**
- `id="xxx"` → daftarkan ke registry sebagai type `id`
- `class="a b c"` → split by space, daftarkan masing-masing
- ID collision: `id` yang sama di >1 elemen → flag `collision`
- Comments `<!-- -->` otomatis di-skip oleh tree-sitter
- Template literals `id="{{ variable }}"` difilter
- Void elements, self-closing tags: handled correctly

---

## CSS Parser (tree-sitter-css)

**Target:** Semua selector yang referensikan class (`.xxx`) atau id (`#xxx`).

**Rules:**
- `.btn-primary { ... }` → referensi ke class `btn-primary`
- `#sidebar-nav { ... }` → referensi ke id `sidebar-nav`
- Compound selectors: `.modal .btn-primary` → KEDUANYA
- duplicate_define: selector sama muncul 2+ kali (file sama atau beda)
- @keyframes: otomatis di-skip
- Comments: otomatis di-skip oleh tree-sitter
- Pseudo-class: `.btn-primary:hover` → match ke `btn-primary`
- SCSS/Less: fallback regex untuk preprocessor syntax

---

## JS Frontend Parser (tree-sitter-javascript)

**Target:** Semua referensi ke class/id via DOM selector.

**Pattern yang dideteksi:**
```js
document.getElementById("sidebar-nav")
document.querySelector("#sidebar-nav")
document.querySelector(".btn-primary")
document.querySelectorAll(".btn-primary")
document.getElementsByClassName("btn-primary")
$(".btn-primary")           // jQuery
$("#sidebar-nav")           // jQuery
el.classList.add("active")  // DIABAIKAN — dynamic
```

**Rules:**
- Hanya string literal yang dicount
- Variable refs (`querySelector(myVar)`) diabaikan
- Template literals diabaikan
- Reference dari 2+ file → `duplicate_ref`

---

## JS Backend Parser (tree-sitter-javascript)

**Target:** Function declarations dan calls.

**Pattern yang dideteksi:**
```js
// Declaration
function processData(input) { ... }
const processData = (input) => { ... }
const processData = function(input) { ... }
async function fetchData() { ... }

// Call
processData(myInput)
obj.processData(myInput)
```

**Rules:**
- Arrow function → sama seperti function declaration
- Anonymous callbacks → DIABAIKAN
- Built-in keywords → DIABAIKAN
- Method calls tracked sebagai `method_name`

---

## TSX/JSX Parser (tree-sitter-typescript)

**Target:** className, id, dan function declarations di React/TSX files.

**Pattern yang dideteksi:**
```tsx
// className variants
<div className="modal active">
<div className={`modal ${isOpen ? 'active' : ''}`}>
<div className={"btn-primary"}>
<div className={condition ? "a" : "b"}>

// id
<div id="modal-root">

// Function components
const Modal = ({ isOpen }: Props) => { ... }
function Modal() { ... }
```

**Rules:**
- className: extract dari string, template literal, dan ternary expressions
- Dynamic className (`className={variable}`): hanya track literal strings
- React component: nama diawali huruf besar → flag `component: true`
- Handles export default, named exports

---

## Rust Parser (tree-sitter-rust)

**Target:** Function declarations dan calls.

**Pattern yang dideteksi:**
```rust
fn verify_token(token: &str) -> Result<Claims> { ... }
pub fn hash_password(pw: &str) -> String { ... }
async fn fetch_data(url: &str) -> Response { ... }

// Calls
verify_token(&token)?
hash_password(&input)
self.verify_token(&token)
HttpClient::new()
```

**Rules:**
- `pub fn` dan `fn` keduanya di-track
- `async fn` → flag `async: true`
- `self.method()` → tracked dengan `via_self: true`
- Macro calls (`println!`, `vec!`) → DIABAIKAN
- `impl TypeName { fn method() }` → tracked dengan `impl_for`
- `impl Trait for Type` → tracked dengan `trait_name`
- Scoped calls: `Module::function()` → tracked

---

## Vue SFC Parser

**Target:** Class/id dari template, style, dan script Vue SFC.

**Pattern yang dideteksi:**
```vue
<template>
  <div class="container" :class="{'active': isOpen}" id="app">
    <span :class="['bold', isActive ? 'visible' : 'hidden']">
  </div>
</template>

<style scoped>
.container { ... }
.active { ... }
</style>
```

**Rules:**
- Static `class="xxx"` → tracked
- Dynamic `:class="xxx"` → extract literal strings dari binding
- `:class="['a', condition ? 'b' : 'c']"` → track "a", "b", "c"
- `:class="{'active': condition}"` → track "active"
- `:class="classes.wrapper"` → track "wrapper" as dynamic ref
- Scoped styles: otomatis detected
- SCSS/Less in `<style lang="scss">`: supported via fallback

---

## Svelte Parser

**Target:** Class/id dari markup dan scoped styles.

**Pattern yang dideteksi:**
```svelte
<button class="btn-primary" class:active={isActive} id="submit-btn">

<style>
  .btn-primary { ... }
  :global(.external-class) { ... }
</style>
```

**Rules:**
- `class="xxx"` → tracked
- `class:active={condition}` → track "active" as class directive
- `:global(.xxx)` modifier → tracked as global
- Scoped styles: default in Svelte
- Script section: DOM selector references tracked

---

## Tailwind CSS Detector

**Target:** Utility class detection dan analysis.

**Rules:**
- Pattern matching against Tailwind utility prefixes
- Responsive prefixes: `sm:`, `md:`, `lg:`, `xl:`, `2xl:`
- State prefixes: `hover:`, `focus:`, `dark:`, `group-hover:`
- Custom prefix from `tailwind.config.js`
- Dynamic patterns: `text-${color}-500` → flagged as dynamic
- `@apply` custom utilities tracked
- Custom config (prefix, content paths, darkMode) parsed

---

## Penentuan Frontend vs Backend

Berdasarkan `codelens.config.json` (auto-detected):

```
frontend_paths check → cocok → JS/TS Frontend Parser
      ↓ tidak cocok
backend_paths check  → cocok → JS Backend Parser
      ↓ tidak cocok
Default              → JS Backend Parser (safer assumption)
```

**Special cases:**
- `.tsx` / `.jsx` files → selalu pakai TSX Parser (handles both frontend + backend)
- `.vue` files → selalu pakai Vue SFC Parser
- `.svelte` files → selalu pakai Svelte Parser
- `.ts` in frontend paths → TSX Parser
- `.ts` in backend paths → JS Backend Parser

---

## Fallback Regex Parsers (28+ Bahasa)

Untuk bahasa di luar 9 tree-sitter utama, CodeLens punya regex-based fallback parser di `scripts/parsers/fallback_<lang>.py`. Parser ini menangani function declarations, struct/class definitions, dan call edges — cukup untuk call graph & dead-code analysis dasar.

### Bahasa yang Didukung via Fallback

| Bahasa | File Extension | Parser File | Catatan |
|--------|----------------|-------------|---------|
| C | `.c`, `.h` | `fallback_c.py` | Functions, macros, typedefs, call edges |
| C++ | `.cpp`, `.hpp`, `.cc`, `.cxx`, `.hxx` | `fallback_cpp.py` | Classes, methods, namespaces |
| C# | `.cs` | `fallback_csharp.py` | Classes, methods, properties |
| CSS | (fallback when tree-sitter unavailable) | `fallback_css.py` | Same rules as tree-sitter CSS parser |
| Dart | `.dart` | `fallback_dart.py`, `fallback_dart_extra.py` | Classes, methods, async functions |
| Elixir | `.ex`, `.exs` | `fallback_elixir.py` | Module functions, pattern-matched defs |
| GDScript | `.gd` | `fallback_gdscript.py` | Godot script functions |
| Go | `.go` | `fallback_go.py` | Functions, methods, types |
| Haskell | `.hs` | `fallback_haskell.py` | Function defs, type sigs |
| HTML | (fallback) | `fallback_html.py` | id/class extraction |
| Java | `.java` | `fallback_java.py` | Classes, methods |
| JavaScript (backend) | (fallback) | `fallback_js_backend.py` | Functions, calls |
| JavaScript (frontend) | (fallback) | `fallback_js_frontend.py` | DOM selectors |
| Kotlin | `.kt`, `.kts` | `fallback_kotlin.py` | Functions, classes |
| Lua | `.lua` | `fallback_lua.py` | Functions, locals |
| Nim | `.nim` | `fallback_nim.py` | Procedures, macros |
| Objective-C | `.m`, `.mm` | `fallback_objc.py` | Methods, classes |
| PHP | `.php` | `fallback_php.py` | Functions, classes |
| Python | (fallback) | `fallback_python.py` | Functions, classes, decorators |
| R | `.r`, `.R` | `fallback_r.py` | Functions |
| Ruby | `.rb` | `fallback_ruby.py` | Methods, blocks |
| Rust | (fallback) | `fallback_rust.py` | Functions, impls |
| Scala | `.scala` | `fallback_scala.py` | Classes, methods, objects |
| Shell/Bash | `.sh`, `.bash` | `fallback_shell.py` | Functions |
| Swift | `.swift` | `fallback_swift.py` | Functions, classes |
| Vim | `.vim` | `fallback_vim.py` | Functions, commands |
| Zig | `.zig` | `fallback_zig.py` | Functions |

### Aturan Umum Fallback

- **Comment-aware**: `//`, `#`, `/* */`, `--`, `;;` di-skip sesuai sintaks bahasa
- **String-aware**: literals `'...'`, `"..."`, `` `...` `` di-skip agar tidak ada false positive
- **Brace-depth**: class/struct body di-track via brace matching (untuk C++/Java/C#/Swift)
- **Storage-class skip**: keywords seperti `void`, `const`, `unsigned`, `static`, `inline` di-skip agar tidak dikelirukan dengan function name (bug yang ditemukan saat testing redis/redis)
- **Macro skip**: macros seperti `println!`, `vec!` (Rust) atau `#define` (C) diabaikan dari call graph

### Keterbatasan Fallback

Tidak seperti tree-sitter, fallback parser:
- **Tidak scope-aware** — tidak bisa bedain variabel lokal vs global dengan nama sama
- **Tidak type-aware** — tidak bisa parse generic parameters `<T>` dengan akurat
- **Tidak multi-line aware untuk arrow functions** dalam parentheses (bug yang pernah ditemukan di JS backend)
- **Tidak template-literal aware** — `${variable}` di string bisa dikelirukan dengan code

Untuk analisis kritis (taint analysis, security audit), jalankan `setup.sh` untuk install tree-sitter grammars dan dapatkan akurasi penuh.

---

## Bahasa yang Tidak Didukung

Bahasa berikut tidak punya tree-sitter atau fallback parser sama sekali:

OCaml, Perl, Clojure, F#, Erlang, Fortran, Lisp, Prolog.

(Check `scripts/parsers/` untuk status terkini — daftar ini bisa berubah saat fallback parser baru ditambahkan.)

Saat file bahasa ini discan, CodeLens menghitung jumlah file tapi tidak menghasilkan nodes/edges. Output scan akan menampilkan `"unsupported_langs": ["ocaml", "perl"]` di field `frameworks`.
