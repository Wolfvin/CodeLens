# Status & Flag Reference — v2

## Node Status (level entry)

### `active`
- ref_count > 0
- Referenced in at least 1 location
- **AI action:** Normal, proceed. Exercise caution when editing (check callers first)

### `dead`
- ref_count = 0
- Not referenced anywhere
- Candidate for legacy code or leftover from refactoring
- **AI action:** Flag to user. Do not extend. Ask: reuse or delete?

### `duplicate_ref`
- Referenced from 2+ different files
- Used in many places — not an error, but proceed with caution
- **AI action:** Before editing, list all referrers to the user. Changes will have broad impact.

### `collision`
- Specific to HTML `id`
- Same ID found in >1 HTML element
- This is an **active bug** — the HTML spec forbids duplicate IDs
- **AI action:** Stop the current task. Report the collision to the user. Do not proceed until fixed.

---

## Per-Reference Flag (level path entry)

### `duplicate_define`
- CSS: selector defined >1x
- JS/Rust: function with the same name in >1 file
- The latter overrides the former (CSS cascade)
- **AI action:** Show the user all definition locations. Ask for confirmation on which is intended.

### `null`
- No issues
- Normal, no action needed

---

## Backend-specific Status

### Component flag (`component: true`)
- TSX/JSX: function whose name starts with an uppercase letter (React convention)
- Indicates this is a React component, not a utility function
- **AI action:** When editing a component, consider the impact on the render cycle

### `impl_for` / `trait_name`
- Rust: function within an impl block
- Indicates this function belongs to a specific struct/trait
- **AI action:** When editing, consider all callers that use this method via a struct instance

### `via_self: true`
- Edge that goes through a self.method() call
- Indicates an internal method call within an impl block
- **AI action:** Changing this method affects all methods within the same impl

---

## Frontend-specific Metadata

### `source` field
Indicates where this reference originates from:
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
ref_count = total references to this class/id/function
            from CSS + JS (frontend)
            or incoming edges (backend)

ref_count: 0 → dead
ref_count: 1 → active, single use
ref_count: 2+ → active, multiple use → check duplicate_ref
```

---

## Priority Action for AI

1. `collision` → **STOP, fix first**
2. `duplicate_define` → **WARNING, show to user**
3. `dead` + user wants to edit → **ASK first: reuse or delete?**
4. `duplicate_ref` + user wants to edit → **LIST all callers first**
5. `active` → **Normal, proceed**
6. `found: false` → **Safe, proceed to create**
