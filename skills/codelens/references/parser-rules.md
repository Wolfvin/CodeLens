# Parser Rules per Bahasa — v2 (Tree-sitter Edition)

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
