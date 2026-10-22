"""Flask Notes App: notes with categories, tags, archive, trash and media (SQLite storage)."""

import os
import secrets
import sqlite3
from urllib.parse import urlsplit

import click
from flask import (
    Flask, abort, flash, g, redirect, render_template, request, send_file, url_for,
)
from flask_wtf.csrf import CSRFProtect

import media

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    content    TEXT NOT NULL DEFAULT '',
    pinned     INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# Additive migration (see init_db). The original notes table above is never altered
# except by appending the nullable columns below, so existing rows are preserved as-is.
CATEGORIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL COLLATE NOCASE UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

NOTE_COLUMNS = (
    ("category_id", "INTEGER REFERENCES categories(id) ON DELETE SET NULL"),
    ("archived_at", "TEXT"),
    ("trashed_at", "TEXT"),
    # Agent 5: set only when a note's title, content, category or tags genuinely change.
    # Existing rows stay NULL and are read as COALESCE(updated_at, created_at).
    ("updated_at", "TEXT"),
)

NOTE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_notes_category ON notes (category_id)",
    "CREATE INDEX IF NOT EXISTS idx_notes_state ON notes (trashed_at, archived_at)",
)

DEFAULT_CATEGORIES = ("Work", "Business", "Personal", "Homework")

# Tags (Agent 5): many-to-many with notes. Names are unique case-insensitively (COLLATE NOCASE).
# Deleting a tag or a note removes only the link rows (ON DELETE CASCADE), never the other side.
TAGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tags (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL COLLATE NOCASE UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""
NOTE_TAGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS note_tags (
    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (note_id, tag_id)
);
"""
TAG_INDEXES = ("CREATE INDEX IF NOT EXISTS idx_note_tags_tag ON note_tags (tag_id, note_id)",)

# Tiny key/value table. Used so the default categories are seeded exactly once; without it a
# renamed or deleted default (Agent 5 category management) would be re-created on every start.
META_SCHEMA = "CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"

# Media attachments (Agent 4). Only metadata lives here; binaries are files in UPLOAD_FOLDER.
# ON DELETE CASCADE removes rows when a note is permanently deleted; the files are removed
# by the app after that commit (see release_files in create_app).
MEDIA_SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id       INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    storage_key   TEXT NOT NULL UNIQUE,
    original_name TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('image', 'audio')),
    mime_type     TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL CHECK (size_bytes > 0),
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""
MEDIA_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_media_note ON media (note_id)",
    "CREATE INDEX IF NOT EXISTS idx_media_kind ON media (kind, id)",
)
MAX_FILES_PER_UPLOAD = 10
MAX_ATTACHMENTS_PER_NOTE = 20
MAX_REQUEST_BYTES = 64 * media.MIB

MAX_TITLE = 100
MAX_CONTENT = 2000
MAX_CATEGORY_NAME = 40
MAX_TAG_NAME = 30
MAX_TAGS_PER_NOTE = 10
MAX_QUERY = 200

# A note is in exactly one list. Trash wins over archive: a note that was archived and
# then trashed keeps archived_at, so restoring it from Trash returns it to the Archive.
# These fragments are constants, never built from user input.
STATE_FILTERS = {
    "active": "notes.archived_at IS NULL AND notes.trashed_at IS NULL",
    "archived": "notes.archived_at IS NOT NULL AND notes.trashed_at IS NULL",
    "trashed": "notes.trashed_at IS NOT NULL",
}

# Sorting. Every order ends in notes.id so ties are always broken the same way.
# NOCASE only folds ASCII letters; other scripts sort by code point.
SORT_SQL = {
    "pinned": "notes.pinned DESC, notes.id DESC",
    "updated": "COALESCE(notes.updated_at, notes.created_at) DESC, notes.id DESC",
    "created": "notes.created_at DESC, notes.id DESC",
    "title": "notes.title COLLATE NOCASE ASC, notes.id ASC",
    "trashed": "notes.trashed_at DESC, notes.id DESC",
}
SORT_LABELS = {
    "pinned": "Pinned first",
    "updated": "Recently updated",
    "created": "Recently created",
    "title": "Title (A\u2013Z)",
    "trashed": "Recently trashed",
}
STATE_SORTS = {
    "active": ("pinned", "updated", "created", "title"),
    "archived": ("pinned", "updated", "created", "title"),
    "trashed": ("trashed", "updated", "created", "title", "pinned"),
}
DEFAULT_SORT = {"active": "pinned", "archived": "pinned", "trashed": "trashed"}

# Endpoints a POST form may ask to be redirected back to (via a hidden "next" field).
# Anything else falls back to the route's default, so this can never be an open redirect.
NEXT_TARGETS = {"index", "archive_view", "trash_view"}
# Pages a POST may return to (with their filter query string) via a hidden "return_to" field.
RETURN_PATHS = {"/": "index", "/archive": "archive_view", "/trash": "trash_view"}


def validate_note(title, content):
    """Return an error message, or None if the input is fine."""
    if not title:
        return "Title is required."
    if len(title) > MAX_TITLE:
        return f"Title must be {MAX_TITLE} characters or fewer."
    if len(content) > MAX_CONTENT:
        return f"Content must be {MAX_CONTENT} characters or fewer."
    return None


def validate_category_name(name):
    """Return an error message, or None. `name` must already be whitespace-normalised."""
    if not name:
        return "Category name is required."
    if len(name) > MAX_CATEGORY_NAME:
        return f"Category name must be {MAX_CATEGORY_NAME} characters or fewer."
    if not name.isprintable():
        return "Category name contains invalid characters."
    return None


def normalize_tag(raw):
    """Collapse whitespace and drop leading '#' (people type #idea). Case is kept for display."""
    return " ".join((raw or "").split()).lstrip("#").strip()


def validate_tag_name(name):
    if not name:
        return "Tag name is required."
    if len(name) > MAX_TAG_NAME:
        return f"Tag name must be {MAX_TAG_NAME} characters or fewer."
    if not name.isprintable() or "," in name:
        return "Tag name contains invalid characters."
    return None


def like_pattern(text):
    """Escape LIKE wildcards so searching for 50% or a_b matches those characters literally."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def init_db(path):
    """Create or upgrade the database at `path`. Safe to run repeatedly.

    Fresh and pre-existing databases take the same path: ensure the original notes table,
    add any missing columns/indexes, then seed default categories with INSERT OR IGNORE.
    Runs in one transaction, so a failure leaves the database as it was.
    """
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN")
        try:
            conn.execute(SCHEMA)
            conn.execute(CATEGORIES_SCHEMA)
            existing = {row[1] for row in conn.execute("PRAGMA table_info(notes)")}
            for column, definition in NOTE_COLUMNS:
                if column not in existing:
                    conn.execute(f"ALTER TABLE notes ADD COLUMN {column} {definition}")
            for statement in NOTE_INDEXES:
                conn.execute(statement)
            conn.execute(MEDIA_SCHEMA)
            for statement in MEDIA_INDEXES:
                conn.execute(statement)
            conn.execute(TAGS_SCHEMA)
            conn.execute(NOTE_TAGS_SCHEMA)
            for statement in TAG_INDEXES:
                conn.execute(statement)
            conn.execute(META_SCHEMA)
            # Seed the defaults once. Databases from earlier versions already contain them, so
            # the first run here just records the marker; later renames/deletions are respected.
            seeded = conn.execute("SELECT 1 FROM app_meta WHERE key = 'default_categories_seeded'").fetchone()
            if not seeded:
                conn.executemany(
                    "INSERT OR IGNORE INTO categories (name) VALUES (?)",
                    [(name,) for name in DEFAULT_CATEGORIES],
                )
                conn.execute("INSERT INTO app_meta (key, value) VALUES ('default_categories_seeded', '1')")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        APP_ENV=os.environ.get("APP_ENV", "production").strip().lower(),
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        DATABASE=os.environ.get("DATABASE", os.path.join(app.root_path, "notes.db")),
        UPLOAD_FOLDER=os.environ.get("UPLOAD_FOLDER", os.path.join(app.root_path, "uploads")),
        MAX_CONTENT_LENGTH=MAX_REQUEST_BYTES,
        MAX_IMAGE_BYTES=media.MAX_IMAGE_BYTES,
        MAX_AUDIO_BYTES=media.MAX_AUDIO_BYTES,
    )
    if test_config:
        app.config.update(test_config)
    app.config["APP_ENV"] = str(app.config["APP_ENV"]).strip().lower()
    if not app.config["SECRET_KEY"]:
        if app.config["TESTING"] or app.config["APP_ENV"] == "development":
            app.config["SECRET_KEY"] = secrets.token_hex(32)
        else:
            raise RuntimeError(
                "SECRET_KEY must be set unless APP_ENV is development or testing."
            )

    CSRFProtect(app)

    # ---- database helpers ----
    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
        return g.db

    @app.teardown_appcontext
    def close_db(_error):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    init_db(app.config["DATABASE"])

    def get_note_or_404(note_id, trashed=None):
        """Fetch a note. trashed=False -> 404 if in Trash; trashed=True -> 404 if not in Trash."""
        note = get_db().execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if note is None:
            abort(404)
        if trashed is True and note["trashed_at"] is None:
            abort(404)
        if trashed is False and note["trashed_at"] is not None:
            abort(404)
        return note

    def get_categories():
        return get_db().execute("SELECT id, name FROM categories ORDER BY id").fetchall()

    def parse_category_id(raw):
        """Return (category_id_or_None, error). Empty means 'no category'."""
        raw = (raw or "").strip()
        if not raw:
            return None, None
        if raw.isascii() and raw.isdigit():
            row = get_db().execute("SELECT id FROM categories WHERE id = ?", (int(raw),)).fetchone()
            if row is not None:
                return row["id"], None
        return None, "Choose a valid category."

    def get_tags():
        return get_db().execute("SELECT id, name FROM tags ORDER BY name COLLATE NOCASE, id").fetchall()

    def lookup_id(table, raw):
        """Return the (id, name) row for a validated numeric id, else None. `table` is a constant."""
        raw = (raw or "").strip()
        if not (raw.isascii() and raw.isdigit()):
            return None
        return get_db().execute(f"SELECT id, name FROM {table} WHERE id = ?", (int(raw),)).fetchone()

    def parse_filters(state):
        """Read q / category / tag / pinned / sort from the query string. Unknown ids or values
        are a 404 (consistent with the existing category filter) rather than silently ignored."""
        args = request.args
        filters = {
            "q": args.get("q", "").strip()[:MAX_QUERY],
            "category": None, "tag": None, "pinned": False,
            "sort": DEFAULT_SORT[state], "default_sort": DEFAULT_SORT[state],
        }
        for key, table in (("category", "categories"), ("tag", "tags")):
            raw = args.get(key, "").strip()
            if raw:
                filters[key] = lookup_id(table, raw)
                if filters[key] is None:
                    abort(404)
        pinned = args.get("pinned", "").strip()
        if pinned not in ("", "0", "1"):
            abort(404)
        filters["pinned"] = pinned == "1"
        sort = args.get("sort", "").strip()
        if sort:
            if sort not in STATE_SORTS[state]:
                abort(404)
            filters["sort"] = sort
        return filters

    def filter_url(endpoint, filters, **changes):
        """URL for `endpoint` carrying the current filters; pass key=None to drop one."""
        params = {}
        if filters["q"]:
            params["q"] = filters["q"]
        if filters["category"]:
            params["category"] = filters["category"]["id"]
        if filters["tag"]:
            params["tag"] = filters["tag"]["id"]
        if filters["pinned"]:
            params["pinned"] = "1"
        if filters["sort"] != filters["default_sort"]:
            params["sort"] = filters["sort"]
        for key, value in changes.items():
            if value is None:
                params.pop(key, None)
            else:
                params[key] = value
        return url_for(endpoint, **params)

    app.jinja_env.globals["filter_url"] = filter_url

    def list_notes(state, filters=None):
        """Notes in one state (active / archived / trashed), narrowed by AND-combined filters."""
        filters = filters or {"q": "", "category": None, "tag": None, "pinned": False, "sort": DEFAULT_SORT[state]}
        sql = (
            "SELECT notes.*, categories.name AS category_name, "
            "(SELECT COUNT(*) FROM media WHERE media.note_id = notes.id) AS media_count FROM notes "
            "LEFT JOIN categories ON categories.id = notes.category_id "
            "WHERE " + STATE_FILTERS[state]
        )
        params = []
        if filters["q"]:
            sql += " AND (notes.title LIKE ? ESCAPE '\\' OR notes.content LIKE ? ESCAPE '\\')"
            params += [like_pattern(filters["q"])] * 2
        if filters["category"]:
            sql += " AND notes.category_id = ?"
            params.append(filters["category"]["id"])
        if filters["tag"]:
            sql += " AND EXISTS (SELECT 1 FROM note_tags WHERE note_tags.note_id = notes.id AND note_tags.tag_id = ?)"
            params.append(filters["tag"]["id"])
        if filters["pinned"]:
            sql += " AND notes.pinned = 1"
        sql += " ORDER BY " + SORT_SQL[filters["sort"]]
        notes = [dict(row) for row in get_db().execute(sql, params)]
        attach_tags(notes)
        return notes

    def attach_tags(notes):
        """Add a 'tags' list (id, name) to each note dict using one query per 500 notes."""
        by_id = {n["id"]: n for n in notes}
        for n in notes:
            n["tags"] = []
        ids = list(by_id)
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            marks = ",".join("?" * len(part))  # placeholders only; values are bound
            rows = get_db().execute(
                "SELECT note_tags.note_id, tags.id, tags.name FROM note_tags "
                "JOIN tags ON tags.id = note_tags.tag_id "
                f"WHERE note_tags.note_id IN ({marks}) ORDER BY tags.name COLLATE NOCASE, tags.id", part)
            for row in rows:
                by_id[row["note_id"]]["tags"].append({"id": row["id"], "name": row["name"]})

    def list_context(state, endpoint):
        filters = parse_filters(state)
        return {
            "filters": filters, "endpoint": endpoint, "categories": get_categories(), "tags": get_tags(),
            "sort_options": [(v, SORT_LABELS[v]) for v in STATE_SORTS[state]],
            "return_to": filter_url(endpoint, filters), "notes": list_notes(state, filters),
        }

    def safe_return(raw):
        """A same-site list URL (path + query) from a hidden field, or None. Only the three list
        pages are allowed, so this can never redirect off-site or to an arbitrary path."""
        raw = (raw or "").strip()
        if not raw or len(raw) > 600 or not raw.startswith("/") or raw.startswith("//") \
                or "\\" in raw or any(ord(c) < 32 for c in raw):
            return None
        parts = urlsplit(raw)
        if parts.scheme or parts.netloc or parts.path not in RETURN_PATHS:
            return None
        return parts.path + ("?" + parts.query if parts.query else "")

    # ---- tag helpers ----
    def resolve_tags(selected_raw, new_raw):
        """Validate tag input WITHOUT writing. Returns (existing_ids, new_names, error)."""
        db, ids, names, seen = get_db(), set(), [], set()
        for raw in selected_raw:
            row = lookup_id("tags", raw)
            if row is None:
                return None, None, "Choose valid tags."
            ids.add(row["id"])
        parts = [normalize_tag(p) for p in (new_raw or "").split(",")]
        for name in parts:
            if not name:
                continue
            error = validate_tag_name(name)
            if error:
                return None, None, error
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            row = db.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()  # NOCASE column
            if row:
                ids.add(row["id"])
            else:
                names.append(name)
        if len(ids) + len(names) > MAX_TAGS_PER_NOTE:
            return None, None, f"A note can have at most {MAX_TAGS_PER_NOTE} tags."
        return ids, names, None

    def write_note_tags(note_id, existing_ids, new_names):
        """Create missing tags and make the note's tag set exactly the given one (no commit).
        Returns True if the note's tags changed."""
        db = get_db()
        wanted = set(existing_ids)
        for name in new_names:
            try:
                db.execute("INSERT INTO tags (name) VALUES (?)", (name,))
            except sqlite3.IntegrityError:  # created concurrently: reuse it
                pass
            wanted.add(db.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()["id"])
        current = {r["tag_id"] for r in db.execute("SELECT tag_id FROM note_tags WHERE note_id = ?", (note_id,))}
        for tag_id in current - wanted:
            db.execute("DELETE FROM note_tags WHERE note_id = ? AND tag_id = ?", (note_id, tag_id))
        for tag_id in wanted - current:
            db.execute("INSERT INTO note_tags (note_id, tag_id) VALUES (?, ?)", (note_id, tag_id))
        return current != wanted

    app.add_template_filter(media.human_size, "filesize")

    def upload_root():
        return app.config["UPLOAD_FOLDER"]

    def release_files(keys):
        """Delete files whose rows are already gone. Runs only AFTER the DB commit, so a failure
        can leave an unreferenced file (harmless, cleaned by `flask cleanup-media`) but never a
        row pointing at a missing file. A file still referenced by any row is never deleted."""
        keys = list(keys)
        if not keys:
            return
        db, still_used = get_db(), set()
        for i in range(0, len(keys), 500):
            part = keys[i:i + 500]
            marks = ",".join("?" * len(part))  # placeholders only; values are bound
            still_used |= {r[0] for r in db.execute(
                f"SELECT storage_key FROM media WHERE storage_key IN ({marks})", part)}
        failed = media.remove_files(upload_root(), [k for k in keys if k not in still_used])
        if failed:
            flash(f"{len(failed)} attachment file(s) could not be removed from disk. They are no longer "
                  "linked to any note; run \u201cflask --app app cleanup-media\u201d to remove them.", "error")

    def redirect_back(default):
        destination = safe_return(request.form.get("return_to"))
        if destination:
            return redirect(destination)
        target = request.form.get("next", default)
        if target not in NEXT_TARGETS:
            target = default
        return redirect(url_for(target))

    # ---- routes ----
    @app.route("/")
    def index():
        context = list_context("active", "index")
        filters = context["filters"]
        return render_template("index.html", query=filters["q"], active_category=filters["category"], **context)

    @app.route("/add", methods=["POST"])
    def add():
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        category_id, category_error = parse_category_id(request.form.get("category_id"))
        tag_ids, new_tags, tag_error = resolve_tags([], request.form.get("new_tags", ""))
        error = validate_note(title, content) or category_error or tag_error
        if error:
            flash(error, "error")
        else:
            db = get_db()
            cursor = db.execute(
                "INSERT INTO notes (title, content, category_id) VALUES (?, ?, ?)",
                (title, content, category_id),
            )
            write_note_tags(cursor.lastrowid, tag_ids, new_tags)
            db.commit()
            flash("Note added.", "success")
        return redirect(url_for("index"))

    def edit_context(note, title, content, selected_category, selected_tags, new_tags, return_to):
        return {
            "note": note, "title": title, "content": content, "categories": get_categories(),
            "selected_category": selected_category, "tags": get_tags(),
            "selected_tags": {str(t) for t in selected_tags}, "new_tags": new_tags,
            "return_to": return_to or "", "return_url": return_to or url_for("index"),
        }

    @app.route("/edit/<int:note_id>", methods=["GET", "POST"])
    def edit(note_id):
        note = get_note_or_404(note_id, trashed=False)
        if request.method == "POST":
            return_to = safe_return(request.form.get("return_to"))
            title = request.form.get("title", "").strip()
            content = request.form.get("content", "").strip()
            if "category_id" in request.form:
                category_id, category_error = parse_category_id(request.form["category_id"])
            else:  # older clients that don't send the field keep the current category
                category_id, category_error = note["category_id"], None
            # Tags are only touched when the form says it carries the tag controls.
            tags_sent = "tags_submitted" in request.form
            selected = request.form.getlist("tag_ids") if tags_sent else []
            new_raw = request.form.get("new_tags", "") if tags_sent else ""
            tag_ids, new_tags, tag_error = resolve_tags(selected, new_raw) if tags_sent else (None, None, None)
            error = validate_note(title, content) or category_error or tag_error
            if error:
                flash(error, "error")
                if tags_sent:
                    shown_tags = selected
                else:
                    shown_tags = [r["tag_id"] for r in get_db().execute(
                        "SELECT tag_id FROM note_tags WHERE note_id = ?", (note_id,))]
                return render_template("edit.html", **edit_context(
                    note, title, content, request.form.get("category_id", note["category_id"]),
                    shown_tags, new_raw, return_to))
            db = get_db()
            tags_changed = write_note_tags(note_id, tag_ids, new_tags) if tags_sent else False
            changed = (title != note["title"] or content != note["content"]
                       or category_id != note["category_id"] or tags_changed)
            if changed:  # a real edit: bump updated_at; a no-op save leaves it alone
                db.execute(
                    "UPDATE notes SET title = ?, content = ?, category_id = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (title, content, category_id, note_id),
                )
            db.commit()
            flash("Note updated." if changed else "No changes to save.", "success")
            default = "archive_view" if note["archived_at"] else "index"
            return redirect(return_to or url_for(default))
        current = [r["tag_id"] for r in get_db().execute("SELECT tag_id FROM note_tags WHERE note_id = ?", (note_id,))]
        return render_template("edit.html", **edit_context(
            note, note["title"], note["content"], note["category_id"], current, "",
            safe_return(request.args.get("return_to"))))

    @app.route("/pin/<int:note_id>", methods=["POST"])
    def pin(note_id):
        note = get_note_or_404(note_id, trashed=False)
        db = get_db()
        db.execute("UPDATE notes SET pinned = ? WHERE id = ?", (0 if note["pinned"] else 1, note_id))
        db.commit()
        return redirect_back("index")

    # -- categories --
    @app.route("/categories")
    def categories_view():
        rows = get_db().execute(
            "SELECT categories.id, categories.name, COUNT(notes.id) AS note_count, "
            "(SELECT COUNT(*) FROM notes WHERE notes.category_id = categories.id) AS total_count "
            "FROM categories LEFT JOIN notes ON notes.category_id = categories.id AND "
            + STATE_FILTERS["active"] +
            " GROUP BY categories.id ORDER BY categories.id"
        ).fetchall()
        return render_template("categories.html", categories=rows, max_name=MAX_CATEGORY_NAME)

    @app.route("/categories", methods=["POST"])
    def add_category():
        name = " ".join(request.form.get("name", "").split())
        error = validate_category_name(name)
        if not error:
            db = get_db()
            try:
                db.execute("INSERT INTO categories (name) VALUES (?)", (name,))
                db.commit()
            except sqlite3.IntegrityError:  # UNIQUE ... COLLATE NOCASE
                db.rollback()
                error = f"A category named \u201c{name}\u201d already exists."
        if error:
            flash(error, "error")
        else:
            flash(f"Category \u201c{name}\u201d created.", "success")
        return redirect(url_for("categories_view"))

    def get_category_or_404(category_id):
        row = get_db().execute("SELECT id, name FROM categories WHERE id = ?", (category_id,)).fetchone()
        if row is None:
            abort(404)
        return row

    @app.route("/categories/<int:category_id>/rename", methods=["POST"])
    def rename_category(category_id):
        category = get_category_or_404(category_id)
        name = " ".join(request.form.get("name", "").split())
        error = validate_category_name(name)
        if not error:
            db = get_db()
            try:  # the NOCASE UNIQUE index also rejects case-only clashes with *another* category
                db.execute("UPDATE categories SET name = ? WHERE id = ?", (name, category_id))
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                error = f"A category named \u201c{name}\u201d already exists."
        if error:
            flash(error, "error")
        else:
            flash(f"Category renamed to \u201c{name}\u201d.", "success")
        return redirect(url_for("categories_view"))

    @app.route("/categories/<int:category_id>/delete")
    def confirm_delete_category(category_id):
        category = get_category_or_404(category_id)
        total = get_db().execute(
            "SELECT COUNT(*) FROM notes WHERE category_id = ?", (category_id,)).fetchone()[0]
        noun = "note" if total == 1 else "notes"
        message = (f"Its {total} {noun} will be kept and become uncategorized."
                   if total else "No notes use this category.")
        return render_template(
            "confirm_delete.html", heading=f"Delete category \u201c{category['name']}\u201d?", message=message,
            action=url_for("delete_category", category_id=category_id), cancel_url=url_for("categories_view"),
            button="Delete category", back_label="Categories",
        )

    @app.route("/categories/<int:category_id>/delete", methods=["POST"])
    def delete_category(category_id):
        category = get_category_or_404(category_id)
        db = get_db()
        # Explicit un-assign (the foreign key would also do this) so notes are never lost,
        # whatever state they are in: active, archived or in Trash.
        db.execute("UPDATE notes SET category_id = NULL WHERE category_id = ?", (category_id,))
        db.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        db.commit()
        flash(f"Category \u201c{category['name']}\u201d deleted. Its notes were kept.", "success")
        return redirect(url_for("categories_view"))

    # -- tags --
    def get_tag_or_404(tag_id):
        row = get_db().execute("SELECT id, name FROM tags WHERE id = ?", (tag_id,)).fetchone()
        if row is None:
            abort(404)
        return row

    @app.route("/tags")
    def tags_view():
        rows = get_db().execute(
            "SELECT tags.id, tags.name, COUNT(notes.id) AS note_count, "
            "(SELECT COUNT(*) FROM note_tags WHERE note_tags.tag_id = tags.id) AS total_count FROM tags "
            "LEFT JOIN note_tags ON note_tags.tag_id = tags.id "
            "LEFT JOIN notes ON notes.id = note_tags.note_id AND " + STATE_FILTERS["active"] +
            " GROUP BY tags.id ORDER BY tags.name COLLATE NOCASE, tags.id"
        ).fetchall()
        return render_template("tags.html", tags=rows, max_name=MAX_TAG_NAME)

    @app.route("/tags", methods=["POST"])
    def add_tag():
        name = normalize_tag(request.form.get("name", ""))
        error = validate_tag_name(name)
        if not error:
            db = get_db()
            try:
                db.execute("INSERT INTO tags (name) VALUES (?)", (name,))
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                error = f"A tag named \u201c{name}\u201d already exists."
        if error:
            flash(error, "error")
        else:
            flash(f"Tag \u201c{name}\u201d created.", "success")
        return redirect(url_for("tags_view"))

    @app.route("/tags/<int:tag_id>/delete")
    def confirm_delete_tag(tag_id):
        tag = get_tag_or_404(tag_id)
        total = get_db().execute("SELECT COUNT(*) FROM note_tags WHERE tag_id = ?", (tag_id,)).fetchone()[0]
        noun = "note" if total == 1 else "notes"
        message = (f"It will be removed from {total} {noun}. The {noun} themselves are kept."
                   if total else "No notes use this tag.")
        return render_template(
            "confirm_delete.html", heading=f"Delete tag \u201c{tag['name']}\u201d?", message=message,
            action=url_for("delete_tag", tag_id=tag_id), cancel_url=url_for("tags_view"),
            button="Delete tag", back_label="Tags",
        )

    @app.route("/tags/<int:tag_id>/delete", methods=["POST"])
    def delete_tag(tag_id):
        tag = get_tag_or_404(tag_id)
        db = get_db()
        db.execute("DELETE FROM tags WHERE id = ?", (tag_id,))  # note_tags rows cascade; notes untouched
        db.commit()
        flash(f"Tag \u201c{tag['name']}\u201d deleted. Its notes were kept.", "success")
        return redirect(url_for("tags_view"))

    # -- archive --
    @app.route("/archive")
    def archive_view():
        return render_template("archive.html", **list_context("archived", "archive_view"))

    @app.route("/archive/<int:note_id>", methods=["POST"])
    def archive_note(note_id):
        get_note_or_404(note_id, trashed=False)
        db = get_db()
        db.execute(
            "UPDATE notes SET archived_at = COALESCE(archived_at, CURRENT_TIMESTAMP) WHERE id = ?",
            (note_id,),
        )
        db.commit()
        flash("Note archived.", "success")
        return redirect_back("index")

    @app.route("/unarchive/<int:note_id>", methods=["POST"])
    def unarchive_note(note_id):
        get_note_or_404(note_id, trashed=False)
        db = get_db()
        db.execute("UPDATE notes SET archived_at = NULL WHERE id = ?", (note_id,))
        db.commit()
        flash("Note moved back to All notes.", "success")
        return redirect_back("archive_view")

    # -- trash --
    @app.route("/delete/<int:note_id>", methods=["POST"])
    def delete(note_id):
        """Moves a note to Trash. Nothing is permanently deleted here (see purge_note)."""
        note = get_note_or_404(note_id)
        if note["trashed_at"] is not None:
            flash("Note is already in Trash.", "success")
        else:
            db = get_db()
            db.execute("UPDATE notes SET trashed_at = CURRENT_TIMESTAMP WHERE id = ?", (note_id,))
            db.commit()
            flash("Note moved to Trash.", "success")
        return redirect_back("index")

    @app.route("/trash")
    def trash_view():
        return render_template("trash.html", **list_context("trashed", "trash_view"))

    @app.route("/restore/<int:note_id>", methods=["POST"])
    def restore_note(note_id):
        note = get_note_or_404(note_id, trashed=True)
        db = get_db()
        db.execute("UPDATE notes SET trashed_at = NULL WHERE id = ?", (note_id,))
        db.commit()
        flash("Note restored to Archive." if note["archived_at"] else "Note restored.", "success")
        return redirect_back("trash_view")

    @app.route("/purge/<int:note_id>", methods=["POST"])
    def purge_note(note_id):
        """Permanent deletion. Only works on notes that are already in Trash."""
        get_note_or_404(note_id, trashed=True)
        db = get_db()
        keys = [r["storage_key"] for r in db.execute(
            "SELECT storage_key FROM media WHERE note_id = ?", (note_id,))]
        db.execute("DELETE FROM notes WHERE id = ? AND trashed_at IS NOT NULL", (note_id,))
        db.commit()  # media rows go with the note (ON DELETE CASCADE)
        release_files(keys)
        flash("Note permanently deleted.", "success")
        return redirect_back("trash_view")

    @app.route("/trash/empty", methods=["POST"])
    def empty_trash():
        db = get_db()
        keys = [r["storage_key"] for r in db.execute(
            "SELECT storage_key FROM media WHERE note_id IN "
            "(SELECT id FROM notes WHERE trashed_at IS NOT NULL)")]
        cursor = db.execute("DELETE FROM notes WHERE trashed_at IS NOT NULL")
        db.commit()
        release_files(keys)
        if cursor.rowcount:
            noun = "note" if cursor.rowcount == 1 else "notes"
            flash(f"Trash emptied: {cursor.rowcount} {noun} permanently deleted.", "success")
        else:
            flash("Trash is already empty.", "success")
        return redirect(url_for("trash_view"))

    # ---- media attachments (Agent 4) ----
    # Policy: media follows its note. Notes in Trash hide their attachments (library, viewer and
    # file URLs return 404, uploads/deletes are refused) and Restore brings them back untouched.
    # Archived notes keep full access.
    MEDIA_SELECT = (
        "SELECT media.*, notes.title AS note_title FROM media "
        "JOIN notes ON notes.id = media.note_id WHERE notes.trashed_at IS NULL"
    )

    def get_media_or_404(media_id):
        row = get_db().execute(MEDIA_SELECT + " AND media.id = ?", (media_id,)).fetchone()
        if row is None:
            abort(404)
        return row

    @app.errorhandler(413)
    def request_too_large(_error):
        limit = app.config["MAX_CONTENT_LENGTH"] // media.MIB
        flash(f"That upload is too large. Keep each upload under {limit} MiB in total.", "error")
        return redirect(url_for("media_library"))

    @app.route("/media")
    def media_library():
        kind = request.args.get("type", "").strip()
        if kind not in ("", "image", "audio"):
            abort(404)
        sql, params = MEDIA_SELECT, []
        if kind:
            sql += " AND media.kind = ?"
            params.append(kind)
        items = get_db().execute(sql + " ORDER BY media.id DESC", params).fetchall()
        return render_template("media_library.html", items=items, kind=kind)

    @app.route("/media/<int:media_id>")
    def media_view(media_id):
        return render_template("media_view.html", item=get_media_or_404(media_id))

    @app.route("/media/<int:media_id>/file")
    def media_file(media_id):
        """Streams one stored file by database id. The path comes from a validated storage key,
        never from the URL, and the MIME type is the one verified at upload time."""
        item = get_media_or_404(media_id)
        try:
            path = media.upload_path(upload_root(), item["storage_key"])
            response = send_file(
                path, mimetype=item["mime_type"], conditional=True,
                download_name=media.clean_filename(item["original_name"]),
            )
        except (ValueError, FileNotFoundError):
            abort(404)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; media-src 'self'; sandbox allow-same-origin"
        )
        response.headers["Cache-Control"] = "private, max-age=0, must-revalidate"
        return response

    @app.route("/notes/<int:note_id>/media")
    def note_media(note_id):
        note = get_note_or_404(note_id, trashed=False)
        items = get_db().execute(
            MEDIA_SELECT + " AND media.note_id = ? ORDER BY media.id DESC", (note_id,)
        ).fetchall()
        return render_template(
            "note_media.html", note=note, items=items,
            max_files=MAX_FILES_PER_UPLOAD, max_per_note=MAX_ATTACHMENTS_PER_NOTE,
            max_image_mib=app.config["MAX_IMAGE_BYTES"] // media.MIB,
            max_audio_mib=app.config["MAX_AUDIO_BYTES"] // media.MIB,
        )

    @app.route("/notes/<int:note_id>/media", methods=["POST"])
    def upload_media(note_id):
        get_note_or_404(note_id, trashed=False)
        back = redirect(url_for("note_media", note_id=note_id))
        files = [f for f in request.files.getlist("files") if f and f.filename]
        db = get_db()
        existing = db.execute("SELECT COUNT(*) FROM media WHERE note_id = ?", (note_id,)).fetchone()[0]
        if not files:
            flash("Choose at least one file to upload.", "error")
            return back
        if len(files) > MAX_FILES_PER_UPLOAD:
            flash(f"Upload at most {MAX_FILES_PER_UPLOAD} files at a time.", "error")
            return back
        if existing + len(files) > MAX_ATTACHMENTS_PER_NOTE:
            flash(f"A note can have at most {MAX_ATTACHMENTS_PER_NOTE} attachments.", "error")
            return back
        limits = {"image": app.config["MAX_IMAGE_BYTES"], "audio": app.config["MAX_AUDIO_BYTES"]}
        saved, errors = 0, []
        for upload in files:
            name = media.clean_filename(upload.filename)
            info, problem = media.save_stream(upload.stream, upload.filename, upload_root(), limits)
            if problem:
                errors.append(f"\u201c{name}\u201d {problem}")
                continue
            try:
                db.execute(
                    "INSERT INTO media (note_id, storage_key, original_name, kind, mime_type, size_bytes) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (note_id, info["key"], name, info["kind"], info["mime"], info["size"]),
                )
                db.commit()
                saved += 1
            except sqlite3.Error:
                db.rollback()
                media.remove_files(upload_root(), [info["key"]])  # never leave an orphan file
                errors.append(f"\u201c{name}\u201d could not be saved.")
        for message in errors:
            flash(message, "error")
        if saved:
            flash(f"{saved} attachment{'s' if saved != 1 else ''} added.", "success")
        return back

    @app.route("/media/<int:media_id>/delete", methods=["POST"])
    def delete_media(media_id):
        item = get_media_or_404(media_id)
        db = get_db()
        db.execute("DELETE FROM media WHERE id = ?", (media_id,))
        db.commit()
        release_files([item["storage_key"]])
        flash("Attachment deleted.", "success")
        return redirect(url_for("note_media", note_id=item["note_id"]))

    @app.cli.command("cleanup-media")
    def cleanup_media_command():
        """Delete files in UPLOAD_FOLDER that no attachment row references."""
        known = [r["storage_key"] for r in get_db().execute("SELECT storage_key FROM media")]
        removed = media.cleanup_orphans(upload_root(), known)
        click.echo(f"Removed {len(removed)} unreferenced file(s).")

    return app


if __name__ == "__main__":
    environment = os.environ.get("APP_ENV", "development").strip().lower()
    create_app({"APP_ENV": environment}).run(debug=environment == "development")
