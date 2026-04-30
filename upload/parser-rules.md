# Parser Rules per Bahasa

## HTML Parser

**Target:** Extract semua `id` dan `class` dari elemen HTML.

**Rules:**
- `id="xxx"` → daftarkan ke registry sebagai type `id`
- `class="a b c"` → split by space, daftarkan masing-masing sebagai type `class`
- Jika `id` yang sama ditemukan di lebih dari 1 elemen → flag `collision`
- Ignore: `id` dan `class` di dalam comment `<!-- -->`
- Ignore: template literals yang belum di-render (misal `id="{{ variable }}"`)

**Contoh:**
```html
<div id="sidebar-nav" class="container flex dark-mode">
```
Menghasilkan:
- id: `sidebar-nav`
- class: `container`, `flex`, `dark-mode`

---

## CSS Parser

**Target:** Semua selector yang referensikan class (`.xxx`) atau id (`#xxx`).

**Rules:**
- `.btn-primary { ... }` → referensi ke class `btn-primary`
- `#sidebar-nav { ... }` → referensi ke class `sidebar-nav`
- Selector compound: `.modal .btn-primary` → referensi ke KEDUANYA
- Jika selector yang sama muncul 2x di file berbeda → flag `duplicate_define`
- Jika selector yang sama muncul 2x di file yang SAMA → flag `duplicate_define` juga
- Ignore: selector di dalam comment `/* */`
- Ignore: selector di dalam `@keyframes`

**Pseudo-class diabaikan untuk matching:**
- `.btn-primary:hover` → match ke class `btn-primary`
- `#nav:focus` → match ke id `nav`

---

## JS Parser (Frontend)

**Target:** Semua referensi ke class atau id via DOM selector.

**Pattern yang dideteksi:**
```js
document.getElementById("sidebar-nav")
document.querySelector("#sidebar-nav")
document.querySelector(".btn-primary")
document.querySelectorAll(".btn-primary")
document.getElementsByClassName("btn-primary")
$(".btn-primary")           // jQuery
$("#sidebar-nav")           // jQuery
el.classList.add("active")  // DIABAIKAN — dynamic, bukan reference langsung
el.classList.toggle("open") // DIABAIKAN
```

**Rules:**
- Hanya string literal yang dicount — bukan variable (`querySelector(myVar)` diabaikan)
- Reference yang sama dari 2+ file → status node jadi `duplicate_ref`

---

## JS Parser (Backend)

**Target:** Function declarations dan calls, sama seperti Rust parser tapi untuk JS non-frontend.

**Pattern yang dideteksi:**
```js
// Declaration
function processData(input) { ... }
const processData = (input) => { ... }
const processData = function(input) { ... }

// Call
processData(myInput)
utils.processData(myInput)
```

**Rules:**
- Method calls di-track dengan format `object.method` sebagai satu node
- Arrow function yang di-assign ke const → diperlakukan sama seperti function declaration
- Callback inline (anonymous function) → DIABAIKAN, tidak punya nama

---

## Rust Parser

**Target:** Function declarations dan calls.

**Pattern yang dideteksi:**
```rust
// Declaration
fn verify_token(token: &str) -> Result<Claims> { ... }
pub fn hash_password(pw: &str) -> String { ... }
async fn fetch_data(url: &str) -> Response { ... }

// Call
verify_token(&token)?
hash_password(&input)
self.verify_token(&token)
```

**Rules:**
- `pub fn` dan `fn` keduanya di-track
- `async fn` di-track dengan flag `async: true`
- Method calls via `self.method()` → di-track sebagai edge ke struct yang sama
- Macro calls (`println!`, `vec!`) → DIABAIKAN
- Trait implementations → di-track, dengan note `impl_for: TypeName`

---

## Penentuan Frontend vs Backend untuk JS

Berdasarkan `codelens.config.json`:

```
frontend_paths check → cocok → JS Frontend Parser
      ↓ tidak cocok
backend_paths check  → cocok → JS Backend Parser
      ↓ tidak cocok
Default              → JS Backend Parser (safer assumption)
```

Jika file ada di `node_modules/` atau `dist/` → SELALU diabaikan.
