# legacy/

These files are **not** part of the deployed web service. They were moved here from
the repository root so the deployable app stays clean. Nothing imports them.

| File | What it is |
| --- | --- |
| `download_book.py` | Standalone Selenium script that screenshots a book viewer and stitches a PDF. Needs `selenium`, `PIL`, `img2pdf`, Chrome — not in `requirements.txt`. |
| `ocr_desktop_app.py` | A Streamlit desktop OCR/RAG tool with a hardcoded Windows path. |
| `sundarayya_downloader.py`, `sundarayya_scraper.py`, `sundarayya_search_downloader.py` | One-off CLI scrapers for sundarayya.org. |
| `working.py` | An early prototype FastAPI app (duplicate of parts of `backend/main.py`). |
| `manasuclass.py` | An early Manasu scraper that is broken (missing imports); superseded by `backend/manasu.py`. |
| `working.html` | A scratch frontend variant. |

To run any of them, install its own dependencies separately.
