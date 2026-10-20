import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db")})
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
    add_note(client)
    response = client.post("/delete/1", follow_redirects=True)
    assert b"Note deleted." in response.data
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
