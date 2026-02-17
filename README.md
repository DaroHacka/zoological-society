# 🐾 Zoological Society  

<img src="zoological logo.png" width="200" align="right" alt="Zoological Society Logo">
# Zoological Society

Zoological Society is a clean, self‑contained cross‑platform archive system designed to help you organize consoles, computers, and games of any generation — from modern PCs to vintage platforms like the Amiga, ZX Spectrum, Commodore 64, or 486 — with style and flexibility.

(…rest of README)
*A lightweight, user‑friendly game archive with rotating themed headers, customizable visuals, and smart metadata fetching.*

Zoological Society is a clean, self-contained cross-platform archive system designed to help you organize consoles, computers, and games of any generation — from modern PCs to vintage platforms like the Amiga, ZX Spectrum, Commodore 64 — with style and flexibility It blends simplicity with thoughtful UI touches: rotating banners, color themes, metadata fetching, genre filtering, and a smooth workflow for managing large collections.

This project is built for people who want a personal archive that feels **beautiful**, **fast**, and **fully under their control**.

<p align="center">
  <img src="screenshots/Screenshot 2026-02-17 133639.png" width="1080" alt="Zoological Society Logo">
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
  <img src="screenshots/Screenshot 2026-02-17 135023.png" width="1080" alt="Zoological Society Logo">
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
  <img src="screenshots/Screenshot 2026-02-17 140149.png" width="1080" alt="Zoological Society Logo">
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
  <img src="screenshots/Screenshot 2026-02-17 140332.png" width="1080" alt="Zoological Society Logo">
</p>

<p align="center">
  <img src="screenshots/Screenshot 2026-02-17 141132.png" width="1080" alt="Zoological Society Logo">
</p>

<p align="center">
  <img src="screenshots/Screenshot 2026-02-17 141148.png" width="1080" alt="Zoological Society Logo">
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

## 🧩 Roadmap (optional section — remove if you prefer)

- Additional metadata sources  
- Export/import archive  
- Custom console icons  
- Dark/light theme presets  
- Multi‑language support  

---

## 📜 License
MIT License — feel free to use, modify, and adapt.

---

## 💬 Feedback & Contributions
This project is personal but open to suggestions, improvements, and ideas.  
Feel free to open issues or submit pull requests.
