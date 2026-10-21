import re
import sqlite3

import pytest

from app import create_app, init_db


@pytest.fixture
def app(tmp_path):
    return create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "DATABASE": str(tmp_path / "test.db"),
    })


@pytest.fixture
def client(app):
    return app.test_client()


def add_note(client, title="Shopping", content="Milk and eggs"):
    return client.post("/add", data={"title": title, "content": content}, follow_redirects=True)


def test_index_starts_empty(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"No notes yet" in response.data


def test_add_note(client):
    response = add_note(client)
    assert b"Note added." in response.data
    assert b"Shopping" in response.data
    assert b"Milk and eggs" in response.data


def test_add_requires_title(client):
    response = add_note(client, title="   ")
    assert b"Title is required." in response.data
    assert b"No notes yet" in response.data


def test_title_too_long_rejected(client):
    response = add_note(client, title="x" * 101)
    assert b"100 characters or fewer" in response.data


def test_edit_note(client):
    add_note(client)
    response = client.post("/edit/1", data={"title": "Groceries", "content": "Bread"}, follow_redirects=True)
    assert b"Note updated." in response.data
    assert b"Groceries" in response.data
    assert b"Shopping" not in response.data


def test_edit_with_empty_title_shows_error(client):
    add_note(client)
    response = client.post("/edit/1", data={"title": "", "content": "x"})
    assert b"Title is required." in response.data


def test_delete_note(client):
    # /delete/<id> now moves the note to Trash (documented change); see the trash tests below.
    add_note(client)
    response = client.post("/delete/1", follow_redirects=True)
    assert b"Note moved to Trash." in response.data
    assert b"No notes yet" in response.data


def test_missing_note_returns_404(client):
    assert client.get("/edit/999").status_code == 404
    assert client.post("/delete/999").status_code == 404
    assert client.post("/pin/999").status_code == 404


def test_search_filters_notes(client):
    add_note(client, "Shopping", "Milk")
    add_note(client, "Homework", "Maths chapter 4")
    response = client.get("/?q=maths")
    assert b"Homework" in response.data
    assert b"Shopping" not in response.data
    assert b"No notes match" in client.get("/?q=zzz").data


def test_pinned_notes_come_first(client):
    add_note(client, "First", "a")
    add_note(client, "Second", "b")
    client.post("/pin/1")
    html = client.get("/").data.decode()
    assert html.index("First") < html.index("Second")


def test_html_in_notes_is_escaped(client):
    add_note(client, "<script>alert(1)</script>", "<b>bold</b>")
    html = client.get("/").data.decode()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_environment_config_is_used(monkeypatch, tmp_path):
    database = tmp_path / "environment.db"
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "configured-secret")
    monkeypatch.setenv("DATABASE", str(database))

    app = create_app()

    assert app.config["APP_ENV"] == "production"
    assert app.config["SECRET_KEY"] == "configured-secret"
    assert app.config["DATABASE"] == str(database)
    assert database.exists()


def test_test_config_overrides_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("SECRET_KEY", "environment-secret")
    monkeypatch.setenv("DATABASE", str(tmp_path / "environment.db"))
    database = tmp_path / "test-config.db"

    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-config-secret",
        "DATABASE": str(database),
    })

    assert app.config["SECRET_KEY"] == "test-config-secret"
    assert app.config["DATABASE"] == str(database)


def test_production_requires_secret_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SECRET_KEY must be set"):
        create_app()


def test_development_secret_is_random_when_not_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("DATABASE", str(tmp_path / "development.db"))

    first = create_app()
    second = create_app()

    assert first.config["SECRET_KEY"]
    assert first.config["SECRET_KEY"] != "dev-only-change-me"
    assert first.config["SECRET_KEY"] != second.config["SECRET_KEY"]


def test_post_requires_csrf_token(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "csrf-test-secret")
    monkeypatch.setenv("DATABASE", str(tmp_path / "csrf.db"))
    app = create_app()

    response = app.test_client().post(
        "/add", data={"title": "Shopping", "content": "Milk"}
    )

    assert response.status_code == 400
    assert b"CSRF" in response.data


# ======================================================================
# Categories, archive and trash
# All tests use temporary databases (tmp_path); the real notes.db is never touched.
# ======================================================================

def query_db(app, sql, params=()):
    """Read straight from the test database file (independent of the app's own connection)."""
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def note_row(app, note_id):
    rows = query_db(app, "SELECT * FROM notes WHERE id = ?", (note_id,))
    return rows[0] if rows else None


def category_names(app):
    return [r["name"] for r in query_db(app, "SELECT name FROM categories ORDER BY id")]


def add_with_category(client, title, category_id, content="body"):
    return client.post(
        "/add",
        data={"title": title, "content": content, "category_id": str(category_id)},
        follow_redirects=True,
    )


def page(client, url="/"):
    return client.get(url).data.decode()


DEFAULTS = ["Work", "Business", "Personal", "Homework"]


# ---------- default categories ----------

def test_default_categories_are_seeded(app):
    assert category_names(app) == DEFAULTS


def test_default_categories_not_duplicated_by_repeated_init(tmp_path):
    database = str(tmp_path / "repeat.db")
    for _ in range(3):
        create_app({"TESTING": True, "DATABASE": database})
    init_db(database)
    conn = sqlite3.connect(database)
    names = [r[0] for r in conn.execute("SELECT name FROM categories ORDER BY id")]
    conn.close()
    assert names == DEFAULTS


def test_categories_page_lists_defaults_with_counts(client):
    html = page(client, "/categories")
    for name in DEFAULTS:
        assert name in html


# ---------- creating categories ----------

def test_create_custom_category(app, client):
    response = client.post("/categories", data={"name": "Fitness"}, follow_redirects=True)
    assert b"created" in response.data
    assert b"Fitness" in response.data
    assert category_names(app)[-1] == "Fitness"


def test_category_name_is_trimmed_and_whitespace_collapsed(app, client):
    client.post("/categories", data={"name": "  Side    Project  "})
    assert "Side Project" in category_names(app)


def test_blank_category_name_rejected(app, client):
    response = client.post("/categories", data={"name": "   "}, follow_redirects=True)
    assert b"Category name is required." in response.data
    assert category_names(app) == DEFAULTS


def test_overlong_category_name_rejected_but_limit_accepted(app, client):
    too_long = client.post("/categories", data={"name": "x" * 41}, follow_redirects=True)
    assert b"40 characters or fewer" in too_long.data
    client.post("/categories", data={"name": "y" * 40})
    assert category_names(app) == DEFAULTS + ["y" * 40]


def test_control_characters_in_category_name_rejected(app, client):
    response = client.post("/categories", data={"name": "Bad\x00name"}, follow_redirects=True)
    assert b"invalid characters" in response.data
    assert category_names(app) == DEFAULTS


@pytest.mark.parametrize("name", ["Work", "work", "  WORK ", "hOmEwOrK"])
def test_duplicate_category_rejected_case_insensitively(app, client, name):
    response = client.post("/categories", data={"name": name}, follow_redirects=True)
    assert b"already exists" in response.data
    assert category_names(app) == DEFAULTS


def test_custom_duplicate_rejected(app, client):
    client.post("/categories", data={"name": "Fitness"})
    response = client.post("/categories", data={"name": "fitness"}, follow_redirects=True)
    assert b"already exists" in response.data
    assert category_names(app).count("Fitness") == 1


def test_category_names_are_escaped(client):
    client.post("/categories", data={"name": "<b>x</b>"})
    html = page(client, "/categories")
    assert "<b>x</b>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html


# ---------- assigning and filtering ----------

def test_add_note_with_category(app, client):
    add_with_category(client, "Report", 1)
    assert note_row(app, 1)["category_id"] == 1
    assert "Work" in page(client)


def test_add_note_without_category_is_uncategorised(app, client):
    add_note(client)
    assert note_row(app, 1)["category_id"] is None


@pytest.mark.parametrize("bad", ["999", "abc", "-1", "1.5", "1; DROP TABLE notes"])
def test_add_note_with_invalid_category_rejected(app, client, bad):
    response = add_with_category(client, "Report", bad)
    assert b"Choose a valid category." in response.data
    assert query_db(app, "SELECT COUNT(*) AS n FROM notes")[0]["n"] == 0


def test_changing_category_keeps_id_content_and_timestamp(app, client):
    add_with_category(client, "Report", 1, content="Quarterly numbers")
    before = note_row(app, 1)
    client.post("/edit/1", data={"title": "Report", "content": "Quarterly numbers", "category_id": "2"})
    after = note_row(app, 1)
    assert after["id"] == before["id"]
    assert after["category_id"] == 2
    assert after["content"] == "Quarterly numbers"
    assert after["created_at"] == before["created_at"]


def test_edit_without_category_field_keeps_existing_category(app, client):
    add_with_category(client, "Report", 3)
    client.post("/edit/1", data={"title": "Renamed", "content": "x"})
    assert note_row(app, 1)["category_id"] == 3


def test_edit_with_empty_category_clears_it(app, client):
    add_with_category(client, "Report", 3)
    client.post("/edit/1", data={"title": "Report", "content": "x", "category_id": ""})
    assert note_row(app, 1)["category_id"] is None


def test_edit_with_invalid_category_shows_error_and_changes_nothing(app, client):
    add_with_category(client, "Report", 1)
    response = client.post("/edit/1", data={"title": "Changed", "content": "x", "category_id": "999"})
    assert b"Choose a valid category." in response.data
    row = note_row(app, 1)
    assert row["title"] == "Report" and row["category_id"] == 1


def test_edit_form_preselects_current_category(client):
    add_with_category(client, "Report", 2)
    html = page(client, "/edit/1")
    assert re.search(r'<option value="2" selected>Business</option>', html)


def test_filter_notes_by_category(client):
    add_with_category(client, "Work thing", 1)
    add_with_category(client, "Home thing", 3)
    add_note(client, "Loose thing", "")
    html = page(client, "/?category=1")
    assert "Work thing" in html
    assert "Home thing" not in html and "Loose thing" not in html
    assert 'aria-current="true"' in html  # the active filter chip is exposed to assistive tech


def test_category_filter_combines_with_search(client):
    add_with_category(client, "Alpha budget", 1)
    add_with_category(client, "Beta budget", 2)
    html = page(client, "/?category=1&q=budget")
    assert "Alpha budget" in html and "Beta budget" not in html


@pytest.mark.parametrize("bad", ["999", "abc", "-1"])
def test_unknown_category_filter_returns_404(client, bad):
    assert client.get(f"/?category={bad}").status_code == 404


def test_empty_category_filter_message(client):
    html = page(client, "/?category=1")
    assert "No notes in Work yet" in html


def test_category_counts_only_include_active_notes(client):
    add_with_category(client, "One", 1)
    add_with_category(client, "Two", 1)
    add_with_category(client, "Three", 1)
    client.post("/archive/2")
    client.post("/delete/3")
    html = page(client, "/categories")
    work_card = re.search(r'category-name">.*?<span>Work</span>.*?category-count">(\d+)', html, re.S)
    assert work_card.group(1) == "1"


def test_deleting_a_category_row_keeps_notes(app, client):
    add_with_category(client, "Report", 1)
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM categories WHERE id = 1")
    conn.commit()
    conn.close()
    row = note_row(app, 1)
    assert row is not None and row["category_id"] is None and row["title"] == "Report"


# ---------- archive ----------

def test_archive_hides_note_from_all_notes(app, client):
    add_note(client)
    response = client.post("/archive/1", follow_redirects=True)
    assert b"Note archived." in response.data
    assert b"Shopping" not in response.data  # gone from All notes
    assert "Shopping" in page(client, "/archive")
    assert "Shopping" not in page(client, "/trash")
    assert note_row(app, 1) is not None  # still stored


def test_archived_note_can_be_unarchived(client):
    add_note(client)
    client.post("/archive/1")
    response = client.post("/unarchive/1", follow_redirects=True)
    assert b"Nothing archived" in response.data
    assert "Shopping" in page(client)


def test_archive_preserves_pin_and_data(app, client):
    add_with_category(client, "Keep me", 2, content="details")
    client.post("/pin/1")
    before = note_row(app, 1)
    client.post("/archive/1")
    client.post("/unarchive/1")
    after = note_row(app, 1)
    for column in ("id", "title", "content", "pinned", "created_at", "category_id"):
        assert after[column] == before[column]
    assert after["archived_at"] is None


def test_pin_state_survives_archive_round_trip_and_shows_in_archive(client):
    add_note(client)
    client.post("/pin/1")
    client.post("/archive/1")
    assert "Pinned" in page(client, "/archive")


def test_archived_note_can_be_edited_and_returns_to_archive(client):
    add_note(client)
    client.post("/archive/1")
    response = client.post("/edit/1", data={"title": "Groceries", "content": "x"}, follow_redirects=True)
    assert b"Note updated." in response.data
    assert b"Groceries" in response.data
    assert b"Nothing archived" not in response.data  # we landed on the Archive page


def test_archived_notes_excluded_from_search_and_category_filter(client):
    add_with_category(client, "Budget plan", 1)
    client.post("/archive/1")
    assert "Budget plan" not in page(client, "/?q=budget")
    assert "Budget plan" not in page(client, "/?category=1")


# ---------- trash ----------

def test_delete_moves_note_to_trash_without_deleting_it(app, client):
    add_with_category(client, "Report", 1, content="keep")
    client.post("/delete/1")
    row = note_row(app, 1)
    assert row is not None and row["trashed_at"] is not None
    assert row["content"] == "keep" and row["category_id"] == 1
    assert "Report" not in page(client)
    assert "Report" not in page(client, "/archive")
    assert "Report" in page(client, "/trash")


def test_delete_is_idempotent(client):
    add_note(client)
    client.post("/delete/1")
    response = client.post("/delete/1", follow_redirects=True)
    assert response.status_code == 200 and b"already in Trash" in response.data


def test_restore_from_trash(app, client):
    add_note(client)
    client.post("/pin/1")
    client.post("/delete/1")
    response = client.post("/restore/1", follow_redirects=True)
    assert b"Note restored." in response.data
    assert "Shopping" in page(client) and "Shopping" not in page(client, "/trash")
    row = note_row(app, 1)
    assert row["trashed_at"] is None and row["pinned"] == 1


def test_restoring_an_archived_then_trashed_note_returns_it_to_archive(client):
    add_note(client)
    client.post("/archive/1")
    client.post("/delete/1")
    assert "Shopping" not in page(client, "/archive")  # in Trash, not Archive
    response = client.post("/restore/1", follow_redirects=True)
    assert b"restored to Archive" in response.data
    assert "Shopping" in page(client, "/archive") and "Shopping" not in page(client)


def test_purge_deletes_permanently_only_from_trash(app, client):
    add_note(client)
    assert client.post("/purge/1").status_code == 404  # active note: refused
    client.post("/archive/1")
    assert client.post("/purge/1").status_code == 404  # archived note: refused
    assert note_row(app, 1) is not None
    client.post("/delete/1")
    response = client.post("/purge/1", follow_redirects=True)
    assert b"permanently deleted" in response.data
    assert note_row(app, 1) is None


def test_restore_requires_note_to_be_in_trash(client):
    add_note(client)
    assert client.post("/restore/1").status_code == 404
    assert client.post("/restore/999").status_code == 404


def test_trashed_notes_cannot_be_edited_pinned_or_archived(client):
    add_note(client)
    client.post("/delete/1")
    assert client.get("/edit/1").status_code == 404
    assert client.post("/edit/1", data={"title": "x", "content": ""}).status_code == 404
    assert client.post("/pin/1").status_code == 404
    assert client.post("/archive/1").status_code == 404
    assert client.post("/unarchive/1").status_code == 404


def test_empty_trash_only_removes_trashed_notes(app, client):
    for title in ("Active", "Archived", "Trash A", "Trash B"):
        add_note(client, title, "")
    client.post("/archive/2")
    client.post("/delete/3")
    client.post("/delete/4")
    response = client.post("/trash/empty", follow_redirects=True)
    assert b"Trash emptied: 2 notes permanently deleted." in response.data
    remaining = [r["title"] for r in query_db(app, "SELECT title FROM notes ORDER BY id")]
    assert remaining == ["Active", "Archived"]
    assert b"already empty" in client.post("/trash/empty", follow_redirects=True).data


def test_ids_are_not_reused_after_permanent_delete(app, client):
    add_note(client)
    client.post("/delete/1")
    client.post("/purge/1")
    add_note(client, "Second", "")
    assert note_row(app, 2)["title"] == "Second" and note_row(app, 1) is None


# ---------- list membership ----------

def test_each_note_appears_only_in_its_own_list(client):
    for title in ("Plain note", "Archived note", "Trashed note"):
        add_note(client, title, "")
    client.post("/archive/2")
    client.post("/delete/3")
    index, archive, trash = page(client), page(client, "/archive"), page(client, "/trash")
    assert "Plain note" in index and "Archived note" not in index and "Trashed note" not in index
    assert "Archived note" in archive and "Plain note" not in archive and "Trashed note" not in archive
    assert "Trashed note" in trash and "Plain note" not in trash and "Archived note" not in trash


def test_search_never_leaks_archived_or_trashed_notes(client):
    # The term appears in the title of one note and only in the *content* of the others, so a
    # missing pair of parentheses around the OR in the SQL would let hidden notes through.
    add_note(client, "Budget one", "")
    add_note(client, "Hidden archived", "budget details")
    add_note(client, "Hidden trashed", "budget details")
    client.post("/archive/2")
    client.post("/delete/3")
    html = page(client, "/?q=budget")
    assert "Budget one" in html
    assert "Hidden archived" not in html and "Hidden trashed" not in html


def test_empty_states_for_archive_and_trash(client):
    assert "Nothing archived" in page(client, "/archive")
    assert "Trash is empty" in page(client, "/trash")


# ---------- navigation ----------

@pytest.mark.parametrize("url, label", [
    ("/", "All notes"), ("/categories", "Categories"), ("/archive", "Archive"), ("/trash", "Trash"),
])
def test_active_nav_item_is_marked_current(client, url, label):
    html = page(client, url)
    current = re.findall(r'<a class="nav-item is-active" href="[^"]*" aria-current="page">\s*<svg.*?</svg><span>([^<]+)</span>', html, re.S)
    assert current == [label]


def test_nav_has_no_coming_soon_placeholders(client):
    html = page(client)
    assert "is-soon" not in html and "Soon" not in html
    for url in ("/categories", "/archive", "/trash"):
        assert f'href="{url}"' in html


def test_next_field_only_redirects_to_known_pages(client):
    add_note(client)
    add_note(client, "Second", "")
    evil = client.post("/pin/1", data={"next": "http://evil.example/"})
    assert evil.status_code == 302 and "evil.example" not in evil.headers["Location"]
    ok = client.post("/archive/2", data={"next": "trash_view"})
    assert ok.headers["Location"].endswith("/trash")


# ---------- CSRF ----------

@pytest.fixture
def csrf_app(tmp_path):
    # CSRF left ENABLED (the default); the other fixtures switch it off for convenience.
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "csrf.db")})


STATE_CHANGING = [
    "/add", "/edit/1", "/pin/1", "/delete/1", "/archive/1", "/unarchive/1",
    "/restore/1", "/purge/1", "/trash/empty", "/categories",
]


@pytest.mark.parametrize("url", STATE_CHANGING)
def test_state_changing_routes_reject_missing_csrf_token(csrf_app, url):
    response = csrf_app.test_client().post(url, data={"title": "x", "name": "x"})
    assert response.status_code == 400
    assert b"CSRF" in response.data


@pytest.mark.parametrize("url", STATE_CHANGING)
def test_state_changing_routes_reject_invalid_csrf_token(csrf_app, url):
    client = csrf_app.test_client()
    client.get("/")  # establish a session so a real token exists
    response = client.post(url, data={"title": "x", "name": "x", "csrf_token": "forged"})
    assert response.status_code == 400


@pytest.mark.parametrize("url", ["/archive/1", "/unarchive/1", "/delete/1", "/restore/1", "/purge/1", "/trash/empty", "/pin/1"])
def test_state_changing_routes_are_post_only(client, url):
    add_note(client)
    assert client.get(url).status_code == 405


def test_valid_csrf_token_allows_the_full_note_lifecycle(csrf_app):
    client = csrf_app.test_client()

    def token(url="/"):
        return re.search(r'name="csrf_token" value="([^"]+)"', client.get(url).data.decode()).group(1)

    assert client.post("/add", data={"title": "Life", "content": "", "csrf_token": token()}).status_code == 302
    for step in ("/archive/1", "/unarchive/1", "/delete/1", "/restore/1", "/delete/1", "/purge/1"):
        assert client.post(step, data={"csrf_token": token()}).status_code == 302, step
    assert query_db(csrf_app, "SELECT COUNT(*) AS n FROM notes")[0]["n"] == 0
    created = client.post("/categories", data={"name": "Reading", "csrf_token": token("/categories")})
    assert created.status_code == 302 and "Reading" in category_names(csrf_app)


def test_every_post_form_on_every_page_carries_a_csrf_token(client):
    add_with_category(client, "Active", 1)
    add_note(client, "Archived", "")
    add_note(client, "Trashed", "")
    client.post("/archive/2")
    client.post("/delete/3")
    for url in ("/", "/archive", "/trash", "/categories", "/edit/1"):
        html = page(client, url)
        assert html.count('method="post"') == html.count('name="csrf_token"') > 0, url


# ---------- migration of a pre-existing database ----------

LEGACY_SCHEMA = """
CREATE TABLE notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    content    TEXT NOT NULL DEFAULT '',
    pinned     INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""
LEGACY_NOTES = [
    (1, "hello", "first note", 0, "2026-10-20 22:16:47"),
    (3, "pinned one", "line1\nline2", 1, "2026-10-20 22:17:11"),
    (7, "<b>odd</b> title", "", 1, "2025-01-02 03:04:05"),
]
NOTE_SNAPSHOT = "SELECT id, title, content, pinned, created_at FROM notes ORDER BY id"


@pytest.fixture
def legacy_db(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    conn.executemany("INSERT INTO notes (id, title, content, pinned, created_at) VALUES (?, ?, ?, ?, ?)", LEGACY_NOTES)
    conn.commit()
    conn.close()
    return str(path)


def snapshot(path, sql=NOTE_SNAPSHOT):
    conn = sqlite3.connect(path)
    try:
        return [tuple(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def test_migration_preserves_existing_notes_exactly(legacy_db):
    before = snapshot(legacy_db)
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False, "DATABASE": legacy_db})
    assert snapshot(legacy_db) == before == [tuple(n) for n in LEGACY_NOTES]
    html = app.test_client().get("/").get_data(as_text=True)
    assert "hello" in html and "pinned one" in html and "&lt;b&gt;odd&lt;/b&gt; title" in html


def test_migration_adds_columns_defaults_and_seeds_categories(legacy_db):
    create_app({"TESTING": True, "DATABASE": legacy_db})
    columns = {r[1] for r in snapshot(legacy_db, "PRAGMA table_info(notes)")}
    assert {"category_id", "archived_at", "trashed_at"} <= columns
    assert snapshot(legacy_db, "SELECT category_id, archived_at, trashed_at FROM notes") == [(None, None, None)] * 3
    assert [r[0] for r in snapshot(legacy_db, "SELECT name FROM categories ORDER BY id")] == DEFAULTS


def test_migration_is_idempotent(legacy_db):
    create_app({"TESTING": True, "DATABASE": legacy_db})
    schema_once = snapshot(legacy_db, "SELECT name, sql FROM sqlite_master ORDER BY name")
    create_app({"TESTING": True, "DATABASE": legacy_db})
    init_db(legacy_db)
    assert snapshot(legacy_db, "SELECT name, sql FROM sqlite_master ORDER BY name") == schema_once
    assert snapshot(legacy_db, "SELECT COUNT(*) FROM categories") == [(4,)]
    assert snapshot(legacy_db) == [tuple(n) for n in LEGACY_NOTES]


def test_migration_resumes_after_a_partial_upgrade(legacy_db):
    conn = sqlite3.connect(legacy_db)
    conn.execute("ALTER TABLE notes ADD COLUMN archived_at TEXT")  # as if an earlier run stopped midway
    conn.commit()
    conn.close()
    create_app({"TESTING": True, "DATABASE": legacy_db})
    columns = [r[1] for r in snapshot(legacy_db, "PRAGMA table_info(notes)")]
    assert sorted(columns) == sorted(set(columns))  # no duplicate columns
    assert {"category_id", "archived_at", "trashed_at"} <= set(columns)
    assert snapshot(legacy_db) == [tuple(n) for n in LEGACY_NOTES]


def test_category_foreign_key_is_declared_with_set_null(legacy_db):
    create_app({"TESTING": True, "DATABASE": legacy_db})
    fks = snapshot(legacy_db, "SELECT \"table\", \"from\", on_delete FROM pragma_foreign_key_list('notes')")
    assert fks == [("categories", "category_id", "SET NULL")]


def test_new_notes_after_migration_continue_the_id_sequence(legacy_db):
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False, "DATABASE": legacy_db})
    app.test_client().post("/add", data={"title": "after", "content": ""})
    assert snapshot(legacy_db, "SELECT id FROM notes ORDER BY id") == [(1,), (3,), (7,), (8,)]


def test_migrated_legacy_notes_work_with_every_new_feature(legacy_db):
    client = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False, "DATABASE": legacy_db}).test_client()
    client.post("/edit/3", data={"title": "pinned one", "content": "line1\nline2", "category_id": "1"})
    client.post("/archive/3")
    client.post("/delete/1")
    assert "pinned one" in page(client, "/archive") and "hello" in page(client, "/trash")
    client.post("/unarchive/3")
    client.post("/restore/1")
    assert snapshot(legacy_db) == [tuple(n) for n in LEGACY_NOTES]  # round trip changes no original data
    assert snapshot(legacy_db, "SELECT category_id FROM notes WHERE id = 3") == [(1,)]
