# 🐾 Zoological Society  

<img src="zoological logo.png" width="200" align="right" alt="Zoological Society Logo">
# Zoological Society
<br><br>

*A lightweight, user‑friendly game archive with rotating themed headers, customizable visuals, and smart metadata fetching.*

Zoological Society is especially designed for keeping track of the games you own across platforms and digital stores. Whether your library spans physical cartridges, retro computers, modern consoles, or multiple online storefronts, it gives you a clear overview of your entire collection. It helps you decide what to play next, avoid forgetting what you already own, and maintain a tidy, unified archive no matter how scattered your games are in real life.

This project is built for people who want a personal archive that feels **beautiful**, **fast**, and **fully under their control**.

---

## 📰 What's New (Latest Updates)

### Version 2.2 - Metadata, Genres & Status Overhaul

#### 🗄️ Database & Backend
- **SQLite WAL Mode** - Concurrent read/write access, no more locking errors during fetches
- **Bulk Fetch Lock** - Serializes bulk operations so only one runs at a time
- **DB Key Sync** - API keys from `.env` are synced to the database on startup automatically

#### 🎮 TheGamesDB Integration
- **Third Metadata Provider** - TheGamesDB as a new source for cover art and screenshots
- **Rate Limiting** - Built-in rate limiter to protect against monthly quota exhaustion
- **API Key Management** - Add/remove API keys for RAWG and TheGamesDB from the Options modal

#### 🏷️ Genre System
- **Genre Normalization** - Archive-wide consistent casing (e.g. "RPG" not "rpg", "Rpg", "Rpgs")
- **Genre Suggestions** - Typing in the genre field shows archive-wide unique genre suggestions
- **Genres Endpoint** - Dedicated `/api/genres` endpoint returning all unique genres in the archive
- **Console Catalog** - Canonical catalog of 117 consoles with TheGamesDB/RAWG platform IDs

#### 📝 Notes & Status
- **Game Notes** - Add free-text notes to any game (visible on game detail and thumbnails)
- **Printed Status** - Mark games as printed with a printer icon 🖨️
- **Thumbnail Badges** - Completed (✅) and printed (🖨️) badges on game thumbnails
- **Markdown Descriptions** - Bold, italic, and paragraph formatting in game descriptions and notes

#### 🖼️ Fetch Source Selection
- **Default Source** - Choose your preferred source (Auto, DuckDuckGo, TheGamesDB, RAWG) for covers and screenshots
- **Per-Operation Override** - Options modal lets you set defaults that apply to every single-game fetch
- **Auto Fallback** - "Auto" mode chains DuckDuckGo → TheGamesDB → RAWG with automatic fallback

#### 📱 Tablet & Mobile Optimization
- **Responsive Layout** - Full tablet support with 3 breakpoints (1024px, 768px, 480px) — the app now works beautifully on iPads and phones
- **Collapsible Sidebar** - Sidebar narrows on tablet and collapses behind a hamburger menu (☰) on small screens, with backdrop overlay
- **Touch-Friendly Interactions** - `touch-action: manipulation` eliminates double-tap delays; swipe left/right on the game list changes pages
- **Swipe Navigation** - Swipe left/right in the lightbox to browse screenshots, in the game detail modal to browse games — content stays locked in place during swipes via `preventDefault()` on horizontal intent
- **Header Responsiveness** - Header images scale to screen width, capped at safe heights per breakpoint (200px PC, 120px tablet, 80px phone)
- **Game Detail Scrolling** - Game detail modal now scrolls vertically on touch devices (overflow-y: auto)
- **Lightbox Fixes** - Close button z-index fix, no-repeat background to prevent tiling, slide animation on swipe

---

### Previous Implementations

#### Version 2.1 - Fetching & UI Improvements

##### 🚀 Fetching Upgrades
- **Real-time Progress** - See live progress when fetching covers and screenshots with SSE streaming (shows X/Y games, percentage, elapsed time)
- **Batch by Letter** - Filter fetching by starting letter (A-Z, 0-9) to process games in chunks
- **Cancel Fetch** - Ability to cancel ongoing fetch operations mid-way

##### 🎨 UI Improvements  
- **Page Jump** - Type a page number directly in the pagination input to jump ahead
- **Screenshot Grid** - Improved 5-column grid with consistent sizing
- **Screenshot Navigation** - Fixed lightbox navigation to correctly track clicked screenshot

---

<p align="center">
  <img src="/img-content/Screenshot 2026-02-17 133639.png" width="1080" alt="Zoological Society Logo">
</p>

---

## ✨ Features

### 📁 Archive Creation
- Add consoles from local ROM folders  
- Create empty consoles manually  
- Add games manually (single entry or bulk list)  
- Rescan folders to detect new games  

---

<p align="center">
  <img src="/img-content/Screenshot 2026-02-17 144240.png" width="1080" alt="Zoological Society Logo">
</p>

### 🎨 Graphic Customization

#### **Header Images**
- Random header selection from `/headers/` folder  
- 39 themed headers included  
- Auto‑rotation every **2 hours**  
- Manual refresh button (🔄)  
- Upload your own custom headers  

#### **Title Customization**
- Collapse/expand title (▼ arrow)  
- Rename project title (✏️ pencil icon)  

#### **Theme Colors**
- Background color picker  
- Accent color picker  

---

<p align="center">
  <img src="/img-content/Screenshot 2026-02-17 140149.png" width="1080" alt="Zoological Society Logo">
</p>

### 📊 Status Filters & Stats

#### **Status Tracking**
- Playing  
- Completed  
- Plan to Play  
- On Hold  
- Dropped  
- Mark as Favorite ⭐  

#### **Stats Display**
- Total consoles  
- Total games  
- Completed count  
- Favorites count  

---

### 🎮 Genres
- Genre filtering per console  
- Genre display inside game details  

---

### 🔍 Auto‑Fetch / Metadata
- **RAWG API** integration for detailed game metadata  
- **DuckDuckGo fallback** (no API key required)  
- Automatic cover image fetching  
- Screenshot fetching  

---

### 💾 Data Management
- Delete entire consoles (including all games)  
- Delete individual games  
- Delete covers and screenshots  

---

### 🔎 Search & Navigation
- Global search across all consoles  
- Console‑specific filtering  
- Alphabetical index navigation  

<p align="center">
  <img src="/img-content/Screenshot 2026-02-17 140332.png" width="1080" alt="Zoological Society Logo">
</p>

<p align="center">
  <img src="/img-content/Screenshot 2026-02-17 141132.png" width="1080" alt="Zoological Society Logo">
</p>

<p align="center">
  <img src="/img-content/Screenshot 2026-02-17 141148.png" width="1080" alt="Zoological Society Logo">
</p>

---

## 📂 Project Structure (simplified)

```
zoological-society/
│
├── headers/            # Rotating banner images
├── covers/             # Auto-fetched or manual cover art
├── screenshots/        # Auto-fetched screenshots
├── data/               # JSON database for consoles & games
├── src/                # Frontend & backend logic
└── README.md
```

---

## 🚀 Getting Started

Clone the repository:

```bash
git clone git@github.com:DaroHacka/zoological-society.git
cd zoological-society
```

Run the project (depending on your setup):

```bash
npm install
npm run dev
```

Or your preferred environment.

---

## 🖼️ Header System

The project includes **39 ultra‑wide banners** designed for a rotating header system.  
You can add your own images to `/headers/` — the app will automatically detect them. 

---

## 📜 License
MIT License — feel free to use, modify, and adapt.

---

## 💬 Feedback & Contributions
This project is personal but open to suggestions, improvements, and ideas.  
Feel free to open issues or submit pull requests.
