"""Media attachment tests (Agent 4). Every test uses a temporary database and upload directory."""
import io
import os
import re
import sqlite3

import pytest

import media
from app import MAX_ATTACHMENTS_PER_NOTE, MAX_FILES_PER_UPLOAD, create_app, init_db

MIB = 1024 * 1024
HEADERS = {
    "png": (b"\x89PNG\r\n\x1a\n", "x.png", "image", "image/png"),
    "jpg": (b"\xff\xd8\xff\xe0\x00\x10JFIF", "x.jpg", "image", "image/jpeg"),
    "gif": (b"GIF89a\x01\x00\x01\x00", "x.gif", "image", "image/gif"),
    "webp": (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "x.webp", "image", "image/webp"),
    "mp3": (b"ID3\x03\x00\x00\x00\x00\x00\x00", "x.mp3", "audio", "audio/mpeg"),
    "wav": (b"RIFF\x00\x00\x00\x00WAVEfmt ", "x.wav", "audio", "audio/wav"),
    "ogg": (b"OggS\x00\x02\x00\x00", "x.ogg", "audio", "audio/ogg"),
    "flac": (b"fLaC\x00\x00\x00\x22", "x.flac", "audio", "audio/flac"),
    "m4a": (b"\x00\x00\x00\x20ftypM4A \x00\x00", "x.m4a", "audio", "audio/mp4"),
}


def blob(fmt, size=64):
    head = HEADERS[fmt][0]
    return head + b"\x01" * (size - len(head))


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
    return create_app({
        "TESTING": True, "SECRET_KEY": "csrf-secret",
        "DATABASE": str(tmp_path / "csrf.db"), "UPLOAD_FOLDER": str(tmp_path / "uploads"),
    })


def add_note(client, title="Holiday"):
    client.post("/add", data={"title": title, "content": "body"})


def upload(client, note_id, *files, follow=True):
    data = {"files": [(io.BytesIO(content), name) for name, content in files]}
    return client.post(f"/notes/{note_id}/media", data=data, content_type="multipart/form-data",
                       follow_redirects=follow)


def db_rows(app, sql, params=()):
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def stored(app):
    root = app.config["UPLOAD_FOLDER"]
    return sorted(os.listdir(root)) if os.path.isdir(root) else []


# ---- migration and setup ----

PRE_MEDIA_SCHEMA = """
CREATE TABLE notes (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, content TEXT NOT NULL DEFAULT '',
  pinned INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  category_id INTEGER, archived_at TEXT, trashed_at TEXT);
CREATE TABLE categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
INSERT INTO categories (id, name) VALUES (3, 'Work');
"""
OLD_ROWS = [
    (2, "Plain", "a", 0, "2024-01-01 01:02:03", None, None, None),
    (7, "Pinned work", "b", 1, "2024-02-02 02:03:04", 3, None, None),
    (9, "Archived", "c", 0, "2024-03-03 03:04:05", None, "2024-04-01 00:00:00", None),
    (12, "Trashed", "d", 0, "2024-05-05 05:06:07", None, None, "2024-06-01 00:00:00"),
]


def test_migration_adds_media_and_preserves_existing_data(tmp_path):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript(PRE_MEDIA_SCHEMA)
    conn.executemany("INSERT INTO notes (id, title, content, pinned, created_at, category_id, archived_at, trashed_at) "
                     "VALUES (?,?,?,?,?,?,?,?)", OLD_ROWS)
    conn.commit()
    conn.close()
    for _ in range(3):
        init_db(path)
    conn = sqlite3.connect(path)
    assert [tuple(r) for r in conn.execute(
        "SELECT id, title, content, pinned, created_at, category_id, archived_at, trashed_at FROM notes ORDER BY id")] == OLD_ROWS
    assert [r[1] for r in conn.execute("PRAGMA table_info(media)")] == [
        "id", "note_id", "storage_key", "original_name", "kind", "mime_type", "size_bytes", "created_at"]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()


def test_startup_does_not_create_upload_folder_and_init_is_repeatable(tmp_path):
    uploads = tmp_path / "uploads"
    for _ in range(2):
        create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.db"), "UPLOAD_FOLDER": str(uploads)})
    assert not uploads.exists()


def test_deleting_a_note_row_cascades_to_media_rows(app, client):
    add_note(client)
    upload(client, 1, ("a.png", blob("png")))
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM notes WHERE id = 1")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM media").fetchone()[0] == 0
    conn.close()


def test_storage_key_is_unique(app, client):
    add_note(client)
    upload(client, 1, ("a.png", blob("png")))
    key = db_rows(app, "SELECT storage_key FROM media")[0][0]
    conn = sqlite3.connect(app.config["DATABASE"])
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO media (note_id, storage_key, original_name, kind, mime_type, size_bytes) "
                     "VALUES (1, ?, 'dup.png', 'image', 'image/png', 10)", (key,))
    conn.close()


# ---- successful uploads ----

def test_image_upload_metadata_storage_and_retrieval(app, client):
    add_note(client)
    data = blob("png", 500)
    response = upload(client, 1, ("holiday photo.png", data))
    assert b"1 attachment added." in response.data
    row = db_rows(app, "SELECT * FROM media")[0]
    assert (row["note_id"], row["original_name"], row["kind"], row["mime_type"], row["size_bytes"]) == (
        1, "holiday photo.png", "image", "image/png", 500)
    assert re.fullmatch(r"[0-9a-f]{32}\.png", row["storage_key"])
    assert stored(app) == [row["storage_key"]]
    file_response = client.get(f"/media/{row['id']}/file")
    assert file_response.status_code == 200 and file_response.data == data
    assert file_response.headers["Content-Type"] == "image/png"
    assert file_response.headers["X-Content-Type-Options"] == "nosniff"
    csp = file_response.headers["Content-Security-Policy"]
    assert "sandbox allow-same-origin" in csp and "media-src 'self'" in csp
    assert file_response.headers["Content-Disposition"].startswith("inline")
    assert row["storage_key"] not in client.get("/media").data.decode()  # key never exposed to pages


def test_audio_upload_and_range_streaming(app, client):
    add_note(client)
    data = blob("mp3", 1000)
    upload(client, 1, ("memo.mp3", data))
    mid = db_rows(app, "SELECT id FROM media")[0][0]
    partial = client.get(f"/media/{mid}/file", headers={"Range": "bytes=0-9"})
    assert partial.status_code == 206 and partial.data == data[:10]
    assert partial.headers["Content-Type"] == "audio/mpeg"
    assert b"<audio" in client.get(f"/media/{mid}").data


def test_every_supported_format_is_accepted_with_verified_mime(app, client):
    add_note(client)
    for fmt, (_, name, kind, mime) in HEADERS.items():
        upload(client, 1, (name, blob(fmt)))
        row = db_rows(app, "SELECT kind, mime_type FROM media ORDER BY id DESC LIMIT 1")[0]
        assert (row["kind"], row["mime_type"]) == (kind, mime), fmt
    assert len(stored(app)) == len(HEADERS)


def test_multiple_files_in_one_request_and_partial_success(app, client):
    add_note(client)
    response = upload(client, 1, ("a.png", blob("png")), ("b.mp3", blob("mp3")), ("notes.txt", b"hello"))
    assert b"2 attachments added." in response.data
    assert "notes.txt” is not a supported image or audio file." in response.data.decode()
    assert len(db_rows(app, "SELECT id FROM media")) == 2 and len(stored(app)) == 2


def test_browser_content_type_is_ignored(app, client):
    add_note(client)
    data = {"files": (io.BytesIO(blob("png")), "pic.png", "text/html")}
    client.post("/notes/1/media", data=data, content_type="multipart/form-data")
    assert db_rows(app, "SELECT mime_type FROM media")[0][0] == "image/png"
    data = {"files": (io.BytesIO(b"<script>alert(1)</script>"), "pic.png", "image/png")}
    client.post("/notes/1/media", data=data, content_type="multipart/form-data")
    assert len(db_rows(app, "SELECT id FROM media")) == 1


# ---- size limits ----

def test_image_size_boundary(app, client):
    add_note(client)
    assert b"1 attachment added." in upload(client, 1, ("ok.png", blob("png", 10 * MIB))).data
    response = upload(client, 1, ("big.png", blob("png", 10 * MIB + 1)))
    assert "10 MiB limit for image files" in response.data.decode()
    assert len(db_rows(app, "SELECT id FROM media")) == 1 and len(stored(app)) == 1  # no partial file left


def test_audio_size_boundary_and_separate_limits(app, client):
    add_note(client)
    assert b"1 attachment added." in upload(client, 1, ("ok.wav", blob("wav", 25 * MIB))).data
    assert "25 MiB limit for audio files" in upload(client, 1, ("big.wav", blob("wav", 25 * MIB + 1))).data.decode()
    assert b"1 attachment added." in upload(client, 1, ("long.mp3", blob("mp3", 11 * MIB))).data  # > image limit, fine for audio
    assert "10 MiB limit" in upload(client, 1, ("long.png", blob("png", 11 * MIB))).data.decode()
    assert len(stored(app)) == 2


def test_overall_request_limit(tmp_path):
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False, "DATABASE": str(tmp_path / "d.db"),
                      "UPLOAD_FOLDER": str(tmp_path / "up"), "MAX_CONTENT_LENGTH": 2000})
    client = app.test_client()
    add_note(client)
    response = upload(client, 1, ("a.png", blob("png", 5000)))
    assert b"too large" in response.data
    assert stored(app) == [] and db_rows(app, "SELECT id FROM media") == []


# ---- rejected input ----

def test_empty_unsupported_and_mismatched_files_rejected(app, client):
    add_note(client)
    cases = {
        "empty.png": (b"", "is empty."),
        "text.png": (b"just text, not an image", "not a supported image or audio file"),
        "fake.png": (blob("jpg"), "does not match its JPEG contents"),
        "song.mp3": (blob("wav"), "does not match its WAV contents"),
        "vector.svg": (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "not a supported"),
        "page.html": (blob("png"), "does not match"),
        "tool.exe": (b"MZ\x90\x00", "not a supported"),
        "noext": (blob("png"), "does not match"),
    }
    for name, (content, expected) in cases.items():
        text = upload(client, 1, (name, content)).data.decode()
        assert expected in text, name
    assert db_rows(app, "SELECT id FROM media") == [] and stored(app) == []


def test_missing_file_field_and_non_multipart_requests(app, client):
    add_note(client)
    assert b"Choose at least one file" in client.post("/notes/1/media", follow_redirects=True).data
    assert b"Choose at least one file" in client.post("/notes/1/media", data={"files": ""},
                                                       content_type="multipart/form-data", follow_redirects=True).data
    assert b"Choose at least one file" in client.post("/notes/1/media", data=b"{garbage",
                                                       content_type="application/json", follow_redirects=True).data
    assert b"Choose at least one file" in client.post("/notes/1/media", data={"files": "plain text"},
                                                       follow_redirects=True).data


def test_file_count_limits(app, client):
    add_note(client)
    many = [(f"{i}.png", blob("png")) for i in range(MAX_FILES_PER_UPLOAD + 1)]
    assert b"at most 10 files" in upload(client, 1, *many).data
    for i in range(MAX_ATTACHMENTS_PER_NOTE // MAX_FILES_PER_UPLOAD):
        upload(client, 1, *[(f"{i}-{j}.png", blob("png")) for j in range(MAX_FILES_PER_UPLOAD)])
    assert b"at most 20 attachments" in upload(client, 1, ("extra.png", blob("png"))).data
    assert len(db_rows(app, "SELECT id FROM media")) == 20 == len(stored(app))


# ---- filenames and paths ----

def test_random_storage_names_and_traversal_filenames(app, client, tmp_path):
    add_note(client)
    for name in ("../../evil.png", "..\\..\\evil.png", "/etc/passwd.png", "a/b/c.png"):
        upload(client, 1, (name, blob("png")))
    keys = [r[0] for r in db_rows(app, "SELECT storage_key FROM media")]
    assert len(keys) == len(set(keys)) == 4
    assert all(re.fullmatch(r"[0-9a-f]{32}\.png", k) for k in keys)
    assert sorted(stored(app)) == sorted(keys)
    assert sorted(os.listdir(tmp_path)) == ["test.db", "uploads"]  # nothing escaped the upload root
    assert {r[0] for r in db_rows(app, "SELECT original_name FROM media")} == {"evil.png", "passwd.png", "c.png"}


def test_upload_path_rejects_unsafe_keys(tmp_path):
    root = str(tmp_path)
    good = "a" * 32 + ".png"
    assert media.upload_path(root, good) == os.path.join(os.path.realpath(root), good)
    for bad in ("../x.png", "/etc/passwd", "a" * 32 + ".php", "a" * 32 + ".png/../../x", "", None,
                "A" * 32 + ".png", "a" * 31 + ".png", "sub/" + good):
        with pytest.raises(ValueError):
            media.upload_path(root, bad)


def test_tampered_storage_key_is_never_served(app, client):
    add_note(client)
    upload(client, 1, ("a.png", blob("png")))
    outside = os.path.join(os.path.dirname(app.config["UPLOAD_FOLDER"]), "secret.png")
    with open(outside, "wb") as f:
        f.write(blob("png"))
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.execute("UPDATE media SET storage_key = '../secret.png'")
    conn.commit()
    conn.close()
    assert client.get("/media/1/file").status_code == 404


def test_display_filename_is_escaped(app, client):
    add_note(client)
    upload(client, 1, ("<img src=x onerror=alert(1)>.png", blob("png")))
    for url in ("/media", "/notes/1/media", "/media/1"):
        html = client.get(url).data.decode()
        assert "<img src=x" not in html and "&lt;img src=x onerror=alert(1)&gt;.png" in html, url


def test_clean_filename():
    assert media.clean_filename("a\x00b\x1f.png") == "ab.png"
    assert media.clean_filename("C:\\x\\y\\pic.png") == "pic.png"
    assert media.clean_filename("") == "attachment" and media.clean_filename("..") == "attachment"
    assert len(media.clean_filename("x" * 500 + ".png")) == 120


def test_format_detection():
    assert media.detect_format(b"\xff\xf1\x50\x80") is None            # ADTS AAC is not MP3
    assert media.detect_format(b"\xff\xfb\x90\x00") == "mp3"           # MPEG-1 Layer III frame
    assert media.detect_format(bytes(range(32))) is None
    assert media.detect_format(b"RIFF\0\0\0\0AVI LIST") is None


# ---- note states ----

def test_unknown_note_and_unknown_media_return_404(client):
    assert client.get("/notes/9/media").status_code == 404
    assert upload(client, 9, ("a.png", blob("png")), follow=False).status_code == 404
    for url in ("/media/9", "/media/9/file"):
        assert client.get(url).status_code == 404
    assert client.post("/media/9/delete").status_code == 404
    assert client.get("/media?type=video").status_code == 404


def test_trashed_note_hides_media_and_blocks_changes_then_restore_returns_it(app, client):
    add_note(client)
    data = blob("png", 300)
    upload(client, 1, ("keep.png", data))
    client.post("/delete/1")
    assert client.get("/media/1/file").status_code == 404 and client.get("/media/1").status_code == 404
    assert client.get("/notes/1/media").status_code == 404
    assert upload(client, 1, ("new.png", blob("png")), follow=False).status_code == 404
    assert client.post("/media/1/delete").status_code == 404
    assert b"keep.png" not in client.get("/media").data
    assert len(stored(app)) == 1 and len(db_rows(app, "SELECT id FROM media")) == 1  # nothing destroyed
    client.post("/restore/1")
    assert client.get("/media/1/file").data == data and b"keep.png" in client.get("/media").data


def test_archived_note_keeps_attachments_and_allows_changes(app, client):
    add_note(client)
    client.post("/archive/1")
    assert b"1 attachment added." in upload(client, 1, ("a.png", blob("png"))).data
    assert b"a.png" in client.get("/media").data
    assert client.post("/media/1/delete").status_code == 302


# ---- deletion and cleanup ----

def test_delete_attachment_removes_row_and_file_only_for_that_attachment(app, client):
    add_note(client)
    add_note(client, "Other")
    upload(client, 1, ("a.png", blob("png")), ("b.mp3", blob("mp3")))
    upload(client, 2, ("c.png", blob("png")))
    keys = {r["id"]: r["storage_key"] for r in db_rows(app, "SELECT id, storage_key FROM media")}
    response = client.post("/media/1/delete", follow_redirects=True)
    assert b"Attachment deleted." in response.data
    assert keys[1] not in stored(app) and set(stored(app)) == {keys[2], keys[3]}
    assert [r[0] for r in db_rows(app, "SELECT id FROM media ORDER BY id")] == [2, 3]
    assert client.post("/media/1/delete").status_code == 404


def test_permanent_delete_removes_only_that_notes_media(app, client):
    add_note(client)
    add_note(client, "Other")
    upload(client, 1, ("a.png", blob("png")), ("b.mp3", blob("mp3")))
    upload(client, 2, ("c.png", blob("png")))
    other = db_rows(app, "SELECT storage_key FROM media WHERE note_id = 2")[0][0]
    client.post("/delete/1")
    assert len(stored(app)) == 3                      # moving to Trash destroys nothing
    client.post("/purge/1")
    assert stored(app) == [other]
    assert [r[0] for r in db_rows(app, "SELECT note_id FROM media")] == [2]
    assert client.get("/media/3/file").status_code == 200


def test_empty_trash_cleans_media_of_trashed_notes_only(app, client):
    for title in ("A", "B", "Keep"):
        add_note(client, title)
    upload(client, 1, ("a.png", blob("png")))
    upload(client, 2, ("b.wav", blob("wav")))
    upload(client, 3, ("k.png", blob("png")))
    client.post("/delete/1")
    client.post("/delete/2")
    client.post("/trash/empty")
    assert [r[0] for r in db_rows(app, "SELECT note_id FROM media")] == [3] and len(stored(app)) == 1


def test_file_deletion_failure_is_reported_and_orphans_can_be_cleaned(app, client, monkeypatch, caplog):
    add_note(client)
    upload(client, 1, ("a.png", blob("png")))
    client.post("/delete/1")

    def broken(_path):
        raise PermissionError("locked")
    monkeypatch.setattr(media, "_unlink", broken)
    response = client.post("/purge/1", follow_redirects=True)
    assert b"could not be removed from disk" in response.data and b"cleanup-media" in response.data
    assert db_rows(app, "SELECT id FROM media") == [] and len(stored(app)) == 1   # row gone, file left behind
    assert "Could not delete media file" in caplog.text
    monkeypatch.undo()
    result = app.test_cli_runner().invoke(args=["cleanup-media"])
    assert "Removed 1 unreferenced" in result.output and stored(app) == []


def test_cleanup_never_touches_referenced_or_unrelated_files(app, client):
    add_note(client)
    upload(client, 1, ("a.png", blob("png")))
    root = app.config["UPLOAD_FOLDER"]
    for name in ("notes.txt", "A" * 32 + ".png"):
        with open(os.path.join(root, name), "w") as f:
            f.write("user file")
    orphan = "b" * 32 + ".png"
    with open(os.path.join(root, orphan), "wb") as f:
        f.write(blob("png"))
    app.test_cli_runner().invoke(args=["cleanup-media"])
    left = set(stored(app))
    assert orphan not in left and {"notes.txt", "A" * 32 + ".png"} <= left and len(left) == 3


def test_database_failure_during_upload_leaves_no_orphan_file(app, client):
    add_note(client)
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.execute("CREATE TRIGGER block_media BEFORE INSERT ON media BEGIN SELECT RAISE(ABORT, 'blocked'); END")
    conn.commit()
    conn.close()
    response = upload(client, 1, ("a.png", blob("png")))
    assert b"could not be saved" in response.data
    assert stored(app) == [] and db_rows(app, "SELECT id FROM media") == []


# ---- CSRF ----

def csrf_token(client, path="/notes/1/media"):
    return re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).data.decode()).group(1)


def test_media_routes_require_csrf(csrf_app):
    client = csrf_app.test_client()
    token = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/").data.decode()).group(1)
    client.post("/add", data={"title": "N", "content": "", "csrf_token": token})
    files = lambda: {"files": (io.BytesIO(blob("png")), "a.png")}
    assert client.post("/notes/1/media", data=files(), content_type="multipart/form-data").status_code == 400
    assert client.post("/notes/1/media", data={**files(), "csrf_token": "forged"},
                       content_type="multipart/form-data").status_code == 400
    assert stored(csrf_app) == []
    token = csrf_token(client)
    ok = client.post("/notes/1/media", data={**files(), "csrf_token": token}, content_type="multipart/form-data")
    assert ok.status_code == 302 and len(stored(csrf_app)) == 1
    assert client.post("/media/1/delete").status_code == 400
    assert client.post("/media/1/delete", data={"csrf_token": "forged"}).status_code == 400
    assert len(stored(csrf_app)) == 1
    assert client.post("/media/1/delete", data={"csrf_token": token}).status_code == 302
    assert stored(csrf_app) == []


def test_media_forms_include_csrf_tokens(app, client):
    add_note(client)
    upload(client, 1, ("a.png", blob("png")))
    for url in ("/notes/1/media", "/media/1", "/media", "/"):
        html = client.get(url).data.decode()
        assert html.count('method="post"') == html.count('name="csrf_token"'), url
    assert 'enctype="multipart/form-data"' in client.get("/notes/1/media").data.decode()


# ---- library and navigation ----

def test_media_library_filters_and_links(app, client):
    add_note(client, "Trip")
    upload(client, 1, ("pic.png", blob("png")), ("clip.mp3", blob("mp3")))
    everything = client.get("/media").data.decode()
    assert "pic.png" in everything and "clip.mp3" in everything and "/notes/1/media" in everything and "Trip" in everything
    images = client.get("/media?type=image").data.decode()
    assert "pic.png" in images and "clip.mp3" not in images
    audio = client.get("/media?type=audio").data.decode()
    assert "clip.mp3" in audio and "pic.png" not in audio and "<audio" in audio


def test_empty_states_navigation_and_note_card_link(app, client):
    assert b"No attachments yet" in client.get("/media").data
    assert b"No images yet" in client.get("/media?type=image").data
    add_note(client)
    assert b"No attachments yet" in client.get("/notes/1/media").data
    html = client.get("/").data.decode()
    assert 'href="/media"' in html and 'href="/notes/1/media"' in html
    upload(client, 1, ("a.png", blob("png")))
    assert "Files (1)" in client.get("/").data.decode()
    assert 'href="/media" aria-current="page"' in client.get("/media").data.decode()
    assert 'href="/notes/1/media"' in client.get("/edit/1").data.decode()


def test_symlink_inside_upload_root_cannot_escape(tmp_path):
    root = tmp_path / "uploads"
    root.mkdir()
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"secret")
    key = "c" * 32 + ".png"
    try:
        os.symlink(outside, root / key)
    except (OSError, NotImplementedError):
        return  # symlinks unavailable on this platform
    with pytest.raises(ValueError):
        media.upload_path(str(root), key)
