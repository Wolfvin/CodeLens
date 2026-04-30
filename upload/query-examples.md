# Query Examples

## codelens_query — Contoh Use Case

### Cek sebelum buat ID baru
```json
{ "query": "modal-btn", "domain": "frontend" }
```
→ Cek apakah `#modal-btn` sudah ada di HTML/CSS/JS.

### Cek sebelum buat class baru
```json
{ "query": "card-wrapper", "domain": "frontend" }
```

### Cek sebelum buat function baru di Rust/JS backend
```json
{ "query": "verify_token", "domain": "backend" }
```
→ Return node + semua callers + semua callees.

### Cek function yang spesifik di file tertentu
```json
{ "query": "hash_password", "domain": "backend", "file": "src/utils/hash.rs" }
```

---

## codelens_list — Contoh Use Case

### Audit semua dead code
```json
{ "domain": "frontend", "filter": "dead" }
{ "domain": "backend",  "filter": "dead" }
```

### Cari semua ID collision (bug HTML)
```json
{ "domain": "frontend", "filter": "collision" }
```

### Cari semua CSS yang duplicate define
```json
{ "domain": "frontend", "filter": "duplicate_define" }
```

### Lihat semua referensi (full audit)
```json
{ "domain": "frontend", "filter": "all" }
{ "domain": "backend",  "filter": "all" }
```

---

## Interpretasi Output untuk AI

### Ketika `found: true` dan `status: "active"`
→ Sudah ada dan aktif dipakai. **JANGAN buat ulang.**
→ Baca `js` array untuk tahu logic apa yang sudah ada.
→ Extend atau diskusi dengan user.

### Ketika `found: true` dan `status: "dead"`
→ Ada tapi tidak dipakai. Dua pilihan:
  1. Reuse — extend yang sudah ada
  2. Hapus dulu — lalu buat baru yang bersih
→ Tanya user mana yang diinginkan.

### Ketika `found: true` dan `status: "duplicate_ref"`
→ Dipanggil dari banyak tempat. Hati-hati saat mengubah — perubahan akan berdampak ke semua caller.
→ List semua caller ke user sebelum edit.

### Ketika `found: true` dan `status: "collision"`
→ Bug aktif — ID muncul di lebih dari 1 elemen HTML.
→ Flag ke user segera, jangan lanjut tanpa fix ini dulu.

### Ketika `found: false`
→ Aman. Nama belum dipakai di mana pun.
→ Lanjut buat.
