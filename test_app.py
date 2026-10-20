import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "DATABASE": str(tmp_path / "test.db"),
    })
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
