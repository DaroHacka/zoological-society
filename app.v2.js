// -------------------------------------------------------------
// Backend base URL (dynamic based on current hostname)
// -------------------------------------------------------------
const API_HOST = window.location.hostname + ":9001";
const API = "http://" + API_HOST + "/api";

// Static files base URL
const STATIC_BASE = "http://" + API_HOST;

// Helper to convert relative static URLs to absolute URLs
function toAbsoluteUrl(url) {
  if (!url) return url;
  if (url.startsWith('http')) return url; // Already absolute
  return STATIC_BASE + url;
}

// -------------------------------------------------------------
// State
// -------------------------------------------------------------
let consoles = [];
let gamesByConsole = {}; // consoleId -> array of games
let currentConsoleId = null;
let currentGameDetail = null; // For modal

let activeFilter = null;
let activeGenreFilter = null;
let activeStatusFilter = null;
let currentPage = 1;
const PAGE_SIZE = 20;

// UI state
let isLoading = false;
let currentCoverGameId = null;
let genreFilterOpen = false;

// View state: 'homepage' or 'console' or 'search'
let currentView = 'homepage';
let globalSearchQuery = '';
let archiveStats = {
  total_consoles: 0,
  total_games: 0,
  completed_count: 0,
  favorites_count: 0,
  playing_count: 0,
  plan_to_play_count: 0,
  dropped_count: 0,
  on_hold_count: 0
};

let consoleStats = null;

// Genre filter state
let genres = [];

// Screenshot lightbox state
let currentLightboxScreenshots = [];
let currentLightboxIndex = 0;

// Game detail modal navigation state
let currentGameIndex = -1;
let currentGamesList = [];

// Description pagination state
let currentDescriptionPage = 1;
let totalDescriptionPages = 1;
let currentGameStatus = null;

// -----------------------------------------------------------
// Lightbox for screenshots (with navigation)
// -----------------------------------------------------------

function openLightbox(imageSrc) {
  const lightbox = document.getElementById("screenshot-lightbox");
  const img = document.getElementById("lightbox-img");
  
  // Extract URLs from screenshot objects for lightbox
  const screenshotUrls = currentLightboxScreenshots.map(s => s.url || s);
  
  // Find the index of clicked screenshot
  currentLightboxIndex = screenshotUrls.indexOf(imageSrc);
  if (currentLightboxIndex === -1) {
    currentLightboxIndex = 0;
  }
  
  img.src = imageSrc;
  lightbox.classList.add("active");
  updateLightboxCounter();
}

function closeLightbox() {
  const lightbox = document.getElementById("screenshot-lightbox");
  lightbox.classList.remove("active");
}

function nextScreenshot() {
  if (currentLightboxScreenshots.length === 0) return;
  currentLightboxIndex = (currentLightboxIndex + 1) % currentLightboxScreenshots.length;
  updateLightbox();
}

function previousScreenshot() {
  if (currentLightboxScreenshots.length === 0) return;
  currentLightboxIndex = (currentLightboxIndex - 1 + currentLightboxScreenshots.length) % currentLightboxScreenshots.length;
  updateLightbox();
}

function updateLightbox() {
  const img = document.getElementById("lightbox-img");
  const screenshot = currentLightboxScreenshots[currentLightboxIndex];
  img.src = toAbsoluteUrl(screenshot.url || screenshot) + "?t=" + Date.now();
  updateLightboxCounter();
}

function updateLightboxCounter() {
  document.getElementById("lightbox-current").textContent = currentLightboxIndex + 1;
  document.getElementById("lightbox-total").textContent = currentLightboxScreenshots.length;
}

// -----------------------------------------------------------
// Cover Lightbox (for viewing cover in full size)
// -----------------------------------------------------------

function openCoverLightbox(imageSrc) {
  const lightbox = document.getElementById("screenshot-lightbox");
  const img = document.getElementById("lightbox-img");
  
  // For cover, we don't have multiple images, so just show the cover
  img.src = imageSrc;
  lightbox.classList.add("active");
  
  // Hide the counter since there's only one image
  document.getElementById("lightbox-current").textContent = "1";
  document.getElementById("lightbox-total").textContent = "1";
}

// -----------------------------------------------------------
// Cover Upload Functionality
// -----------------------------------------------------------

function openCoverUploadModal(gameId) {
  currentCoverGameId = gameId;
  document.getElementById("cover-game-id").value = gameId;
  toggleModal("#modal-upload-cover", true);
}

async function onSaveCover() {
  const gameId = parseInt(document.getElementById("cover-game-id").value);
  const fileInput = document.getElementById("cover-file-input");
  const urlInput = document.getElementById("cover-url-input");

  if (!gameId) {
    showToast("Error: No game selected", "error");
    return;
  }

  // Check which tab is active
  const uploadTab = document.getElementById("tab-upload");
  const isFileUpload = !uploadTab.classList.contains("hidden");

  if (isFileUpload) {
    // File upload
    if (!fileInput.files.length) {
      showToast("Please select an image file", "warning");
      return;
    }

    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append("file", file);

    try {
      setLoading(true);
      const res = await fetch(`${API}/games/${gameId}/upload-cover`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: "Upload failed" }));
        throw new Error(error.detail || "Upload failed");
      }

      showToast("Cover uploaded successfully!", "success");
      fileInput.value = "";
      toggleModal("#modal-upload-cover", false);
      await loadGamesForConsole(currentConsoleId);
    } catch (e) {
      showToast(`Error: ${e.message}`, "error");
    } finally {
      setLoading(false);
    }
  } else {
    // URL upload
    const url = urlInput.value.trim();
    if (!url) {
      showToast("Please enter an image URL", "warning");
      return;
    }

    try {
      const result = await apiCall(`/games/${gameId}/cover-from-url`, {
        method: "POST",
        body: JSON.stringify({ url }),
      });

      showToast("Cover saved successfully!", "success");
      urlInput.value = "";
      toggleModal("#modal-upload-cover", false);
      await loadGamesForConsole(currentConsoleId);
    } catch (e) {
      // Error already shown by apiCall
    }
  }
}

// -----------------------------------------------------------
// Screenshot Upload Functionality
// -----------------------------------------------------------

function openAddScreenshotModal(gameId, currentScreenshotCount) {
  document.getElementById("screenshot-game-id").value = gameId;
  document.getElementById("screenshot-file-input").value = "";
  document.getElementById("screenshot-url-input").value = "";
  
  const limitMsg = document.getElementById("screenshot-limit-msg");
  if (currentScreenshotCount >= 5) {
    limitMsg.textContent = "Maximum 5 screenshots reached. Delete one to add more.";
    document.getElementById("btn-screenshot-save").disabled = true;
  } else {
    limitMsg.textContent = `You can add up to 5 screenshots per game. (${5 - currentScreenshotCount} remaining)`;
    document.getElementById("btn-screenshot-save").disabled = false;
  }
  
  toggleModal("#modal-add-screenshot", true);
}

async function onSaveScreenshot() {
  const gameId = parseInt(document.getElementById("screenshot-game-id").value);
  const fileInput = document.getElementById("screenshot-file-input");
  const urlInput = document.getElementById("screenshot-url-input");

  if (!gameId) {
    showToast("Error: No game selected", "error");
    return;
  }

  const uploadTab = document.getElementById("tab-screenshot-upload");
  const isFileUpload = !uploadTab.classList.contains("hidden");

  if (isFileUpload) {
    if (!fileInput.files.length) {
      showToast("Please select an image file", "warning");
      return;
    }

    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append("file", file);

    try {
      setLoading(true);
      const res = await fetch(`${API}/games/${gameId}/upload-screenshot`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: "Upload failed" }));
        throw new Error(error.detail || "Upload failed");
      }

      showToast("Screenshot added successfully!", "success");
      fileInput.value = "";
      toggleModal("#modal-add-screenshot", false);
      
      if (currentGameDetail && currentGameDetail.id) {
        await openGameDetail(currentGameDetail.id);
      }
    } catch (e) {
      showToast(`Error: ${e.message}`, "error");
    } finally {
      setLoading(false);
    }
  } else {
    const url = urlInput.value.trim();
    if (!url) {
      showToast("Please enter an image URL", "warning");
      return;
    }

    try {
      const result = await apiCall(`/games/${gameId}/screenshot-from-url`, {
        method: "POST",
        body: JSON.stringify({ url }),
      });

      showToast("Screenshot added successfully!", "success");
      urlInput.value = "";
      toggleModal("#modal-add-screenshot", false);
      
      if (currentGameDetail && currentGameDetail.id) {
        await openGameDetail(currentGameDetail.id);
      }
    } catch (e) {
      // Error already shown by apiCall
    }
  }
}

// -----------------------------------------------------------
// Edit Game Details
// -----------------------------------------------------------

let currentEditGameId = null;

async function openEditGameModal(gameId) {
  const game = currentGameDetail;
  if (!game) return;
  
  currentEditGameId = gameId;
  document.getElementById("edit-game-id").value = gameId;
  document.getElementById("edit-game-title").value = game.title || "";
  document.getElementById("edit-game-genre").value = game.genre || "";
  document.getElementById("edit-game-description").value = game.description || "";
  
  // Load and set status checkboxes
  const status = await loadGameStatus(gameId);
  if (status) {
    document.getElementById("edit-status-favorite").checked = status.is_favorite;
    document.getElementById("edit-status-playing").checked = status.is_playing;
    document.getElementById("edit-status-plan-to-play").checked = status.has_plan_to_play;
    document.getElementById("edit-status-completed").checked = status.is_completed;
    document.getElementById("edit-status-dropped").checked = status.is_dropped;
    document.getElementById("edit-status-on-hold").checked = status.is_on_hold;
    document.getElementById("edit-completed-date").value = status.completed_date_note || "";
    
    // Show/hide completed date field
    const completedDateLabel = document.getElementById("completed-date-label");
    completedDateLabel.classList.toggle("hidden", !status.is_completed);
  } else {
    // Reset checkboxes
    document.getElementById("edit-status-favorite").checked = false;
    document.getElementById("edit-status-playing").checked = false;
    document.getElementById("edit-status-plan-to-play").checked = false;
    document.getElementById("edit-status-completed").checked = false;
    document.getElementById("edit-status-dropped").checked = false;
    document.getElementById("edit-status-on-hold").checked = false;
    document.getElementById("edit-completed-date").value = "";
    document.getElementById("completed-date-label").classList.add("hidden");
  }
  
  // Add event listener to show/hide completed date field
  const completedCheckbox = document.getElementById("edit-status-completed");
  completedCheckbox.onchange = function() {
    document.getElementById("completed-date-label").classList.toggle("hidden", !this.checked);
  };
  
  toggleModal("#modal-edit-game", true);
}

async function onSaveGameEdit() {
  const gameId = parseInt(document.getElementById("edit-game-id").value);
  const title = document.getElementById("edit-game-title").value.trim();
  const genre = document.getElementById("edit-game-genre").value.trim();
  const description = document.getElementById("edit-game-description").value.trim();

  if (!gameId || !title) {
    showToast("Title is required", "warning");
    return;
  }

  try {
    const result = await apiCall(`/games/${gameId}/update`, {
      method: "POST",
      body: JSON.stringify({ title, genre, description }),
    });

    // Save status
    const completedNoteValue = document.getElementById("edit-completed-date").value.trim();
    const statusData = {
      is_favorite: document.getElementById("edit-status-favorite").checked,
      has_plan_to_play: document.getElementById("edit-status-plan-to-play").checked,
      is_playing: document.getElementById("edit-status-playing").checked,
      is_completed: document.getElementById("edit-status-completed").checked,
      completed_date_note: completedNoteValue || "",
      is_dropped: document.getElementById("edit-status-dropped").checked,
      is_on_hold: document.getElementById("edit-status-on-hold").checked
    };
    
    await saveGameStatus(gameId, statusData);

    showToast("Game updated successfully!", "success");
    toggleModal("#modal-edit-game", false);
    
    // Refresh the game detail and list (only if we have a console selected)
    if (currentConsoleId) {
      await loadGamesForConsole(currentConsoleId);
    }
    await openGameDetail(gameId);
    loadStats();
  } catch (e) {
    // Error already shown
  }
}

// -----------------------------------------------------------
// Genre Filter
// -----------------------------------------------------------

function toggleGenreFilter() {
  genreFilterOpen = !genreFilterOpen;
  const genreList = document.getElementById("genre-list");
  const icon = document.getElementById("genre-toggle-icon");
  
  if (genreFilterOpen) {
    genreList.style.display = "block";
    icon.textContent = "▼";
  } else {
    genreList.style.display = "none";
    icon.textContent = "▶";
  }
}

function extractGenres() {
  genres = new Set();
  
  if (!currentConsoleId) return;
  
  const games = gamesByConsole[currentConsoleId] || [];
  games.forEach((game) => {
    if (game.genre) {
      // Split by comma and add each genre
      game.genre.split(",").forEach((g) => {
        const trimmed = g.trim();
        if (trimmed) genres.add(trimmed);
      });
    }
  });
  
  genres = Array.from(genres).sort();
  renderGenreFilter();
}

function renderGenreFilter() {
  const section = document.getElementById("genre-filter-section");
  const genreList = document.getElementById("genre-list");
  
  if (genres.length === 0) {
    section.style.display = "none";
    return;
  }
  
  section.style.display = "block";
  genreList.innerHTML = "";
  
  genres.forEach((genre) => {
    const li = document.createElement("li");
    li.className = genre === activeGenreFilter ? "active" : "";
    li.textContent = genre;
    li.addEventListener("click", () => applyGenreFilter(genre));
    genreList.appendChild(li);
  });
}

function applyGenreFilter(genre) {
  if (activeGenreFilter === genre) {
    // Toggle off
    activeGenreFilter = null;
  } else {
    activeGenreFilter = genre;
  }
  
  activeFilter = null; // Clear alphabetical filter
  activeStatusFilter = null;
  currentPage = 1;
  renderGenreFilter();
  renderStatusFilters();
  renderGamesForCurrentConsole();
}

// -----------------------------------------------------------
// Status Filter
// -----------------------------------------------------------

let statusFilteredGames = []; // Store games when filtering by status

async function applyStatusFilter(status) {
  if (activeStatusFilter === status) {
    // Toggle off
    activeStatusFilter = null;
    statusFilteredGames = [];
    $("#recently-viewed-section").classList.remove("hidden");
  } else {
    activeStatusFilter = status;
    
    // Fetch games by status from API - global or console-specific
    try {
      if (currentConsoleId) {
        statusFilteredGames = await apiCall(`/consoles/${currentConsoleId}/games/by-status?status=${status}`);
      } else {
        statusFilteredGames = await apiCall(`/games/by-status?status=${status}`);
      }
    } catch (e) {
      statusFilteredGames = [];
    }
    
    // Hide Recently Viewed when status filter is active
    $("#recently-viewed-section").classList.add("hidden");
  }
  
  activeFilter = null;
  activeGenreFilter = null;
  currentPage = 1;
  renderStatusFilters();
  renderGenreFilter();
  renderGamesForCurrentConsole();
}

function renderStatusFilters() {
  // Use console-specific stats if inside a console, otherwise use global stats
  const stats = consoleStats || archiveStats;
  
  // Update counts
  $("#count-favorite").textContent = stats.favorites_count || stats.favorite_count || 0;
  $("#count-playing").textContent = stats.playing_count || 0;
  $("#count-plan_to_play").textContent = stats.plan_to_play_count || 0;
  $("#count-completed").textContent = stats.completed_count || 0;
  $("#count-dropped").textContent = stats.dropped_count || 0;
  $("#count-on_hold").textContent = stats.on_hold_count || 0;
  
  // Update active state
  $$(".status-filter-item").forEach(li => {
    const status = li.dataset.status;
    li.classList.toggle("active", status === activeStatusFilter);
  });
}

function toggleStatusFilter() {
  const statusList = $("#status-filter-list");
  const icon = $("#status-toggle-icon");
  
  if (statusList.style.display === "none") {
    statusList.style.display = "block";
    icon.textContent = "▼";
  } else {
    statusList.style.display = "none";
    icon.textContent = "▶";
  }
}

function toggleConsoleList() {
  const consoleList = $("#console-list");
  const icon = $("#console-list-toggle-icon");
  const collapsed = consoleList.style.display === "none";
  
  if (collapsed) {
    consoleList.style.display = "block";
    icon.textContent = "▼";
    localStorage.setItem("consoleListCollapsed", "false");
  } else {
    consoleList.style.display = "none";
    icon.textContent = "▶";
    localStorage.setItem("consoleListCollapsed", "true");
  }
}

function loadConsoleListState() {
  const collapsed = localStorage.getItem("consoleListCollapsed") === "true";
  const consoleList = $("#console-list");
  const icon = $("#console-list-toggle-icon");
  
  if (collapsed) {
    consoleList.style.display = "none";
    icon.textContent = "▶";
  } else {
    consoleList.style.display = "block";
    icon.textContent = "▼";
  }
}

// -----------------------------------------------------------
// Homepage & Stats
// -----------------------------------------------------------

async function loadStats() {
  try {
    const stats = await apiCall("/stats");
    archiveStats = stats;
    
    // Update homepage stats
    $("#stat-consoles .stat-number").textContent = stats.total_consoles || 0;
    $("#stat-games .stat-number").textContent = stats.total_games || 0;
    $("#stat-completed .stat-number").textContent = stats.completed_count || 0;
    $("#stat-favorites .stat-number").textContent = stats.favorites_count || 0;
    
    renderStatusFilters();
  } catch (e) {
    console.error("Failed to load stats:", e);
  }
}

async function loadRecentlyViewed() {
  try {
    const games = await apiCall("/recently-viewed?limit=5");
    const container = $("#recently-viewed-list");
    
    if (!games || games.length === 0) {
      container.innerHTML = '<p class="no-items">No recently viewed games</p>';
      return;
    }
    
    container.innerHTML = "";
    games.forEach(game => {
      const div = document.createElement("div");
      div.className = "recent-game-card";
      div.onclick = () => navigateToGame(game.id, game.console_name);
      
      const coverUrl = game.cover_url ? toAbsoluteUrl(game.cover_url) : "";
      const coverImg = coverUrl 
        ? `<img src="${coverUrl}" alt="${game.title}" />`
        : `<div class="no-cover-small" style="width:100px;height:150px;background:var(--card-bg);display:flex;align-items:center;justify-content:center;border-radius:var(--radius);">🎮</div>`;
      
      div.innerHTML = `
        ${coverImg}
        <div class="title">${game.title}</div>
      `;
      container.appendChild(div);
    });
  } catch (e) {
    console.error("Failed to load recently viewed:", e);
  }
}

async function loadLastAdded() {
  try {
    const games = await apiCall("/recently-added?limit=10");
    const container = $("#last-added-list");
    
    if (!games || games.length === 0) {
      container.innerHTML = '<p class="no-items">No recently added games</p>';
      return;
    }
    
    container.innerHTML = "";
    games.forEach(game => {
      const div = document.createElement("div");
      div.className = "recent-game-card";
      div.onclick = () => navigateToGame(game.id, game.console_name);
      
      const coverUrl = game.cover_url ? toAbsoluteUrl(game.cover_url) : "";
      const coverImg = coverUrl 
        ? `<img src="${coverUrl}" alt="${game.title}" />`
        : `<div class="no-cover-small" style="width:100px;height:150px;background:var(--card-bg);display:flex;align-items:center;justify-content:center;border-radius:var(--radius);">🎮</div>`;
      
      div.innerHTML = `
        ${coverImg}
        <div class="title">${game.title}</div>
      `;
      container.appendChild(div);
    });
  } catch (e) {
    console.error("Failed to load last added:", e);
  }
}

function goToHomepage() {
  currentConsoleId = null;
  activeFilter = null;
  activeGenreFilter = null;
  activeStatusFilter = null;
  statusFilteredGames = [];
  consoleStats = null;
  currentPage = 1;
  
  // Clear localStorage state for console
  localStorage.setItem('archive_currentView', 'homepage');
  localStorage.setItem('archive_currentConsoleId', '');
  
  renderHomepage();
  renderConsoles();
  renderStatusFilters();
}

function renderHomepage() {
  currentView = 'homepage';
  $("#homepage").classList.remove("hidden");
  $("#search-results").classList.add("hidden");
  $(".app-body").classList.add("show-homepage");
  
  // Show sidebar elements that were hidden
  $(".console-summary").style.display = "none";
  $(".alpha-index").style.display = "none";
  $(".metadata-actions").style.display = "none";
  
  // Load stats and recently viewed
  loadStats();
  loadRecentlyViewed();
  loadLastAdded();
}

function showConsoleView() {
  currentView = 'console';
  $("#homepage").classList.add("hidden");
  $("#search-results").classList.add("hidden");
  $(".app-body").classList.remove("show-homepage");
  
  // Show console view elements
  $(".console-summary").style.display = "flex";
  $(".alpha-index").style.display = "block";
  $(".metadata-actions").style.display = "flex";
}

// -----------------------------------------------------------
// Global Search
// -----------------------------------------------------------

async function performGlobalSearch(query) {
  if (!query.trim()) return;
  
  setLoading(true);
  try {
    const results = await apiCall(`/games/search?q=${encodeURIComponent(query)}`);
    globalSearchQuery = query;
    
    // Show search results view - explicitly hide console elements
    currentView = 'search';
    $("#homepage").classList.add("hidden");
    $("#search-results").classList.remove("hidden");
    $(".app-body").classList.remove("show-homepage");
    
    // Hide console-specific elements
    $(".console-summary").style.display = "none";
    $(".alpha-index").style.display = "none";
    $(".metadata-actions").style.display = "none";
    $("#game-list").style.display = "none";
    
    $("#search-query").textContent = query;
    renderSearchResults(results);
  } catch (e) {
    console.error("Search failed:", e);
    showToast("Search failed: " + e.message, "error");
  } finally {
    setLoading(false);
  }
}

// -----------------------------------------------------------
// Create Game Card (reusable function)
// -----------------------------------------------------------
function createGameCard(game, consoleName) {
  const card = document.createElement("article");
  card.className = "game-card";
  card.dataset.id = game.id;
  card.dataset.title = game.title;

  const cover = game.cover_url
    ? `<img src="${toAbsoluteUrl(game.cover_url)}${game.cover_url.includes('?') ? '&' : '?'}t=${Date.now()}" alt="${game.title} cover" />`
    : `<div class="no-cover">No cover</div>`;

  card.innerHTML = `
    <div class="game-cover" style="position: relative;">
      ${cover}
    </div>
    <div class="game-title">${game.title}</div>
    <div class="game-meta">${game.genre || "Unknown genre"}</div>
    ${consoleName ? `<div class="game-meta" style="color: var(--accent);">${consoleName}</div>` : ''}
  `;

  // Make the entire card clickable to open game detail
  card.addEventListener("click", () => {
    openGameDetail(game.id);
  });

  return card;
}

function renderSearchResults(games) {
  const container = $("#search-results-list");
  container.innerHTML = "";
  
  if (!games || games.length === 0) {
    container.innerHTML = '<p class="no-items">No games found</p>';
    return;
  }
  
  games.forEach(game => {
    const card = createGameCard(game, game.console_name);
    container.appendChild(card);
  });
}

function clearSearch() {
  globalSearchQuery = "";
  $("#global-search-input").value = "";
  
  // Hide search results, show appropriate view
  $("#search-results").classList.add("hidden");
  $("#game-list").style.display = "block";
  
  // Return to previous view
  if (currentConsoleId) {
    showConsoleView();
    renderConsoles();
    updateConsoleSummary();
    loadGamesForConsole(currentConsoleId);
  } else {
    renderHomepage();
  }
}

// -----------------------------------------------------------
// Navigate to a game (from recently viewed or search results)
// -----------------------------------------------------------

async function navigateToGame(gameId, consoleName) {
  // Find console by name
  const console = consoles.find(c => c.name === consoleName);
  if (!console) {
    showToast("Console not found", "error");
    return;
  }
  
  // Select the console and open the game
  await selectConsole(console.id);
  await openGameDetail(gameId);
}

// -----------------------------------------------------------
// Get Started Guide
// -----------------------------------------------------------

function toggleGetStarted() {
  const content = $("#get-started-content");
  const icon = $("#get-started-icon");
  content.classList.toggle("expanded");
  icon.textContent = content.classList.contains("expanded") ? "▲" : "▼";
}

// -----------------------------------------------------------
// Completed Games Modal
// -----------------------------------------------------------

async function showCompletedGamesModal() {
  try {
    const games = await apiCall("/games/completed");
    const container = $("#completed-games-list");
    
    if (!games || games.length === 0) {
      container.innerHTML = '<p class="no-items">No completed games yet</p>';
    } else {
      container.innerHTML = "";
      games.forEach(game => {
        const div = document.createElement("div");
        div.className = "completed-game-item";
        
        const coverUrl = game.cover_url ? toAbsoluteUrl(game.cover_url) : "";
        const coverImg = coverUrl 
          ? `<img src="${coverUrl}" alt="${game.title}" />`
          : `<div class="no-cover-small" style="width:50px;height:75px;background:var(--card-bg);display:flex;align-items:center;justify-content:center;border-radius:4px;">🎮</div>`;
        
        div.innerHTML = `
          ${coverImg}
          <div class="info">
            <div class="title">${game.title}</div>
            <div class="console">${game.console_name}</div>
          </div>
        `;
        div.onclick = () => {
          toggleModal("#modal-completed-games", false);
          // Navigate to the game
          const console = consoles.find(c => c.name === game.console_name);
          if (console) {
            selectConsole(console.id).then(() => {
              openGameDetail(game.id);
            });
          }
        };
        container.appendChild(div);
      });
    }
    
    toggleModal("#modal-completed-games", true);
  } catch (e) {
    showToast("Failed to load completed games", "error");
  }
}

// -----------------------------------------------------------
// Game Status Management
// -----------------------------------------------------------

async function loadGameStatus(gameId) {
  try {
    const status = await apiCall(`/games/${gameId}/status`);
    return status;
  } catch (e) {
    console.error("Failed to load game status:", e);
    return null;
  }
}

async function saveGameStatus(gameId, statusData) {
  try {
    await apiCall(`/games/${gameId}/status`, {
      method: "POST",
      body: JSON.stringify(statusData)
    });
    
    // Refresh stats
    loadStats();
    
    return true;
  } catch (e) {
    return false;
  }
}

async function recordGameView(gameId) {
  try {
    await apiCall(`/games/${gameId}/view`, { method: "POST" });
  } catch (e) {
    // Silently fail - not critical
  }
}

// -----------------------------------------------------------
// Page State Persistence
// -----------------------------------------------------------

function savePageState() {
  localStorage.setItem('archive_currentConsoleId', currentConsoleId || '');
  localStorage.setItem('archive_currentView', currentView);
  localStorage.setItem('archive_activeFilter', activeFilter || '');
  localStorage.setItem('archive_activeGenreFilter', activeGenreFilter || '');
  localStorage.setItem('archive_activeStatusFilter', activeStatusFilter || '');
  localStorage.setItem('archive_currentPage', currentPage);
}

function loadPageState() {
  const savedView = localStorage.getItem('archive_currentView');
  const savedConsoleId = localStorage.getItem('archive_currentConsoleId');
  
  if (savedView === 'console' && savedConsoleId) {
    return {
      view: 'console',
      consoleId: parseInt(savedConsoleId)
    };
  }
  
  return { view: 'homepage' };
}

// -----------------------------------------------------------
// DOM helpers
// -----------------------------------------------------------
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// Show/hide loading indicator
function setLoading(show) {
  isLoading = show;
  const loader = $("#loading-indicator");
  if (loader) {
    loader.classList.toggle("hidden", !show);
  }
}

// Show toast notification
function showToast(message, type = "info") {
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);

  setTimeout(() => {
    toast.classList.add("show");
  }, 10);

  setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// API call wrapper with error handling
async function apiCall(endpoint, options = {}) {
  try {
    setLoading(true);
    const res = await fetch(`${API}${endpoint}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
    });

    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(error.detail || `HTTP ${res.status}`);
    }

    return await res.json();
  } catch (e) {
    showToast(`Error: ${e.message}`, "error");
    throw e;
  } finally {
    setLoading(false);
  }
}

// -----------------------------------------------------------
// Add Game Modal
// -----------------------------------------------------------

function switchAddGameTab(tabName) {
  // Update tab buttons
  $$(".add-game-tabs .tab-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.tab === tabName);
  });
  
  // Update tab content
  $$(".add-game-tabs ~ .tab-content").forEach(tab => {
    tab.classList.remove("active");
    tab.classList.add("hidden");
  });
  
  const content = $(`#tab-${tabName}`);
  if (content) {
    content.classList.add("active");
    content.classList.remove("hidden");
  }
}

async function confirmAddGame() {
  if (!currentConsoleId) {
    showToast("Please select a console first", "warning");
    return;
  }
  
  const singleTab = $("#tab-single").classList.contains("active");
  
  if (singleTab) {
    // Single game mode
    const title = $("#add-game-title").value.trim();
    if (!title) {
      showToast("Please enter a game title", "warning");
      return;
    }
    
    try {
      const result = await apiCall(`/consoles/${currentConsoleId}/games`, {
        method: "POST",
        body: JSON.stringify({ title: title })
      });
      
      if (result.added > 0) {
        showToast(`Added: ${title}`, "success");
      } else {
        showToast(`Already exists: ${title}`, "info");
      }
      
      // Close modal and clear input
      toggleModal("#modal-add-game", false);
      $("#add-game-title").value = "";
      
      // Refresh game list
      await loadGamesForConsole(currentConsoleId);
      loadLastAdded();
      
    } catch (e) {
      showToast("Failed to add game", "error");
    }
    
  } else {
    // Bulk games mode
    const listText = $("#add-games-list").value.trim();
    if (!listText) {
      showToast("Please paste a list of games", "warning");
      return;
    }
    
    // Parse the list - split by newlines
    const games = listText.split("\n").map(line => line.trim()).filter(line => line.length > 0);
    
    if (games.length === 0) {
      showToast("No valid game titles found", "warning");
      return;
    }
    
    try {
      const result = await apiCall(`/consoles/${currentConsoleId}/games/bulk`, {
        method: "POST",
        body: JSON.stringify({ games: games })
      });
      
      showToast(`Added ${result.added} games${result.skipped > 0 ? ` (${result.skipped} already existed)` : ""}`, "success");
      
      // Close modal and clear input
      toggleModal("#modal-add-game", false);
      $("#add-games-list").value = "";
      
      // Refresh game list
      await loadGamesForConsole(currentConsoleId);
      loadLastAdded();
      
    } catch (e) {
      showToast("Failed to add games", "error");
    }
  }
}

// -----------------------------------------------------------
// Initialization
// -----------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  // Core features - wrap in try-catch to prevent one failure from breaking others
  try {
    bindUI();
    renderAlphaIndex();
    applySavedTheme();
    initLightboxHandlers();
    initTabHandlers();
  } catch (e) {
    console.error("Core initialization error:", e);
  }
  
  try {
    loadInitialData();
  } catch (e) {
    console.error("loadInitialData error:", e);
  }
  
  try {
    initExtraFeatures();
  } catch (e) {
    console.error("initExtraFeatures error:", e);
  }
});

// -----------------------------------------------------------
// Tab switching for cover upload modal
// -----------------------------------------------------------
function initTabHandlers() {
  const tabBtns = document.querySelectorAll(".tab-btn");
  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const tabName = btn.dataset.tab;
      
      // Hide all tabs
      document.querySelectorAll(".tab-content").forEach((tab) => {
        tab.classList.remove("active");
        tab.classList.add("hidden");
      });
      
      // Deactivate all buttons
      document.querySelectorAll(".tab-btn").forEach((b) => {
        b.classList.remove("active");
      });
      
      // Show selected tab
      document.getElementById(`tab-${tabName}`).classList.remove("hidden");
      document.getElementById(`tab-${tabName}`).classList.add("active");
      btn.classList.add("active");
    });
  });
}

// Lightbox handlers
function initLightboxHandlers() {
  const lightbox = document.getElementById("screenshot-lightbox");
  if (lightbox) {
    lightbox.addEventListener("click", (e) => {
      if (e.target === lightbox) {
        closeLightbox();
      }
    });
  }

  // Keyboard navigation for lightbox and game detail modal
  document.addEventListener("keydown", (e) => {
    const lightbox = document.getElementById("screenshot-lightbox");
    const gameDetailModal = document.getElementById("modal-game-detail");
    
    // Check if user is typing in an input or textarea (don't interfere with cursor movement)
    const isTyping = document.activeElement && (
      document.activeElement.tagName === 'INPUT' || 
      document.activeElement.tagName === 'TEXTAREA' ||
      document.activeElement.isContentEditable
    );
    
    // Screenshot lightbox navigation takes priority when active
    if (lightbox && lightbox.classList.contains("active")) {
      if (e.key === "Escape") {
        closeLightbox();
      } else if (e.key === "ArrowRight") {
        nextScreenshot();
      } else if (e.key === "ArrowLeft") {
        previousScreenshot();
      }
      return; // Don't process game navigation when lightbox is open
    }
    
    // Don't navigate between games if user is typing in a text field
    if (isTyping) {
      return;
    }
    
    // Game detail modal navigation (only when lightbox is NOT open and not typing)
    if (gameDetailModal && !gameDetailModal.classList.contains("hidden")) {
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        navigateToPrevGame();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        navigateToNextGame();
      } else if (e.key === "Escape") {
        toggleModal("#modal-game-detail", false);
      }
    }
  });
}

// -----------------------------------------------------------
// Console Type Toggle
// -----------------------------------------------------------
function toggleConsoleType() {
  const consoleType = document.querySelector('input[name="console-type"]:checked').value;
  const pathLabel = document.getElementById("console-path-label");
  
  if (consoleType === "empty") {
    pathLabel.classList.add("hidden");
  } else {
    pathLabel.classList.remove("hidden");
  }
}

// -----------------------------------------------------------
// RAWG API Key
// -----------------------------------------------------------
function saveRawgApiKey() {
  const keyInput = document.getElementById("rawg-api-key");
  const apiKey = keyInput.value.trim();
  
  if (apiKey) {
    localStorage.setItem("rawg_api_key", apiKey);
    showToast("RAWG API key saved! Refresh to use it.", "success");
  } else {
    showToast("Please enter an API key", "warning");
  }
}

// Load RAWG key from localStorage on startup
function loadRawgApiKey() {
  const savedKey = localStorage.getItem("rawg_api_key");
  if (savedKey) {
    document.getElementById("rawg-api-key").value = savedKey;
  }
}

// -----------------------------------------------------------
// UI binding
// -----------------------------------------------------------
function bindUI() {
  const addConsoleBtn = $("#btn-add-console");
  const addGameBtn = $("#btn-add-game");
  const themeBtn = $("#btn-theme");
  const consoleCancelBtn = $("#btn-console-cancel");
  const themeCancelBtn = $("#btn-theme-cancel");
  const consoleSaveBtn = $("#btn-console-save");
  const themeSaveBtn = $("#btn-theme-save");
  const rescanBtn = $("#btn-rescan-console");
  const fetchTextBtn = $("#btn-fetch-text");
  const fetchCoversBtn = $("#btn-fetch-covers");
  const fetchScreenshotsBtn = $("#btn-fetch-screenshots");
  const coverCancelBtn = document.getElementById("btn-cover-cancel");
  const coverSaveBtn = document.getElementById("btn-cover-save");
  const screenshotCancelBtn = document.getElementById("btn-screenshot-cancel");
  const screenshotSaveBtn = document.getElementById("btn-screenshot-save");
  const editCancelBtn = document.getElementById("btn-edit-cancel");
  const editSaveBtn = document.getElementById("btn-edit-save");
  const rawgKeyBtn = document.getElementById("btn-save-rawg-key");

  // RAWG API key save
  if (rawgKeyBtn) {
    rawgKeyBtn.addEventListener("click", saveRawgApiKey);
  }
  
  // Load saved RAWG key
  loadRawgApiKey();

  if (addGameBtn) {
    addGameBtn.addEventListener("click", () => {
      toggleModal("#modal-add-game", true);
    });
  }

  if (addConsoleBtn) {
    addConsoleBtn.addEventListener("click", () => {
      toggleModal("#modal-console", true);
    });
  }

  if (themeBtn) {
    themeBtn.addEventListener("click", () => {
      populateThemeModal();
      toggleModal("#modal-theme", true);
    });
  }

  const homeBtn = $("#btn-home");
  if (homeBtn) {
    homeBtn.addEventListener("click", goToHomepage);
  }

  if (consoleCancelBtn) {
    consoleCancelBtn.addEventListener("click", () =>
      toggleModal("#modal-console", false)
    );
  }

  if (themeCancelBtn) {
    themeCancelBtn.addEventListener("click", () =>
      toggleModal("#modal-theme", false)
    );
  }

  if (consoleSaveBtn) {
    consoleSaveBtn.addEventListener("click", onSaveConsole);
  }

  if (themeSaveBtn) {
    themeSaveBtn.addEventListener("click", onSaveTheme);
  }

  const themeRemoveHeaderBtn = document.getElementById("btn-theme-remove-header");
  if (themeRemoveHeaderBtn) {
    themeRemoveHeaderBtn.addEventListener("click", onRemoveThemeHeader);
  }

  const themeRandomHeaderBtn = document.getElementById("btn-theme-random-header");
  if (themeRandomHeaderBtn) {
    themeRandomHeaderBtn.addEventListener("click", onRandomHeader);
  }

  if (rescanBtn) {
    rescanBtn.addEventListener("click", onRescanConsole);
  }

  if (fetchTextBtn) {
    fetchTextBtn.addEventListener("click", onFetchText);
  }

  if (fetchCoversBtn) {
    fetchCoversBtn.addEventListener("click", onFetchCovers);
  }

  if (fetchScreenshotsBtn) {
    fetchScreenshotsBtn.addEventListener("click", onFetchScreenshots);
  }

  if (coverCancelBtn) {
    coverCancelBtn.addEventListener("click", () => {
      toggleModal("#modal-upload-cover", false);
      document.getElementById("cover-file-input").value = "";
      document.getElementById("cover-url-input").value = "";
    });
  }

  if (coverSaveBtn) {
    coverSaveBtn.addEventListener("click", onSaveCover);
  }

  if (editCancelBtn) {
    editCancelBtn.addEventListener("click", () =>
      toggleModal("#modal-edit-game", false)
    );
  }

  if (editSaveBtn) {
    editSaveBtn.addEventListener("click", onSaveGameEdit);
  }

  if (screenshotCancelBtn) {
    screenshotCancelBtn.addEventListener("click", () => {
      toggleModal("#modal-add-screenshot", false);
      document.getElementById("screenshot-file-input").value = "";
      document.getElementById("screenshot-url-input").value = "";
    });
  }

  if (screenshotSaveBtn) {
    screenshotSaveBtn.addEventListener("click", onSaveScreenshot);
  }

  // Close modals on background click
  $$(".modal").forEach((modal) => {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) {
        toggleModal(`#${modal.id}`, false);
      }
    });
  });
  
  // Global search
  const globalSearchInput = $("#global-search-input");
  const globalSearchBtn = $("#global-search-btn");
  
  if (globalSearchInput) {
    globalSearchInput.addEventListener("keypress", (e) => {
      if (e.key === "Enter") {
        performGlobalSearch(globalSearchInput.value);
      }
    });
  }
  
  if (globalSearchBtn) {
    globalSearchBtn.addEventListener("click", () => {
      performGlobalSearch(globalSearchInput.value);
    });
  }
  
  // Completed stats click
  const statCompleted = $("#stat-completed");
  if (statCompleted) {
    statCompleted.addEventListener("click", showCompletedGamesModal);
  }
}

function toggleModal(selector, show) {
  let modal = $(selector);
  
  // If modal doesn't exist, try to recreate it or find an alternative
  if (!modal) {
    // For game detail modal, it might need to be fetched from the HTML
    if (selector === "#modal-game-detail") {
      const existingModal = document.getElementById("modal-game-detail");
      if (!existingModal) {
        console.warn(`Modal not found: ${selector}`);
        return;
      }
      modal = existingModal;
    } else {
      console.warn(`Modal not found: ${selector}`);
      return;
    }
  }
  
  if (show) {
    modal.classList.remove("hidden");
  } else {
    modal.classList.add("hidden");
  }
}

// -----------------------------------------------------------
// Load initial data from backend
// -----------------------------------------------------------
async function loadInitialData() {
  try {
    consoles = await apiCall("/consoles");
  } catch (e) {
    consoles = [];
  }

  renderConsoles();

  // Check for saved page state
  const savedState = loadPageState();
  
  if (savedState.view === 'console' && savedState.consoleId) {
    // Check if the saved console still exists
    const consoleExists = consoles.find(c => c.id === savedState.consoleId);
    if (consoleExists) {
      await selectConsole(savedState.consoleId);
      return;
    }
  }
  
  // Default: show homepage
  renderHomepage();
  updateConsoleSummary();
}

// -----------------------------------------------------------
// Consoles
// -----------------------------------------------------------
function renderConsoles() {
  const list = $("#console-list");
  list.innerHTML = "";

  consoles.forEach((c) => {
    const li = document.createElement("li");
    li.dataset.id = c.id;
    li.className = c.id === currentConsoleId ? "active" : "";
    li.innerHTML = `
      <button class="edit-console-btn" onclick="editConsole(${c.id}, event)" title="Rename console">✏️</button>
      <button class="delete-console-btn" onclick="deleteConsole(${c.id}, event)" title="Delete console">🗑️</button>
      <span class="console-name">${c.name}</span>
      <span class="console-count">${c.game_count} games</span>
    `;
    li.addEventListener("click", (e) => {
      if (!e.target.classList.contains('delete-console-btn') && !e.target.classList.contains('edit-console-btn')) {
        selectConsole(c.id);
      }
    });
    list.appendChild(li);
  });
}

let editingConsoleId = null;

async function onSaveConsole() {
  const name = $("#console-name-input").value.trim();
  const consoleType = document.querySelector('input[name="console-type"]:checked').value;
  const path = consoleType === "folder" ? $("#console-path-input").value.trim() : "";

  if (!name) {
    showToast("Please provide a console name.", "warning");
    return;
  }

  if (consoleType === "folder" && !path) {
    showToast("Please provide a folder path.", "warning");
    return;
  }

  try {
    if (editingConsoleId) {
      const consoleData = { name, path: path || "" };
      const updated = await apiCall(`/consoles/${editingConsoleId}`, {
        method: "PUT",
        body: JSON.stringify(consoleData),
      });

      const idx = consoles.findIndex(c => c.id === editingConsoleId);
      if (idx !== -1) {
        consoles[idx] = updated;
      }

      renderConsoles();
      updateConsoleSummary();
      showToast(`Console renamed to '${name}'!`, "success");
    } else {
      const consoleData = { name };
      if (path) {
        consoleData.path = path;
      }
      
      const created = await apiCall("/consoles", {
        method: "POST",
        body: JSON.stringify(consoleData),
      });

      consoles.push(created);
      gamesByConsole[created.id] = [];

      currentConsoleId = created.id;
      renderConsoles();
      updateConsoleSummary();
      await loadGamesForConsole(created.id);
      
      const msg = path 
        ? `Console '${name}' added and ${created.game_count} games scanned!`
        : `Console '${name}' created (empty). Use "Add Game" to add games.`;
      showToast(msg, "success");
    }
    
    toggleModal("#modal-console", false);
    $("#console-name-input").value = "";
    $("#console-path-input").value = "";
    $("#btn-console-save").textContent = "Save";
    editingConsoleId = null;
  } catch (e) {
    // Error already shown by apiCall
  }
}

function editConsole(id, event) {
  event.stopPropagation();
  const console = consoles.find(c => c.id === id);
  if (!console) return;

  editingConsoleId = id;
  $("#console-name-input").value = console.name;
  $("#console-path-input").value = console.path;
  $("#btn-console-save").textContent = "Rename";
  toggleModal("#modal-console", true);
}

// -----------------------------------------------------------
// Console selection & rescan
// -----------------------------------------------------------
async function selectConsole(id) {
  currentConsoleId = id;
  activeFilter = null;
  activeGenreFilter = null;
  activeStatusFilter = null;
  statusFilteredGames = [];
  currentPage = 1;
  genreFilterOpen = false;

  showConsoleView();
  savePageState();
  renderConsoles();
  renderStatusFilters();
  updateConsoleSummary();
  await loadGamesForConsole(id);
  extractGenres();
}

function updateConsoleSummary() {
  const titleEl = $("#console-name");
  const rescanBtn = $("#btn-rescan-console");

  const c = consoles.find((x) => x.id === currentConsoleId);
  if (!c) {
    titleEl.textContent = "Select a console";
    rescanBtn.disabled = true;
    return;
  }

  titleEl.textContent = c.name;
  rescanBtn.disabled = false;
}

async function onRescanConsole() {
  const c = consoles.find((x) => x.id === currentConsoleId);
  if (!c) return;

  try {
    const result = await apiCall(`/consoles/${c.id}/scan`, { method: "POST" });
    showToast(
      `Scan complete: ${result.added} games added, ${result.errors || 0} errors`,
      "success"
    );
    await loadGamesForConsole(c.id);
    extractGenres();
  } catch (e) {
    // Error already shown
  }
}

// -----------------------------------------------------------
// Metadata actions
// -----------------------------------------------------------
async function onFetchText() {
  if (!currentConsoleId) return;
  
  // Show confirmation dialog and wait for user choice
  const choice = await showMetadataFetchDialog();
  if (!choice) return; // User cancelled
  
  try {
    showToast(choice === "force" ? "Force updating all metadata..." : "Smart updating metadata...", "info");
    
    const forceParam = choice === "force" ? "?force=true" : "";
    const result = await apiCall(
      `/consoles/${currentConsoleId}/fetch-metadata${forceParam}`,
      { method: "POST" }
    );
    
    if (choice === "force") {
      showToast(`Force updated metadata for ${result.updated} games (${result.skipped} skipped)`, "success");
    } else {
      showToast(`Smart updated metadata for ${result.updated} games (${result.skipped} skipped)`, "success");
    }
    
    await loadGamesForConsole(currentConsoleId);
    extractGenres();
  } catch (e) {
    // Error already shown
  }
}

function showMetadataFetchDialog() {
  // Remove any existing modals first
  const existingModals = document.querySelectorAll('.modal');
  existingModals.forEach(m => m.remove());
  
  // Create modal with backdrop
  const modal = document.createElement('div');
  modal.className = 'modal active';
  modal.innerHTML = `
    <div class="modal-content">
      <h2>Fetch Metadata Strategy</h2>
      <div style="margin: 20px 0;">
        <div style="margin-bottom: 15px;">
          <label style="display: block; margin-bottom: 10px; font-weight: bold;">
            <input type="radio" name="fetch-strategy" value="smart" checked style="margin-right: 8px;">
            Smart Update (Recommended)
          </label>
          <p style="margin: 5px 0 15px; color: var(--text-muted); font-size: 0.9rem;">
            Only updates games without existing metadata. Preserves your manually edited descriptions.
          </p>
        </div>
        
        <div style="margin-bottom: 15px;">
          <label style="display: block; margin-bottom: 10px; font-weight: bold;">
            <input type="radio" name="fetch-strategy" value="force" style="margin-right: 8px;">
            Force Update All
          </label>
          <p style="margin: 5px 0 15px; color: var(--text-muted); font-size: 0.9rem;">
            Updates ALL games in this console. Will overwrite existing metadata.
          </p>
        </div>
      </div>
      
      <div class="modal-actions">
        <button onclick="closeMetadataDialog()">Cancel</button>
        <button onclick="confirmFetchStrategy(this)" style="background: var(--accent-color);">Proceed</button>
      </div>
    </div>
  `;
  
  document.body.appendChild(modal);
  
  // Return promise that resolves with user choice
  return new Promise((resolve) => {
    modal.confirmFetchStrategy = (button) => {
      const selected = modal.querySelector('input[name="fetch-strategy"]:checked').value;
      
      if (selected === "force") {
        const confirmation = prompt("Type '123' to confirm force update of ALL games:");
        if (confirmation !== "123") {
          showToast("Force update cancelled - incorrect confirmation", "error");
          closeMetadataDialog();
          resolve(null);
          return;
        }
      }
      
      closeMetadataDialog();
      resolve(selected);
    };
  });
}

function closeMetadataDialog() {
  const modal = document.querySelector('.modal');
  if (modal) {
    modal.remove();
  }
}

function confirmFetchStrategy(button) {
  const modal = button.closest('.modal');
  if (modal && typeof modal.confirmFetchStrategy === 'function') {
    modal.confirmFetchStrategy(button);
  }
}

function showCoverFetchDialog() {
  const existingModals = document.querySelectorAll('.modal');
  existingModals.forEach(m => m.remove());
  
  const modal = document.createElement('div');
  modal.className = 'modal active';
  modal.innerHTML = `
    <div class="modal-content">
      <h2>Fetch Covers</h2>
      <div style="margin: 20px 0;">
        <div style="margin-bottom: 20px;">
          <h3 style="margin: 0 0 10px; font-size: 1rem;">Select Source</h3>
          <div style="margin-bottom: 12px;">
            <label style="display: block; margin-bottom: 8px; font-weight: bold;">
              <input type="radio" name="fetch-source" value="duckduckgo" checked style="margin-right: 8px;">
              DuckDuckGo (Recommended)
            </label>
            <p style="margin: 5px 0 8px; color: var(--text-muted); font-size: 0.85rem;">
              Searches for box cover images. Better results for most games.
            </p>
          </div>
          <div>
            <label style="display: block; margin-bottom: 8px; font-weight: bold;">
              <input type="radio" name="fetch-source" value="rawg" style="margin-right: 8px;">
              RAWG
            </label>
            <p style="margin: 5px 0; color: var(--text-muted); font-size: 0.85rem;">
              Uses RAWG database. May have fewer but sometimes more accurate covers.
            </p>
          </div>
        </div>
        
        <div>
          <h3 style="margin: 0 0 10px; font-size: 1rem;">Select Strategy</h3>
          <div style="margin-bottom: 12px;">
            <label style="display: block; margin-bottom: 8px; font-weight: bold;">
              <input type="radio" name="fetch-strategy" value="smart" checked style="margin-right: 8px;">
              Smart Update (Recommended)
            </label>
            <p style="margin: 5px 0 8px; color: var(--text-muted); font-size: 0.85rem;">
              Only updates games without existing covers. Preserves your manually downloaded covers.
            </p>
          </div>
          <div>
            <label style="display: block; margin-bottom: 8px; font-weight: bold;">
              <input type="radio" name="fetch-strategy" value="force" style="margin-right: 8px;">
              Force Update All
            </label>
            <p style="margin: 5px 0; color: var(--text-muted); font-size: 0.85rem;">
              Updates ALL games in this console. Will overwrite existing covers.
            </p>
          </div>
        </div>
      </div>
      
      <div class="modal-actions">
        <button onclick="this.closest('.modal').remove(); resolve(null);">Cancel</button>
        <button onclick="confirmCoverStrategy(this)" style="background: var(--accent-color);">Proceed</button>
      </div>
    </div>
  `;
  
  document.body.appendChild(modal);
  
  return new Promise((resolve) => {
    modal.confirmCoverStrategy = (button) => {
      const source = modal.querySelector('input[name="fetch-source"]:checked').value;
      const strategy = modal.querySelector('input[name="fetch-strategy"]:checked').value;
      
      if (strategy === "force") {
        const confirmation = prompt("Type '123' to confirm force update of ALL covers:");
        if (confirmation !== "123") {
          showToast("Force update cancelled - incorrect confirmation", "error");
          closeCoverDialog();
          resolve(null);
          return;
        }
      }
      
      closeCoverDialog();
      resolve({ source, strategy });
    };
  });
}

function closeCoverDialog() {
  const modal = document.querySelector('.modal');
  if (modal) {
    modal.remove();
  }
}

function confirmCoverStrategy(button) {
  const modal = button.closest('.modal');
  if (modal && typeof modal.confirmCoverStrategy === 'function') {
    modal.confirmCoverStrategy(button);
  }
}

async function onFetchCovers() {
  if (!currentConsoleId) return;
  
  const choice = await showCoverFetchDialog();
  if (!choice) return;
  
  try {
    setLoading(true);
    const { source, strategy } = choice;
    showToast(strategy === "force" ? "Force updating all covers..." : "Smart updating covers...", "info");
    
    const params = new URLSearchParams();
    if (strategy === "force") params.append("force", "true");
    if (source) params.append("source", source);
    
    const result = await apiCall(
      `/consoles/${currentConsoleId}/fetch-covers?${params.toString()}`,
      { method: "POST" }
    );
    
    if (strategy === "force") {
      showToast(`Force updated covers for ${result.updated} games (${result.skipped} skipped)`, "success");
    } else {
      showToast(`Smart updated covers for ${result.updated} games (${result.skipped} skipped)`, "success");
    }
    await loadGamesForConsole(currentConsoleId);
  } catch (e) {
    // Error already shown
  } finally {
    setLoading(false);
  }
}

async function onFetchScreenshots() {
  if (!currentConsoleId) return;
  
  // Show confirmation dialog
  const result = await showScreenshotFetchDialog();
  if (!result) return;
  
  const { strategy, source } = result;
  
  try {
    showToast(strategy === "force" ? "Force fetching all screenshots..." : "Smart fetching missing screenshots...", "info");
    
    const params = new URLSearchParams();
    if (strategy === "force") params.append("force", "true");
    if (source) params.append("source", source);
    
    const fetchResult = await apiCall(
      `/consoles/${currentConsoleId}/fetch-screenshots?${params.toString()}`,
      { method: "POST" }
    );
    
    if (strategy === "force") {
      showToast(`Force fetched screenshots for ${fetchResult.updated} games (${fetchResult.skipped} skipped)`, "success");
    } else {
      showToast(`Smart fetched screenshots for ${fetchResult.updated} games (${fetchResult.skipped} skipped)`, "success");
    }
    
    await loadGamesForConsole(currentConsoleId);
  } catch (e) {
    // Error already shown
  }
}

function showScreenshotFetchDialog() {
  return new Promise((resolve) => {
    // Remove any existing modals first
    const existingModals = document.querySelectorAll('.modal');
    existingModals.forEach(m => m.remove());
    
    // Create modal with backdrop
    const modal = document.createElement('div');
    modal.className = 'modal active';
    modal.innerHTML = `
      <div class="modal-content">
        <h2>Fetch Screenshots Strategy</h2>
        <div style="margin: 20px 0;">
          <div style="margin-bottom: 20px;">
            <h3 style="margin: 0 0 10px; font-size: 1rem;">Select Source</h3>
            <div style="margin-bottom: 12px;">
              <label style="display: block; margin-bottom: 8px; font-weight: bold;">
                <input type="radio" name="fetch-source" value="duckduckgo" checked style="margin-right: 8px;">
                DuckDuckGo (Recommended)
              </label>
              <p style="margin: 5px 0 8px; color: var(--text-muted); font-size: 0.85rem;">
                Searches for screenshots. Works for any console. No API key needed.
              </p>
            </div>
            <div>
              <label style="display: block; margin-bottom: 8px; font-weight: bold;">
                <input type="radio" name="fetch-source" value="rawg" style="margin-right: 8px;">
                RAWG
              </label>
              <p style="margin: 5px 0; color: var(--text-muted); font-size: 0.85rem;">
                Uses RAWG database. Requires API key in homepage settings.
              </p>
            </div>
          </div>
          
          <div style="margin-bottom: 15px;">
            <label style="display: block; margin-bottom: 10px; font-weight: bold;">
              <input type="radio" name="fetch-strategy" value="smart" checked style="margin-right: 8px;">
              Smart Update (Recommended)
            </label>
            <p style="margin: 5px 0 15px; color: var(--text-muted); font-size: 0.9rem;">
              Only fetches screenshots for games that don't have any. Preserves existing screenshots.
            </p>
          </div>
          
          <div style="margin-bottom: 15px;">
            <label style="display: block; margin-bottom: 10px; font-weight: bold;">
              <input type="radio" name="fetch-strategy" value="force" style="margin-right: 8px;">
              Force Update All
            </label>
            <p style="margin: 5px 0 15px; color: var(--text-muted); font-size: 0.9rem;">
              Re-fetches ALL games in this console. Will overwrite existing screenshots.
            </p>
          </div>
        </div>
        
        <div class="modal-actions">
          <button id="btn-screenshot-cancel">Cancel</button>
          <button id="btn-screenshot-proceed" style="background: var(--accent-color);">Proceed</button>
        </div>
      </div>
    `;
    
    document.body.appendChild(modal);
    
    // Add event listeners
    document.getElementById('btn-screenshot-cancel').addEventListener('click', () => {
      modal.remove();
      resolve(null);
    });
    
    document.getElementById('btn-screenshot-proceed').addEventListener('click', () => {
      const strategy = document.querySelector('input[name=fetch-strategy]:checked').value;
      const source = document.querySelector('input[name=fetch-source]:checked').value;
      modal.remove();
      resolve({ strategy, source });
    });
  });
}

// -----------------------------------------------------------
// Load games for a console
// -----------------------------------------------------------
async function loadGamesForConsole(consoleId) {
  try {
    const games = await apiCall(`/consoles/${consoleId}/games`);
    gamesByConsole[consoleId] = games;
  } catch (e) {
    gamesByConsole[consoleId] = [];
  }

  try {
    consoleStats = await apiCall(`/consoles/${consoleId}/stats`);
  } catch (e) {
    consoleStats = null;
  }

  renderConsoles();
  renderGamesForCurrentConsole();
  renderStatusFilters();
}

// -----------------------------------------------------------
// Alphabetical index (0–9 + A–Z + All)
// -----------------------------------------------------------
function renderAlphaIndex() {
  const container = $("#alpha-index");
  container.innerHTML = "";

  // First button: 0–9
  const numBtn = document.createElement("button");
  numBtn.className = activeFilter === "0-9" ? "active" : "secondary";
  numBtn.textContent = "0–9";
  numBtn.addEventListener("click", () => applyFilter("0-9"));
  container.appendChild(numBtn);

  // A–Z buttons
  const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
  letters.forEach((letter) => {
    const btn = document.createElement("button");
    btn.className = activeFilter === letter ? "active" : "secondary";
    btn.textContent = letter;
    btn.addEventListener("click", () => applyFilter(letter));
    container.appendChild(btn);
  });

  // Reset filter
  const resetBtn = document.createElement("button");
  resetBtn.className = !activeFilter ? "active" : "secondary";
  resetBtn.textContent = "All";
  resetBtn.addEventListener("click", () => {
    activeFilter = null;
    currentPage = 1;
    renderAlphaIndex();
    renderGamesForCurrentConsole();
  });
  container.appendChild(resetBtn);
}

function applyFilter(letter) {
  activeFilter = letter;
  currentPage = 1;
  renderAlphaIndex();
  renderGamesForCurrentConsole();
}

// -----------------------------------------------------------
// Games rendering (with filtering + pagination)
// -----------------------------------------------------------
function renderGamesForCurrentConsole() {
  const container = $("#game-list");
  container.innerHTML = "";

  let games;
  
  // If status filter is active, use the pre-fetched status-filtered games (even on homepage)
  if (activeStatusFilter && statusFilteredGames.length > 0) {
    games = statusFilteredGames.slice();
  } else if (!currentConsoleId) {
    container.innerHTML = `<p>Select a console to see its games.</p>`;
    return;
  } else {
    games = (gamesByConsole[currentConsoleId] || [])
      .slice()
      .sort((a, b) => a.title.localeCompare(b.title));
  }

  // Apply alphabetical filter (only when not using status filter)
  if (!activeStatusFilter && activeFilter) {
    if (activeFilter === "0-9") {
      games = games.filter((g) => /^[0-9]/.test(g.title));
    } else {
      games = games.filter((g) =>
        g.title.toUpperCase().startsWith(activeFilter)
      );
    }
  }

  // Apply genre filter (only when not using status filter)
  if (!activeStatusFilter && activeGenreFilter) {
    games = games.filter((g) => {
      if (!g.genre) return false;
      return g.genre.split(",").some((genre) =>
        genre.trim() === activeGenreFilter
      );
    });
  }

  const totalPages = Math.ceil(games.length / PAGE_SIZE);
  if (currentPage > totalPages) currentPage = 1;

  const start = (currentPage - 1) * PAGE_SIZE;
  const end = start + PAGE_SIZE;
  const pageGames = games.slice(start, end);

  if (!pageGames.length) {
    container.innerHTML = `<p>No games found.</p>`;
    return;
  }

  pageGames.forEach((g) => {
    const card = document.createElement("article");
    card.className = "game-card";
    card.dataset.id = g.id;
    card.dataset.title = g.title;

    const cover = g.cover_url
      ? `<img src="${toAbsoluteUrl(g.cover_url)}${g.cover_url.includes('?') ? '&' : '?'}t=${Date.now()}" alt="${g.title} cover" />`
      : `<div class="no-cover">No cover</div>`;

    card.innerHTML = `
      <div class="game-cover" style="position: relative;">
        ${cover}
        <button class="game-card-fetch-btn" onclick="fetchSingleGameMetadata(${g.id}, event)" title="Fetch metadata">🔄</button>
        <button class="game-card-edit-cover" onclick="openCoverUploadModal(${g.id})" title="Upload cover">📷</button>
        <button class="game-card-delete" onclick="deleteGame(${g.id}, event)" title="Delete game">🗑️</button>
        <button class="game-card-fetch-cover" onclick="fetchSingleGameCover(${g.id}, event)" title="Fetch cover from DuckDuckGo">🖼️</button>
      </div>
      <div class="game-title">${g.title}</div>
      <div class="game-meta">${g.genre || "Unknown genre"}</div>
      <div class="game-actions">
      </div>
    `;

    // Make the entire card clickable to open game detail
    card.addEventListener("click", (event) => {
      // Don't open if clicking on buttons
      if (event.target.closest('.game-card-fetch-btn, .game-card-edit-cover, .game-card-delete, .game-card-fetch-cover')) {
        return;
      }
      openGameDetail(g.id);
    });

    container.appendChild(card);
  });

  // Pagination
  const pagination = document.createElement("div");
  pagination.className = "pagination";

  if (currentPage > 1) {
    const prev = document.createElement("button");
    prev.textContent = "Previous";
    prev.addEventListener("click", () => {
      currentPage--;
      renderGamesForCurrentConsole();
    });
    pagination.appendChild(prev);
  }

  const info = document.createElement("span");
  info.textContent = `Page ${currentPage} of ${totalPages}`;
  pagination.appendChild(info);

  if (currentPage < totalPages) {
    const next = document.createElement("button");
    next.textContent = "Next";
    next.addEventListener("click", () => {
      currentPage++;
      renderGamesForCurrentConsole();
    });
    pagination.appendChild(next);
  }

  container.appendChild(pagination);
}

// -----------------------------------------------------------
// Game detail modal
// -----------------------------------------------------------
async function openGameDetail(gameId) {
  try {
    const game = await apiCall(`/games/${gameId}`);
    currentGameDetail = game;
    currentLightboxScreenshots = game.screenshots || [];
    
    // Reset description pagination state
    currentDescriptionPage = 1;
    totalDescriptionPages = 1;
    
    // Record that user viewed this game
    recordGameView(gameId);
    
    // Fetch game status for completed date/comment
    currentGameStatus = await loadGameStatus(gameId);
    
    // Update game index for navigation
    currentGamesList = (gamesByConsole[currentConsoleId] || [])
      .slice()
      .sort((a, b) => a.title.localeCompare(b.title));
    
    // Apply filters if active
    if (activeFilter || activeGenreFilter) {
      if (activeFilter) {
        if (activeFilter === "0-9") {
          currentGamesList = currentGamesList.filter((g) => /^[0-9]/.test(g.title));
        } else {
          currentGamesList = currentGamesList.filter((g) =>
            g.title.toUpperCase().startsWith(activeFilter)
          );
        }
      }
      if (activeGenreFilter) {
        currentGamesList = currentGamesList.filter((g) => {
          if (!g.genre) return false;
          return g.genre.split(",").some((genre) =>
            genre.trim() === activeGenreFilter
          );
        });
      }
    }
    
    currentGameIndex = currentGamesList.findIndex((g) => g.id === gameId);
    
    renderGameDetail(game);
    toggleModal("#modal-game-detail", true);
  } catch (e) {
    // Error already shown
  }
}

function renderGameDetail(game) {
  const modal = $("#modal-game-detail");
  if (!modal) return;

  // Calculate description pagination
  const descriptionText = game.description || "No description available";
  const charsPerPage = 800;
  totalDescriptionPages = Math.max(1, Math.ceil(descriptionText.length / charsPerPage));
  if (currentDescriptionPage > totalDescriptionPages) currentDescriptionPage = 1;
  
  const startIdx = (currentDescriptionPage - 1) * charsPerPage;
  const endIdx = Math.min(startIdx + charsPerPage, descriptionText.length);
  const currentDescription = descriptionText.slice(startIdx, endIdx);
  
  const descPaginationHtml = totalDescriptionPages > 1 
    ? `<div class="desc-pagination">
        <button onclick="changeDescriptionPage(-1)" ${currentDescriptionPage <= 1 ? 'disabled' : ''}>◀</button>
        <span>${currentDescriptionPage}/${totalDescriptionPages}</span>
        <button onclick="changeDescriptionPage(1)" ${currentDescriptionPage >= totalDescriptionPages ? 'disabled' : ''}>▶</button>
      </div>`
    : '';

  // Check for completed status and note
  const completedNote = currentGameStatus?.completed_date_note;
  const hasCompletedNote = completedNote && completedNote.trim().length > 0;
  const notePreview = hasCompletedNote ? getNotePreview(completedNote) : '';
  
  const completedHtml = hasCompletedNote
    ? `<p class="game-detail-completed">
        <span class="completed-indicator" data-note="${escapeHtml(completedNote)}" onclick="openCompletedCommentModal(this)" title="Click to view completion notes">✅</span>
        <span class="completed-preview">${notePreview}</span>
      </p>`
    : '';

  const content = modal.querySelector(".modal-game-content");
  if (!content) return;

  const cover = game.cover_url
    ? `
      <div style="position: relative;">
        <img src="${toAbsoluteUrl(game.cover_url)}${game.cover_url.includes('?') ? '&' : '?'}t=${Date.now()}" alt="${game.title} cover" class="game-detail-cover" style="cursor:pointer;" onclick="openCoverLightbox('${toAbsoluteUrl(game.cover_url)}?t=${Date.now()}')" title="Click to view full size" />
        <button class="delete-cover-btn" onclick="deleteGameCover(${game.id})" title="Delete cover">🗑️</button>
      </div>
    `
    : `<div class="no-cover">No cover</div>`;

  const screenshotsHtml =
    game.screenshots && game.screenshots.length > 0
      ? `
    <div class="game-detail-screenshots">
      <h3>Screenshots (${game.screenshots.length})</h3>
      <div class="screenshots-grid">
        ${game.screenshots
          .map(
            (screenshot) => `
              <div style="position: relative;">
                <img src="${toAbsoluteUrl(screenshot.url)}?t=${Date.now()}" alt="Screenshot" class="screenshot-thumb" onclick="openLightbox('${toAbsoluteUrl(screenshot.url)}?t=${Date.now()}')" />
                <button class="delete-screenshot-btn" onclick="deleteScreenshot(${screenshot.id})" title="Delete screenshot">🗑️</button>
              </div>
            `
          )
          .join("")}
      </div>
    </div>
  `
      : "";

  const isFirst = currentGameIndex <= 0;
  const isLast = currentGameIndex >= currentGamesList.length - 1;
  const positionText = currentGamesList.length > 0 
    ? `${currentGameIndex + 1} / ${currentGamesList.length}` 
    : '';

  content.innerHTML = `
    <button class="modal-close" onclick="toggleModal('#modal-game-detail', false)">×</button>
    <button class="game-nav-btn game-nav-prev ${isFirst ? 'disabled' : ''}" 
      onclick="navigateToPrevGame()" ${isFirst ? 'disabled' : ''} title="Previous game (←)">◀</button>
    <button class="game-nav-btn game-nav-next ${isLast ? 'disabled' : ''}" 
      onclick="navigateToNextGame()" ${isLast ? 'disabled' : ''} title="Next game (→)">▶</button>
    <div class="game-detail-position">${positionText}</div>
    <div class="game-detail-actions">
      <button class="game-detail-edit-btn secondary" onclick="openEditGameModal(${game.id})">✏️ Edit Details</button>
      <button class="game-detail-fetch-btn secondary" onclick="fetchSingleGameMetadata(${game.id})">🔄 Fetch Metadata</button>
      <button class="game-detail-fetch-btn secondary" onclick="fetchSingleGameScreenshots(${game.id})">🖼️ Fetch Screenshots</button>
      <button class="game-detail-fetch-btn secondary" onclick="openAddScreenshotModal(${game.id}, ${game.screenshots ? game.screenshots.length : 0})" ${game.screenshots && game.screenshots.length >= 5 ? 'disabled title="Maximum 5 screenshots reached"' : ''}>➕ Add Screenshot</button>
    </div>
    <div class="game-detail-container">
      <div class="game-detail-header">
        ${cover}
        <div class="game-detail-info">
          <h2>${game.title}</h2>
          <p class="game-detail-genre"><strong>Genre:</strong> ${game.genre || "Unknown"}</p>
          <p class="game-detail-desc"><strong>Description:</strong> ${currentDescription}</p>
          ${descPaginationHtml}
          ${completedHtml}
        </div>
      </div>
      ${screenshotsHtml}
    </div>
  `;
}

// -----------------------------------------------------------
// Game Detail Navigation
// -----------------------------------------------------------
async function navigateToPrevGame() {
  if (currentGameIndex <= 0 || currentGamesList.length === 0) return;
  
  currentGameIndex--;
  const prevGame = currentGamesList[currentGameIndex];
  
  try {
    const game = await apiCall(`/games/${prevGame.id}`);
    currentGameDetail = game;
    currentLightboxScreenshots = game.screenshots || [];
    currentDescriptionPage = 1;
    currentGameStatus = await loadGameStatus(prevGame.id);
    renderGameDetail(game);
  } catch (e) {
    showToast("Failed to load previous game", "error");
  }
}

async function navigateToNextGame() {
  if (currentGameIndex >= currentGamesList.length - 1 || currentGamesList.length === 0) return;
  
  currentGameIndex++;
  const nextGame = currentGamesList[currentGameIndex];
  
  try {
    const game = await apiCall(`/games/${nextGame.id}`);
    currentGameDetail = game;
    currentLightboxScreenshots = game.screenshots || [];
    currentDescriptionPage = 1;
    currentGameStatus = await loadGameStatus(nextGame.id);
    renderGameDetail(game);
  } catch (e) {
    showToast("Failed to load next game", "error");
  }
}

function changeDescriptionPage(delta) {
  const newPage = currentDescriptionPage + delta;
  if (newPage >= 1 && newPage <= totalDescriptionPages) {
    currentDescriptionPage = newPage;
    renderGameDetail(currentGameDetail);
  }
}

function getNotePreview(note) {
  if (!note) return '';
  const words = note.trim().split(/\s+/);
  const previewWords = words.slice(0, 20);
  let preview = previewWords.join(' ');
  if (words.length > 20) {
    preview += '...';
  }
  return preview;
}

function escapeHtml(text) {
  if (!text) return '';
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function openCompletedCommentModal(element) {
  const note = element.getAttribute('data-note');
  const content = $("#completed-comment-content");
  content.innerHTML = `<div>${note}</div>`;
  toggleModal("#modal-completed-comment", true);
}

// -----------------------------------------------------------
// Single Game Metadata Fetch
// -----------------------------------------------------------
async function fetchSingleGameMetadata(gameId, event) {
  if (event) {
    event.stopPropagation();
  }
  
  try {
    showToast("Fetching metadata for this game...", "info");
    
    const result = await apiCall(
      `/games/${gameId}/fetch-metadata`,
      { method: "POST" }
    );
    
    if (result.status === "ok") {
      showToast(`Metadata updated for "${result.title}"`, "success");
      
      // Update the current game detail if modal is open
      if (currentGameDetail && currentGameDetail.id === gameId) {
        // Refresh the game data
        const updatedGame = await apiCall(`/games/${gameId}`);
        currentGameDetail = updatedGame;
        renderGameDetail(updatedGame);
      }
      
      // Refresh games list to show updated covers
      if (currentConsoleId) {
        await loadGamesForConsole(currentConsoleId);
        extractGenres();
      }
    } else {
      showToast("Failed to fetch metadata", "error");
    }
  } catch (e) {
    showToast("Error fetching metadata", "error");
  }
}

// -----------------------------------------------------------
// Single Game Screenshots Fetch
// -----------------------------------------------------------
async function fetchSingleGameScreenshots(gameId, event) {
  if (event) {
    event.stopPropagation();
  }
  
  if (!confirm("This will overwrite existing screenshots. Continue?")) {
    return;
  }
  
  try {
    showToast("Fetching screenshots for this game...", "info");
    
    const result = await apiCall(
      `/games/${gameId}/fetch-screenshots`,
      { method: "POST" }
    );
    
    if (result.status === "ok") {
      showToast(`Fetched ${result.updated} screenshots for "${result.title}"`, "success");
      
      // Update the current game detail if modal is open
      if (currentGameDetail && currentGameDetail.id === gameId) {
        // Refresh the game data
        const updatedGame = await apiCall(`/games/${gameId}`);
        currentGameDetail = updatedGame;
        renderGameDetail(updatedGame);
      }
      
      // Refresh games list
      if (currentConsoleId) {
        await loadGamesForConsole(currentConsoleId);
      }
    } else {
      showToast("Failed to fetch screenshots", "error");
    }
  } catch (e) {
    showToast("Error fetching screenshots", "error");
  }
}

// -----------------------------------------------------------
// Single Game Cover Fetch (DuckDuckGo)
// -----------------------------------------------------------
async function fetchSingleGameCover(gameId, event) {
  if (event) {
    event.stopPropagation();
  }
  
  try {
    showToast("Fetching cover from DuckDuckGo...", "info");
    
    const result = await apiCall(
      `/games/${gameId}/fetch-cover`,
      { method: "POST" }
    );
    
    if (result.status === "ok") {
      showToast(`Cover updated for "${result.title}"`, "success");
      
      // Update the current game detail if modal is open
      if (currentGameDetail && currentGameDetail.id === gameId) {
        const updatedGame = await apiCall(`/games/${gameId}`);
        currentGameDetail = updatedGame;
        renderGameDetail(updatedGame);
      }
      
      // Refresh games list
      if (currentConsoleId) {
        await loadGamesForConsole(currentConsoleId);
      }
    } else {
      showToast(result.detail || "Failed to fetch cover", "error");
    }
  } catch (e) {
    showToast("Error fetching cover", "error");
  }
}

// -----------------------------------------------------------
// Delete functions
// -----------------------------------------------------------
async function deleteGame(gameId, event) {
  event.stopPropagation();
  
  if (!confirm("Are you sure you want to delete this game and all its files? This action cannot be undone.")) {
    return;
  }

  try {
    await apiCall(`/games/${gameId}`, { method: "DELETE" });
    showToast("Game deleted successfully", "success");
    
    // Reload games for current console
    await loadGamesForConsole(currentConsoleId);
    extractGenres();
    await loadStats();
  } catch (error) {
    // Error already shown by apiCall
  }
}

async function deleteConsole(consoleId, event) {
  event.stopPropagation();
  
  const console = consoles.find(c => c.id === consoleId);
  if (!console) return;
  
  if (!confirm(`Are you sure you want to delete the console "${console.name}" and ALL its games? This action cannot be undone.`)) {
    return;
  }

  try {
    await apiCall(`/consoles/${consoleId}`, { method: "DELETE" });
    showToast("Console and all games deleted successfully", "success");
    
    // Remove from local state
    consoles = consoles.filter(c => c.id !== consoleId);
    delete gamesByConsole[consoleId];
    
    // If this was the current console, reset selection
    if (currentConsoleId === consoleId) {
      currentConsoleId = null;
    }
    
    renderConsoles();
    updateConsoleSummary();
    renderGamesForCurrentConsole();
    await loadStats();
  } catch (error) {
    // Error already shown by apiCall
  }
}

async function deleteGameCover(gameId) {
  if (!confirm("Are you sure you want to delete this cover?")) {
    return;
  }

  try {
    await apiCall(`/games/${gameId}/cover`, { method: "DELETE" });
    showToast("Cover deleted successfully", "success");
    
    // Reload games to update the display
    await loadGamesForConsole(currentConsoleId);
  } catch (error) {
    // Error already shown by apiCall
  }
}

async function deleteScreenshot(screenshotId) {
  if (!confirm("Are you sure you want to delete this screenshot?")) {
    return;
  }

  try {
    await apiCall(`/screenshots/${screenshotId}`, { method: "DELETE" });
    showToast("Screenshot deleted successfully", "success");
    
    // If we have a current game detail open, refresh it
    if (currentGameDetail) {
      openGameDetail(currentGameDetail.id);
    }
  } catch (error) {
    // Error already shown by apiCall
  }
}

// -----------------------------------------------------------
// Theme handling
// -----------------------------------------------------------
async function onSaveTheme() {
  const bgColor = $("#theme-bg-color").value;
  const accent = $("#theme-accent-color").value;
  let headerImage = $("#theme-header-image").value.trim();

  const handleThemeSave = async (finalHeaderImage) => {
    const theme = { bgColor, accent, headerImage: finalHeaderImage };
    localStorage.setItem("gameArchiveTheme", JSON.stringify(theme));
    applyTheme(theme);
    toggleModal("#modal-theme", false);
    showToast("Theme saved!", "success");
  };

  const fileInput = $("#theme-header-upload");
  if (fileInput.files && fileInput.files[0]) {
    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append("file", file);

    try {
      setLoading(true);
      const res = await fetch(`${API}/theme/upload-header`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) throw new Error("Upload failed");
      const result = await res.json();
      headerImage = result.url;
    } catch (e) {
      showToast("Failed to upload header: " + e.message, "error");
      setLoading(false);
      return;
    }
    setLoading(false);
  }

  handleThemeSave(headerImage);
}

function applySavedTheme() {
  const raw = localStorage.getItem("gameArchiveTheme");
  if (!raw) return;
  try {
    const theme = JSON.parse(raw);
    applyTheme(theme);
  } catch (e) {
    console.error("Failed to parse saved theme:", e);
  }
}

function applyTheme(theme) {
  if (theme.bgColor) {
    document.documentElement.style.setProperty("--bg-color", theme.bgColor);
    document.body.style.background = theme.bgColor;
  }
  if (theme.accent) {
    document.documentElement.style.setProperty("--accent", theme.accent);
  }
  if (theme.headerImage) {
    const img = new Image();
    img.onload = function() {
      $(".app-header").style.backgroundImage = `url("${theme.headerImage}")`;
      $(".app-header").style.backgroundSize = "100% auto";
      $(".app-header").style.backgroundPosition = "center";
      $(".app-header").style.height = this.naturalHeight + "px";
    };
    img.onerror = function() {
      $(".app-header").style.backgroundImage = `url("${theme.headerImage}")`;
      $(".app-header").style.backgroundSize = "cover";
      $(".app-header").style.backgroundPosition = "center";
    };
    img.src = theme.headerImage;
  } else {
    $(".app-header").style.backgroundImage = "none";
    $(".app-header").style.backgroundSize = "cover";
    $(".app-header").style.height = "";
  }
}

// -----------------------------------------------------------
// Title collapse
// -----------------------------------------------------------
function toggleTitleCollapse() {
  const titleArea = $(".title-area");
  const arrow = $("#title-collapse-arrow");
  const collapsed = titleArea.classList.toggle("collapsed");
  
  arrow.textContent = collapsed ? "▶" : "▼";
  localStorage.setItem("titleCollapsed", collapsed ? "true" : "false");
}

function loadTitleCollapseState() {
  const collapsed = localStorage.getItem("titleCollapsed") === "true";
  if (collapsed) {
    $(".title-area").classList.add("collapsed");
    $("#title-collapse-arrow").textContent = "▶";
  }
}

// -----------------------------------------------------------
// Title rename
// -----------------------------------------------------------
function startRenameTitle() {
  const titleInput = $("#title-edit-input");
  const currentTitle = $("#app-title").textContent;
  
  $("#app-title").classList.add("hidden");
  $(".pencil-icon").classList.add("hidden");
  titleInput.value = currentTitle;
  titleInput.classList.remove("hidden");
  titleInput.focus();
  titleInput.select();
}

function finishRenameTitle() {
  const titleInput = $("#title-edit-input");
  const newTitle = titleInput.value.trim();
  
  titleInput.classList.add("hidden");
  $("#app-title").classList.remove("hidden");
  $(".pencil-icon").classList.remove("hidden");
  
  if (newTitle) {
    const title = newTitle;
    localStorage.setItem("customTitle", title);
    $("#app-title").textContent = title;
    $("#homepage-title").textContent = title;
  }
}

function handleRenameTitleKey(event) {
  if (event.key === "Enter") {
    finishRenameTitle();
  } else if (event.key === "Escape") {
    $("#title-edit-input").classList.add("hidden");
    $("#app-title").classList.remove("hidden");
    $(".pencil-icon").classList.remove("hidden");
  }
}

function loadCustomTitle() {
  const customTitle = localStorage.getItem("customTitle");
  if (customTitle) {
    $("#app-title").textContent = customTitle;
    $("#homepage-title").textContent = customTitle;
  }
}

// -----------------------------------------------------------
// Header management
// -----------------------------------------------------------
async function populateThemeModal() {
  const currentHeaderImg = $("#theme-current-header-img");
  const currentHeaderDiv = $("#theme-current-header");
  
  try {
    const res = await fetch(`${API}/theme/header`);
    const data = await res.json();
    
    if (data.exists) {
      currentHeaderImg.src = data.url;
      currentHeaderDiv.classList.remove("hidden");
    } else {
      currentHeaderDiv.classList.add("hidden");
    }
  } catch (e) {
    currentHeaderDiv.classList.add("hidden");
  }
}

async function onRemoveThemeHeader() {
  try {
    setLoading(true);
    const res = await fetch(`${API}/theme/header`, { method: "DELETE" });
    if (!res.ok) throw new Error("Failed to delete");
    
    const raw = localStorage.getItem("gameArchiveTheme");
    if (raw) {
      const theme = JSON.parse(raw);
      theme.headerImage = "";
      localStorage.setItem("gameArchiveTheme", JSON.stringify(theme));
      applyTheme(theme);
    }
    
    $("#theme-current-header").classList.add("hidden");
    $("#theme-header-image").value = "";
    $("#theme-header-upload").value = "";
    
    showToast("Header image removed", "success");
  } catch (e) {
    showToast("Failed to remove header: " + e.message, "error");
  }
  setLoading(false);
}

let headerRotationInterval = null;

async function onRandomHeader() {
  try {
    setLoading(true);
    const res = await fetch(`${API}/theme/headers`);
    const data = await res.json();
    
    if (!data.headers || data.headers.length === 0) {
      showToast("No header images available", "warning");
      setLoading(false);
      return;
    }
    
    const randomHeader = data.headers[Math.floor(Math.random() * data.headers.length)];
    const headerUrl = `/headers/${randomHeader}`;
    
    const raw = localStorage.getItem("gameArchiveTheme");
    const theme = raw ? JSON.parse(raw) : {};
    theme.headerImage = headerUrl;
    localStorage.setItem("gameArchiveTheme", JSON.stringify(theme));
    applyTheme(theme);
    
    showToast("Header changed!", "success");
  } catch (e) {
    showToast("Failed to change header: " + e.message, "error");
  }
  setLoading(false);
}

const HEADER_ROTATION_INTERVAL = 2 * 60 * 60 * 1000; // 2 hours in milliseconds

async function applyRandomHeaderOnLoad() {
  try {
    const res = await fetch(`${API}/theme/headers`);
    const data = await res.json();
    
    if (!data.headers || data.headers.length === 0) {
      return;
    }
    
    const lastChanged = parseInt(localStorage.getItem("headerChangedAt")) || 0;
    const now = Date.now();
    const elapsed = now - lastChanged;
    
    // Check if we need to rotate (either first time or 2+ hours passed)
    if (lastChanged === 0 || elapsed >= HEADER_ROTATION_INTERVAL) {
      // Pick new random header
      const savedIndex = localStorage.getItem("headerIndex");
      let headerIndex;
      
      do {
        headerIndex = Math.floor(Math.random() * data.headers.length);
      } while (data.headers.length > 1 && headerIndex === parseInt(savedIndex));
      
      localStorage.setItem("headerIndex", headerIndex);
      localStorage.setItem("headerChangedAt", now);
      
      const headerUrl = `/headers/${data.headers[headerIndex]}`;
      
      const raw = localStorage.getItem("gameArchiveTheme");
      const theme = raw ? JSON.parse(raw) : {};
      theme.headerImage = headerUrl;
      localStorage.setItem("gameArchiveTheme", JSON.stringify(theme));
      applyTheme(theme);
    } else {
      // Apply saved header if exists
      const raw = localStorage.getItem("gameArchiveTheme");
      if (raw) {
        const theme = JSON.parse(raw);
        if (theme.headerImage) {
          applyTheme(theme);
        }
      }
    }
    
    // Schedule rotation (will rotate after remaining time)
    const remainingTime = Math.max(HEADER_ROTATION_INTERVAL - elapsed, 0);
    
    headerRotationInterval = setTimeout(async () => {
      try {
        const res = await fetch(`${API}/theme/headers`);
        const data = await res.json();
        if (data.headers && data.headers.length > 0) {
          const newIndex = Math.floor(Math.random() * data.headers.length);
          localStorage.setItem("headerIndex", newIndex);
          localStorage.setItem("headerChangedAt", Date.now());
          const newHeaderUrl = `/headers/${data.headers[newIndex]}`;
          const currentTheme = JSON.parse(localStorage.getItem("gameArchiveTheme") || "{}");
          currentTheme.headerImage = newHeaderUrl;
          localStorage.setItem("gameArchiveTheme", JSON.stringify(currentTheme));
          applyTheme(currentTheme);
        }
        
        // Continue rotating every 2 hours
        headerRotationInterval = setInterval(async () => {
          const res = await fetch(`${API}/theme/headers`);
          const data = await res.json();
          if (data.headers && data.headers.length > 0) {
            const newIndex = Math.floor(Math.random() * data.headers.length);
            localStorage.setItem("headerIndex", newIndex);
            localStorage.setItem("headerChangedAt", Date.now());
            const newHeaderUrl = `/headers/${data.headers[newIndex]}`;
            const currentTheme = JSON.parse(localStorage.getItem("gameArchiveTheme") || "{}");
            currentTheme.headerImage = newHeaderUrl;
            localStorage.setItem("gameArchiveTheme", JSON.stringify(currentTheme));
            applyTheme(currentTheme);
          }
        }, HEADER_ROTATION_INTERVAL);
        
      } catch (e) {
        console.error("Header rotation error:", e);
      }
    }, remainingTime);
    
  } catch (e) {
    console.error("Failed to apply random header:", e);
  }
}

// -----------------------------------------------------------
// Initialize extra features on load
// -----------------------------------------------------------
function initExtraFeatures() {
  loadTitleCollapseState();
  loadConsoleListState();
  loadCustomTitle();
  applyRandomHeaderOnLoad();
}
