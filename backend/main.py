import warnings
warnings.filterwarnings("ignore", message=".*httpx module is deprecated.*")

import concurrent.futures
import os
import re
import uuid
from urllib.parse import quote

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
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


@app.get("/download-book")
def download_book(book_page_url: str = Query(...), title: str = Query(...), source: str = Query("SVK")):
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

        return {
            "status": "success",
            "message": "పుస్తకం విజయవంతంగా డౌన్‌లోడ్ చేయబడింది!",
            "file_url": f"/downloads/{filename}",
            "filename": filename,
            "download_url": f"/download-file?filename={quote(filename)}",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


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
