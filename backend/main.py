import warnings
warnings.filterwarnings("ignore", message=".*httpx module is deprecated.*")

import concurrent.futures
import os
import re
import uuid
from urllib.parse import quote

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
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


def _content_disposition(filename: str) -> str:
    """Build a Content-Disposition header that can carry a Telugu file name.

    HTTP headers are latin-1, so a Telugu title cannot go in `filename=` directly;
    it is sent RFC 5987 style in `filename*`, with an ASCII fallback alongside.
    """
    # A fully Telugu title leaves nothing behind, so fall back to a generic name.
    base = filename[:-4] if filename.lower().endswith(".pdf") else filename
    ascii_name = base.encode("ascii", "ignore").decode("ascii").strip(" .") or "book"
    return f"attachment; filename=\"{ascii_name}.pdf\"; filename*=UTF-8''{quote(filename)}"


def _fetch_to_disk(source: str, book_page_url: str, title: str, filepath: str):
    """Fetch a book to disk. Used where the source cannot be streamed."""
    if source == "Manasu Foundation":
        if hasattr(manasu_scraper, "consult_download"):
            manasu_scraper.consult_download(book_page_url, title, filepath)
        else:
            manasu_scraper.download(book_page_url, title, filepath)
    elif source == "TTD Ebooks":
        ttd_scraper.download(book_page_url, title, filepath)
    else:
        svk_scraper.download(book_page_url, title, filepath)


@app.get("/download-check")
def download_check(book_page_url: str = Query(...), title: str = Query("book"), source: str = Query("SVK")):
    """Preflight before the browser starts downloading.

    The download itself is a browser navigation, so a failure there would just save
    an error page. Checking first lets us show a proper message instead. Sources that
    cannot be streamed (Google Drive, TTD) are fetched to disk here, and the stream
    step then simply serves that file.
    """
    try:
        if source == "Internet Archive":
            ia_scraper.resolve(book_page_url)
            return {"ok": True}
        if source == "SVK":
            svk_scraper.resolve(book_page_url)
            return {"ok": True}

        # Google Drive and TTD need the file itself, so fetch it now.
        prepared = f"{_safe_book_name(title, 40)}_{uuid.uuid4().hex[:6]}.pdf"
        _fetch_to_disk(source, book_page_url, title, os.path.join(DOWNLOAD_DIR, prepared))
        return {"ok": True, "prepared": prepared}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.get("/download-book")
def download_book(
    book_page_url: str = Query(...), title: str = Query(...),
    source: str = Query("SVK"), prepared: str = Query(""),
):
    """Stream the book to the browser.

    The response headers go out immediately, so the browser's own download manager
    starts at once and shows real progress - no waiting dialog. Where the source
    offers a direct PDF URL (Internet Archive, SVK) the file is streamed straight
    through; otherwise the file fetched during the preflight is served.
    """
    filename = f"{_safe_book_name(title)}.pdf"

    if prepared:
        path = os.path.join(DOWNLOAD_DIR, os.path.basename(prepared))
        if os.path.exists(path):
            return FileResponse(path, media_type="application/pdf", filename=filename)
        return Response(
            "Download failed: the prepared file is no longer available.",
            media_type="text/plain",
            headers={"Content-Disposition": 'attachment; filename="download-error.txt"'},
        )

    if source in ("Manasu Foundation", "TTD Ebooks"):
        # Not streamable - fetch it first, then serve the file.
        path = os.path.join(DOWNLOAD_DIR, f"{_safe_book_name(title, 40)}_{uuid.uuid4().hex[:6]}.pdf")
        try:
            _fetch_to_disk(source, book_page_url, title, path)
        except Exception as e:
            return Response(
                f"Download failed: {e}", media_type="text/plain",
                headers={"Content-Disposition": 'attachment; filename="download-error.txt"'},
            )
        return FileResponse(path, media_type="application/pdf", filename=filename)

    try:
        if source == "Internet Archive":
            direct_url, direct_headers = ia_scraper.resolve(book_page_url)
        else:
            direct_url, direct_headers = svk_scraper.resolve(book_page_url)
    except Exception as e:
        return Response(
            f"Download failed: {e}", media_type="text/plain",
            headers={"Content-Disposition": 'attachment; filename="download-error.txt"'},
        )

    def body():
        with requests.get(direct_url, headers=direct_headers, stream=True, timeout=(20, 300)) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    yield chunk

    return StreamingResponse(
        body(), media_type="application/pdf",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


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
