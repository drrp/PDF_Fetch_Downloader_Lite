import warnings
warnings.filterwarnings("ignore", message=".*httpx module is deprecated.*")

import concurrent.futures
import os
import re
import uuid

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.svk import SVKScraper
from backend.archive import InternetArchiveScraper
from backend.manasu import ManasuFoundationScraper
from backend.ttd import TTDScraper

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
FRONTEND_INDEX = os.path.join(FRONTEND_DIR, "index.html")
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app = FastAPI(title="PDF Fetch Downloader (Search & Download)")

if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/downloads", StaticFiles(directory=DOWNLOAD_DIR), name="downloads")

svk_scraper = SVKScraper()
ia_scraper = InternetArchiveScraper()
manasu_scraper = ManasuFoundationScraper()
ttd_scraper = TTDScraper()


@app.post("/reset-app")
def reset_app():
    # The dashboard's Reset button reloads the page client-side; this endpoint
    # only acknowledges the request so the frontend fetch() does not error.
    return {"status": "ok"}


@app.get("/")
def read_root():
    if os.path.exists(FRONTEND_INDEX):
        return FileResponse(FRONTEND_INDEX)
    return {"error": "index.html not found"}


@app.get("/search")
def search(
    query: str = Query(...),
    use_svk: bool = Query(True), use_ia: bool = Query(True),
    use_manasu: bool = Query(True), use_ttd: bool = Query(True),
    page: int = Query(1), limit: int = Query(0),
):
    # The four libraries are independent, so query them at the same time: the
    # request now takes about as long as the slowest library, not the sum of all.
    sources = []
    if use_svk: sources.append(("SVK", svk_scraper))
    if use_ia: sources.append(("Internet Archive", ia_scraper))
    if use_manasu: sources.append(("Manasu Foundation", manasu_scraper))
    if use_ttd: sources.append(("TTD Ebooks", ttd_scraper))

    results = []
    if sources:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(sources)) as ex:
            futures = [(name, ex.submit(s.search, query)) for name, s in sources]
            for name, fut in futures:          # collect in a fixed order
                try:
                    results.extend(fut.result())
                except Exception as e:
                    print(f"{name} search error: {e}")

    total_items = len(results)
    # limit=0 (the default) returns everything; the frontend paginates locally.
    if limit and limit > 0:
        start_idx = (page - 1) * limit
        paginated_results = results[start_idx:start_idx + limit]
        total_pages = (total_items + limit - 1) // limit if total_items > 0 else 1
    else:
        paginated_results = results
        total_pages = 1

    return {
        "results": paginated_results, "total": total_items,
        "page": page, "total_pages": total_pages
    }


def _safe_book_name(title: str, limit: int = 60) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", title).strip()[:limit] or "book"


def _looks_like_pdf(path: str) -> bool:
    """Cheap sanity check, so a corrupt or HTML response is never handed to the user."""
    try:
        with open(path, "rb") as f:
            return b"%PDF-" in f.read(1024)
    except OSError:
        return False


def _fetch_to_disk(source: str, book_page_url: str, title: str, filepath: str):
    """Fetch a book to disk using the scraper for its source."""
    if source == "Internet Archive":
        ia_scraper.download(book_page_url, title, filepath)
    elif source == "Manasu Foundation":
        if hasattr(manasu_scraper, "consult_download"):
            manasu_scraper.consult_download(book_page_url, title, filepath)
        else:
            manasu_scraper.download(book_page_url, title, filepath)
    elif source == "TTD Ebooks":
        ttd_scraper.download(book_page_url, title, filepath)
    else:
        svk_scraper.download(book_page_url, title, filepath)


def _new_book_path(title: str) -> str:
    return f"{_safe_book_name(title, 40)}_{uuid.uuid4().hex[:6]}.pdf"


def _error_download(message: str) -> Response:
    return Response(
        f"Download failed: {message}",
        media_type="text/plain",
        headers={"Content-Disposition": 'attachment; filename="download-error.txt"'},
    )


@app.get("/download-check")
def download_check(book_page_url: str = Query(...), title: str = Query("book"), source: str = Query("SVK")):
    """Fetch the book to disk before the browser starts downloading.

    The browser download is a plain navigation, so a failure there would just save an
    error page. Fetching first lets us report problems properly - and the result is
    checked to be a real PDF before it is offered.
    """
    prepared = _new_book_path(title)
    path = os.path.join(DOWNLOAD_DIR, prepared)

    try:
        _fetch_to_disk(source, book_page_url, title, path)
    except Exception as e:
        return {"ok": False, "message": str(e)}

    if not _looks_like_pdf(path):
        try:
            os.remove(path)
        except OSError:
            pass
        return {
            "ok": False,
            "message": "ఈ గ్రంథాలయం నుండి వచ్చిన ఫైల్ సరైన PDF కాదు. దయచేసి మరో పుస్తకం ప్రయత్నించండి.",
        }

    return {"ok": True, "prepared": prepared}


@app.get("/download-book")
def download_book(
    book_page_url: str = Query(""), title: str = Query(...),
    source: str = Query("SVK"), prepared: str = Query(""),
):
    """Serve an already-fetched book as a file download.

    The file is sent from disk with Content-Length, so the browser shows real
    progress and saves exactly the bytes the scraper fetched.
    """
    filename = f"{_safe_book_name(title)}.pdf"

    if not prepared:
        # Reached directly, without the preflight: fetch it now, then serve it.
        prepared = _new_book_path(title)
        try:
            _fetch_to_disk(source, book_page_url, title, os.path.join(DOWNLOAD_DIR, prepared))
        except Exception as e:
            return _error_download(str(e))

    path = os.path.join(DOWNLOAD_DIR, os.path.basename(prepared))
    if not os.path.exists(path):
        return _error_download("the prepared file is no longer available")

    return FileResponse(path, media_type="application/pdf", filename=filename)


@app.get("/download-file")
def download_file(filename: str = Query(...)):
    """Serve a saved PDF as a file download (attachment) rather than inline.

    Browsers render large scanned PDFs very slowly in a tab; sending
    Content-Disposition: attachment saves the file straight to the user's disk.
    """
    # os.path.basename prevents path traversal (e.g. '../../etc/passwd')
    safe_name = os.path.basename(filename)
    filepath = os.path.join(DOWNLOAD_DIR, safe_name)
    if not os.path.exists(filepath):
        return {"error": "File not found"}
    return FileResponse(filepath, media_type='application/pdf', filename=safe_name)
