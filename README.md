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

For local development, `python app.py` runs with `APP_ENV=development` by
default and generates a random secret key for that process when `SECRET_KEY`
is not set. Set `SECRET_KEY` to a stable, randomly generated value when
running multiple workers or deploying the app; production mode requires it.
Set `APP_ENV=production` when deploying. `DATABASE` can be set to the desired
SQLite database file path; otherwise the app continues to use `notes.db` beside
`app.py`.

`.env.example` documents the supported variables, but the app does not load
`.env` files automatically. Configure these variables in your shell or
deployment environment.

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
├── .env.example
├── README.md
└── .gitignore
```

## Concepts used
Flask routing and application factory, Jinja2 templates and inheritance, HTML forms (GET and POST), the Post/Redirect/Get pattern, SQLite with parameterised queries, flash messages, error handling (404), testing with the Flask test client.

## Notes
Set `APP_ENV=production` and a strong `SECRET_KEY` before deploying anywhere
public. Production startup fails if no secret key is configured.
