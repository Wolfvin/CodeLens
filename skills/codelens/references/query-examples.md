# Query Examples

## codelens_query — Contoh Use Case

### Cek sebelum buat ID baru
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" query "modal-btn" /path/to/workspace --domain frontend
```
→ Cek apakah `#modal-btn` sudah ada di HTML/CSS/JS.

### Cek sebelum buat class baru
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" query "card-wrapper" /path/to/workspace --domain frontend
```

### Cek sebelum buat function baru di Rust/JS backend
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" query "verify_token" /path/to/workspace --domain backend
```
→ Return node + semua callers + semua callees.

### Cek function yang spesifik di file tertentu
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" query "hash_password" /path/to/workspace --domain backend --file "src/utils/"
```

### Auto-detect domain (cari di semua domain)
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" query "modal-btn" /path/to/workspace
```
→ Cari di frontend dulu, kalau tidak ketemu cari di backend.

---

## codelens_list — Contoh Use Case

### Audit semua dead code
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain frontend --filter dead
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain backend --filter dead
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain all --filter dead
```

### Cari semua ID collision (bug HTML)
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain frontend --filter collision
```

### Cari semua CSS yang duplicate define
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain frontend --filter duplicate_define
```

### Lihat semua referensi (full audit)
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain frontend --filter all
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain backend --filter all
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain all --filter all
```

### Cari semua duplicate reference
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain frontend --filter duplicate_ref
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
