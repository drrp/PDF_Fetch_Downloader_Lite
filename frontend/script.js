const searchBtn = document.getElementById("search-btn");
const queryInput = document.getElementById("query");
const chkSvk = document.getElementById("chk-svk");
const chkIa = document.getElementById("chk-ia");
const chkManasu = document.getElementById("chk-manasu");
const chkTtd = document.getElementById("chk-ttd");
const resultFilter = document.getElementById("result-filter");
const resultsContainer = document.getElementById("results");

// Short library labels for the UI. The full names stay in the data and in the API
// calls; only what is displayed is abbreviated.
const SOURCE_ABBR = {
  "Internet Archive": "IA",
  "SVK": "SVK",
  "Manasu Foundation": "MF",
  "TTD Ebooks": "TTD",
};
const abbr = (source) => SOURCE_ABBR[source] || source;
const statTotal = document.getElementById("stat-total");
const resultsCountLabel = document.getElementById("results-count-label");

// ---------------------------------------------------------
window.addEventListener("DOMContentLoaded", async () => {
  // sessionStorage నుండి పెండింగ్ డౌన్‌లోడ్ లేదా సెర్చ్‌ని చెక్ చేయడం (URL క్లీన్‌గా ఉంటుంది)
  const pendingDlUrl = sessionStorage.getItem('pending_dl_url');
  const pendingDlTitle = sessionStorage.getItem('pending_dl_title');
  const pendingDlSource = sessionStorage.getItem('pending_dl_source');

  if (pendingDlUrl && pendingDlTitle) {
    sessionStorage.removeItem('pending_dl_url');
    sessionStorage.removeItem('pending_dl_title');
    sessionStorage.removeItem('pending_dl_source');

    queryInput.value = pendingDlTitle;
    resultsContainer.innerHTML = "";
    resultsCountLabel.innerText = "రీ-డౌన్‌లోడ్ కోసం సిద్ధంగా ఉన్న పుస్తకం";

    const card = document.createElement("div");
    card.className = "book-card";

    let badgeClass = "badge-svk";
    if (pendingDlSource === "Internet Archive") badgeClass = "badge-ia";
    if (pendingDlSource === "Manasu Foundation") badgeClass = "badge-manasu";
    if (pendingDlSource === "TTD Ebooks") badgeClass = "badge-ttd";

    card.innerHTML = `
        <div class="book-info">
            <div class="no-cover"><i class="fa-solid fa-book"></i></div>
            <div class="book-details-content">
                <span class="badge ${badgeClass}" title="${pendingDlSource}">${abbr(pendingDlSource)}</span>
                <div class="book-title">${pendingDlTitle}</div>
            </div>
        </div>
        <button class="action-btn" onclick="savePdfLocally('${pendingDlUrl}', '${pendingDlTitle.replace(/'/g, "\\'")}', '${pendingDlSource}', this)">
            <i class="fa-solid fa-download"></i> మళ్లీ సేవ్ చేయి
        </button>
    `;
    resultsContainer.appendChild(card);
    return;
  }

  const pendingSearch = sessionStorage.getItem('pending_search');
  if (pendingSearch) {
    sessionStorage.removeItem('pending_search');
    queryInput.value = pendingSearch;
    performSearch();
  }
});

// ఫిల్టర్ మారినప్పుడు వెంటనే మళ్లీ చూపించడం — సర్వర్‌కి కొత్త రిక్వెస్ట్ అవసరం లేదు.
if (resultFilter) {
  resultFilter.addEventListener("input", () => {
    currentPage = 1;
    renderCurrentPageResults();
  });
}
// ---------------------------------------------------------

let allSearchResults = []; // మొత్తం ఫలితాలు స్టోర్ చేసుకోవడానికి
let currentPage = 1;
const itemsPerPage = 10;

async function performSearch(page = 1) {
  currentPage = page;

  // ఒకవేళ మొదటిసారి సెర్చ్ చేస్తుంటే లేదా క్వెరీ మారితేనే సర్వర్‌కి రిక్వెస్ట్ వెళ్తుంది
  if (page === 1 || allSearchResults.length === 0) {
    const query = queryInput.value.trim();
    const useSvk = chkSvk.checked;
    const useIa = chkIa.checked;
    const useManasu = chkManasu.checked;
    const useTtd = chkTtd.checked;

    if (!query) {
      Swal.fire({
        title: "గమనిక",
        text: "దయచేసి శోధన పదాన్ని నమోదు చేయండి.",
        icon: "warning",
        confirmButtonColor: "#1e3a8a",
      });
      return;
    }

    resultsContainer.innerHTML = `
        <div class="status-message">
            <div class="spinner"></div>
            ఎంచుకున్న లైబ్రరీల నుండి పుస్తకాలను వెతుకుతోంది...
        </div>
    `;
    searchBtn.disabled = true;

    try {
      // A new search starts with a clean filter.
      if (resultFilter) resultFilter.value = "";
      // No limit: the server returns everything it finds and we paginate locally.
      const response = await fetch(
        `/search?query=${encodeURIComponent(query)}&use_svk=${useSvk}&use_ia=${useIa}&use_manasu=${useManasu}&use_ttd=${useTtd}`
      );
      const data = await response.json();

      allSearchResults = data.results || [];
      statTotal.innerText = allSearchResults.length;
    } catch (error) {
      resultsContainer.innerHTML =
        '<div class="status-message" style="color: #dc2626;">సమాచారాన్ని పొందడంలో లోపం ఏర్పడింది.</div>';
      searchBtn.disabled = false;
      return;
    } finally {
      searchBtn.disabled = false;
    }
  }

  // లోకల్ డేటా నుండే పేజీకి సరిపడా 10 ఐటమ్స్ కట్ చేసి చూపించడం (ఎలాంటి లోడింగ్ ఉండదు)
  renderCurrentPageResults();
}

// వచ్చిన ఫలితాలను పేరు / రచయిత ఆధారంగా వడపోసే ఫంక్షన్ (ప్లెయిన్ టెక్స్ట్).
function currentResults() {
  const term = resultFilter ? resultFilter.value.trim() : "";
  if (!term) return allSearchResults;

  const needle = term.toLowerCase();
  return allSearchResults.filter(
    (b) =>
      (b.title || "").toLowerCase().includes(needle) ||
      (b.author || "").toLowerCase().includes(needle),
  );
}

function renderCurrentPageResults() {
  resultsContainer.innerHTML = "";

  const books = currentResults();
  const totalBooks = books.length;
  const totalPages = Math.ceil(totalBooks / itemsPerPage) || 1;
  if (currentPage > totalPages) currentPage = totalPages;

  resultsCountLabel.innerText = `మొత్తం: ${totalBooks} పుస్తకాలు (పేజీ ${currentPage} / ${totalPages})`;

  if (totalBooks === 0) {
    resultsContainer.innerHTML =
      '<div class="status-message">ఈ శోధనకు ఎలాంటి పుస్తకాలు లభించలేదు.</div>';
    return;
  }

  const startIdx = (currentPage - 1) * itemsPerPage;
  const endIdx = startIdx + itemsPerPage;
  const pageItems = books.slice(startIdx, endIdx);

 pageItems.forEach((book) => {
      const card = document.createElement("div");
      card.className = "book-card";

      const coverHtml = book.cover_image
        ? `<img src="${book.cover_image}" alt="Cover" class="book-cover" onerror="this.outerHTML='<div class=\\'no-cover\\'>ప్రతి లేదు</div>'">`
        : `<div class="no-cover">ప్రతి లేదు</div>`;

      let badgeClass = "badge-svk";
      if (book.source === "Internet Archive") badgeClass = "badge-ia";
      if (book.source === "Manasu Foundation") badgeClass = "badge-manasu";
      if (book.source === "TTD Ebooks") badgeClass = "badge-ttd";

      // కేవలం టైటిల్, రచయిత, సంవత్సరం మాత్రమే (వివరణ తొలగించబడింది)
      let authorHtml = book.author ? `<div class="book-author"><i class="fa-solid fa-pen-nib"></i> ${book.author}</div>` : '';
      let yearHtml = book.year ? `<span class="book-year">(${book.year})</span>` : '';

      card.innerHTML = `
              <div class="book-info">
                  ${coverHtml}
                  <div class="book-details-content">
                      <span class="badge ${badgeClass}" title="${book.source}">${abbr(book.source)}</span>
                      <div class="book-title">${book.title} ${yearHtml}</div>
                      ${authorHtml}
                  </div>
              </div>
              <button class="action-btn" onclick="savePdfLocally('${book.download_url}', '${book.title.replace(/'/g, "\\'")}', '${book.source}', this)">
                  <i class="fa-solid fa-download"></i> సేవ్ చేయి
              </button>
          `;
      resultsContainer.appendChild(card);
    });

  if (totalPages > 1) {
    renderPagination(currentPage, totalPages);
  }
}

// పేజినేషన్ బటన్స్ కోసం (ఇది పేజీ మారినప్పుడు కేవలం లోకల్ డేటాని మాత్రమే మారుస్తుంది)
function renderPagination(currentPage, totalPages) {
  const paginationDiv = document.createElement("div");
  paginationDiv.className = "pagination-container";
  
  let paginationHtml = `<button class="page-btn" ${currentPage === 1 ? 'disabled' : ''} onclick="changePage(${currentPage - 1})"><i class="fa-solid fa-chevron-left"></i> వెనుకకు</button>`;
  
  for (let i = 1; i <= totalPages; i++) {
    if (i === 1 || i === totalPages || (i >= currentPage - 2 && i <= currentPage + 2)) {
      paginationHtml += `<button class="page-btn ${i === currentPage ? 'active' : ''}" onclick="changePage(${i})">${i}</button>`;
    } else if (i === currentPage - 3 || i === currentPage + 3) {
      paginationHtml += `<span style="padding: 8px; color: #64748b;">...</span>`;
    }
  }

  paginationHtml += `<button class="page-btn" ${currentPage === totalPages ? 'disabled' : ''} onclick="changePage(${currentPage + 1})">తదుపరి <i class="fa-solid fa-chevron-right"></i></button>`;
  
  paginationDiv.innerHTML = paginationHtml;
  resultsContainer.appendChild(paginationDiv);
}

function changePage(page) {
  currentPage = page;
  renderCurrentPageResults();
  window.scrollTo({ top: 0, behavior: 'smooth' }); // పేజీ మారగానే పైకి స్క్రోల్ అవుతుంది
}

async function savePdfLocally(url, title, source, btnElement) {
  const original = btnElement.innerHTML;
  btnElement.disabled = true;
  btnElement.innerHTML =
    '<i class="fa-solid fa-spinner fa-spin"></i> సిద్ధమవుతోంది...';

  const params =
    `book_page_url=${encodeURIComponent(url)}` +
    `&title=${encodeURIComponent(title)}` +
    `&source=${encodeURIComponent(source)}`;

  // Quick preflight. The download itself is a browser navigation, so a failure
  // there would just save an error page; checking first lets us show a proper
  // message instead. (For Google Drive and TTD this also fetches the file.)
  let prepared = "";
  try {
    const check = await fetch(`/download-check?${params}`).then((r) => r.json());
    if (!check.ok) {
      btnElement.disabled = false;
      btnElement.innerHTML = original;
      Swal.fire({
        title: "డౌన్‌లోడ్ కుదరలేదు",
        text: check.message || "ఈ పుస్తకాన్ని డౌన్‌లోడ్ చేయలేకపోయాం.",
        icon: "error",
        confirmButtonColor: "#dc2626",
      });
      return;
    }
    prepared = check.prepared || "";
  } catch (e) {
    // If the preflight itself fails, just try the download anyway.
  }

  // Hand the file straight to the browser: the server streams it, so the browser's
  // own download manager starts immediately and shows the real progress.
  const a = document.createElement("a");
  a.href = `/download-book?${params}&prepared=${encodeURIComponent(prepared)}`;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();

  setTimeout(() => {
    btnElement.disabled = false;
    btnElement.innerHTML = '<i class="fa-solid fa-check"></i> సేవ్ అయింది';
    btnElement.style.backgroundColor = "#1e3a8a";
  }, 2000);
}
let currentFetchController = null;
let downloadProgressInterval = null;
let searchRequestSequence = 0;

function confirmAppReset() {
  Swal.fire({
    title: "అప్లికేషన్‌ను రీసెట్ చేయాలా?",
    text: "అన్ని ఆక్టివ్ డౌన్‌లోడ్‌లు, శోధనలు నిలిపివేయబడతాయి మరియు సెట్టింగ్‌లు రీసెట్ చేయబడతాయి.",
    icon: "warning",
    showCancelButton: true,
    confirmButtonColor: "#dc2626",
    cancelButtonColor: "#64748b",
    confirmButtonText: "అవును, రీసెట్ చేయి",
    cancelButtonText: "రద్దు చేయు",
  }).then(async (result) => {
    if (result.isConfirmed) {
      searchRequestSequence++;
      if (downloadProgressInterval) {
        clearInterval(downloadProgressInterval);
      }
      if (currentFetchController) {
        currentFetchController.abort();
      }

      try {
        await fetch("/reset-app", { method: "POST" });
      } catch (e) {
        console.error("Backend reset notice failed", e);
      }

      Swal.fire({
        title: "రీసెట్ చేయబడింది!",
        text: "అప్లికేషన్ విజయవంతంగా పునఃప్రారంభించబడుతోంది...",
        icon: "success",
        timer: 1200,
        showConfirmButton: false,
      }).then(() => {
        // పేజీని ఆటోమేటిక్‌గా రీలోడ్ చేయడం కోసం
        location.reload();
      });
    }
  });
}

queryInput.addEventListener("keypress", (e) => {
  if (e.key === "Enter") performSearch();
});