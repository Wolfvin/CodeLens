# Query Examples — v2

## codelens_query

### Cek sebelum buat ID baru
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" query "modal-btn" /path/to/workspace --domain frontend
```

### Cek sebelum buat className baru (React/TSX)
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" query "card-wrapper" /path/to/workspace --domain frontend
```

### Cek sebelum buat function baru di Rust
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" query "verify_token" /path/to/workspace --domain backend
```

### Auto-detect domain
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" query "processData" /path/to/workspace
```

### Filter berdasarkan file
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" query "hash_password" /path/to/workspace --domain backend --file "src/utils/"
```

---

## codelens_list

### Audit semua dead code
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain all --filter dead
```

### Cari ID collision
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain frontend --filter collision
```

### Cari duplicate CSS define
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain frontend --filter duplicate_define
```

### Cari semua yang reference dari banyak tempat
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain frontend --filter duplicate_ref
```

### Full audit
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain all --filter all
```

---

## codelens_scan

### Full scan
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" scan /path/to/workspace
```

### Incremental scan (hanya file yang berubah)
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" scan /path/to/workspace --incremental
```

---

## codelens_init

### Initialize dengan auto-detect frameworks
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" init /path/to/workspace
```

---

## codelens_detect

### Detect frameworks saja
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" detect /path/to/workspace
```

---

## Interpretasi Output untuk AI

### `found: true` + `status: "active"`
→ Sudah ada dan aktif. **JANGAN buat ulang.**
→ Baca `js` array untuk tahu logic yang sudah ada.
→ Extend atau diskusi dengan user.

### `found: true` + `status: "dead"`
→ Ada tapi tidak dipakai. Dua pilihan:
  1. Reuse — extend yang sudah ada
  2. Hapus dulu — lalu buat baru
→ Tanya user.

### `found: true` + `status: "duplicate_ref"`
→ Dipanggil dari banyak tempat. Perubahan berdampak luas.
→ List semua referrers ke user sebelum edit.

### `found: true` + `status: "collision"`
→ BUG AKTIF — ID muncul di >1 HTML elemen.
→ Hentikan. Report ke user. Fix dulu.

### `found: true` + `duplicate_define: true` (backend)
→ Function dengan nama sama di >1 file.
→ Tunjukkan semua lokasi ke user.

### `found: false`
→ Aman. Nama belum dipakai.
→ Lanjut buat.
