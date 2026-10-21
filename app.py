"""Flask Notes App: notes with categories, archive and trash (SQLite storage)."""

import os
import secrets
import sqlite3

from flask import Flask, abort, flash, g, redirect, render_template, request, url_for
from flask_wtf.csrf import CSRFProtect

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
)

NOTE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_notes_category ON notes (category_id)",
    "CREATE INDEX IF NOT EXISTS idx_notes_state ON notes (trashed_at, archived_at)",
)

DEFAULT_CATEGORIES = ("Work", "Business", "Personal", "Homework")

MAX_TITLE = 100
MAX_CONTENT = 2000
MAX_CATEGORY_NAME = 40

# A note is in exactly one list. Trash wins over archive: a note that was archived and
# then trashed keeps archived_at, so restoring it from Trash returns it to the Archive.
# These fragments are constants, never built from user input.
STATE_FILTERS = {
    "active": "notes.archived_at IS NULL AND notes.trashed_at IS NULL",
    "archived": "notes.archived_at IS NOT NULL AND notes.trashed_at IS NULL",
    "trashed": "notes.trashed_at IS NOT NULL",
}
STATE_ORDER = {
    "active": "notes.pinned DESC, notes.id DESC",
    "archived": "notes.pinned DESC, notes.id DESC",
    "trashed": "notes.trashed_at DESC, notes.id DESC",
}

# Endpoints a POST form may ask to be redirected back to (via a hidden "next" field).
# Anything else falls back to the route's default, so this can never be an open redirect.
NEXT_TARGETS = {"index", "archive_view", "trash_view"}


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
            conn.executemany(
                "INSERT OR IGNORE INTO categories (name) VALUES (?)",
                [(name,) for name in DEFAULT_CATEGORIES],
            )
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

    def list_notes(state, query="", category_id=None):
        sql = (
            "SELECT notes.*, categories.name AS category_name FROM notes "
            "LEFT JOIN categories ON categories.id = notes.category_id "
            "WHERE " + STATE_FILTERS[state]
        )
        params = []
        if query:
            sql += " AND (notes.title LIKE ? OR notes.content LIKE ?)"
            params += [f"%{query}%", f"%{query}%"]
        if category_id is not None:
            sql += " AND notes.category_id = ?"
            params.append(category_id)
        sql += " ORDER BY " + STATE_ORDER[state]
        return get_db().execute(sql, params).fetchall()

    def redirect_back(default):
        target = request.form.get("next", default)
        if target not in NEXT_TARGETS:
            target = default
        return redirect(url_for(target))

    # ---- routes ----
    @app.route("/")
    def index():
        query = request.args.get("q", "").strip()
        category = None
        raw_category = request.args.get("category", "").strip()
        if raw_category:
            if raw_category.isascii() and raw_category.isdigit():
                category = get_db().execute(
                    "SELECT id, name FROM categories WHERE id = ?", (int(raw_category),)
                ).fetchone()
            if category is None:
                abort(404)
        notes = list_notes("active", query, category["id"] if category else None)
        return render_template(
            "index.html", notes=notes, query=query,
            categories=get_categories(), active_category=category,
        )

    @app.route("/add", methods=["POST"])
    def add():
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        category_id, category_error = parse_category_id(request.form.get("category_id"))
        error = validate_note(title, content) or category_error
        if error:
            flash(error, "error")
        else:
            db = get_db()
            db.execute(
                "INSERT INTO notes (title, content, category_id) VALUES (?, ?, ?)",
                (title, content, category_id),
            )
            db.commit()
            flash("Note added.", "success")
        return redirect(url_for("index"))

    @app.route("/edit/<int:note_id>", methods=["GET", "POST"])
    def edit(note_id):
        note = get_note_or_404(note_id, trashed=False)
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            content = request.form.get("content", "").strip()
            if "category_id" in request.form:
                category_id, category_error = parse_category_id(request.form["category_id"])
            else:  # older clients that don't send the field keep the current category
                category_id, category_error = note["category_id"], None
            error = validate_note(title, content) or category_error
            if error:
                flash(error, "error")
                return render_template(
                    "edit.html", note=note, title=title, content=content,
                    categories=get_categories(),
                    selected_category=request.form.get("category_id", ""),
                )
            db = get_db()
            db.execute(
                "UPDATE notes SET title = ?, content = ?, category_id = ? WHERE id = ?",
                (title, content, category_id, note_id),
            )
            db.commit()
            flash("Note updated.", "success")
            return redirect(url_for("archive_view" if note["archived_at"] else "index"))
        return render_template(
            "edit.html", note=note, title=note["title"], content=note["content"],
            categories=get_categories(), selected_category=note["category_id"],
        )

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
            "SELECT categories.id, categories.name, COUNT(notes.id) AS note_count "
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

    # -- archive --
    @app.route("/archive")
    def archive_view():
        return render_template("archive.html", notes=list_notes("archived"))

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
        return render_template("trash.html", notes=list_notes("trashed"))

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
        db.execute("DELETE FROM notes WHERE id = ? AND trashed_at IS NOT NULL", (note_id,))
        db.commit()
        flash("Note permanently deleted.", "success")
        return redirect_back("trash_view")

    @app.route("/trash/empty", methods=["POST"])
    def empty_trash():
        db = get_db()
        cursor = db.execute("DELETE FROM notes WHERE trashed_at IS NOT NULL")
        db.commit()
        if cursor.rowcount:
            noun = "note" if cursor.rowcount == 1 else "notes"
            flash(f"Trash emptied: {cursor.rowcount} {noun} permanently deleted.", "success")
        else:
            flash("Trash is already empty.", "success")
        return redirect(url_for("trash_view"))

    return app


if __name__ == "__main__":
    environment = os.environ.get("APP_ENV", "development").strip().lower()
    create_app({"APP_ENV": environment}).run(debug=environment == "development")
