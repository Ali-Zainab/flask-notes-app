# Agent 3 handoff: categories, archive, trash

## What exists now
- **Categories**: `categories` table (name unique, case-insensitive for ASCII), defaults Work / Business / Personal / Homework seeded with `INSERT OR IGNORE`. Create via `/categories`; assign in the add/edit forms; filter with `/?category=<id>` (combines with `q`). Max name length 40. Unknown or non-numeric `category` -> 404.
- **Archive**: `archived_at` timestamp. Hidden from All notes and search; listed at `/archive`.
- **Trash**: `trashed_at` timestamp. `POST /delete/<id>` now **moves to Trash** (it used to hard-delete). Permanent deletion only via `/purge/<id>` (refuses notes not in Trash) and `/trash/empty`.
- **State rule**: Trash wins over Archive. Trashing an archived note keeps `archived_at`, so restoring it returns it to Archive. Archived notes never appear in Trash.

## Routes (all state-changing routes are POST + CSRF)
| Route | Methods | Endpoint |
|---|---|---|
| `/` (`q`, `category`) | GET | `index` |
| `/add`, `/pin/<id>`, `/delete/<id>` (-> Trash) | POST | `add`, `pin`, `delete` |
| `/edit/<id>` | GET, POST | `edit` (404 if trashed) |
| `/categories` | GET / POST | `categories_view` / `add_category` |
| `/archive` | GET | `archive_view` |
| `/archive/<id>`, `/unarchive/<id>` | POST | `archive_note`, `unarchive_note` |
| `/trash` | GET | `trash_view` |
| `/restore/<id>`, `/purge/<id>`, `/trash/empty` | POST | `restore_note`, `purge_note`, `empty_trash` |

POST forms may send a hidden `next` (`index`, `archive_view` or `trash_view`) to choose where to return; anything else is ignored.

## Migration (`init_db` in app.py)
One transaction, idempotent, runs on every start: ensure `notes`, create `categories`, `ALTER TABLE notes ADD COLUMN` for each missing column (`category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL`, `archived_at TEXT`, `trashed_at TEXT`), create two indexes, seed defaults. Existing rows are never rewritten. `PRAGMA foreign_keys = ON` is set on every app connection.

## Not done (by design)
- **No automatic trash expiry.** Notes stay in Trash until restored or purged; the Trash page says so. Adding expiry needs a retention setting, tests and user-facing messaging first.
- No category rename/delete UI (the FK safely nulls `category_id` if a category row is ever removed). No "Uncategorized" filter. Category uniqueness is ASCII case-insensitive only (SQLite NOCASE).
- Search covers All notes only. Redirects after an action return to the list, not the exact filtered view.
- Without JavaScript the permanent-delete buttons submit without the confirmation dialog (they only exist on the Trash page).
- Existing test `test_delete_note` was edited: `/delete` now flashes "Note moved to Trash."

## Next agent: do not
Change title/content limits, make `/delete` hard-delete again, or build media/AI on top without handling archived/trashed/purged notes.
