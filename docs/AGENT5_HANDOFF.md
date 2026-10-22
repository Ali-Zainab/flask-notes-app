# Agent 5A handoff: search, organization, tags, category management

Baseline: Agent 4 checkpoint `aa24730` (supplied as a zip). No new dependencies.

## Search, filter, sort (`/`, `/archive`, `/trash`)
- Query parameters: `q`, `category=<id>`, `tag=<id>`, `pinned=1`, `sort=`. Filters combine with **AND**. The three views share one parser and one SQL builder; the state (active / archived / trashed) is always part of the WHERE clause, so notes never leak between views.
- `q` matches title **or** content, case-insensitive for ASCII (SQLite LIKE). `%`, `_` and `\` are now matched literally (previously they acted as wildcards). Truncated to 200 characters.
- Sorts (every one ends with `notes.id` as tie-breaker): `pinned` = pinned, then newest id (default; All notes/Archive keep the "Pinned"/"Others" sections); `updated` = `COALESCE(updated_at, created_at)` desc; `created` = `created_at` desc; `title` = case-insensitive A-Z, ties by lower id. Trash defaults to `trashed` (recently trashed) and also offers the others. Any sort other than `pinned` is one flat list.
- An unknown or non-numeric `category`/`tag`, a `pinned` other than `0/1`, or a `sort` not valid for that view returns **404** (same rule the category filter already had).
- Active filters are shown as removable chips with "Reset all filters". Note cards carry a hidden `return_to`; pin/archive/unarchive/trash/restore/purge and Edit (save, Cancel, back link) return to the same filtered list. `return_to` is accepted only if it is a same-site path `/`, `/archive` or `/trash` (+ query); anything else is ignored.

## Schema (additive, one transaction, idempotent; `init_db`)
| Change | Detail |
|---|---|
| `notes.updated_at TEXT` (nullable) | Set only when title, content, category or tags genuinely change. Existing rows stay NULL and read as `created_at`. Pin/archive/trash/media never touch it. A no-op save says "No changes to save." |
| `tags(id, name NOCASE UNIQUE, created_at)` | Case-only duplicates impossible. |
| `note_tags(note_id, tag_id, PK(note_id, tag_id))` | FKs `ON DELETE CASCADE` both ways; index `idx_note_tags_tag(tag_id, note_id)`. Permanent note deletion / Empty Trash remove link rows; tags survive. |
| `app_meta(key, value)` | Marker `default_categories_seeded`. Defaults are now seeded **once**; before this a deleted/renamed default would have reappeared on every start. Existing databases already contain the four defaults, so nothing changes for them. |

## Tags
- Names: whitespace collapsed, leading `#` dropped, 1-30 printable characters, no commas. Max 10 per note. Duplicates (any case) are rejected on `/tags` and **reused** when typed in a note form.
- Assign on Add (comma-separated "Tags" field) and Edit (checkboxes + "Add new tags"). The edit form sends `tags_submitted=1`; a client that omits it leaves tags untouched. All validation happens before any write.
- Tags stay on archived and trashed notes (and come back with Restore). Deleting a tag removes only the links.

## Category management
- Rename keeps the id, so assignments are untouched; blank/overlong/duplicate (case-insensitive, other categories only) rejected.
- Delete = GET confirmation page (states how many notes, in any state, are kept) then POST. Notes become uncategorized; nothing else changes. Works without JavaScript.

## Routes added
| Route | Methods |
|---|---|
| `/tags` | GET (list), POST (create) |
| `/tags/<id>/delete` | GET (confirm page), POST (delete) |
| `/categories/<id>/rename` | POST |
| `/categories/<id>/delete` | GET (confirm page), POST (delete) |

Changed: `/`, `/archive`, `/trash` (filters/sort), `/add` (`new_tags`), `/edit/<id>` (tags, `return_to`, `updated_at`), and the POST routes that redirect back (`return_to`). All POSTs carry CSRF.

## Known limitations
- No tag rename; no multi-tag filter (one tag at a time); no pagination; search is plain LIKE (no ranking, ASCII case folding only); non-ASCII titles sort by code point.
- Tags cannot be set during the *media* upload flow; note creation takes tags as text only.
- The mobile bottom bar still has six items; Tags is reachable from the sidebar (desktop) and the "Manage tags" button on Categories.
- Layout was not verified in a real browser by the agent (see report).
- Do not: change note title/content limits, hard-delete in `/delete`, or re-seed default categories on every start.
