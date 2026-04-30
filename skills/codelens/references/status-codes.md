# Status & Flag Reference Lengkap

## Node Status (level entry)

### `active`
- ref_count > 0
- Digunakan di setidaknya 1 tempat
- Aman untuk di-reference, hati-hati saat edit (cek callers/referrers dulu)

### `dead`
- ref_count = 0
- Tidak ada yang reference sama sekali
- Kandidat legacy code atau sisa refactor
- **AI action:** Flag ke user. Jangan extend. Tanya apakah mau dihapus atau di-reuse.

### `duplicate_ref`
- ref_count >= 2, dari file yang berbeda
- Dipakai di banyak tempat — bukan error, tapi perlu hati-hati
- **AI action:** Sebelum edit, list semua referrers ke user. Perubahan berdampak luas.

### `collision`
- Khusus HTML `id`
- ID yang sama ditemukan di lebih dari 1 elemen HTML
- Ini **bug aktif** — HTML spec melarang duplicate ID
- **AI action:** Hentikan task saat ini. Report collision ke user dulu. Jangan lanjut sebelum fix.

---

## Per-Referensi Flag (level path entry)

### `duplicate_define`
- CSS: selector yang sama di-define lebih dari 1x
- JS/Rust: function dengan nama sama dideklarasikan di lebih dari 1 file
- Yang terakhir akan override yang pertama (CSS cascade)
- **AI action:** Tunjukkan ke user semua lokasi define. Minta konfirmasi mana yang intended.

### `null`
- Tidak ada masalah pada referensi ini
- Normal, tidak perlu action

---

## ref_count Logic

```
ref_count = jumlah total referensi ke class/id/function ini
            dari CSS + JS (frontend)
            atau incoming edges (backend)

ref_count: 0 → dead
ref_count: 1 → active, single use
ref_count: 2+ → active, multiple use → cek apakah intentional atau duplicate_ref
```

---

## Prioritas Action untuk AI

1. `collision` → **STOP, fix dulu**
2. `duplicate_define` → **WARNING, tunjukkan ke user**
3. `dead` + user mau edit → **TANYA dulu: reuse atau hapus?**
4. `duplicate_ref` + user mau edit → **LIST semua caller dulu**
5. `active` → **Normal, lanjut**
6. `found: false` → **Aman, lanjut buat**
