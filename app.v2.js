// -------------------------------------------------------------
// Backend base URL (dynamic based on current hostname)
// -------------------------------------------------------------
const API_HOST = window.location.hostname + ":9000";
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

// Collection state
let collections = [];
let currentCollectionId = null;
let currentCollectionGames = [];

// Series state
let seriesList = [];
let currentSeriesId = null;
let currentSeriesGames = [];
// (Series state managed locally within functions)

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
  
  const screenshotUrls = currentLightboxScreenshots.map(s => s.url || s);
  const cleanImageSrc = imageSrc.split('?t=')[0];
  
  currentLightboxIndex = screenshotUrls.findIndex(url => {
    const cleanUrl = url.split('?t=')[0];
    return cleanUrl === cleanImageSrc || cleanUrl.endsWith(cleanImageSrc.split('/').pop());
  });
  
  if (currentLightboxIndex === -1) {
    currentLightboxIndex = 0;
  }
  
  setupLightboxImage(img, imageSrc);
  lightbox.classList.add("active");
  updateLightboxCounter();
}

function closeLightbox() {
  const lightbox = document.getElementById("screenshot-lightbox");
  lightbox.classList.remove("active");
  resetDrag();
  resetZoom();
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
  const screenshotUrl = screenshot.url || screenshot;
  setupLightboxImage(img, toAbsoluteUrl(screenshotUrl) + "?t=" + Date.now());
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
  
  setupLightboxImage(img, imageSrc);
  lightbox.classList.add("active");
  
  document.getElementById("lightbox-current").textContent = "1";
  document.getElementById("lightbox-total").textContent = "1";
}

// -----------------------------------------------------------
// Lightbox drag-to-pan
// -----------------------------------------------------------

let isDragging = false;
let wasDragged = false;
let dragStartX = 0;
let dragStartY = 0;
let dragOffsetX = 0;
let dragOffsetY = 0;
let isZoomed = false;
let isTouchDrag = false;

function canDrag(img) {
  if (!img || !img.complete || img.naturalWidth === 0) return false;
  return img.offsetWidth > window.innerWidth || img.offsetHeight > window.innerHeight;
}

function clampDrag(img, dx, dy) {
  const vw = window.innerWidth, vh = window.innerHeight;
  const iw = img.offsetWidth, ih = img.offsetHeight;
  return {
    x: Math.max(Math.min(0, vw - iw), Math.min(Math.max(0, vw - iw), dx)),
    y: Math.max(Math.min(0, vh - ih), Math.min(Math.max(0, vh - ih), dy))
  };
}

function centerImage(img) {
  if (!img.complete || img.naturalWidth === 0) return;
  const c = clampDrag(img, (window.innerWidth - img.offsetWidth) / 2, (window.innerHeight - img.offsetHeight) / 2);
  dragOffsetX = c.x;
  dragOffsetY = c.y;
  img.style.transform = `translate(${c.x}px, ${c.y}px)`;
}

function resetDrag() {
  isDragging = false;
  wasDragged = false;
  dragOffsetX = 0;
  dragOffsetY = 0;
  const lightbox = document.getElementById("screenshot-lightbox");
  if (lightbox) lightbox.classList.remove("dragging");
}

function resetZoom() {
  isZoomed = false;
  const img = document.getElementById("lightbox-img");
  if (img) {
    img.classList.remove("zoomed");
    img.style.removeProperty("height");
    img.style.removeProperty("width");
  }
}

function toggleFit() {
  const img = document.getElementById("lightbox-img");
  if (!img.complete || img.naturalWidth === 0) return;

  if (isZoomed) {
    isZoomed = false;
    img.classList.remove("zoomed");
    img.style.removeProperty("height");
    img.style.removeProperty("width");
    img.style.transform = "";
    isDragging = false;
    wasDragged = false;
    centerImage(img);
  } else {
    isZoomed = true;
    img.classList.add("zoomed");
    const vw = window.innerWidth, vh = window.innerHeight;
    const scale = Math.min(vw / img.naturalWidth, vh / img.naturalHeight);
    const fitW = img.naturalWidth * scale;
    const fitH = img.naturalHeight * scale;
    img.style.height = fitH + "px";
    img.style.width = fitW + "px";
    const dx = (vw - fitW) / 2;
    const dy = (vh - fitH) / 2;
    img.style.transform = `translate(${dx}px, ${dy}px)`;
    dragOffsetX = dx;
    dragOffsetY = dy;
    isDragging = false;
    wasDragged = false;
  }
}

function setupLightboxImage(img, src) {
  resetDrag();
  resetZoom();
  img.style.transform = "";
  img.src = src;
  const onLoad = () => {
    centerImage(img);
    img.removeEventListener("load", onLoad);
  };
  if (img.complete) {
    centerImage(img);
  } else {
    img.addEventListener("load", onLoad);
  }
}

function onDragStart(e) {
  if (e.button !== 0) return;
  const img = document.getElementById("lightbox-img");
  if (!canDrag(img)) return;
  isDragging = true;
  isTouchDrag = false;
  wasDragged = false;
  dragStartX = e.clientX - dragOffsetX;
  dragStartY = e.clientY - dragOffsetY;
  document.getElementById("screenshot-lightbox").classList.add("dragging");
  e.preventDefault();
}

function onDragMove(e) {
  if (!isDragging) return;
  wasDragged = true;
  const img = document.getElementById("lightbox-img");
  const dx = e.clientX - dragStartX;
  const dy = e.clientY - dragStartY;
  const c = clampDrag(img, dx, dy);
  dragOffsetX = c.x;
  dragOffsetY = c.y;
  img.style.transform = `translate(${c.x}px, ${c.y}px)`;
}

function onDragEnd() {
  if (!isDragging) return;
  const tapped = isTouchDrag && !wasDragged;
  isDragging = false;
  isTouchDrag = false;
  document.getElementById("screenshot-lightbox").classList.remove("dragging");
  if (tapped) toggleFit();
}

function onTouchStart(e) {
  if (e.touches.length !== 1) return;
  const img = document.getElementById("lightbox-img");
  if (!canDrag(img)) return;
  isDragging = true;
  isTouchDrag = true;
  wasDragged = false;
  dragStartX = e.touches[0].clientX - dragOffsetX;
  dragStartY = e.touches[0].clientY - dragOffsetY;
  document.getElementById("screenshot-lightbox").classList.add("dragging");
  e.preventDefault();
}

function onTouchMove(e) {
  if (!isDragging || e.touches.length !== 1) return;
  wasDragged = true;
  const img = document.getElementById("lightbox-img");
  const dx = e.touches[0].clientX - dragStartX;
  const dy = e.touches[0].clientY - dragStartY;
  const c = clampDrag(img, dx, dy);
  dragOffsetX = c.x;
  dragOffsetY = c.y;
  img.style.transform = `translate(${c.x}px, ${c.y}px)`;
  e.preventDefault();
}

function initLightboxDrag() {
  const img = document.getElementById("lightbox-img");
  
  img.addEventListener("mousedown", onDragStart);
  document.addEventListener("mousemove", onDragMove);
  document.addEventListener("mouseup", onDragEnd);
  
  img.addEventListener("touchstart", onTouchStart, { passive: false });
  document.addEventListener("touchmove", onTouchMove, { passive: false });
  document.addEventListener("touchend", onDragEnd, { passive: false });
  
  img.addEventListener("click", (e) => {
    if (wasDragged) return;
    toggleFit();
  });
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
  document.getElementById("edit-game-year").value = game.release_year || "";
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
    document.getElementById("edit-status-printed").checked = status.is_printed;
    document.getElementById("edit-completed-date").value = status.completed_date_note || "";
    document.getElementById("edit-game-notes").value = status.notes || "";
    
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
    document.getElementById("edit-status-printed").checked = false;
    document.getElementById("edit-completed-date").value = "";
    document.getElementById("edit-game-notes").value = "";
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
  const yearVal = document.getElementById("edit-game-year").value.trim();
  const release_year = yearVal ? parseInt(yearVal) : null;
  const description = document.getElementById("edit-game-description").value.trim();

  if (!gameId || !title) {
    showToast("Title is required", "warning");
    return;
  }

  try {
    const result = await apiCall(`/games/${gameId}/update`, {
      method: "POST",
      body: JSON.stringify({ title, genre, description, release_year }),
    });

    // Save status
    const completedNoteValue = document.getElementById("edit-completed-date").value.trim();
    const notesValue = document.getElementById("edit-game-notes").value.trim();
    const statusData = {
      is_favorite: document.getElementById("edit-status-favorite").checked,
      has_plan_to_play: document.getElementById("edit-status-plan-to-play").checked,
      is_playing: document.getElementById("edit-status-playing").checked,
      is_completed: document.getElementById("edit-status-completed").checked,
      completed_date_note: completedNoteValue || "",
      is_dropped: document.getElementById("edit-status-dropped").checked,
      is_on_hold: document.getElementById("edit-status-on-hold").checked,
      is_printed: document.getElementById("edit-status-printed").checked,
      notes: notesValue || "",
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

// -----------------------------------------------------------
// Genre Edit Mode
// -----------------------------------------------------------

let genreEditMode = false;
let editingGroupId = null;

let genreOrganization = {
  highlighted: [],
  groups: [],
  collapsedCount: 5,
  expandedChars: {}
};

function getGenreOrgKey() {
  return `genre_organization_${currentConsoleId || 'global'}`;
}

function loadGenreOrganization() {
  try {
    const saved = localStorage.getItem(getGenreOrgKey());
    if (saved) {
      genreOrganization = JSON.parse(saved);
    } else {
      genreOrganization = {
        highlighted: [],
        groups: [],
        collapsedCount: 5,
        expandedChars: {}
      };
    }
  } catch (e) {
    genreOrganization = {
      highlighted: [],
      groups: [],
      collapsedCount: 5,
      expandedChars: {}
    };
  }
}

function saveGenreOrganization() {
  try {
    localStorage.setItem(getGenreOrgKey(), JSON.stringify(genreOrganization));
  } catch (e) {
    console.error('Failed to save genre organization:', e);
  }
}

function showGenreEditButton() {
  const editBtn = document.getElementById('genre-edit-btn');
  if (currentConsoleId && genres && genres.length > 0) {
    editBtn.classList.remove('hidden');
  } else {
    editBtn.classList.add('hidden');
  }
}

function toggleGenreEditMode() {
  genreEditMode = !genreEditMode;
  if (genreEditMode) {
    loadGenreOrganization();
    renderGenreEditPanel();
    toggleModal('#modal-genre-edit', true);
  } else {
    toggleModal('#modal-genre-edit', false);
    renderGenreFilter();
  }
}

function getFirstChar(genre) {
  const first = genre.charAt(0).toUpperCase();
  return /[A-Z]/.test(first) ? first : '#';
}

function groupGenresByFirstChar(genreList) {
  const groups = {};
  genreList.forEach(genre => {
    const char = getFirstChar(genre);
    if (!groups[char]) {
      groups[char] = [];
    }
    groups[char].push(genre);
  });
  
  Object.keys(groups).forEach(char => {
    groups[char].sort((a, b) => a.localeCompare(b));
  });
  
  return groups;
}

function renderGenreFilter() {
  const section = document.getElementById("genre-filter-section");
  const genreList = document.getElementById("genre-list");
  
  if (genres.length === 0) {
    section.style.display = "none";
    showGenreEditButton();
    return;
  }
  
  section.style.display = "block";
  showGenreEditButton();
  
  genreList.innerHTML = "";
  
  loadGenreOrganization();
  
  const allGenres = [...genres].sort((a, b) => a.localeCompare(b));
  const groupedGenres = groupGenresByFirstChar(allGenres);
  
  const chars = Object.keys(groupedGenres).sort((a, b) => {
    if (a === '#') return 1;
    if (b === '#') return -1;
    return a.localeCompare(b);
  });
  
  const groupedGenreNames = new Set();
  genreOrganization.groups.forEach(g => g.genres.forEach(ng => groupedGenreNames.add(ng)));
  
  let groupIndex = 0;
  const totalGroups = genreOrganization.groups.length;
  
  function renderGroupSection(group) {
    const groupItem = document.createElement("li");
    groupItem.className = "genre-group-item";
    
    const isExpanded = genreOrganization.expandedChars[`group_${group.id}`] !== false;
    
    const header = document.createElement("div");
    header.className = `genre-group-header ${isExpanded ? 'expanded' : ''}`;
    header.innerHTML = `
      <span class="expand-icon">▶</span>
      <span>${group.name}</span>
      <span class="group-count">${group.genres.length}</span>
    `;
    header.onclick = () => toggleGroupExpansion(group.id);
    
    const items = document.createElement("div");
    items.className = `genre-group-items ${isExpanded ? '' : 'collapsed'}`;
    
    group.genres.forEach(genre => {
      const li = document.createElement("li");
      li.className = genre === activeGenreFilter ? "active" : "";
      li.textContent = genre;
      li.addEventListener("click", () => applyGenreFilter(genre));
      items.appendChild(li);
    });
    
    groupItem.appendChild(header);
    groupItem.appendChild(items);
    return groupItem;
  }
  
  if (genreOrganization.groups.length > 0) {
    genreOrganization.groups.forEach(group => {
      genreList.appendChild(renderGroupSection(group));
    });
  }
  
  chars.forEach(char => {
    const charGenres = groupedGenres[char];
    const isExpanded = genreOrganization.expandedChars[char] === true;
    const collapsedCount = genreOrganization.collapsedCount;
    
    const highlightedInChar = charGenres.filter(g => genreOrganization.highlighted.includes(g));
    const regularInChar = charGenres.filter(g => !genreOrganization.highlighted.includes(g));
    
    let displayGenres;
    if (isExpanded) {
      displayGenres = charGenres;
    } else {
      const combined = [...highlightedInChar, ...regularInChar];
      displayGenres = combined.slice(0, collapsedCount);
    }
    
    const groupCharItem = document.createElement("li");
    groupCharItem.className = "genre-char-group";
    
    const header = document.createElement("div");
    header.className = `genre-char-header ${isExpanded ? 'expanded' : ''}`;
    header.innerHTML = `
      <span class="expand-icon">▶</span>
      <span>${char}</span>
      <span class="char-count">${charGenres.length}</span>
    `;
    header.onclick = () => toggleCharExpansion(char);
    
    const items = document.createElement("div");
    items.className = `genre-char-items ${isExpanded ? '' : 'collapsed'}`;
    
    displayGenres.forEach(genre => {
      if (!groupedGenreNames.has(genre)) {
        const li = document.createElement("li");
        li.className = genre === activeGenreFilter ? "active" : "";
        li.classList.toggle("highlighted", genreOrganization.highlighted.includes(genre));
        li.textContent = genre;
        li.addEventListener("click", () => applyGenreFilter(genre));
        items.appendChild(li);
      }
    });
    
    if (items.children.length > 0 || !isExpanded) {
      groupCharItem.appendChild(header);
      groupCharItem.appendChild(items);
      genreList.appendChild(groupCharItem);
    }
  });
}

function toggleCharExpansion(char) {
  loadGenreOrganization();
  genreOrganization.expandedChars[char] = !genreOrganization.expandedChars[char];
  saveGenreOrganization();
  renderGenreFilter();
}

function toggleGroupExpansion(groupId) {
  loadGenreOrganization();
  genreOrganization.expandedChars[`group_${groupId}`] = !genreOrganization.expandedChars[`group_${groupId}`];
  saveGenreOrganization();
  renderGenreFilter();
}

function renderGenreEditPanel() {
  loadGenreOrganization();
  
  document.getElementById('genre-collapsed-count').value = genreOrganization.collapsedCount;
  document.getElementById('genre-collapsed-count').onchange = function() {
    const val = parseInt(this.value) || 5;
    genreOrganization.collapsedCount = Math.max(1, Math.min(10, val));
    saveGenreOrganization();
  };
  
  const highlightList = document.getElementById('genre-highlight-list');
  highlightList.innerHTML = '';
  
  const allGenres = [...genres].sort((a, b) => a.localeCompare(b));
  const groupedGenreNames = new Set();
  genreOrganization.groups.forEach(g => g.genres.forEach(ng => groupedGenreNames.add(ng)));
  
  allGenres.forEach(genre => {
    if (!groupedGenreNames.has(genre)) {
      const span = document.createElement('span');
      span.className = `genre-checkbox ${genreOrganization.highlighted.includes(genre) ? 'checked' : ''}`;
      span.textContent = genre;
      span.onclick = () => {
        toggleGenreHighlight(genre);
        span.classList.toggle('checked');
      };
      highlightList.appendChild(span);
    }
  });
  
  renderGroupsList();
  document.getElementById('genre-group-panel').classList.add('hidden');
}

function toggleGenreHighlight(genre) {
  loadGenreOrganization();
  const idx = genreOrganization.highlighted.indexOf(genre);
  if (idx > -1) {
    genreOrganization.highlighted.splice(idx, 1);
  } else {
    genreOrganization.highlighted.push(genre);
  }
  saveGenreOrganization();
}

function renderGroupsList() {
  const groupsList = document.getElementById('genre-groups-list');
  groupsList.innerHTML = '';
  
  genreOrganization.groups.forEach(group => {
    const item = document.createElement('div');
    item.className = 'genre-group-edit-item';
    item.innerHTML = `
      <span class="group-name">${group.name} (${group.genres.length})</span>
      <div class="group-actions">
        <button onclick="editGroup('${group.id}')" title="Edit">✏️</button>
        <button onclick="deleteGroup('${group.id}')" title="Delete">🗑️</button>
      </div>
    `;
    groupsList.appendChild(item);
  });
}

function openGroupPanel(groupId = null) {
  editingGroupId = groupId;
  const panel = document.getElementById('genre-group-panel');
  const title = document.getElementById('group-panel-title');
  const nameInput = document.getElementById('group-name-input');
  const genresList = document.getElementById('group-genres-list');
  
  panel.classList.remove('hidden');
  
  if (groupId) {
    const group = genreOrganization.groups.find(g => g.id === groupId);
    title.textContent = 'Edit Group';
    nameInput.value = group.name;
  } else {
    title.textContent = 'Create Group';
    nameInput.value = '';
  }
  
  const allGenres = [...genres].sort((a, b) => a.localeCompare(b));
  const existingGroupGenres = groupId 
    ? (genreOrganization.groups.find(g => g.id === groupId)?.genres || [])
    : [];
  
  genresList.innerHTML = '';
  allGenres.forEach(genre => {
    const span = document.createElement('span');
    span.className = `genre-checkbox ${existingGroupGenres.includes(genre) ? 'checked' : ''}`;
    span.textContent = genre;
    span.onclick = () => {
      span.classList.toggle('checked');
    };
    genresList.appendChild(span);
  });
}

function cancelGroupEdit() {
  document.getElementById('genre-group-panel').classList.add('hidden');
  editingGroupId = null;
}

function saveGroup() {
  const nameInput = document.getElementById('group-name-input');
  const name = nameInput.value.trim();
  
  if (!name) {
    alert('Please enter a group name');
    return;
  }
  
  const selectedGenres = [];
  document.querySelectorAll('#group-genres-list .genre-checkbox.checked').forEach(span => {
    selectedGenres.push(span.textContent);
  });
  
  loadGenreOrganization();
  
  if (editingGroupId) {
    const group = genreOrganization.groups.find(g => g.id === editingGroupId);
    if (group) {
      group.name = name;
      group.genres = selectedGenres;
    }
  } else {
    const newGroup = {
      id: 'group_' + Date.now(),
      name: name,
      genres: selectedGenres
    };
    genreOrganization.groups.push(newGroup);
  }
  
  saveGenreOrganization();
  renderGenreEditPanel();
}

function editGroup(groupId) {
  openGroupPanel(groupId);
}

function deleteGroup(groupId) {
  if (!confirm('Delete this group? The genres will return to the general list.')) {
    return;
  }
  
  loadGenreOrganization();
  genreOrganization.groups = genreOrganization.groups.filter(g => g.id !== groupId);
  saveGenreOrganization();
  renderGenreEditPanel();
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
// Collections
// -----------------------------------------------------------

async function loadCollections() {
  try {
    collections = await apiCall("/collections");
  } catch (e) {
    collections = [];
  }
  renderCollections();
}

function renderCollections() {
  const list = $("#collections-list");
  const createBtn = $("#btn-create-collection");
  if (!list) return;

  list.innerHTML = "";

  if (collections.length === 0) {
    list.style.display = "none";
    if (createBtn) createBtn.style.display = "block";
    return;
  }

  if (createBtn) createBtn.style.display = "block";

  collections.forEach((c) => {
    const li = document.createElement("li");
    li.className = c.id === currentCollectionId ? "collection-item active" : "collection-item";
    li.dataset.id = c.id;
    li.innerHTML = `
      <span class="collection-name">${c.name}</span>
      <span class="collection-count">${c.game_count}</span>
      <button class="delete-collection-btn" onclick="deleteCollection(${c.id}, event)" title="Delete collection">🗑️</button>
    `;
    li.addEventListener("click", async (e) => {
      if (!e.target.classList.contains("delete-collection-btn")) {
        try {
          await selectCollection(c.id);
        } catch (err) {
          console.error("selectCollection failed:", err);
        }
      }
    });
    list.appendChild(li);
  });

  list.style.display = "block";
}

function toggleCollectionsList() {
  const list = $("#collections-list");
  const icon = $("#collections-toggle-icon");
  const createBtn = $("#btn-create-collection");
  if (!list) return;

  const collapsed = list.style.display === "none" || list.style.display === "";
  list.style.display = collapsed ? "block" : "none";
  icon.textContent = collapsed ? "▼" : "▶";
  if (createBtn) createBtn.style.display = collapsed ? "block" : "none";
  localStorage.setItem("collectionsListCollapsed", collapsed ? "false" : "true");
}

function loadCollectionsListState() {
  const collapsed = localStorage.getItem("collectionsListCollapsed") !== "false";
  const list = $("#collections-list");
  const icon = $("#collections-toggle-icon");
  const createBtn = $("#btn-create-collection");
  if (!list) return;

  if (collapsed) {
    list.style.display = "none";
    icon.textContent = "▶";
    if (createBtn) createBtn.style.display = "none";
  } else {
    list.style.display = "block";
    icon.textContent = "▼";
    if (createBtn) createBtn.style.display = "block";
  }
}

function openCreateCollectionModal() {
  document.getElementById("create-collection-name").value = "";
  document.getElementById("create-collection-desc").value = "";
  toggleModal("#modal-create-collection", true);
}

function closeCreateCollectionModal() {
  toggleModal("#modal-create-collection", false);
}

async function confirmCreateCollection() {
  const name = document.getElementById("create-collection-name").value.trim();
  const description = document.getElementById("create-collection-desc").value.trim();

  if (!name) {
    showToast("Collection name is required", "warning");
    return;
  }

  try {
    const collection = await apiCall("/collections", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    });
    collections.push(collection);
    renderCollections();
    toggleModal("#modal-create-collection", false);
    showToast(`Collection '${name}' created!`, "success");
  } catch (e) {
    // Error already shown
  }
}

async function deleteCollection(id, event) {
  if (event) event.stopPropagation();

  const c = collections.find((x) => x.id === id);
  if (!c) return;

  if (!confirm(`Delete collection '${c.name}'? The games will not be deleted.`)) return;

  try {
    await apiCall(`/collections/${id}`, { method: "DELETE" });
    collections = collections.filter((x) => x.id !== id);

    if (currentCollectionId === id) {
      currentCollectionId = null;
      currentCollectionGames = [];
      renderHomepage();
    }

    renderCollections();
    loadStats();
    showToast(`Collection '${c.name}' deleted`, "success");
  } catch (e) {
    // Error already shown
  }
}

async function selectCollection(id) {
  try {
    currentCollectionId = id;
    currentConsoleId = null;
    activeFilter = null;
    activeGenreFilter = null;
    activeStatusFilter = null;
    statusFilteredGames = [];

    showConsoleView();
    savePageState();
    updateConsoleSummary();
    renderCollections();
    renderConsoles();

    try {
      const games = await apiCall(`/collections/${id}/games`);
      currentCollectionGames = games;
    } catch (e) {
      currentCollectionGames = [];
    }

    renderCollectionGames();
  } catch (e) {
    console.error("selectCollection error:", e);
  }
}

function renderCollectionGames() {
  const container = $("#game-list");
  const titleEl = $("#console-name");
  if (!container) return;

  const collection = collections.find((c) => c.id === currentCollectionId);
  titleEl.textContent = collection ? `📂 ${collection.name}` : "Collection";

  // Hide metadata actions for collection view
  const alpha = $("#alpha-index");
  const meta = $("#metadata-actions");
  if (alpha) alpha.style.display = "none";
  if (meta) meta.style.display = "none";

  const rescanBtn = $("#btn-rescan-console");
  const addGameBtn = $("#btn-add-game");
  if (rescanBtn) rescanBtn.style.display = "none";
  if (addGameBtn) addGameBtn.style.display = "none";

  container.innerHTML = "";

  if (currentCollectionGames.length === 0) {
    container.innerHTML = '<p>No games in this collection.</p>';
    return;
  }

  currentCollectionGames.forEach((g) => {
    const card = document.createElement("article");
    card.className = "game-card";
    card.dataset.id = g.game_id;

    const cover = g.cover_url
      ? `<img src="${toAbsoluteUrl(g.cover_url)}${g.cover_url.includes('?') ? '&' : '?'}t=${Date.now()}" alt="${g.title} cover" />`
      : `<div class="no-cover">No cover</div>`;

    card.innerHTML = `
      <div class="game-cover" style="position: relative;">
        ${cover}
        <button class="game-card-fetch-btn" onclick="fetchSingleGameMetadata(${g.game_id}, event)" title="Fetch metadata">🔄</button>
      </div>
      <div class="game-title">${g.title}</div>
      <div class="game-meta">
        <span class="game-console-badge">${g.console_name}</span>
        ${g.genre || "Unknown genre"}
      </div>
    `;

    card.addEventListener("click", (event) => {
      if (event.target.closest('.game-card-fetch-btn')) return;
      openGameDetail(g.game_id);
    });

    container.appendChild(card);
  });
}

async function addGameToCollection(collectionId, gameId) {
  await apiCall(`/collections/${collectionId}/games/${gameId}`, { method: "POST" });
}

async function removeGameFromCollection(collectionId, gameId) {
  await apiCall(`/collections/${collectionId}/games/${gameId}`, { method: "DELETE" });
}

async function toggleGameCollection(collectionId, gameId, add) {
  try {
    if (add) {
      await addGameToCollection(collectionId, gameId);
      showToast("Game added to collection", "success");
    } else {
      await removeGameFromCollection(collectionId, gameId);
      showToast("Game removed from collection", "success");
    }
    await loadCollections();
    if (currentCollectionId) await selectCollection(currentCollectionId);
    renderGameDetailCollections(currentGameDetail);
  } catch (e) {
    // apiCall already shows error toast
  }
}

// -----------------------------------------------------------
// Series
// -----------------------------------------------------------

async function loadSeries() {
  try {
    seriesList = await apiCall("/series");
  } catch (e) {
    seriesList = [];
  }
}

function renderSeries() {
  // Series sidebar list has been replaced with buttons — no list to render
}

// --- Series Creation (Full Page) ---

let seriesCreateSelected = [];

function openSeriesCreateView() {
  currentView = 'series-create';
  seriesCreateSelected = [];

  $("#homepage").classList.add("hidden");
  $("#search-results").classList.add("hidden");
  $(".console-summary").style.display = "none";
  $(".alpha-index").style.display = "none";
  $(".metadata-actions").style.display = "none";
  $("#game-list").style.display = "none";
  $("#series-list-view").classList.add("hidden");
  $("#series-detail-view").classList.add("hidden");
  $("#series-create-view").classList.remove("hidden");

  $("#series-create-name").value = "";
  $("#series-create-genre").value = "";
  $("#series-create-results").innerHTML = '<p style="color: var(--text-muted); font-size: 0.85rem;">Type a series name to search your archive for matching games:</p>';
  const selAllBtn = $("#btn-select-all-create");
  const deselAllBtn = $("#btn-deselect-all-create");
  if (selAllBtn) selAllBtn.classList.add("hidden");
  if (deselAllBtn) deselAllBtn.classList.add("hidden");
  updateSeriesCreateCount();
}

function cancelSeriesCreate() {
  $("#series-create-view").classList.add("hidden");
  currentView = 'homepage';
  renderHomepage();
}

let seriesCreateSearchTimeout = null;

function onSeriesCreateNameInput() {
  const query = $("#series-create-name").value.trim();
  const container = $("#series-create-results");
  const selAllBtn = $("#btn-select-all-create");
  const deselAllBtn = $("#btn-deselect-all-create");

  if (seriesCreateSearchTimeout) clearTimeout(seriesCreateSearchTimeout);

  if (query.length < 2) {
    container.innerHTML = '<p style="color: var(--text-muted); font-size: 0.85rem;">Type at least 2 characters to search...</p>';
    if (selAllBtn) selAllBtn.classList.add("hidden");
    if (deselAllBtn) deselAllBtn.classList.add("hidden");
    return;
  }

  seriesCreateSearchTimeout = setTimeout(async () => {
    try {
      const results = await apiCall(`/games/search?q=${encodeURIComponent(query)}`);
      if (!results || results.length === 0) {
        container.innerHTML = '<p style="color: var(--text-muted); font-size: 0.85rem;">No matching games found in your archive.</p>';
        if (selAllBtn) selAllBtn.classList.add("hidden");
        if (deselAllBtn) deselAllBtn.classList.add("hidden");
        return;
      }

      container.innerHTML = "";
      if (selAllBtn) selAllBtn.classList.remove("hidden");
      if (deselAllBtn) deselAllBtn.classList.remove("hidden");

      results.forEach((g) => {
        const card = document.createElement("article");
        card.className = "game-card selectable";
        card.dataset.id = g.id;

        const cover = g.cover_url
          ? `<img src="${toAbsoluteUrl(g.cover_url)}${g.cover_url.includes('?') ? '&' : '?'}t=${Date.now()}" alt="${g.title} cover" />`
          : `<div class="no-cover">No cover</div>`;

        card.innerHTML = `
          <div class="game-cover">${cover}</div>
          <div class="game-title">${g.title}</div>
          <div class="game-meta">
            <span class="game-console-badge">${g.console_name}</span>
          </div>
        `;

        card.addEventListener("click", () => {
          toggleSeriesCreateSelection(g.id, card);
        });

        container.appendChild(card);
      });
    } catch (e) {
      container.innerHTML = '<p style="color: #ff6b6b; font-size: 0.85rem;">Search failed</p>';
    }
  }, 300);
}

function toggleSeriesCreateSelection(gameId, cardEl) {
  const idx = seriesCreateSelected.indexOf(gameId);
  if (idx >= 0) {
    seriesCreateSelected.splice(idx, 1);
    cardEl.classList.remove("selected");
  } else {
    seriesCreateSelected.push(gameId);
    cardEl.classList.add("selected");
  }
  updateSeriesCreateCount();
}

function selectAllCreateResults() {
  const cards = document.querySelectorAll("#series-create-results .game-card.selectable");
  seriesCreateSelected = [];
  cards.forEach((card) => {
    const id = parseInt(card.dataset.id);
    if (!seriesCreateSelected.includes(id)) {
      seriesCreateSelected.push(id);
    }
    card.classList.add("selected");
  });
  updateSeriesCreateCount();
}

function deselectAllCreateResults() {
  seriesCreateSelected = [];
  document.querySelectorAll("#series-create-results .game-card.selectable.selected").forEach((card) => {
    card.classList.remove("selected");
  });
  updateSeriesCreateCount();
}

function updateSeriesCreateCount() {
  const countEl = $("#series-create-count");
  const btnEl = $("#btn-series-create-confirm");
  if (countEl) countEl.textContent = seriesCreateSelected.length;
  if (btnEl) btnEl.disabled = seriesCreateSelected.length === 0;
}

async function confirmSeriesCreate() {
  const name = $("#series-create-name").value.trim();
  const genre = $("#series-create-genre").value.trim();

  if (!name) {
    showToast("Series name is required", "warning");
    return;
  }
  if (seriesCreateSelected.length === 0) {
    showToast("Select at least one game", "warning");
    return;
  }

  try {
    const series = await apiCall("/series", {
      method: "POST",
      body: JSON.stringify({ name, genre }),
    });

    const gamesPayload = seriesCreateSelected.map((gameId) => ({
      game_id: gameId,
      is_missing: false,
    }));

    const result = await apiCall(`/series/${series.id}/games/batch`, {
      method: "POST",
      body: JSON.stringify({ games: gamesPayload }),
    });

    seriesList.push({ ...series, game_count: result.added });
    renderSeries();
    showToast(`Series '${name}' created with ${result.added} games!`, "success");

    await selectSeries(series.id);
  } catch (e) {
    try {
      await loadSeries();
      const existing = seriesList.find((s) => s.name === name);
      if (existing) {
        showToast(`Series '${name}' already exists (${existing.game_count} games). Loading it.`, "info");
        await selectSeries(existing.id);
      }
    } catch (e2) {
      // Ignore
    }
  }
}

// --- Series Detail View ---

async function selectSeries(id) {
  try {
    currentSeriesId = id;
    currentConsoleId = null;
    currentCollectionId = null;
    activeFilter = null;
    activeGenreFilter = null;
    activeStatusFilter = null;
    statusFilteredGames = [];
    currentPage = 1;

    currentView = 'series';
    savePageState();

    $("#homepage").classList.add("hidden");
    $("#search-results").classList.add("hidden");
    $("#series-create-view").classList.add("hidden");
    $("#series-list-view").classList.add("hidden");
    $(".console-summary").style.display = "none";
    $(".alpha-index").style.display = "none";
    $(".metadata-actions").style.display = "none";
    $("#game-list").style.display = "none";
    $("#series-detail-view").classList.remove("hidden");

    renderSeries();
    renderCollections();
    renderConsoles();

    try {
      const games = await apiCall(`/series/${id}/games`);
      currentSeriesGames = games;
    } catch (e) {
      currentSeriesGames = [];
    }

    dismissMissingGames();
    renderSeriesDetail();
  } catch (e) {
    console.error("selectSeries error:", e);
  }
}

function renderSeriesDetail() {
  const series = seriesList.find((s) => s.id === currentSeriesId);
  if (!series) return;

  $("#series-detail-title").textContent = `📚 ${series.name}`;
  $("#series-detail-count").textContent = `${currentSeriesGames.length} games`;

  const container = $("#series-detail-games");
  container.innerHTML = "";

  if (currentSeriesGames.length === 0) {
    container.innerHTML = '<p>No games in this series. Click "Search Internet for Missing Titles" to populate it.</p>';
    return;
  }

  currentSeriesGames.forEach((g, idx) => {
    const card = document.createElement("article");
    card.className = g.is_missing ? "game-card series-missing" : "game-card";

    const cover = g.cover_url
      ? `<img src="${toAbsoluteUrl(g.cover_url)}${g.cover_url.includes('?') ? '&' : '?'}t=${Date.now()}" alt="${g.title} cover" />`
      : `<div class="no-cover">No cover</div>`;

    const missingBadge = g.is_missing ? '<span class="series-missing-badge">MISSING</span>' : '';
    const addBtn = g.is_missing ? `<button class="series-add-btn" onclick="addMissingToArchive(${g.id}, event)" title="Add to archive">＋</button>` : '';

    card.innerHTML = `
      <div class="game-cover" style="position: relative;">
        ${cover}
        ${missingBadge}
        ${addBtn}
        <span class="series-position-badge">${g.position}</span>
      </div>
      <div class="game-title">${g.title}</div>
      <div class="game-meta">
        ${(g.console_name || g.platform) ? `<span class="game-console-badge">${g.console_name || g.platform}</span>` : ''}
        <span class="series-year-edit" onclick="editSeriesYear(${g.id}, this)" title="Click to edit year">${g.release_year || '—'}</span>
        <span class="series-card-actions">
          <button class="series-reorder-btn" onclick="moveSeriesGame(${g.id}, 'up', event)" title="Move up" ${idx === 0 ? 'disabled' : ''}>▲</button>
          <button class="series-reorder-btn" onclick="moveSeriesGame(${g.id}, 'down', event)" title="Move down" ${idx === currentSeriesGames.length - 1 ? 'disabled' : ''}>▼</button>
          <button class="series-remove-btn" onclick="removeGameFromSeriesUI(${g.id}, event)" title="Remove from series">✕</button>
        </span>
      </div>
    `;

    card.addEventListener("click", (event) => {
      if (event.target.closest('.series-card-actions')) return;
      if (!g.is_missing && g.game_id) {
        openGameDetail(g.game_id);
      }
    });

    container.appendChild(card);
  });
}

async function addMissingToArchive(entryId, event) {
  event.stopPropagation();
  if (!currentSeriesId) return;

  const game = currentSeriesGames.find((g) => g.id === entryId);
  if (!game) return;

  const btn = event.currentTarget;
  btn.disabled = true;
  btn.textContent = "...";

  try {
    const res = await fetch(`${API}/series/${currentSeriesId}/games/${entryId}/add-to-archive`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      alert(data.detail || "Failed to add game to archive");
      btn.disabled = false;
      btn.textContent = "＋";
      return;
    }

    // Update the local game entry
    game.is_missing = false;
    game.game_id = data.game_id;
    renderSeriesDetail();
  } catch (e) {
    console.error("addMissingToArchive failed:", e);
    btn.disabled = false;
    btn.textContent = "＋";
  }
}

function editSeriesYear(entryId, el) {
  event.stopPropagation();
  const game = currentSeriesGames.find((g) => g.id === entryId);
  if (!game) return;

  const currentVal = game.release_year || "";
  const input = document.createElement("input");
  input.type = "number";
  input.className = "series-year-input";
  input.value = currentVal;
  input.min = "1970";
  input.max = "2030";
  input.placeholder = "Year";

  el.replaceWith(input);
  input.focus();
  input.select();

  async function save() {
    const newVal = input.value.trim();
    const newYear = newVal ? parseInt(newVal) : null;

    if (newYear !== game.release_year) {
      try {
        await apiCall(`/series/${currentSeriesId}/games/${entryId}`, {
          method: "PUT",
          body: JSON.stringify({ release_year: newYear }),
        });
        game.release_year = newYear;
      } catch (e) {
        console.error("Failed to update year:", e);
      }
    }
    renderSeriesDetail();
  }

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); save(); }
    if (e.key === "Escape") { renderSeriesDetail(); }
  });
  input.addEventListener("blur", save);
}

async function moveSeriesGame(entryId, direction, event) {
  if (event) event.stopPropagation();
  if (!currentSeriesId) return;

  const idx = currentSeriesGames.findIndex((g) => g.id === entryId);
  if (idx < 0) return;

  if (direction === "up" && idx > 0) {
    [currentSeriesGames[idx - 1], currentSeriesGames[idx]] = [currentSeriesGames[idx], currentSeriesGames[idx - 1]];
  } else if (direction === "down" && idx < currentSeriesGames.length - 1) {
    [currentSeriesGames[idx], currentSeriesGames[idx + 1]] = [currentSeriesGames[idx + 1], currentSeriesGames[idx]];
  } else {
    return;
  }

  const positions = currentSeriesGames.map((g, i) => ({ id: g.id, position: i + 1 }));

  try {
    await apiCall(`/series/${currentSeriesId}/games/reorder`, {
      method: "PUT",
      body: JSON.stringify({ positions }),
    });
    renderSeriesDetail();
  } catch (e) {
    showToast("Failed to reorder", "error");
  }
}

async function removeGameFromSeriesUI(entryId, event) {
  if (event) event.stopPropagation();
  if (!currentSeriesId) return;

  const game = currentSeriesGames.find((g) => g.id === entryId);
  if (!game) return;
  if (!confirm(`Remove "${game.title}" from the series?`)) return;

  try {
    await apiCall(`/series/${currentSeriesId}/games/${entryId}`, { method: "DELETE" });
    await selectSeries(currentSeriesId);
    await loadSeries();
    showToast("Game removed from series", "success");
  } catch (e) {
    // Error already shown
  }
}

async function deleteSeriesFromDetail() {
  if (!currentSeriesId) return;
  const s = seriesList.find((x) => x.id === currentSeriesId);
  if (!s) return;
  if (!confirm(`Delete series '${s.name}'? This will not delete the games themselves.`)) return;

  try {
    await apiCall(`/series/${currentSeriesId}`, { method: "DELETE" });
    seriesList = seriesList.filter((x) => x.id !== currentSeriesId);
    currentSeriesId = null;
    currentSeriesGames = [];
    renderSeries();
    goToHomepage();
    showToast(`Series '${s.name}' deleted`, "success");
  } catch (e) {
    // Error already shown
  }
}

async function deleteSeries(id, event) {
  if (event) event.stopPropagation();

  const s = seriesList.find((x) => x.id === id);
  if (!s) return;
  if (!confirm(`Delete series '${s.name}'?`)) return;

  try {
    await apiCall(`/series/${id}`, { method: "DELETE" });
    seriesList = seriesList.filter((x) => x.id !== id);

    if (currentSeriesId === id) {
      currentSeriesId = null;
      currentSeriesGames = [];
      goToHomepage();
    }

    renderSeries();
    loadStats();
    showToast(`Series '${s.name}' deleted`, "success");
  } catch (e) {
    // Error already shown
  }
}

// --- Series List View (Main Content) ---

function showSeriesListView() {
  currentView = 'series-list';
  currentConsoleId = null;
  currentCollectionId = null;
  currentSeriesId = null;
  currentSeriesGames = [];
  activeFilter = null;
  activeGenreFilter = null;
  activeStatusFilter = null;
  statusFilteredGames = [];
  currentPage = 1;

  $("#homepage").classList.add("hidden");
  $("#search-results").classList.add("hidden");
  $(".console-summary").style.display = "none";
  $(".alpha-index").style.display = "none";
  $(".metadata-actions").style.display = "none";
  $("#game-list").style.display = "none";
  $("#series-create-view").classList.add("hidden");
  $("#series-detail-view").classList.add("hidden");
  $("#series-list-view").classList.remove("hidden");

  savePageState();
  renderSeriesGrid();
}

function renderSeriesGrid() {
  const container = $("#series-grid");
  if (!container) return;
  container.innerHTML = "";

  if (seriesList.length === 0) {
    container.innerHTML = '<p style="color: var(--text-muted); padding: 20px;">No series yet. Create one to get started!</p>';
    return;
  }

  seriesList.forEach((s) => {
    const card = document.createElement("article");
    card.className = "game-card series-grid-card";

    const coverUrl = s.cover_url ? toAbsoluteUrl(s.cover_url) : "";
    const cover = coverUrl
      ? `<img src="${coverUrl}" alt="${s.name}" />`
      : `<div class="no-cover">📚</div>`;

    card.innerHTML = `
      <div class="game-cover">${cover}</div>
      <div class="game-title">${s.name}</div>
      <div class="game-meta">
        <span class="game-console-badge">${s.game_count} games</span>
        ${s.genre ? `<span class="genre-badge">${s.genre}</span>` : ''}
      </div>
      <button class="series-delete-grid-btn" onclick="deleteSeries(${s.id}, event)" title="Delete series">🗑️</button>
    `;

    card.addEventListener("click", (e) => {
      if (e.target.closest('.series-delete-grid-btn')) return;
      selectSeries(s.id);
    });

    container.appendChild(card);
  });
}

function groupSeriesView(mode) {
  const container = $("#series-grid");
  if (!container) return;
  container.innerHTML = "";

  if (mode === "genre") {
    // Group by genre
    const genreGroups = {};
    seriesList.forEach((s) => {
      const genre = s.genre || "Uncategorized";
      if (!genreGroups[genre]) genreGroups[genre] = [];
      genreGroups[genre].push(s);
    });

    Object.keys(genreGroups).sort().forEach((genre) => {
      const heading = document.createElement("h3");
      heading.className = "series-genre-heading";
      heading.textContent = genre;
      container.appendChild(heading);

      const grid = document.createElement("div");
      grid.className = "game-list";
      genreGroups[genre].forEach((s) => {
        grid.appendChild(createSeriesGridCard(s));
      });
      container.appendChild(grid);
    });
  } else {
    renderSeriesGrid();
  }
}

function createSeriesGridCard(s) {
  const card = document.createElement("article");
  card.className = "game-card series-grid-card";

  const coverUrl = s.cover_url ? toAbsoluteUrl(s.cover_url) : "";
  const cover = coverUrl
    ? `<img src="${coverUrl}" alt="${s.name}" />`
    : `<div class="no-cover">📚</div>`;

  card.innerHTML = `
    <div class="game-cover">${cover}</div>
    <div class="game-title">${s.name}</div>
    <div class="game-meta">
      <span class="game-console-badge">${s.game_count} games</span>
      ${s.genre ? `<span class="genre-badge">${s.genre}</span>` : ''}
    </div>
    <button class="series-delete-grid-btn" onclick="deleteSeries(${s.id}, event)" title="Delete series">🗑️</button>
  `;

  card.addEventListener("click", (e) => {
    if (e.target.closest('.series-delete-grid-btn')) return;
    selectSeries(s.id);
  });

  return card;
}

// --- Game Detail Filters (Sidebar) ---

let detailFilterState = {};
let activeDetailFilters = { decade: null, developer: null, publisher: null };

async function loadDetailFilters() {
  try {
    const filters = await apiCall("/metadata-filters");
    renderDetailFilterList("decade", filters.decades || []);
    renderDetailFilterList("developer", filters.developers || []);
    renderDetailFilterList("publisher", filters.publishers || []);
    // Show the section if there's any data
    const section = $("#detail-filter-section");
    if (section && (filters.decades?.length || filters.developers?.length || filters.publishers?.length)) {
      section.style.display = "block";
    }
  } catch (e) {
    console.warn("Failed to load detail filters:", e);
  }
}

function renderDetailFilterList(type, items) {
  const list = $(`#${type}-filter-list`);
  if (!list) return;
  list.innerHTML = "";
  items.forEach((item) => {
    const li = document.createElement("li");
    li.className = "detail-filter-item";
    li.dataset.value = item.value;
    li.innerHTML = `${item.value} <span class="count">${item.count}</span>`;
    li.addEventListener("click", () => applyDetailFilter(type, item.value));
    list.appendChild(li);
  });
}

function toggleDetailFilter() {
  const content = $("#detail-filter-content");
  const icon = $("#detail-filter-toggle-icon");
  if (!content) return;
  const collapsed = content.style.display === "none";
  content.style.display = collapsed ? "block" : "none";
  icon.textContent = collapsed ? "▼" : "▶";
}

function toggleDetailFilterGroup(type) {
  const list = $(`#${type}-filter-list`);
  const icon = $(`#${type}-toggle-icon`);
  if (!list) return;
  const collapsed = list.style.display === "none";
  list.style.display = collapsed ? "block" : "none";
  icon.textContent = collapsed ? "▼" : "▶";
}

function applyDetailFilter(type, value) {
  // Toggle filter: if already active, deactivate
  if (activeDetailFilters[type] === value) {
    activeDetailFilters[type] = null;
  } else {
    activeDetailFilters[type] = value;
  }

  // Update active state in the UI
  const list = $(`#${type}-filter-list`);
  if (list) {
    list.querySelectorAll(".detail-filter-item").forEach((li) => {
      li.classList.toggle("active", li.dataset.value === activeDetailFilters[type]);
    });
  }

  // Apply filter to current view
  filterGamesByDetail();
}

function filterGamesByDetail() {
  const hasFilter = Object.values(activeDetailFilters).some(v => v !== null);
  if (!hasFilter) {
    // No filters active — restore normal view
    if (currentConsoleId) {
      renderGamesForCurrentConsole();
    } else if (currentView === 'homepage') {
      renderHomepage();
    }
    return;
  }

  // Get all games from current console or all games
  let allGames = [];
  if (currentConsoleId && gamesByConsole[currentConsoleId]) {
    allGames = gamesByConsole[currentConsoleId];
  }

  // Apply filters
  const filtered = allGames.filter((g) => {
    if (activeDetailFilters.decade) {
      if (!g.release_year) return false;
      const decade = `${Math.floor(g.release_year / 10) * 10}s`;
      if (decade !== activeDetailFilters.decade) return false;
    }
    if (activeDetailFilters.developer) {
      if (!g.developer) return false;
      if (!g.developer.split(",").map(d => d.trim()).includes(activeDetailFilters.developer)) return false;
    }
    if (activeDetailFilters.publisher) {
      if (!g.publisher) return false;
      if (!g.publisher.split(",").map(p => p.trim()).includes(activeDetailFilters.publisher)) return false;
    }
    return true;
  });

  // Render filtered games
  const container = $("#game-list");
  container.innerHTML = "";
  if (filtered.length === 0) {
    container.innerHTML = '<p class="no-items">No games match the selected filters</p>';
    return;
  }
  filtered.forEach((g) => {
    container.appendChild(createGameCard(g, ""));
  });
}

// --- Internet Search for Missing Titles ---

let seriesMissingAll = [];
let seriesMissingSelected = new Set();
let seriesSearchAborted = false;

async function searchInternetForMissing() {
  if (!currentSeriesId || currentSeriesGames.length === 0) {
    showToast("No games in series to search from", "warning");
    return;
  }

  seriesSearchAborted = false;
  const searchBtn = document.querySelector('#series-detail-actions button[onclick*="searchInternetForMissing"]');
  if (searchBtn) {
    searchBtn.disabled = true;
    searchBtn.textContent = "🔍 Searching...";
  }

  const existingTitles = new Set(currentSeriesGames.map((g) => g.title.toLowerCase()));
  const confirmedMissing = new Set(currentSeriesGames.filter((g) => g.is_missing).map((g) => g.title.toLowerCase()));

  seriesMissingAll = [];
  seriesMissingSelected = new Set();
  const seenTitles = new Set();
  const seenRawgIds = new Set();

  const progressEl = $("#series-missing-progress");
  const section = $("#series-missing-confirm");
  const gamesContainer = $("#series-detail-games");

  // Move missing section above the games list
  if (section.parentNode !== gamesContainer.parentNode || section.nextElementSibling !== gamesContainer) {
    section.parentNode.insertBefore(section, gamesContainer);
  }

  section.classList.remove("hidden");
  const container = $("#series-missing-games-list");
  container.innerHTML = "";
  updateMissingCount();

  let rawgResultCount = 0;

  // Step 1: RAWG expand for covers
  for (const game of currentSeriesGames) {
    if (seriesSearchAborted) break;
    if (!game.game_id) continue;

    try {
      const data = await apiCall(`/series/expand/${game.game_id}`);
      if (data && data.games) {
        for (const g of data.games) {
          if (seriesSearchAborted) break;
          if (g.rawg_id && seenRawgIds.has(g.rawg_id)) continue;
          if (g.rawg_id) seenRawgIds.add(g.rawg_id);

          const titleLower = g.title.toLowerCase();
          if (existingTitles.has(titleLower) || confirmedMissing.has(titleLower) || seenTitles.has(titleLower)) continue;
          seenTitles.add(titleLower);

          g.source = "rawg";
          seriesMissingAll.push(g);
          rawgResultCount++;
          appendMissingGameCard(g, seriesMissingAll.length - 1);
          updateMissingCount();
        }
      }
    } catch (e) {
      // RAWG expand not available for this game — silently skip
    }
  }

  // Step 2: Wikipedia for additional titles
  if (!seriesSearchAborted) {
    const series = seriesList.find((s) => s.id === currentSeriesId);
    if (series) {
      if (progressEl) {
        progressEl.textContent = rawgResultCount > 0
          ? `Found ${rawgResultCount} titles from RAWG. Searching Wikipedia for more...`
          : `Searching Wikipedia for "${series.name}" titles...`;
        progressEl.classList.remove("hidden");
      }

      try {
        const wikiData = await apiCall(`/series/search-wikipedia/${encodeURIComponent(series.name)}`);
        if (wikiData && wikiData.games) {
          for (const g of wikiData.games) {
            if (seriesSearchAborted) break;
            const titleLower = g.title.toLowerCase();
            if (existingTitles.has(titleLower) || confirmedMissing.has(titleLower) || seenTitles.has(titleLower)) continue;
            seenTitles.add(titleLower);

            seriesMissingAll.push(g);
            appendMissingGameCard(g, seriesMissingAll.length - 1);
            updateMissingCount();
          }
        }
      } catch (e) {
        console.warn("Wikipedia search failed:", e);
      }
    }
  }

  if (progressEl) {
    progressEl.classList.add("hidden");
  }
  if (searchBtn) {
    searchBtn.disabled = false;
    searchBtn.textContent = "🔍 Search Internet for Missing Titles";
  }

  if (seriesMissingAll.length === 0) {
    container.innerHTML = '<p style="color: var(--text-muted); font-size: 0.85rem; padding: 12px;">No missing titles found.</p>';
  }
}

function appendMissingGameCard(g, idx) {
  const container = $("#series-missing-games-list");
  const card = document.createElement("article");
  card.className = "game-card series-missing selectable missing-selectable selected";
  card.dataset.missingIdx = idx;
  seriesMissingSelected.add(idx);

  const cover = g.cover_url
    ? `<img src="${toAbsoluteUrl(g.cover_url)}" alt="${g.title}" />`
    : `<div class="no-cover">No cover</div>`;

  const sourceTag = g.source === "wikipedia" ? '<span class="missing-source-tag">Wikipedia</span>' : '';

  card.innerHTML = `
    <div class="game-cover" style="position: relative;">
      ${cover}
      <span class="series-missing-badge">MISSING</span>
    </div>
    <div class="game-title">${g.title}</div>
    <div class="game-meta">
      ${g.platform ? `<span class="game-console-badge">${g.platform}</span>` : ''}
      ${g.release_year || ''}
      ${sourceTag}
    </div>
  `;

  card.addEventListener("click", () => {
    if (seriesMissingSelected.has(idx)) {
      seriesMissingSelected.delete(idx);
      card.classList.remove("selected");
    } else {
      seriesMissingSelected.add(idx);
      card.classList.add("selected");
    }
    updateMissingCount();
  });

  container.appendChild(card);
}

function updateMissingCount() {
  const countEl = $("#series-missing-count");
  if (countEl) countEl.textContent = seriesMissingSelected.size;
}

function toggleAllMissing(select) {
  const cards = document.querySelectorAll("#series-missing-games-list .missing-selectable");
  cards.forEach((card) => {
    const idx = parseInt(card.dataset.missingIdx);
    if (select) {
      seriesMissingSelected.add(idx);
      card.classList.add("selected");
    } else {
      seriesMissingSelected.delete(idx);
      card.classList.remove("selected");
    }
  });
  updateMissingCount();
}

async function confirmSelectedMissing() {
  if (!currentSeriesId || seriesMissingSelected.size === 0) return;

  const selected = [...seriesMissingSelected].map((i) => seriesMissingAll[i]).filter(Boolean);
  showToast(`Adding ${selected.length} missing games...`, "info");

  try {
    const gamesPayload = selected.map((g) => ({
      title: g.title,
      cover_url: g.cover_url || "",
      platform: g.platform || "",
      release_year: g.release_year,
      rawg_id: null,
      is_missing: true,
    }));

    await apiCall(`/series/${currentSeriesId}/games/batch`, {
      method: "POST",
      body: JSON.stringify({ games: gamesPayload }),
    });

    await selectSeries(currentSeriesId);
    await loadSeries();
    showToast(`Added ${selected.length} missing games to series`, "success");
  } catch (e) {
    showToast("Failed to add some games", "error");
  }
}

function dismissMissingGames() {
  seriesMissingAll = [];
  seriesMissingSelected = new Set();
  seriesSearchAborted = false;
  const section = $("#series-missing-confirm");
  const gamesContainer = $("#series-detail-games");
  if (section) section.classList.add("hidden");
  // Restore DOM order: missing section back after games list
  if (section && gamesContainer && section.parentNode === gamesContainer.parentNode) {
    gamesContainer.parentNode.insertBefore(section, gamesContainer.nextSibling);
  }
  const progressEl = $("#series-missing-progress");
  if (progressEl) progressEl.classList.add("hidden");
}

// --- Sort/Order ---

async function sortSeriesDetail(mode) {
  if (!currentSeriesGames || currentSeriesGames.length === 0) return;

  // For chronological/console sort, fetch missing release years first
  if ((mode === "chronological" || mode === "console") && currentSeriesId) {
    const missingYears = currentSeriesGames.filter(g => !g.release_year);
    if (missingYears.length > 0) {
      showToast(`Fetching release dates for ${missingYears.length} games...`, "info");
      try {
        const result = await apiCall(`/series/${currentSeriesId}/fetch-metadata`);
        if (result.updated > 0) {
          showToast(`Updated ${result.updated} release dates`, "success");
          // Re-fetch games to get updated data
          const games = await apiCall(`/series/${currentSeriesId}/games`);
          currentSeriesGames = games;
        }
      } catch (e) {
        console.warn("Failed to fetch series metadata:", e);
      }
    }
  }

  if (mode === "custom") {
    currentSeriesGames.sort((a, b) => a.position - b.position);
  } else if (mode === "chronological") {
    currentSeriesGames.sort((a, b) => (a.release_year || 9999) - (b.release_year || 9999));
  } else if (mode === "console") {
    currentSeriesGames.sort((a, b) => {
      const pa = (a.platform || "ZZZ").toLowerCase();
      const pb = (b.platform || "ZZZ").toLowerCase();
      if (pa !== pb) return pa.localeCompare(pb);
      return (a.release_year || 9999) - (b.release_year || 9999);
    });
  }

  currentSeriesGames.forEach((g, i) => g.position = i + 1);

  const positions = currentSeriesGames.map((g) => ({ id: g.id, position: g.position }));
  apiCall(`/series/${currentSeriesId}/games/reorder`, {
    method: "PUT",
    body: JSON.stringify({ positions }),
  }).catch(() => {});

  renderSeriesDetail();
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
    const games = await apiCall("/recently-viewed?limit=10");
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

function loadHomepageSeries() {
  const section = $("#my-series-section");
  const container = $("#my-series-list");
  if (!section || !container) return;

  if (seriesList.length === 0) {
    section.style.display = "none";
    return;
  }

  section.style.display = "block";
  container.innerHTML = "";

  seriesList.forEach((s) => {
    const div = document.createElement("div");
    div.className = "recent-game-card";
    div.onclick = () => selectSeries(s.id);

    const coverUrl = s.cover_url ? toAbsoluteUrl(s.cover_url) : "";
    const coverImg = coverUrl
      ? `<img src="${coverUrl}" alt="${s.name}" />`
      : `<div class="no-cover-small" style="width:100px;height:150px;background:var(--card-bg);display:flex;align-items:center;justify-content:center;border-radius:var(--radius);font-size:1.5rem;">📚</div>`;

    div.innerHTML = `
      ${coverImg}
      <div class="title">${s.name}</div>
      <div style="font-size: 0.75rem; color: var(--text-muted);">${s.game_count} games</div>
    `;
    container.appendChild(div);
  });
}

function goToHomepage() {
  currentConsoleId = null;
  currentCollectionId = null;
  currentCollectionGames = [];
  activeFilter = null;
  activeGenreFilter = null;
  activeStatusFilter = null;
  activeDetailFilters = { decade: null, developer: null, publisher: null };
  statusFilteredGames = [];
  consoleStats = null;
  currentPage = 1;
  currentSeriesId = null;
  currentSeriesGames = [];
  currentView = 'homepage';

  // Clear localStorage state for console
  localStorage.setItem('archive_currentView', 'homepage');
  localStorage.setItem('archive_currentConsoleId', '');
  localStorage.setItem('archive_currentCollectionId', '');

  // Hide series views
  $("#series-create-view").classList.add("hidden");
  $("#series-detail-view").classList.add("hidden");
  $("#series-list-view").classList.add("hidden");
  $("#game-list").style.display = "";
  
  renderHomepage();
  renderConsoles();
  renderCollections();
  renderStatusFilters();
}

function renderHomepage() {
  currentView = 'homepage';
  $("#homepage").classList.remove("hidden");
  $("#search-results").classList.add("hidden");
  $(".app-body").classList.add("show-homepage");
  
  // Hide console/series views
  $(".console-summary").style.display = "none";
  $(".alpha-index").style.display = "none";
  $(".metadata-actions").style.display = "none";
  $("#game-list").style.display = "";
  $("#series-create-view").classList.add("hidden");
  $("#series-detail-view").classList.add("hidden");
  $("#series-list-view").classList.add("hidden");
  
  // Load stats and recently viewed
  loadStats();
  loadRecentlyViewed();
  loadLastAdded();
  loadHomepageSeries();
  loadDetailFilters();
}

function showConsoleView() {
  currentView = 'console';
  $("#homepage").classList.add("hidden");
  $("#search-results").classList.add("hidden");
  $(".app-body").classList.remove("show-homepage");
  $("#series-create-view").classList.add("hidden");
  $("#series-detail-view").classList.add("hidden");
  $("#series-list-view").classList.add("hidden");
  
  // Show console view elements
  $(".console-summary").style.display = "flex";
  $(".alpha-index").style.display = "block";
  $(".metadata-actions").style.display = "flex";
  $("#game-list").style.display = "grid";
  
  // Reset visibility of buttons that may have been hidden in collection view
  const rescanBtn = $("#btn-rescan-console");
  const addGameBtn = $("#btn-add-game");
  if (rescanBtn) rescanBtn.style.display = "";
  if (addGameBtn) addGameBtn.style.display = "";
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

  const yearBadge = game.release_year ? `<span class="game-year-badge">${game.release_year}</span>` : '';

  card.innerHTML = `
    <div class="game-cover" style="position: relative;">
      ${cover}
      <button class="game-info-btn" onclick="showGameInfo(event, ${game.id})" title="Game info">ℹ️</button>
      ${yearBadge}
    </div>
    <div class="game-title">${game.title}</div>
    <div class="game-meta">${game.genre || "Unknown genre"}</div>
    ${consoleName ? `<div class="game-meta" style="color: var(--accent);">${consoleName}</div>` : ''}
  `;

  // Make the entire card clickable to open game detail
  card.addEventListener("click", (e) => {
    if (e.target.closest('.game-info-btn')) return;
    openGameDetail(game.id);
  });

  return card;
}

async function showGameInfo(event, gameId) {
  event.stopPropagation();

  // Remove any existing popup
  const existing = document.querySelector('.game-info-popup');
  if (existing) existing.remove();

  try {
    const game = await apiCall(`/games/${gameId}`);
    const popup = document.createElement("div");
    popup.className = "game-info-popup";

    let html = '';
    if (game.release_year) html += `<div class="info-row"><span class="info-label">Year:</span> ${game.release_year}</div>`;
    if (game.developer) html += `<div class="info-row"><span class="info-label">Developer:</span> ${game.developer}</div>`;
    if (game.publisher) html += `<div class="info-row"><span class="info-label">Publisher:</span> ${game.publisher}</div>`;
    if (game.genre) html += `<div class="info-row"><span class="info-label">Genre:</span> ${game.genre}</div>`;
    if (!html) html = '<div class="info-row" style="color: var(--text-muted);">No metadata available</div>';

    popup.innerHTML = html;

    // Position near click
    const rect = event.target.getBoundingClientRect();
    popup.style.position = "fixed";
    popup.style.left = `${rect.left}px`;
    popup.style.top = `${rect.bottom + 4}px`;
    popup.style.zIndex = "10000";

    document.body.appendChild(popup);

    // Close on click outside
    setTimeout(() => {
      document.addEventListener("click", function closePopup(e) {
        if (!popup.contains(e.target) && !e.target.closest('.game-info-btn')) {
          popup.remove();
          document.removeEventListener("click", closePopup);
        }
      });
    }, 100);
  } catch (e) {
    console.warn("Failed to load game info:", e);
  }
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
  $("#game-list").style.display = "grid";
  
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
  localStorage.setItem('archive_currentCollectionId', currentCollectionId || '');
  localStorage.setItem('archive_currentSeriesId', currentSeriesId || '');
  localStorage.setItem('archive_currentView', currentView);
  localStorage.setItem('archive_activeFilter', activeFilter || '');
  localStorage.setItem('archive_activeGenreFilter', activeGenreFilter || '');
  localStorage.setItem('archive_activeStatusFilter', activeStatusFilter || '');
  localStorage.setItem('archive_currentPage', currentPage);
}

function loadPageState() {
  const savedView = localStorage.getItem('archive_currentView');
  const savedConsoleId = localStorage.getItem('archive_currentConsoleId');
  const savedCollectionId = localStorage.getItem('archive_currentCollectionId');
  const savedSeriesId = localStorage.getItem('archive_currentSeriesId');
  
  if (savedView === 'console' && savedConsoleId) {
    return {
      view: 'console',
      consoleId: parseInt(savedConsoleId)
    };
  }
  
  if (savedCollectionId) {
    return {
      view: 'collection',
      collectionId: parseInt(savedCollectionId)
    };
  }

  if (savedSeriesId) {
    return {
      view: 'series',
      seriesId: parseInt(savedSeriesId)
    };
  }

  if (savedView === 'series-list') {
    return { view: 'series-list' };
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
      if (e.target === lightbox && !wasDragged) {
        closeLightbox();
      }
    });
  }

  initLightboxDrag();

  // Touch swipe for lightbox (when not zoomed)
  let lightboxSwipeStartX = 0;
  let lightboxSwipeStartY = 0;
  let lightboxSwipeStartTime = 0;
  let lightboxSwipeLocked = false;

  if (lightbox) {
    lightbox.addEventListener("touchstart", (e) => {
      if (isZoomed) return;
      if (e.touches.length !== 1) return;
      lightboxSwipeStartX = e.touches[0].clientX;
      lightboxSwipeStartY = e.touches[0].clientY;
      lightboxSwipeStartTime = Date.now();
      lightboxSwipeLocked = false;
    }, { passive: false });

    lightbox.addEventListener("touchmove", (e) => {
      if (isZoomed || lightboxSwipeLocked) return;
      const dx = Math.abs(e.touches[0].clientX - lightboxSwipeStartX);
      const dy = Math.abs(e.touches[0].clientY - lightboxSwipeStartY);
      if (dx > 10 && dx > dy) {
        lightboxSwipeLocked = true;
        e.preventDefault();
      } else if (dy > 10 && dy > dx) {
        lightboxSwipeLocked = false;
      }
    }, { passive: false });

    lightbox.addEventListener("touchend", (e) => {
      if (isZoomed) return;
      const dx = e.changedTouches[0].clientX - lightboxSwipeStartX;
      const dy = Math.abs(e.changedTouches[0].clientY - lightboxSwipeStartY);
      const dt = Date.now() - lightboxSwipeStartTime;
      if (Math.abs(dx) > 50 && dy < 40 && dt < 500) {
        const img = document.getElementById("lightbox-img");
        if (dx < 0) {
          if (img) { img.classList.remove("lightbox-slide-left"); img.classList.add("lightbox-slide-right"); }
          nextScreenshot();
        } else {
          if (img) { img.classList.remove("lightbox-slide-right"); img.classList.add("lightbox-slide-left"); }
          previousScreenshot();
        }
        setTimeout(() => { if (img) { img.classList.remove("lightbox-slide-left", "lightbox-slide-right"); } }, 300);
      }
      lightboxSwipeLocked = false;
    }, { passive: true });
  }

  // Touch swipe for game detail modal
  const gameDetailModal = document.getElementById("modal-game-detail");
  let gameSwipeStartX = 0;
  let gameSwipeStartY = 0;
  let gameSwipeStartTime = 0;
  let gameSwipeLocked = false;

  if (gameDetailModal) {
    gameDetailModal.addEventListener("touchstart", (e) => {
      const lb = document.getElementById("screenshot-lightbox");
      if (lb && lb.classList.contains("active")) return;
      const isTyping = document.activeElement && (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA');
      if (isTyping) return;
      if (e.touches.length !== 1) return;
      gameSwipeStartX = e.touches[0].clientX;
      gameSwipeStartY = e.touches[0].clientY;
      gameSwipeStartTime = Date.now();
      gameSwipeLocked = false;
    }, { passive: false });

    gameDetailModal.addEventListener("touchmove", (e) => {
      if (gameSwipeLocked) return;
      const dx = Math.abs(e.touches[0].clientX - gameSwipeStartX);
      const dy = Math.abs(e.touches[0].clientY - gameSwipeStartY);
      if (dx > 10 && dx > dy) {
        gameSwipeLocked = true;
        e.preventDefault();
      } else if (dy > 10 && dy > dx) {
        gameSwipeLocked = false;
      }
    }, { passive: false });

    gameDetailModal.addEventListener("touchend", (e) => {
      const lb = document.getElementById("screenshot-lightbox");
      if (lb && lb.classList.contains("active")) return;
      const dx = e.changedTouches[0].clientX - gameSwipeStartX;
      const dy = Math.abs(e.changedTouches[0].clientY - gameSwipeStartY);
      const dt = Date.now() - gameSwipeStartTime;
      if (Math.abs(dx) > 60 && dy < 50 && dt < 500) {
        if (dx < 0) {
          navigateToNextGame();
        } else {
          navigateToPrevGame();
        }
      }
      gameSwipeLocked = false;
    }, { passive: true });
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

  if (addGameBtn) {
    addGameBtn.addEventListener("click", () => {
      toggleModal("#modal-add-game", true);
    });
  }

  if (addConsoleBtn) {
    addConsoleBtn.addEventListener("click", () => {
      document.querySelector('input[name="console-type"][value="folder"]').checked = true;
      toggleConsoleType();
      populateConsoleCatalog();
      toggleModal("#modal-console", true);
    });
  }

  if (themeBtn) {
    themeBtn.addEventListener("click", () => {
      populateThemeModal();
      refreshApiKeyStatus();
      toggleModal("#modal-theme", true);
    });
  }

  const homeBtn = $("#btn-home");
  if (homeBtn) {
    homeBtn.addEventListener("click", goToHomepage);
  }

  if (consoleCancelBtn) {
    consoleCancelBtn.addEventListener("click", () => {
      document.querySelector('input[name="console-type"][value="folder"]').checked = true;
      toggleConsoleType();
      toggleModal("#modal-console", false);
    });
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

  const apiKeysSaveBtn = $("#btn-apikeys-save");
  if (apiKeysSaveBtn) {
    apiKeysSaveBtn.addEventListener("click", onSaveApiKeys);
  }

  // API key inputs: clear mask on focus, restore on blur if left empty
  for (const id of ["apikey-rawg", "apikey-tgdb"]) {
    const inp = $("#" + id);
    if (!inp) continue;
    inp.addEventListener("focus", () => {
      if (inp.value === "••••••••") inp.value = "";
    });
    inp.addEventListener("blur", () => {
      if (!inp.value.trim()) refreshApiKeyStatus();
    });
  }

  // Genre suggestion dropdown
  setupGenreSuggestions();

  const themeRemoveHeaderBtn = $("#btn-theme-remove-header");
  if (themeRemoveHeaderBtn) {
    themeRemoveHeaderBtn.addEventListener("click", onRemoveThemeHeader);
  }

  const themeRandomHeaderBtn = $("#btn-theme-random-header");
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
  const modal = $(selector);
  if (!modal) {
    console.error(`Modal not found: ${selector}`);
    return;
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

  // Load collections
  await loadCollections();
  loadCollectionsListState();

  // Load series
  await loadSeries();

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

  if (savedState.view === 'collection' && savedState.collectionId) {
    const collectionExists = collections.find(c => c.id === savedState.collectionId);
    if (collectionExists) {
      await selectCollection(savedState.collectionId);
      return;
    }
  }

  if (savedState.view === 'series' && savedState.seriesId) {
    const seriesExists = seriesList.find(s => s.id === savedState.seriesId);
    if (seriesExists) {
      await selectSeries(savedState.seriesId);
      return;
    }
  }

  if (savedState.view === 'series-list') {
    showSeriesListView();
    return;
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
      ${c.icon_url ? `<img class="console-icon" src="${toAbsoluteUrl(c.icon_url)}" alt="${c.name}" />` : ''}
      <span class="console-name">${c.name}</span>
      <span class="console-count">${c.game_count}</span>
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

function toggleConsoleType() {
  const consoleType = document.querySelector('input[name="console-type"]:checked').value;
  const pathLabel = document.getElementById("console-path-label");
  
  if (consoleType === "empty") {
    pathLabel.classList.add("hidden");
  } else {
    pathLabel.classList.remove("hidden");
  }
}

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
      const updated = await apiCall(`/consoles/${editingConsoleId}`, {
        method: "PUT",
        body: JSON.stringify({ name, path }),
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
      
      if (path) {
        await loadGamesForConsole(created.id);
        showToast(`Console '${name}' added and ${created.game_count} games scanned!`, "success");
      } else {
        showToast(`Console '${name}' created (empty). Use "Add Game" to add games.`, "success");
      }
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
  currentCollectionId = null;
  activeFilter = null;
  activeGenreFilter = null;
  activeStatusFilter = null;
  statusFilteredGames = [];
  currentPage = 1;
  genreFilterOpen = false;

  showConsoleView();
  savePageState();
  renderConsoles();
  renderCollections();
  renderStatusFilters();
  updateConsoleSummary();
  await loadGamesForConsole(id);
  extractGenres();
  closeSidebarOverlay();
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
    const { strategy, letter } = choice;
    let toastMsg = strategy === "force" ? "Force updating all metadata" : "Smart updating metadata";
    if (letter) toastMsg += ` (${letter === '0' ? '0-9' : letter})`;
    toastMsg += "...";
    showToast(toastMsg, "info");
    
    const params = new URLSearchParams();
    if (strategy === "force") params.append("force", "true");
    if (letter) params.append("letter", letter);
    
    const result = await apiCall(
      `/consoles/${currentConsoleId}/fetch-metadata?${params.toString()}`,
      { method: "POST" }
    );
    
    const progressMsg = `${result.processed}/${result.total} (${result.progress_pct}%)`;
    if (strategy === "force") {
      showToast(`Force updated metadata: ${result.updated} (${result.skipped} skipped) - ${progressMsg}`, "success");
    } else {
      showToast(`Smart updated metadata: ${result.updated} (${result.skipped} skipped) - ${progressMsg}`, "success");
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
  
  const letters = ['', '0', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z'];
  const letterOptions = letters.map(l => `<option value="${l}">${l === '' ? 'All' : l}</option>`).join('');
  
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

        <div>
          <h3 style="margin: 0 0 10px; font-size: 1rem;">Filter by Letter (Optional)</h3>
          <select id="fetch-letter" style="padding: 8px; width: 100%; font-size: 1rem;">
            ${letterOptions}
          </select>
          <p style="margin: 5px 0; color: var(--text-muted); font-size: 0.85rem;">
            Leave as "All" to fetch all games. Select a letter to fetch only games starting with that letter.
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
      const letterSelect = modal.querySelector('#fetch-letter');
      const letter = letterSelect ? letterSelect.value : '';
      
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
      resolve({ strategy: selected, letter });
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
  
  const letters = ['', '0', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z'];
  const letterOptions = letters.map(l => `<option value="${l}">${l === '' ? 'All' : l}</option>`).join('');
  
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
          <div style="margin-top: 12px;">
            <label style="display: block; margin-bottom: 8px; font-weight: bold;">
              <input type="radio" name="fetch-source" value="tgdb" style="margin-right: 8px;">
              TheGamesDB
            </label>
            <p style="margin: 5px 0; color: var(--text-muted); font-size: 0.85rem;">
              Real box art per console. Requires a TheGamesDB API key (Options &#9881;&#65039;). Falls back automatically when DuckDuckGo is unavailable.
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

        <div>
          <h3 style="margin: 0 0 10px; font-size: 1rem;">Filter by Letter (Optional)</h3>
          <select id="fetch-letter" style="padding: 8px; width: 100%; font-size: 1rem;">
            ${letterOptions}
          </select>
          <p style="margin: 5px 0; color: var(--text-muted); font-size: 0.85rem;">
            Leave as "All" to fetch all games. Select a letter to fetch only games starting with that letter.
          </p>
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
      const letterSelect = modal.querySelector('#fetch-letter');
      const letter = letterSelect ? letterSelect.value : '';
      
      console.log('[DEBUG] Letter select:', letterSelect);
      console.log('[DEBUG] Letter value:', letter);
      
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
      resolve({ source, strategy, letter });
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
  if (document.getElementById("fetch-progress-container")) {
    showToast("A fetch is already running — please wait for it to finish.", "warning");
    return;
  }

  const choice = await showCoverFetchDialog();
  if (!choice) return;
  
  try {
    setLoading(true);
    const { source, strategy, letter } = choice;
    
    let toastMsg = strategy === "force" ? "Force updating all covers" : "Smart updating covers";
    if (letter) toastMsg += ` (${letter === '0' ? '0-9' : letter})`;
    toastMsg += "...";
    showToast(toastMsg, "info");
    
    const params = new URLSearchParams();
    if (strategy === "force") params.append("force", "true");
    if (source) params.append("source", source);
    if (letter) params.append("letter", letter);
    
    // Add progress UI
    const progressContainer = document.createElement('div');
    progressContainer.id = 'fetch-progress-container';
    progressContainer.style.cssText = 'position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: var(--bg-secondary); padding: 15px 25px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); z-index: 10000; min-width: 300px;';
    progressContainer.innerHTML = `
      <div style="margin-bottom: 8px; font-weight: bold;">Fetching Covers</div>
      <div id="fetch-progress-bar" style="width: 100%; height: 8px; background: var(--bg-primary); border-radius: 4px; overflow: hidden;">
        <div id="fetch-progress-fill" style="width: 0%; height: 100%; background: var(--accent-color); transition: width 0.3s;"></div>
      </div>
      <div id="fetch-progress-text" style="margin-top: 8px; font-size: 0.85rem; color: var(--text-muted);">0/0 (0%)</div>
      <button id="btn-cancel-fetch" style="margin-top: 10px; padding: 8px 20px; background: #dc3545; color: white; border: none; border-radius: 4px; cursor: pointer;">Cancel</button>
    `;
    document.body.appendChild(progressContainer);
    
    // Cancel button handler
    document.getElementById('btn-cancel-fetch').onclick = async () => {
      try {
        await apiCall(`/consoles/${currentConsoleId}/fetch-covers/cancel`, { method: "POST" });
        showToast("Cancel signal sent...", "info");
      } catch (e) {}
    };
    
    // Use SSE streaming endpoint
    const url = `${API}/consoles/${currentConsoleId}/fetch-covers/stream?${params.toString()}`;
    const eventSource = new EventSource(url);
    
    let fetchComplete = false;
    let rateLimitedShown = false;

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        if (data.status === 'error') {
          eventSource.close();
          showToast(`Error: ${data.error}`, "error");
          return;
        }

        if (data.status === 'rate_limited') {
          if (!rateLimitedShown) {
            rateLimitedShown = true;
            showToast("DuckDuckGo is rate-limiting this IP - falling back to TheGamesDB where possible", "warning");
          }
          return;
        }

        if (data.status === 'starting') {
          return;
        }
        
        // Update progress UI
        const fill = document.getElementById('fetch-progress-fill');
        const text = document.getElementById('fetch-progress-text');
        if (fill) fill.style.width = `${data.progress_pct}%`;
        if (text) text.textContent = `${data.processed}/${data.total} (${data.progress_pct}%)`;
        
        if (data.status === 'complete' || data.status === 'done') {
          fetchComplete = true;
          eventSource.close();
          
          // Remove progress UI
          progressContainer.remove();
          
          if (data.cancelled) {
            showToast(`Cover fetch cancelled - ${data.processed}/${data.total} processed (${data.updated} updated, ${data.skipped} skipped)`, "warning");
          } else {
            const elapsed = data.elapsed ? ` in ${data.elapsed}s` : '';
            showToast(`Fetched covers: ${data.updated} updated, ${data.skipped} skipped - ${data.processed}/${data.total}${elapsed}`, "success");
          }
          loadGamesForConsole(currentConsoleId);
        }
      } catch (e) {
        console.error("SSE parse error:", e);
      }
    };
    
    eventSource.onerror = () => {
      if (!fetchComplete) {
        eventSource.close();
        progressContainer.remove();
        showToast("Connection error - please retry", "error");
        setLoading(false);
      }
    };
    
  } catch (e) {
    const progressContainer = document.getElementById('fetch-progress-container');
    if (progressContainer) progressContainer.remove();
    showToast(e.message || "Error fetching covers", "error");
  } finally {
    // Don't call setLoading(false) here - it's handled in onmessage
  }
}

async function onFetchScreenshots() {
  if (!currentConsoleId) return;
  if (document.getElementById("fetch-progress-container")) {
    showToast("A fetch is already running — please wait for it to finish.", "warning");
    return;
  }

  // Show confirmation dialog
  const choice = await showScreenshotFetchDialog();
  if (!choice) return;
  
  try {
    const { source, strategy, letter } = choice;
    let toastMsg = strategy === "force" ? "Force fetching all screenshots" : "Smart fetching missing screenshots";
    if (source) toastMsg += ` [${source}]`;
    if (letter) toastMsg += ` (${letter === '0' ? '0-9' : letter})`;
    toastMsg += "...";
    showToast(toastMsg, "info");

    const params = new URLSearchParams();
    if (strategy === "force") params.append("force", "true");
    if (source) params.append("source", source);
    if (letter) params.append("letter", letter);
    
    // Add progress UI
    const progressContainer = document.createElement('div');
    progressContainer.id = 'fetch-progress-container';
    progressContainer.style.cssText = 'position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: var(--bg-secondary); padding: 15px 25px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); z-index: 10000; min-width: 300px;';
    progressContainer.innerHTML = `
      <div style="margin-bottom: 8px; font-weight: bold;">Fetching Screenshots</div>
      <div id="fetch-progress-bar" style="width: 100%; height: 8px; background: var(--bg-primary); border-radius: 4px; overflow: hidden;">
        <div id="fetch-progress-fill" style="width: 0%; height: 100%; background: var(--accent-color); transition: width 0.3s;"></div>
      </div>
      <div id="fetch-progress-text" style="margin-top: 8px; font-size: 0.85rem; color: var(--text-muted);">0/0 (0%)</div>
      <button id="btn-cancel-fetch" style="margin-top: 10px; padding: 8px 20px; background: #dc3545; color: white; border: none; border-radius: 4px; cursor: pointer;">Cancel</button>
    `;
    document.body.appendChild(progressContainer);
    
    // Cancel button handler
    document.getElementById('btn-cancel-fetch').onclick = async () => {
      try {
        await apiCall(`/consoles/${currentConsoleId}/fetch-screenshots/cancel`, { method: "POST" });
        showToast("Cancel signal sent...", "info");
      } catch (e) {}
    };
    
    // Use SSE streaming endpoint
    const url = `${API}/consoles/${currentConsoleId}/fetch-screenshots/stream?${params.toString()}`;
    const eventSource = new EventSource(url);
    
    let fetchComplete = false;
    let rateLimitedShown = false;

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        if (data.status === 'error') {
          eventSource.close();
          showToast(`Error: ${data.error}`, "error");
          return;
        }

        if (data.status === 'rate_limited') {
          if (!rateLimitedShown) {
            rateLimitedShown = true;
            showToast("DuckDuckGo is rate-limiting this IP - falling back to TheGamesDB/RAWG where possible", "warning");
          }
          return;
        }

        if (data.status === 'starting') {
          return;
        }

        // Update progress UI
        const fill = document.getElementById('fetch-progress-fill');
        const text = document.getElementById('fetch-progress-text');
        if (fill) fill.style.width = `${data.progress_pct}%`;
        if (text) text.textContent = `${data.processed}/${data.total} (${data.progress_pct}%)`;

        if (data.status === 'complete' || data.status === 'done') {
          fetchComplete = true;
          eventSource.close();

          // Remove progress UI
          progressContainer.remove();

          const elapsed = data.elapsed ? ` in ${data.elapsed}s` : '';
          const summary = `Fetched screenshots: ${data.updated} updated, ${data.skipped} skipped - ${data.processed}/${data.total}`;

          if (data.cancelled) {
            showToast(`Screenshot fetch cancelled - ${summary}${elapsed}`, "warning");
          } else {
            showToast(`${summary}${elapsed}`, "success");
          }
          loadGamesForConsole(currentConsoleId);
        }
      } catch (e) {
        console.error("SSE parse error:", e);
      }
    };
    
    eventSource.onerror = () => {
      if (!fetchComplete) {
        eventSource.close();
        progressContainer.remove();
        showToast("Connection error - please retry", "error");
        setLoading(false);
      }
    };
    
  } catch (e) {
    const progressContainer = document.getElementById('fetch-progress-container');
    if (progressContainer) progressContainer.remove();
    showToast(e.message || "Error fetching screenshots", "error");
  }
}

function showScreenshotFetchDialog() {
  return new Promise((resolve) => {
    // Remove any existing modals first
    const existingModals = document.querySelectorAll('.modal');
    existingModals.forEach(m => m.remove());
    
    const letters = ['', '0', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z'];
    const letterOptions = letters.map(l => `<option value="${l}">${l === '' ? 'All' : l}</option>`).join('');
    
    // Create modal with backdrop
    const modal = document.createElement('div');
    modal.className = 'modal active';
    modal.innerHTML = `
      <div class="modal-content">
        <h2>Fetch Screenshots Strategy</h2>
        <div style="margin: 20px 0;">
          <div style="margin-bottom: 15px;">
            <h3 style="margin: 0 0 10px; font-size: 1rem;">Select Source</h3>
            <div style="margin-bottom: 12px;">
              <label style="display: block; margin-bottom: 8px; font-weight: bold;">
                <input type="radio" name="screenshot-source" value="duckduckgo" checked style="margin-right: 8px;">
                DuckDuckGo (Recommended)
              </label>
              <p style="margin: 5px 0 8px; color: var(--text-muted); font-size: 0.85rem;">
                Web image search. Falls back to TheGamesDB and RAWG automatically.
              </p>
            </div>
            <div style="margin-bottom: 12px;">
              <label style="display: block; margin-bottom: 8px; font-weight: bold;">
                <input type="radio" name="screenshot-source" value="tgdb" style="margin-right: 8px;">
                TheGamesDB
              </label>
              <p style="margin: 5px 0 8px; color: var(--text-muted); font-size: 0.85rem;">
                Real in-game screenshots per console. Requires a TheGamesDB API key (Options &#9881;&#65039;).
              </p>
            </div>
            <div>
              <label style="display: block; margin-bottom: 8px; font-weight: bold;">
                <input type="radio" name="screenshot-source" value="rawg" style="margin-right: 8px;">
                RAWG
              </label>
              <p style="margin: 5px 0; color: var(--text-muted); font-size: 0.85rem;">
                Uses the RAWG database only.
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

          <div>
            <h3 style="margin: 0 0 10px; font-size: 1rem;">Filter by Letter (Optional)</h3>
            <select id="fetch-letter" style="padding: 8px; width: 100%; font-size: 1rem;">
              ${letterOptions}
            </select>
            <p style="margin: 5px 0; color: var(--text-muted); font-size: 0.85rem;">
              Leave as "All" to fetch all games. Select a letter to fetch only games starting with that letter.
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
      const source = modal.querySelector('input[name="screenshot-source"]:checked').value;
      const strategy = document.querySelector('input[name=fetch-strategy]:checked').value;
      const letterSelect = modal.querySelector('#fetch-letter');
      const letter = letterSelect ? letterSelect.value : '';
      modal.remove();
      resolve({ source, strategy, letter });
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

  // Handle global status filter on homepage (no console selected)
  if (!currentConsoleId && activeStatusFilter && statusFilteredGames.length > 0) {
    renderGlobalStatusFilteredGames(container);
    return;
  }

  if (!currentConsoleId) {
    container.innerHTML = `<p>Select a console to see its games.</p>`;
    return;
  }

  let games;
  
  // If status filter is active, use the pre-fetched status-filtered games
  if (activeStatusFilter && statusFilteredGames.length > 0) {
    games = statusFilteredGames.slice();
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
        ${g.is_completed ? '<div class="game-card-status-badge game-card-completed-badge">✅</div>' : ''}
        ${g.is_printed ? '<div class="game-card-status-badge game-card-printed-badge">🖨️</div>' : ''}
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
  info.innerHTML = `
    <input type="number" id="page-jump-input" min="1" max="${totalPages}" value="${currentPage}" 
           style="width: 50px; padding: 4px 8px; border: 1px solid var(--border); border-radius: 4px; background: white; color: var(--text); text-align: center;" />
    <span>of ${totalPages}</span>
  `;
  const pageInput = info.querySelector("#page-jump-input");
  pageInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") {
      let newPage = parseInt(pageInput.value);
      if (newPage >= 1 && newPage <= totalPages) {
        currentPage = newPage;
        renderGamesForCurrentConsole();
      } else {
        pageInput.value = currentPage;
      }
    }
  });
  pageInput.addEventListener("blur", () => {
    let newPage = parseInt(pageInput.value);
    if (newPage >= 1 && newPage <= totalPages) {
      currentPage = newPage;
      renderGamesForCurrentConsole();
    } else {
      pageInput.value = currentPage;
    }
  });
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

// Render global status-filtered games (from homepage)
// -----------------------------------------------------------
function renderGlobalStatusFilteredGames(container) {
  let games = statusFilteredGames.slice();
  
  const totalPages = Math.ceil(games.length / PAGE_SIZE);
  if (currentPage > totalPages) currentPage = 1;

  const start = (currentPage - 1) * PAGE_SIZE;
  const end = start + PAGE_SIZE;
  const pageGames = games.slice(start, end);

  // Add header showing we're viewing all games with this status
  const header = document.createElement("div");
  header.style.marginBottom = "16px";
  header.innerHTML = `
    <h2>All ${activeStatusFilter.replace("_", " ")} Games</h2>
    <p style="color: var(--text-muted);">Showing ${games.length} game(s) across all consoles</p>
  `;
  container.appendChild(header);

  if (!pageGames.length) {
    container.innerHTML += `<p>No games found.</p>`;
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
        ${g.is_completed ? '<div class="game-card-status-badge game-card-completed-badge">✅</div>' : ''}
        ${g.is_printed ? '<div class="game-card-status-badge game-card-printed-badge">🖨️</div>' : ''}
      </div>
      <div class="game-title">${g.title}</div>
      <div class="game-meta">
        ${g.genre || "Unknown genre"}
        ${g.console_name ? `<span class="game-console-badge">${g.console_name}</span>` : ""}
      </div>
      <div class="game-actions">
      </div>
    `;

    card.addEventListener("click", (e) => {
      if (e.target.tagName === "BUTTON") return;
      openGameDetail(g.id);
    });

    container.appendChild(card);
  });

  // Pagination for global filtered games
  if (totalPages > 1) {
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
    info.innerHTML = `
      <input type="number" id="page-jump-input-global" min="1" max="${totalPages}" value="${currentPage}" 
             style="width: 50px; padding: 4px 8px; border: 1px solid var(--border); border-radius: 4px; background: white; color: var(--text); text-align: center;" />
      <span>of ${totalPages}</span>
    `;
    const pageInput = info.querySelector("#page-jump-input-global");
    pageInput.addEventListener("keypress", (e) => {
      if (e.key === "Enter") {
        let newPage = parseInt(pageInput.value);
        if (newPage >= 1 && newPage <= totalPages) {
          currentPage = newPage;
          renderGamesForCurrentConsole();
        } else {
          pageInput.value = currentPage;
        }
      }
    });
    pageInput.addEventListener("blur", () => {
      let newPage = parseInt(pageInput.value);
      if (newPage >= 1 && newPage <= totalPages) {
        currentPage = newPage;
        renderGamesForCurrentConsole();
      } else {
        pageInput.value = currentPage;
      }
    });
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

  // Check for notes
  const gameNotes = currentGameStatus?.notes;
  const hasNotes = gameNotes && gameNotes.trim().length > 0;
  const notesPreview = hasNotes ? getNotePreview(gameNotes) : '';

  const notesHtml = hasNotes
    ? `<p class="game-detail-completed">
        <span class="completed-indicator" data-note="${escapeHtml(gameNotes)}" onclick="openNotesCommentModal(this)" title="Click to view notes">📝</span>
        <span class="completed-preview">${notesPreview}</span>
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
          <div class="game-detail-desc"><strong>Description:</strong> ${renderMarkdown(currentDescription)}</div>
          ${descPaginationHtml}
          ${completedHtml}
          ${notesHtml}
        </div>
      </div>
      ${screenshotsHtml}
      <div class="game-detail-collections" id="game-detail-collections">
        <h3>Collections</h3>
        <div id="game-collection-tags" class="collection-tags"></div>
        <div class="add-to-collection" style="margin-top:8px;">
          <input type="text" id="collection-input" placeholder="Type collection name to add..." autocomplete="off" />
          <div id="collection-suggestions" class="collection-suggestions" style="display:none;"></div>
        </div>
      </div>
    </div>
  `;

  renderGameDetailCollections(game);
}

async function renderGameDetailCollections(game) {
  const tagsContainer = document.getElementById("game-collection-tags");
  const input = document.getElementById("collection-input");
  if (!tagsContainer) return;

  let gameCollections = [];
  try {
    gameCollections = await apiCall(`/games/${game.id}/collections`);
  } catch (e) {
    gameCollections = [];
  }

  tagsContainer.innerHTML = "";
  if (gameCollections.length > 0) {
    gameCollections.forEach((c) => {
      const tag = document.createElement("span");
      tag.className = "collection-tag";
      tag.innerHTML = `${c.collection_name} <span class="collection-tag-remove" onclick="toggleGameCollection(${c.collection_id}, ${game.id}, false)">×</span>`;
      tagsContainer.appendChild(tag);
    });
  } else {
    tagsContainer.innerHTML = '<span class="no-collections">Not in any collection</span>';
  }

  if (input) {
    input.value = "";
    input.oninput = function () {
      const val = this.value.trim().toLowerCase();
      const suggestions = document.getElementById("collection-suggestions");
      if (!val || val.length < 1) {
        suggestions.style.display = "none";
        return;
      }
      const matches = collections.filter((c) =>
        c.name.toLowerCase().includes(val)
      );
      if (matches.length === 0) {
        suggestions.innerHTML = `<div class="collection-suggestion" onclick="createAndAddCollection('${this.value.trim()}', ${game.id})">+ Create "${this.value.trim()}"</div>`;
        suggestions.style.display = "block";
        return;
      }
      suggestions.innerHTML = matches
        .map(
          (c) =>
            `<div class="collection-suggestion" onclick="toggleGameCollection(${c.id}, ${game.id}, true); document.getElementById('collection-input').value = ''; document.getElementById('collection-suggestions').style.display = 'none';">${c.name} (${c.game_count})</div>`
        )
        .join("");
      suggestions.style.display = "block";
    };

    input.onblur = function () {
      setTimeout(() => {
        document.getElementById("collection-suggestions").style.display = "none";
      }, 200);
    };

    input.onfocus = function () {
      if (this.value.trim()) {
        this.oninput();
      }
    };
  }
}

async function createAndAddCollection(name, gameId) {
  try {
    const collection = await apiCall("/collections", {
      method: "POST",
      body: JSON.stringify({ name, description: "" }),
    });
    collections.push(collection);
    renderCollections();
    const ok = await addGameToCollection(collection.id, gameId);
    if (ok) {
      showToast(`Created and added to '${name}'`, "success");
      await loadCollections();
      renderGameDetailCollections(currentGameDetail);
    }
  } catch (e) {
    // Error already shown
  }
}

// -----------------------------------------------------------
// Game Detail Navigation
// -----------------------------------------------------------
function changeDescriptionPage(delta) {
  const newPage = currentDescriptionPage + delta;
  if (newPage >= 1 && newPage <= totalDescriptionPages) {
    currentDescriptionPage = newPage;
    renderGameDetail(currentGameDetail);
  }
}

function formatCompletedDate(note) {
  if (!note) return '';
  // Try to extract date from note - look for patterns like "mm/dd/yyyy" or "yyyy" or "mm/dd"
  // The note can contain the date plus comment, so we try to extract just the date part
  const dateMatch = note.match(/^(\d{1,2}\/\d{1,2}\/\d{4}|\d{4}|\d{1,2}\/\d{1,2})/);
  if (dateMatch) {
    return dateMatch[1];
  }
  return '';
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

function renderMarkdown(text) {
  if (!text) return '';
  let html = escapeHtml(text);
  // Bold: **text**
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // Italic: *text* (but not inside **)
  html = html.replace(/(?<!\*)\*([^*]+?)\*(?!\*)/g, '<em>$1</em>');
  // Paragraphs: double newlines
  html = html.split(/\n{2,}/).map(p => '<p>' + p.trim() + '</p>').join('');
  // Single newlines inside paragraphs
  html = html.replace(/([^>])\n([^<])/g, '$1<br>$2');
  return html;
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

function openCompletedCommentModal(element) {
  const note = element.getAttribute('data-note');
  const content = $("#completed-comment-content");
  content.innerHTML = renderMarkdown(note);
  toggleModal("#modal-completed-comment", true);
}

function openNotesCommentModal(element) {
  const note = element.getAttribute('data-note');
  const content = $("#notes-comment-content");
  content.innerHTML = renderMarkdown(note);
  toggleModal("#modal-notes-comment", true);
}

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

    // Read default source from Options modal
    const source = ($("#default-screenshot-source") || {}).value || "duckduckgo";

    const result = await apiCall(
      `/games/${gameId}/fetch-screenshots?source=${encodeURIComponent(source)}`,
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
    showToast("Fetching cover...", "info");

    // Read default source from Options modal
    const source = ($("#default-cover-source") || {}).value || "auto";

    const result = await apiCall(
      `/games/${gameId}/fetch-cover?source=${encodeURIComponent(source)}`,
      { method: "POST" }
    );

    if (result.status === "ok") {
      const via = result.source ? ` (${result.source})` : "";
      showToast(`Cover updated for "${result.title}"${via}`, "success");

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
    showToast(e.message || "Error fetching cover", "error");
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
  } catch (error) {
    // Error already shown by apiCall
  }
}

async function deleteConsole(consoleId, event) {
  event.stopPropagation();
  
  const console = consoles.find(c => c.id === consoleId);
  if (!console) return;
  
  const confirmation = prompt(`Type '123' to confirm deletion of console "${console.name}" and ALL its games:`);
  if (confirmation !== "123") {
    showToast("Console deletion cancelled - incorrect confirmation", "error");
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

  // Check if a file was uploaded
  const fileInput = $("#theme-header-upload");
  if (fileInput.files && fileInput.files[0]) {
    const file = fileInput.files[0];
    
    // Upload the file
    const formData = new FormData();
    formData.append("file", file);

    try {
      setLoading(true);
      const res = await fetch(`${API}/theme/upload-header`, {
        method: "POST",
        body: formData,
      });
      
      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: "Upload failed" }));
        throw new Error(error.detail || "Upload failed");
      }
      
      const result = await res.json();
      headerImage = result.url;
      showToast("Header image uploaded!", "success");
    } catch (e) {
      showToast(`Upload failed: ${e.message}`, "error");
      return;
    } finally {
      setLoading(false);
    }
  }

  const theme = { bgColor, accent, headerImage };
  localStorage.setItem("gameArchiveTheme", JSON.stringify(theme));

  applyTheme(theme);

  // Save default fetch sources
  const coverSource = $("#default-cover-source").value;
  const screenshotSource = $("#default-screenshot-source").value;
  try {
    await apiCall("/settings/default-source", {
      method: "PUT",
      body: JSON.stringify({ cover_source: coverSource, screenshot_source: screenshotSource }),
    });
  } catch (e) {
    // non-critical — continue
  }

  toggleModal("#modal-theme", false);
  showToast("Theme saved!", "success");
}

let consoleCatalogCache = null;

async function populateConsoleCatalog() {
  const list = document.getElementById("console-catalog-list");
  if (!list) return;
  try {
    if (!consoleCatalogCache) {
      consoleCatalogCache = await apiCall("/consoles/catalog");
    }
    list.innerHTML = consoleCatalogCache
      .map((c) => `<option value="${c.name.replace(/"/g, "&quot;")}"></option>`)
      .join("");
  } catch (e) {
    // catalog optional - leave datalist empty
  }
}

async function refreshApiKeyStatus() {
  const statusEl = $("#apikey-status");
  const rawgInput = $("#apikey-rawg");
  const tgdbInput = $("#apikey-tgdb");
  if (!statusEl) return;
  try {
    const status = await apiCall("/settings/apikeys");
    const parts = [];
    parts.push(`RAWG: ${status.rawg_configured ? "configured" : "not set"}`);
    parts.push(`TheGamesDB: ${status.tgdb_configured ? "configured" : "not set"}`);
    statusEl.textContent = parts.join("  |  ");
    if (rawgInput) rawgInput.value = status.rawg_configured ? "••••••••" : "";
    if (tgdbInput) tgdbInput.value = status.tgdb_configured ? "••••••••" : "";
  } catch (e) {
    statusEl.textContent = "";
  }
}

function setupGenreSuggestions() {
  const input = $("#edit-game-genre");
  if (!input) return;

  // Create dropdown in document.body to avoid overflow clipping by .modal-content
  const dropdown = document.createElement("div");
  dropdown.id = "genre-suggestions";
  dropdown.className = "genre-suggestions";
  document.body.appendChild(dropdown);

  let allGenres = [];
  let activeIdx = -1;
  let cachePromise = null;
  let currentMatches = [];

  async function loadGenres() {
    if (allGenres.length) return allGenres;
    if (!cachePromise) {
      cachePromise = apiCall("/genres").catch(() => []);
    }
    allGenres = await cachePromise;
    return allGenres;
  }

  function positionDropdown() {
    const r = input.getBoundingClientRect();
    dropdown.style.position = "fixed";
    dropdown.style.top = r.bottom + 2 + "px";
    dropdown.style.left = r.left + "px";
    dropdown.style.width = r.width + "px";
  }

  function render(matches) {
    currentMatches = matches;
    dropdown.innerHTML = "";
    if (!matches.length) { dropdown.style.display = "none"; return; }
    matches.forEach((g, i) => {
      const div = document.createElement("div");
      div.textContent = g;
      if (i === activeIdx) div.className = "genre-suggestion-item active";
      else div.className = "genre-suggestion-item";
      div.addEventListener("mouseenter", () => { activeIdx = i; render(matches); });
      div.addEventListener("mousedown", (e) => { e.preventDefault(); pick(g); });
      dropdown.appendChild(div);
    });
    positionDropdown();
    dropdown.style.display = "block";
  }

  function pick(val) {
    const raw = input.value;
    const parts = raw.split(",").map(s => s.trim());
    parts[parts.length - 1] = val;
    input.value = parts.join(", ") + ", ";
    dropdown.style.display = "none";
    activeIdx = -1;
    input.focus();
  }

  input.addEventListener("input", async () => {
    activeIdx = -1;
    const raw = input.value;
    const parts = raw.split(",").map(s => s.trim());
    const needle = (parts[parts.length - 1] || "").toLowerCase();
    if (!needle) { dropdown.style.display = "none"; return; }

    const all = await loadGenres();
    const matches = all.filter(g => g.toLowerCase().includes(needle)).slice(0, 8);
    render(matches);
  });

  input.addEventListener("keydown", (e) => {
    const items = dropdown.children;
    if (!items.length || dropdown.style.display === "none") return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIdx = Math.min(activeIdx + 1, items.length - 1);
      Array.from(items).forEach((d, i) => d.className = i === activeIdx ? "genre-suggestion-item active" : "genre-suggestion-item");
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIdx = Math.max(activeIdx - 1, 0);
      Array.from(items).forEach((d, i) => d.className = i === activeIdx ? "genre-suggestion-item active" : "genre-suggestion-item");
    } else if (e.key === "Enter" && activeIdx >= 0) {
      e.preventDefault();
      pick(items[activeIdx].textContent);
    } else if (e.key === "Escape") {
      dropdown.style.display = "none";
    }
  });

  input.addEventListener("blur", () => {
    setTimeout(() => { dropdown.style.display = "none"; }, 200);
  });
}

async function onSaveApiKeys() {
  const statusEl = $("#apikey-status");
  const updates = [];

  const rawgKey = $("#apikey-rawg") ? $("#apikey-rawg").value.trim() : "";
  const tgdbKey = $("#apikey-tgdb") ? $("#apikey-tgdb").value.trim() : "";

  if (rawgKey) updates.push(["rawg", rawgKey]);
  if (tgdbKey) updates.push(["tgdb", tgdbKey]);

  if (!updates.length) {
    showToast("No new keys entered", "info");
    return;
  }

  try {
    setLoading(true);
    for (const [provider, key] of updates) {
      await apiCall(`/settings/apikeys/${provider}`, {
        method: "PUT",
        body: JSON.stringify({ key }),
      });
      $("#" + (provider === "rawg" ? "apikey-rawg" : "apikey-tgdb")).value = "";
    }
    showToast("API key(s) saved", "success");
  } catch (e) {
    showToast(`Failed to save key(s): ${e.message}`, "error");
  } finally {
    setLoading(false);
  }
  if (statusEl) await refreshApiKeyStatus();
}

async function populateThemeModal() {
  const currentHeaderSection = $("#theme-current-header");
  const currentHeaderImg = $("#theme-current-header-img");

  // Check server state instead of localStorage
  try {
    const res = await fetch(`${API}/theme/header`);
    const data = await res.json();
    
    if (data.exists && data.url) {
      const fullUrl = toAbsoluteUrl(data.url) + `?t=${Date.now()}`; // Add cache-buster
      currentHeaderImg.src = fullUrl;
      currentHeaderSection.classList.remove("hidden");
    } else {
      // No image on server - hide preview and clear localStorage if it has headerImage
      currentHeaderSection.classList.add("hidden");
      currentHeaderImg.src = "";
      
      // Also clear localStorage to sync state
      const raw = localStorage.getItem("gameArchiveTheme");
      if (raw) {
        try {
          const theme = JSON.parse(raw);
          if (theme.headerImage) {
            theme.headerImage = "";
            localStorage.setItem("gameArchiveTheme", JSON.stringify(theme));
            applyTheme(theme);
          }
        } catch (e) {}
      }
    }
  } catch (e) {
    console.error("Failed to check theme header:", e);
    currentHeaderSection.classList.add("hidden");
  }
  
  // Also clear the file input
  const fileInput = $("#theme-header-upload");
  if (fileInput) fileInput.value = "";

  // Load saved colors into the inputs
  const raw = localStorage.getItem("gameArchiveTheme");
  if (raw) {
    try {
      const theme = JSON.parse(raw);
      if (theme.bgColor) {
        const bgInput = $("#theme-bg-color");
        if (bgInput) bgInput.value = theme.bgColor;
      }
      if (theme.accent) {
        const accentInput = $("#theme-accent-color");
        if (accentInput) accentInput.value = theme.accent;
      }
    } catch (e) {}
  }

  // Load default fetch sources
  try {
    const ds = await apiCall("/settings/default-source");
    const coverSel = $("#default-cover-source");
    const ssSel = $("#default-screenshot-source");
    if (coverSel && ds.cover_source) coverSel.value = ds.cover_source;
    if (ssSel && ds.screenshot_source) ssSel.value = ds.screenshot_source;
  } catch (e) {
    // non-critical
  }
}

async function onRemoveThemeHeader() {
  try {
    setLoading(true);
    const res = await fetch(`${API}/theme/header`, { method: "DELETE" });
    if (!res.ok) throw new Error("Failed to delete");
    
    // Update localStorage
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
    showToast(`Failed to remove: ${e.message}`, "error");
  } finally {
    setLoading(false);
  }
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

// -----------------------------------------------------------
// Theme
// -----------------------------------------------------------

let headerGeneration = 0;

function applyTheme(theme) {
  if (theme.bgColor) {
    document.documentElement.style.setProperty("--bg-color", theme.bgColor);
    document.body.style.background = theme.bgColor;
  }
  if (theme.accent) {
    document.documentElement.style.setProperty("--accent", theme.accent);
  }
  if (theme.headerImage) {
    headerGeneration++;
    const gen = headerGeneration;
    const img = new Image();
    img.onload = function() {
      if (gen !== headerGeneration) return; // stale — another applyTheme() ran
      const header = $(".app-header");
      header.style.backgroundImage = `url("${theme.headerImage}")`;
      header.style.backgroundRepeat = "no-repeat";
      header.style.backgroundSize = "100% auto";
      header.style.backgroundPosition = "center";
      header.style.height = Math.min(this.naturalHeight, 200) + "px";
      header.style.overflow = "hidden";
    };
    img.onerror = function() {
      if (gen !== headerGeneration) return; // stale — don't clear
    };
    img.src = theme.headerImage;
  } else {
    $(".app-header").style.backgroundImage = "none";
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
// Sidebar toggle (unified: tablet collapse + small screen overlay)
// -----------------------------------------------------------

function toggleSidebarCollapse() {
  const sidebar = $("#sidebar");
  if (!sidebar) return;
  const isSmallScreen = window.innerWidth <= 768;
  if (isSmallScreen) {
    // Overlay mode: toggle open/close
    sidebar.classList.toggle("sidebar-open");
    const backdrop = $("#sidebar-backdrop");
    if (backdrop) backdrop.classList.toggle("active", sidebar.classList.contains("sidebar-open"));
  } else {
    // Tablet mode: toggle collapsed/expanded
    sidebar.classList.toggle("sidebar-collapsed");
    const collapsed = sidebar.classList.contains("sidebar-collapsed");
    localStorage.setItem("sidebarCollapsed", collapsed ? "true" : "false");
  }
}

function loadSidebarCollapseState() {
  const sidebar = $("#sidebar");
  if (!sidebar) return;
  const collapsed = localStorage.getItem("sidebarCollapsed") === "true";
  if (collapsed && window.innerWidth > 768) {
    sidebar.classList.add("sidebar-collapsed");
  }
}

// -----------------------------------------------------------
// Sidebar overlay (small tablet / phone)
// -----------------------------------------------------------

function openSidebarOverlay() {
  const sidebar = $("#sidebar");
  const backdrop = $("#sidebar-backdrop");
  if (sidebar) sidebar.classList.add("sidebar-open");
  if (backdrop) backdrop.classList.add("active");
}

function closeSidebarOverlay() {
  const sidebar = $("#sidebar");
  const backdrop = $("#sidebar-backdrop");
  if (sidebar) sidebar.classList.remove("sidebar-open");
  if (backdrop) backdrop.classList.remove("active");
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
    const homepageTitle = $("#homepage-title");
    if (homepageTitle) {
      homepageTitle.textContent = title;
    }
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
    const homepageTitle = $("#homepage-title");
    if (homepageTitle) {
      homepageTitle.textContent = customTitle;
    }
  }
}

let headerRotationInterval = null;

const HEADER_ROTATION_INTERVAL = 2 * 60 * 60 * 1000; // 2 hours in milliseconds

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
  loadSidebarCollapseState();
  loadConsoleListState();
  loadCustomTitle();
  applyRandomHeaderOnLoad();

  // Clean up sidebar state on resize (e.g. tablet rotation)
  window.addEventListener("resize", () => {
    const sidebar = $("#sidebar");
    if (!sidebar) return;
    if (window.innerWidth > 768) {
      closeSidebarOverlay();
    }
  });

  // Swipe left/right on game list to change pages
  initGameListSwipe();
}

function initGameListSwipe() {
  const gameList = $("#game-list");
  if (!gameList) return;
  let swipeStartX = 0;
  let swipeStartY = 0;
  let swipeStartTime = 0;
  let swipeLocked = false;

  gameList.addEventListener("touchstart", (e) => {
    if (e.touches.length !== 1) return;
    swipeStartX = e.touches[0].clientX;
    swipeStartY = e.touches[0].clientY;
    swipeStartTime = Date.now();
    swipeLocked = false;
  }, { passive: false });

  gameList.addEventListener("touchmove", (e) => {
    if (swipeLocked) return;
    const dx = Math.abs(e.touches[0].clientX - swipeStartX);
    const dy = Math.abs(e.touches[0].clientY - swipeStartY);
    if (dx > 10 && dx > dy) {
      swipeLocked = true;
      e.preventDefault();
    } else if (dy > 10 && dy > dx) {
      swipeLocked = false;
    }
  }, { passive: false });

  gameList.addEventListener("touchend", (e) => {
    const dx = e.changedTouches[0].clientX - swipeStartX;
    const dy = Math.abs(e.changedTouches[0].clientY - swipeStartY);
    const dt = Date.now() - swipeStartTime;
    if (Math.abs(dx) > 60 && dy < 40 && dt < 500) {
      const totalPages = Math.ceil((gamesByConsole[currentConsoleId] || []).length / PAGE_SIZE);
      if (totalPages <= 1) return;
      if (dx < 0 && currentPage < totalPages) {
        currentPage++;
        renderGamesForCurrentConsole();
      } else if (dx > 0 && currentPage > 1) {
        currentPage--;
        renderGamesForCurrentConsole();
      }
    }
    swipeLocked = false;
  }, { passive: true });
}
