import os
import time
import requests
from bs4 import BeautifulSoup
import concurrent.futures
import re

# --- బేస్ క్లాస్‌ని ఇక్కడ డిఫైన్ చేయండి ---
class BaseLibraryScraper:
    def search(self, query: str):
        raise NotImplementedError
    
    def download(self, book_url: str, title: str, filepath: str):
        raise NotImplementedError

class TTDScraper(BaseLibraryScraper):
    # Time budget (seconds) for one whole download, shared across every retry, so a
    # stalled server can never hang the request for tens of minutes.
    TOTAL_BUDGET = 180
    # Longest we wait for data between chunks on a single request.
    READ_CAP = 120

    def __init__(self):
        self.base_domain = "https://ebooks.tirumala.org"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9,te;q=0.8"
        }

    def search(self, query: str):
        all_books = []
        url = f"{self.base_domain}/search"
        seen_urls = set()
        
        # టైటిల్ మరియు ఆథర్ సెర్చ్ కీలు
        search_keys = ["search", "author"]
        
        # నెట్‌వర్క్ రిక్వెస్ట్ చేసే చిన్న ఫంక్షన్
        def fetch_data(key):
            try:
                params = {"value": query, "key": key}
                # ఇక్కడ ప్రత్యేకంగా session కాకుండా డైరెక్ట్ requests.get వాడటం త్రెడింగ్‌లో సురక్షితం
                response = requests.get(url, params=params, headers=self.headers, timeout=60)
                if response.status_code == 200:
                    return response.text
            except Exception as e:
                print(f"TTD Ebooks Search Error for key '{key}': {e}")
            return None

        # --- Multi-threading లాజిక్ ఇక్కడే మొదలవుతుంది ---
        # రెండు రిక్వెస్ట్‌లను ఒకేసారి పంపి డేటాను లాగుతుంది!
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            html_responses = list(executor.map(fetch_data, search_keys))
            
        # వచ్చిన రిజల్ట్స్ ని పార్స్ చేయడం (పాత లాజిక్)
        for html in html_responses:
            if not html:
                continue

            soup = BeautifulSoup(html, "html.parser")
            results_list = soup.find("div", class_="results-list")
            if not results_list:
                continue

            cards = results_list.find_all("div", class_="stripc")
            
            for card in cards:
                link_tag = card.select_one(".stripc-part1 a")
                if not link_tag:
                    continue

                href = link_tag.get("href")
                if not href:
                    continue

                # డూప్లికేట్స్ తీసెయ్యడం
                detail_url = f"{self.base_domain}/{href}" if not href.startswith("http") else href
                if detail_url in seen_urls:
                    continue
                seen_urls.add(detail_url)

                title_tag = card.select_one(".stripc-part2 h6")
                title_text = title_tag.get_text(strip=True) if title_tag else "Unknown Title"
                
                author_tag = card.select_one(".stripc-part2 p")
                if author_tag:
                    author_text = author_tag.get_text(strip=True).replace("By :", "").strip()
                    if author_text:
                        title_text = f"{title_text} ({author_text})"

                cover_url = ""
                img_tag = link_tag.find("img")
                if img_tag and img_tag.get("src"):
                    src = img_tag.get("src")
                    cover_url = f"{self.base_domain}/{src}" if not src.startswith("http") else src

                all_books.append({
                    "title": title_text,
                    "download_url": detail_url,
                    "cover_image": cover_url,
                    "source": "TTD Ebooks"
                })
                
        return all_books

    def download(self, book_page_url: str, title: str, filepath: str):
        match = re.search(r"id=(\d+)", book_page_url)
        if not match:
            raise Exception("Could not find publication ID for this TTD ebook.")

        book_id = match.group(1)
        candidate_urls = [
            f"{self.base_domain}/download.php?id={book_id}",
            f"{self.base_domain}/uploads/pdf/{book_id}.pdf",
        ]

        session = requests.Session()
        session.headers.update(self.headers)

        # One shared time budget for the whole operation. Every request below is
        # bounded by whatever is left of it, so the call always returns within
        # about TOTAL_BUDGET seconds no matter how badly the server behaves.
        deadline = time.monotonic() + self.TOTAL_BUDGET

        def remaining():
            return deadline - time.monotonic()

        last_error = ""
        timed_out = False

        for attempt in range(1, 3):  # up to 2 tries
            if remaining() <= 0:
                break

            # Warm up the reader page so the download endpoint sees a session.
            try:
                session.get(book_page_url, timeout=(10, min(30, remaining())))
            except requests.exceptions.RequestException:
                pass  # not fatal on its own

            for url in candidate_urls:
                if remaining() <= 0:
                    break
                try:
                    download_headers = {"Referer": book_page_url}
                    resp = session.get(
                        url,
                        headers=download_headers,
                        stream=True,
                        timeout=(min(20, remaining()), min(self.READ_CAP, remaining())),
                    )
                    if resp.status_code != 200:
                        last_error = f"HTTP {resp.status_code} from {url}"
                        continue

                    with open(filepath, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                            if remaining() <= 0:
                                raise requests.exceptions.Timeout("exceeded time budget")

                    # Make sure we actually received a PDF, not an HTML error page.
                    with open(filepath, "rb") as f:
                        header = f.read(5)
                    if header != b"%PDF-":
                        try:
                            os.remove(filepath)
                        except OSError:
                            pass
                        last_error = "The TTD server returned a non-PDF response."
                        continue

                    return  # success
                except requests.exceptions.Timeout:
                    timed_out = True
                    last_error = "timeout"
                    continue
                except requests.exceptions.RequestException as e:
                    last_error = str(e)
                    continue

        if timed_out:
            raise Exception(
                f"The TTD server did not respond within about {self.TOTAL_BUDGET} seconds. "
                "This is usually the TTD server being slow, or it blocking requests "
                "from outside India. Try again later, or open the book page directly: "
                f"{book_page_url}"
            )
        raise Exception(
            f"Could not download this TTD ebook. Last error: "
            f"{last_error or 'the download ran out of time'}"
        )