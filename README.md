# Flask Notes App

A small full-stack web app for keeping notes. The backend is Flask with a SQLite database, and the pages are rendered with Jinja templates.

## Features
- Add, edit, delete and pin notes
- Search notes by title or content
- Server-side validation (title required, length limits) with flash messages
- Pinned notes always appear first
- Safe output: note text is HTML-escaped (no script injection)
- 11 automated tests with `pytest` and Flask's test client

## Setup
```
pip install -r requirements.txt
python app.py
```
Then open http://127.0.0.1:5000 in your browser.

## Run the tests
```
pytest
```

## Project structure
```
flask-notes-app/
├── app.py              # routes, database and validation
├── templates/
│   ├── base.html
│   ├── index.html
│   └── edit.html
├── static/
│   └── style.css
├── test_app.py         # automated tests
├── requirements.txt
├── README.md
└── .gitignore
```

## Concepts used
Flask routing and application factory, Jinja2 templates and inheritance, HTML forms (GET and POST), the Post/Redirect/Get pattern, SQLite with parameterised queries, flash messages, error handling (404), testing with the Flask test client.

## Notes
Set the `SECRET_KEY` environment variable before deploying anywhere public. The default key is for local development only.
