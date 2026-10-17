# Deploying PDF Fetch Downloader (Search & Download)

This app is a **FastAPI + Postgres web service** that serves its own frontend. It
runs as a single Python web service (a `render.yaml` blueprint and a `Dockerfile`
are included). It does **not** run on GitHub Pages, which only serves static files.

Target setup: **Render** for the app, **Supabase** for the database.

---

## 1. Supabase connection string

1. Supabase dashboard -> **Project Settings -> Database**.
2. Copy the **Connection string -> URI** (use the *Session pooler*).
   It looks like `postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres`.
3. The app creates its tables (`users`, `activities`) on first start, so no manual
   SQL is needed.

## 2. Google credentials

Only OAuth is needed for this variant (no Vision/OCR, no Gemini):

- Google Cloud Console -> **APIs & Services -> Credentials** -> OAuth 2.0 Client ID
  (type **Web application**). Under **Authorized redirect URIs** add
  `https://<your-domain>/auth/callback`
  (and, while testing, your `https://<app>.onrender.com/auth/callback`).

## 3. Render wiring (step by step)

### 3a. Connect the repository

1. Render dashboard -> **New -> Blueprint** (to use `render.yaml`) or
   **New -> Web Service** (to configure by hand).
2. Connect GitHub and grant the Render GitHub App access to this repo.
3. Pick the repo, branch **`main`**.

### 3b. Service settings

| Setting | Value |
| --- | --- |
| Runtime | Python 3 |
| Build command | `pip install --upgrade pip && pip install -r requirements.txt` |
| Start command | `uvicorn backend.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"` |
| Health check path | `/` |

The `--proxy-headers --forwarded-allow-ips="*"` part is required: it makes uvicorn
trust Render's HTTPS headers, so the app builds an `https://` Google OAuth redirect
URL. Without it, login fails on a custom domain.

### 3c. Environment variables

Add these in **Settings -> Environment**:

| Key | Value |
| --- | --- |
| `DATABASE_URL` | Supabase connection string (step 1) |
| `SESSION_SECRET_KEY` | a long random string (Render can generate it) |
| `GOOGLE_CLIENT_ID` | from step 2 |
| `GOOGLE_CLIENT_SECRET` | from step 2 |
| `ADMIN_EMAIL` | the email that gets the admin dashboard |
| `COOKIE_HTTPS_ONLY` | `true` |
| `PYTHON_VERSION` | `3.12.0` |

### 3d. Free tier vs paid (and the card prompt)

The blueprint ships on the **free** plan, which needs no payment method. Free
services sleep after ~15 minutes idle (the next visit cold-starts in ~30-60s) and
have no persistent disk, so downloaded PDFs are lost on restart.

To keep downloads across restarts, move to a paid instance and add a disk: set
`plan: starter` in `render.yaml` and uncomment the `disk:` block, or use
**Settings -> Disks -> Add** with mount path `/opt/render/project/src/downloads`.
Render asks for a card for any paid instance or disk.

## 4. Custom domain

1. Render service -> **Settings -> Custom Domains -> Add Custom Domain** and enter
   your domain.
2. Render shows the DNS record to create at your registrar (a **CNAME** for a
   subdomain). Add it, and on Cloudflare keep it **DNS only** until the certificate
   issues.
3. Confirm the Google OAuth redirect URI uses the same host:
   `https://<your-domain>/auth/callback`.

## 5. Verify

- [ ] The site loads the login page.
- [ ] "Google తో లాగిన్ అవ్వండి" completes and returns you logged in.
- [ ] A search returns results from the four libraries.
- [ ] Downloading a book saves a PDF to your computer.
- [ ] Logging in with `ADMIN_EMAIL` shows the admin panel.

## 6. Notes

- **Downloads live on disk** (`downloads/`). The free plan wipes that disk on
  restart, so keep the persistent disk (paid) or move PDFs to Supabase Storage.
- **This variant has no OCR.** The OCR hub, full-text index, AI summary and
  chandassu analysis from the full version are not included.
- **Secrets stay in the host's env vars.** `.env` is git-ignored.
