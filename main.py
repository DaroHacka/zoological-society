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
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import threading

# Serializes bulk fetch operations so only one runs at a time
FETCH_LOCK = threading.Lock()

# --- Console platform mappings live in console_catalog.py ---


def get_platform_id(console_name: str):
    """Resolve a console name to its RAWG platform id via the canonical catalog."""
    import console_catalog
    entry = console_catalog.find_by_name(console_name)
    if entry:
        return entry.rawg_id
    return None


def get_platform_id_for_console(console_id: int) -> Optional[int]:
    """Get RAWG platform ID for a console by slug (fallback: name lookup)."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT name, slug FROM consoles WHERE id = ?", (console_id,))
        result = cur.fetchone()
        conn.close()

        if not result:
            return None

        import console_catalog
        if result["slug"]:
            entry = console_catalog.get_by_slug(result["slug"])
            if entry:
                return entry.rawg_id
        return get_platform_id(result["name"])
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
DATA_DIR = "/srv/dev-disk-by-uuid-2856cdb9-5991-47dc-886b-1be20f8c2993/ArkVault/zoological society"
DB_PATH = os.path.join(BASE_DIR, "db", "game_vault.db")
COVERS_DIR = os.path.join(DATA_DIR, "covers")
SCREENSHOTS_DIR = os.path.join(DATA_DIR, "screenshots")
METADATA_DIR = os.path.join(DATA_DIR, "metadata")
HEADERS_DIR = os.path.join(DATA_DIR, "headers")
THEME_DIR = os.path.join(BASE_DIR, "theme_images")
ICONS_DIR = os.path.join(BASE_DIR, "console icons")

os.makedirs(COVERS_DIR, exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
os.makedirs(METADATA_DIR, exist_ok=True)
os.makedirs(HEADERS_DIR, exist_ok=True)
os.makedirs(THEME_DIR, exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# -------------------------------------------------------------------
# API providers configuration
# Keys are resolved in order: settings table (managed via web UI)
# -> environment variable -> .env file in project root.
# -------------------------------------------------------------------
RAWG_BASE = "https://api.rawg.io/api"
TGDB_BASE = "https://api.thegamesdb.net/v1"
RAWG_TIMEOUT = 15
WIKIPEDIA_TIMEOUT = 10
TGDB_TIMEOUT = 15


def _read_env_key(name: str) -> str:
    val = os.environ.get(name, "")
    if val:
        return val.strip()
    _env_path = os.path.join(BASE_DIR, ".env")
    if os.path.isfile(_env_path):
        try:
            with open(_env_path) as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line.startswith(f"{name}="):
                        return _line.split("=", 1)[1].strip().strip("\"'")
        except Exception:
            pass
    return ""


def get_setting(key: str, default: str = "") -> str:
    """Read a setting from the DB settings table, falling back to env/.env."""
    try:
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        finally:
            conn.close()
        if row and row["value"]:
            return str(row["value"])
    except Exception:
        pass
    env_val = _read_env_key(key.upper())
    return env_val or default


def set_setting(key: str, value: str):
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value;
            """,
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def delete_setting(key: str):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM settings WHERE key = ?;", (key,))
        conn.commit()
    finally:
        conn.close()

# Wikipedia API User-Agent to avoid 403 errors
WIKIPEDIA_HEADERS = {
    'User-Agent': 'GameArchive/1.0 (Educational Purpose; Contact: admin@example.com)'
}

# Standard cover size
COVER_WIDTH = 300
COVER_HEIGHT = 450

# Cancel mechanism
FETCH_CANCEL_FILE = os.path.join(BASE_DIR, ".fetch_cancel")


def set_fetch_cancel(cancel: bool):
    if cancel:
        with open(FETCH_CANCEL_FILE, "w") as f:
            f.write("1")
    else:
        if os.path.exists(FETCH_CANCEL_FILE):
            os.remove(FETCH_CANCEL_FILE)


def is_fetch_cancelled() -> bool:
    return os.path.exists(FETCH_CANCEL_FILE)


# -------------------------------------------------------------------
# Console icon auto-matching
# -------------------------------------------------------------------

def sanitize_for_match(text: str) -> str:
    """Lowercase, remove all non-alphanumeric characters."""
    return "".join(c for c in text.lower() if c.isalnum())

def match_console_icon(console_name: str) -> Optional[str]:
    """
    Find the best matching icon for a console using scored matching:

    1. Exact match (sanitized names equal)                   → score 30
    2. Console name is substring of icon name                → score 20
       (icon was named with the full console name)
    3. Icon name is substring of console name                → score 10
       (icon has a shorter/abbreviated name, e.g. 'psp.png'
        matching 'Sony PSP' since 'psp' is in 'sonypsp')

    Ties broken by shortest filename (most specific).
    Returns URL path like '/icons/nes.png' or None.
    """
    if not os.path.isdir(ICONS_DIR):
        return None

    supported = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    clean_name = sanitize_for_match(console_name)

    best_file = None
    best_score = -1

    for fname in os.listdir(ICONS_DIR):
        name, ext = os.path.splitext(fname)
        if ext.lower() not in supported:
            continue
        clean_icon = sanitize_for_match(name)

        if clean_name == clean_icon:
            score = 30
        elif clean_name in clean_icon:
            score = 20
        elif clean_icon in clean_name:
            score = 10
        else:
            continue

        if score > best_score:
            best_score = score
            best_file = fname
        elif score == best_score:
            # For exact/substring matches (20-30): shorter = more specific
            # For icon-in-console matches (10): longer = more specific
            if score >= 20:
                if len(fname) < len(best_file or ""):
                    best_file = fname
            else:
                if len(fname) > len(best_file or ""):
                    best_file = fname

    if best_file:
        return f"/icons/{best_file}"
    return None

# -------------------------------------------------------------------
# Pydantic Models
# -------------------------------------------------------------------
class ConsoleBase(BaseModel):
    name: str
    path: Optional[str] = None  # Optional - can create console without path
    slug: Optional[str] = None  # Canonical catalog identity (optional on input)

class ConsoleResponse(ConsoleBase):
    id: int
    game_count: int = 0
    icon_url: Optional[str] = None

    class Config:
        from_attributes = True

class ApiKeyRequest(BaseModel):
    key: str

class ConsolePairRequest(BaseModel):
    slug: str

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
    is_completed: bool = False
    is_printed: bool = False
    release_year: Optional[int] = None
    publisher: Optional[str] = None
    developer: Optional[str] = None

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
    notes: Optional[str] = None
    is_printed: Optional[bool] = None

class GameStatusResponse(BaseModel):
    game_id: int
    is_favorite: bool = False
    has_plan_to_play: bool = False
    is_playing: bool = False
    is_completed: bool = False
    completed_date_note: Optional[str] = None
    is_dropped: bool = False
    is_on_hold: bool = False
    notes: Optional[str] = None
    is_printed: bool = False

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
    is_completed: bool = False
    is_printed: bool = False
    release_year: Optional[int] = None
    publisher: Optional[str] = None
    developer: Optional[str] = None

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
    app.mount("/icons", StaticFiles(directory=ICONS_DIR), name="icons")
    logger.info("Static file serving configured successfully")
except Exception as e:
    logger.error(f"Failed to mount static files: {e}")

# -------------------------------------------------------------------
# API: Settings (API keys) & console catalog
# -------------------------------------------------------------------

def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 4:
        return "*" * len(key)
    return "*" * (len(key) - 4) + key[-4:]

@app.get("/api/settings/apikeys")
def get_api_keys():
    """Return masked API key status for UI display"""
    rawg = get_setting("rawg_api_key")
    tgdb = get_setting("tgdb_api_key")
    return {
        "rawg": {"configured": bool(rawg.strip()), "masked": _mask_key(rawg)},
        "tgdb": {"configured": bool(tgdb.strip()), "masked": _mask_key(tgdb)},
    }

@app.put("/api/settings/apikeys/{provider}")
def set_api_key(provider: str, body: ApiKeyRequest):
    provider = provider.lower()
    if provider not in ("rawg", "tgdb"):
        raise HTTPException(status_code=400, detail="Unknown provider")
    key = body.key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="Key cannot be empty")
    set_setting(f"{provider}_api_key", key)
    logger.info(f"API key updated for {provider}")
    return {"status": "ok", "provider": provider, "masked": _mask_key(key)}

@app.delete("/api/settings/apikeys/{provider}")
def remove_api_key(provider: str):
    provider = provider.lower()
    if provider not in ("rawg", "tgdb"):
        raise HTTPException(status_code=400, detail="Unknown provider")
    delete_setting(f"{provider}_api_key")
    logger.info(f"API key removed for {provider}")
    return {"status": "ok", "provider": provider}

class DefaultSourceRequest(BaseModel):
    cover_source: Optional[str] = None
    screenshot_source: Optional[str] = None

@app.get("/api/settings/default-source")
def get_default_source():
    """Return the default fetch sources for single-game operations"""
    return {
        "cover_source": get_setting("default_cover_source", "auto"),
        "screenshot_source": get_setting("default_screenshot_source", "auto"),
    }

@app.put("/api/settings/default-source")
def set_default_source(body: DefaultSourceRequest):
    """Set default fetch sources for single-game operations"""
    valid = ("auto", "duckduckgo", "tgdb", "rawg")
    if body.cover_source is not None:
        if body.cover_source not in valid:
            raise HTTPException(status_code=400, detail=f"Invalid source. Must be one of: {', '.join(valid)}")
        set_setting("default_cover_source", body.cover_source)
    if body.screenshot_source is not None:
        if body.screenshot_source not in valid:
            raise HTTPException(status_code=400, detail=f"Invalid source. Must be one of: {', '.join(valid)}")
        set_setting("default_screenshot_source", body.screenshot_source)
    return {"status": "ok"}

@app.get("/api/consoles/catalog")
def get_console_catalog():
    """Full canonical console catalog for the add-console picker"""
    import console_catalog
    return [e.to_dict() for e in console_catalog.all_entries()]


# -------------------------------------------------------------------
# DB helpers
# -------------------------------------------------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn

def _exec_write(cur, sql, params=(), retries: int = 3):
    """Execute a write statement with retry on 'database is locked'."""
    for attempt in range(retries):
        try:
            cur.execute(sql, params)
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < retries - 1:
                time.sleep(1)
                continue
            raise

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
            notes TEXT,
            is_printed INTEGER DEFAULT 0,
            FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE
        );
        """
    )

    # --- Migration: add notes and is_printed to game_status if missing ---
    gs_cols = [r[1] for r in cur.execute("PRAGMA table_info(game_status)").fetchall()]
    if "notes" not in gs_cols:
        cur.execute("ALTER TABLE game_status ADD COLUMN notes TEXT")
        logger.info("Migration: added game_status.notes column")
    if "is_printed" not in gs_cols:
        cur.execute("ALTER TABLE game_status ADD COLUMN is_printed INTEGER DEFAULT 0")
        logger.info("Migration: added game_status.is_printed column")

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

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS collection_games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collection_id INTEGER NOT NULL,
            game_id INTEGER NOT NULL,
            FOREIGN KEY(collection_id) REFERENCES collections(id) ON DELETE CASCADE,
            FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE,
            UNIQUE(collection_id, game_id)
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            genre TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS series_games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id INTEGER NOT NULL,
            game_id INTEGER,
            position INTEGER NOT NULL,
            title TEXT NOT NULL,
            cover_url TEXT,
            platform TEXT DEFAULT '',
            release_year INTEGER,
            rawg_id INTEGER,
            is_missing INTEGER DEFAULT 0,
            FOREIGN KEY(series_id) REFERENCES series(id) ON DELETE CASCADE,
            FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS series_cache (
            rawg_game_id INTEGER PRIMARY KEY,
            series_data TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )

    # --- Seed API keys from .env if DB is empty or env has a different value ---
    for env_name, db_key in [("RAWG_API_KEY", "rawg_api_key"), ("TGDB_API_KEY", "tgdb_api_key")]:
        env_val = _read_env_key(env_name)
        if env_val:
            row = cur.execute("SELECT value FROM settings WHERE key = ?", (db_key,)).fetchone()
            if not row or row["value"] != env_val:
                cur.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
                    (db_key, env_val),
                )
                logger.info(f"Seeded {db_key} from environment/.env")

    # --- Migration: add release_year, publisher, developer to games ---
    games_cols = [r[1] for r in cur.execute("PRAGMA table_info(games)").fetchall()]
    if "release_year" not in games_cols:
        cur.execute("ALTER TABLE games ADD COLUMN release_year INTEGER")
        logger.info("Migration: added games.release_year column")
    if "publisher" not in games_cols:
        cur.execute("ALTER TABLE games ADD COLUMN publisher TEXT")
        logger.info("Migration: added games.publisher column")
    if "developer" not in games_cols:
        cur.execute("ALTER TABLE games ADD COLUMN developer TEXT")
        logger.info("Migration: added games.developer column")

    # --- Backfill release_year/publisher/developer from metadata JSON files ---
    backfill_rows = cur.execute(
        "SELECT id, metadata_json FROM games WHERE release_year IS NULL AND metadata_json IS NOT NULL"
    ).fetchall()
    if backfill_rows:
        logger.info(f"Backfilling metadata for {len(backfill_rows)} games from JSON files...")
        backfilled = 0
        for row in backfill_rows:
            meta_path = row["metadata_json"]
            if not meta_path:
                continue
            meta_full = os.path.join(BASE_DIR, meta_path.lstrip("/"))
            if not os.path.isfile(meta_full):
                continue
            try:
                with open(meta_full) as f:
                    meta = json.load(f)
                release_year = None
                publisher = None
                developer = None
                released = meta.get("released", "")
                if released:
                    try:
                        release_year = int(released.split("-")[0])
                    except (ValueError, IndexError):
                        pass
                pubs = meta.get("publishers") or []
                if pubs:
                    publisher = ", ".join(p.get("name", "") for p in pubs if p.get("name"))
                devs = meta.get("developers") or []
                if devs:
                    developer = ", ".join(d.get("name", "") for d in devs if d.get("name"))
                if release_year or publisher or developer:
                    cur.execute(
                        "UPDATE games SET release_year = COALESCE(?, release_year), publisher = COALESCE(?, publisher), developer = COALESCE(?, developer) WHERE id = ?;",
                        (release_year, publisher, developer, row["id"]),
                    )
                    backfilled += 1
            except Exception:
                pass
        if backfilled:
            logger.info(f"Backfilled metadata for {backfilled} games")

    # --- Migration: consoles.slug column + pairing with canonical catalog ---
    existing_cols = [r[1] for r in cur.execute("PRAGMA table_info(consoles)").fetchall()]
    if "slug" not in existing_cols:
        cur.execute("ALTER TABLE consoles ADD COLUMN slug TEXT")
        logger.info("Migration: added consoles.slug column")

    try:
        import console_catalog
        for row in cur.execute("SELECT id, name, slug FROM consoles").fetchall():
            if row["slug"] and console_catalog.get_by_slug(row["slug"]):
                continue
            entry = console_catalog.find_by_name(row["name"])
            if entry:
                cur.execute(
                    "UPDATE consoles SET slug = ? WHERE id = ?;", (entry.slug, row["id"])
                )
                logger.info(f"Paired console '{row['name']}' -> {entry.slug}")
            else:
                logger.warning(f"No catalog match for console '{row['name']}' - leaving unpaired")
    except Exception as me:
        logger.warning(f"Console catalog pairing skipped: {me}")

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
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=RAWG_TIMEOUT)
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
    return bool(get_setting("rawg_api_key").strip())

def fetch_rawg_game(title: str, console_id: Optional[int] = None,
                    strict_platform: bool = False) -> Optional[dict]:
    """Search for a game on RAWG with platform filtering.

    strict_platform=True (used for cover art) refuses unfiltered results:
    when the console has no RAWG platform mapping, returns None instead of
    risking a wrong-platform game.
    """
    rawg_key = get_setting("rawg_api_key")
    if not rawg_key.strip():
        logger.debug("RAWG API key not configured, skipping RAWG")
        return None

    try:
        url = f"{RAWG_BASE}/games"
        params = {
            "search": title,
            "page_size": 5,
            "key": rawg_key,
        }

        platform_id = None
        if console_id:
            platform_id = get_platform_id_for_console(console_id)
            if platform_id:
                params["platforms"] = platform_id
            elif strict_platform:
                logger.debug(f"No RAWG platform mapping for console {console_id}, skipping")
                return None

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
            "key": get_setting("rawg_api_key"),
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

class DDGRateLimited(Exception):
    """Raised when DuckDuckGo throttles/blocks us - callers should back off
    or fall back to another provider instead of hammering."""
    pass


def _ddgs_images(query: str, **kwargs) -> list:
    """Single entry point for DDGS image searches.

    Uses the only backend supported by ddgs>=9 ('duckduckgo'), detects
    rate limiting and raises DDGRateLimited so callers fail fast instead
    of firing retry storms that extend the block.
    """
    from ddgs import DDGS
    from ddgs.exceptions import RatelimitException
    try:
        return list(DDGS().images(query, backend="duckduckgo", **kwargs))
    except RatelimitException as e:
        logger.warning(f"[DUCKDUCKGO] Rate limited by DuckDuckGo: {e}")
        raise DDGRateLimited(str(e)) from e


def fetch_duckduckgo_screenshots(title: str, console_name: str, limit: int = 5) -> List[str]:
    """Fetch landscape screenshots from DuckDuckGo for any console"""
    logger.info(f"[DUCKDUCKGO] Starting screenshot search for: {title} ({console_name})")
    import time

    query = f"{sanitize_query(title)} {sanitize_query(console_name)} screenshots"
    logger.info(f"[DUCKDUCKGO] Query: {query}")

    results = None
    try:
        results = _ddgs_images(query, layout="Wide", max_results=10)
        logger.info(f"[DUCKDUCKGO] Got {len(results) if results else 0} raw results")
    except DDGRateLimited:
        raise
    except Exception as e:
        logger.warning(f"[DUCKDUCKGO] Search failed: {e}")
        # Retry once without layout filter
        try:
            results = _ddgs_images(query, max_results=10)
            logger.info(f"[DUCKDUCKGO] Retry without layout got {len(results) if results else 0} results")
        except DDGRateLimited:
            raise
        except Exception as e2:
            logger.warning(f"[DUCKDUCKGO] Retry also failed: {e2}")
            return []

    if not results:
        logger.warning(f"[DUCKDUCKGO] No results returned for: {query}")
        return []

    large_urls = []
    small_urls = []

    for i, result in enumerate(results):
        img_url = result.get("image") or result.get("thumbnail")
        if not img_url:
            continue

        try:
            time.sleep(0.3)
            response = requests.get(img_url, timeout=10, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            if response.status_code != 200:
                continue

            img = Image.open(BytesIO(response.content))
            width, height = img.size
            logger.info(f"[DUCKDUCKGO] Result {i}: {width}x{height}")

            if width <= height:
                continue

            aspect_ratio = width / height
            if aspect_ratio < 1.3 or aspect_ratio > 2.5:
                continue

            is_large = width >= 640 and height >= 480 and width <= 1920
            is_small = width >= 320 and height >= 240 and width <= 1920

            if not is_large and not is_small:
                continue

            if is_large:
                large_urls.append(img_url)
            else:
                small_urls.append(img_url)

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

    logger.error(f"[DUCKDUCKGO] No valid screenshots found for '{title}'")
    return []

def fetch_duckduckgo_cover(title: str, console_name: str) -> Optional[str]:
    """Fetch portrait box cover from DuckDuckGo"""
    logger.info(f"[DUCKDUCKGO] Starting cover search for: {title} ({console_name})")
    import time

    query = f"{sanitize_query(title)} {sanitize_query(console_name)} box cover"
    logger.info(f"[DUCKDUCKGO] Query: {query}")

    results = None
    try:
        results = _ddgs_images(query, layout="Tall", max_results=10)
        logger.info(f"[DUCKDUCKGO] Got {len(results) if results else 0} raw results")
    except DDGRateLimited:
        raise
    except Exception as e:
        logger.warning(f"[DUCKDUCKGO] Search failed: {e}")
        # Retry once without layout filter
        try:
            results = _ddgs_images(query, max_results=10)
            logger.info(f"[DUCKDUCKGO] Retry without layout got {len(results) if results else 0} results")
        except DDGRateLimited:
            raise
        except Exception as e2:
            logger.warning(f"[DUCKDUCKGO] Retry also failed: {e2}")
            return None

    if not results:
        logger.warning(f"[DUCKDUCKGO] No results returned for: {query}")
        return None

    for i, result in enumerate(results):
        img_url = result.get("image") or result.get("thumbnail")
        if not img_url:
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
            logger.info(f"[DUCKDUCKGO] Result {i}: {width}x{height}")

            if height > width:
                logger.info(f"[DUCKDUCKGO] Valid portrait cover: {width}x{height}")
                return img_url
        except Exception as e:
            logger.error(f"[DUCKDUCKGO] Failed to verify cover: {e}")
            continue

    logger.error(f"[DUCKDUCKGO] No valid portrait cover found for '{title}'")
    return None

# -------------------------------------------------------------------
# TheGamesDB helpers
# -------------------------------------------------------------------

def _tgdb_platform_id(console_name: str) -> Optional[int]:
    import console_catalog
    entry = console_catalog.find_by_name(console_name)
    if entry:
        return entry.tgdb_id
    return None


def _tgdb_platform_id_for_console(console_id: int) -> Optional[int]:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT name, slug FROM consoles WHERE id = ?", (console_id,))
        result = cur.fetchone()
        conn.close()
        if not result:
            return None
        import console_catalog
        if result["slug"]:
            entry = console_catalog.get_by_slug(result["slug"])
            if entry:
                return entry.tgdb_id
        return _tgdb_platform_id(result["name"])
    except Exception as e:
        logger.error(f"Failed to get TGDB platform ID for console {console_id}: {e}")
        return None


def is_tgdb_configured() -> bool:
    return bool(get_setting("tgdb_api_key").strip())


_tgdb_last_call = 0.0
_TGDB_MIN_INTERVAL = 1.0  # seconds between TGDB API requests


def _tgdb_search_games(title: str, platform_id: Optional[int]):
    """Search TheGamesDB; returns (games, include) or (None, None).

    Platform filtering uses the documented `filter[platform]` param and
    boxart is requested via `include=boxart` (returned top-level under
    payload["include"]["boxart"]).
    """
    global _tgdb_last_call
    elapsed = time.time() - _tgdb_last_call
    if elapsed < _TGDB_MIN_INTERVAL:
        time.sleep(_TGDB_MIN_INTERVAL - elapsed)

    api_key = get_setting("tgdb_api_key")
    if not api_key:
        return None, None
    params = {
        "apikey": api_key,
        "name": title,
        "page_size": 5,
        "include": "boxart",
    }
    if platform_id:
        params["filter[platform]"] = str(platform_id)
    res = requests.get(f"{TGDB_BASE}/Games/ByGameName", params=params,
                       timeout=TGDB_TIMEOUT)
    _tgdb_last_call = time.time()
    res.raise_for_status()
    payload = res.json()
    status = payload.get("status")
    if payload.get("code") not in (200, None) or (
        status and str(status).lower() != "success"
    ):
        raise RuntimeError(f"TGDB error: code={payload.get('code')} status={status}")
    data = payload.get("data") or {}
    include = payload.get("include") or {}
    return data.get("games") or [], include


def _tgdb_image_url(base_url, img) -> str:
    if isinstance(base_url, dict):
        base = base_url.get("original") or base_url.get("1x") or ""
        for v in base_url.values():
            if v:
                base = base or v
                break
    else:
        base = base_url or ""
    return f"{base}{img.get('filename', '')}"


def _parse_resolution(resolution) -> tuple:
    """'640x480' -> (640, 480); falls back to (0, 0)."""
    try:
        w, h = str(resolution).lower().split("x")
        return int(w), int(h)
    except Exception:
        return 0, 0


def fetch_tgdb_cover(title: str, console_id: int, console_name: str = "") -> Optional[str]:
    """Fetch a portrait front box art URL from TheGamesDB."""
    if not is_tgdb_configured():
        logger.debug("TheGamesDB API key not configured, skipping TGDB")
        return None

    platform_id = _tgdb_platform_id_for_console(console_id) if console_id else \
        (_tgdb_platform_id(console_name) if console_name else None)
    if console_id and not platform_id:
        logger.debug(f"No TGDB platform mapping for console {console_id}, skipping")
        return None

    try:
        games, include = _tgdb_search_games(title, platform_id)
        if not games:
            logger.info(f"[TGDB] No results for '{title}'")
            return None

        boxart = (include.get("boxart") or {})
        base_url = boxart.get("base_url") or {}
        art_by_game = boxart.get("data") or {}

        best_url, best_area = None, 0
        fallback_url = None
        for game in games:
            gid = str(game.get("id"))
            images = art_by_game.get(gid) or []
            fronts = [im for im in images
                      if im.get("type") == "boxart" and im.get("side") == "front"]
            for im in fronts:
                url = _tgdb_image_url(base_url, im)
                if not url:
                    continue
                w, h = _parse_resolution(im.get("resolution"))
                if w and h and h > w:
                    # Prefer true portrait box art, largest area wins
                    if h * w > best_area:
                        best_area = h * w
                        best_url = url
                elif fallback_url is None:
                    # Unknown-resolution or square/cropped front art still
                    # beats having no cover at all
                    fallback_url = url

        if not best_url:
            best_url = fallback_url
        if best_url:
            logger.info(f"[TGDB] Found cover for '{title}': {best_url}")
        else:
            logger.info(f"[TGDB] No portrait front boxart for '{title}'")
        return best_url
    except Exception as e:
        logger.warning(f"[TGDB] Cover search failed for '{title}': {e}")
        return None


def _tgdb_game_screenshots(game_ids: List[int], limit: int = 5) -> List[dict]:
    """Fetch screenshot image records for TGDB game ids via /v1/Games/Images."""
    global _tgdb_last_call
    elapsed = time.time() - _tgdb_last_call
    if elapsed < _TGDB_MIN_INTERVAL:
        time.sleep(_TGDB_MIN_INTERVAL - elapsed)

    api_key = get_setting("tgdb_api_key")
    if not api_key or not game_ids:
        return []
    params = {
        "apikey": api_key,
        "games_id": ",".join(str(g) for g in game_ids),
        "filter[type]": "screenshot",
    }
    res = requests.get(f"{TGDB_BASE}/Games/Images", params=params,
                       timeout=TGDB_TIMEOUT)
    _tgdb_last_call = time.time()
    res.raise_for_status()
    payload = res.json()
    status = payload.get("status")
    if payload.get("code") not in (200, None) or (
        status and str(status).lower() != "success"
    ):
        raise RuntimeError(f"TGDB error: code={payload.get('code')} status={status}")
    data = payload.get("data") or {}
    base_url = data.get("base_url") or {}
    # images are grouped by game id: {"8185": [ {filename...}, ... ]}
    grouped = data.get("images") or {}
    out = []
    for images in grouped.values():
        for im in images:
            url = _tgdb_image_url(base_url, im)
            if url:
                w, h = _parse_resolution(im.get("resolution"))
                out.append((w * h, url))
    out.sort(key=lambda t: t[0], reverse=True)
    return [u for _, u in out[:limit]]


def fetch_tgdb_screenshots(title: str, console_id: int, console_name: str = "",
                           limit: int = 5) -> List[str]:
    """Fetch screenshot URLs from TheGamesDB."""
    if not is_tgdb_configured():
        logger.debug("TheGamesDB API key not configured, skipping TGDB")
        return []

    platform_id = _tgdb_platform_id_for_console(console_id) if console_id else \
        (_tgdb_platform_id(console_name) if console_name else None)
    if console_id and not platform_id:
        logger.debug(f"No TGDB platform mapping for console {console_id}, skipping")
        return []

    try:
        games, _include = _tgdb_search_games(title, platform_id)
        if not games:
            logger.info(f"[TGDB] No results for '{title}'")
            return []

        # Prefer exact-title matches to avoid cross-game screenshots
        wanted = title.strip().lower()
        exact = [g for g in games
                 if str(g.get("game_title", "")).strip().lower() == wanted]
        chosen = (exact or games)[:3]

        urls = _tgdb_game_screenshots([g["id"] for g in chosen], limit=limit)
        logger.info(f"[TGDB] Returning {len(urls)} screenshots for '{title}'")
        return urls
    except Exception as e:
        logger.warning(f"[TGDB] Screenshot search failed for '{title}': {e}")
        return []


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
            SELECT c.id, c.name, c.path, c.slug, COUNT(g.id) as game_count
            FROM consoles c
            LEFT JOIN games g ON c.id = g.console_id
            GROUP BY c.id
            ORDER BY c.name;
        """)
        rows = cur.fetchall()
        conn.close()

        result = []
        for r in rows:
            item = dict(r)
            item["icon_url"] = match_console_icon(item["name"])
            result.append(item)
        return result
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

        # Resolve canonical slug: explicit slug wins, else auto-pair by name
        import console_catalog as _cc
        slug = None
        if console.slug and console.slug.strip():
            slug = console.slug.strip()
            if not _cc.get_by_slug(slug):
                raise HTTPException(status_code=400,
                                    detail=f"Unknown console catalog slug: {slug}")
        else:
            entry = _cc.find_by_name(console.name)
            if entry:
                slug = entry.slug

        try:
            cur.execute(
                "INSERT INTO consoles (name, path, created_at, slug) VALUES (?, ?, ?, ?);",
                (console.name.strip(), path, now, slug),
            )
            cid = cur.lastrowid
            conn.commit()
            logger.info(f"Console added: {console.name}" + (f" at {path}" if path else " (empty console)"))
        except sqlite3.IntegrityError:
            conn.close()
            raise HTTPException(status_code=409, detail=f"Console '{console.name}' already exists")
        finally:
            conn.close()
        
        icon_url = match_console_icon(console.name)
        return ConsoleResponse(id=cid, name=console.name, path=path, slug=slug, game_count=0, icon_url=icon_url)
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
    """Update a console's display name (slug / canonical identity unchanged)"""
    try:
        if not console.name or not console.name.strip():
            raise HTTPException(status_code=400, detail="Console name cannot be empty")

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id, path, slug FROM consoles WHERE id = ?;", (console_id,))
        existing = cur.fetchone()

        if not existing:
            conn.close()
            raise HTTPException(status_code=404, detail="Console not found")

        _, path, current_slug = existing
        
        cur.execute(
            "UPDATE consoles SET name = ? WHERE id = ?;",
            (console.name.strip(), console_id),
        )
        conn.commit()
        
        cur.execute("SELECT COUNT(*) FROM games WHERE console_id = ?;", (console_id,))
        game_count = cur.fetchone()[0]
        
        conn.close()
        logger.info(f"Console updated: ID {console_id} -> {console.name}")
        
        icon_url = match_console_icon(console.name)
        return ConsoleResponse(id=console_id, name=console.name, path=path,
                               slug=current_slug, game_count=game_count, icon_url=icon_url)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update console: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update console: {str(e)}")

@app.post("/api/consoles/{console_id}/pair")
def pair_console(console_id: int, body: ConsolePairRequest):
    """Manually pair a console with a canonical catalog entry"""
    import console_catalog as _cc
    entry = _cc.get_by_slug(body.slug.strip())
    if not entry:
        raise HTTPException(status_code=400,
                            detail=f"Unknown console catalog slug: {body.slug}")
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id FROM consoles WHERE id = ?;", (console_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Console not found")
        cur.execute("UPDATE consoles SET slug = ? WHERE id = ?;",
                    (entry.slug, console_id))
        conn.commit()
        cur.execute("SELECT name, path FROM consoles WHERE id = ?;", (console_id,))
        row = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM games WHERE console_id = ?;", (console_id,))
        game_count = cur.fetchone()[0]
        conn.close()
        logger.info(f"Console {console_id} paired with catalog entry '{entry.slug}'")
        icon_url = match_console_icon(row["name"])
        return ConsoleResponse(id=console_id, name=row["name"], path=row["path"],
                               slug=entry.slug, game_count=game_count, icon_url=icon_url)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to pair console: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to pair console: {str(e)}")

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
            SELECT g.id, g.folder_name, g.title, g.genre, g.description, g.cover_url,
                   COALESCE(gs.is_completed, 0) as is_completed,
                   COALESCE(gs.is_printed, 0) as is_printed
            FROM games g
            LEFT JOIN game_status gs ON g.id = gs.game_id
            WHERE g.console_id = ?
            ORDER BY g.title;
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
                is_completed=bool(r["is_completed"]),
                is_printed=bool(r["is_printed"]),
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
            SELECT g.id, g.title, g.genre, g.cover_url, c.name as console_name,
                   g.release_year, g.publisher, g.developer
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
            console_name=r["console_name"],
            release_year=r["release_year"],
            publisher=r["publisher"],
            developer=r["developer"],
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
            SELECT g.id, g.title, g.genre, g.cover_url, c.name as console_name,
                   COALESCE(gs.is_completed, 0) as is_completed,
                   COALESCE(gs.is_printed, 0) as is_printed,
                   g.release_year, g.publisher, g.developer
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
            console_name=r["console_name"],
            is_completed=bool(r["is_completed"]),
            is_printed=bool(r["is_printed"]),
            release_year=r["release_year"],
            publisher=r["publisher"],
            developer=r["developer"],
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
            SELECT g.id, g.title, g.genre, g.cover_url, c.name as console_name,
                   COALESCE(gs.is_completed, 0) as is_completed,
                   COALESCE(gs.is_printed, 0) as is_printed,
                   g.release_year, g.publisher, g.developer
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
            console_name=r["console_name"],
            is_completed=bool(r["is_completed"]),
            is_printed=bool(r["is_printed"]),
            release_year=r["release_year"],
            publisher=r["publisher"],
            developer=r["developer"],
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
                   metadata_json, created_at, updated_at,
                   release_year, publisher, developer
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
            release_year=row["release_year"],
            publisher=row["publisher"],
            developer=row["developer"],
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
                meta_genre = ", ".join(g["name"] for g in rawg_game.get("genres") or [])
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
                genres = [g["name"] for g in rawg_game.get("genres") or []]
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
            genres = [g["name"] for g in rawg_game.get("genres") or []]
            tags = [t["name"] for t in rawg_game.get("tags") or []]
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

        # Extract publisher/developer/release_year from RAWG data (smart: only fill NULLs)
        new_release_year = None
        new_publisher = None
        new_developer = None
        if rawg_game:
            released = rawg_game.get("released", "")
            if released:
                try:
                    new_release_year = int(released.split("-")[0])
                except (ValueError, IndexError):
                    pass
            pubs = rawg_game.get("publishers") or []
            if pubs:
                new_publisher = ", ".join(p.get("name", "") for p in pubs if p.get("name"))
            devs = rawg_game.get("developers") or []
            if devs:
                new_developer = ", ".join(d.get("name", "") for d in devs if d.get("name"))

        # Update DB (smart: only overwrite NULL fields)
        cur.execute(
            """
            UPDATE games
            SET
                genre = ?,
                description = ?,
                metadata_json = ?,
                release_year = COALESCE(?, release_year),
                publisher = COALESCE(?, publisher),
                developer = COALESCE(?, developer),
                updated_at = ?
            WHERE id = ?;
            """,
            (new_genre, new_desc, local_meta, new_release_year, new_publisher, new_developer, now, gid),
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
    source can be 'duckduckgo', 'rawg' or 'tgdb'.
    The DB connection is NOT held during network work to avoid lock contention."""
    # 0) Read game info + clear old rows, then release the connection
    conn = get_conn()
    try:
        cur = conn.cursor()
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

        _exec_write(cur, "DELETE FROM screenshots WHERE game_id = ?;", (gid,))
        conn.commit()
    finally:
        conn.close()

    logger.info(f"[DEBUG] Single game screenshot - console: '{console_name}', source: '{source}'")

    # Delete old screenshot files (no DB connection needed)
    screenshot_dir = Path(SCREENSHOTS_DIR) / str(gid)
    if screenshot_dir.exists():
        for f in screenshot_dir.glob("*.jpg"):
            f.unlink()

    screenshots_urls = []
    ddg_rate_limited = False

    # 1) Try DuckDuckGo first (unless TGDB or RAWG explicitly selected)
    if source not in ("tgdb", "rawg"):
        try:
            raw_screens = fetch_duckduckgo_screenshots(title, console_name, limit=5)
            if raw_screens:
                index = 1
                for s_url in raw_screens:
                    img = download_image(s_url)
                    if not img:
                        continue
                    local_s = save_screenshot(img, gid, index)
                    if local_s:
                        screenshots_urls.append(local_s)
                        index += 1
        except DDGRateLimited:
            ddg_rate_limited = True
            logger.warning(f"DuckDuckGo rate limited during screenshot search for {title}")
        except Exception as e:
            logger.warning(f"DuckDuckGo failed for {title}: {e}")

    # 2) TheGamesDB (explicit selection or fallback from DuckDuckGo)
    if not screenshots_urls and source in ("duckduckgo", "tgdb") and is_tgdb_configured():
        try:
            tgdb_urls = fetch_tgdb_screenshots(title, console_id, console_name, limit=5)
            if tgdb_urls:
                screenshot_dir.mkdir(parents=True, exist_ok=True)
                index = 1
                for s_url in tgdb_urls:
                    img = download_image(s_url)
                    if not img:
                        continue
                    local_s = save_screenshot(img, gid, index)
                    if local_s:
                        screenshots_urls.append(local_s)
                        index += 1
        except Exception as e:
            logger.warning(f"TheGamesDB failed for {title}: {e}")

    # 3) Fall back to RAWG
    if not screenshots_urls and source in ("duckduckgo", "rawg") and is_rawg_configured():
        try:
            rawg_game = fetch_rawg_game(title, console_id)
            if rawg_game:
                rawg_id = rawg_game.get("id")
                if rawg_id:
                    raw_screens = fetch_rawg_screenshots(rawg_id, limit=5)
                    if raw_screens:
                        screenshot_dir.mkdir(parents=True, exist_ok=True)
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
        except Exception as e:
            logger.warning(f"RAWG failed for {title}: {e}")

    # 4) Error if all sources failed
    if not screenshots_urls:
        if ddg_rate_limited:
            raise HTTPException(
                status_code=429,
                detail="DuckDuckGo is rate-limiting this IP and no other provider had screenshots. Try again later.",
            )
        raise HTTPException(status_code=404, detail="No screenshots found from any source")

    # 5) Brief write window: reopen connection just for the inserts
    conn = get_conn()
    try:
        cur = conn.cursor()
        for url in screenshots_urls:
            _exec_write(cur,
                "INSERT INTO screenshots (game_id, url) VALUES (?, ?);",
                (gid, url),
            )
        conn.commit()
    finally:
        conn.close()

    logger.info(f"Fetched {len(screenshots_urls)} screenshots for {title}")
    return {"status": "ok", "updated": len(screenshots_urls), "title": title}

@app.post("/api/consoles/{cid}/fetch-metadata")
def fetch_metadata_for_console(cid: int, force: bool = Query(False), letter: str = Query(None), batch_commit: int = Query(50)):
    """Fetch text metadata for console with smart filtering.
    letter can be A-Z or 0-9 to filter by starting letter.
    batch_commit is the number of games to process before committing (default 50)."""
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Validate console
        cur.execute("SELECT id, name FROM consoles WHERE id = ?;", (cid,))
        console = cur.fetchone()
        if not console:
            raise HTTPException(status_code=404, detail="Console not found")
        
        console_name = console["name"]

        # Build query with optional letter filter
        query = """
            SELECT id, title, genre, description
            FROM games
            WHERE console_id = ?
        """
        params = [cid]
        
        if letter:
            if letter == "0":
                query += " AND title GLOB '[0-9]*'"
            else:
                query += " AND title LIKE ?"
                params.append(f"{letter}%")
        
        query += " ORDER BY title;"
        
        cur.execute(query, params)
        rows = cur.fetchall()

        if not rows:
            conn.close()
            raise HTTPException(status_code=404, detail="No games found for this filter")

        updated = 0
        skipped = 0
        processed = 0
        total = len(rows)
        
        logger.info(f"Fetching metadata for {total} games in console {cid} (force={force}, letter={letter})")
        
        # Batch commit counter
        commit_counter = 0

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
                processed += 1
                continue
            
            if force:
                logger.info(f"Force updating metadata for {title}")

            rawg_game = None
            meta_genre = None
            meta_desc = None

            if is_rawg_configured():
                rawg_game = fetch_rawg_game(title, cid)
                if rawg_game:
                    meta_genre = ", ".join(g["name"] for g in rawg_game.get("genres") or [])
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
                    genres = [g["name"] for g in rawg_game.get("genres") or []]
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
                genres = [g["name"] for g in rawg_game.get("genres") or []]
                tags = [t["name"] for t in rawg_game.get("tags") or []]
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

            # Extract publisher/developer/release_year from RAWG data (smart: only fill NULLs)
            new_release_year = None
            new_publisher = None
            new_developer = None
            if rawg_game:
                released = rawg_game.get("released", "")
                if released:
                    try:
                        new_release_year = int(released.split("-")[0])
                    except (ValueError, IndexError):
                        pass
                pubs = rawg_game.get("publishers") or []
                if pubs:
                    new_publisher = ", ".join(p.get("name", "") for p in pubs if p.get("name"))
                devs = rawg_game.get("developers") or []
                if devs:
                    new_developer = ", ".join(d.get("name", "") for d in devs if d.get("name"))

            # Update DB (smart: only overwrite NULL fields)
            cur.execute(
                """
                UPDATE games
                SET
                    genre = ?,
                    description = ?,
                    metadata_json = ?,
                    release_year = COALESCE(?, release_year),
                    publisher = COALESCE(?, publisher),
                    developer = COALESCE(?, developer),
                    updated_at = ?
                WHERE id = ?;
                """,
                (new_genre, new_desc, local_meta, new_release_year, new_publisher, new_developer, datetime.utcnow().isoformat(), gid),
            )

            updated += 1
            processed += 1
            commit_counter += 1
            logger.info(f"Updated metadata for {title}")
            
            # Batch commit
            if commit_counter >= batch_commit:
                conn.commit()
                commit_counter = 0
                logger.debug(f"Batch commit at {processed}/{total}")

        conn.commit()
        conn.close()

        progress_pct = round((processed / total) * 100, 2) if total > 0 else 0
        logger.info(f"Metadata updated for {updated} games in console {cid}, {skipped} skipped, processed: {processed}/{total}")
        return {"status": "ok", "updated": updated, "skipped": skipped, "processed": processed, "total": total, "progress_pct": progress_pct}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch metadata: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch metadata")

@app.post("/api/consoles/{cid}/fetch-covers")
def fetch_covers_for_console(cid: int, force: bool = Query(False), source: str = Query("rawg"), letter: str = Query(None), batch_commit: int = Query(50)):
    """Fetch covers with console-specific folder structure. source can be 'rawg', 'duckduckgo' or 'tgdb'.
    letter can be A-Z or 0-9 to filter by starting letter.
    batch_commit is the number of games to process before committing (default 50)."""
    logger.info(f"[DEBUG] fetch_covers called with cid={cid}, force={force}, source={source}, letter={letter}, batch_commit={batch_commit}")
    if not FETCH_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A fetch is already running. Please wait for it to finish.")
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Get console info first
        cur.execute("SELECT id, name FROM consoles WHERE id = ?", (cid,))
        console = cur.fetchone()
        if not console:
            conn.close()
            raise HTTPException(status_code=404, detail="Console not found")
        
        console_name = console["name"]
        
        # Build query with optional letter filter
        query = """
            SELECT id, title, genre, description, console_id, cover_url
            FROM games
            WHERE console_id = ?
        """
        params = [cid]
        
        if letter:
            if letter == "0":
                query += " AND title GLOB '[0-9]*'"
            else:
                query += " AND title LIKE ?"
                params.append(f"{letter}%")
        
        query += " ORDER BY title;"
        
        cur.execute(query, params)
        rows = cur.fetchall()
        
        if not rows:
            conn.close()
            raise HTTPException(status_code=404, detail="No games found for this filter")
        
        total = len(rows)
        updated = 0
        skipped = 0
        processed = 0
        cancelled = False
        
        logger.info(f"Fetching covers for {total} games in console {cid} (force={force}, source={source}, letter={letter})")
        start = time.time()
        
        # Batch commit counter
        commit_counter = 0
        
        # Clear any previous cancel flag
        set_fetch_cancel(False)
        
        for game in rows:
            # Check cancel flag periodically
            if processed % 10 == 0:
                if is_fetch_cancelled():
                    cancelled = True
                    break
            
            gid = game["id"]
            title = game["title"]
            existing_cover = game["cover_url"]
            
            # Skip if already has cover (unless force=true)
            if existing_cover and existing_cover.lower() != "null" and not force:
                logger.debug(f"Skipping {title} - already has cover")
                skipped += 1
                processed += 1
                continue
            
            # Create console-specific folder structure
            safe_title = sanitize_filename(title)  # Remove special chars
            safe_console = console_name.lower().replace(" ", "_")
            cover_filename = f"{safe_console}/{safe_title}.jpg"
            cover_path = Path(COVERS_DIR) / cover_filename
            cover_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Fetch cover based on source (with automatic fallback to TGDB
            # when DuckDuckGo is rate limited or finds nothing)
            cover_url = None
            used_source = None
            try:
                if source == "duckduckgo":
                    try:
                        cover_url = fetch_duckduckgo_cover(title, console_name)
                        if cover_url:
                            used_source = "duckduckgo"
                            logger.info(f"Found DuckDuckGo cover for {title}")
                    except DDGRateLimited:
                        logger.warning(f"DuckDuckGo rate limited, falling back for {title}")
                    if not cover_url and is_tgdb_configured():
                        cover_url = fetch_tgdb_cover(title, cid, console_name)
                        if cover_url:
                            used_source = "tgdb"
                elif source == "tgdb":
                    cover_url = fetch_tgdb_cover(title, cid, console_name)
                    if cover_url:
                        used_source = "tgdb"
                else:
                    rawg_game = fetch_rawg_game(title, console_id=cid, strict_platform=True)
                    if rawg_game and rawg_game.get("background_image"):
                        cover_url = rawg_game["background_image"]
                        used_source = "rawg"
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
                            "source_type": used_source or source,
                            "original_url": cover_url,
                        })

                        _exec_write(cur,
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
            
            processed += 1
            commit_counter += 1
            
            # Batch commit
            if commit_counter >= batch_commit:
                conn.commit()
                commit_counter = 0
                logger.debug(f"Batch commit at {processed}/{total}")
        
        # Final commit
        conn.commit()
        
        # Clear cancel flag
        set_fetch_cancel(False)
        
        end = time.time()
        progress_pct = round((processed / total) * 100, 2) if total > 0 else 0
        
        logger.info(f"Cover fetching completed in {end - start:.2f}s - updated: {updated}, skipped: {skipped}, processed: {processed}, cancelled: {cancelled}")
        
        return {
            "status": "ok",
            "updated": updated,
            "skipped": skipped,
            "processed": processed,
            "total": total,
            "progress_pct": progress_pct,
            "cancelled": cancelled
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch covers: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch covers")
    finally:
        FETCH_LOCK.release()


def generate_cover_progress_stream(cid: int, force: bool, source: str, letter: str, batch_commit: int):
    """Generator that yields SSE progress updates for cover fetching."""
    import asyncio

    if not FETCH_LOCK.acquire(blocking=False):
        yield f"data: {json.dumps({'status': 'busy', 'error': 'A fetch is already running. Please wait for it to finish.'})}\n\n"
        return

    try:
        conn = get_conn()
        cur = conn.cursor()
        
        cur.execute("SELECT id, name FROM consoles WHERE id = ?", (cid,))
        console = cur.fetchone()
        if not console:
            yield f"data: {json.dumps({'error': 'Console not found'})}\n\n"
            return
        
        console_name = console["name"]
        
        query = """
            SELECT id, title, genre, description, console_id, cover_url
            FROM games
            WHERE console_id = ?
        """
        params = [cid]
        
        if letter:
            if letter == "0":
                query += " AND title GLOB '[0-9]*'"
            else:
                query += " AND title LIKE ?"
                params.append(f"{letter}%")
        
        query += " ORDER BY title;"
        
        cur.execute(query, params)
        rows = cur.fetchall()
        
        if not rows:
            yield f"data: {json.dumps({'error': 'No games found for this filter'})}\n\n"
            return
        
        total = len(rows)
        updated = 0
        skipped = 0
        processed = 0
        cancelled = False
        
        logger.info(f"Streaming covers for {total} games in console {cid}")
        start = time.time()
        
        commit_counter = 0
        set_fetch_cancel(False)
        
        # Send initial status
        yield f"data: {json.dumps({'status': 'starting', 'total': total, 'processed': 0, 'updated': 0, 'skipped': 0})}\n\n"
        
        for game in rows:
            if processed % 10 == 0:
                if is_fetch_cancelled():
                    cancelled = True
                    break
            
            gid = game["id"]
            title = game["title"]
            existing_cover = game["cover_url"]
            
            if existing_cover and existing_cover.lower() != "null" and not force:
                skipped += 1
                processed += 1
                continue
            
            safe_title = sanitize_filename(title)
            safe_console = console_name.lower().replace(" ", "_")
            cover_filename = f"{safe_console}/{safe_title}.jpg"
            cover_path = Path(COVERS_DIR) / cover_filename
            cover_path.parent.mkdir(parents=True, exist_ok=True)
            
            cover_url = None
            used_source = None
            rate_limited_hit = False
            try:
                if source == "duckduckgo":
                    try:
                        cover_url = fetch_duckduckgo_cover(title, console_name)
                        if cover_url:
                            used_source = "duckduckgo"
                    except DDGRateLimited:
                        rate_limited_hit = True
                    if not cover_url and is_tgdb_configured():
                        cover_url = fetch_tgdb_cover(title, cid, console_name)
                        if cover_url:
                            used_source = "tgdb"
                elif source == "tgdb":
                    cover_url = fetch_tgdb_cover(title, cid, console_name)
                    if cover_url:
                        used_source = "tgdb"
                else:
                    rawg_game = fetch_rawg_game(title, console_id=cid, strict_platform=True)
                    if rawg_game and rawg_game.get("background_image"):
                        cover_url = rawg_game["background_image"]
                        used_source = "rawg"
            except Exception as e:
                logger.warning(f"Cover search failed for {title}: {e}")

            if rate_limited_hit:
                yield f"data: {json.dumps({'status': 'rate_limited', 'provider': 'duckduckgo', 'current': title})}\n\n"

            if cover_url:
                try:
                    response = requests.get(cover_url, timeout=15)
                    if response.status_code == 200:
                        with open(cover_path, "wb") as f:
                            f.write(response.content)

                        local_meta = save_metadata_json(gid, {
                            "source": "downloaded",
                            "source_type": used_source or source,
                            "original_url": cover_url,
                        })

                        _exec_write(cur,
                            "UPDATE games SET cover_url = ?, metadata_json = ? WHERE id = ?;",
                            (f"/covers/{cover_filename}", local_meta, gid),
                        )
                        updated += 1
                except Exception as e:
                    logger.warning(f"Cover download failed for {title}: {e}")

            if not cover_url:
                skipped += 1
            
            processed += 1
            commit_counter += 1
            
            if commit_counter >= batch_commit:
                conn.commit()
                commit_counter = 0
            
            # Send progress update every 5 games or on last
            if processed % 5 == 0 or processed == total:
                progress_pct = round((processed / total) * 100, 2) if total > 0 else 0
                yield f"data: {json.dumps({'status': 'progress', 'processed': processed, 'total': total, 'progress_pct': progress_pct, 'updated': updated, 'skipped': skipped, 'current': title})}\n\n"
        
        conn.commit()
        set_fetch_cancel(False)
        
        end = time.time()
        progress_pct = round((processed / total) * 100, 2) if total > 0 else 0
        
        yield f"data: {json.dumps({'status': 'complete', 'processed': processed, 'total': total, 'progress_pct': progress_pct, 'updated': updated, 'skipped': skipped, 'cancelled': cancelled, 'elapsed': round(end - start, 2)})}\n\n"

    except Exception as e:
        logger.error(f"Stream error: {e}")
        yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"
    finally:
        FETCH_LOCK.release()


@app.get("/api/consoles/{cid}/fetch-covers/stream")
def fetch_covers_stream(cid: int, force: bool = Query(False), source: str = Query("rawg"), letter: str = Query(None), batch_commit: int = Query(50)):
    """Fetch covers with real-time SSE progress updates."""
    return StreamingResponse(
        generate_cover_progress_stream(cid, force, source, letter, batch_commit),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.post("/api/consoles/{cid}/fetch-covers/cancel")
def cancel_fetch_covers(cid: int):
    """Cancel an ongoing fetch covers operation"""
    set_fetch_cancel(True)
    return {"status": "ok", "cancelled": True}


@app.post("/api/consoles/{cid}/fetch-screenshots/cancel")
def cancel_fetch_screenshots(cid: int):
    """Cancel an ongoing fetch screenshots operation"""
    set_fetch_cancel(True)
    return {"status": "ok", "cancelled": True}


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
def fetch_screenshots_for_console(cid: int, force: bool = Query(False), source: str = Query("duckduckgo"), letter: str = Query(None), batch_commit: int = Query(50)):
    """Fetch and save screenshots for games. Use force=true to re-fetch all, false for missing only.
    source can be 'duckduckgo', 'rawg' or 'tgdb'.
    letter can be A-Z or 0-9 to filter by starting letter.
    batch_commit is the number of games to process before committing (default 50)."""
    if not FETCH_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A fetch is already running. Please wait for it to finish.")
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id, name FROM consoles WHERE id = ?;", (cid,))
        console = cur.fetchone()
        if not console:
            raise HTTPException(status_code=404, detail="Console not found")

        console_name = console["name"]
        logger.info(f"[DEBUG] Console name: '{console_name}', source: '{source}', letter: '{letter}'")

        # If force=true, delete existing screenshots first
        if force:
            if letter:
                if letter == "0":
                    _exec_write(cur, "DELETE FROM screenshots WHERE game_id IN (SELECT id FROM games WHERE console_id = ? AND title GLOB '[0-9]*');", (cid,))
                else:
                    _exec_write(cur, "DELETE FROM screenshots WHERE game_id IN (SELECT id FROM games WHERE console_id = ? AND title LIKE ?);", (cid, f"{letter}%"))
                logger.info(f"Cleared existing screenshots for console {cid} letter {letter}")
            else:
                _exec_write(cur, "DELETE FROM screenshots WHERE game_id IN (SELECT id FROM games WHERE console_id = ?);", (cid,))
                logger.info(f"Cleared existing screenshots for console {cid}")

        # Build query with optional letter filter
        base_where = "WHERE g.console_id = ?"
        params = [cid]
        
        if letter:
            if letter == "0":
                base_where += " AND g.title GLOB '[0-9]*'"
            else:
                base_where += " AND g.title LIKE ?"
                params.append(f"{letter}%")
        
        # Games with MISSING screenshots (smart fetching) or all games (force)
        if force:
            query = "SELECT id, title FROM games WHERE console_id = ?"
            exec_params = [cid]
            if letter:
                if letter == "0":
                    query += " AND title GLOB '[0-9]*'"
                else:
                    query += " AND title LIKE ?"
                    exec_params.append(f"{letter}%")
            query += " ORDER BY title;"
        else:
            query = f"""
            SELECT g.id, g.title
            FROM games g
            LEFT JOIN screenshots s ON g.id = s.game_id
            {base_where}
            GROUP BY g.id
            HAVING COUNT(s.id) = 0
            ORDER BY g.title;
            """
            exec_params = params

        cur.execute(query, exec_params)
        rows = cur.fetchall()

        if not rows:
            conn.close()
            raise HTTPException(status_code=404, detail="No games found for this filter")

        updated = 0
        skipped = 0
        processed = 0
        total = len(rows)
        
        logger.info(f"Fetching screenshots for {total} games in console {cid} using {source} (letter={letter})")
        
        # Batch commit counter
        commit_counter = 0

        for r in rows:
            gid = r["id"]
            title = r["title"]

            if source == "duckduckgo":
                try:
                    raw_screens = fetch_duckduckgo_screenshots(title, console_name, limit=5)
                except DDGRateLimited:
                    raw_screens = []
                    logger.warning(f"DuckDuckGo rate limited during screenshots for {title}")
            elif source == "tgdb":
                tgdb_urls = fetch_tgdb_screenshots(title, cid, console_name, limit=5)
                raw_screens = list(tgdb_urls)
            else:
                rawg_game = fetch_rawg_game(title, cid)
                if not rawg_game:
                    skipped += 1
                    processed += 1
                    continue

                rawg_id = rawg_game.get("id")
                if not rawg_id:
                    skipped += 1
                    processed += 1
                    continue

                # Fetch screenshots
                raw_screens = [s.get("image") for s in fetch_rawg_screenshots(rawg_id, limit=5)
                               if s.get("image")]

            if not raw_screens:
                skipped += 1
                processed += 1
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

            # Insert screenshots into DB
            if screenshots_urls:
                for url in screenshots_urls:
                    _exec_write(cur,
                        "INSERT INTO screenshots (game_id, url) VALUES (?, ?);",
                        (gid, url),
                    )
                updated += 1
            else:
                skipped += 1

            processed += 1
            commit_counter += 1

            # Batch commit
            if commit_counter >= batch_commit:
                conn.commit()
                commit_counter = 0
                logger.debug(f"Batch commit at {processed}/{total}")

        conn.commit()
        conn.close()

        progress_pct = round((processed / total) * 100, 2) if total > 0 else 0
        logger.info(f"Screenshots completed: {updated} fetched, {skipped} skipped, processed: {processed}/{total}")
        return {"status": "ok", "updated": updated, "skipped": skipped, "processed": processed, "total": total, "progress_pct": progress_pct}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch screenshots: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch screenshots")
    finally:
        FETCH_LOCK.release()


def generate_screenshot_progress_stream(cid: int, force: bool, source: str, letter: str, batch_commit: int):
    """Generator that yields SSE progress updates for screenshot fetching."""
    if not FETCH_LOCK.acquire(blocking=False):
        yield f"data: {json.dumps({'status': 'busy', 'error': 'A fetch is already running. Please wait for it to finish.'})}\n\n"
        return

    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id, name FROM consoles WHERE id = ?;", (cid,))
        console = cur.fetchone()
        if not console:
            yield f"data: {json.dumps({'error': 'Console not found'})}\n\n"
            return

        console_name = console["name"]

        if force:
            if letter:
                if letter == "0":
                    _exec_write(cur, "DELETE FROM screenshots WHERE game_id IN (SELECT id FROM games WHERE console_id = ? AND title GLOB '[0-9]*');", (cid,))
                else:
                    _exec_write(cur, "DELETE FROM screenshots WHERE game_id IN (SELECT id FROM games WHERE console_id = ? AND title LIKE ?);", (cid, f"{letter}%"))
            else:
                _exec_write(cur, "DELETE FROM screenshots WHERE game_id IN (SELECT id FROM games WHERE console_id = ?);", (cid,))

        base_where = "WHERE g.console_id = ?"
        params = [cid]

        if letter:
            if letter == "0":
                base_where += " AND g.title GLOB '[0-9]*'"
            else:
                base_where += " AND g.title LIKE ?"
                params.append(f"{letter}%")

        if force:
            query = "SELECT id, title FROM games WHERE console_id = ?"
            exec_params = [cid]
            if letter:
                if letter == "0":
                    query += " AND title GLOB '[0-9]*'"
                else:
                    query += " AND title LIKE ?"
                    exec_params.append(f"{letter}%")
            query += " ORDER BY title;"
        else:
            query = f"""
            SELECT g.id, g.title
            FROM games g
            LEFT JOIN screenshots s ON g.id = s.game_id
            {base_where}
            GROUP BY g.id
            HAVING COUNT(s.id) = 0
            ORDER BY g.title;
            """
            exec_params = params

        cur.execute(query, exec_params)
        rows = cur.fetchall()

        if not rows:
            yield f"data: {json.dumps({'error': 'No games found for this filter'})}\n\n"
            return

        total = len(rows)
        updated = 0
        skipped = 0
        processed = 0
        cancelled = False

        logger.info(f"Streaming screenshots for {total} games in console {cid}")
        start = time.time()

        commit_counter = 0
        set_fetch_cancel(False)

        yield f"data: {json.dumps({'status': 'starting', 'total': total, 'processed': 0, 'updated': 0, 'skipped': 0})}\n\n"

        for game in rows:
            if processed % 10 == 0:
                if is_fetch_cancelled():
                    cancelled = True
                    break

            gid = game["id"]
            title = game["title"]

            screenshots_urls = []
            rate_limited_hit = False

            # 1) DuckDuckGo first (unless TGDB or RAWG explicitly selected)
            if source not in ("tgdb", "rawg"):
                try:
                    images = fetch_duckduckgo_screenshots(title, console_name, limit=5)
                    for img_url in images[:5]:
                        img = download_image(img_url)
                        if img:
                            local_s = save_screenshot(img, gid, len(screenshots_urls) + 1)
                            if local_s:
                                screenshots_urls.append(local_s)
                except DDGRateLimited:
                    rate_limited_hit = True
                    logger.warning(f"DuckDuckGo rate limited during screenshots for {title}")
                except Exception as e:
                    logger.warning(f"DuckDuckGo failed for {title}: {e}")

            # 2) TheGamesDB (explicit selection or fallback from DuckDuckGo)
            if not screenshots_urls and source in ("duckduckgo", "tgdb") and is_tgdb_configured():
                try:
                    tgdb_urls = fetch_tgdb_screenshots(title, cid, console_name, limit=5)
                    for img_url in tgdb_urls[:5]:
                        img = download_image(img_url)
                        if img:
                            local_s = save_screenshot(img, gid, len(screenshots_urls) + 1)
                            if local_s:
                                screenshots_urls.append(local_s)
                except Exception as e:
                    logger.warning(f"TheGamesDB failed for {title}: {e}")

            if rate_limited_hit:
                yield f"data: {json.dumps({'status': 'rate_limited', 'provider': 'duckduckgo', 'current': title})}\n\n"

            # 3) Fall back to RAWG
            if not screenshots_urls and is_rawg_configured():
                try:
                    rawg_game = fetch_rawg_game(title, cid)
                    if rawg_game and rawg_game.get("short_screenshots"):
                        raw_screens = rawg_game["short_screenshots"]
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
                except Exception as e:
                    logger.warning(f"RAWG failed for {title}: {e}")

            if screenshots_urls:
                for url in screenshots_urls:
                    _exec_write(cur,
                        "INSERT INTO screenshots (game_id, url) VALUES (?, ?);",
                        (gid, url),
                    )
                updated += 1
            else:
                skipped += 1

            processed += 1
            commit_counter += 1

            if commit_counter >= batch_commit:
                conn.commit()
                commit_counter = 0

            if processed % 5 == 0 or processed == total:
                progress_pct = round((processed / total) * 100, 2) if total > 0 else 0
                yield f"data: {json.dumps({'status': 'progress', 'processed': processed, 'total': total, 'progress_pct': progress_pct, 'updated': updated, 'skipped': skipped, 'current': title})}\n\n"

        conn.commit()
        conn.close()
        set_fetch_cancel(False)

        end = time.time()
        progress_pct = round((processed / total) * 100, 2) if total > 0 else 0

        yield f"data: {json.dumps({'status': 'complete', 'processed': processed, 'total': total, 'progress_pct': progress_pct, 'updated': updated, 'skipped': skipped, 'cancelled': cancelled, 'elapsed': round(end - start, 2)})}\n\n"

    except Exception as e:
        logger.error(f"Stream error: {e}")
        yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"
    finally:
        FETCH_LOCK.release()


@app.get("/api/consoles/{cid}/fetch-screenshots/stream")
def fetch_screenshots_stream(cid: int, force: bool = Query(False), source: str = Query("duckduckgo"), letter: str = Query(None), batch_commit: int = Query(50)):
    """Fetch screenshots with real-time SSE progress updates."""
    return StreamingResponse(
        generate_screenshot_progress_stream(cid, force, source, letter, batch_commit),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

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
def fetch_cover_for_game(game_id: int, source: str = Query("auto")):
    """Fetch a cover for a single game. source can be 'auto' (DDG→TGDB chain), 'duckduckgo', 'tgdb', or 'rawg'.
    The DB connection is NOT held during network work to avoid lock contention."""
    # 0) Read game info, then release the connection immediately
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT g.id, g.title, g.console_id, c.name as console_name
            FROM games g
            JOIN consoles c ON g.console_id = c.id
            WHERE g.id = ?;
        """, (game_id,))
        row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Game not found")

    gid = row["id"]
    title = row["title"]
    console_id = row["console_id"]
    console_name = row["console_name"]

    logger.info(f"[COVER] Fetching cover for: {title} ({console_name})")

    cover_url = None
    used_source = None
    ddg_rate_limited = False

    if source == "auto":
        # 1) DuckDuckGo
        try:
            cover_url = fetch_duckduckgo_cover(title, console_name)
            if cover_url:
                used_source = "duckduckgo"
        except DDGRateLimited:
            ddg_rate_limited = True
            logger.warning(f"[COVER] DuckDuckGo rate limited during search for '{title}'")

        # 2) TheGamesDB fallback
        if not cover_url:
            if is_tgdb_configured():
                cover_url = fetch_tgdb_cover(title, console_id, console_name)
                if cover_url:
                    used_source = "tgdb"
            elif ddg_rate_limited:
                raise HTTPException(
                    status_code=429,
                    detail="DuckDuckGo is rate-limiting this IP and no TheGamesDB API key is configured. "
                           "Add one under Options -> API Keys to enable automatic fallback.",
                )

        if not cover_url:
            if ddg_rate_limited:
                raise HTTPException(
                    status_code=429,
                    detail="DuckDuckGo is rate-limiting this IP and TheGamesDB had no cover for this game. Try again later.",
                )
            raise HTTPException(status_code=404, detail="No cover found for this game")
    else:
        # Specific source requested
        if source == "duckduckgo":
            try:
                cover_url = fetch_duckduckgo_cover(title, console_name)
                if cover_url:
                    used_source = "duckduckgo"
            except DDGRateLimited:
                raise HTTPException(status_code=429, detail="DuckDuckGo is rate-limiting this IP. Try again later.")
        elif source == "tgdb":
            if not is_tgdb_configured():
                raise HTTPException(status_code=400, detail="TheGamesDB API key not configured. Add one under Options -> API Keys.")
            cover_url = fetch_tgdb_cover(title, console_id, console_name)
            if cover_url:
                used_source = "tgdb"
        elif source == "rawg":
            if not is_rawg_configured():
                raise HTTPException(status_code=400, detail="RAWG API key not configured. Add one under Options -> API Keys.")
            rawg_game = fetch_rawg_game(title, console_id)
            if rawg_game and rawg_game.get("background_image"):
                cover_url = rawg_game["background_image"]
                used_source = "rawg"

        if not cover_url:
            raise HTTPException(status_code=404, detail=f"No cover found from {source} for this game")

    # 3) Download and save cover file
    safe_title = sanitize_filename(title)
    safe_console = console_name.lower().replace(" ", "_")
    cover_filename = f"{safe_console}/{safe_title}.jpg"
    cover_path = Path(COVERS_DIR) / cover_filename
    cover_path.parent.mkdir(parents=True, exist_ok=True)

    response = requests.get(cover_url, timeout=15)
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to download cover")

    with open(cover_path, "wb") as f:
        f.write(response.content)

    # 4) Brief write window: reopen connection just for the update
    conn = get_conn()
    try:
        cur = conn.cursor()
        now = datetime.utcnow().isoformat()
        _exec_write(cur,
            "UPDATE games SET cover_url = ?, updated_at = ? WHERE id = ?;",
            (f"/covers/{cover_filename}", now, gid),
        )
        conn.commit()
    finally:
        conn.close()

    logger.info(f"[COVER] Cover saved ({used_source}) for {title}: {cover_filename}")
    return {"status": "ok", "title": title, "source": used_source,
            "cover_url": f"/covers/{cover_filename}"}

# -------------------------------------------------------------------
# API: Update Game Details
# -------------------------------------------------------------------

@app.post("/api/games/{game_id}/update")
def update_game(game_id: int, data: GameUpdateRequest):
    """Update game title, genre, and description"""
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id FROM games WHERE id = ?;", (game_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Game not found")

        title = data.title.strip()
        genre = data.genre.strip() if data.genre else ""
        description = data.description.strip() if data.description else ""

        if not title:
            raise HTTPException(status_code=400, detail="Title is required")

        # Normalize genre tags against existing archive labels (case-insensitive match)
        if genre:
            genre_tags = [t.strip() for t in genre.split(",") if t.strip()]
            cur.execute("SELECT DISTINCT genre FROM games WHERE genre IS NOT NULL AND genre != ''")
            known = {}
            for r in cur.fetchall():
                for t in r["genre"].split(","):
                    t = t.strip()
                    if t:
                        known[t.lower()] = t
            normalized = [known.get(t.lower(), t) for t in genre_tags]
            genre = ", ".join(normalized)

        now = datetime.utcnow().isoformat()

        _exec_write(cur,
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

@app.get("/api/genres")
def get_genres():
    """Return all unique genre labels from the archive, case-insensitive deduped, sorted."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT genre FROM games WHERE genre IS NOT NULL AND genre != ''")
        rows = cur.fetchall()
    finally:
        conn.close()

    canonical = {}
    for row in rows:
        for tag in row["genre"].split(","):
            tag = tag.strip()
            if not tag:
                continue
            key = tag.lower()
            if key not in canonical:
                canonical[key] = tag
    return sorted(canonical.values(), key=str.lower)

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
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        cur.execute("SELECT id FROM games WHERE id = ?;", (game_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Game not found")
        
        cur.execute("SELECT COUNT(*) FROM screenshots WHERE game_id = ?;", (game_id,))
        count = cur.fetchone()[0]
        
        if count >= MAX_SCREENSHOTS_PER_GAME:
            raise HTTPException(status_code=400, detail=f"Maximum {MAX_SCREENSHOTS_PER_GAME} screenshots allowed per game")
        
        contents = await file.read()
        try:
            img = Image.open(BytesIO(contents)).convert("RGB")
        except Exception as e:
            logger.error(f"Failed to open image: {e}")
            raise HTTPException(status_code=400, detail="Invalid image file")
        
        index = count + 1
        
        local_screenshot = save_screenshot(img, game_id, index)
        if not local_screenshot:
            raise HTTPException(status_code=500, detail="Failed to save screenshot")
        
        cur.execute(
            "INSERT INTO screenshots (game_id, url) VALUES (?, ?);",
            (game_id, local_screenshot),
        )
        conn.commit()
        screenshot_id = cur.lastrowid
        
        logger.info(f"Screenshot uploaded for game {game_id}")
        return {"status": "ok", "screenshot_id": screenshot_id, "url": local_screenshot}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload screenshot: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload screenshot")
    finally:
        conn.close()

@app.post("/api/games/{game_id}/screenshot-from-url")
def screenshot_from_url(game_id: int, data: ScreenshotFromUrlRequest):
    """Add a screenshot from a URL"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        cur.execute("SELECT id FROM games WHERE id = ?;", (game_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Game not found")
        
        cur.execute("SELECT COUNT(*) FROM screenshots WHERE game_id = ?;", (game_id,))
        count = cur.fetchone()[0]
        
        if count >= MAX_SCREENSHOTS_PER_GAME:
            raise HTTPException(status_code=400, detail=f"Maximum {MAX_SCREENSHOTS_PER_GAME} screenshots allowed per game")
        
        url = data.url
        if not url:
            raise HTTPException(status_code=400, detail="URL is required")
        
        index = count + 1
        
        img = download_image(url)
        if not img:
            raise HTTPException(status_code=400, detail="Failed to download image from URL")
        
        local_screenshot = save_screenshot(img, game_id, index)
        if not local_screenshot:
            raise HTTPException(status_code=500, detail="Failed to save screenshot")
        
        cur.execute(
            "INSERT INTO screenshots (game_id, url) VALUES (?, ?);",
            (game_id, local_screenshot),
        )
        conn.commit()
        screenshot_id = cur.lastrowid
        
        logger.info(f"Screenshot added from URL for game {game_id}: {url}")
        return {"status": "ok", "screenshot_id": screenshot_id, "url": local_screenshot}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add screenshot from URL: {e}")
        raise HTTPException(status_code=500, detail="Failed to add screenshot from URL")
    finally:
        conn.close()

# -------------------------------------------------------------------
# API: Collections
# -------------------------------------------------------------------

class CollectionBase(BaseModel):
    name: str
    description: Optional[str] = ""

class CollectionResponse(CollectionBase):
    id: int
    game_count: int = 0
    created_at: str

    class Config:
        from_attributes = True

class CollectionGameResponse(BaseModel):
    id: int
    game_id: int
    title: str
    genre: Optional[str] = None
    cover_url: Optional[str] = None
    console_name: str

    class Config:
        from_attributes = True

class GameCollectionsResponse(BaseModel):
    collection_id: int
    collection_name: str

    class Config:
        from_attributes = True

# --- Series Models ---

class SeriesBase(BaseModel):
    name: str
    genre: Optional[str] = ""

class SeriesResponse(SeriesBase):
    id: int
    game_count: int = 0
    created_at: str
    cover_url: Optional[str] = None

    class Config:
        from_attributes = True

class SeriesGameEntry(BaseModel):
    id: int
    series_id: int
    game_id: Optional[int] = None
    position: int
    title: str
    cover_url: Optional[str] = None
    platform: Optional[str] = ""
    release_year: Optional[int] = None
    rawg_id: Optional[int] = None
    is_missing: bool = False

    class Config:
        from_attributes = True

class SeriesAddGameRequest(BaseModel):
    game_id: Optional[int] = None
    title: Optional[str] = ""
    cover_url: Optional[str] = None
    platform: Optional[str] = ""
    release_year: Optional[int] = None
    rawg_id: Optional[int] = None
    is_missing: bool = False

class SeriesBulkAddRequest(BaseModel):
    games: List[SeriesAddGameRequest]

class SeriesReorderRequest(BaseModel):
    positions: List[dict]  # [{"id": int, "position": int}, ...]

class SeriesExpandResponse(BaseModel):
    games: List[dict]
    source_rawg_id: int

@app.get("/api/collections", response_model=List[CollectionResponse])
def get_collections():
    """List all collections with game counts"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT c.id, c.name, c.description, c.created_at,
                   COUNT(cg.id) as game_count
            FROM collections c
            LEFT JOIN collection_games cg ON c.id = cg.collection_id
            GROUP BY c.id
            ORDER BY c.name;
        """)
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to get collections: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve collections")

@app.post("/api/collections", response_model=CollectionResponse)
def create_collection(data: CollectionBase):
    """Create a new collection"""
    try:
        name = data.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Collection name cannot be empty")

        conn = get_conn()
        cur = conn.cursor()
        now = datetime.utcnow().isoformat()

        try:
            cur.execute(
                "INSERT INTO collections (name, description, created_at) VALUES (?, ?, ?);",
                (name, data.description or "", now),
            )
            cid = cur.lastrowid
            conn.commit()
            logger.info(f"Collection created: {name}")
        except sqlite3.IntegrityError:
            conn.close()
            raise HTTPException(status_code=409, detail=f"Collection '{name}' already exists")

        conn.close()
        return CollectionResponse(id=cid, name=name, description=data.description or "", game_count=0, created_at=now)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create collection: {e}")
        raise HTTPException(status_code=500, detail="Failed to create collection")

@app.put("/api/collections/{collection_id}", response_model=CollectionResponse)
def update_collection(collection_id: int, data: CollectionBase):
    """Update a collection's name or description"""
    try:
        name = data.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Collection name cannot be empty")

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id FROM collections WHERE id = ?;", (collection_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Collection not found")

        cur.execute(
            "UPDATE collections SET name = ?, description = ? WHERE id = ?;",
            (name, data.description or "", collection_id),
        )
        conn.commit()

        cur.execute("SELECT COUNT(*) FROM collection_games WHERE collection_id = ?;", (collection_id,))
        game_count = cur.fetchone()[0]
        cur.execute("SELECT created_at FROM collections WHERE id = ?;", (collection_id,))
        created_at = cur.fetchone()["created_at"]
        conn.close()

        return CollectionResponse(id=collection_id, name=name, description=data.description or "", game_count=game_count, created_at=created_at)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update collection: {e}")
        raise HTTPException(status_code=500, detail="Failed to update collection")

@app.delete("/api/collections/{collection_id}")
def delete_collection(collection_id: int):
    """Delete a collection"""
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id FROM collections WHERE id = ?;", (collection_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Collection not found")

        cur.execute("DELETE FROM collections WHERE id = ?;", (collection_id,))
        conn.commit()
        conn.close()

        return {"status": "ok", "message": "Collection deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete collection: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete collection")

@app.get("/api/collections/{collection_id}/games", response_model=List[CollectionGameResponse])
def get_collection_games(collection_id: int):
    """Get all games in a collection"""
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id FROM collections WHERE id = ?;", (collection_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Collection not found")

        cur.execute("""
            SELECT cg.id, cg.game_id, g.title, g.genre, g.cover_url, co.name as console_name
            FROM collection_games cg
            JOIN games g ON cg.game_id = g.id
            JOIN consoles co ON g.console_id = co.id
            WHERE cg.collection_id = ?
            ORDER BY g.title;
        """, (collection_id,))

        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get collection games: {e}")
        raise HTTPException(status_code=500, detail="Failed to get collection games")

@app.post("/api/collections/{collection_id}/games/{game_id}")
def add_game_to_collection(collection_id: int, game_id: int):
    """Add a game to a collection"""
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id FROM collections WHERE id = ?;", (collection_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Collection not found")

        cur.execute("SELECT id FROM games WHERE id = ?;", (game_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Game not found")

        try:
            cur.execute(
                "INSERT INTO collection_games (collection_id, game_id) VALUES (?, ?);",
                (collection_id, game_id),
            )
            conn.commit()
            logger.info(f"Game {game_id} added to collection {collection_id}")
        except sqlite3.IntegrityError:
            conn.close()
            raise HTTPException(status_code=409, detail="Game already in collection")

        conn.close()
        return {"status": "ok", "message": "Game added to collection"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add game to collection: {e}")
        raise HTTPException(status_code=500, detail="Failed to add game to collection")

@app.delete("/api/collections/{collection_id}/games/{game_id}")
def remove_game_from_collection(collection_id: int, game_id: int):
    """Remove a game from a collection"""
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute(
            "DELETE FROM collection_games WHERE collection_id = ? AND game_id = ?;",
            (collection_id, game_id),
        )

        if cur.rowcount == 0:
            conn.close()
            raise HTTPException(status_code=404, detail="Game not found in collection")

        conn.commit()
        conn.close()
        return {"status": "ok", "message": "Game removed from collection"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to remove game from collection: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove game from collection")

@app.get("/api/games/{game_id}/collections", response_model=List[GameCollectionsResponse])
def get_game_collections(game_id: int):
    """Get all collections a game belongs to"""
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT c.id as collection_id, c.name as collection_name
            FROM collection_games cg
            JOIN collections c ON cg.collection_id = c.id
            WHERE cg.game_id = ?
            ORDER BY c.name;
        """, (game_id,))

        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to get game collections: {e}")
        raise HTTPException(status_code=500, detail="Failed to get game collections")

# -------------------------------------------------------------------
# API: Series
# -------------------------------------------------------------------

@app.get("/api/series", response_model=List[SeriesResponse])
def get_series():
    """List all series with game counts"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT s.id, s.name, s.genre, s.created_at,
                   COUNT(sg.id) as game_count,
                   (SELECT sg2.cover_url FROM series_games sg2 
                    WHERE sg2.series_id = s.id AND sg2.cover_url IS NOT NULL AND sg2.cover_url != '' 
                    ORDER BY RANDOM() LIMIT 1) as cover_url
            FROM series s
            LEFT JOIN series_games sg ON s.id = sg.series_id
            GROUP BY s.id
            ORDER BY s.name;
        """)
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to get series: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve series")

@app.post("/api/series", response_model=SeriesResponse)
def create_series(data: SeriesBase):
    """Create a new series"""
    try:
        name = data.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Series name cannot be empty")

        conn = get_conn()
        cur = conn.cursor()
        now = datetime.utcnow().isoformat()

        try:
            cur.execute(
                "INSERT INTO series (name, genre, created_at) VALUES (?, ?, ?);",
                (name, data.genre or "", now),
            )
            sid = cur.lastrowid
            conn.commit()
            logger.info(f"Series created: {name}")
        except sqlite3.IntegrityError:
            conn.close()
            raise HTTPException(status_code=409, detail=f"Series '{name}' already exists")

        conn.close()
        return SeriesResponse(id=sid, name=name, genre=data.genre or "", game_count=0, created_at=now)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create series: {e}")
        raise HTTPException(status_code=500, detail="Failed to create series")

@app.put("/api/series/{series_id}", response_model=SeriesResponse)
def update_series(series_id: int, data: SeriesBase):
    """Update a series name or genre"""
    try:
        name = data.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Series name cannot be empty")

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id FROM series WHERE id = ?;", (series_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Series not found")

        cur.execute(
            "UPDATE series SET name = ?, genre = ? WHERE id = ?;",
            (name, data.genre or "", series_id),
        )
        conn.commit()

        cur.execute("SELECT COUNT(*) FROM series_games WHERE series_id = ?;", (series_id,))
        game_count = cur.fetchone()[0]
        cur.execute("SELECT created_at FROM series WHERE id = ?;", (series_id,))
        created_at = cur.fetchone()["created_at"]
        conn.close()

        return SeriesResponse(id=series_id, name=name, genre=data.genre or "", game_count=game_count, created_at=created_at)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update series: {e}")
        raise HTTPException(status_code=500, detail="Failed to update series")

@app.delete("/api/series/{series_id}")
def delete_series(series_id: int):
    """Delete a series and all its entries"""
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id FROM series WHERE id = ?;", (series_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Series not found")

        cur.execute("DELETE FROM series WHERE id = ?;", (series_id,))
        conn.commit()
        conn.close()

        return {"status": "ok", "message": "Series deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete series: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete series")

@app.get("/api/series/{series_id}/games", response_model=List[SeriesGameEntry])
def get_series_games(series_id: int):
    """Get all games in a series, ordered by position"""
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id FROM series WHERE id = ?;", (series_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Series not found")

        cur.execute("""
            SELECT sg.id, sg.series_id, sg.game_id, sg.position, sg.title,
                   sg.cover_url, sg.platform, sg.release_year, sg.rawg_id, sg.is_missing,
                   c.name as console_name
            FROM series_games sg
            LEFT JOIN games g ON sg.game_id = g.id
            LEFT JOIN consoles c ON g.console_id = c.id
            WHERE sg.series_id = ?
            ORDER BY sg.position;
        """, (series_id,))

        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get series games: {e}")
        raise HTTPException(status_code=500, detail="Failed to get series games")

@app.post("/api/series/{series_id}/games", response_model=SeriesGameEntry)
def add_game_to_series(series_id: int, data: SeriesAddGameRequest):
    """Add a game (archive game or missing entry) to a series"""
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id FROM series WHERE id = ?;", (series_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Series not found")

        cur.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM series_games WHERE series_id = ?;", (series_id,))
        next_pos = cur.fetchone()[0]

        # If game_id is provided, verify it exists in archive
        if data.game_id:
            cur.execute("SELECT id, title, cover_url FROM games WHERE id = ?;", (data.game_id,))
            game_row = cur.fetchone()
            if not game_row:
                conn.close()
                raise HTTPException(status_code=404, detail="Game not found in archive")
            # Use archive data as fallback
            if not data.title:
                data.title = game_row["title"]
            if not data.cover_url:
                data.cover_url = game_row["cover_url"]
            is_missing = 0
        else:
            is_missing = 1 if data.is_missing else 0

        cur.execute(
            """INSERT INTO series_games (series_id, game_id, position, title, cover_url, platform, release_year, rawg_id, is_missing)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);""",
            (series_id, data.game_id, next_pos, data.title, data.cover_url, data.platform or "", data.release_year, data.rawg_id, is_missing),
        )
        entry_id = cur.lastrowid
        conn.commit()
        logger.info(f"Game '{data.title}' added to series {series_id}")

        conn.close()
        return SeriesGameEntry(
            id=entry_id, series_id=series_id, game_id=data.game_id,
            position=next_pos, title=data.title, cover_url=data.cover_url,
            platform=data.platform or "", release_year=data.release_year,
            rawg_id=data.rawg_id, is_missing=bool(is_missing),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add game to series: {e}")
        raise HTTPException(status_code=500, detail="Failed to add game to series")

@app.post("/api/series/{series_id}/games/batch")
def add_games_to_series_batch(series_id: int, data: SeriesBulkAddRequest):
    """Add multiple games to a series in one transaction"""
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id FROM series WHERE id = ?;", (series_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Series not found")

        cur.execute("SELECT COALESCE(MAX(position), 0) FROM series_games WHERE series_id = ?;", (series_id,))
        next_pos = cur.fetchone()[0]

        added = 0
        for g in data.games:
            next_pos += 1
            is_missing = 0
            title = g.title
            cover_url = g.cover_url
            game_id = g.game_id

            if game_id:
                cur.execute("SELECT id, title, cover_url FROM games WHERE id = ?;", (game_id,))
                game_row = cur.fetchone()
                if game_row:
                    if not title:
                        title = game_row["title"]
                    if not cover_url:
                        cover_url = game_row["cover_url"]
                    is_missing = 0
                else:
                    is_missing = 1
            else:
                is_missing = 1 if g.is_missing else 0

            cur.execute(
                """INSERT INTO series_games (series_id, game_id, position, title, cover_url, platform, release_year, rawg_id, is_missing)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                (series_id, game_id, next_pos, title, cover_url or "", g.platform or "", g.release_year, g.rawg_id, is_missing),
            )
            added += 1

        conn.commit()
        logger.info(f"Batch added {added} games to series {series_id}")
        conn.close()
        return {"added": added, "series_id": series_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to batch add games to series: {e}")
        raise HTTPException(status_code=500, detail="Failed to batch add games to series")

@app.put("/api/series/{series_id}/games/reorder")
def reorder_series_games(series_id: int, data: SeriesReorderRequest):
    """Reorder games in a series (batch update positions)"""
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id FROM series WHERE id = ?;", (series_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Series not found")

        for item in data.positions:
            cur.execute(
                "UPDATE series_games SET position = ? WHERE id = ? AND series_id = ?;",
                (item["position"], item["id"], series_id),
            )
        conn.commit()
        conn.close()

        return {"status": "ok", "message": "Series games reordered"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reorder series games: {e}")
        raise HTTPException(status_code=500, detail="Failed to reorder series games")

@app.delete("/api/series/{series_id}/games/{entry_id}")
def remove_game_from_series(series_id: int, entry_id: int):
    """Remove a game from a series"""
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute(
            "DELETE FROM series_games WHERE id = ? AND series_id = ?;",
            (entry_id, series_id),
        )

        if cur.rowcount == 0:
            conn.close()
            raise HTTPException(status_code=404, detail="Game entry not found in series")

        conn.commit()
        conn.close()
        return {"status": "ok", "message": "Game removed from series"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to remove game from series: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove game from series")

@app.post("/api/series/{series_id}/games/{entry_id}/add-to-archive")
def add_missing_game_to_archive(series_id: int, entry_id: int):
    """Add a missing game from a series to the archive.

    Finds the best-matching console based on the platform string,
    creates a new game entry, and links it to the series entry.
    """
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Get the series game entry
        cur.execute(
            "SELECT id, title, platform, cover_url, release_year, rawg_id, is_missing FROM series_games WHERE id = ? AND series_id = ?;",
            (entry_id, series_id),
        )
        sg = cur.fetchone()
        if not sg:
            conn.close()
            raise HTTPException(status_code=404, detail="Series game entry not found")
        if not sg["is_missing"]:
            conn.close()
            return {"status": "ok", "message": "Game is already in the archive"}

        platform = (sg["platform"] or "").strip()
        title = sg["title"]

        # Find best matching console
        cur.execute("SELECT id, name FROM consoles;")
        consoles = cur.fetchall()
        console_id = None

        # Score-based matching: exact > substring > partial
        best_score = 0
        for c in consoles:
            cname = c["name"].lower()
            plow = platform.lower()
            if not plow:
                continue
            # Exact match
            if plow == cname:
                console_id = c["id"]
                best_score = 30
                break
            # Platform is substring of console name
            if plow in cname and best_score < 20:
                console_id = c["id"]
                best_score = 20
            # Console name is substring of platform
            elif cname in plow and best_score < 10:
                console_id = c["id"]
                best_score = 10

        if console_id is None:
            conn.close()
            raise HTTPException(
                status_code=400,
                detail=f"No matching console found for platform '{platform}'. Please add a console with that name first.",
            )

        # Create the game in the archive
        now = datetime.utcnow().isoformat()
        folder_name = normalize_title_for_folder(title)
        cur.execute(
            """
            INSERT INTO games (console_id, folder_name, title, genre, description, cover_url, metadata_json, release_year, developer, publisher, created_at, updated_at)
            VALUES (?, ?, ?, NULL, NULL, ?, NULL, ?, NULL, NULL, ?, ?);
            """,
            (console_id, folder_name, title, sg["cover_url"], sg["release_year"], now, now),
        )
        new_game_id = cur.lastrowid

        # Link series entry to the new game
        cur.execute(
            "UPDATE series_games SET game_id = ?, is_missing = 0 WHERE id = ?;",
            (new_game_id, entry_id),
        )

        conn.commit()
        conn.close()
        logger.info(f"Added '{title}' to archive (game_id={new_game_id}, console_id={console_id})")
        return {"status": "ok", "game_id": new_game_id, "console_id": console_id, "title": title}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add missing game to archive: {e}")
        raise HTTPException(status_code=500, detail="Failed to add game to archive")

@app.get("/api/series/expand/{game_id}")
def expand_series_from_game(game_id: int):
    """Fetch all games in the same series from RAWG using a game in the archive"""
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Get the game from archive
        cur.execute("SELECT id, title, metadata_json FROM games WHERE id = ?;", (game_id,))
        game_row = cur.fetchone()
        if not game_row:
            conn.close()
            raise HTTPException(status_code=404, detail="Game not found in archive")

        # Extract rawg_id from metadata JSON file
        rawg_id = None
        meta_path = game_row["metadata_json"]
        if meta_path:
            meta_full = os.path.join(BASE_DIR, meta_path.lstrip("/"))
            if os.path.isfile(meta_full):
                try:
                    with open(meta_full) as f:
                        meta_data = json.load(f)
                    rawg_id = meta_data.get("id")
                except Exception:
                    pass

        if not rawg_id:
            conn.close()
            raise HTTPException(status_code=404, detail="Game has no RAWG ID - fetch metadata first")

        rawg_id = int(rawg_id)

        # Check cache (7-day expiry)
        cache_row = cur.execute(
            "SELECT series_data, fetched_at FROM series_cache WHERE rawg_game_id = ?;",
            (rawg_id,),
        ).fetchone()

        if cache_row:
            fetched_at = datetime.fromisoformat(cache_row["fetched_at"])
            if (datetime.utcnow() - fetched_at).days < 7:
                cached_games = json.loads(cache_row["series_data"])
                # Cross-reference cached results with archive
                game_title_map = {}
                for row in cur.execute("SELECT id, title FROM games").fetchall():
                    game_title_map[row["title"].lower()] = row["id"]
                for g in cached_games:
                    archive_id = game_title_map.get(g["title"].lower())
                    if archive_id:
                        g["archive_game_id"] = archive_id
                        g["in_archive"] = True
                    else:
                        g["in_archive"] = False
                conn.close()
                return {"games": cached_games, "source_rawg_id": rawg_id}

        # Fetch from RAWG
        api_key = get_setting("rawg_api_key")
        if not api_key:
            conn.close()
            raise HTTPException(status_code=400, detail="RAWG API key not configured")

        rawg_url = f"{RAWG_BASE}/games/{rawg_id}/game-series?key={api_key}&page_size=100"
        resp = requests.get(rawg_url, timeout=RAWG_TIMEOUT)
        if resp.status_code != 200:
            conn.close()
            raise HTTPException(status_code=502, detail=f"RAWG API error: {resp.status_code}")

        rawg_data = resp.json()
        results = rawg_data.get("results", [])

        # Process results
        series_games = []
        for g in results:
            # Extract release year
            release_year = None
            if g.get("released"):
                try:
                    release_year = int(g["released"][:4])
                except (ValueError, IndexError):
                    pass

            # Extract primary platform
            platform = ""
            if g.get("platforms") and len(g["platforms"]) > 0:
                platform = g["platforms"][0].get("platform", {}).get("name", "")

            series_games.append({
                "rawg_id": g.get("id"),
                "title": g.get("name", "Unknown"),
                "cover_url": g.get("background_image", ""),
                "platform": platform,
                "release_year": release_year,
            })

        # Sort by release year
        series_games.sort(key=lambda x: x.get("release_year") or 9999)

        # Cross-reference with archive: find which games already exist
        game_title_map = {}
        for row in cur.execute("SELECT id, title FROM games").fetchall():
            game_title_map[row["title"].lower()] = row["id"]

        for g in series_games:
            archive_id = game_title_map.get(g["title"].lower())
            if archive_id:
                g["archive_game_id"] = archive_id
                g["in_archive"] = True
            else:
                g["in_archive"] = False

        # Cache results
        now = datetime.utcnow().isoformat()
        cur.execute(
            "INSERT OR REPLACE INTO series_cache (rawg_game_id, series_data, fetched_at) VALUES (?, ?, ?);",
            (rawg_id, json.dumps(series_games), now),
        )
        conn.commit()
        conn.close()

        return {"games": series_games, "source_rawg_id": rawg_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to expand series: {e}")
        raise HTTPException(status_code=500, detail="Failed to expand series from RAWG")

@app.get("/api/series/search-wikipedia/{series_name}")
def search_wikipedia_series(series_name: str):
    """Search Wikipedia for games in a series/franchise by parsing wikitext tables."""
    try:
        all_found = []
        seen_titles = set()
        search_url = "https://en.wikipedia.org/w/api.php"

        page_names_to_try = [
            f"List of {series_name} video games",
            f"List of {series_name} games",
            f"{series_name} (series)",
            f"{series_name} video game series",
            f"{series_name}",
        ]

        # Also try searching Wikipedia for the right page
        search_params = {
            "action": "query", "format": "json", "list": "search",
            "srsearch": f"{series_name} video game series",
            "srlimit": 5, "redirects": 1, "utf8": 1,
        }
        try:
            sres = requests.get(search_url, params=search_params, timeout=WIKIPEDIA_TIMEOUT, headers=WIKIPEDIA_HEADERS)
            sres.raise_for_status()
            sdata = sres.json()
            if "query" in sdata and "search" in sdata["query"]:
                for sr in sdata["query"]["search"]:
                    t = sr["title"]
                    if t not in page_names_to_try:
                        page_names_to_try.insert(0, t)
        except Exception:
            pass

        series_lower = series_name.lower().strip()

        def clean_wiki_title(raw):
            """Extract a clean title from wikitext markup like ''[[Page|Display]]'' or ''[[Page]]''."""
            t = raw
            t = re.sub(r"''+", "", t)
            pipe_match = re.search(r"\[\[[^\]]*?\|([^\]]+?)\]\]", t)
            if pipe_match:
                t = pipe_match.group(1)
            else:
                link_match = re.search(r"\[\[([^\]]+?)\]\]", t)
                if link_match:
                    t = link_match.group(1)
            t = re.sub(r"\[\[|\]\]", "", t)
            t = re.sub(r"\{\{[^}]*\}\}", "", t)
            t = re.sub(r'<ref[^>]*>.*?</ref>', '', t)
            t = re.sub(r'<ref[^/]*/>', '', t)
            t = t.strip()
            t = re.sub(r"\s+", " ", t)
            return t

        for page_name in page_names_to_try:
            try:
                res = requests.get(search_url, params={
                    "action": "query", "format": "json", "prop": "revisions",
                    "titles": page_name, "rvprop": "content", "rvslots": "main",
                    "utf8": 1, "redirects": 1,
                }, timeout=WIKIPEDIA_TIMEOUT, headers=WIKIPEDIA_HEADERS)
                res.raise_for_status()
                data = res.json()

                if "query" not in data or "pages" not in data["query"]:
                    continue

                pages = data["query"]["pages"]
                page_id = next(iter(pages))
                if int(page_id) < 0:
                    continue

                revisions = pages[page_id].get("revisions")
                if not revisions:
                    continue

                wikitext = revisions[0].get("slots", {}).get("main", {}).get("*", "")
                if not wikitext:
                    continue

                lines = wikitext.split("\n")
                i = 0
                while i < len(lines):
                    line = lines[i].strip()

                    if line.startswith("{|"):
                        header_lines = []
                        row_lines = []
                        rows = []
                        i += 1
                        while i < len(lines) and not lines[i].strip().startswith("|}"):
                            tl = lines[i].strip()
                            if tl.startswith("!"):
                                header_lines.append(tl)
                            elif tl.startswith("|-"):
                                if row_lines:
                                    rows.append(row_lines)
                                row_lines = []
                            elif tl.startswith("|"):
                                row_lines.append(tl)
                            i += 1
                        if row_lines:
                            rows.append(row_lines)

                        # Parse headers: "! Games" or "! Games !! Year"
                        headers_text = []
                        for hl in header_lines:
                            parts = [p.strip().lower() for p in hl.lstrip("!").split("!!")]
                            headers_text.extend(parts)

                        games_col = -1
                        year_col = -1
                        for idx, h in enumerate(headers_text):
                            if h in ("games", "title", "name", "game", "game title"):
                                games_col = idx
                            if h in ("year", "release year", "release", "released", "date"):
                                year_col = idx

                        if games_col < 0:
                            continue

                        for row in rows:
                            # Each cell starts with "| "
                            cells = []
                            for cell_line in row:
                                cell = cell_line.lstrip("|").strip()
                                cells.append(cell)

                            if len(cells) <= games_col:
                                continue

                            raw_title = cells[games_col]
                            title = clean_wiki_title(raw_title)

                            if not title or len(title) < 2 or len(title) > 80:
                                continue

                            lower = title.lower()
                            skip_words = [
                                "video game", "game series", "list of", "see also",
                                "reception", "gameplay", "development", "compilation",
                                "the series", "the game", "spin-off", "soundtrack",
                            ]
                            if any(sw in lower for sw in skip_words):
                                continue

                            # Extract year
                            release_year = None
                            if year_col >= 0 and len(cells) > year_col:
                                year_match = re.search(r"(\d{4})", cells[year_col])
                                if year_match:
                                    y = int(year_match.group(1))
                                    if 1980 <= y <= 2030:
                                        release_year = y

                            if re.match(r"^[IVXLCDM]+$", title):
                                title = f"{series_name} {title}"
                            elif not any(sw in lower for sw in series_lower.split()):
                                if len(title) < 25:
                                    title = f"{series_name} {title}"

                            title_key = title.lower().strip()
                            if title_key not in seen_titles:
                                seen_titles.add(title_key)
                                all_found.append({
                                    "title": title,
                                    "release_year": release_year,
                                    "cover_url": "",
                                    "platform": "",
                                    "source": "wikipedia",
                                })

                    i += 1

                # Also parse {{Video game titles/item}} templates (used by Final Fantasy page)
                if not all_found:
                    template_pattern = re.compile(
                        r'\{\{Video game titles/item\s*\n'
                        r'((?:\|[^}]+\n?)+)',
                        re.IGNORECASE
                    )
                    for tm in template_pattern.finditer(wikitext):
                        block = tm.group(1)
                        title = ""
                        release_year = None

                        title_match = re.search(r'\|title\s*=\s*(.+)', block)
                        if title_match:
                            title = clean_wiki_title(title_match.group(1).strip())
                        else:
                            article_match = re.search(r'\|article\s*=\s*(.+)', block)
                            if article_match:
                                title = clean_wiki_title(article_match.group(1).strip())

                        release_match = re.search(r'\|release\s*=\s*(\d{4})', block)
                        if release_match:
                            y = int(release_match.group(1))
                            if 1980 <= y <= 2030:
                                release_year = y

                        if not title or len(title) < 2 or len(title) > 80:
                            continue

                        title_key = title.lower().strip()
                        if title_key not in seen_titles:
                            seen_titles.add(title_key)
                            all_found.append({
                                "title": title,
                                "release_year": release_year,
                                "cover_url": "",
                                "platform": "",
                                "source": "wikipedia",
                            })

                if all_found:
                    break

            except Exception as e:
                logger.debug(f"Wikipedia page parse failed for '{page_name}': {e}")
                continue

        all_found.sort(key=lambda x: x.get("release_year") or 9999)
        return {"games": all_found, "total": len(all_found)}
    except Exception as e:
        logger.error(f"Wikipedia series search failed: {e}")
        raise HTTPException(status_code=500, detail="Wikipedia search failed")

# -------------------------------------------------------------------
# API: Series Metadata Fetch
# -------------------------------------------------------------------

@app.get("/api/series/{series_id}/fetch-metadata")
def fetch_series_metadata(series_id: int):
    """Fetch release_year for series games from their metadata JSON files or RAWG."""
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id FROM series WHERE id = ?;", (series_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Series not found")

        cur.execute("""
            SELECT sg.id, sg.game_id, sg.title, sg.release_year, g.metadata_json
            FROM series_games sg
            LEFT JOIN games g ON sg.game_id = g.id
            WHERE sg.series_id = ? AND sg.release_year IS NULL;
        """, (series_id,))
        rows = cur.fetchall()

        updated = 0
        for r in rows:
            release_year = None

            # Try reading from metadata JSON file first
            if r["metadata_json"]:
                meta_full = os.path.join(BASE_DIR, r["metadata_json"].lstrip("/"))
                if os.path.isfile(meta_full):
                    try:
                        with open(meta_full) as f:
                            meta = json.load(f)
                        released = meta.get("released", "")
                        if released:
                            release_year = int(released.split("-")[0])
                    except Exception:
                        pass

            # Fallback: search RAWG by title
            if release_year is None:
                try:
                    rawg_game = fetch_rawg_game(r["title"])
                    if rawg_game:
                        released = rawg_game.get("released", "")
                        if released:
                            release_year = int(released.split("-")[0])
                except Exception:
                    pass

            if release_year is not None:
                cur.execute(
                    "UPDATE series_games SET release_year = ? WHERE id = ?;",
                    (release_year, r["id"]),
                )
                updated += 1

        conn.commit()
        conn.close()
        return {"updated": updated}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch series metadata: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch series metadata")

# -------------------------------------------------------------------
# API: Metadata Filters
# -------------------------------------------------------------------

@app.get("/api/metadata-filters")
def get_metadata_filters():
    """Get distinct decade, developer, publisher values for filtering."""
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Decades
        decades = {}
        for row in cur.execute("SELECT release_year FROM games WHERE release_year IS NOT NULL").fetchall():
            decade = f"{(row['release_year'] // 10) * 10}s"
            decades[decade] = decades.get(decade, 0) + 1

        # Developers
        developers = {}
        for row in cur.execute("SELECT developer FROM games WHERE developer IS NOT NULL AND developer != ''").fetchall():
            for dev in row["developer"].split(","):
                dev = dev.strip()
                if dev:
                    developers[dev] = developers.get(dev, 0) + 1

        # Publishers
        publishers = {}
        for row in cur.execute("SELECT publisher FROM games WHERE publisher IS NOT NULL AND publisher != ''").fetchall():
            for pub in row["publisher"].split(","):
                pub = pub.strip()
                if pub:
                    publishers[pub] = publishers.get(pub, 0) + 1

        conn.close()

        return {
            "decades": [{"value": k, "count": v} for k, v in sorted(decades.items(), reverse=True)],
            "developers": [{"value": k, "count": v} for k, v in sorted(developers.items(), key=lambda x: -x[1])],
            "publishers": [{"value": k, "count": v} for k, v in sorted(publishers.items(), key=lambda x: -x[1])],
        }
    except Exception as e:
        logger.error(f"Failed to get metadata filters: {e}")
        raise HTTPException(status_code=500, detail="Failed to get metadata filters")

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
            is_on_hold=bool(row["is_on_hold"]),
            notes=row["notes"],
            is_printed=bool(row["is_printed"]),
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
        if data.notes is not None:
            updates.append("notes = ?")
            params.append(data.notes)
        if data.is_printed is not None:
            updates.append("is_printed = ?")
            params.append(1 if data.is_printed else 0)
        
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
                   g.release_year, g.publisher, g.developer,
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
            console_name=r["console_name"],
            release_year=r["release_year"],
            publisher=r["publisher"],
            developer=r["developer"],
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
            SELECT g.id, g.title, g.genre, g.cover_url, c.name as console_name,
                   g.release_year, g.publisher, g.developer
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
            console_name=r["console_name"],
            release_year=r["release_year"],
            publisher=r["publisher"],
            developer=r["developer"],
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
