import warnings
warnings.filterwarnings("ignore", message=".*httpx module is deprecated.*")

import concurrent.futures
import os
import re
import uuid
from urllib.parse import quote

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

try:
    import rcssmin
    import rjsmin
except ImportError:  # minification is optional; fall back to serving files as-is
    rcssmin = rjsmin = None

from backend.svk import SVKScraper
from backend.archive import InternetArchiveScraper
from backend.manasu import ManasuFoundationScraper
from backend.ttd import TTDScraper

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
FRONTEND_INDEX = os.path.join(FRONTEND_DIR, "index.html")
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

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
    sources: str = Query(""),
    page: int = Query(1), limit: int = Query(0),
):
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
                    results.append(book)
            except Exception as e:
                print(f"search error [{code}]: {e}")

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
def download_book(book_page_url: str = Query(...), title: str = Query(...), source: str = Query("b")):
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

        return {
            "status": "success",
            "message": "పుస్తకం విజయవంతంగా డౌన్‌లోడ్ చేయబడింది!",
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
