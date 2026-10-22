"""Agent 5 tests: search, filters, sorting, tags, category management, updated_at, migration.
Every test uses a temporary database and upload folder; the real notes.db/uploads are never touched."""
import io
import re
import sqlite3
from urllib.parse import parse_qs, urlsplit

import pytest

import media
from app import MAX_TAGS_PER_NOTE, create_app, init_db

PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 56


@pytest.fixture
def app(tmp_path):
    return create_app({
        "TESTING": True, "WTF_CSRF_ENABLED": False,
        "DATABASE": str(tmp_path / "test.db"), "UPLOAD_FOLDER": str(tmp_path / "uploads"),
    })


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def csrf_app(tmp_path):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "csrf.db"), "UPLOAD_FOLDER": str(tmp_path / "u")})


def sql(app, query, params=()):
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query, params).fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


def page(client, url="/", **kw):
    return client.get(url, **kw).get_data(as_text=True)


def add(client, title, content="", category="", tags=""):
    return client.post("/add", data={"title": title, "content": content, "category_id": category, "new_tags": tags})


def ids_in_order(html):
    """Note ids in the order their cards appear (pin / unarchive / restore form actions)."""
    return [int(i) for i in re.findall(r'action="/(?:pin|unarchive|restore)/(\d+)"', html)]


def tag_names(app, note_id):
    return [r["name"] for r in sql(app, "SELECT tags.name FROM tags JOIN note_tags ON tags.id = note_tags.tag_id "
                                        "WHERE note_id = ? ORDER BY tags.id", (note_id,))]


# ---- a small library covering every state ----
@pytest.fixture
def library(client):
    add(client, "Alpha plan", "budget review", category="1", tags="ideas")            # 1 pinned, Work
    add(client, "beta notes", "meeting budget", category="1", tags="ideas, urgent")   # 2 Work
    add(client, "Gamma", "holiday", category="3", tags="urgent")                      # 3 Personal
    add(client, "delta archived", "budget", category="1", tags="ideas")               # 4 archived
    add(client, "epsilon trashed", "budget", category="1", tags="ideas")              # 5 trashed
    client.post("/pin/1")
    client.post("/archive/4")
    client.post("/delete/5")
    return client


def titles(html):
    return [t for t in ("Alpha plan", "beta notes", "Gamma", "delta archived", "epsilon trashed") if t in html]


# ======================= search =======================

def test_search_matches_title_and_content_case_insensitively(library):
    assert titles(page(library, "/?q=BUDGET")) == ["Alpha plan", "beta notes"]   # content hits
    assert titles(page(library, "/?q=gamma")) == ["Gamma"]                        # title hit


def test_all_notes_search_never_includes_archived_or_trashed(library):
    html = page(library, "/?q=budget")
    assert "delta archived" not in html and "epsilon trashed" not in html


def test_archive_and_trash_search_are_scoped_to_their_own_state(library):
    assert titles(page(library, "/archive?q=budget")) == ["delta archived"]
    assert titles(page(library, "/trash?q=budget")) == ["epsilon trashed"]


def test_like_wildcards_are_matched_literally(client):
    add(client, "Sale", "50% off")
    add(client, "Snake", "snake_case")
    add(client, "Plain", "nothing here")
    assert titles_of(page(client, "/?q=%25")) == ["Sale"]
    assert titles_of(page(client, "/?q=_")) == ["Snake"]
    assert titles_of(page(client, "/?q=50%25 o")) == ["Sale"]


def titles_of(html):
    return [t for t in ("Sale", "Snake", "Plain") if re.search(r'note-title">\s*' + t + r'\s*</h3>', html)]


def test_blank_and_overlong_queries_are_safe(library):
    assert len(titles(page(library, "/?q=%20%20"))) == 3            # whitespace-only = no search
    assert library.get("/?q=" + "x" * 5000).status_code == 200      # truncated, not an error


# ======================= filters =======================

@pytest.mark.parametrize("url, expected", [
    ("/?category=1", ["Alpha plan", "beta notes"]),
    ("/?tag=2", ["beta notes", "Gamma"]),
    ("/?pinned=1", ["Alpha plan"]),
    ("/?category=1&tag=2", ["beta notes"]),
    ("/?tag=1&pinned=1", ["Alpha plan"]),
    ("/?q=budget&category=1&tag=1&pinned=1", ["Alpha plan"]),
    ("/?q=budget&category=3", []),
    ("/?category=3&tag=2", ["Gamma"]),
])
def test_filters_combine_with_and_semantics(library, url, expected):
    assert titles(page(library, url)) == expected


def test_filters_apply_on_archive_and_trash_too(library):
    assert titles(page(library, "/archive?tag=1&category=1")) == ["delta archived"]
    assert titles(page(library, "/archive?tag=2")) == []
    assert titles(page(library, "/trash?tag=1&pinned=0")) == ["epsilon trashed"]
    assert titles(page(library, "/trash?pinned=1")) == []


@pytest.mark.parametrize("url", [
    "/?tag=999", "/?tag=abc", "/?tag=-1", "/?category=999", "/?pinned=yes", "/?pinned=2",
    "/?sort=bogus", "/?sort=trashed", "/archive?sort=trashed", "/trash?sort=bogus", "/archive?tag=999",
])
def test_invalid_filter_values_return_404(library, url):
    assert library.get(url).status_code == 404


def test_active_filters_are_visible_and_removable(library):
    html = page(library, "/?q=budget&category=1&tag=1&pinned=1&sort=title")
    pills = html[html.index('class="active-filters"'):]
    for label in ("Search: “budget”", "Category: Work", "Tag: ideas", "Pinned only", "Sorted: Title (A–Z)", "Reset all filters"):
        assert label in pills, label
    # removing one filter keeps the others
    remove_tag = re.search(r'href="([^"]+)">Tag: ideas', pills).group(1).replace("&amp;", "&")
    assert "tag=" not in remove_tag and "category=1" in remove_tag and "pinned=1" in remove_tag and "q=budget" in remove_tag
    assert 'href="/">Reset all filters' in pills
    assert "active-filters" not in page(library, "/")                # nothing active -> no pill row


def test_category_chips_keep_the_other_filters(library):
    html = page(library, "/?tag=2&sort=title")
    chips = re.findall(r'<a class="chip[^"]*" href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)
    href = next(h for h, inner in chips if "Personal" in inner).replace("&amp;", "&")
    assert "tag=2" in href and "sort=title" in href and "category=3" in href
    all_href = next(h for h, inner in chips if inner.strip() == "All").replace("&amp;", "&")
    assert "tag=2" in all_href and "category=" not in all_href


def test_filter_form_controls_are_labelled(library):
    html = page(library)
    for field in ("q", "f-tag", "f-sort"):
        assert f'for="{field}"' in html and f'id="{field}"' in html
    assert 'name="pinned"' in html and "Pinned only" in html
    assert 'for="f-category"' in page(library, "/archive")           # Archive/Trash get a category select


def test_empty_states_for_filters(library):
    assert "No notes match these filters" in page(library, "/?category=3&tag=1")
    assert "No notes in Work yet" not in page(library, "/?category=1&tag=2&pinned=1")
    assert "No archived notes match these filters" in page(library, "/archive?tag=2")
    assert "No notes in Trash match these filters" in page(library, "/trash?pinned=1")


# ======================= sorting =======================

@pytest.fixture
def sorted_notes(client, app):
    for title in ("T-zulu", "T-Alpha", "T-alpha", "T-Mike"):
        add(client, title)
    for note_id, created, updated in ((1, "2026-01-01 00:00:00", None), (2, "2026-01-03 00:00:00", "2026-02-01 00:00:00"),
                                      (3, "2026-01-03 00:00:00", None), (4, "2026-01-02 00:00:00", None)):
        sql(app, "UPDATE notes SET created_at = ?, updated_at = ? WHERE id = ?", (created, updated, note_id))
    client.post("/pin/4")
    return client


@pytest.mark.parametrize("sort, expected", [
    ("", [4, 3, 2, 1]),            # default "Pinned first": pinned, then newest id
    ("pinned", [4, 3, 2, 1]),
    ("created", [3, 2, 4, 1]),     # 2 and 3 tie on created_at -> higher id first
    ("updated", [2, 3, 4, 1]),     # NULL updated_at falls back to created_at
    ("title", [2, 3, 4, 1]),       # T-Alpha / T-alpha tie (NOCASE) -> lower id first
])
def test_each_sort_order_is_exact(sorted_notes, sort, expected):
    url = "/" + (f"?sort={sort}" if sort else "")
    assert ids_in_order(page(sorted_notes, url)) == expected


def test_sort_is_deterministic_across_repeated_requests(sorted_notes):
    for sort in ("created", "updated", "title", "pinned"):
        first = ids_in_order(page(sorted_notes, f"/?sort={sort}"))
        assert all(ids_in_order(page(sorted_notes, f"/?sort={sort}")) == first for _ in range(3))


def test_non_default_sort_is_one_flat_list_and_default_groups_pins(sorted_notes):
    assert 'id="pinned-heading"' in page(sorted_notes, "/")
    flat = page(sorted_notes, "/?sort=title")
    assert 'id="pinned-heading"' not in flat and "Sorted by title (a–z)" in flat


def test_sort_combines_with_filters(client, app):
    for title, tags in (("T-b", "x"), ("T-a", "x"), ("T-c", "")):
        add(client, title, tags=tags)
    assert ids_in_order(page(client, "/?tag=1&sort=title")) == [2, 1]


def test_trash_defaults_to_recently_trashed_and_supports_other_sorts(client, app):
    for title in ("T-b", "T-a"):
        add(client, title)
    client.post("/delete/1")
    client.post("/delete/2")
    sql(app, "UPDATE notes SET trashed_at = '2026-03-01 00:00:00' WHERE id = 1")
    sql(app, "UPDATE notes SET trashed_at = '2026-03-02 00:00:00' WHERE id = 2")
    assert ids_in_order(page(client, "/trash")) == [2, 1]
    assert ids_in_order(page(client, "/trash?sort=title")) == [2, 1]      # T-a (id 2) before T-b (id 1)
    assert ids_in_order(page(client, "/trash?sort=created")) == [2, 1]


# ======================= updated_at =======================

OLD = "2000-01-01 00:00:00"


def updated(app, note_id=1):
    return sql(app, "SELECT updated_at FROM notes WHERE id = ?", (note_id,))[0][0]


def test_new_and_untouched_notes_have_no_updated_at(app, client):
    add(client, "N")
    assert updated(app) is None


def test_genuine_edits_bump_updated_at(app, client):
    add(client, "N", "body", category="1")
    for data in ({"title": "N2", "content": "body"}, {"title": "N2", "content": "new body"},
                 {"title": "N2", "content": "new body", "category_id": "2"},
                 {"title": "N2", "content": "new body", "category_id": "2", "tags_submitted": "1", "new_tags": "fresh"}):
        sql(app, "UPDATE notes SET updated_at = ?", (OLD,))
        client.post("/edit/1", data=data)
        assert updated(app) > OLD, data


def test_noop_save_and_other_actions_do_not_bump_updated_at(app, client):
    add(client, "N", "body", category="1")
    sql(app, "UPDATE notes SET updated_at = ?", (OLD,))
    assert b"No changes to save." in client.post(
        "/edit/1", data={"title": "N", "content": "body", "category_id": "1"}, follow_redirects=True).data
    for action in ("/pin/1", "/archive/1", "/unarchive/1", "/delete/1", "/restore/1"):
        client.post(action)
    assert updated(app) == OLD


def test_updated_sort_reflects_a_real_edit(client, app):
    for title in ("T-a", "T-b", "T-c"):
        add(client, title)
    client.post("/edit/1", data={"title": "T-a", "content": "changed"})
    sql(app, "UPDATE notes SET updated_at = '2999-01-01 00:00:00' WHERE id = 1")
    assert ids_in_order(page(client, "/?sort=updated"))[0] == 1


# ======================= tags =======================

def test_create_tag_normalises_and_rejects_duplicates(app, client):
    client.post("/tags", data={"name": "  #  Big   Ideas "})
    assert [r["name"] for r in sql(app, "SELECT name FROM tags")] == ["Big Ideas"]
    for dup in ("big ideas", "BIG  IDEAS", "#Big Ideas"):
        assert b"already exists" in client.post("/tags", data={"name": dup}, follow_redirects=True).data
    assert sql(app, "SELECT COUNT(*) FROM tags")[0][0] == 1


@pytest.mark.parametrize("name, message", [
    ("", b"Tag name is required."), ("   ", b"Tag name is required."), ("#", b"Tag name is required."),
    ("x" * 31, b"30 characters or fewer"), ("a,b", b"invalid characters"), ("bad\x00name", b"invalid characters"),
])
def test_invalid_tag_names_are_rejected(app, client, name, message):
    assert message in client.post("/tags", data={"name": name}, follow_redirects=True).data
    assert sql(app, "SELECT COUNT(*) FROM tags")[0][0] == 0
    client.post("/tags", data={"name": "y" * 30})
    assert sql(app, "SELECT COUNT(*) FROM tags")[0][0] == 1          # exactly 30 is allowed


def test_tag_names_are_escaped(client):
    client.post("/tags", data={"name": "<b>x</b>"})
    html = page(client, "/tags")
    assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html


def test_assign_tags_when_adding_a_note(app, client):
    add(client, "N", tags="one, Two , #three,one")
    assert tag_names(app, 1) == ["one", "Two", "three"]


def test_one_note_many_tags_and_one_tag_many_notes(app, client):
    add(client, "A", tags="shared, only-a")
    add(client, "B", tags="SHARED")                   # reuses the existing tag, no duplicate
    assert sql(app, "SELECT COUNT(*) FROM tags")[0][0] == 2
    assert tag_names(app, 1) == ["shared", "only-a"] and tag_names(app, 2) == ["shared"]
    assert ids_in_order(page(client, "/?tag=1")) == [2, 1]


def edit_tags(client, note_id, tag_ids=(), new="", title="N", content=""):
    return client.post(f"/edit/{note_id}", data={
        "title": title, "content": content, "tags_submitted": "1", "tag_ids": list(tag_ids), "new_tags": new})


def test_edit_assigns_and_removes_tags(app, client):
    add(client, "N", tags="a, b")
    edit_tags(client, 1, tag_ids=["1"], new="c")            # keep a, drop b, add c
    assert tag_names(app, 1) == ["a", "c"]
    edit_tags(client, 1)                                     # uncheck everything
    assert tag_names(app, 1) == []
    assert sql(app, "SELECT COUNT(*) FROM tags")[0][0] == 3  # the tags themselves remain


def test_edit_without_tag_controls_keeps_existing_tags(app, client):
    add(client, "N", tags="a, b")
    client.post("/edit/1", data={"title": "Renamed", "content": ""})
    assert tag_names(app, 1) == ["a", "b"]


def test_edit_page_preselects_current_tags(client):
    add(client, "N", tags="a, b")
    add(client, "M", tags="b")
    html = page(client, "/edit/2")
    assert re.search(r'value="2" checked><span>b</span>', html) and not re.search(r'value="1" checked', html)


def test_too_many_tags_rejected_without_changes(app, client):
    many = ",".join(f"t{i}" for i in range(MAX_TAGS_PER_NOTE + 1))
    assert b"at most 10 tags" in client.post("/add", data={"title": "N", "new_tags": many}, follow_redirects=True).data
    assert sql(app, "SELECT COUNT(*) FROM notes")[0][0] == 0 and sql(app, "SELECT COUNT(*) FROM tags")[0][0] == 0
    add(client, "N", tags=",".join(f"t{i}" for i in range(MAX_TAGS_PER_NOTE)))     # exactly 10 is fine
    assert len(tag_names(app, 1)) == 10
    resp = edit_tags(client, 1, tag_ids=["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"], new="extra")
    assert b"at most 10 tags" in resp.data and len(tag_names(app, 1)) == 10


def test_retyping_existing_tags_in_another_case_does_not_count_twice(app, client):
    names = [f"t{i}" for i in range(MAX_TAGS_PER_NOTE)]
    add(client, "N", tags=",".join(names))
    # all ten stay checked AND the same names are typed again in capitals: still ten tags, no error
    resp = edit_tags(client, 1, tag_ids=[str(i) for i in range(1, 11)], new="T0, T1", title="N", content="x")
    assert resp.status_code == 302 and len(tag_names(app, 1)) == 10
    assert sql(app, "SELECT COUNT(*) FROM tags")[0][0] == 10


@pytest.mark.parametrize("bad", ["999", "abc", "-1", "1.5"])
def test_invalid_tag_ids_rejected_and_note_unchanged(app, client, bad):
    add(client, "N", "body", tags="a")
    resp = edit_tags(client, 1, tag_ids=[bad], title="Changed", content="x")
    assert b"Choose valid tags." in resp.data
    row = sql(app, "SELECT title, content FROM notes")[0]
    assert (row["title"], row["content"]) == ("N", "body") and tag_names(app, 1) == ["a"]


def test_invalid_tag_name_in_edit_keeps_typed_text_and_changes_nothing(app, client):
    add(client, "N", tags="a")
    resp = edit_tags(client, 1, tag_ids=["1"], new="x" * 40, title="Changed")
    assert b"30 characters or fewer" in resp.data and ("x" * 40).encode() in resp.data
    assert sql(app, "SELECT title FROM notes")[0][0] == "N"


def test_tag_chips_show_on_cards_and_link_to_the_filter(library):
    html = page(library)
    assert 'href="/?tag=1"' in html and "<ul class=\"tag-list\"" in html
    assert 'href="/archive?tag=1"' in page(library, "/archive")
    assert 'href="/trash?tag=1"' in page(library, "/trash")


def test_delete_tag_keeps_notes_and_removes_only_the_links(app, library):
    assert library.get("/tags/1/delete").status_code == 200
    assert sql(app, "SELECT COUNT(*) FROM tags")[0][0] == 2            # GET never deletes
    notes_before = sql(app, "SELECT id, title, content, pinned, created_at, category_id FROM notes ORDER BY id")
    resp = library.post("/tags/1/delete", follow_redirects=True)
    assert b"Its notes were kept." in resp.data
    assert [r["name"] for r in sql(app, "SELECT name FROM tags")] == ["urgent"]
    assert sql(app, "SELECT COUNT(*) FROM note_tags WHERE tag_id = 1")[0][0] == 0
    assert sql(app, "SELECT id, title, content, pinned, created_at, category_id FROM notes ORDER BY id") == notes_before
    assert library.get("/?tag=1").status_code == 404                    # the filter no longer exists


def test_confirm_pages_state_the_consequences(library):
    html = page(library, "/tags/1/delete")
    assert "Delete tag “ideas”?" in html and "removed from 4 notes" in html
    assert "kept and become uncategorized" in page(library, "/categories/1/delete")


@pytest.mark.parametrize("url", ["/tags/999/delete", "/categories/999/delete", "/tags/abc/delete"])
def test_missing_targets_return_404_for_get_and_post(client, url):
    assert client.get(url).status_code == 404 and client.post(url).status_code == 404


def test_permanent_delete_removes_links_but_not_tags_and_trash_keeps_them(app, library):
    library.post("/restore/5")
    library.post("/delete/5")
    assert tag_names(app, 5) == ["ideas"]                                # Trash keeps tags
    library.post("/purge/5")
    assert sql(app, "SELECT COUNT(*) FROM note_tags WHERE note_id = 5")[0][0] == 0
    assert sql(app, "SELECT COUNT(*) FROM tags")[0][0] == 2
    library.post("/delete/4")
    library.post("/trash/empty")
    assert sql(app, "SELECT COUNT(*) FROM note_tags WHERE note_id IN (4, 5)")[0][0] == 0


def test_tags_page_counts_active_notes_only(library):
    html = page(library, "/tags")
    ideas = re.search(r'<span>ideas</span></span>\s*<span class="category-count">(\d+)', html)
    assert ideas.group(1) == "2"                                         # notes 1,2 (4 archived, 5 trashed)


# ======================= category management =======================

def category(app, category_id):
    rows = sql(app, "SELECT name FROM categories WHERE id = ?", (category_id,))
    return rows[0][0] if rows else None


def test_rename_category_keeps_id_and_note_assignments(app, library):
    before = sql(app, "SELECT id, category_id FROM notes ORDER BY id")
    assert b"renamed to" in library.post("/categories/1/rename", data={"name": "  Job   Stuff "}, follow_redirects=True).data
    assert category(app, 1) == "Job Stuff"
    assert sql(app, "SELECT id, category_id FROM notes ORDER BY id") == before
    assert "Job Stuff" in page(library, "/?category=1")


def test_rename_may_change_only_the_case_of_its_own_name(app, client):
    client.post("/categories/1/rename", data={"name": "WORK"})
    assert category(app, 1) == "WORK"


@pytest.mark.parametrize("name, message", [
    ("", b"Category name is required."), ("   ", b"Category name is required."),
    ("x" * 41, b"40 characters or fewer"), ("bad\x00", b"invalid characters"),
    ("business", b"already exists"), ("PERSONAL ", b"already exists"),
])
def test_rename_validation_and_duplicates(app, client, name, message):
    assert message in client.post("/categories/1/rename", data={"name": name}, follow_redirects=True).data
    assert category(app, 1) == "Work"


def test_delete_category_keeps_every_note_in_every_state(app, library):
    library.post("/pin/2")
    before = sql(app, "SELECT id, title, content, pinned, created_at, archived_at, trashed_at FROM notes ORDER BY id")
    assert library.get("/categories/1/delete").status_code == 200
    assert category(app, 1) == "Work"                                    # GET never deletes
    assert b"Its notes were kept." in library.post("/categories/1/delete", follow_redirects=True).data
    assert category(app, 1) is None
    assert sql(app, "SELECT id, title, content, pinned, created_at, archived_at, trashed_at FROM notes ORDER BY id") == before
    assert [r[0] for r in sql(app, "SELECT category_id FROM notes ORDER BY id")] == [None, None, 3, None, None]
    assert library.get("/?category=1").status_code == 404
    assert titles(page(library)) == ["Alpha plan", "beta notes", "Gamma"]


def test_category_page_has_rename_and_delete_controls(client):
    html = page(client, "/categories")
    assert 'action="/categories/1/rename"' in html and 'href="/categories/1/delete"' in html
    assert 'for="rename-1"' in html and 'id="rename-1"' in html


def test_deleted_or_renamed_default_categories_are_not_reseeded(app, tmp_path):
    client = app.test_client()
    client.post("/categories/1/delete")                       # Work
    client.post("/categories/2/rename", data={"name": "Biz"})  # Business
    for _ in range(2):
        create_app({"TESTING": True, "DATABASE": app.config["DATABASE"], "UPLOAD_FOLDER": str(tmp_path / "u")})
    init_db(app.config["DATABASE"])
    assert [r[0] for r in sql(app, "SELECT name FROM categories ORDER BY id")] == ["Biz", "Personal", "Homework"]


# ======================= CSRF =======================

NEW_POSTS = ["/categories/1/rename", "/categories/1/delete", "/tags", "/tags/1/delete"]


@pytest.mark.parametrize("url", NEW_POSTS)
def test_new_state_changing_routes_reject_missing_and_invalid_tokens(csrf_app, url):
    client = csrf_app.test_client()
    assert client.post(url, data={"name": "x"}).status_code == 400
    client.get("/")
    assert client.post(url, data={"name": "x", "csrf_token": "forged"}).status_code == 400


@pytest.mark.parametrize("url", ["/tags/1/delete", "/categories/1/delete"])
def test_new_post_routes_reject_get_for_actions(client, url):
    client.post("/tags", data={"name": "t"})
    client.get(url)                                           # GET = confirmation page only
    assert sql_count(client) == (1, 4)


def sql_count(client):
    app = client.application
    return sql(app, "SELECT COUNT(*) FROM tags")[0][0], sql(app, "SELECT COUNT(*) FROM categories")[0][0]


def test_valid_tokens_allow_category_and_tag_management(csrf_app):
    client = csrf_app.test_client()

    def token(url):
        return re.search(r'name="csrf_token" value="([^"]+)"', client.get(url).get_data(as_text=True)).group(1)

    assert client.post("/tags", data={"name": "t", "csrf_token": token("/tags")}).status_code == 302
    assert client.post("/categories/1/rename", data={"name": "Job", "csrf_token": token("/categories")}).status_code == 302
    assert client.post("/tags/1/delete", data={"csrf_token": token("/tags/1/delete")}).status_code == 302
    assert client.post("/categories/1/delete", data={"csrf_token": token("/categories/1/delete")}).status_code == 302
    assert category(csrf_app, 1) is None and sql(csrf_app, "SELECT COUNT(*) FROM tags")[0][0] == 0


def test_every_post_form_on_the_new_pages_carries_a_csrf_token(library):
    for url in ("/", "/archive", "/trash", "/tags", "/categories", "/edit/1", "/tags/1/delete",
                "/categories/1/delete", "/?tag=1&sort=title"):
        html = page(library, url)
        assert html.count('method="post"') == html.count('name="csrf_token"') > 0, url


# ======================= filters survive note actions =======================

FILTERED = "/?tag=1&sort=title"


def location(resp):
    return resp.headers["Location"]


def test_note_actions_return_to_the_filtered_view(library):
    assert location(library.post("/pin/2", data={"return_to": FILTERED})).endswith(FILTERED)
    assert location(library.post("/archive/2", data={"return_to": "/?q=budget&pinned=1"})).endswith("/?q=budget&pinned=1")
    assert location(library.post("/unarchive/2", data={"return_to": "/archive?tag=1"})).endswith("/archive?tag=1")
    assert location(library.post("/delete/2", data={"return_to": FILTERED})).endswith(FILTERED)
    assert location(library.post("/restore/2", data={"return_to": "/trash?q=beta"})).endswith("/trash?q=beta")


@pytest.mark.parametrize("evil", [
    "//evil.example/", "https://evil.example/", "/\\evil.example", "/media", "/edit/1", "javascript:alert(1)",
    "/?x=1\r\nSet-Cookie: a=b", "relative/path", "/" + "a" * 700,
])
def test_return_to_cannot_redirect_off_the_list_pages(library, evil):
    target = location(library.post("/pin/2", data={"return_to": evil}))
    assert "evil" not in target and "Set-Cookie" not in target and target.endswith("/")


def test_cards_carry_return_to_and_edit_round_trips(library):
    html = page(library, FILTERED)
    assert 'name="return_to" value="/?tag=1&amp;sort=title"' in html
    link = re.search(r'href="(/edit/1\?[^"]*)"', html).group(1)
    assert parse_qs(urlsplit(link).query)["return_to"] == [FILTERED]
    edit_page = page(library, "/edit/1", query_string={"return_to": FILTERED})
    assert edit_page.count('href="/?tag=1&amp;sort=title"') == 2           # back link + Cancel
    saved = library.post("/edit/1", data={"title": "Alpha plan", "content": "x", "return_to": FILTERED})
    assert location(saved).endswith(FILTERED)
    assert location(library.post("/edit/1", data={"title": "Alpha plan", "content": "x", "return_to": "//evil.example"})).endswith("/")


# ======================= migration & Agent 4 compatibility =======================

AGENT4_DDL = """
CREATE TABLE categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                         created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE notes (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, content TEXT NOT NULL DEFAULT '',
    pinned INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL, archived_at TEXT, trashed_at TEXT);
CREATE TABLE media (id INTEGER PRIMARY KEY AUTOINCREMENT, note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    storage_key TEXT NOT NULL UNIQUE, original_name TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('image','audio')),
    mime_type TEXT NOT NULL, size_bytes INTEGER NOT NULL CHECK (size_bytes > 0), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
"""
KEY = "ab" * 16 + ".png"
NOTE_COLS = "id, title, content, pinned, created_at, category_id, archived_at, trashed_at"


@pytest.fixture
def agent4_db(tmp_path):
    """A database exactly as Agent 4 leaves it: seeded categories, notes in every state, one attachment."""
    path = tmp_path / "agent4.db"
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / KEY).write_bytes(PNG)
    conn = sqlite3.connect(path)
    conn.executescript(AGENT4_DDL)
    conn.executemany("INSERT INTO categories (name) VALUES (?)", [("Work",), ("Business",), ("Personal",), ("Homework",), ("Custom",)])
    conn.executemany(
        "INSERT INTO notes (id, title, content, pinned, created_at, category_id, archived_at, trashed_at) VALUES (?,?,?,?,?,?,?,?)", [
            (1, "active pinned", "body one", 1, "2026-01-01 10:00:00", 1, None, None),
            (4, "archived", "body two", 0, "2026-01-02 10:00:00", 5, "2026-02-01 00:00:00", None),
            (9, "trashed", "body three", 0, "2026-01-03 10:00:00", None, None, "2026-03-01 00:00:00"),
        ])
    conn.execute("INSERT INTO media (note_id, storage_key, original_name, kind, mime_type, size_bytes) VALUES (1, ?, 'pic.png', 'image', 'image/png', ?)", (KEY, len(PNG)))
    conn.commit()
    conn.close()
    return str(path), str(uploads)


def migrate(agent4_db):
    path, uploads = agent4_db
    return create_app({"TESTING": True, "WTF_CSRF_ENABLED": False, "DATABASE": path, "UPLOAD_FOLDER": uploads})


def dump(path, query):
    conn = sqlite3.connect(path)
    try:
        return [tuple(r) for r in conn.execute(query)]
    finally:
        conn.close()


def test_agent4_database_migrates_without_changing_any_existing_data(agent4_db):
    path, _ = agent4_db
    notes, cats, media_rows = (dump(path, q) for q in (
        f"SELECT {NOTE_COLS} FROM notes ORDER BY id", "SELECT id, name FROM categories ORDER BY id", "SELECT * FROM media"))
    migrate(agent4_db)
    assert dump(path, f"SELECT {NOTE_COLS} FROM notes ORDER BY id") == notes
    assert dump(path, "SELECT id, name FROM categories ORDER BY id") == cats          # incl. "Custom", no extras
    assert dump(path, "SELECT * FROM media") == media_rows
    assert dump(path, "SELECT updated_at FROM notes") == [(None,)] * 3
    names = {r[0] for r in dump(path, "SELECT name FROM sqlite_master WHERE type IN ('table','index')")}
    assert {"tags", "note_tags", "app_meta", "idx_note_tags_tag"} <= names


def test_migration_is_idempotent_and_adds_no_duplicates(agent4_db):
    path, _ = agent4_db
    migrate(agent4_db)
    schema = dump(path, "SELECT name, sql FROM sqlite_master ORDER BY name")
    migrate(agent4_db)
    init_db(path)
    assert dump(path, "SELECT name, sql FROM sqlite_master ORDER BY name") == schema
    assert dump(path, "SELECT COUNT(*) FROM categories") == [(5,)]
    assert dump(path, "SELECT key, value FROM app_meta") == [("default_categories_seeded", "1")]
    cols = [r[1] for r in dump(path, "PRAGMA table_info(notes)")]
    assert cols.count("updated_at") == 1 and len(cols) == len(set(cols))


def test_note_tags_declares_cascading_foreign_keys_and_a_composite_key(agent4_db):
    migrate(agent4_db)
    fks = dump(agent4_db[0], "SELECT \"table\", \"from\", on_delete FROM pragma_foreign_key_list('note_tags') ORDER BY \"from\"")
    assert fks == [("notes", "note_id", "CASCADE"), ("tags", "tag_id", "CASCADE")]
    conn = sqlite3.connect(agent4_db[0])
    conn.execute("INSERT INTO tags (name) VALUES ('t')")
    conn.execute("INSERT INTO note_tags VALUES (1, 1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO note_tags VALUES (1, 1)")                         # same tag twice on a note
    conn.close()


def test_migrated_agent4_data_works_with_every_view_and_media_still_streams(agent4_db):
    client = migrate(agent4_db).test_client()
    assert titles_in(page(client), ("active pinned", "archived", "trashed")) == ["active pinned"]
    assert titles_in(page(client, "/archive"), ("active pinned", "archived", "trashed")) == ["archived"]
    assert titles_in(page(client, "/trash"), ("active pinned", "archived", "trashed")) == ["trashed"]
    assert titles_in(page(client, "/archive?category=5"), ("archived",)) == ["archived"]
    resp = client.get("/media/1/file")
    assert resp.status_code == 200 and resp.data == PNG and resp.mimetype == "image/png"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def titles_in(html, names):
    return [n for n in names if n in html]


def test_agent4_cleanup_still_works_with_tags_and_attachments(agent4_db, tmp_path):
    path, uploads = agent4_db
    app = migrate(agent4_db)
    client = app.test_client()
    client.post("/edit/1", data={"title": "active pinned", "content": "body one", "tags_submitted": "1", "new_tags": "keep"})
    client.post("/delete/1")
    assert (tmp_path / "uploads" / KEY).exists()                        # Trash must not destroy attachments
    assert client.get("/media/1/file").status_code == 404               # ...but hides them
    client.post("/restore/1")
    assert client.get("/media/1/file").status_code == 200               # Restore brings them back
    client.post("/delete/1")
    client.post("/trash/empty")
    assert not (tmp_path / "uploads" / KEY).exists()                    # Empty Trash removes the file
    assert dump(path, "SELECT COUNT(*) FROM media") == [(0,)] and dump(path, "SELECT COUNT(*) FROM note_tags") == [(0,)]
    assert dump(path, "SELECT name FROM tags") == [("keep",)]


def test_uploads_still_work_alongside_tags(app, client):
    add(client, "N", tags="a")
    data = {"files": [(io.BytesIO(PNG), "p.png", "image/png")]}
    client.post("/notes/1/media", data=data, content_type="multipart/form-data")
    assert sql(app, "SELECT COUNT(*) FROM media")[0][0] == 1 and tag_names(app, 1) == ["a"]
    assert media.KEY_RE.fullmatch(sql(app, "SELECT storage_key FROM media")[0][0])


def test_pre_categories_database_migrates_through_every_stage(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, content TEXT NOT NULL DEFAULT '', "
                 "pinned INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("INSERT INTO notes (id, title, content, pinned, created_at) VALUES (7, 'old', 'c', 1, '2025-05-05 05:05:05')")
    conn.commit()
    conn.close()
    app = create_app({"TESTING": True, "DATABASE": str(path), "UPLOAD_FOLDER": str(tmp_path / "u")})
    assert dump(str(path), "SELECT id, title, content, pinned, created_at, updated_at FROM notes") == [(7, "old", "c", 1, "2025-05-05 05:05:05", None)]
    assert [r[0] for r in dump(str(path), "SELECT name FROM categories ORDER BY id")] == ["Work", "Business", "Personal", "Homework"]
    assert "old" in app.test_client().get("/").get_data(as_text=True)
