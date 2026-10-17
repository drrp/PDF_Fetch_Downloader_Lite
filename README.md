# PDF Fetch Downloader — Search & Download (no login)

A small FastAPI web app that searches four Telugu/Indian digital libraries at once
and downloads the books you pick as PDFs.

**No login, no database.** Anyone who opens the site can search and download; there
is no sign-in, no user accounts, and no OCR hub.

## What it does

- **Unified search** across four sources: Internet Archive, SVK Library (Telugu
  Academy), Manasu Foundation, and TTD Ebooks.
- **One-click download** of a found book. The PDF is saved to your computer as a
  file download (not opened in a browser tab, which is slow for large scans).

## Stack

- **Backend:** FastAPI, served by Uvicorn (`backend/main.py`).
- **Frontend:** static HTML/CSS/JS in `frontend/`, served by the same FastAPI app.
- **No database, no auth.** The app is stateless apart from the `downloads/` folder.

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Open http://127.0.0.1:8000 — no configuration needed.

## Deploying

See **DEPLOY.md**. The app runs as a single Python web service (a `render.yaml`
blueprint and a `Dockerfile` are included). It does **not** run on GitHub Pages.

## Project layout

```
backend/        FastAPI app + one scraper per library
frontend/       HTML/CSS/JS served by the backend
legacy/         Standalone desktop/CLI tools, not part of the web service
render.yaml     Render blueprint
Dockerfile      Portable container build
requirements.txt
```
