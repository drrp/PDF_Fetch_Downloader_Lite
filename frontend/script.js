const searchBtn = document.getElementById("search-btn");
const queryInput = document.getElementById("query");
const sourceBoxes = document.querySelectorAll(
  ".checkbox-label input[data-source]",
);
const resultFilter = document.getElementById("result-filter");
const resultsContainer = document.getElementById("results");
const statTotal = document.getElementById("stat-total");
const resultsCountLabel = document.getElementById("results-count-label");

// Libraries are identified by short codes, and the reader-facing label arrives with
// each result from the server. Nothing in this file names them.
// The server decides whether downloads go straight from the library (which saves its
// bandwidth but usually opens a PDF viewer) or through the server (which saves the
// file immediately). It tells us which at startup.
let directDownload = false;

const chosenSources = () =>
  Array.from(sourceBoxes)
    .filter((box) => box.checked)
    .map((box) => box.dataset.source)
    .join(",");

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
    const sources = chosenSources();

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
        `/search?query=${encodeURIComponent(query)}&sources=${encodeURIComponent(sources)}`
      );
      if (response.status === 401) {
        window.location.href = "/login/google";
        return;
      }
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

      const badgeClass = `src-${book.source}`;

      // కేవలం టైటిల్, రచయిత, సంవత్సరం మాత్రమే (వివరణ తొలగించబడింది)
      let authorHtml = book.author ? `<div class="book-author"><i class="fa-solid fa-pen-nib"></i> ${book.author}</div>` : '';
      let yearHtml = book.year ? `<span class="book-year">(${book.year})</span>` : '';

      card.innerHTML = `
              <div class="book-info">
                  ${coverHtml}
                  <div class="book-details-content">
                      <span class="badge ${badgeClass}">${book.source_label || ""}</span>
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
  const params =
    `book_page_url=${encodeURIComponent(url)}` +
    `&title=${encodeURIComponent(title)}` +
    `&source=${encodeURIComponent(source)}`;

  // Optionally ask whether the library has its own download link. That saves this
  // server all the bandwidth, but most libraries send no Content-Disposition, so the
  // browser opens the PDF in a viewer rather than saving it - which is why it is off
  // by default and the server-side download below is used instead.
  if (directDownload) {
    const previousHtml = btnElement.innerHTML;
    btnElement.disabled = true;
    btnElement.innerHTML =
      '<i class="fa-solid fa-spinner fa-spin"></i> లింక్ వెతుకుతోంది...';
    try {
      const link = await fetch(`/download-link?${params}`).then((r) => r.json());
      if (link && link.ok && link.url) {
        btnElement.disabled = false;
        btnElement.innerHTML = '<i class="fa-solid fa-check"></i> సేవ్ అయింది';
        btnElement.style.backgroundColor = "#1e3a8a";

        Swal.fire({
          title: "డౌన్‌లోడ్ ప్రారంభమైంది!",
          text: "మీ బ్రౌజర్ నేరుగా గ్రంథాలయం నుండి ఫైల్‌ను సేవ్ చేస్తోంది.",
          icon: "success",
          timer: 2500,
          showConfirmButton: false,
        });

        const direct = document.createElement("a");
        direct.href = link.url;
        direct.target = "_blank";
        direct.rel = "noopener";
        document.body.appendChild(direct);
        direct.click();
        direct.remove();
        return;
      }
    } catch (e) {
      // No direct link available - fall back to the server-side download below.
    }
    btnElement.disabled = false;
    btnElement.innerHTML = previousHtml;
  }

  Swal.fire({
    title: "పుస్తకం డౌన్‌లోడ్ అవుతోంది",
    html: `
          <div style="margin: 20px 0; text-align: center;">
              <p style="color: #0f172a; font-size: 15px; font-weight: 600; margin-bottom: 15px; line-height: 1.4;">"${title}"</p>
              
              <div id="progress-bar-container" style="background: #e2e8f0; border-radius: 6px; overflow: hidden; height: 24px; padding: 2px; margin-bottom: 12px; box-shadow: inset 0 1px 2px rgba(0,0,0,0.1);">
                  <div id="progress-bar-fill" style="background: linear-gradient(90deg, #2563eb, #1d4ed8); width: 5%; height: 100%; border-radius: 4px; transition: width 0.4s ease;"></div>
              </div>
              
              <div style="display: flex; justify-content: space-between; font-size: 13px; font-weight: 600; color: #475569;">
                  <span id="progress-percent">5%</span>
                  <span id="progress-text">సర్వర్‌‌తో కనెక్ట్ అవుతోంది...</span>
              </div>
          </div>
      `,
    allowOutsideClick: false,
    allowEscapeKey: false,
    showConfirmButton: false,
    didOpen: () => {
      const fill = document.getElementById("progress-bar-fill");
      const percent = document.getElementById("progress-percent");
      const text = document.getElementById("progress-text");

      let currentPercent = 5;

      window.downloadProgressInterval = setInterval(() => {
        if (currentPercent < 90) {
          const increment =
            currentPercent < 40
              ? Math.floor(Math.random() * 8) + 5
              : Math.floor(Math.random() * 3) + 1;
          currentPercent = Math.min(currentPercent + increment, 90);

          if (fill) fill.style.width = currentPercent + "%";
          if (percent) percent.innerText = currentPercent + "%";

          if (currentPercent > 60 && text) {
            text.innerText = "ఫైల్ స్ట్రీమ్ ప్రాసెస్ చేయబడుతోంది...";
          } else if (currentPercent > 30 && text) {
            text.innerText = "లైబ్రరీ నుండి డేటా సేకరించబడుతోంది...";
          }
        }
      }, 400);
    },
    willClose: () => {
      clearInterval(window.downloadProgressInterval);
    },
  });

  try {
    const response = await fetch(
      `/download-book?book_page_url=${encodeURIComponent(url)}&title=${encodeURIComponent(title)}&source=${encodeURIComponent(source)}`,
      {
        signal: window.currentFetchController
          ? window.currentFetchController.signal
          : undefined,
      },
    );
    if (response.status === 401) {
      window.location.href = "/login/google";
      return;
    }
    const data = await response.json();

    clearInterval(window.downloadProgressInterval);
    const fill = document.getElementById("progress-bar-fill");
    const percent = document.getElementById("progress-percent");
    const text = document.getElementById("progress-text");
    if (fill) fill.style.width = "100%";
    if (percent) percent.innerText = "100%";
    if (text) text.innerText = "పూర్తయింది!";

    await new Promise((r) => setTimeout(r, 400));

    if (data.status === "success") {
      btnElement.innerHTML = '<i class="fa-solid fa-check"></i> సేవ్ అయింది';
      btnElement.style.backgroundColor = "#1e3a8a";

      // Start the browser download immediately - no second confirmation. The file
      // is streamed from our own server (the library sites cannot be fetched
      // directly by the browser), so the browser's download manager takes over and
      // shows the progress from here.
      const a = document.createElement("a");
      a.href = data.download_url;
      a.download = data.filename || "";
      document.body.appendChild(a);
      a.click();
      a.remove();

      Swal.fire({
        title: "డౌన్‌లోడ్ ప్రారంభమైంది!",
        text: `"${title}" ఫైల్ మీ కంప్యూటర్‌లో సేవ్ అవుతోంది.`,
        icon: "success",
        timer: 2000,
        showConfirmButton: false,
      });
    } else if (data.status === "gdrive_restricted") {
      btnElement.innerHTML =
        '<i class="fa-brands fa-google-drive"></i> డ్రైవ్‌లో తెరవండి';
      btnElement.style.backgroundColor = "#d97706";

      Swal.fire({
        title: "గూగుల్ లాగిన్ అవసరం",
        text: "ఈ పుస్తకానికి Google ఖాతా అనుమతి అవసరం. దయచేసి దీన్ని నేరుగా డ్రైవ్‌లో తెరవండి.",
        icon: "info",
        showCancelButton: true,
        confirmButtonColor: "#2563eb",
        cancelButtonColor: "#64748b",
        confirmButtonText:
          '<i class="fa-solid fa-arrow-up-right-from-square"></i> డ్రైవ్‌లో తెరవండి',
        cancelButtonText: "మూసివేయండి",
      }).then((res) => {
        if (res.isConfirmed) {
          window.open(data.url, "_blank");
        }
      });
    } else {
      Swal.fire({
        title: "విఫలమైంది",
        text: data.message,
        icon: "error",
        confirmButtonColor: "#dc2626",
      });
    }
  } catch (error) {
    if (error.name === "AbortError") return;

    clearInterval(window.downloadProgressInterval);
    Swal.fire({
      title: "లోపం",
      text: "సర్వర్‌తో కనెక్షన్ విఫలమైంది.",
      icon: "error",
      confirmButtonColor: "#dc2626",
    });
  }
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

// సైన్ ఇన్ చేసిన యూజర్ వివరాలను చూపించడం (లాగిన్ బటన్ / ప్రొఫైల్ కార్డ్).
async function checkLoginStatus() {
  try {
    const data = await fetch("/api/current-user").then((r) => r.json());
    directDownload = !!data.direct_download;

    // A copy with sign-in switched off shows no login button and no account card.
    if (!data.login_enabled) {
      const loginBtn = document.getElementById("google-login-btn");
      if (loginBtn) loginBtn.style.display = "none";
      const accountCard = document.getElementById("user-profile-card");
      if (accountCard) accountCard.style.display = "none";
      return;
    }

    if (!data.logged_in) return;

    const loginBtn = document.getElementById("google-login-btn");
    if (loginBtn) loginBtn.style.display = "none";

    const card = document.getElementById("user-profile-card");
    if (!card) return;
    card.style.display = "flex";

    const avatar = document.getElementById("user-avatar");
    if (avatar && data.picture) avatar.src = data.picture;

    const nameEl = document.getElementById("user-name");
    if (nameEl) nameEl.textContent = data.name || "";

    if (data.is_admin && !document.getElementById("admin-link")) {
      const adminLink = document.createElement("a");
      adminLink.id = "admin-link";
      adminLink.className = "profile-link admin-link";
      adminLink.href = "/admin";
      adminLink.innerHTML = '<i class="fa-solid fa-gauge"></i> అడ్మిన్';
      card.appendChild(adminLink);
    }
  } catch (e) {
    // లాగిన్ కాలేదు, లేదా చెక్ విఫలమైంది — లాగిన్ బటన్ అలాగే ఉంటుంది.
  }
}

window.addEventListener("DOMContentLoaded", checkLoginStatus);


// The profile page hands over a "search again" / "download again" request through
// sessionStorage before sending the reader back here.
window.addEventListener("DOMContentLoaded", () => {
  const pendingSearch = sessionStorage.getItem("pending_search");
  if (pendingSearch) {
    sessionStorage.removeItem("pending_search");
    queryInput.value = pendingSearch;
    performSearch();
    return;
  }

  const dlUrl = sessionStorage.getItem("pending_dl_url");
  const dlTitle = sessionStorage.getItem("pending_dl_title");
  const dlSource = sessionStorage.getItem("pending_dl_source");
  const dlLabel = sessionStorage.getItem("pending_dl_label") || "";
  if (!dlUrl || !dlTitle) return;

  sessionStorage.removeItem("pending_dl_url");
  sessionStorage.removeItem("pending_dl_title");
  sessionStorage.removeItem("pending_dl_source");
  sessionStorage.removeItem("pending_dl_label");

  queryInput.value = dlTitle;
  resultsContainer.innerHTML = "";
  resultsCountLabel.innerText = "మళ్లీ డౌన్‌లోడ్ చేయడానికి సిద్ధంగా ఉన్న పుస్తకం";

  const card = document.createElement("div");
  card.className = "book-card";
  card.innerHTML = `
      <div class="book-info">
          <div class="no-cover"><i class="fa-solid fa-book"></i></div>
          <div class="book-details-content">
              <span class="badge src-${dlSource}">${dlLabel}</span>
              <div class="book-title">${dlTitle}</div>
          </div>
      </div>
      <button class="action-btn" onclick="savePdfLocally('${dlUrl}', '${dlTitle.replace(/'/g, "\\'")}', '${dlSource}', this)">
          <i class="fa-solid fa-download"></i> మళ్లీ సేవ్ చేయి
      </button>
  `;
  resultsContainer.appendChild(card);
});
