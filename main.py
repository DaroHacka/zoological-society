import os
import re
import json
import sqlite3
import logging
from datetime import datetime
from io import BytesIO
from PIL import Image
from typing import Optional, List
import urllib.parse

import requests
from fastapi import FastAPI, HTTPException, BackgroundTasks, File, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# --- RAWG PLATFORM ALIASES ---
RAWG_PLATFORM_ALIASES = {
    15: ["ps2", "playstation 2", "sony playstation 2"],
    16: ["ps3", "playstation 3", "sony playstation 3"],
    18: ["ps4", "playstation 4", "sony playstation 4"],
    187: ["ps5", "playstation 5", "sony playstation 5"],

    14: ["xbox", "original xbox", "microsoft xbox"],
    17: ["xbox 360", "x360"],
    1: ["xbox one"],
    186: ["xbox series x", "xbox series s", "series x"],

    13: ["gamecube", "nintendo gamecube", "ngc"],
    11: ["wii", "nintendo wii"],
    10: ["switch", "nintendo switch", "nsw"],
    9:  ["nds", "nintendo ds", "ds"],
    8:  ["3ds", "nintendo 3ds", "cia"],
    4:  ["pc", "windows", "steam"],
}

def get_platform_id(console_name: str):
    name = console_name.lower().strip()
    for pid, aliases in RAWG_PLATFORM_ALIASES.items():
        if name in aliases:
            return pid
    return None

def get_platform_id_for_console(console_id: int) -> Optional[int]:
    """Get RAWG platform ID for a console by looking up the console name"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT name FROM consoles WHERE id = ?", (console_id,))
        result = cur.fetchone()
        conn.close()
        
        if not result:
            return None
            
        console_name = result[0]
        return get_platform_id(console_name)
    except Exception as e:
        logger.error(f"Failed to get platform ID for console {console_id}: {e}")
        return None

# -------------------------------------------------------------------
# Logging setup
# -------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Paths
# -------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "db", "game_vault.db")
COVERS_DIR = os.path.join(BASE_DIR, "covers")
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "screenshots")
METADATA_DIR = os.path.join(BASE_DIR, "metadata")
HEADERS_DIR = os.path.join(BASE_DIR, "headers")
THEME_DIR = os.path.join(BASE_DIR, "theme_images")

os.makedirs(COVERS_DIR, exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
os.makedirs(METADATA_DIR, exist_ok=True)
os.makedirs(HEADERS_DIR, exist_ok=True)
os.makedirs(THEME_DIR, exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# RAWG API configuration
# Get your free API key at: https://rawg.io/apidocs
# Leave empty to use DuckDuckGo only (no RAWG)
RAWG_BASE = "https://api.rawg.io/api"
RAWG_API_KEY = os.environ.get("RAWG_API_KEY", "")
RAWG_TIMEOUT = 15
WIKIPEDIA_TIMEOUT = 10

# Wikipedia API User-Agent to avoid 403 errors
WIKIPEDIA_HEADERS = {
    'User-Agent': 'GameArchive/1.0 (Educational Purpose; Contact: admin@example.com)'
}

# Standard cover size
COVER_WIDTH = 300
COVER_HEIGHT = 450

# -------------------------------------------------------------------
# Pydantic Models
# -------------------------------------------------------------------
class ConsoleBase(BaseModel):
    name: str
    path: Optional[str] = None  # Optional - can create console without path

class ConsoleResponse(ConsoleBase):
    id: int
    game_count: int = 0

    class Config:
        from_attributes = True

class ScreenshotResponse(BaseModel):
    id: int
    url: str

    class Config:
        from_attributes = True

class GameResponse(BaseModel):
    id: int
    folder_name: str
    title: str
    genre: Optional[str] = None
    description: Optional[str] = None
    cover_url: Optional[str] = None
    screenshots: List[ScreenshotResponse] = []

    class Config:
        from_attributes = True

class GameDetailResponse(GameResponse):
    metadata_json: Optional[str] = None
    created_at: str
    updated_at: str

class HealthResponse(BaseModel):
    status: str
    database: bool
    covers_dir: bool
    screenshots_dir: bool

class CoverFromUrlRequest(BaseModel):
    url: str

class ScreenshotFromUrlRequest(BaseModel):
    url: str

class GameUpdateRequest(BaseModel):
    title: str
    genre: Optional[str] = None
    description: Optional[str] = None

class AddSingleGameRequest(BaseModel):
    title: str

class AddBulkGamesRequest(BaseModel):
    games: List[str]

# New Pydantic Models for Status & Search
class GameStatusUpdate(BaseModel):
    is_favorite: Optional[bool] = None
    has_plan_to_play: Optional[bool] = None
    is_playing: Optional[bool] = None
    is_completed: Optional[bool] = None
    completed_date_note: Optional[str] = None
    is_dropped: Optional[bool] = None
    is_on_hold: Optional[bool] = None

class GameStatusResponse(BaseModel):
    game_id: int
    is_favorite: bool = False
    has_plan_to_play: bool = False
    is_playing: bool = False
    is_completed: bool = False
    completed_date_note: Optional[str] = None
    is_dropped: bool = False
    is_on_hold: bool = False

    class Config:
        from_attributes = True

class StatsResponse(BaseModel):
    total_consoles: int
    total_games: int
    completed_count: int
    favorites_count: int
    playing_count: int
    plan_to_play_count: int
    dropped_count: int
    on_hold_count: int

class SearchResultGame(BaseModel):
    id: int
    title: str
    genre: Optional[str] = None
    cover_url: Optional[str] = None
    console_name: str

    class Config:
        from_attributes = True

# -------------------------------------------------------------------
# FastAPI setup
# -------------------------------------------------------------------
app = FastAPI(title="Game Archive API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://192.168.1.3:3021",   # GitHub version test
        "http://192.168.1.6:3021",   # your laptop/phone
        "http://localhost:3021",
        "http://127.0.0.1:3021",
        "*"                          # fallback (optional)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Mount static directories
try:
    app.mount("/covers", StaticFiles(directory=COVERS_DIR), name="covers")
    app.mount("/screenshots", StaticFiles(directory=SCREENSHOTS_DIR), name="screenshots")
    app.mount("/headers", StaticFiles(directory=HEADERS_DIR), name="headers")
    app.mount("/theme_images", StaticFiles(directory=THEME_DIR), name="theme_images")
    logger.info("Static file serving configured successfully")
except Exception as e:
    logger.error(f"Failed to mount static files: {e}")

# -------------------------------------------------------------------
# DB helpers
# -------------------------------------------------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS consoles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            path TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            console_id INTEGER NOT NULL,
            folder_name TEXT NOT NULL,
            title TEXT NOT NULL,
            genre TEXT,
            description TEXT,
            cover_url TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(console_id, folder_name),
            FOREIGN KEY(console_id) REFERENCES consoles(id) ON DELETE CASCADE
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS screenshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS game_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL UNIQUE,
            is_favorite INTEGER DEFAULT 0,
            has_plan_to_play INTEGER DEFAULT 0,
            is_playing INTEGER DEFAULT 0,
            is_completed INTEGER DEFAULT 0,
            completed_date_note TEXT,
            is_dropped INTEGER DEFAULT 0,
            is_on_hold INTEGER DEFAULT 0,
            FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS recently_viewed (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL UNIQUE,
            viewed_at TEXT NOT NULL,
            FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE
        );
        """
    )

    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")

try:
    init_db()
except Exception as e:
    logger.error(f"Database initialization failed: {e}")

# -------------------------------------------------------------------
# Fetch functions
# -------------------------------------------------------------------
from pathlib import Path
import time

def search_steam_for_game(title: str) -> Optional[dict]:
    """Search Steam for a game and return its cover URL"""
    try:
        # Try exact title match first
        search_url = f"https://store.steampowered.com/api/v1/games/{title.lower().replace(' ', '%20')}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; GameArchive/1.0)',
        }
        
        response = requests.get(search_url, timeout=10, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if data.get("data") and len(data["data"]) > 0:
                game = data["data"][0]
                if game.get("header_image"):
                    return {
                        "cover_url": game["header_image"],
                        "source": "steam"
                    }
        return None
    except Exception as e:
        logger.warning(f"Steam search failed for {title}: {e}")
        return None

def is_game_file(filename: str) -> bool:
    """Check if a file is likely a game file based on extension"""
    game_extensions = {
        # Nintendo
        '.nsp', '.xci', '.nsz',  # Switch
        '.iso', '.cso', '.wbfs',  # Wii/GameCube
        '.wad',                   # WiiWare/Virtual Console
        '.nds', '.3ds', '.cia',   # DS/3DS
        '.gba', '.gbc', '.gb',    # Game Boy series
        '.snes', '.smc', '.nes',  # Nintendo classic
        
        # Sony
        '.iso', '.bin', '.cue', '.mdf',  # PlayStation
        '.pbp', '.cso',               # PSP
        
        # Microsoft
        '.iso', '.xex',              # Xbox
        '.cci', '.3ds',              # Xbox 360
        
        # Sega
        '.iso', '.bin', '.cue',      # Dreamcast
        '.smd', '.md', '.gen',       # Genesis
        
        # Atari
        '.a26', '.a52', '.a78',     # Atari systems
        
        # Commodore
        '.d64', '.crt', '.prg',     # C64
        
        # Archives (commonly used for ROMs)
        '.zip', '.rar', '.7z'
    }
    
    # Get file extension in lowercase
    _, ext = os.path.splitext(filename.lower())
    return ext in game_extensions

# -------------------------------------------------------------------
# Title normalization (aggressive cleaning for ROM filenames)
# -------------------------------------------------------------------

def normalize_title(raw: str) -> str:
    """
    Normalize game titles from folder names.
    Handles patterns like:
    - 13-Sentinels-Aegis-Rim-Base-Game-Switch-NSP
    - A-Short-Hike-Switch-NSP-Base-Game
    - Animal Crossing - New Horizons [FitGirl Repack]
    - ATELIER-ESCHA-AND-LOGY-ALCHEMISTS-OF-THE-DUSK-SKY-DX-NSP-ROMSLAB
    """
    if not raw:
        return raw
    
    cleaned = raw.strip()

    # Remove file extensions and common archive markers
    cleaned = re.sub(r'\.(nsp|xci|nsz|rar|zip|7z)$', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\.part\d+\.(rar|zip)$', '', cleaned, flags=re.IGNORECASE)

    # Remove bracketed/parenthesized content (scene tags, repacks, versions)
    cleaned = re.sub(r'\s*[\(\[\{].*?[\)\]\}]\s*', ' ', cleaned)

    # Remove common ROM/scene tags
    tags = [
        r'\bBase[- ]?Game\b',
        r'\b(?:Full[- ])?Game\b',
        r'\b(?:eShop|NSP|XCI|NSZ)\b',
        r'\b(?:ROMSLAB|FitGirl|Scene|Repack)\b',
        r'\bUpdate\b',
        r'\bDX\b',
        r'\bDefinitive[- ]?Edition\b',
        r'\bGOTY\b',
        r'\bSwitch\b',
        r'\b(?:EU|US|JP|Asia)\b',
        r'\brev\b',
        r'\bpatch\b',
        r'\bDLC\b',
        r'\bv\d+\.\d+(?:\.\d+)?\b',  # version numbers like v1.2.1
    ]
    for tag in tags:
        cleaned = re.sub(tag, '', cleaned, flags=re.IGNORECASE)

    # Replace hyphens, underscores, dots with spaces (but keep internal punctuation)
    cleaned = re.sub(r'[-_\.]+', ' ', cleaned)

    # Collapse multiple spaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # Capitalize properly
    cleaned = ' '.join(word.capitalize() for word in cleaned.split())

    return cleaned or raw

# -------------------------------------------------------------------
# Image helpers
# -------------------------------------------------------------------

def download_image(url: str) -> Optional[Image.Image]:
    """Download and convert image to RGB"""
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=RAWG_TIMEOUT)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        return img
    except Exception as e:
        logger.warning(f"Failed to download image from {url}: {e}")
        return None

def save_resized_cover(img: Image.Image, game_id: int) -> Optional[str]:
    """Resize cover to standard dimensions with dark border"""
    try:
        img = img.copy()
        img.thumbnail((COVER_WIDTH, COVER_HEIGHT), Image.LANCZOS)

        canvas = Image.new("RGB", (COVER_WIDTH, COVER_HEIGHT), (16, 16, 16))
        x = (COVER_WIDTH - img.width) // 2
        y = (COVER_HEIGHT - img.height) // 2
        canvas.paste(img, (x, y))

        path = os.path.join(COVERS_DIR, f"{game_id}.jpg")
        canvas.save(path, "JPEG", quality=90)

        # Add cache busting with timestamp
        timestamp = int(datetime.utcnow().timestamp())
        return f"/covers/{game_id}.jpg?t={timestamp}"
    except Exception as e:
        logger.error(f"Failed to save cover for game {game_id}: {e}")
        return None

def save_screenshot(img: Image.Image, game_id: int, index: int) -> Optional[str]:
    """Save screenshot at reduced resolution"""
    try:
        folder = os.path.join(SCREENSHOTS_DIR, str(game_id))
        os.makedirs(folder, exist_ok=True)

        img = img.copy()
        img.thumbnail((1280, 720), Image.LANCZOS)

        path = os.path.join(folder, f"{index}.jpg")
        img.save(path, "JPEG", quality=85)
        
        # Detailed logging for debugging
        final_url = f"/screenshots/{game_id}/{index}.jpg"
        logger.info(f"[SCREENSHOT_SAVE] game_id={game_id}, index={index}, path={path}, url={final_url}")

        return final_url
    except Exception as e:
        logger.error(f"Failed to save screenshot for game {game_id}: {e}")
        return None

def save_metadata_json(game_id: int, data: Optional[dict]) -> Optional[str]:
    """Save metadata to JSON file"""
    if not data:
        return None
    try:
        path = os.path.join(METADATA_DIR, f"{game_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return f"/metadata/{game_id}.json"
    except Exception as e:
        logger.error(f"Failed to save metadata for game {game_id}: {e}")
        return None

# -------------------------------------------------------------------
# RAWG API helpers
# -------------------------------------------------------------------

def is_rawg_configured() -> bool:
    """Check if RAWG API key is configured"""
    return bool(RAWG_API_KEY.strip())

def fetch_rawg_game(title: str, console_id: Optional[int] = None) -> Optional[dict]:
    """Search for a game on RAWG with platform filtering"""
    if not is_rawg_configured():
        logger.debug("RAWG API key not configured, skipping RAWG")
        return None
    
    try:
        url = f"{RAWG_BASE}/games"
        params = {
            "search": title,
            "page_size": 5,
            "key": RAWG_API_KEY,
        }
        
        platform_id = None
        if console_id:
            platform_id = get_platform_id_for_console(console_id)
            if platform_id:
                params["platforms"] = platform_id
        
        res = requests.get(url, params=params, timeout=RAWG_TIMEOUT)
        res.raise_for_status()
        data = res.json()

        if "results" not in data or not data["results"]:
            logger.debug(f"No RAWG results for: {title}")
            return None

        # If we filtered by platform, return the first result
        if platform_id:
            return data["results"][0]
        
        # If no platform filter, try to find best match by platform relevance
        return data["results"][0]
    except Exception as e:
        logger.warning(f"RAWG search failed for '{title}': {e}")
        return None

def fetch_rawg_screenshots(rawg_id: int, limit: int = 5) -> List[dict]:
    """Fetch screenshots for a game from RAWG"""
    try:
        url = f"{RAWG_BASE}/games/{rawg_id}/screenshots"
        params = {
            "page_size": limit,
            "key": RAWG_API_KEY,
        }
        res = requests.get(url, params=params, timeout=RAWG_TIMEOUT)
        res.raise_for_status()
        data = res.json()
        return data.get("results", [])
    except Exception as e:
        logger.warning(f"Failed to fetch screenshots for RAWG ID {rawg_id}: {e}")
        return []

# -------------------------------------------------------------------
# DuckDuckGo Image Search helpers
# -------------------------------------------------------------------

def fetch_duckduckgo_screenshots(title: str, console_name: str, limit: int = 5) -> List[str]:
    """Fetch landscape screenshots from DuckDuckGo for any console"""
    logger.info(f"[DUCKDUCKGO] Starting screenshot search for: {title} ({console_name})")
    import time
    
    # Try different backends
    backends = ["api", "html"]
    
    for backend in backends:
        try:
            from ddgs import DDGS
            ddgs = DDGS()
            
            query = f"{sanitize_query(title)} {sanitize_query(console_name)} screenshots"
            logger.info(f"[DUCKDUCKGO] Query: {query}, backend: {backend}")
            
            results = None
            try:
                results = list(ddgs.images(query, layout="Wide", max_results=10, backend=backend))
                logger.info(f"[DUCKDUCKGO] Got {len(results) if results else 0} raw results with {backend}")
            except Exception as e:
                logger.warning(f"[DUCKDUCKGO] {backend} failed: {e}")
                # Try without layout filter
                try:
                    results = list(ddgs.images(query, max_results=10, backend=backend))
                    logger.info(f"[DUCKDUCKGO] Retry without layout got {len(results) if results else 0} results")
                except Exception as e2:
                    logger.warning(f"[DUCKDUCKGO] {backend} retry also failed: {e2}")
                    continue
            
            if not results:
                logger.warning(f"[DUCKDUCKGO] No results returned for: {query}")
                continue
            
            large_urls = []
            small_urls = []
            
            for i, result in enumerate(results):
                logger.info(f"[DUCKDUCKGO] Result {i}: {result}")
                img_url = result.get("image") or result.get("thumbnail")
                if not img_url:
                    logger.info(f"[DUCKDUCKGO] Result {i} has no image URL")
                    continue
                
                try:
                    logger.info(f"[DUCKDUCKGO] Downloading: {img_url}")
                    time.sleep(0.3)
                    response = requests.get(img_url, timeout=10, headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    })
                    if response.status_code != 200:
                        logger.warning(f"[DUCKDUCKGO] HTTP {response.status_code} for {img_url}")
                        continue
                    
                    img = Image.open(BytesIO(response.content))
                    width, height = img.size
                    logger.info(f"[DUCKDUCKGO] Image size: {width}x{height}")
                    
                    if width <= height:
                        logger.info(f"[DUCKDUCKGO] Not landscape: {width}x{height}")
                        continue
                    
                    aspect_ratio = width / height
                    if aspect_ratio < 1.3 or aspect_ratio > 2.5:
                        logger.info(f"[DUCKDUCKGO] Aspect ratio not suitable: {aspect_ratio:.2f} ({width}x{height})")
                        continue
                    
                    is_large = width >= 640 and height >= 480 and width <= 1920
                    is_small = width >= 320 and height >= 240 and width <= 1920
                    
                    if not is_large and not is_small:
                        logger.info(f"[DUCKDUCKGO] Size too small: {width}x{height}")
                        continue
                    
                    if is_large:
                        large_urls.append(img_url)
                        logger.info(f"[DUCKDUCKGO] Valid LARGE screenshot: {width}x{height} (aspect: {aspect_ratio:.2f})")
                    else:
                        small_urls.append(img_url)
                        logger.info(f"[DUCKDUCKGO] Valid SMALL screenshot: {width}x{height} (aspect: {aspect_ratio:.2f})")
                    
                    if len(large_urls) >= limit:
                        break
                except Exception as e:
                    logger.error(f"[DUCKDUCKGO] Failed to verify screenshot: {e}")
                    continue
            
            valid_urls = large_urls[:limit]
            if len(valid_urls) < limit:
                needed = limit - len(valid_urls)
                valid_urls.extend(small_urls[:needed])
            
            if valid_urls:
                logger.info(f"[DUCKDUCKGO] Returning {len(valid_urls)} valid URLs (large: {len(large_urls)}, small: {len(small_urls)})")
                return valid_urls[:limit]
                
        except Exception as e:
            logger.warning(f"[DUCKDUCKGO] Backend {backend} failed: {e}")
            continue
    
    logger.error(f"[DUCKDUCKGO] All backends failed for '{title}'")
    return []

def fetch_duckduckgo_cover(title: str, console_name: str) -> Optional[str]:
    """Fetch portrait box cover from DuckDuckGo"""
    logger.info(f"[DUCKDUCKGO] Starting cover search for: {title} ({console_name})")
    import time
    
    # Try different backends
    backends = ["api", "html"]
    
    for backend in backends:
        try:
            from ddgs import DDGS
            ddgs = DDGS()
            
            query = f"{sanitize_query(title)} {sanitize_query(console_name)} box cover"
            logger.info(f"[DUCKDUCKGO] Query: {query}, backend: {backend}")
            
            results = None
            try:
                results = list(ddgs.images(query, layout="Tall", max_results=10, backend=backend))
                logger.info(f"[DUCKDUCKGO] Got {len(results) if results else 0} raw results with {backend}")
            except Exception as e:
                logger.warning(f"[DUCKDUCKGO] {backend} failed: {e}")
                # Try without layout filter
                try:
                    results = list(ddgs.images(query, max_results=10, backend=backend))
                    logger.info(f"[DUCKDUCKGO] Retry without layout got {len(results) if results else 0} results")
                except Exception as e2:
                    logger.warning(f"[DUCKDUCKGO] {backend} retry also failed: {e2}")
                    continue
            
            if not results:
                logger.warning(f"[DUCKDUCKGO] No results returned for: {query}")
                continue
            
            for i, result in enumerate(results):
                logger.info(f"[DUCKDUCKGO] Result {i}: {result}")
                img_url = result.get("image") or result.get("thumbnail")
                if not img_url:
                    logger.info(f"[DUCKDUCKGO] Result {i} has no image URL")
                    continue
                
                try:
                    logger.info(f"[DUCKDUCKGO] Downloading: {img_url}")
                    # Add delay to avoid rate limiting
                    time.sleep(0.3)
                    response = requests.get(img_url, timeout=10, headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    })
                    if response.status_code != 200:
                        logger.warning(f"[DUCKDUCKGO] HTTP {response.status_code} for {img_url}")
                        continue
                    
                    img = Image.open(BytesIO(response.content))
                    width, height = img.size
                    logger.info(f"[DUCKDUCKGO] Image size: {width}x{height}")
                    
                    if height > width:
                        logger.info(f"[DUCKDUCKGO] Valid portrait cover: {width}x{height}")
                        return img_url
                    else:
                        logger.info(f"[DUCKDUCKGO] Not portrait: {width}x{height}")
                except Exception as e:
                    logger.error(f"[DUCKDUCKGO] Failed to verify cover: {e}")
                    continue
            
            logger.warning(f"[DUCKDUCKGO] No valid portrait cover found with {backend}")
            continue
                    
        except Exception as e:
            logger.warning(f"[DUCKDUCKGO] Backend {backend} failed: {e}")
            continue
    
    logger.error(f"[DUCKDUCKGO] All backends failed for '{title}'")
    return None

# -------------------------------------------------------------------
# Wikipedia API helpers
# -------------------------------------------------------------------

def fetch_wikipedia_description(title: str, console_id: Optional[int] = None, strict: bool = True) -> Optional[str]:
    """Fetch full paragraph description from Wikipedia API with two-tier search"""
    try:
        # Try multiple search strategies
        search_queries = []
        
        # Add console-specific queries first
        if console_id:
            console_name = get_console_name_for_platform(console_id)
            if console_name:
                search_queries.append(f'"{title}" ({console_name} video game)')
                search_queries.append(f'"{title}" ({console_name})')
        
        # Add generic video game queries
        search_queries.append(f'"{title}" video game')
        search_queries.append(f'"{title}" (video game)')
        
        # Finally try plain title (least preferred)
        search_queries.append(f'"{title}"')
        
        search_url = "https://en.wikipedia.org/w/api.php"
        
        best_result = None
        for search_query in search_queries:
            logger.debug(f"Trying Wikipedia search: {search_query}")
            
            search_params = {
                "action": "query",
                "format": "json",
                "list": "search",
                "srsearch": search_query,
                "srlimit": 5,
                "redirects": 1,
                "utf8": 1
            }
            
            res = requests.get(search_url, params=search_params, timeout=WIKIPEDIA_TIMEOUT, headers=WIKIPEDIA_HEADERS)
            res.raise_for_status()
            data = res.json()
            
            if "query" not in data or "search" not in data["query"] or not data["query"]["search"]:
                continue
            
            search_results = data["query"]["search"]
            
            # Find best match with configurable strictness
            best_result = None
            for result in search_results:
                result_title = result["title"].lower()
                snippet = result.get("snippet", "").lower()
                
                if strict:
                    # STRICT FILTERS - skip wrong types
                    skip_patterns = ["(company)", "(manufacturer)", "(developer)", "(publisher)", 
                                  "(film)", "(movie)", "(band)", "(album)", "(novel)", 
                                  "(tv series)", "(mountain)"]
                    
                    if any(pattern in result_title for pattern in skip_patterns):
                        logger.debug(f"Skipping non-game page: {result['title']}")
                        continue
                    
                    # Skip company descriptions
                    if any(company_word in snippet for company_word in ["company", "founded", "headquartered", "manufacturer"]):
                        logger.debug(f"Skipping company page: {result['title']}")
                        continue
                    
                    # POSITIVE FILTERS - prefer clear game indicators  
                    has_game_indicators = ("video game" in snippet or 
                                        "game is a" in snippet or
                                        "gameplay" in snippet or
                                        "player controls" in snippet)
                else:
                    # RELAXED FILTERS - more permissive
                    # Only skip obvious non-game content
                    obvious_skips = ["(company)", "(manufacturer)", "(tv series)", "(album)", "(band)"]
                    if any(pattern in result_title for pattern in obvious_skips):
                        logger.debug(f"Skipping obvious non-game page: {result['title']}")
                        continue
                    
                    # More relaxed game indicators
                    has_game_indicators = ("video game" in snippet or 
                                        "game is a" in snippet or
                                        "gameplay" in snippet or
                                        "player controls" in snippet or
                                        "developed by" in snippet)
                
                # Title similarity check
                title_lower = title.lower().strip()
                result_title_clean = result["title"].lower()
                
                # Remove disambiguation for comparison
                for suffix in [" (video game)", " (game)", " (wii)", " (switch)"]:
                    result_title_clean = result_title_clean.replace(suffix, "")
                
                is_good_match = (title_lower == result_title_clean or 
                                title_lower in result_title_clean)
                
                if has_game_indicators and is_good_match:
                    best_result = result
                    logger.debug(f"Selected {'good' if strict else 'relaxed'} match: {result['title']}")
                    break
                elif best_result is None and is_good_match:
                    best_result = result
                    logger.debug(f"Selected fallback {'good' if strict else 'relaxed'} match: {result['title']}")
            
            if best_result:
                page_title = best_result["title"]
                break
        
        if not best_result:
            logger.debug(f"No suitable Wikipedia result found for: {title}")
            return None
        
        # Get page content - request more text for fuller description
        content_url = "https://en.wikipedia.org/w/api.php"
        content_params = {
            "action": "query",
            "format": "json",
            "prop": "extracts",
            "titles": page_title,
            "exintro": 1,
            "explaintext": 1,
            "utf8": 1
        }
        
        res = requests.get(content_url, params=content_params, timeout=WIKIPEDIA_TIMEOUT, headers=WIKIPEDIA_HEADERS)
        res.raise_for_status()
        data = res.json()
        
        if "query" not in data or "pages" not in data["query"]:
            return None
            
        page_id = next(iter(data["query"]["pages"]))
        extract = data["query"]["pages"][page_id].get("extract", "")
        
        if not extract or len(extract.strip()) < 20:
            return None
            
        # Clean up the extract but keep full paragraphs
        description = extract.strip()
        
        # Remove common Wikipedia prefixes
        description = re.sub(r'^(is a\s+)', '', description, flags=re.IGNORECASE)
        description = re.sub(r'^(are\s+)', '', description, flags=re.IGNORECASE)
        
        # Remove references like [1], [2]
        description = re.sub(r'\[\d+\]', '', description)
        
        # Remove sections that come after the main description
        for section in ["See also", "Reception", "Gameplay", "Development", "Plot", "Synopsis"]:
            if f"\n{section}" in description:
                description = description.split(f"\n{section}")[0].strip()
            elif f"{section}" in description:
                description = description.split(f"{section}")[0].strip()
        
        # Split into paragraphs and return the first substantial paragraph
        paragraphs = [p.strip() for p in description.split('\n\n') if p.strip()]
        
        if not paragraphs:
            return None
            
        # Use the first paragraph, but ensure it's substantial
        first_para = paragraphs[0]
        
        # If first paragraph is too short, try to combine with second
        if len(first_para) < 100 and len(paragraphs) > 1:
            first_para = first_para + " " + paragraphs[1]
        
        # Length limit - more generous now but still reasonable
        if len(first_para) > 800:
            # Try to end at sentence boundary
            sentences = first_para.split('. ')
            combined = '. '.join(sentences[:3])  # First 3 sentences
            if not combined.endswith('.'):
                combined += '.'
            return combined
        elif len(first_para) < 50:  # Too short, use fallback
            return None
            
        return first_para
        
    except Exception as e:
        logger.warning(f"Failed to fetch Wikipedia description for '{title}': {e}")
        return None

def get_console_name_for_platform(console_id: int) -> Optional[str]:
    """Get a clean console name for RAWG platform search"""
    console_names = {
        13: "GameCube",
        11: "Wii", 
        10: "Wii U",
        7: "Switch",
        15: "PlayStation 2",
        16: "PlayStation 3",
        18: "PlayStation 4",
        187: "PlayStation 5",
        14: "Xbox",
        17: "Xbox 360",
        1: "Xbox One",
        186: "Xbox Series X/S",
        9: "Nintendo DS",
        8: "Nintendo 3DS"
    }
    return console_names.get(console_id)
    """Get a clean console name for Wikipedia searches"""
    console_names = {
        13: "GameCube",
        11: "Wii", 
        10: "Wii U",
        7: "Switch",
        15: "PlayStation 2",
        16: "PlayStation 3",
        18: "PlayStation 4",
        187: "PlayStation 5",
        14: "Xbox",
        17: "Xbox 360",
        1: "Xbox One",
        186: "Xbox Series X/S",
        9: "Nintendo DS",
        8: "Nintendo 3DS"
    }
    return console_names.get(console_id)

# -------------------------------------------------------------------
# API: Health Check
# -------------------------------------------------------------------

@app.get("/api/health", response_model=HealthResponse)
def health_check():
    """Check API and system health"""
    try:
        conn = get_conn()
        conn.execute("SELECT 1")
        conn.close()
        db_ok = True
    except:
        db_ok = False

    return HealthResponse(
        status="ok" if db_ok else "degraded",
        database=db_ok,
        covers_dir=os.path.isdir(COVERS_DIR),
        screenshots_dir=os.path.isdir(SCREENSHOTS_DIR),
    )

# -------------------------------------------------------------------
# API: Consoles
# -------------------------------------------------------------------

@app.get("/api/consoles", response_model=List[ConsoleResponse])
def get_consoles():
    """List all consoles with game counts"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT c.id, c.name, c.path, COUNT(g.id) as game_count
            FROM consoles c
            LEFT JOIN games g ON c.id = g.console_id
            GROUP BY c.id
            ORDER BY c.name;
        """)
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to get consoles: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve consoles")

@app.post("/api/consoles", response_model=ConsoleResponse)
def add_console(console: ConsoleBase):
    """Add a new console"""
    try:
        if not console.name or not console.name.strip():
            raise HTTPException(status_code=400, detail="Console name cannot be empty")
        
        path = ""
        # Only validate path if provided
        if console.path and console.path.strip():
            path = os.path.abspath(console.path)
            logger.info(f"Validating console path: {path}")
            
            if not os.path.exists(path):
                logger.error(f"Path does not exist: {path}")
                raise HTTPException(status_code=400, detail=f"Folder path does not exist: {path}")
            
            if not os.path.isdir(path):
                logger.error(f"Path is not a directory: {path}")
                raise HTTPException(status_code=400, detail=f"Path is not a directory: {path}")

        conn = get_conn()
        cur = conn.cursor()
        now = datetime.utcnow().isoformat()
        
        try:
            cur.execute(
                "INSERT INTO consoles (name, path, created_at) VALUES (?, ?, ?);",
                (console.name.strip(), path, now),
            )
            cid = cur.lastrowid
            conn.commit()
            logger.info(f"Console added: {console.name}" + (f" at {path}" if path else " (empty console)"))
        except sqlite3.IntegrityError:
            conn.close()
            raise HTTPException(status_code=409, detail=f"Console '{console.name}' already exists")
        finally:
            conn.close()
        
        return ConsoleResponse(id=cid, name=console.name, path=path, game_count=0)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add console: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to add console: {str(e)}")

# -------------------------------------------------------------------
# API: Update console
# -------------------------------------------------------------------

@app.put("/api/consoles/{console_id}", response_model=ConsoleResponse)
def update_console(console_id: int, console: ConsoleBase):
    """Update a console's name"""
    try:
        if not console.name or not console.name.strip():
            raise HTTPException(status_code=400, detail="Console name cannot be empty")
        
        conn = get_conn()
        cur = conn.cursor()
        
        cur.execute("SELECT id, path FROM consoles WHERE id = ?;", (console_id,))
        existing = cur.fetchone()
        
        if not existing:
            conn.close()
            raise HTTPException(status_code=404, detail="Console not found")
        
        _, path = existing
        
        cur.execute(
            "UPDATE consoles SET name = ? WHERE id = ?;",
            (console.name.strip(), console_id),
        )
        conn.commit()
        
        cur.execute("SELECT COUNT(*) FROM games WHERE console_id = ?;", (console_id,))
        game_count = cur.fetchone()[0]
        
        conn.close()
        logger.info(f"Console updated: ID {console_id} -> {console.name}")
        
        return ConsoleResponse(id=console_id, name=console.name, path=path, game_count=game_count)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update console: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update console: {str(e)}")

# -------------------------------------------------------------------
# API: Scan console folder
# -------------------------------------------------------------------

@app.post("/api/consoles/{cid}/scan")
def scan_console(cid: int):
    """Scan console folder and add games to database"""
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT path FROM consoles WHERE id = ?;", (cid,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Console not found")

        path = row["path"]
        
        logger.info(f"Scanning console {cid} at path: {path}")
        
        if not os.path.isdir(path):
            logger.error(f"Console folder not found: {path}")
            raise HTTPException(status_code=400, detail="Console folder path is invalid or inaccessible")

        now = datetime.utcnow().isoformat()
        added = 0
        errors = 0
        skipped = 0

        try:
            entries = os.listdir(path)
        except PermissionError as e:
            logger.error(f"Permission denied reading {path}: {e}")
            raise HTTPException(status_code=403, detail=f"Permission denied accessing folder: {path}")
        except Exception as e:
            logger.error(f"Error listing directory {path}: {e}")
            raise HTTPException(status_code=400, detail=f"Error reading folder: {str(e)}")

        # Get existing normalized titles to avoid duplicates
        cur.execute("SELECT title FROM games WHERE console_id = ?", (cid,))
        existing_titles = set(row[0].lower().strip() for row in cur.fetchall())
        
        processed_names = {}  # normalized_name -> (original_name, is_directory)
        
        for entry in entries:
            full = os.path.join(path, entry)
            
            # Process both directories and game files
            if os.path.isdir(full):
                # It's a directory - treat as traditional game folder
                folder_name = entry
                title = normalize_title(entry)
                is_directory = True
            else:
                # It's a file - check if it's a game file
                if not is_game_file(entry):
                    skipped += 1
                    continue
                
                # Remove file extension for folder_name and title
                folder_name = os.path.splitext(entry)[0]
                title = normalize_title(folder_name)
                is_directory = False

            # Check for duplicates using normalized title
            normalized_title = title.lower().strip()
            
            if normalized_title in existing_titles:
                logger.debug(f"Skipping duplicate game: {title} (already exists)")
                skipped += 1
                continue
            
            # Check if we already processed a similar name (folder vs file conflict)
            if normalized_title in processed_names:
                # Prefer directories over files when there's a conflict
                existing_entry = processed_names[normalized_title]
                if existing_entry[1] and not is_directory:
                    # We already have a directory, skip this file
                    logger.debug(f"Skipping file in favor of directory: {entry} (conflict with {existing_entry[0]})")
                    skipped += 1
                    continue
                elif not existing_entry[1] and is_directory:
                    # We have a file but found a directory, replace the file entry
                    logger.debug(f"Preferring directory over file: {entry} (replacing {existing_entry[0]})")
                    # Note: We can't easily remove the already processed file entry in this loop,
                    # but INSERT OR IGNORE will handle the database level
                    # In practice, this case is rare since we process entries sequentially
                else:
                    # Same type, skip duplicate
                    logger.debug(f"Skipping duplicate: {entry} (conflict with {existing_entry[0]})")
                    skipped += 1
                    continue
            
            # Mark this name as processed
            processed_names[normalized_title] = (folder_name, is_directory)

            try:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO games
                        (console_id, folder_name, title, genre, description, cover_url,
                         metadata_json, created_at, updated_at)
                    VALUES (?, ?, ?, NULL, NULL, NULL, NULL, ?, ?);
                    """,
                    (cid, folder_name, title, now, now),
                )
                if cur.rowcount > 0:
                    added += 1
                    logger.debug(f"Added game: {title}")
            except Exception as e:
                logger.warning(f"Failed to add game {folder_name}: {e}")
                errors += 1

        conn.commit()
        conn.close()
        
        logger.info(f"Console {cid} scan complete: {added} added, {errors} errors, {skipped} files skipped")
        return {"status": "ok", "added": added, "errors": errors, "skipped": skipped}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to scan console {cid}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to scan console: {str(e)}")

# -------------------------------------------------------------------
# API: Add Single Game
# -------------------------------------------------------------------

def normalize_title_for_folder(title: str) -> str:
    """Convert title to folder_name format (filename-safe)"""
    import re
    folder = title.lower()
    folder = re.sub(r'[^\w\s-]', '', folder)  # Remove special chars except spaces and hyphens
    folder = re.sub(r'[\s]+', '_', folder)    # Replace spaces with underscores
    folder = folder.strip('_')
    return folder

@app.post("/api/consoles/{cid}/games")
def add_single_game(cid: int, data: AddSingleGameRequest):
    """Add a single game to a console"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Verify console exists
        cur.execute("SELECT id, name FROM consoles WHERE id = ?;", (cid,))
        console = cur.fetchone()
        if not console:
            conn.close()
            raise HTTPException(status_code=404, detail="Console not found")
        
        title = data.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="Title is required")
        
        folder_name = normalize_title_for_folder(title)
        now = datetime.utcnow().isoformat()
        
        cur.execute(
            """
            INSERT OR IGNORE INTO games
                (console_id, folder_name, title, genre, description, cover_url,
                 metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, NULL, NULL, NULL, NULL, ?, ?);
            """,
            (cid, folder_name, title, now, now),
        )
        
        conn.commit()
        added = cur.rowcount > 0
        conn.close()
        
        if added:
            logger.info(f"Added game: {title} to console {console['name']}")
            return {"status": "ok", "added": 1, "title": title}
        else:
            return {"status": "ok", "added": 0, "title": title, "message": "Game already exists"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add game: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to add game: {str(e)}")

# -------------------------------------------------------------------
# API: Add Bulk Games
# -------------------------------------------------------------------

@app.post("/api/consoles/{cid}/games/bulk")
def add_bulk_games(cid: int, data: AddBulkGamesRequest):
    """Add multiple games to a console"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Verify console exists
        cur.execute("SELECT id, name FROM consoles WHERE id = ?;", (cid,))
        console = cur.fetchone()
        if not console:
            conn.close()
            raise HTTPException(status_code=404, detail="Console not found")
        
        games = data.games
        if not games:
            raise HTTPException(status_code=400, detail="No games provided")
        
        now = datetime.utcnow().isoformat()
        added = 0
        skipped = 0
        
        for game_title in games:
            game_title = game_title.strip()
            if not game_title:
                continue
            
            folder_name = normalize_title_for_folder(game_title)
            
            cur.execute(
                """
                INSERT OR IGNORE INTO games
                    (console_id, folder_name, title, genre, description, cover_url,
                     metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, NULL, NULL, NULL, NULL, ?, ?);
                """,
                (cid, folder_name, game_title, now, now),
            )
            
            if cur.rowcount > 0:
                added += 1
            else:
                skipped += 1
        
        conn.commit()
        conn.close()
        
        logger.info(f"Bulk added {added} games to console {console['name']}, {skipped} skipped (already exist)")
        return {"status": "ok", "added": added, "skipped": skipped}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to bulk add games: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to bulk add games: {str(e)}")

# -------------------------------------------------------------------
# API: Games list
# -------------------------------------------------------------------

@app.get("/api/consoles/{cid}/games", response_model=List[GameResponse])
def get_games(cid: int):
    """Get all games for a console"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Verify console exists
        cur.execute("SELECT id FROM consoles WHERE id = ?;", (cid,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Console not found")
        
        cur.execute(
            """
            SELECT id, folder_name, title, genre, description, cover_url
            FROM games
            WHERE console_id = ?
            ORDER BY title;
            """,
            (cid,),
        )
        rows = cur.fetchall()

        # Load screenshots per game
        game_ids = [r["id"] for r in rows]
        screenshots_map = {gid: [] for gid in game_ids}
        
        if game_ids:
            cur.execute(
                f"""
                SELECT game_id, id, url
                FROM screenshots
                WHERE game_id IN ({",".join("?" for _ in game_ids)});
                """,
                game_ids,
            )
            for s in cur.fetchall():
                screenshots_map[s["game_id"]].append(ScreenshotResponse(id=s["id"], url=s["url"]))

        conn.close()

        result = []
        for r in rows:
            result.append(GameResponse(
                id=r["id"],
                folder_name=r["folder_name"],
                title=r["title"],
                genre=r["genre"] or "Unknown",
                description=r["description"] or "",
                cover_url=r["cover_url"],
                screenshots=screenshots_map.get(r["id"], []),
            ))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get games for console {cid}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve games")

# -------------------------------------------------------------------
# API: Global Search
# -------------------------------------------------------------------

@app.get("/api/games/search", response_model=List[SearchResultGame])
def search_games(q: str = Query(..., description="Search query")):
    """Search games across all consoles"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        search_term = f"%{q}%"
        cur.execute("""
            SELECT g.id, g.title, g.genre, g.cover_url, c.name as console_name
            FROM games g
            JOIN consoles c ON g.console_id = c.id
            WHERE g.title LIKE ?
            ORDER BY g.title
            LIMIT 50;
        """, (search_term,))
        
        rows = cur.fetchall()
        conn.close()
        
        return [SearchResultGame(
            id=r["id"],
            title=r["title"],
            genre=r["genre"],
            cover_url=r["cover_url"],
            console_name=r["console_name"]
        ) for r in rows]
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail="Search failed")

# -------------------------------------------------------------------
# API: Games by Status
# -------------------------------------------------------------------

@app.get("/api/games/by-status", response_model=List[SearchResultGame])
def get_all_games_by_status(status: str = Query(..., description="Status: favorite, playing, plan_to_play, completed, dropped, on_hold")):
    """Get ALL games across all consoles filtered by status"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        status_map = {
            "favorite": "is_favorite",
            "playing": "is_playing",
            "plan_to_play": "has_plan_to_play",
            "completed": "is_completed",
            "dropped": "is_dropped",
            "on_hold": "is_on_hold"
        }
        
        column = status_map.get(status)
        if not column:
            conn.close()
            raise HTTPException(status_code=400, detail="Invalid status")
        
        cur.execute(f"""
            SELECT g.id, g.title, g.genre, g.cover_url, c.name as console_name
            FROM games g
            JOIN consoles c ON g.console_id = c.id
            LEFT JOIN game_status gs ON g.id = gs.game_id
            WHERE COALESCE(gs.{column}, 0) = 1
            ORDER BY c.name, g.title;
        """)
        
        rows = cur.fetchall()
        conn.close()
        
        return [SearchResultGame(
            id=r["id"],
            title=r["title"],
            genre=r["genre"],
            cover_url=r["cover_url"],
            console_name=r["console_name"]
        ) for r in rows]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get all games by status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get games by status")


@app.get("/api/consoles/{console_id}/games/by-status", response_model=List[SearchResultGame])
def get_games_by_status(console_id: int, status: str = Query(..., description="Status: favorite, playing, plan_to_play, completed, dropped, on_hold")):
    """Get games for a console filtered by status"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Verify console exists
        cur.execute("SELECT id FROM consoles WHERE id = ?;", (console_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Console not found")
        
        # Map status to database column
        status_map = {
            "favorite": "is_favorite",
            "playing": "is_playing",
            "plan_to_play": "has_plan_to_play",
            "completed": "is_completed",
            "dropped": "is_dropped",
            "on_hold": "is_on_hold"
        }
        
        column = status_map.get(status)
        if not column:
            conn.close()
            raise HTTPException(status_code=400, detail="Invalid status")
        
        cur.execute(f"""
            SELECT g.id, g.title, g.genre, g.cover_url, c.name as console_name
            FROM games g
            JOIN consoles c ON g.console_id = c.id
            LEFT JOIN game_status gs ON g.id = gs.game_id
            WHERE g.console_id = ? AND COALESCE(gs.{column}, 0) = 1
            ORDER BY g.title;
        """, (console_id,))
        
        rows = cur.fetchall()
        conn.close()
        
        return [SearchResultGame(
            id=r["id"],
            title=r["title"],
            genre=r["genre"],
            cover_url=r["cover_url"],
            console_name=r["console_name"]
        ) for r in rows]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get games by status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get games by status")

@app.get("/api/games/{game_id}", response_model=GameDetailResponse)
def get_game_detail(game_id: int):
    """Get detailed information for a specific game"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        cur.execute(
            """
            SELECT id, folder_name, title, genre, description, cover_url, 
                   metadata_json, created_at, updated_at
            FROM games
            WHERE id = ?;
            """,
            (game_id,),
        )
        row = cur.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Game not found")
        
        # Get screenshots
        cur.execute("SELECT id, url FROM screenshots WHERE game_id = ? ORDER BY id;", (game_id,))
        screenshots = [ScreenshotResponse(id=s["id"], url=s["url"]) for s in cur.fetchall()]
        
        conn.close()
        
        return GameDetailResponse(
            id=row["id"],
            folder_name=row["folder_name"],
            title=row["title"],
            genre=row["genre"] or "Unknown",
            description=row["description"] or "",
            cover_url=row["cover_url"],
            screenshots=screenshots,
            metadata_json=row["metadata_json"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get game detail {game_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve game details")

# -------------------------------------------------------------------
# API: Fetch metadata from RAWG (Phase 2)
# -------------------------------------------------------------------

@app.post("/api/games/{game_id}/fetch-metadata")
def fetch_metadata_for_single_game(game_id: int):
    """Fetch text metadata for a single game"""
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Get game info
        cur.execute(
            """
            SELECT id, title, genre, description, console_id
            FROM games
            WHERE id = ?;
            """,
            (game_id,),
        )
        row = cur.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Game not found")

        gid = row["id"]
        title = row["title"]
        existing_genre = row["genre"]
        existing_desc = row["description"]
        console_id = row["console_id"]
        now = datetime.utcnow().isoformat()

        logger.info(f"Fetching metadata for single game: {title}")

        rawg_game = None
        meta_genre = None
        meta_desc = None

        if is_rawg_configured():
            rawg_game = fetch_rawg_game(title, console_id)
            if rawg_game:
                meta_genre = ", ".join(g["name"] for g in rawg_game.get("genres", []))
                logger.debug(f"Got RAWG data for {title}: genre={meta_genre}")
            else:
                logger.debug(f"No RAWG result for {title} (may need API key)")
        else:
            logger.debug(f"RAWG API key not configured, skipping RAWG")

        wiki_desc = fetch_wikipedia_description(title, console_id, strict=True)
        if not wiki_desc:
            logger.debug(f"Strict Wikipedia failed for {title}, trying relaxed search")
            wiki_desc = fetch_wikipedia_description(title, console_id, strict=False)

        if wiki_desc:
            wiki_para = wiki_desc
            
            if rawg_game:
                genres = [g["name"] for g in rawg_game.get("genres", [])]
                released = rawg_game.get("released", "")
                rating = rawg_game.get("rating", 0)
                
                hybrid_parts = [wiki_para]
                
                if genres and not any(genre.lower() in wiki_para.lower() for genre in genres):
                    genre_text = " and ".join(genres[:2])
                    hybrid_parts.append(f"A {genre_text.lower()} game")
                
                if released and not any(year in wiki_para for year in [released.split("-")[0]]):
                    year = released.split("-")[0]
                    hybrid_parts.append(f"Released in {year}")
                
                if rating and rating > 0 and str(rating) not in wiki_para:
                    hybrid_parts.append(f"(Rated {rating}/5)")
                
                full_hybrid = ". ".join(hybrid_parts)
                if len(full_hybrid) > 800:
                    meta_desc = wiki_para + ". " + ". ".join(hybrid_parts[1:])
                    if len(meta_desc) > 800:
                        meta_desc = meta_desc[:800] + "..."
                else:
                    meta_desc = full_hybrid
            else:
                meta_desc = wiki_para[:800] + "..." if len(wiki_para) > 800 else wiki_para
                
            logger.info(f"Using Wikipedia description for {title}")
        else:
            logger.debug(f"No Wikipedia description found for {title}")

        if not meta_desc and rawg_game:
            game_title = rawg_game.get("name", "")
            genres = [g["name"] for g in rawg_game.get("genres", [])]
            tags = [t["name"] for t in rawg_game.get("tags", [])]
            released = rawg_game.get("released", "")
            rating = rawg_game.get("rating", 0)
            
            desc_parts = []
            
            if game_title and released:
                year = released.split("-")[0]
                desc_parts.append(f"{game_title} ({year})")
            elif game_title:
                desc_parts.append(game_title)
            
            if genres:
                genre_text = " and ".join(genres[:3])
                desc_parts.append(f"is a {genre_text.lower()} game")
            
            if tags:
                notable_tags = [tag for tag in tags if tag.lower() not in ["exclusive", "multiplayer", "singleplayer"]][:2]
                if notable_tags:
                    desc_parts.append(f"featuring {', '.join(notable_tags).lower()}")
            
            if rating and rating > 0:
                desc_parts.append(f"(Rated {rating}/5)")
            
            meta_desc = ". ".join(desc_parts) + "."
            logger.info(f"Generated description from RAWG data for {title}")

        if meta_desc and len(meta_desc) > 800:
            meta_desc = meta_desc[:800] + "..."

        if not meta_genre and not meta_desc:
            raise HTTPException(status_code=404, detail="No metadata found for this game")

        new_genre = meta_genre or existing_genre
        new_desc = meta_desc or existing_desc

        local_meta = save_metadata_json(gid, rawg_game) if rawg_game else None

        # Update DB
        cur.execute(
            """
            UPDATE games
            SET
                genre = ?,
                description = ?,
                metadata_json = ?,
                updated_at = ?
            WHERE id = ?;
            """,
            (new_genre, new_desc, local_meta, now, gid),
        )

        conn.commit()
        conn.close()

        logger.info(f"Updated metadata for single game: {title}")
        return {"status": "ok", "updated": 1, "title": title, "description": new_desc}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch metadata for game {game_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch metadata")

@app.post("/api/games/{game_id}/fetch-screenshots")
def fetch_screenshots_for_game(game_id: int, source: str = Query("duckduckgo")):
    """Fetch and save screenshots for a single game, overwriting existing ones.
    source can be 'duckduckgo' or 'rawg'."""
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Get game info
        cur.execute("""
            SELECT g.id, g.title, g.console_id, c.name as console_name 
            FROM games g 
            JOIN consoles c ON g.console_id = c.id 
            WHERE g.id = ?;
        """, (game_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Game not found")

        gid = row["id"]
        title = row["title"]
        console_id = row["console_id"]
        console_name = row["console_name"]
        
        logger.info(f"[DEBUG] Single game screenshot - console: '{console_name}', source: '{source}'")

        # Delete existing screenshots
        cur.execute("DELETE FROM screenshots WHERE game_id = ?;", (gid,))
        
        # Delete old screenshot files
        screenshot_dir = Path(SCREENSHOTS_DIR) / str(gid)
        if screenshot_dir.exists():
            for f in screenshot_dir.glob("*.jpg"):
                f.unlink()

        if source == "duckduckgo":
            # Use DuckDuckGo with console name in query
            raw_screens = fetch_duckduckgo_screenshots(title, console_name, limit=5)
            if not raw_screens:
                raise HTTPException(status_code=404, detail="No DuckDuckGo screenshots found for this game")
            
            screenshots_urls = []
            index = 1
            for s_url in raw_screens:
                img = download_image(s_url)
                if not img:
                    continue
                local_s = save_screenshot(img, gid, index)
                if local_s:
                    screenshots_urls.append(local_s)
                    index += 1
            
            if not screenshots_urls:
                raise HTTPException(status_code=404, detail="Failed to download any screenshots")
        else:
            # Use RAWG for other consoles
            rawg_game = fetch_rawg_game(title, console_id)
            if not rawg_game:
                raise HTTPException(status_code=404, detail="No RAWG data found for this game")

            rawg_id = rawg_game.get("id")
            if not rawg_id:
                raise HTTPException(status_code=404, detail="No RAWG ID found for this game")

            # Fetch screenshots
            raw_screens = fetch_rawg_screenshots(rawg_id, limit=5)
            if not raw_screens:
                raise HTTPException(status_code=404, detail="No screenshots found for this game")

            # Create screenshot directory
            screenshot_dir.mkdir(parents=True, exist_ok=True)

            screenshots_urls = []
            index = 1
            for s in raw_screens:
                s_url = s.get("image")
                if not s_url:
                    continue
                img = download_image(s_url)
                if not img:
                    continue
                local_s = save_screenshot(img, gid, index)
                if local_s:
                    screenshots_urls.append(local_s)
                    index += 1

        # Insert into DB
        for url in screenshots_urls:
            cur.execute(
                "INSERT INTO screenshots (game_id, url) VALUES (?, ?);",
                (gid, url),
            )

        conn.commit()
        
        logger.info(f"Fetched {len(screenshots_urls)} screenshots for {title}")
        return {"status": "ok", "updated": len(screenshots_urls), "title": title}

    except HTTPException:
        if conn:
            conn.close()
        raise
    except Exception as e:
        logger.error(f"Failed to fetch screenshots for game {game_id}: {e}")
        if conn:
            conn.close()
        raise HTTPException(status_code=500, detail="Failed to fetch screenshots")
    finally:
        if conn:
            conn.close()

@app.post("/api/consoles/{cid}/fetch-metadata")
def fetch_metadata_for_console(cid: int, force: bool = Query(False)):
    """Fetch text metadata for console with smart filtering"""
    """Fetch text metadata ONLY for missing fields, without overwriting manual edits."""
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Validate console
        cur.execute("SELECT id FROM consoles WHERE id = ?;", (cid,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Console not found")

        # Fetch games for this console
        cur.execute(
            """
            SELECT id, title, genre, description
            FROM games
            WHERE console_id = ?
            ORDER BY title;
            """,
            (cid,),
        )
        rows = cur.fetchall()

        updated = 0
        skipped = 0
        now = datetime.utcnow().isoformat()

        for r in rows:
            gid = r["id"]
            title = r["title"]
            existing_genre = r["genre"]
            existing_desc = r["description"]

            # Smart processing: only update games without metadata unless force=True
            has_existing_metadata = (
                existing_genre and 
                existing_genre.lower() != "unknown" and
                existing_desc and 
                existing_desc.strip() and 
                len(existing_desc.strip()) > 20
            )
            
            if has_existing_metadata and not force:
                skipped += 1
                logger.debug(f"Skipping {title} - has existing metadata")
                continue
            
            if force:
                logger.info(f"Force updating metadata for {title}")

            rawg_game = None
            meta_genre = None
            meta_desc = None

            if is_rawg_configured():
                rawg_game = fetch_rawg_game(title, cid)
                if rawg_game:
                    meta_genre = ", ".join(g["name"] for g in rawg_game.get("genres", []))
                    logger.debug(f"Got RAWG data for {title}: genre={meta_genre}")
                else:
                    logger.debug(f"No RAWG result for {title}")
            else:
                logger.debug(f"RAWG API key not configured, skipping RAWG")

            wiki_desc = fetch_wikipedia_description(title, cid, strict=True)
            if not wiki_desc:
                logger.debug(f"Strict Wikipedia failed for {title}, trying relaxed search")
                wiki_desc = fetch_wikipedia_description(title, cid, strict=False)

            if wiki_desc:
                wiki_para = wiki_desc
                
                if rawg_game:
                    genres = [g["name"] for g in rawg_game.get("genres", [])]
                    released = rawg_game.get("released", "")
                    rating = rawg_game.get("rating", 0)
                    
                    hybrid_parts = [wiki_para]
                    
                    if genres and not any(genre.lower() in wiki_para.lower() for genre in genres):
                        genre_text = " and ".join(genres[:2])
                        hybrid_parts.append(f"A {genre_text.lower()} game")
                    
                    if released and not any(year in wiki_para for year in [released.split("-")[0]]):
                        year = released.split("-")[0]
                        hybrid_parts.append(f"Released in {year}")
                    
                    if rating and rating > 0 and str(rating) not in wiki_para:
                        hybrid_parts.append(f"(Rated {rating}/5)")
                    
                    full_hybrid = ". ".join(hybrid_parts)
                    if len(full_hybrid) > 800:
                        meta_desc = wiki_para + ". " + ". ".join(hybrid_parts[1:])
                        if len(meta_desc) > 800:
                            meta_desc = meta_desc[:800] + "..."
                    else:
                        meta_desc = full_hybrid
                else:
                    meta_desc = wiki_para[:800] + "..." if len(wiki_para) > 800 else wiki_para
                    
                logger.info(f"Using Wikipedia description for {title}")
            else:
                logger.debug(f"No Wikipedia description found for {title}")

            if not meta_desc and rawg_game:
                game_title = rawg_game.get("name", "")
                genres = [g["name"] for g in rawg_game.get("genres", [])]
                tags = [t["name"] for t in rawg_game.get("tags", [])]
                released = rawg_game.get("released", "")
                rating = rawg_game.get("rating", 0)
                
                desc_parts = []
                
                if game_title and released:
                    year = released.split("-")[0]
                    desc_parts.append(f"{game_title} ({year})")
                elif game_title:
                    desc_parts.append(game_title)
                
                if genres:
                    genre_text = " and ".join(genres[:3])
                    desc_parts.append(f"is a {genre_text.lower()} game")
                
                if tags:
                    notable_tags = [tag for tag in tags if tag.lower() not in ["exclusive", "multiplayer", "singleplayer"]][:2]
                    if notable_tags:
                        desc_parts.append(f"featuring {', '.join(notable_tags).lower()}")
                
                if rating and rating > 0:
                    desc_parts.append(f"(Rated {rating}/5)")
                
                meta_desc = ". ".join(desc_parts) + "."
                logger.info(f"Generated description from RAWG data for {title}")
                
                if not meta_desc or len(meta_desc.split()) < 3:
                    meta_desc = rawg_game.get("slug", "").replace("-", " ").title()
            
            if meta_desc and len(meta_desc) > 800:
                meta_desc = meta_desc[:800] + "..."

            if not meta_genre and not meta_desc:
                skipped += 1
                logger.debug(f"No metadata found for {title}")
                continue

            new_genre = meta_genre or existing_genre
            new_desc = meta_desc or existing_desc

            local_meta = save_metadata_json(gid, rawg_game) if rawg_game else None

            # Update DB
            cur.execute(
                """
                UPDATE games
                SET
                    genre = ?,
                    description = ?,
                    metadata_json = ?,
                    updated_at = ?
                WHERE id = ?;
                """,
                (new_genre, new_desc, local_meta, now, gid),
            )

            updated += 1
            logger.info(f"Updated metadata for {title}")

        conn.commit()
        conn.close()

        logger.info(f"Metadata updated for {updated} games in console {cid}, {skipped} skipped")
        return {"status": "ok", "updated": updated, "skipped": skipped}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch metadata: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch metadata")

@app.post("/api/consoles/{cid}/fetch-covers")
def fetch_covers_for_console(cid: int, force: bool = Query(False), source: str = Query("rawg")):
    """Fetch covers with console-specific folder structure. source can be 'rawg' or 'duckduckgo'"""
    logger.info(f"[DEBUG] fetch_covers called with cid={cid}, force={force}, source={source}")
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Get games for this console
        cur.execute(
            """
            SELECT id, title, genre, description, console_id, cover_url
            FROM games
            WHERE console_id = ?
            ORDER BY title;
            """,
            (cid,),
        )
        rows = cur.fetchall()
        
        if not rows:
            conn.close()
            raise HTTPException(status_code=404, detail="Console not found")
        
        total = len(rows)
        updated = 0
        skipped = 0
        
        logger.info(f"Fetching covers for {total} games in console {cid} (force={force}, source={source})")
        start = time.time()
        
        # Get console name for folder structure
        console_info = cur.execute("SELECT name FROM consoles WHERE id = ?", (cid,)).fetchone()
        console_name = console_info["name"] if console_info else "unknown"
        
        for game in rows:
            gid = game["id"]
            title = game["title"]
            existing_cover = game["cover_url"]
            
            # Skip if already has cover (unless force=true)
            if existing_cover and existing_cover.lower() != "null" and not force:
                logger.debug(f"Skipping {title} - already has cover")
                skipped += 1
                continue
            
            # Create console-specific folder structure
            safe_title = sanitize_filename(title)  # Remove special chars
            safe_console = console_name.lower().replace(" ", "_")
            cover_filename = f"{safe_console}/{safe_title}.jpg"
            cover_path = Path(COVERS_DIR) / cover_filename
            cover_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Fetch cover based on source
            cover_url = None
            try:
                if source == "duckduckgo":
                    cover_url = fetch_duckduckgo_cover(title, console_name)
                    if cover_url:
                        logger.info(f"Found DuckDuckGo cover for {title}")
                else:
                    rawg_game = fetch_rawg_game(title)
                    if rawg_game and rawg_game.get("background_image"):
                        cover_url = rawg_game["background_image"]
                        logger.info(f"Found RAWG cover for {title}")
            except Exception as e:
                logger.warning(f"Cover search failed for {title}: {e}")
            
            if cover_url:
                # Download and save cover
                try:
                    response = requests.get(cover_url, timeout=15)
                    if response.status_code == 200:
                        # Save the image
                        with open(cover_path, "wb") as f:
                            f.write(response.content)
                        logger.info(f"Saved cover: {cover_path}")
                        
                        # Update database with local path
                        local_meta = save_metadata_json(gid, {
                            "source": "downloaded",
                            "source_type": source,
                            "original_url": cover_url,
                        })
                        
                        cur.execute(
                            """
                            UPDATE games
                            SET cover_url = ?, metadata_json = ?
                            WHERE id = ?;
                            """,
                            (f"/covers/{cover_filename}", local_meta, gid),
                        )
                        
                        updated += 1
                        logger.info(f"Updated cover for {title}")
                    else:
                        logger.warning(f"Failed to download cover for {title}: HTTP {response.status_code}")
                except Exception as e:
                    logger.warning(f"Cover download failed for {title}: {e}")
            
            if not cover_url:
                skipped += 1
                logger.debug(f"No cover found for {title}")
        
        conn.commit()
        
        end = time.time()
        logger.info(f"Cover fetching completed in {end - start:.2f}s")
        
        return {"status": "ok", "updated": updated, "skipped": skipped}
        
    except Exception as e:
        logger.error(f"Failed to fetch covers: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch covers")

def sanitize_filename(title: str) -> str:
    """Sanitize title for filename"""
    import re
    # Remove special characters and replace with underscores
    safe = re.sub(r'[<>:"/\\|?*]', '_', title.strip())
    safe = re.sub(r'\s+', '_', safe)
    safe = safe.strip('_')
    return safe.lower()[:100]  # Limit length

def sanitize_query(title: str) -> str:
    """Remove punctuation for DuckDuckGo search queries"""
    import re
    # Remove punctuation that can affect search results
    safe = re.sub(r'[.,;:\!\'\"&]', '', title)
    safe = re.sub(r'\s+', ' ', safe)  # Normalize whitespace
    return safe.strip()

@app.post("/api/consoles/{cid}/fetch-screenshots")
def fetch_screenshots_for_console(cid: int, force: bool = Query(False), source: str = Query("duckduckgo")):
    """Fetch and save screenshots for games. Use force=true to re-fetch all, false for missing only.
    source can be 'duckduckgo' or 'rawg'."""
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id, name FROM consoles WHERE id = ?;", (cid,))
        console = cur.fetchone()
        if not console:
            raise HTTPException(status_code=404, detail="Console not found")
        
        console_name = console["name"]
        logger.info(f"[DEBUG] Console name: '{console_name}', source: '{source}'")
        
        # If force=true, delete existing screenshots first
        if force:
            cur.execute("DELETE FROM screenshots WHERE game_id IN (SELECT id FROM games WHERE console_id = ?);", (cid,))
            logger.info(f"Cleared existing screenshots for console {cid}")

        # Games with MISSING screenshots (smart fetching) or all games (force)
        if force:
            cur.execute(
                """
                SELECT id, title
                FROM games
                WHERE console_id = ?
                ORDER BY title;
                """,
                (cid,),
            )
        else:
            cur.execute(
                """
                SELECT g.id, g.title
                FROM games g
                LEFT JOIN screenshots s ON g.id = s.game_id
                WHERE g.console_id = ?
                GROUP BY g.id
                HAVING COUNT(s.id) = 0;
                """,
                (cid,),
            )
        rows = cur.fetchall()

        updated = 0
        skipped = 0
        now = datetime.utcnow().isoformat()

        logger.info(f"Fetching screenshots for {len(rows)} games in console {cid} using {source}")

        for r in rows:
            gid = r["id"]
            title = r["title"]

            if source == "duckduckgo":
                raw_screens = fetch_duckduckgo_screenshots(title, console_name, limit=5)
                if not raw_screens:
                    skipped += 1
                    continue
                
                screenshots_urls = []
                index = 1
                for s_url in raw_screens:
                    img = download_image(s_url)
                    if not img:
                        continue
                    local_s = save_screenshot(img, gid, index)
                    if local_s:
                        screenshots_urls.append(local_s)
                        index += 1
            else:
                rawg_game = fetch_rawg_game(title, cid)
                if not rawg_game:
                    skipped += 1
                    continue

                rawg_id = rawg_game.get("id")
                if not rawg_id:
                    skipped += 1
                    continue

                # Fetch screenshots
                raw_screens = fetch_rawg_screenshots(rawg_id, limit=5)
                if not raw_screens:
                    skipped += 1
                    continue

                screenshots_urls = []
                index = 1
                for s in raw_screens:
                    s_url = s.get("image")
                    if not s_url:
                        continue
                    img = download_image(s_url)
                    if not img:
                        continue
                    local_s = save_screenshot(img, gid, index)
                    if local_s:
                        screenshots_urls.append(local_s)
                        index += 1

            # Insert screenshots into DB
            if screenshots_urls:
                for url in screenshots_urls:
                    cur.execute(
                        "INSERT INTO screenshots (game_id, url) VALUES (?, ?);",
                        (gid, url),
                    )
                updated += 1
            else:
                skipped += 1

        conn.commit()
        conn.close()
        
        logger.info(f"Screenshots completed: {updated} fetched, {skipped} skipped")
        return {"status": "ok", "updated": updated, "skipped": skipped}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch screenshots: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch screenshots")

# -------------------------------------------------------------------
# API: Upload Cover Image
# -------------------------------------------------------------------

@app.post("/api/games/{game_id}/upload-cover")
async def upload_cover(game_id: int, file: UploadFile = File(...)):
    """Upload a cover image from disk"""
    try:
        # Verify game exists
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id FROM games WHERE id = ?;", (game_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Game not found")
        conn.close()

        # Ensure covers directory exists
        os.makedirs(COVERS_DIR, exist_ok=True)

        # Delete existing cover file if it exists
        existing_cover_path = os.path.join(COVERS_DIR, f"{game_id}.jpg")
        if os.path.exists(existing_cover_path):
            try:
                os.remove(existing_cover_path)
            except Exception as e:
                logger.warning(f"Could not delete existing cover: {e}")

        # Read and process image
        contents = await file.read()
        try:
            img = Image.open(BytesIO(contents)).convert("RGB")
        except Exception as e:
            logger.error(f"Failed to open image: {e}")
            raise HTTPException(status_code=400, detail="Invalid image file")

        # Save resized cover
        local_cover = save_resized_cover(img, game_id)
        if not local_cover:
            raise HTTPException(status_code=500, detail="Failed to save cover image")

        # Update database
        conn = get_conn()
        cur = conn.cursor()
        now = datetime.utcnow().isoformat()
        cur.execute(
            "UPDATE games SET cover_url = ?, updated_at = ? WHERE id = ?;",
            (local_cover, now, game_id),
        )
        conn.commit()
        conn.close()

        logger.info(f"Cover uploaded for game {game_id}")
        return {"status": "ok", "cover_url": local_cover}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload cover: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload cover")

@app.post("/api/games/{game_id}/cover-from-url")
def cover_from_url(game_id: int, data: CoverFromUrlRequest):
    """Save a cover from a URL"""
    try:
        # Verify game exists
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id FROM games WHERE id = ?;", (game_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Game not found")
        conn.close()

        # Ensure covers directory exists
        os.makedirs(COVERS_DIR, exist_ok=True)

        # Delete existing cover file if it exists
        existing_cover_path = os.path.join(COVERS_DIR, f"{game_id}.jpg")
        if os.path.exists(existing_cover_path):
            try:
                os.remove(existing_cover_path)
            except Exception as e:
                logger.warning(f"Could not delete existing cover: {e}")

        url = data.url
        if not url:
            raise HTTPException(status_code=400, detail="URL is required")

        # Download and process image
        img = download_image(url)
        if not img:
            raise HTTPException(status_code=400, detail="Failed to download image from URL")

        # Save resized cover
        local_cover = save_resized_cover(img, game_id)
        if not local_cover:
            raise HTTPException(status_code=500, detail="Failed to save cover image")

        # Update database
        conn = get_conn()
        cur = conn.cursor()
        now = datetime.utcnow().isoformat()
        cur.execute(
            "UPDATE games SET cover_url = ?, updated_at = ? WHERE id = ?;",
            (local_cover, now, game_id),
        )
        conn.commit()
        conn.close()

        logger.info(f"Cover set from URL for game {game_id}: {url}")
        return {"status": "ok", "cover_url": local_cover}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set cover from URL: {e}")
        raise HTTPException(status_code=500, detail="Failed to set cover from URL")

# -------------------------------------------------------------------
# API: Fetch Cover from DuckDuckGo
# -------------------------------------------------------------------

@app.post("/api/games/{game_id}/fetch-cover")
def fetch_cover_for_game(game_id: int):
    """Fetch a cover image from DuckDuckGo for a single game"""
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Get game info with console name
        cur.execute("""
            SELECT g.id, g.title, g.console_id, c.name as console_name 
            FROM games g 
            JOIN consoles c ON g.console_id = c.id 
            WHERE g.id = ?;
        """, (game_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Game not found")
        
        gid = row["id"]
        title = row["title"]
        console_name = row["console_name"]
        
        logger.info(f"[DUCKDUCKGO] Fetching cover for: {title} ({console_name})")
        
        # Fetch cover from DuckDuckGo
        cover_url = fetch_duckduckgo_cover(title, console_name)
        if not cover_url:
            raise HTTPException(status_code=404, detail="No cover found for this game")
        
        # Create console-specific folder structure
        safe_title = sanitize_filename(title)
        safe_console = console_name.lower().replace(" ", "_")
        cover_filename = f"{safe_console}/{safe_title}.jpg"
        cover_path = Path(COVERS_DIR) / cover_filename
        cover_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Download and save cover
        response = requests.get(cover_url, timeout=15)
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to download cover")
        
        with open(cover_path, "wb") as f:
            f.write(response.content)
        
        # Update database
        now = datetime.utcnow().isoformat()
        cur.execute(
            "UPDATE games SET cover_url = ?, updated_at = ? WHERE id = ?;",
            (f"/covers/{cover_filename}", now, gid),
        )
        conn.commit()
        
        logger.info(f"[DUCKDUCKGO] Cover saved for {title}: {cover_filename}")
        return {"status": "ok", "title": title, "cover_url": f"/covers/{cover_filename}"}
        
    except HTTPException:
        if conn:
            conn.close()
        raise
    except Exception as e:
        logger.error(f"Failed to fetch cover for game {game_id}: {e}")
        if conn:
            conn.close()
        raise HTTPException(status_code=500, detail="Failed to fetch cover")

# -------------------------------------------------------------------
# API: Update Game Details
# -------------------------------------------------------------------

@app.post("/api/games/{game_id}/update")
def update_game(game_id: int, data: GameUpdateRequest):
    """Update game title, genre, and description"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Verify game exists
        cur.execute("SELECT id FROM games WHERE id = ?;", (game_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Game not found")
        
        title = data.title.strip()
        genre = data.genre.strip() if data.genre else ""
        description = data.description.strip() if data.description else ""
        
        if not title:
            raise HTTPException(status_code=400, detail="Title is required")
        
        now = datetime.utcnow().isoformat()
        
        cur.execute(
            """
            UPDATE games
            SET title = ?, genre = ?, description = ?, updated_at = ?
            WHERE id = ?;
            """,
            (title, genre or None, description or None, now, game_id),
        )
        
        conn.commit()
        conn.close()
        
        logger.info(f"Game {game_id} updated: title={title}")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update game: {e}")
        raise HTTPException(status_code=500, detail="Failed to update game")

# -------------------------------------------------------------------
# -------------------------------------------------------------------
# Delete endpoints
# -------------------------------------------------------------------

@app.delete("/api/games/{game_id}")
async def delete_game(game_id: int):
    """Delete a game and all its associated files"""
    try:
        conn = get_conn()
        cursor = conn.cursor()
        
        # Get game info including console path and folder name
        cursor.execute("""
            SELECT g.console_id, g.folder_name, g.cover_url, c.path
            FROM games g
            JOIN consoles c ON g.console_id = c.id
            WHERE g.id = ?
        """, (game_id,))
        game = cursor.fetchone()
        
        if not game:
            conn.close()
            raise HTTPException(status_code=404, detail="Game not found")
        
        console_id, folder_name, cover_url, console_path = game
        
        # Delete screenshot files from filesystem
        cursor.execute("SELECT url FROM screenshots WHERE game_id = ?", (game_id,))
        screenshots = cursor.fetchall()
        
        for screenshot in screenshots:
            try:
                # Convert URL to filesystem path
                screenshot_url = screenshot[0]
                if screenshot_url.startswith("/screenshots/"):
                    screenshot_path = os.path.join(SCREENSHOTS_DIR, screenshot_url[12:])
                    if os.path.exists(screenshot_path):
                        os.remove(screenshot_path)
            except Exception as e:
                logger.warning(f"Failed to delete screenshot file: {e}")
        
        # Delete cover file if it exists
        if cover_url:
            try:
                if cover_url.startswith("/covers/"):
                    cover_path = os.path.join(COVERS_DIR, cover_url[8:])
                    # Remove cache busting query params
                    cover_path = cover_path.split('?')[0]
                    if os.path.exists(cover_path):
                        os.remove(cover_path)
            except Exception as e:
                logger.warning(f"Failed to delete cover file: {e}")
        
        # Delete game folder from filesystem
        try:
            game_folder_path = os.path.join(console_path, folder_name)
            if os.path.exists(game_folder_path):
                import shutil
                shutil.rmtree(game_folder_path)
                logger.info(f"Deleted game folder: {game_folder_path}")
        except Exception as e:
            logger.warning(f"Failed to delete game folder: {e}")
        
        # Delete from database (cascades will handle screenshots)
        cursor.execute("DELETE FROM games WHERE id = ?", (game_id,))
        
        conn.commit()
        conn.close()
        
        return {"status": "ok", "message": "Game and associated files deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete game: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete game")

@app.delete("/api/consoles/{console_id}")
async def delete_console(console_id: int):
    """Delete a console and all its games"""
    try:
        conn = get_conn()
        cursor = conn.cursor()
        
        # Get console info
        cursor.execute("SELECT name, path FROM consoles WHERE id = ?", (console_id,))
        console = cursor.fetchone()
        
        if not console:
            conn.close()
            raise HTTPException(status_code=404, detail="Console not found")
        
        console_name, console_path = console
        
        # Get all games for this console with their data
        cursor.execute("""
            SELECT id, folder_name, cover_url 
            FROM games 
            WHERE console_id = ?
        """, (console_id,))
        games = cursor.fetchall()
        
        # Delete all games and their files
        for game_id, folder_name, cover_url in games:
            # Delete screenshot files
            cursor.execute("SELECT url FROM screenshots WHERE game_id = ?", (game_id,))
            screenshots = cursor.fetchall()
            
            for screenshot in screenshots:
                try:
                    screenshot_url = screenshot[0]
                    if screenshot_url.startswith("/screenshots/"):
                        screenshot_path = os.path.join(SCREENSHOTS_DIR, screenshot_url[12:])
                        if os.path.exists(screenshot_path):
                            os.remove(screenshot_path)
                except Exception as e:
                    logger.warning(f"Failed to delete screenshot file: {e}")
            
            # Delete cover file
            if cover_url:
                try:
                    if cover_url.startswith("/covers/"):
                        cover_path = os.path.join(COVERS_DIR, cover_url[8:])
                        cover_path = cover_path.split('?')[0]
                        if os.path.exists(cover_path):
                            os.remove(cover_path)
                except Exception as e:
                    logger.warning(f"Failed to delete cover file: {e}")
            
            # Delete game folder
            try:
                game_folder_path = os.path.join(console_path, folder_name)
                if os.path.exists(game_folder_path):
                    import shutil
                    shutil.rmtree(game_folder_path)
            except Exception as e:
                logger.warning(f"Failed to delete game folder: {e}")
        
        # Delete from database (cascades will handle games and screenshots)
        cursor.execute("DELETE FROM consoles WHERE id = ?", (console_id,))
        
        conn.commit()
        conn.close()
        
        return {"status": "ok", "message": "Console and all associated games deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete console: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete console")

@app.delete("/api/games/{game_id}/cover")
async def delete_game_cover(game_id: int):
    """Delete a game's cover image"""
    try:
        conn = get_conn()
        cursor = conn.cursor()
        
        # Get cover URL
        cursor.execute("SELECT cover_url FROM games WHERE id = ?", (game_id,))
        game = cursor.fetchone()
        
        if not game:
            conn.close()
            raise HTTPException(status_code=404, detail="Game not found")
        
        cover_url = game[0]
        
        # Delete cover file
        if cover_url:
            try:
                if cover_url.startswith("/covers/"):
                    cover_path = os.path.join(COVERS_DIR, cover_url[8:])
                    cover_path = cover_path.split('?')[0]
                    if os.path.exists(cover_path):
                        os.remove(cover_path)
            except Exception as e:
                logger.warning(f"Failed to delete cover file: {e}")
        
        # Update database
        cursor.execute("UPDATE games SET cover_url = NULL WHERE id = ?", (game_id,))
        
        conn.commit()
        conn.close()
        
        return {"status": "ok", "message": "Cover deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete cover: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete cover")

@app.delete("/api/screenshots/{screenshot_id}")
async def delete_screenshot(screenshot_id: int):
    """Delete a specific screenshot"""
    try:
        conn = get_conn()
        cursor = conn.cursor()
        
        # Get screenshot URL
        cursor.execute("SELECT url FROM screenshots WHERE id = ?", (screenshot_id,))
        screenshot = cursor.fetchone()
        
        if not screenshot:
            conn.close()
            raise HTTPException(status_code=404, detail="Screenshot not found")
        
        screenshot_url = screenshot[0]
        
        # Delete file
        try:
            if screenshot_url.startswith("/screenshots/"):
                screenshot_path = os.path.join(SCREENSHOTS_DIR, screenshot_url[12:])
                if os.path.exists(screenshot_path):
                    os.remove(screenshot_path)
        except Exception as e:
            logger.warning(f"Failed to delete screenshot file: {e}")
        
        # Delete from database
        cursor.execute("DELETE FROM screenshots WHERE id = ?", (screenshot_id,))
        
        conn.commit()
        conn.close()
        
        return {"status": "ok", "message": "Screenshot deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete screenshot: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete screenshot")

# -------------------------------------------------------------------
# API: Add Screenshot Manually
# -------------------------------------------------------------------

MAX_SCREENSHOTS_PER_GAME = 5

@app.post("/api/games/{game_id}/upload-screenshot")
async def upload_screenshot(game_id: int, file: UploadFile = File(...)):
    """Upload a screenshot from disk"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        cur.execute("SELECT id FROM games WHERE id = ?;", (game_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Game not found")
        
        cur.execute("SELECT COUNT(*) FROM screenshots WHERE game_id = ?;", (game_id,))
        count = cur.fetchone()[0]
        conn.close()
        
        if count >= MAX_SCREENSHOTS_PER_GAME:
            raise HTTPException(status_code=400, detail=f"Maximum {MAX_SCREENSHOTS_PER_GAME} screenshots allowed per game")
        
        contents = await file.read()
        try:
            img = Image.open(BytesIO(contents)).convert("RGB")
        except Exception as e:
            logger.error(f"Failed to open image: {e}")
            raise HTTPException(status_code=400, detail="Invalid image file")
        
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM screenshots WHERE game_id = ?;", (game_id,))
        index = cur.fetchone()[0]
        
        local_screenshot = save_screenshot(img, game_id, index)
        if not local_screenshot:
            conn.close()
            raise HTTPException(status_code=500, detail="Failed to save screenshot")
        
        cur.execute(
            "INSERT INTO screenshots (game_id, url) VALUES (?, ?);",
            (game_id, local_screenshot),
        )
        conn.commit()
        screenshot_id = cur.lastrowid
        conn.close()
        
        logger.info(f"Screenshot uploaded for game {game_id}")
        return {"status": "ok", "screenshot_id": screenshot_id, "url": local_screenshot}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload screenshot: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload screenshot")

@app.post("/api/games/{game_id}/screenshot-from-url")
def screenshot_from_url(game_id: int, data: ScreenshotFromUrlRequest):
    """Add a screenshot from a URL"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        cur.execute("SELECT id FROM games WHERE id = ?;", (game_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Game not found")
        
        cur.execute("SELECT COUNT(*) FROM screenshots WHERE game_id = ?;", (game_id,))
        count = cur.fetchone()[0]
        
        if count >= MAX_SCREENSHOTS_PER_GAME:
            conn.close()
            raise HTTPException(status_code=400, detail=f"Maximum {MAX_SCREENSHOTS_PER_GAME} screenshots allowed per game")
        
        url = data.url
        if not url:
            conn.close()
            raise HTTPException(status_code=400, detail="URL is required")
        
        cur.execute("SELECT COUNT(*) FROM screenshots WHERE game_id = ?;", (game_id,))
        index = cur.fetchone()[0]
        conn.close()
        
        img = download_image(url)
        if not img:
            raise HTTPException(status_code=400, detail="Failed to download image from URL")
        
        local_screenshot = save_screenshot(img, game_id, index)
        if not local_screenshot:
            raise HTTPException(status_code=500, detail="Failed to save screenshot")
        
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO screenshots (game_id, url) VALUES (?, ?);",
            (game_id, local_screenshot),
        )
        conn.commit()
        screenshot_id = cur.lastrowid
        conn.close()
        
        logger.info(f"Screenshot added from URL for game {game_id}: {url}")
        return {"status": "ok", "screenshot_id": screenshot_id, "url": local_screenshot}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add screenshot from URL: {e}")
        raise HTTPException(status_code=500, detail="Failed to add screenshot from URL")

# -------------------------------------------------------------------
# API: Archive Stats
# -------------------------------------------------------------------

@app.get("/api/stats", response_model=StatsResponse)
def get_stats():
    """Get archive statistics"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Total consoles
        cur.execute("SELECT COUNT(*) as count FROM consoles")
        total_consoles = cur.fetchone()["count"]
        
        # Total games
        cur.execute("SELECT COUNT(*) as count FROM games")
        total_games = cur.fetchone()["count"]
        
        # Status counts (only count for games that actually exist)
        cur.execute("SELECT COUNT(*) as count FROM game_status gs JOIN games g ON gs.game_id = g.id WHERE gs.is_completed = 1")
        completed_count = cur.fetchone()["count"]
        
        cur.execute("SELECT COUNT(*) as count FROM game_status gs JOIN games g ON gs.game_id = g.id WHERE gs.is_favorite = 1")
        favorites_count = cur.fetchone()["count"]
        
        cur.execute("SELECT COUNT(*) as count FROM game_status gs JOIN games g ON gs.game_id = g.id WHERE gs.is_playing = 1")
        playing_count = cur.fetchone()["count"]
        
        cur.execute("SELECT COUNT(*) as count FROM game_status gs JOIN games g ON gs.game_id = g.id WHERE gs.has_plan_to_play = 1")
        plan_to_play_count = cur.fetchone()["count"]
        
        cur.execute("SELECT COUNT(*) as count FROM game_status gs JOIN games g ON gs.game_id = g.id WHERE gs.is_dropped = 1")
        dropped_count = cur.fetchone()["count"]
        
        cur.execute("SELECT COUNT(*) as count FROM game_status gs JOIN games g ON gs.game_id = g.id WHERE gs.is_on_hold = 1")
        on_hold_count = cur.fetchone()["count"]
        
        conn.close()
        
        return StatsResponse(
            total_consoles=total_consoles,
            total_games=total_games,
            completed_count=completed_count,
            favorites_count=favorites_count,
            playing_count=playing_count,
            plan_to_play_count=plan_to_play_count,
            dropped_count=dropped_count,
            on_hold_count=on_hold_count
        )
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get stats")


@app.get("/api/consoles/{console_id}/stats")
def get_console_stats(console_id: int):
    """Get status counts for a specific console"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        cur.execute("SELECT id, name FROM consoles WHERE id = ?;", (console_id,))
        console = cur.fetchone()
        if not console:
            conn.close()
            raise HTTPException(status_code=404, detail="Console not found")
        
        status_columns = [
            ("favorites_count", "is_favorite"),
            ("playing_count", "is_playing"),
            ("plan_to_play_count", "has_plan_to_play"),
            ("completed_count", "is_completed"),
            ("dropped_count", "is_dropped"),
            ("on_hold_count", "is_on_hold")
        ]
        
        result = {"console_id": console_id, "console_name": console["name"]}
        
        for key, column in status_columns:
            cur.execute(f"""
                SELECT COUNT(*) as count 
                FROM games g
                LEFT JOIN game_status gs ON g.id = gs.game_id
                WHERE g.console_id = ? AND COALESCE(gs.{column}, 0) = 1
            """, (console_id,))
            result[key] = cur.fetchone()["count"]
        
        conn.close()
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get console stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get console stats")

# -------------------------------------------------------------------
# API: Completed Games List
# -------------------------------------------------------------------

@app.get("/api/games/completed", response_model=List[SearchResultGame])
def get_completed_games():
    """Get list of completed games"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT g.id, g.title, g.genre, g.cover_url, c.name as console_name,
                   gs.completed_date_note
            FROM games g
            JOIN consoles c ON g.console_id = c.id
            JOIN game_status gs ON g.id = gs.game_id
            WHERE gs.is_completed = 1
            ORDER BY g.title;
        """)
        
        rows = cur.fetchall()
        conn.close()
        
        return [SearchResultGame(
            id=r["id"],
            title=r["title"],
            genre=r["genre"],
            cover_url=r["cover_url"],
            console_name=r["console_name"]
        ) for r in rows]
    except Exception as e:
        logger.error(f"Failed to get completed games: {e}")
        raise HTTPException(status_code=500, detail="Failed to get completed games")

# -------------------------------------------------------------------
# API: Game Status
# -------------------------------------------------------------------

@app.get("/api/games/{game_id}/status", response_model=GameStatusResponse)
def get_game_status(game_id: int):
    """Get status for a game"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Check if game exists
        cur.execute("SELECT id FROM games WHERE id = ?;", (game_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Game not found")
        
        # Get or create status
        cur.execute("SELECT * FROM game_status WHERE game_id = ?;", (game_id,))
        row = cur.fetchone()
        
        if not row:
            # Create default status
            cur.execute("INSERT INTO game_status (game_id) VALUES (?);", (game_id,))
            conn.commit()
            cur.execute("SELECT * FROM game_status WHERE game_id = ?;", (game_id,))
            row = cur.fetchone()
        
        conn.close()
        
        return GameStatusResponse(
            game_id=row["game_id"],
            is_favorite=bool(row["is_favorite"]),
            has_plan_to_play=bool(row["has_plan_to_play"]),
            is_playing=bool(row["is_playing"]),
            is_completed=bool(row["is_completed"]),
            completed_date_note=row["completed_date_note"],
            is_dropped=bool(row["is_dropped"]),
            is_on_hold=bool(row["is_on_hold"])
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get game status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get game status")

@app.post("/api/games/{game_id}/status")
def update_game_status(game_id: int, data: GameStatusUpdate):
    """Update game status"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Check if game exists
        cur.execute("SELECT id FROM games WHERE id = ?;", (game_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Game not found")
        
        # Check if status row exists
        cur.execute("SELECT id FROM game_status WHERE game_id = ?;", (game_id,))
        if not cur.fetchone():
            cur.execute("INSERT INTO game_status (game_id) VALUES (?);", (game_id,))
        
        # Build update query dynamically
        updates = []
        params = []
        
        if data.is_favorite is not None:
            updates.append("is_favorite = ?")
            params.append(1 if data.is_favorite else 0)
        if data.has_plan_to_play is not None:
            updates.append("has_plan_to_play = ?")
            params.append(1 if data.has_plan_to_play else 0)
        if data.is_playing is not None:
            updates.append("is_playing = ?")
            params.append(1 if data.is_playing else 0)
        if data.is_completed is not None:
            updates.append("is_completed = ?")
            params.append(1 if data.is_completed else 0)
        if data.completed_date_note is not None:
            updates.append("completed_date_note = ?")
            # Allow setting to empty string to clear the note, or set to the actual value
            params.append(data.completed_date_note)
        if data.is_dropped is not None:
            updates.append("is_dropped = ?")
            params.append(1 if data.is_dropped else 0)
        if data.is_on_hold is not None:
            updates.append("is_on_hold = ?")
            params.append(1 if data.is_on_hold else 0)
        
        if updates:
            params.append(game_id)
            cur.execute(
                f"UPDATE game_status SET {', '.join(updates)} WHERE game_id = ?;",
                params
            )
            conn.commit()
        
        conn.close()
        
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update game status: {e}")
        raise HTTPException(status_code=500, detail="Failed to update game status")

# -------------------------------------------------------------------
# API: Recently Viewed
# -------------------------------------------------------------------

@app.get("/api/recently-viewed")
def get_recently_viewed(limit: int = Query(5, ge=1, le=20)):
    """Get recently viewed games"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT g.id, g.title, g.genre, g.cover_url, c.name as console_name,
                   r.viewed_at
            FROM recently_viewed r
            JOIN games g ON r.game_id = g.id
            JOIN consoles c ON g.console_id = c.id
            ORDER BY r.viewed_at DESC
            LIMIT ?;
        """, (limit,))
        
        rows = cur.fetchall()
        conn.close()
        
        return [SearchResultGame(
            id=r["id"],
            title=r["title"],
            genre=r["genre"],
            cover_url=r["cover_url"],
            console_name=r["console_name"]
        ) for r in rows]
    except Exception as e:
        logger.error(f"Failed to get recently viewed: {e}")
        raise HTTPException(status_code=500, detail="Failed to get recently viewed")

# -------------------------------------------------------------------
# API: Recently Added Games
# -------------------------------------------------------------------

@app.get("/api/recently-added", response_model=List[SearchResultGame])
def get_recently_added(limit: int = Query(10, ge=1, le=50)):
    """Get most recently added games"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT g.id, g.title, g.genre, g.cover_url, c.name as console_name
            FROM games g
            JOIN consoles c ON g.console_id = c.id
            ORDER BY g.created_at DESC
            LIMIT ?
        """, (limit,))
        
        rows = cur.fetchall()
        conn.close()
        
        return [SearchResultGame(
            id=r["id"],
            title=r["title"],
            genre=r["genre"],
            cover_url=r["cover_url"],
            console_name=r["console_name"]
        ) for r in rows]
    except Exception as e:
        logger.error(f"Failed to get recently added: {e}")
        raise HTTPException(status_code=500, detail="Failed to get recently added games")

@app.post("/api/games/{game_id}/view")
def record_game_view(game_id: int):
    """Record that user viewed a game"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Check if game exists
        cur.execute("SELECT id FROM games WHERE id = ?;", (game_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Game not found")
        
        now = datetime.utcnow().isoformat()
        
        # Insert or update viewed timestamp
        cur.execute("""
            INSERT INTO recently_viewed (game_id, viewed_at)
            VALUES (?, ?)
            ON CONFLICT(game_id) DO UPDATE SET viewed_at = excluded.viewed_at;
        """, (game_id, now))
        
        conn.commit()
        conn.close()
        
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to record game view: {e}")
        raise HTTPException(status_code=500, detail="Failed to record game view")

# -------------------------------------------------------------------
# Theme/Header endpoints
# -------------------------------------------------------------------

@app.get("/api/theme/headers")
def get_theme_headers():
    """Get list of available header images"""
    try:
        headers = []
        for f in os.listdir(HEADERS_DIR):
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                headers.append(f)
        headers.sort()
        return {"headers": headers}
    except Exception as e:
        logger.error(f"Failed to list headers: {e}")
        return {"headers": []}


@app.get("/api/theme/header")
def get_theme_header():
    """Check if a custom header image exists"""
    for ext in ["png", "jpg", "jpeg", "gif", "webp"]:
        path = os.path.join(THEME_DIR, f"header.{ext}")
        if os.path.exists(path):
            return {"exists": True, "url": f"/theme_images/header.{ext}"}
    return {"exists": False}


@app.post("/api/theme/upload-header")
async def upload_theme_header(file: UploadFile = File(...)):
    """Upload a header image for the theme"""
    allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Invalid image type")
    
    ext = file.content_type.split("/")[-1]
    if ext == "jpeg":
        ext = "jpg"
    
    filename = f"header.{ext}"
    filepath = os.path.join(THEME_DIR, filename)
    
    for e in ["jpg", "jpeg", "png", "gif", "webp"]:
        old_path = os.path.join(THEME_DIR, f"header.{e}")
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception:
                pass
    
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 5MB)")
    
    with open(filepath, "wb") as f:
        f.write(contents)
    
    return {"status": "ok", "url": f"/theme_images/{filename}"}


@app.delete("/api/theme/header")
def delete_theme_header():
    """Delete the theme header image"""
    try:
        deleted = False
        for ext in ["png", "jpg", "jpeg", "gif", "webp"]:
            path = os.path.join(THEME_DIR, f"header.{ext}")
            if os.path.exists(path):
                os.remove(path)
                deleted = True
        return {"status": "ok", "deleted": deleted}
    except Exception as e:
        logger.error(f"Failed to delete theme header: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete theme header")

# -------------------------------------------------------------------
# Root endpoint
# -------------------------------------------------------------------

@app.get("/")
def root():
    """API root endpoint"""
    return {
        "message": "Game Archive API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/api/health"
    }

if __name__ == "__main__":
    import uvicorn
    import os
    
    # Configurable port via environment variable (default: 9001)
    port = int(os.environ.get("PORT", os.environ.get("BACKEND_PORT", 9001)))
    uvicorn.run(app, host="0.0.0.0", port=port)
