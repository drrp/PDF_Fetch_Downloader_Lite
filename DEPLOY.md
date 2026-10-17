# Deploying PDF Fetch Downloader (Search & Download)

This app is a **single FastAPI web service** that serves its own frontend. There is
**no login and no database** — you only need to deploy the service.

It does **not** run on GitHub Pages, which can only serve static files.

---

## 1. Deploy on Render

**Blueprint (recommended):** push this repo, then Render -> **New -> Blueprint** ->
pick the repo. `render.yaml` creates the service with everything it needs.

**Manual web service:** Render -> **New -> Web Service**; runtime **Python 3**:

| Setting | Value |
| --- | --- |
| Build command | `pip install --upgrade pip && pip install -r requirements.txt` |
| Start command | `uvicorn backend.main:app --host 0.0.0.0 --port $PORT` |
| Health check path | `/` |
| Instance type | Free |

**Environment variables:** only one, and it is optional —
`PYTHON_VERSION` = `3.12.0`. There are no secrets to set: no database URL, no
Google keys, no API keys.

## 2. Custom domain: library.auchithyam.com

This domain is currently attached to the older `PDF_Fetch_Downloader` service, and
Render allows a custom domain on **only one service at a time**. To move it here:

1. Open the **old** service -> **Settings -> Custom Domains** -> next to
   `library.auchithyam.com`, click **Remove**. (The old app keeps running on its
   `pdf-fetch-downloader.onrender.com` address.)
2. Open the **Lite** service -> **Settings -> Custom Domains -> Add Custom Domain**
   and enter `library.auchithyam.com`. Alternatively redeploy the Blueprint, which
   already declares it in `render.yaml`.
3. Render shows the DNS record for *this* service - a **CNAME** pointing at
   `pdf-fetch-downloader-lite.onrender.com`. It differs from the old target, so
   update that record at your DNS provider. On Cloudflare keep it **DNS only**
   (grey cloud) until the certificate is issued.
4. Wait for Render to show **Certificate issued**, then open
   https://library.auchithyam.com/.

There are no Google OAuth redirect URIs to update, because this app has no login.

## 3. Verify

- [ ] The site loads the dashboard directly (no login screen).
- [ ] A search returns results from the four libraries.
- [ ] Downloading a book saves a PDF to your computer.

## 4. Notes

- **Free tier:** the service sleeps after ~15 minutes idle, so the first visit
  afterwards takes 30-60 seconds to wake.
- **Downloads live on disk** (`downloads/`). The free plan wipes that disk on
  restart. To keep PDFs, move to a paid instance and uncomment the `disk:` block in
  `render.yaml` (Render asks for a card for any paid instance or disk).
- **No OCR.** This variant has no OCR hub, no full-text index, no AI summary and no
  chandassu analysis — just search and download.
