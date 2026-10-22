# NoteNest UI design system (Agent 2)

Presentation layer only (as of Agent 2). Agent 3 later added routes and schema for categories, archive and trash; see `AGENT3_HANDOFF.md`.

## Files
- `templates/base.html` — app shell: sidebar (desktop), top bar + bottom nav (<900px), flash messages, delete-confirm `<dialog>`.
- `templates/_icons.html` — `icon(name, size)` macro, inline SVG, `aria-hidden`.
- `templates/index.html`, `templates/edit.html` — notes overview/composer and editor.
- `static/style.css` — tokens (CSS custom properties), light + dark themes, components.
- `static/app.js` — optional enhancements: theme toggle, char counters, dismissible flashes, delete confirmation.

## Tokens
Colors, radius, shadows and fonts are `--*` variables on `:root`. Dark theme = `:root[data-theme="dark"]`
(explicit choice) or the OS preference when no explicit `data-theme="light"` is set. Theme choice is stored in
`localStorage["notenest-theme"]`.

## Contracts preserved
`index` (GET, `q`), `add` (POST `title`, `content`), `edit` (GET/POST, `title`, `content`),
`pin` (POST), `delete` (POST, now moves to Trash). Every POST form carries `csrf_token`. Template vars: `notes`, `query`, `note`, `title`, `content`.
Test-visible copy kept: "No notes yet", "No notes match".

## Navigation
Categories, Archive and Trash are real links (`categories_view`, `archive_view`, `trash_view`); the active
one gets `.is-active` and `aria-current="page"`. The `.is-soon` and `.badge` styles are no longer used.
Below 900px the bottom nav has five links (Notes, New, Categories, Archive, Trash); the theme toggle stays
in the top bar. Note cards live in `templates/_note_card.html` (`mode`: active / archived / trashed).

## Search, filters, tags and category management (Agent 5)
- `templates/_filters.html` is the shared GET form (search, tag, sort, pinned, plus a category select on Archive/Trash), the category chips (All notes only) and the removable active-filter chips with "Reset all filters". Include it with `filters`, `endpoint`, `categories`, `tags`, `sort_options` in context. `filter_url(endpoint, filters, key=value|None)` builds links that keep the other filters.
- Note cards take `return_to` so pin/archive/trash/edit return to the filtered list. Only `/`, `/archive` and `/trash` are accepted.
- Tags are `.chip.chip-static` inside `ul.tag-list`; the edit form uses `fieldset.tag-picker` with `.tag-option` checkboxes. Category/tag cards share `.category-card`; Rename uses a native `<details>`.
- Deleting a category or tag goes through `confirm_delete.html` (a GET page, then a POST), so it needs no JavaScript.

## Progressive enhancement
Without JS: forms submit normally, delete has no confirmation dialog, theme follows the OS, theme buttons stay hidden.
