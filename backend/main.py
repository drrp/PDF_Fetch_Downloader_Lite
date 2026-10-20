import warnings
warnings.filterwarnings("ignore", message=".*httpx module is deprecated.*")
warnings.filterwarnings("ignore", module="authlib")

import concurrent.futures
import gzip
import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime
from urllib.parse import quote

import psycopg2
import pytz
from psycopg2.extras import RealDictCursor

from authlib.integrations.starlette_client import OAuth
from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

try:
    import rcssmin
    import rjsmin
except ImportError:  # minification is optional; fall back to serving files as-is
    rcssmin = rjsmin = None

from backend.svk import SVKScraper
from backend.archive import InternetArchiveScraper
from backend.manasu import ManasuFoundationScraper
from backend.ttd import TTDScraper

load_dotenv(override=True)

# When the app is packaged as a .exe, PyInstaller unpacks the frontend files into a
# temporary bundle directory instead of leaving them beside the source, so ask it
# where they landed rather than guessing from __file__.
if getattr(sys, "frozen", False):
    BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
FRONTEND_INDEX = os.path.join(FRONTEND_DIR, "index.html")
# Downloaded books are transient - saved, then handed to the browser - so in the
# packaged app they go to the user's temp folder, which is always writable even if
# the .exe itself sits somewhere read-only.
if getattr(sys, "frozen", False):
    DOWNLOAD_DIR = os.path.join(tempfile.gettempdir(), "library-app-downloads")
else:
    DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")

# Supabase (Postgres) connection string. Holds the users and activity tables.
DB_URL = os.getenv("DATABASE_URL")

# --- Config (override any of these via environment variables) ---
# Email that gets the admin dashboard.
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "rpsarma9247@gmail.com")
# Send the login cookie over HTTPS only. Set COOKIE_HTTPS_ONLY=false for local HTTP.
COOKIE_HTTPS_ONLY = os.getenv("COOKIE_HTTPS_ONLY", "true").strip().lower() in ("1", "true", "yes", "on")
# Local development only: set DEV_NO_LOGIN=true to use the app without Google sign-in.
# It is off unless you ask for it, so production is unaffected - but never enable it
# on a public server, because it opens the app to everyone.
DEV_NO_LOGIN = os.getenv("DEV_NO_LOGIN", "").strip().lower() in ("1", "true", "yes", "on")
# When true, the reader's browser fetches the PDF straight from the library, which costs
# this server no bandwidth - but most libraries send no Content-Disposition, so the
# browser opens the PDF in a viewer instead of saving it. Off by default: the server
# downloads the book and sends it as an attachment, which saves it immediately.
DIRECT_DOWNLOAD = os.getenv("DIRECT_DOWNLOAD", "").strip().lower() in ("1", "true", "yes", "on")
# Sign-in switched off entirely, which is what a copy built as a standalone app uses:
# no login page, no login button, and the account routes are not registered at all.
LOGIN_ENABLED = not DEV_NO_LOGIN

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# --- Startup diagnostics: prints only whether each variable is present, never its value ---
print(
    "Startup config check ->",
    "DATABASE_URL:", bool(DB_URL),
    "| SESSION_SECRET_KEY:", bool(os.getenv("SESSION_SECRET_KEY")),
    "| GOOGLE_CLIENT_ID:", bool(os.getenv("GOOGLE_CLIENT_ID")),
    "| GOOGLE_CLIENT_SECRET:", bool(os.getenv("GOOGLE_CLIENT_SECRET")),
)
if DEV_NO_LOGIN:
    print("WARNING: DEV_NO_LOGIN is set - sign-in is DISABLED. Do not use this on a public server.")


def get_db_connection():
    if not DB_URL:
        raise Exception("DATABASE_URL environment variable is not set!")
    return psycopg2.connect(DB_URL)


def init_db():
    if not DB_URL:
        print("Warning: DATABASE_URL is not set.")
        return

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                name TEXT,
                picture TEXT,
                last_login TEXT,
                is_active BOOLEAN DEFAULT FALSE
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS activities (
                id SERIAL PRIMARY KEY,
                email TEXT,
                name TEXT,
                picture TEXT,
                action TEXT,
                details TEXT,
                time TEXT,
                status TEXT DEFAULT 'Success'
            )
        ''')

        # Structured columns, so the profile and admin pages can act on an activity
        # (search again, download again) instead of parsing the readable text.
        # ADD COLUMN IF NOT EXISTS is a no-op on an existing database.
        for column in ("query", "book_title", "book_url", "source_code"):
            cursor.execute(f"ALTER TABLE activities ADD COLUMN IF NOT EXISTS {column} TEXT")

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error initializing DB: {e}")


init_db()


class MinifiedStaticFiles(StaticFiles):
    """Serve JS and CSS minified.

    The browser must download these files to run the app, so they can never be fully
    hidden - but minifying keeps the comments and layout out of view, so the page
    source no longer reads like documentation of how the app is put together.
    """

    _cache = {}

    async def get_response(self, path, scope):
        if rjsmin is not None and path.endswith((".js", ".css")):
            full = os.path.join(str(self.directory), path)
            try:
                stamp = os.path.getmtime(full)
            except OSError:
                return await super().get_response(path, scope)

            key = (path, stamp)
            cached = self._cache.get(key)
            if cached is None:
                with open(full, "r", encoding="utf-8") as f:
                    source = f.read()
                if path.endswith(".js"):
                    cached = (rjsmin.jsmin(source), "application/javascript")
                else:
                    cached = (rcssmin.cssmin(source), "text/css")
                if len(self._cache) > 8:      # only a couple of files in practice
                    self._cache.clear()
                self._cache[key] = cached

            body, media_type = cached
            return Response(body, media_type=media_type,
                            headers={"Cache-Control": "public, max-age=3600"})

        return await super().get_response(path, scope)


app = FastAPI(
    title="Telugu Digital Library Hub",
    # No public API documentation: it would list every endpoint, parameter and
    # response shape. None of that belongs to the reader.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET_KEY", "your-secret-key"),
    same_site="lax",
    https_only=COOKIE_HTTPS_ONLY,
)

oauth = OAuth()
oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

if os.path.exists(FRONTEND_DIR):
    app.mount("/static", MinifiedStaticFiles(directory=FRONTEND_DIR), name="static")

svk_scraper = SVKScraper()
ia_scraper = InternetArchiveScraper()
manasu_scraper = ManasuFoundationScraper()
ttd_scraper = TTDScraper()

# Libraries are addressed by short codes on the wire, so neither the page source nor
# the network traffic spells out where a book came from. The label is what the reader
# sees; the code is all the browser ever handles.
LIBRARIES = {
    "a": ("IA", ia_scraper),
    "b": ("SVK", svk_scraper),
    "c": ("MF", manasu_scraper),
    "d": ("TTD", ttd_scraper),
}


def _json_response(request: Request, payload) -> Response:
    """JSON, gzipped when the client accepts it.

    The search payload is highly repetitive, so gzip shrinks it roughly sixtyfold -
    which matters because it is sent on every search.
    """
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {}
    if "gzip" in request.headers.get("accept-encoding", "").lower():
        body = gzip.compress(body, 6)
        headers["Content-Encoding"] = "gzip"
    return Response(content=body, media_type="application/json", headers=headers)


def _with_source_label(row):
    """Attach the reader-facing label for an activity's library code."""
    entry = dict(row)
    code = entry.get("source_code")
    entry["source_label"] = LIBRARIES[code][0] if code in LIBRARIES else ""
    return entry


def _login_not_configured_page(redirect_uri: str) -> str:
    """A plain explanation, shown when this copy has no Google credentials."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign-in is not set up</title>
<style>
  body {{ margin:0; padding:40px 16px; background:#faf7f5; color:#2b2b2b;
         font-family: system-ui, "Segoe UI", Arial, sans-serif; line-height:1.6; }}
  .card {{ max-width:640px; margin:0 auto; background:#fff; border:1px solid #e8d5d8;
           border-radius:14px; padding:28px 32px; }}
  h1 {{ color:#7a1f2b; font-size:22px; margin:0 0 8px; }}
  h2 {{ color:#7a1f2b; font-size:16px; margin:26px 0 6px; }}
  p {{ margin:8px 0; }}
  code, pre {{ background:#f6f1ef; border-radius:6px;
               font-family: ui-monospace, Consolas, monospace; }}
  code {{ padding:1px 5px; }}
  pre {{ padding:10px 12px; overflow-x:auto; }}
  a {{ color:#7a1f2b; }}
</style>
</head>
<body>
  <div class="card">
    <h1>Sign-in is not set up on this copy</h1>
    <p>This copy of the app has no Google credentials, so there is nothing for the
       login button to do. Nothing is broken.</p>

    <h2>To use the app on this computer</h2>
    <p>Create a file called <code>.env</code> next to <code>requirements.txt</code>
       containing this one line, then restart the app:</p>
    <pre>DEV_NO_LOGIN=true</pre>
    <p>You will go straight into the app, with no login page.</p>

    <h2>To use real Google sign-in</h2>
    <p>Set <code>GOOGLE_CLIENT_ID</code> and <code>GOOGLE_CLIENT_SECRET</code>, and add
       this exact address to the Authorized redirect URIs in the Google Cloud
       Console:</p>
    <pre>{redirect_uri}</pre>

    <p><a href="/">Back to the app</a></p>
  </div>
</body>
</html>"""


def _signed_in(request: Request) -> bool:
    """Whether the caller may use the app. DEV_NO_LOGIN only relaxes this locally."""
    return bool(request.session.get("user")) or DEV_NO_LOGIN


def _index_without_login() -> str:
    """The app page with the whole sign-in area removed.

    Finds the <div id="auth-section"> block and drops it, counting nested divs so it
    removes the right closing tag. Anything unexpected leaves the page untouched.
    """
    try:
        with open(FRONTEND_INDEX, encoding="utf-8") as f:
            html = f.read()
    except OSError:
        return ""

    start = html.find('<div id="auth-section"')
    if start == -1:
        return html

    depth = 0
    i = start
    while i < len(html):
        if html.startswith("<div", i):
            depth += 1
        elif html.startswith("</div>", i):
            depth -= 1
            if depth == 0:
                return html[:start] + html[i + len("</div>"):]
        i += 1
    return html


def log_user_activity(request: Request, action_type: str, details: str, status: str = "Success",
                      query: str = None, book_title: str = None,
                      book_url: str = None, source_code: str = None):
    """Record what a signed-in reader did, for the profile and admin pages."""
    user = request.session.get("user")
    if not user:
        return
    try:
        IST = pytz.timezone("Asia/Kolkata")
        current_time = datetime.now(IST).strftime("%d-%m-%Y %I:%M %p")
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO activities
                (email, name, picture, action, details, time, status,
                 query, book_title, book_url, source_code)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (user.get("email"), user.get("name"), user.get("picture"),
              action_type, details, current_time, status,
              query, book_title, book_url, source_code))
        cursor.execute('UPDATE users SET is_active = TRUE WHERE email = %s', (user.get("email"),))
        conn.commit()
        conn.close()
    except Exception as e:
        print("DB Error logging activity:", e)


# ---------------------------------------------------------------- sign in / out

@app.get("/login/google")
async def login(request: Request):
    if not os.getenv("GOOGLE_CLIENT_ID") or not os.getenv("GOOGLE_CLIENT_SECRET"):
        # Without credentials there is nothing for Google to authenticate against, so
        # say so plainly instead of throwing an error the reader cannot act on.
        return HTMLResponse(_login_not_configured_page(str(request.url_for("auth"))))
    redirect_uri = request.url_for("auth")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def auth(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo") or token.get("user_info")
        if not user_info:
            resp = await oauth.google.get(
                "https://www.googleapis.com/oauth2/v3/userinfo", token=token)
            user_info = resp.json()

        if user_info and user_info.get("email"):
            user_dict = {
                "name": user_info.get("name"),
                "email": user_info.get("email"),
                "picture": user_info.get("picture"),
            }
            request.session["user"] = user_dict

            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            IST = pytz.timezone("Asia/Kolkata")
            login_time = datetime.now(IST).strftime("%d-%m-%Y %I:%M %p")

            cursor.execute("SELECT email FROM users WHERE email = %s", (user_dict.get("email"),))
            existing = cursor.fetchone()

            if existing:
                cursor.execute('''
                    UPDATE users SET name = %s, picture = %s, last_login = %s WHERE email = %s
                ''', (user_dict.get("name"), user_dict.get("picture"),
                      login_time, user_dict.get("email")))
            else:
                cursor.execute('''
                    INSERT INTO users (email, name, picture, last_login, is_active)
                    VALUES (%s, %s, %s, %s, TRUE)
                ''', (user_dict.get("email"), user_dict.get("name"),
                      user_dict.get("picture"), login_time))

            conn.commit()
            conn.close()

            if user_dict.get("email") == ADMIN_EMAIL:
                return RedirectResponse(url="/admin", status_code=303)
    except Exception as e:
        print(f"OAuth Error: {e}")

    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    user = request.session.get("user")
    if user:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_active = FALSE WHERE email = %s", (user.get("email"),))
            conn.commit()
            conn.close()
        except Exception as e:
            print("DB Error on logout:", e)
    request.session.clear()
    return RedirectResponse(url="/")


@app.get("/api/current-user")
def get_current_user(request: Request):
    user = request.session.get("user")
    if not user:
        return {"logged_in": False, "direct_download": DIRECT_DOWNLOAD,
                "login_enabled": LOGIN_ENABLED}
    return {
        "logged_in": True,
        "direct_download": DIRECT_DOWNLOAD,
        "login_enabled": LOGIN_ENABLED,
        "name": user.get("name"),
        "email": user.get("email"),
        "picture": user.get("picture"),
        "is_admin": (user.get("email") == ADMIN_EMAIL),
    }


# ---------------------------------------------------------------- profile / admin

@app.get("/profile")
def user_profile_page(request: Request):
    if not request.session.get("user"):
        return RedirectResponse(url="/login/google", status_code=303)
    page = os.path.join(FRONTEND_DIR, "profile.html")
    return FileResponse(page) if os.path.exists(page) else {"error": "profile.html not found"}


@app.get("/user/activity-json")
def get_user_activity_json(request: Request):
    user = request.session.get("user")
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT action, details, time, status, query, book_title, book_url, source_code "
            "FROM activities WHERE email = %s ORDER BY id DESC", (user.get("email"),))
        activities = [_with_source_label(row) for row in cursor.fetchall()]
        conn.close()

        return {
            "user": user,
            "stats": {
                "searches": sum(1 for a in activities if a["action"] == "Search"),
                "downloads": sum(1 for a in activities
                                 if a["action"] == "Download" and a["status"] == "Success"),
            },
            "activities": activities,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/admin")
def admin_dashboard(request: Request):
    user = request.session.get("user")
    if not user or user.get("email") != ADMIN_EMAIL:
        return RedirectResponse(url="/")
    page = os.path.join(FRONTEND_DIR, "admin.html")
    return FileResponse(page) if os.path.exists(page) else {"error": "admin.html not found"}


@app.get("/admin/users-json")
def get_admin_users_json(request: Request):
    user = request.session.get("user")
    if not user or user.get("email") != ADMIN_EMAIL:
        return JSONResponse({"error": "Unauthorized Access"}, status_code=401)

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM users")
        users = [dict(row) for row in cursor.fetchall()]
        cursor.execute("SELECT * FROM activities ORDER BY id DESC")
        activities = [_with_source_label(row) for row in cursor.fetchall()]
        conn.close()

        return {
            "total_users": len(users),
            "users": users,
            "activities": activities,
            "stats": {
                "searches": sum(1 for a in activities if a["action"] == "Search"),
                "downloads": sum(1 for a in activities if a["action"] == "Download"),
                "total_actions": len(activities),
            },
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------- app

@app.post("/reset-app")
def reset_app():
    # The dashboard's Reset button reloads the page client-side; this endpoint
    # only acknowledges the request so the frontend fetch() does not error.
    return {"status": "ok"}


@app.get("/")
def read_root(request: Request):
    if not _signed_in(request):
        login_page = os.path.join(FRONTEND_DIR, "login.html")
        if os.path.exists(login_page):
            return FileResponse(login_page)
        return RedirectResponse(url="/login/google", status_code=303)
    if not os.path.exists(FRONTEND_INDEX):
        return {"error": "index.html not found"}
    if LOGIN_ENABLED:
        return FileResponse(FRONTEND_INDEX)
    # A copy with no sign-in should not carry the markup for one either, so the whole
    # sign-in area is left out of the page it serves.
    return HTMLResponse(_index_without_login())


@app.get("/search")
def search(
    request: Request,
    query: str = Query(...),
    sources: str = Query(""),
    page: int = Query(1), limit: int = Query(0),
):
    if not _signed_in(request):
        return JSONResponse({"error": "not_signed_in"}, status_code=401)

    # Which libraries to query, as a comma-separated list of codes. Empty or unknown
    # means all of them.
    codes = [c.strip() for c in sources.split(",") if c.strip() in LIBRARIES]
    if not codes:
        codes = list(LIBRARIES)

    # The libraries are independent, so query them at the same time: the request
    # takes about as long as the slowest one, not the sum of all.
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(codes)) as ex:
        futures = [(code, ex.submit(LIBRARIES[code][1].search, query)) for code in codes]
        for code, fut in futures:              # collected in a fixed order
            try:
                for book in fut.result():
                    book["source"] = code
                    book["source_label"] = LIBRARIES[code][0]
                    # The result cards never show this, and it is a large slice of
                    # the response, so it is not sent to the browser at all.
                    book.pop("description", None)
                    results.append(book)
            except Exception as e:
                print(f"search error [{code}]: {e}")

    total_items = len(results)
    log_user_activity(request, "Search", f"వెతికిన పదం: '{query}' — {total_items} ఫలితాలు",
                      query=query)

    # limit=0 (the default) returns everything; the frontend paginates locally.
    if limit and limit > 0:
        start_idx = (page - 1) * limit
        paginated_results = results[start_idx:start_idx + limit]
        total_pages = (total_items + limit - 1) // limit if total_items > 0 else 1
    else:
        paginated_results = results
        total_pages = 1

    return _json_response(request, {
        "results": paginated_results, "total": total_items,
        "page": page, "total_pages": total_pages
    })


@app.get("/download-link")
def download_link(
    request: Request,
    book_page_url: str = Query(...), title: str = Query(...),
    source: str = Query("b"),
):
    """Resolve the library's own PDF URL so the browser can fetch it directly.

    The book then travels straight from the library to the reader and never passes
    through this server, which is what keeps the bandwidth down. Sources that cannot
    be resolved this way (Google Drive, TTD) fall back to /download-book.
    """
    if not _signed_in(request):
        return JSONResponse({"error": "not_signed_in"}, status_code=401)

    if not DIRECT_DOWNLOAD:
        # The reader is better served by a real download, so send them to the
        # server-side path below rather than to a PDF viewer.
        return {"ok": False, "reason": "direct_download_disabled"}

    entry = LIBRARIES.get(source)
    if entry is None:
        return {"ok": False, "reason": "unknown_source"}

    scraper = entry[1]
    if not hasattr(scraper, "resolve"):
        return {"ok": False, "reason": "no_direct_link"}

    try:
        url, _headers = scraper.resolve(book_page_url)
    except Exception as e:
        return {"ok": False, "reason": str(e)}

    log_user_activity(
        request, "Download",
        f"డౌన్‌లోడ్ (నేరుగా గ్రంథాలయం నుండి): '{title}' ({entry[0]})", "Success",
        book_title=title, book_url=book_page_url, source_code=source,
    )
    return {"ok": True, "url": url}


@app.get("/download-book")
def download_book(
    request: Request,
    book_page_url: str = Query(...), title: str = Query(...),
    source: str = Query("b"),
):
    if not _signed_in(request):
        return JSONResponse({"error": "not_signed_in"}, status_code=401)

    entry = LIBRARIES.get(source)
    if entry is None:
        return {"status": "error", "message": "Unknown source."}

    safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()[:40] or "book"
    filename = f"{safe_title}_{uuid.uuid4().hex[:6]}.pdf"
    filepath = os.path.join(DOWNLOAD_DIR, filename)

    try:
        scraper = entry[1]
        if hasattr(scraper, "consult_download"):
            scraper.consult_download(book_page_url, title, filepath)
        else:
            scraper.download(book_page_url, title, filepath)

        log_user_activity(request, "Download", f"డౌన్‌లోడ్: '{title}' ({entry[0]})", "Success",
                          book_title=title, book_url=book_page_url, source_code=source)
        return {
            "status": "success",
            "message": "పుస్తకం విజయవంతంగా డౌన్‌లోడ్ చేయబడింది!",
            "filename": filename,
            "download_url": f"/download-file?filename={quote(filename)}",
        }
    except Exception as e:
        log_user_activity(request, "Download", f"విఫలం: '{title}' ({entry[0]}) | {e}", "Failed",
                          book_title=title, book_url=book_page_url, source_code=source)
        return {"status": "error", "message": str(e)}


@app.get("/download-file")
def download_file(request: Request, filename: str = Query(...)):
    """Serve a saved PDF as a file download (attachment) rather than inline.

    Browsers render large scanned PDFs very slowly in a tab; sending
    Content-Disposition: attachment saves the file straight to the user's disk.
    """
    if not _signed_in(request):
        return RedirectResponse(url="/login/google", status_code=303)

    # os.path.basename prevents path traversal (e.g. '../../etc/passwd')
    safe_name = os.path.basename(filename)
    filepath = os.path.join(DOWNLOAD_DIR, safe_name)
    if not os.path.exists(filepath):
        return {"error": "File not found"}
    return FileResponse(filepath, media_type='application/pdf', filename=safe_name)


# With sign-in switched off, the account routes are removed rather than merely hidden,
# so a standalone copy has no login page, no profile and no admin to stumble into.
if not LOGIN_ENABLED:
    ACCOUNT_ROUTES = {
        "/login/google",
        "/auth/callback",
        "/logout",
        "/profile",
        "/user/activity-json",
        "/admin",
        "/admin/users-json",
    }
    app.router.routes = [
        route for route in app.router.routes
        if getattr(route, "path", None) not in ACCOUNT_ROUTES
    ]
