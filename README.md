# Flask Notes App

A small full-stack web app for keeping notes. The backend is Flask with a SQLite database, and the pages are rendered with Jinja templates.

## Features
- Add, edit and pin notes
- Categories: Work, Business, Personal and Homework are built in; add your own and filter notes by category
- Archive: tuck notes out of All notes without deleting them, and unarchive any time
- Trash: deleting moves a note to Trash; restore it, or delete it permanently from there (nothing is deleted automatically)
- Media: attach images (PNG, JPEG, GIF, WebP) and audio (MP3, WAV, OGG, FLAC, M4A) to notes; browse everything in the Media Library (see `docs/MEDIA.md`)
- Category management: rename a category, or delete it after a confirmation page (its notes are kept and become uncategorized)
- Tags: label a note with several tags and filter by tag; create and delete tags on the Tags page (deleting a tag never deletes notes)
- Search, filter and sort: search title and content, combine with category, tag and pinned filters, and sort by pinned, recently updated, recently created or title. The same controls work in All notes, Archive and Trash, and active filters are shown (and kept after pin/archive/trash actions)
- Server-side validation (title required, length limits) with flash messages
- With the default "Pinned first" sort, pinned notes appear first
- Safe output: note text is HTML-escaped (no script injection)
- Automated tests with `pytest` and Flask's test client (`test_app.py`, `test_media.py`, `test_organization.py`)

## Setup
```
pip install -r requirements.txt
python app.py
```
Then open http://127.0.0.1:5000 in your browser.

For local development, `python app.py` runs with `APP_ENV=development` by
default and generates a random secret key for that process when `SECRET_KEY`
is not set. Set `SECRET_KEY` to a stable, randomly generated value when
running multiple workers or deploying the app; production mode requires it.
Set `APP_ENV=production` when deploying. `DATABASE` can be set to the desired
SQLite database file path; otherwise the app continues to use `notes.db` beside
`app.py`.

Uploaded media is stored on disk in `UPLOAD_FOLDER` (default `uploads/` beside `app.py`, gitignored); back it up together with `notes.db`.

`.env.example` documents the supported variables, but the app does not load
`.env` files automatically. Configure these variables in your shell or
deployment environment.

## Upgrading an existing database
Starting the app upgrades `notes.db` in place, automatically and safely: it only *adds* the
`categories`, `tags`, `note_tags`, `media` and `app_meta` tables and nullable note columns (`category_id`, `archived_at`, `trashed_at`, `updated_at`),
creates the `media` table, then seeds the default categories. Existing notes keep their ids, text, pin state and dates, and
repeated starts change nothing. Back up `notes.db` before upgrading if the notes matter to you.

## Run the tests
```
pytest
```

## Project structure
```
flask-notes-app/
├── app.py              # routes, database and validation
├── media.py            # upload validation, safe storage, cleanup helpers
├── templates/
│   ├── base.html
│   ├── _icons.html, _note_card.html, _media_card.html, _filters.html
│   ├── index.html, edit.html
│   ├── archive.html, trash.html, categories.html, tags.html, confirm_delete.html
│   └── media_library.html, media_view.html, note_media.html
├── static/
│   └── style.css
├── docs/               # UI design system, media, Agent 3 and Agent 5 handoffs
├── test_app.py         # automated tests
├── test_media.py       # media attachment tests
├── test_organization.py # search, filters, sorting, tags, category management
├── requirements.txt
├── .env.example
├── README.md
└── .gitignore
```

## Concepts used
Flask routing and application factory, Jinja2 templates and inheritance, HTML forms (GET and POST), the Post/Redirect/Get pattern, SQLite with parameterised queries, flash messages, error handling (404), testing with the Flask test client.

## Notes
Set `APP_ENV=production` and a strong `SECRET_KEY` before deploying anywhere
public. Production startup fails if no secret key is configured.
