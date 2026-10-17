import warnings
warnings.filterwarnings("ignore", message=".*httpx module is deprecated.*")
warnings.filterwarnings("ignore", module="authlib")

import os
import requests
import re
import uuid
import psycopg2
from psycopg2.extras import RealDictCursor
import time
import pytz
from authlib.integrations.starlette_client import OAuth
from dotenv import load_dotenv
from fastapi import Form
from fastapi import FastAPI, Query, Request, Depends
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime
from urllib.parse import quote
from backend.svk import SVKScraper
from backend.archive import InternetArchiveScraper
from backend.manasu import ManasuFoundationScraper
from backend.ttd import TTDScraper
from starlette.middleware.sessions import SessionMiddleware

load_dotenv(override=True)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
FRONTEND_INDEX = os.path.join(FRONTEND_DIR, "index.html")
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")

# Render Environment Variable నుండి Supabase కనెక్షన్ లింక్ తీసుకుంటుంది
DB_URL = os.getenv("DATABASE_URL")

# --- Config (override any of these via environment variables) ---
# Email that gets the admin dashboard.
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "rpsarma9247@gmail.com")
# Send the login cookie only over HTTPS. Set COOKIE_HTTPS_ONLY=false for plain-HTTP local dev.
COOKIE_HTTPS_ONLY = os.getenv("COOKIE_HTTPS_ONLY", "true").strip().lower() in ("1", "true", "yes", "on")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# --- Startup diagnostics: prints only whether each variable is present, never its value ---
print(
    "Startup config check ->",
    "DATABASE_URL:", bool(DB_URL),
    "| SESSION_SECRET_KEY:", bool(os.getenv("SESSION_SECRET_KEY")),
    "| GOOGLE_CLIENT_ID:", bool(os.getenv("GOOGLE_CLIENT_ID")),
    "| GOOGLE_CLIENT_SECRET:", bool(os.getenv("GOOGLE_CLIENT_SECRET")),
)


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
        
        # Users Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                name TEXT,
                picture TEXT,
                last_login TEXT,
                is_active BOOLEAN DEFAULT FALSE
            )
        ''')
        
        # Activities Table
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
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error initializing DB: {e}")

init_db()

app = FastAPI()

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET_KEY", "your-secret-key"),
    same_site="lax",
    https_only=COOKIE_HTTPS_ONLY
)

oauth = OAuth()
oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

def log_user_activity(request: Request, action_type: str, details: str, status: str = "Success"):
    user = request.session.get('user')
    if user:
        try:
            IST = pytz.timezone('Asia/Kolkata')
            current_time = datetime.now(IST).strftime("%d-%m-%Y %I:%M %p")
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO activities (email, name, picture, action, details, time, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (user.get("email"), user.get("name"), user.get("picture"), action_type, details, current_time, status))
            cursor.execute('UPDATE users SET is_active = TRUE WHERE email = %s', (user.get("email"),))
            conn.commit()
            conn.close()
        except Exception as e:
            print("DB Error logging activity:", e)

@app.get('/profile')
def user_profile_page(request: Request):
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/login/google', status_code=303)
    
    profile_page = os.path.join(FRONTEND_DIR, "profile.html")
    return FileResponse(profile_page) if os.path.exists(profile_page) else {"error": "profile.html not found"}

@app.get('/user/activity-json')
def get_user_activity_json(request: Request):
    user = request.session.get('user')
    if not user:
        return {"error": "Unauthorized"}
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # యూజర్ యొక్క కార్యకలాపాలు (Activities) తెప్పించడం
        cursor.execute("SELECT action, details, time, status FROM activities WHERE email = %s ORDER BY id DESC", (user.get('email'),))
        activities = [dict(row) for row in cursor.fetchall()]
        
        # గణాంకాలు (Stats) లెక్కించడం
        searches_count = sum(1 for a in activities if a['action'] == 'Search')
        downloads_count = sum(1 for a in activities if a['action'] == 'Download' and a['status'] == 'Success')
        
        conn.close()
        
        return {
            "user": user,
            "stats": {
                "searches": searches_count,
                "downloads": downloads_count
            },
            "activities": activities
        }
    except Exception as e:
        return {"error": str(e)}

@app.get('/login/google')
async def login(request: Request):
    redirect_uri = request.url_for('auth')
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get('/auth/callback')
async def auth(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get('userinfo') or token.get('user_info')
        if not user_info:
            resp = await oauth.google.get('https://www.googleapis.com/oauth2/v3/userinfo', token=token)
            user_info = resp.json()
        
        if user_info and user_info.get('email'):
            user_dict = {
                "name": user_info.get("name"),
                "email": user_info.get("email"),
                "picture": user_info.get("picture")
            }
            request.session['user'] = user_dict
            
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            IST = pytz.timezone('Asia/Kolkata')
            login_time = datetime.now(IST).strftime("%d-%m-%Y %I:%M %p")
            
            cursor.execute('SELECT email FROM users WHERE email = %s', (user_dict.get('email'),))
            existing = cursor.fetchone()
            
            if existing:
                cursor.execute('''
                    UPDATE users SET name = %s, picture = %s, last_login = %s WHERE email = %s
                ''', (user_dict.get('name'), user_dict.get('picture'), login_time, user_dict.get('email')))
            else:
                cursor.execute('''
                    INSERT INTO users (email, name, picture, last_login, is_active)
                    VALUES (%s, %s, %s, %s, TRUE)
                ''', (user_dict.get('email'), user_dict.get('name'), user_dict.get('picture'), login_time))
            
            conn.commit()
            conn.close()
                
            if user_dict.get('email') == ADMIN_EMAIL:
                return RedirectResponse(url='/admin', status_code=303)
                
    except Exception as e:
        print(f"OAuth Error: {e}")
        
    return RedirectResponse(url='/', status_code=303)

@app.get('/admin')
def admin_dashboard(request: Request):
    user = request.session.get('user')
    if not user or user.get('email') != ADMIN_EMAIL:
        return RedirectResponse(url='/')
    admin_page = os.path.join(FRONTEND_DIR, "admin.html")
    return FileResponse(admin_page) if os.path.exists(admin_page) else {"error": "admin.html not found"}

@app.get('/admin/users-json')
def get_admin_users_json(request: Request):
    user = request.session.get('user')
    if not user or user.get('email') != ADMIN_EMAIL:
        return {"error": "Unauthorized Access"}
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM users")
    users = [dict(row) for row in cursor.fetchall()]
    cursor.execute("SELECT * FROM activities ORDER BY id DESC")
    activities = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return {
        "total_users": len(users), 
        "users": users,
        "activities": activities,
        "stats": {
            "searches": sum(1 for a in activities if a['action'] == 'Search'),
            "downloads": sum(1 for a in activities if a['action'] == 'Download'),
            "total_actions": len(activities)
        }
    }


@app.get('/api/current-user')
def get_current_user(request: Request):
    user = request.session.get('user')
    if not user:
        return {"logged_in": False}
    return {
        "logged_in": True, "name": user.get("name"), "email": user.get("email"),
        "picture": user.get("picture"), "is_admin": (user.get("email") == ADMIN_EMAIL)
    }

@app.get('/logout')
def logout(request: Request):
    user = request.session.get('user')
    if user:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET is_active = FALSE WHERE email = %s', (user.get('email'),))
            conn.commit()
            conn.close()
        except: pass
    request.session.clear()
    return RedirectResponse(url='/')

@app.post("/reset-app")
def reset_app(request: Request):
    # The dashboard's Reset button reloads the page client-side; this endpoint
    # only acknowledges the request so the frontend fetch() does not error.
    return {"status": "ok"}

if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/downloads", StaticFiles(directory=DOWNLOAD_DIR), name="downloads")

@app.get("/")
def read_root(request: Request):
    user = request.session.get('user')
    if not user:
        login_page = os.path.join(FRONTEND_DIR, "login.html")
        return FileResponse(login_page) if os.path.exists(login_page) else RedirectResponse(url='/login/google')
    if os.path.exists(FRONTEND_INDEX):
        return FileResponse(FRONTEND_INDEX)
    return {"error": "index.html not found"}

svk_scraper = SVKScraper()
ia_scraper = InternetArchiveScraper()
manasu_scraper = ManasuFoundationScraper()
ttd_scraper = TTDScraper()

@app.get("/search")
def search(
    request: Request, query: str = Query(...),
    use_svk: bool = Query(True), use_ia: bool = Query(True),
    use_manasu: bool = Query(True), use_ttd: bool = Query(True),
    page: int = Query(1), limit: int = Query(10)
):
    log_user_activity(request, "Search", f"వెతికిన పదం: '{query}'")
    results = []
    if use_svk: results.extend(svk_scraper.search(query))
    if use_ia: results.extend(ia_scraper.search(query))
    if use_manasu: results.extend(manasu_scraper.search(query))
    if use_ttd: results.extend(ttd_scraper.search(query))
        
    total_items = len(results)
    start_idx = (page - 1) * limit
    paginated_results = results[start_idx:start_idx + limit]
    
    return {
        "results": paginated_results, "total": total_items,
        "page": page, "total_pages": (total_items + limit - 1) // limit if total_items > 0 else 1
    }

@app.get("/download-book")
def download_book(request: Request, book_page_url: str = Query(...), title: str = Query(...), source: str = Query("SVK")):
    safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()[:40] or "book"
    filename = f"{safe_title}_{uuid.uuid4().hex[:6]}.pdf"
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    
    try:
        if source == "Internet Archive": 
            ia_scraper.download(book_page_url, title, filepath)
        elif source == "Manasu Foundation": 
            manasu_scraper.consult_download(book_page_url, title, filepath) if hasattr(manasu_scraper, 'consult_download') else manasu_scraper.download(book_page_url, title, filepath)
        elif source == "TTD Ebooks": 
            ttd_scraper.download(book_page_url, title, filepath)
        else: 
            svk_scraper.download(book_page_url, title, filepath)
            
        log_user_activity(request, "Download", f"డౌన్‌లోడ్: '{title}' ({source})", "Success")
        return {
            "status": "success",
            "message": "పుస్తకం విజయవంతంగా డౌన్‌లోడ్ చేయబడింది!",
            "file_url": f"/downloads/{filename}",
            "filename": filename,
            "download_url": f"/download-file?filename={quote(filename)}",
        }
    except Exception as e:
        log_user_activity(request, "Download", f"విఫలం: '{title}' | ఎర్రర్: {str(e)}", "Failed")
        return {"status": "error", "message": str(e)}

@app.get("/download-file")
def download_file(request: Request, filename: str = Query(...)):
    """Serve a saved PDF as a file download (attachment) rather than inline.

    Browsers render large scanned PDFs very slowly in a tab; sending
    Content-Disposition: attachment saves the file straight to the user's disk.
    """
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/login/google', status_code=303)
    # os.path.basename prevents path traversal (e.g. '../../etc/passwd')
    safe_name = os.path.basename(filename)
    filepath = os.path.join(DOWNLOAD_DIR, safe_name)
    if not os.path.exists(filepath):
        return {"error": "File not found"}
    return FileResponse(filepath, media_type='application/pdf', filename=safe_name)



    


# Books that use the strict సూత్రము / వృత్తి / ఉదాహరణలు grammar template.
# Every other book gets the general, template-free answer below.













    

