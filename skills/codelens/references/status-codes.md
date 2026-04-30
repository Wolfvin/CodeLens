# Status & Flag Reference — v2

## Node Status (level entry)

### `active`
- ref_count > 0
- Digunakan di setidaknya 1 tempat
- **AI action:** Normal, lanjut. Hati-hati saat edit (cek callers dulu)

### `dead`
- ref_count = 0
- Tidak ada yang reference
- Kandidat legacy code atau sisa refactor
- **AI action:** Flag ke user. Jangan extend. Tanya: reuse atau hapus?

### `duplicate_ref`
- Referenced dari 2+ file yang berbeda
- Dipakai di banyak tempat — bukan error, tapi hati-hati
- **AI action:** Sebelum edit, list semua referrers ke user. Perubahan berdampak luas.

### `collision`
- Khusus HTML `id`
- ID yang sama ditemukan di >1 elemen HTML
- Ini **bug aktif** — HTML spec melarang duplicate ID
- **AI action:** Hentikan task saat ini. Report collision ke user. Jangan lanjut sebelum fix.

---

## Per-Referensi Flag (level path entry)

### `duplicate_define`
- CSS: selector di-define >1x
- JS/Rust: function dengan nama sama di >1 file
- Yang terakhir override yang pertama (CSS cascade)
- **AI action:** Tunjukkan ke user semua lokasi define. Minta konfirmasi mana yang intended.

### `null`
- Tidak ada masalah
- Normal, tidak perlu action

---

## Backend-specific Status

### Component flag (`component: true`)
- TSX/JSX: function yang namanya diawali huruf besar (React convention)
- Menandakan ini adalah React component, bukan utility function
- **AI action:** Saat edit component, pertimbangkan impact ke render cycle

### `impl_for` / `trait_name`
- Rust: function dalam impl block
- Menandakan function ini milik struct/trait tertentu
- **AI action:** Saat edit, pertimbangkan semua caller yang pakai method ini via struct instance

### `via_self: true`
- Edge yang melalui self.method() call
- Menandakan internal method call dalam impl block
- **AI action:** Perubahan method ini mempengaruhi semua method dalam impl yang sama

---

## Frontend-specific Metadata

### `source` field
Menandakan dari mana reference ini berasal:
- `vue_class` — static Vue template class
- `vue_binding` — dynamic :class binding
- `vue_scoped_style` — Vue scoped CSS
- `svelte_class` — static Svelte class
- `svelte_directive` — Svelte class: directive
- `svelte_scoped_style` — Svelte scoped CSS
- `jsx_classname` — React className
- `jsx_template` — template literal in className
- `tailwind_utility` — Tailwind CSS class
- `tailwind_dynamic` — dynamic Tailwind class pattern

---

## ref_count Logic

```
ref_count = total referensi ke class/id/function ini
            dari CSS + JS (frontend)
            atau incoming edges (backend)

ref_count: 0 → dead
ref_count: 1 → active, single use
ref_count: 2+ → active, multiple use → cek duplicate_ref
```

---

## Prioritas Action untuk AI

1. `collision` → **STOP, fix dulu**
2. `duplicate_define` → **WARNING, tunjukkan ke user**
3. `dead` + user mau edit → **TANYA dulu: reuse atau hapus?**
4. `duplicate_ref` + user mau edit → **LIST semua caller dulu**
5. `active` → **Normal, lanjut**
6. `found: false` → **Aman, lanjut buat**
