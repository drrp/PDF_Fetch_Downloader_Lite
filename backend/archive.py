import requests
import json
from io import BytesIO
from pypdf import PdfWriter

# Internet Archive results are restricted to Telugu texts, and a few prolific
# government / legal uploaders are excluded because their content is unrelated to
# the literature this app is for.
#
# The language filter is deliberately broad (items are tagged in several ways), and
# the filters are applied in decreasing order of strictness so a search never comes
# back empty just because an item lacked a language tag.
IA_LANGUAGE_CLAUSE = "(language:Telugu OR language:telugu OR language:tel OR language:te)"
IA_EXCLUDED_CREATORS = (
    "High Court for State of Telangana",
    "Government of Andhra Pradesh",
    "Government of Telangana",
)
# Substrings that mark an uploader as out of scope, matched case-insensitively.
# Internet Archive's query parser is unreliable for exclusions, so these are also
# applied in Python once the results come back.
IA_EXCLUDED_CREATOR_PATTERNS = (
    "government of",
    "high court",
)


class InternetArchiveScraper:
    def __init__(self):
        # Official Internet Archive APIs
        self.search_api_url = "https://archive.org/advancedsearch.php"
        self.metadata_api_url = "https://archive.org/metadata"
        self.download_base_url = "https://archive.org/download"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }

    def _query_variants(self, query: str):
        """Queries to try, strictest first (Internet Archive uses Lucene syntax).

        Per the Archive's search documentation, exclusions use `AND NOT`; the bare
        `-` form is not reliable. The caller falls back to the next variant when a
        query matches nothing.
        """
        base = f"({query})"
        exclude = "".join(f' AND NOT creator:"{c}"' for c in IA_EXCLUDED_CREATORS)
        return [
            f"{base} AND mediatype:texts AND {IA_LANGUAGE_CLAUSE}{exclude}",
            f"{base} AND mediatype:texts{exclude}",
            f"{base}",
        ]

    def search(self, query: str):
        # Try the strictest filter first and fall back if it finds nothing, so a
        # strict query can never turn a good search into an empty one.
        for q in self._query_variants(query):
            books = self._search_once(q)
            if books:
                return books
        return []

    def _is_excluded_creator(self, creator_text) -> bool:
        """True when the uploader is one of the out-of-scope government/legal ones."""
        if not creator_text:
            return False
        low = str(creator_text).lower()
        return any(pattern in low for pattern in IA_EXCLUDED_CREATOR_PATTERNS)

    def _search_once(self, q: str):
        all_books = []
        page = 1
        rows = 100  # Fetches up to 100 results at once
        
        session = requests.Session()
        session.headers.update(self.headers)
        
        while True:
            params = {
                "q": q,
                # 'fl[]' లో description, year/date లను కూడా యాడ్ చేసాము
                "fl[]": ["identifier", "title", "creator", "description", "year", "date"],
                "rows": rows, 
                "page": page,
                "output": "json"
            }
            
            try:
                response = session.get(self.search_api_url, params=params, timeout=20)
                if response.status_code != 200:
                    break
                    
                data = response.json()
                docs = data.get("response", {}).get("docs", [])
                
                if not docs:
                    break
                    
                for doc in docs:
                    identifier = doc.get("identifier")
                    if not identifier:
                        continue
                        
                    title = doc.get("title", "Unknown Title")
                    creator = doc.get("creator", "Unknown Author")
                    
                    if isinstance(creator, list):
                        creator = ", ".join(creator)

                    # The query clause is best-effort; this filter guarantees it.
                    if self._is_excluded_creator(creator):
                        continue

                    full_title = f"{title} - {creator}" if creator else title
                    cover_image = f"https://archive.org/services/img/{identifier}"
                    book_page_url = f"https://archive.org/details/{identifier}"
                    
                    # వివరణ మరియు సంవత్సరాన్ని సురక్షితంగా హ్యాండిల్ చేయడం
                    raw_desc = doc.get("description", "")
                    if isinstance(raw_desc, list):
                        raw_desc = " ".join(raw_desc)
                    description_text = raw_desc[:150] + "..." if len(str(raw_desc)) > 150 else raw_desc

                    raw_year = doc.get("year") or doc.get("date", "")
                    if isinstance(raw_year, list):
                        raw_year = raw_year[0] if raw_year else ""
                    year_text = str(raw_year)[:4]  # కేవలం YYYY మాత్రమే

                    all_books.append({
                        "title": full_title,
                        "download_url": book_page_url,
                        "cover_image": cover_image,
                        "source": "Internet Archive",
                        "description": description_text,
                        "author": creator,
                        "year": year_text
                    })
                
                if len(docs) < rows:
                    break
                    
                page += 1
                
            except Exception as e:
                print(f"Internet Archive API Search Error on page {page}: {e}")
                break
                
        return all_books

    def resolve(self, book_page_url: str):
        """Return (pdf_url, headers) for an item, without downloading anything.

        Lets the browser fetch the PDF straight from archive.org, so the file never
        passes through this server and costs it no bandwidth.
        """
        session = requests.Session()
        session.headers.update(self.headers)

        identifier = book_page_url.split("/details/")[-1].split("/")[0].split("?")[0]
        meta_res = session.get(f"{self.metadata_api_url}/{identifier}", timeout=20)
        if meta_res.status_code != 200:
            raise Exception("Failed to fetch metadata from Internet Archive API.")

        files = (meta_res.json() or {}).get("files", [])
        pdf_filename = next(
            (f.get("name") for f in files if f.get("name", "").lower().endswith(".pdf")),
            None,
        )
        if not pdf_filename:
            raise Exception("PDF format is not available for this book on Internet Archive.")

        return f"{self.download_base_url}/{identifier}/{pdf_filename}", dict(self.headers)

    def download(self, book_page_url: str, title: str, filepath: str, progress=None):
        session = requests.Session()
        session.headers.update(self.headers)
        
        identifier = book_page_url.split("/details/")[-1].split("/")[0].split("?")[0]
        metadata_url = f"{self.metadata_api_url}/{identifier}"
        
        try:
            meta_res = session.get(metadata_url, timeout=20)
            if meta_res.status_code != 200:
                raise Exception("Failed to fetch metadata from Internet Archive API.")
                
            data = meta_res.json()
            files = data.get("files", [])
            
            pdf_filename = None
            for file_info in files:
                if file_info.get("name", "").lower().endswith(".pdf"):
                    pdf_filename = file_info["name"]
                    break
                    
            if not pdf_filename:
                raise Exception("PDF format is not available for this book on Internet Archive.")
                
            download_url = f"{self.download_base_url}/{identifier}/{pdf_filename}"
            
            res = session.get(download_url, stream=True, timeout=(15, 300))
            if res.status_code == 200:
                total = int(res.headers.get("content-length") or 0)
                received = 0
                with open(filepath, "wb") as f:
                    for chunk in res.iter_content(chunk_size=32768):
                        if chunk:
                            f.write(chunk)
                            received += len(chunk)
                            if progress:
                                progress(received, total)
            else:
                raise Exception("Failed to download PDF file stream.")
                
        except Exception as e:
            raise Exception(f"Internet Archive API Download Error: {e}")