# PDF Fetch Downloader — Search & Download

A FastAPI + Supabase web app that searches four Telugu/Indian digital libraries at
once and downloads the books you pick as PDFs.

This is the **search-and-download-only** variant. There is no OCR hub, no AI
summary, and no full-text index — just search, download, login and the admin panel.

## What it does

- **Unified search** across four sources: Internet Archive, SVK Library (Telugu
  Academy), Manasu Foundation, and TTD Ebooks.
- **One-click download** of a found book. The PDF is saved to your computer as a
  file download (not opened in a browser tab, which is slow for large scans).
- **Google login** with a user profile page and an admin dashboard for the owner.

## Stack

- **Backend:** FastAPI, served by Uvicorn (`backend/main.py`).
- **Database:** Supabase (PostgreSQL) via `psycopg2`, using `DATABASE_URL`.
- **Frontend:** static HTML/CSS/JS in `frontend/`, served by the same FastAPI app.
- **Auth:** Google OAuth via authlib.

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill in the values
uvicorn backend.main:app --reload
```

Open http://127.0.0.1:8000 (set `COOKIE_HTTPS_ONLY=false` in `.env` for local HTTP).

## Configuration

All settings come from environment variables — see `.env.example`:
`DATABASE_URL`, `SESSION_SECRET_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
`ADMIN_EMAIL`, `COOKIE_HTTPS_ONLY`.

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
