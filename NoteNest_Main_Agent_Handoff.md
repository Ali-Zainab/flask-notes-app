# NoteNest --- Main Agent Handoff & Multi-AI Operating Plan

**Document role:** portable project context for ChatGPT or any future
coordinating AI.\
**Project:** NoteNest, a personal GitHub Flask notes application.\
**Owner preference:** user coordinates by passing instructions and
outputs between free AI services; user is not expected to implement the
code manually.\
**Coordination rule:** ChatGPT is the current main architect/coordinator
when available. This file must let another AI continue if the user
switches chats or reaches a usage limit.

------------------------------------------------------------------------

## 1. Mission

Evolve the existing NoteNest project into a polished, reliable,
AI-assisted personal knowledge and productivity web app. Preserve the
current Flask/Jinja/SQLite architecture unless the actual repository
demonstrates a compelling reason to change it. Do not start over without
evidence.

Desired product capabilities: - Work, Business, Personal, Homework, and
user-created categories. - Search across title/content/summary,
category, dates, month/year, and sorting. - Pinning, archive, trash,
restore, permanent deletion, and retention policy. - Image and audio
attachments; clickable image previews and playable audio. - A separate
media library. - Light/dark, curated color themes, optional image-based
backgrounds. - AI summaries, grounded natural-language note search,
category suggestions, and note organization with confirmation. -
Flashcards generated from notes, manually editable, with a study
experience. - Professional responsive dashboard, polished note editor,
accessible interactions. - Later-stage additions: tasks, reminders,
calendar/agenda, related notes, note history, export/import, backups,
and possibly a knowledge graph. - Safe handling of secrets, uploaded
files, database migrations, and user data.

## 2. Current known project state (from user-uploaded files)

The uploaded README describes a small Flask + SQLite + Jinja app with
add/edit/delete/pin, title/content search, server-side validation, and
pytest tests.

The uploaded `app.py` is a substantially more advanced 910-line Flask
application. It: - Uses SQLite and an app factory (`create_app`). -
Defines categories (Work, Business, Personal, Homework). - Defines
notes, media, flashcards, settings tables, and in-place additions for
summary/category/archive/trash/update timestamps. - Includes note list
filtering by query/category/month/date range/sort. - Has
pin/archive/trash/restore/permanent-delete routes. - Supports
image/audio uploads and a media gallery. - Includes category management,
flashcards, AI assistant actions (find, summarize, organize), background
upload/theme settings. - Imports `ai`, but `ai.py` was not among the
supplied files.

The uploaded `base.html` expects a more advanced template family and
`static/app.js`, including: `notes.html`, `note_form.html`,
`note_view.html`, `media.html`, `categories.html`, `flashcards.html`,
`flashcards_study.html`, `assistant.html`, `settings.html`,
`_macros.html`, and `static/app.js`. These were not included in the
initial uploaded files.

However, uploaded `index.html`, `edit.html`, `test_app.py`, and README
appear to belong to an older app generation: - old templates refer to
routes such as `/add`, `/edit/<id>`, `/delete/<id>`; - current `app.py`
uses `/note/new`, `/note/<id>/edit`, `/note/<id>/trash`, etc. - uploaded
tests import `create_app` but use old route contracts. - uploaded
`requirements.txt` only contains Flask and pytest.

**Conclusion:** the uploaded file set is inconsistent and cannot be
assumed to represent a complete runnable repository. The actual GitHub
repository/current working tree is the source of truth. The first task
is an audit, not feature implementation.

Citation context from initial upload (for future assistants): - README
reference: `turn0file0` - app.py reference: `turn0file1` - base.html
reference: `turn0file2` - old index.html reference: `turn0file3` - old
edit.html reference: `turn0file4` - old tests reference: `turn0file5` -
requirements reference: `turn0file6` - old CSS reference: `turn0file7`

These refs may not exist in a future chat; the prose above is the
portable summary.

## 3. How the user wants to work

The user has access to free tiers of: - Claude - Kimi - Manus - Gemini -
DeepSeek - Grok - GitHub Copilot integrated in VS Code - Multiple Google
accounts for some services

Free-tier model access, context limits, and tool capabilities vary and
may change. Never assume a specific model or token allowance is
guaranteed. The user wants instructions to pass between AIs one by one
and wants each assignment sized to approximately 20,000 tokens of
working context.

The user expects the coordinating AI to: - decide the next task and
suitable agent; - write copy/paste-ready instructions for that AI; -
specify files in scope, prerequisites, tests, and acceptance criteria; -
inspect returned diffs/reports and send review prompts when needed; -
keep a durable Markdown context file updated so another AI can take
over; - avoid promising work is complete without evidence; - make the
process usable without the user having to code manually.

## 4. AI role suggestions (flexible, not capability guarantees)

-   **ChatGPT (current coordinator):** architecture, task breakdown,
    integration decisions, acceptance review, durable project context.
-   **Claude Free:** bounded feature implementation or refactor tasks.
-   **Gemini Free:** repository/design analysis, template/UI planning,
    independent review.
-   **GitHub Copilot in VS Code:** local edits against actual working
    tree, small implementation steps, running tests, diff inspection.
-   **DeepSeek Free:** independent code review, edge cases, test
    suggestions.
-   **Kimi Free:** longer documentation, handoff/checklist review.
-   **Grok Free:** alternative critique / second opinion.
-   **Manus Free:** optional research or self-contained QA if supported
    by its current plan.

These are suggested assignments only. Use whichever service can access
the repository and perform the specific task. Avoid parallel edits to
shared files.

## 5. Token/context budget policy

Treat 20,000 tokens as a maximum working budget, not a target and not a
guarantee. Each AI should reserve about 2,000--3,000 tokens for
validation and handoff. If a task exceeds scope, stop at a safe
checkpoint and split the remaining work into a new assignment. Never
cram a second feature into a nearly exhausted context window.

Each assignment must be self-contained and include: - project mission
and relevant file map; - exact task scope; - explicit non-goals; -
prerequisites; - expected files/areas to change; - acceptance
criteria; - tests to run; - required handoff report.

## 6. Non-negotiable engineering rules

1.  Inspect the actual repository and `git status` before editing.
2.  Never overwrite unrelated work or delete user data/uploads/database
    files.
3.  Preserve Flask/Jinja/SQLite unless there is a documented reason to
    migrate.
4.  Use parameterized SQL, validate inputs, preserve HTML escaping, and
    protect state-changing routes with CSRF.
5.  Validate uploaded file type/signature and size; generate stored
    filenames; guard against path traversal.
6.  Do not put API keys in source. Use environment variables and
    `.env.example`; keep `.env` out of Git.
7.  AI changes to notes/categories must be proposed and confirmed by the
    user.
8.  AI results should be grounded in actual retrieved notes; do not
    fabricate citations or pretend retrieval happened.
9.  AI provider errors must not break core note-taking. An offline
    fallback must be clearly labelled as such.
10. Keep SQLite migrations backward-compatible; test against an existing
    database schema and a fresh database.
11. Add/update tests for each feature; run the full test suite after
    integration where possible.
12. Use a separate branch/worktree or sequential ownership for each AI.
    One AI owns the changed files at a time.
13. Review the diff before merging. Commit coherent tested changes.
14. Never claim tests passed unless the command was actually run.
15. If blocked, report `PARTIAL` or `BLOCKED`, with exact error, files
    touched, and safest next step.
16. Never promise production security based only on passing unit tests.

## 7. Project phases and assignments

### Agent 0 --- Repository audit and baseline

**Goal:** establish the authoritative current code state. Do not
implement a broad feature.

Tasks: - Inspect the real GitHub repository/current working tree and git
status. - List project tree and identify the actual app entry point,
templates, static assets, AI module, tests, requirements, README,
`.gitignore`, database/migrations. - Run tests and start the app if
safe. - Identify missing files, old/new route mismatches, test failures,
and security/data risks. - Document current features and known broken
flows. - Produce `docs/PROJECT_AUDIT.md`, update
`docs/IMPLEMENTATION_PLAN.md`, and create `docs/STATUS.md`. - Do not
modify production data. Avoid risky changes; only make a minimal
test-blocking fix if clearly safe and explain it.

Acceptance: - Source of truth established from repository evidence. -
Exact commands/results recorded. - No destructive changes. - A
prioritized next task is recommended.

### Agent 1 --- Foundation and reliability

Prerequisite: audit approved. - Resolve missing modules/templates and
app inconsistencies found by audit. - Ensure app runs from documented
clean setup. - Add safe config, environment variables, `.env.example`,
correct `.gitignore`. - Validate CSRF, database lifecycle, upload
constraints, error handling. - Add explicit safe migrations and tests. -
Keep existing data and features. Acceptance: fresh setup works;
migration from existing DB works; tests pass.

### Agent 2 --- Premium UI/design system

Prerequisite: foundation stable. - Design premium, calm, modern
productivity UI with readable typography, generous spacing, clear
hierarchy. - Responsive desktop sidebar and mobile navigation. -
Reusable styles for buttons, forms, cards, dialogs, empty states,
badges, alerts. - Light/dark and curated color themes; optional
user-uploaded background with overlays. - Keyboard focus, semantic HTML,
accessible labels, reduced motion. - Use locally stored, licensed, or
otherwise suitable assets; core UI must not depend on random external
image URLs. - The reference images previously shown in chat are not
guaranteed to exist as files. Ask for uploads if exact reuse is
required; otherwise create a consistent design inspired by them.
Acceptance: existing routes work, responsive layout, all themes
readable, no regression.

### Agent 3 --- Notes, categories, search, archive/trash

-   Complete note create/edit/view and state transitions.
-   Custom categories/colors.
-   Pin, archive, trash, restore, permanent delete, retention.
-   Compose search by title/content/summary, category, created/updated
    dates, month/year, sorting.
-   Preserve filters on navigation.
-   Add tests for state transitions and combined filters. Acceptance:
    safe deletion, correct visibility, reliable combined filters.

### Agent 4 --- Media

-   Image/audio attachment to notes.
-   Accessible image lightbox, close button and Escape.
-   HTML audio player with controls.
-   Separate media library with filters and parent-note links.
-   Validate file signatures/types/size; safe generated storage names;
    path traversal protection.
-   Correct media behavior on note archive/trash/restore/permanent
    delete.
-   Tests for valid/invalid uploads and deletion. Acceptance: works
    after restart, safe file serving, media links behave correctly.

### Agent 5 --- AI assistant

-   Inspect current AI provider interface and requirements.
-   Define provider abstraction for summarize, category suggestion, note
    retrieval/search, and flashcard generation.
-   API credentials from environment; timeouts and clear failures.
-   Deterministic offline fallback, clearly labelled.
-   Ground note search in actual records and link results.
-   Category changes and bulk organization require preview and
    confirmation.
-   Validate AI output before saving; cap inputs; only send relevant
    notes.
-   Mock provider in tests; no API key required in CI. Acceptance: core
    app works without keys; failures are graceful; AI results are
    grounded and reviewed before changes.

### Agent 6 --- Flashcards/study

-   Deck list and per-note deck.
-   AI generation using Agent 5 provider; review before save.
-   Manual add/edit/delete.
-   Flip/reveal, next/previous, shuffle, progress.
-   Optional persistent review and spaced repetition if scope permits.
-   Duplicate prevention and empty states.
-   Tests for CRUD, generation, study state. Acceptance: usable without
    AI; generated cards are reviewable.

### Agent 7 --- Dashboard and personalization

-   Home dashboard with quick capture, pinned/recent notes, categories,
    recent decks.
-   Theme preferences, curated color palettes, optional custom
    background.
-   Define persistence (browser-local vs database) and document it.
-   Contrast/accessibility and empty states. Acceptance: all actions
    work, preferences persist as documented.

### Agent 8 --- Tasks/calendar (later phase)

-   Tasks with title, status, priority, due date, optional note link.
-   Convert action items only with user confirmation.
-   Upcoming/overdue/completed views and simple agenda/calendar.
-   Start with in-app reminders; do not claim push notifications unless
    implemented.
-   Safe migration and tests. Acceptance: CRUD/date/note link works; no
    fabricated AI due dates.

### Agent 9 --- Final QA/release

-   Full suite, fresh DB, upgrade existing DB.
-   Test all navigation, search, categories, state transitions, themes,
    uploads, image/audio, AI error states, flashcards, tasks if
    included.
-   Mobile and keyboard checks; CSRF/secrets/upload checks.
-   README setup, config, features, limitations, tests, troubleshooting.
-   Review `.gitignore`; no secrets or user uploads committed.
-   Release checklist and honest known-issues list. Acceptance: clean
    clone setup works, no known critical issues, tests and manual checks
    reported truthfully.

## 8. How to run the collaboration

Do not launch all agents against the same main branch.

Preferred workflow: 1. User shares repository URL and/or a fresh
ZIP/tree. 2. Main coordinator asks Agent 0 for audit only. 3. Review
audit; resolve conflicts before coding. 4. Assign one implementation
task at a time, preferably through Copilot against the actual working
tree or a dedicated branch. 5. After implementation, use a different AI
for review only; it should not edit the same branch unless explicitly
assigned. 6. Run tests locally through Copilot/VS Code or terminal. 7.
Integrate one task, review diff, commit, update `docs/STATUS.md`. 8.
Update this portable context file after major milestones. 9. If a model
reaches limits, paste this file and the latest `docs/STATUS.md`, then
assign only the next explicit task.

## 9. Required handoff format for every AI

Every AI must finish with:

**Status:** COMPLETE / PARTIAL / BLOCKED\
**Summary:** what changed and what a user can do now\
**Files changed:** exact paths\
**Tests run:** exact commands and results\
**Data/migration safety:** what happens to existing records\
**Known limitations:** specific and honest\
**Git:** branch and commit hash, or patch/diff summary\
**Next step:** one explicit next task\
**Do not do:** any important warning for the next agent

A feature is not "complete" merely because code was generated. It is
complete only when integrated, exercised, tested, and documented to the
agreed scope.

## 10. Prompt template to give an implementation AI

You are Agent \[NUMBER\]: \[ASSIGNMENT NAME\] for NoteNest. You are not
the project owner or main architect. Follow the current
`docs/IMPLEMENTATION_PLAN.md` and your exact assigned task.

Before coding: 1. Read this project handoff and `docs/PROJECT_AUDIT.md`.
2. Inspect actual repository files and `git status`. 3. Confirm
prerequisites and list expected files to change. 4. Do not overwrite
unrelated changes.

Implement only your assigned scope. Preserve existing data and behavior.
Add/update tests. Run relevant tests and the full suite when practical.
Inspect the final diff. Never claim tests passed without running them.

Keep the work within an approximately 20,000-token budget, reserving
2,000--3,000 tokens for testing and handoff. If scope is too large, stop
at a clean checkpoint and report PARTIAL rather than leaving broken or
half-written code.

Return the required handoff format. Do not begin the next agent's task.

## 11. Immediate next step

**Do not start feature implementation yet.** The supplied files may
represent two different generations of the app. The actual GitHub
repository must be inspected to establish the source of truth.

Ask the user for the GitHub repository URL (public URL is enough if
public). If private, ask for a ZIP or the relevant current files. Never
ask them to share credentials or API keys.

The first deliverable is a repository audit and a confirmed
implementation sequence, not a redesign or broad rewrite.
