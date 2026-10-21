# Media attachments and Media Library (Agent 4)

## What it does
Images and audio can be attached to notes (Files button on a note card, or Attachments on the edit page).
The Media Library (`/media`) lists every attachment, filterable by type, each linking back to its note.

## Supported formats (checked by file contents, not by name or browser Content-Type)
| Kind | Formats | Per-file limit |
|---|---|---|
| Image | PNG, JPEG, GIF, WebP | 10 MiB (10 x 1024 x 1024 bytes) |
| Audio | MP3, WAV, OGG, FLAC, M4A | 25 MiB (25 x 1024 x 1024 bytes) |

SVG is deliberately **not** supported (it can carry scripts). The file extension must also agree with the detected
format (a JPEG named `x.png` is rejected). Empty files are rejected. A boundary-size file is accepted; one byte over is rejected.
Other limits: 10 files per upload, 20 attachments per note, 64 MiB per request (`MAX_CONTENT_LENGTH`).
Limits are enforced while streaming in 64 KiB chunks, so oversized files are aborted without being held in memory.

## Storage
- Binaries: `UPLOAD_FOLDER` (env var, default `uploads/` beside `app.py`; created on first upload; gitignored).
- Names: random `<32 hex>.<ext>`; the original filename is display-only metadata (directories and control characters stripped).
- Metadata: SQLite table `media` (`id, note_id, storage_key UNIQUE, original_name, kind, mime_type, size_bytes, created_at`),
  `note_id` -> `notes(id) ON DELETE CASCADE`. Additive and idempotent migration inside `init_db`'s transaction.
- Files are served only by id through `/media/<id>/file` (streamed, Range supported, verified MIME, `nosniff`,
  `Content-Security-Policy: sandbox`). Storage keys are re-validated and resolved inside the upload root on every access.

## Note states
| Note state | Attachments |
|---|---|
| Active / Archived | visible, uploadable, deletable |
| In Trash | hidden everywhere (library, viewer, file URLs, upload and delete all 404) but **kept on disk** |
| Restored | visible again, unchanged |
| Permanently deleted / Empty Trash | rows removed by cascade; files removed **after** the DB commit |

## Failure handling
Files are deleted only after the database commit, so a failure can leave an unreferenced file but never a row pointing
at a missing file. Failures are logged and flashed. Remove leftovers with:

    flask --app app cleanup-media

(deletes only well-formed `<32 hex>.<ext>` files in the upload root that no row references; other files are never touched).
A failed database insert during upload deletes the just-written file.

## Routes
| Route | Methods | Endpoint |
|---|---|---|
| `/media` (`?type=image\|audio`) | GET | `media_library` |
| `/media/<id>` | GET | `media_view` |
| `/media/<id>/file` | GET | `media_file` |
| `/media/<id>/delete` | POST | `delete_media` |
| `/notes/<id>/media` | GET | `note_media` |
| `/notes/<id>/media` | POST (multipart, field `files`) | `upload_media` |

## Known limits
Content is verified by signature only (no full decode), so a file can have a valid header and still be corrupt.
No thumbnails are generated (images are scaled by CSS). No quota across notes, no virus scanning, no pagination in the library.
Oversized requests redirect with a flash message rather than returning HTTP 413.
