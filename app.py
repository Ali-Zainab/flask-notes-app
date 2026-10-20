"""Flask Notes App: create, search, edit, pin and delete notes (SQLite storage)."""

import os
import sqlite3

from flask import Flask, abort, flash, g, redirect, render_template, request, url_for

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    content    TEXT NOT NULL DEFAULT '',
    pinned     INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

MAX_TITLE = 100
MAX_CONTENT = 2000


def validate_note(title, content):
    """Return an error message, or None if the input is fine."""
    if not title:
        return "Title is required."
    if len(title) > MAX_TITLE:
        return f"Title must be {MAX_TITLE} characters or fewer."
    if len(content) > MAX_CONTENT:
        return f"Content must be {MAX_CONTENT} characters or fewer."
    return None


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        DATABASE=os.path.join(app.root_path, "notes.db"),
    )
    if test_config:
        app.config.update(test_config)

    # ---- database helpers ----
    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(_error):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    with sqlite3.connect(app.config["DATABASE"]) as conn:
        conn.execute(SCHEMA)

    def get_note_or_404(note_id):
        note = get_db().execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if note is None:
            abort(404)
        return note

    # ---- routes ----
    @app.route("/")
    def index():
        query = request.args.get("q", "").strip()
        if query:
            like = f"%{query}%"
            notes = get_db().execute(
                "SELECT * FROM notes WHERE title LIKE ? OR content LIKE ? "
                "ORDER BY pinned DESC, id DESC",
                (like, like),
            ).fetchall()
        else:
            notes = get_db().execute(
                "SELECT * FROM notes ORDER BY pinned DESC, id DESC"
            ).fetchall()
        return render_template("index.html", notes=notes, query=query)

    @app.route("/add", methods=["POST"])
    def add():
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        error = validate_note(title, content)
        if error:
            flash(error, "error")
        else:
            db = get_db()
            db.execute("INSERT INTO notes (title, content) VALUES (?, ?)", (title, content))
            db.commit()
            flash("Note added.", "success")
        return redirect(url_for("index"))

    @app.route("/edit/<int:note_id>", methods=["GET", "POST"])
    def edit(note_id):
        note = get_note_or_404(note_id)
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            content = request.form.get("content", "").strip()
            error = validate_note(title, content)
            if error:
                flash(error, "error")
                return render_template("edit.html", note=note, title=title, content=content)
            db = get_db()
            db.execute("UPDATE notes SET title = ?, content = ? WHERE id = ?", (title, content, note_id))
            db.commit()
            flash("Note updated.", "success")
            return redirect(url_for("index"))
        return render_template("edit.html", note=note, title=note["title"], content=note["content"])

    @app.route("/pin/<int:note_id>", methods=["POST"])
    def pin(note_id):
        note = get_note_or_404(note_id)
        db = get_db()
        db.execute("UPDATE notes SET pinned = ? WHERE id = ?", (0 if note["pinned"] else 1, note_id))
        db.commit()
        return redirect(url_for("index"))

    @app.route("/delete/<int:note_id>", methods=["POST"])
    def delete(note_id):
        get_note_or_404(note_id)
        db = get_db()
        db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        db.commit()
        flash("Note deleted.", "success")
        return redirect(url_for("index"))

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
