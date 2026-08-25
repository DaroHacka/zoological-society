"""
Canonical console catalog for the Video Game Archive.

Each entry pairs a canonical slug with a display name, known aliases,
and the corresponding TheGamesDB / RAWG platform ids (verified live
against both APIs in Aug 2026). A None id means the provider does not
have that platform; cover/screenshot fetching must skip that provider
for such consoles instead of guessing (wrong-console results).

The slug is the stable identity of a console: display names can be
renamed freely without breaking metadata/cover lookups, and deleting
and re-adding a console resolves back to the same catalog entry.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional


class CatalogEntry:
    __slots__ = ("slug", "name", "aliases", "tgdb_id", "rawg_id")

    def __init__(self, slug, name, aliases=None, tgdb_id=None, rawg_id=None):
        self.slug = slug
        self.name = name
        self.aliases = [a.lower() for a in (aliases or [])]
        self.tgdb_id = tgdb_id
        self.rawg_id = rawg_id

    def to_dict(self):
        return {
            "slug": self.slug,
            "name": self.name,
            "aliases": self.aliases,
            "tgdb_id": self.tgdb_id,
            "rawg_id": self.rawg_id,
        }


def _e(slug, name, aliases=None, tgdb=None, rawg=None):
    return CatalogEntry(slug, name, aliases, tgdb, rawg)


CATALOG = [
    # ------------------------------------------------------------- Nintendo
    _e("nes", "Nintendo Entertainment System (NES)",
       ["nes", "nintendo entertainment system", "famicom"], tgdb=7, rawg=49),
    _e("snes", "Super Nintendo (SNES)",
       ["snes", "super nintendo", "super famicom", "super nintendo entertainment system"], tgdb=6, rawg=79),
    _e("n64", "Nintendo 64",
       ["n64", "nintendo 64", "ultra 64"], tgdb=3, rawg=83),
    _e("gamecube", "Nintendo GameCube",
       ["gamecube", "nintendo gamecube", "ngc", "dolphin"], tgdb=2, rawg=105),
    _e("wii", "Nintendo Wii",
       ["wii", "nintendo wii"], tgdb=9, rawg=11),
    _e("wii-u", "Nintendo Wii U",
       ["wii u", "wiiu", "nintendo wii u"], tgdb=38, rawg=10),
    _e("switch", "Nintendo Switch",
       ["switch", "nintendo switch", "nsw"], tgdb=4971, rawg=7),
    _e("switch-2", "Nintendo Switch 2",
       ["switch 2", "nintendo switch 2"], tgdb=5021, rawg=None),
    _e("gameboy", "Nintendo Game Boy",
       ["gameboy", "game boy", "gb", "nintendo gameboy", "game boy pocket"], tgdb=4, rawg=26),
    _e("gameboy-color", "Nintendo Game Boy Color",
       ["gbc", "gameboy color", "game boy color", "nintendo gameboy color"], tgdb=41, rawg=43),
    _e("gba", "Nintendo Game Boy Advance",
       ["gba", "gameboy advance", "game boy advance", "nintendo gameboy advance"], tgdb=5, rawg=24),
    _e("nds", "Nintendo DS",
       ["nds", "nintendo ds", "ds"], tgdb=8, rawg=9),
    _e("3ds", "Nintendo 3DS",
       ["3ds", "nintendo 3ds", "citra"], tgdb=4912, rawg=8),
    _e("virtual-boy", "Nintendo Virtual Boy",
       ["virtual boy", "vboy", "nintendo virtual boy"], tgdb=4918, rawg=None),
    _e("fds", "Famicom Disk System",
       ["fds", "famicom disk system"], tgdb=4936, rawg=None),
    _e("game-and-watch", "Nintendo Game & Watch",
       ["game & watch", "game and watch"], tgdb=4950, rawg=None),

    # ----------------------------------------------------------------- Sega
    _e("sg-1000", "SEGA SG-1000",
       ["sg-1000", "sg1000", "sega sg-1000"], tgdb=4949, rawg=None),
    _e("master-system", "SEGA Master System",
       ["sms", "master system", "sega master system", "mark iii", "mark 3"], tgdb=35, rawg=74),
    _e("genesis", "SEGA Genesis / Mega Drive",
       ["genesis", "sega genesis", "mega drive", "megadrive", "sega mega drive"], tgdb=18, rawg=167),
    _e("sega-cd", "SEGA CD / Mega-CD",
       ["sega cd", "megacd", "mega-cd", "mega cd"], tgdb=21, rawg=119),
    _e("sega-32x", "SEGA 32X",
       ["32x", "sega 32x", "mega drive 32x", "genesis 32x"], tgdb=33, rawg=117),
    _e("saturn", "SEGA Saturn",
       ["saturn", "sega saturn"], tgdb=17, rawg=107),
    _e("dreamcast", "SEGA Dreamcast",
       ["dreamcast", "sega dreamcast"], tgdb=16, rawg=106),
    _e("game-gear", "SEGA Game Gear",
       ["game gear", "gamegear", "sega game gear"], tgdb=20, rawg=77),
    _e("sega-pico", "SEGA Pico",
       ["pico", "sega pico"], tgdb=4958, rawg=None),

    # ---------------------------------------------------------------- Sony
    _e("psx", "Sony PlayStation",
       ["sony playstation", "playstation", "ps1", "psx", "playstation 1"], tgdb=10, rawg=27),
    _e("ps2", "Sony PlayStation 2",
       ["ps2", "playstation 2", "sony playstation 2"], tgdb=11, rawg=15),
    _e("ps3", "Sony PlayStation 3",
       ["ps3", "playstation 3", "sony playstation 3"], tgdb=12, rawg=16),
    _e("ps4", "Sony PlayStation 4",
       ["ps4", "playstation 4", "sony playstation 4"], tgdb=4919, rawg=18),
    _e("ps5", "Sony PlayStation 5",
       ["ps5", "playstation 5", "sony playstation 5"], tgdb=4980, rawg=187),
    _e("psp", "Sony PlayStation Portable",
       ["psp", "playstation portable", "sony psp"], tgdb=13, rawg=17),
    _e("ps-vita", "Sony PlayStation Vita",
       ["ps vita", "psvita", "vita", "playstation vita"], tgdb=39, rawg=19),

    # ----------------------------------------------------------- Microsoft
    _e("xbox", "Microsoft Xbox",
       ["xbox", "original xbox", "microsoft xbox", "xbx"], tgdb=14, rawg=80),
    _e("xbox-360", "Microsoft Xbox 360",
       ["xbox 360", "x360", "xb360"], tgdb=15, rawg=14),
    _e("xbox-one", "Microsoft Xbox One",
       ["xbox one", "xbone", "xone"], tgdb=4920, rawg=1),
    _e("xbox-series", "Microsoft Xbox Series X|S",
       ["xbox series x", "xbox series s", "series x", "series s", "xbox series"], tgdb=4981, rawg=186),

    # ---------------------------------------------------------- NEC Hudson
    _e("pc-engine-tg16", "TurboGrafx-16 / PC Engine",
       ["turbografx-16", "turbografx 16", "pc engine", "turbo-grafx 16",
        "turbografx-16 - pc engine", "tg16", "pce"], tgdb=34, rawg=None),
    _e("pc-engine-cd", "TurboGrafx-16 CD / PC Engine CD",
       ["turbografx cd", "turbografx-16 cd", "pc engine cd", "cd-rom²",
        "turbografx-16 - pc engine cd", "tg16 cd", "pscd"], tgdb=4955, rawg=None),
    _e("supergrafx", "PC Engine SuperGrafx",
       ["supergrafx", "super grafx", "sgx"], tgdb=None, rawg=None),
    _e("pc-fx", "PC-FX",
       ["pc-fx", "pcfx"], tgdb=4930, rawg=None),

    # ----------------------------------------------------------------- SNK
    _e("neo-geo", "SNK Neo Geo",
       ["neo geo", "neogeo", "neo geo aes", "neo geo mvs", "mvs"], tgdb=24, rawg=12),
    _e("neo-geo-cd", "SNK Neo Geo CD",
       ["neo geo cd", "neogeo cd"], tgdb=4956, rawg=None),
    _e("neo-geo-pocket", "SNK Neo Geo Pocket",
       ["neo geo pocket", "ngp"], tgdb=4922, rawg=None),
    _e("neo-geo-pocket-color", "SNK Neo Geo Pocket Color",
       ["neo geo pocket color", "ngpc"], tgdb=4923, rawg=None),

    # -------------------------------------------------------------- Atari
    _e("atari-2600", "Atari 2600",
       ["atari 2600", "2600", "atari vcs"], tgdb=22, rawg=23),
    _e("atari-5200", "Atari 5200",
       ["atari 5200"], tgdb=26, rawg=31),
    _e("atari-7800", "Atari 7800",
       ["atari 7800", "7800 prosystem"], tgdb=27, rawg=28),
    _e("atari-xegs", "Atari XEGS",
       ["xe", "atari xe", "xegs", "atari xegs"], tgdb=30, rawg=50),
    _e("atari-8-bit", "Atari 8-bit computers",
       ["atari 800", "atari 800xl", "atari 130xe", "atari 65xe", "atari 400",
        "atari 8-bit", "atari 8 bit"], tgdb=4943, rawg=25),
    _e("atari-st", "Atari ST",
       ["atari st", "atarist", "atari ste", "atari tt", "falcon"], tgdb=4937, rawg=34),
    _e("jaguar", "Atari Jaguar",
       ["jaguar", "atari jaguar"], tgdb=28, rawg=112),
    _e("jaguar-cd", "Atari Jaguar CD",
       ["jaguar cd", "atari jaguar cd"], tgdb=29, rawg=None),
    _e("atari-lynx", "Atari Lynx",
       ["lynx", "atari lynx"], tgdb=4924, rawg=46),
    _e("atari-flashback", "Atari Flashback",
       ["flashback", "atari flashback"], tgdb=None, rawg=22),

    # ----------------------------------------------- Other consoles / systems
    _e("colecovision", "ColecoVision",
       ["colecovision", "coleco vision"], tgdb=31, rawg=None),
    _e("intellivision", "Mattel Intellivision",
       ["intellivision"], tgdb=32, rawg=None),
    _e("vectrex", "GCE Vectrex",
       ["vectrex"], tgdb=4939, rawg=None),
    _e("3do", "3DO Interactive Multiplayer",
       ["3do", "panasonic 3do", "3d0"], tgdb=25, rawg=111),
    _e("cd-i", "Philips CD-i",
       ["cd-i", "cdi", "philips cd-i"], tgdb=4917, rawg=None),
    _e("odyssey-2", "Magnavox Odyssey 2",
       ["odyssey 2", "odyssey2", "videopac", "magnavox odyssey 2"], tgdb=4927, rawg=None),
    _e("channel-f", "Fairchild Channel F",
       ["channel f", "ves"], tgdb=4928, rawg=None),
    _e("arcade", "Arcade",
       ["arcade", "arcades", "mame"], tgdb=23, rawg=None),
    _e("wonderswan", "Bandai WonderSwan",
       ["wonderswan", "wonder swan"], tgdb=4925, rawg=None),
    _e("wonderswan-color", "Bandai WonderSwan Color",
       ["wonderswan color", "wonder swan color", "swancrystal"], tgdb=4926, rawg=None),
    _e("ngage", "Nokia N-Gage",
       ["n-gage", "ngage"], tgdb=4938, rawg=None),
    _e("playdate", "Playdate",
       ["playdate"], tgdb=5016, rawg=None),
    _e("evercade", "Evercade",
       ["evercade"], tgdb=4985, rawg=None),
    _e("ouya", "Ouya",
       ["ouya"], tgdb=4921, rawg=None),
    _e("amstrad-gx4000", "Amstrad GX4000",
       ["gx4000", "amstrad gx4000"], tgdb=4999, rawg=None),
    _e("casio-pv-1000", "Casio PV-1000",
       ["pv-1000"], tgdb=4964, rawg=None),
    _e("arcadia-2001", "Emerson Arcadia 2001",
       ["arcadia 2001", "arcadia"], tgdb=4963, rawg=None),
    _e("astrocade", "Bally Astrocade",
       ["astrocade", "bally astrocade", "bally professional arcade"], tgdb=4968, rawg=None),
    _e("supervision", "Watara Supervision",
       ["watara supervision", "supervision"], tgdb=4959, rawg=None),
    _e("gamate", "Bit Corp Gamate",
       ["gamate"], tgdb=5004, rawg=None),
    _e("mega-duck", "Mega Duck / Cougar Boy",
       ["mega duck", "cougar boy"], tgdb=4948, rawg=None),
    _e("pokemon-mini", "Nintendo Pokémon Mini",
       ["pokémon mini", "pokemon mini"], tgdb=4957, rawg=None),
    _e("playdia", "Bandai Playdia",
       ["playdia"], tgdb=5000, rawg=None),
    _e("apple-pippin", "Apple Pippin",
       ["pippin", "bandai pippin", "apple pippin", "atworld"], tgdb=5001, rawg=None),

    # ------------------------------------------------------------ Computers
    _e("pc", "PC (Windows / DOS)",
       ["pc", "windows", "dos", "ms-dos", "steam deck", "pc dos"], tgdb=1, rawg=4),
    _e("pc-steam-deck", "PC - Steam Deck",
       ["pc - steam deck", "steam deck"], tgdb=1, rawg=4),
    _e("mac", "Apple Macintosh",
       ["mac", "macintosh", "macos", "os x"], tgdb=37, rawg=55),
    _e("linux", "Linux",
       ["linux"], tgdb=None, rawg=6),
    _e("ios", "iOS",
       ["ios", "iphone", "ipad"], tgdb=4915, rawg=3),
    _e("android", "Android",
       ["android"], tgdb=4916, rawg=21),
    _e("commodore-64", "Commodore 64",
       ["c64", "commodore 64", "c64c", "c64dx"], tgdb=40, rawg=None),
    _e("commodore-128", "Commodore 128",
       ["c128", "commodore 128"], tgdb=4946, rawg=None),
    _e("commodore-16", "Commodore 16",
       ["c16", "commodore 16"], tgdb=5006, rawg=None),
    _e("commodore-plus4", "Commodore Plus/4",
       ["plus/4", "plus 4", "c264"], tgdb=5007, rawg=None),
    _e("vic-20", "Commodore VIC-20",
       ["vic-20", "vic20", "vc 20"], tgdb=4945, rawg=None),
    _e("commodore-pet", "Commodore PET",
       ["pet", "cbm"], tgdb=5008, rawg=None),
    _e("amiga", "Commodore Amiga",
       ["amiga", "commodore amiga", "amiga 500", "amiga 600", "amiga 1200",
        "amiga 4000", "a500", "a1200", "cdtv"], tgdb=4911, rawg=166),
    _e("amiga-cd32", "Amiga CD32",
       ["cd32", "amiga cd32"], tgdb=4947, rawg=None),
    _e("zx-spectrum", "Sinclair ZX Spectrum",
       ["zx spectrum", "spectrum", "speccy", "zx spectre"], tgdb=4913, rawg=None),
    _e("zx81", "Sinclair ZX81",
       ["zx81", "zx 81", "ts1000", "timex sinclair 1000"], tgdb=5010, rawg=None),
    _e("zx80", "Sinclair ZX80",
       ["zx80", "zx 80"], tgdb=5009, rawg=None),
    _e("sinclair-ql", "Sinclair QL",
       ["ql", "sinclair ql"], tgdb=5020, rawg=None),
    _e("jupiter-ace", "Jupiter Ace",
       ["jupiter ace"], tgdb=5019, rawg=None),
    _e("amstrad-cpc", "Amstrad CPC",
       ["amstrad cpc", "cpc", "cpc464", "cpc664", "cpc6128", "colour personal computer"],
       tgdb=4914, rawg=None),
    _e("bbc-micro", "BBC Micro",
       ["bbc micro", "bbc model b", "bbcmicro"], tgdb=5013, rawg=None),
    _e("acorn-electron", "Acorn Electron",
       ["electron", "acorn electron"], tgdb=4954, rawg=None),
    _e("acorn-atom", "Acorn Atom",
       ["atom", "acorn atom"], tgdb=5014, rawg=None),
    _e("archimedes", "Acorn Archimedes",
       ["archimedes", "acorn archimedes", "risc os"], tgdb=4944, rawg=None),
    _e("msx", "MSX",
       ["msx", "msx2", "msx2+", "msxr"], tgdb=4929, rawg=None),
    _e("sharp-x68000", "Sharp X68000",
       ["x68000", "x68k", "sharp x68000"], tgdb=4931, rawg=None),
    _e("pc-88", "NEC PC-88",
       ["pc-88", "pc88", "pc 8801"], tgdb=4933, rawg=None),
    _e("pc-98", "NEC PC-98",
       ["pc-98", "pc98", "pc 9801"], tgdb=4934, rawg=None),
    _e("sharp-x1", "Sharp X1",
       ["x1", "sharp x1", "cz-800"], tgdb=4977, rawg=None),
    _e("fm-7", "Fujitsu FM-7",
       ["fm-7", "fm7", "fm 7"], tgdb=4978, rawg=None),
    _e("fm-towns-marty", "FM Towns Marty",
       ["fm towns marty", "marty", "fmtowns"], tgdb=4932, rawg=None),
    _e("apple-ii", "Apple II",
       ["apple ii", "apple 2", "apple ][", "iie", "iigs"], tgdb=4942, rawg=41),
    _e("trs-80-coco", "TRS-80 Color Computer",
       ["coco", "trs-80 coco", "tandy color computer"], tgdb=4941, rawg=None),
    _e("dragon", "Dragon 32/64",
       ["dragon 32", "dragon 64", "dragon"], tgdb=4952, rawg=None),
    _e("ti-99-4a", "Texas Instruments TI-99/4A",
       ["ti-99", "ti99", "ti-99/4a"], tgdb=4953, rawg=None),
    _e("sam-coupe", "SAM Coupé",
       ["sam coupe", "samco", "sam coupé"], tgdb=4979, rawg=None),
    _e("oric", "Tangerine Oric",
       ["oric-1", "oric atmos", "oric"], tgdb=4986, rawg=None),
    _e("aquarius", "Mattel Aquarius",
       ["aquarius"], tgdb=4989, rawg=None),
    _e("thomson", "Thomson MO/TO series",
       ["thomson mo5", "thomson to7", "thomson"], tgdb=5022, rawg=None),
]

_BY_SLUG = {e.slug: e for e in CATALOG}


def _normalize(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[’'`]", "", s)
    s = re.sub(r"[^a-z0-9+/| ]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def get_by_slug(slug: str) -> Optional[CatalogEntry]:
    return _BY_SLUG.get(slug)


def all_entries():
    return list(CATALOG)


def find_by_name(console_name: str) -> Optional[CatalogEntry]:
    """Resolve a free-text console name to a catalog entry.

    Strategy: exact normalized match on name/alias first, then unique
    containment, then fuzzy similarity >= 0.82. Returns None when unsure.
    """
    if not console_name:
        return None
    norm = _normalize(console_name)
    if not norm:
        return None

    index_exact = {}
    contains_index = []
    for e in CATALOG:
        candidates = [_normalize(e.name)] + [_normalize(a) for a in e.aliases]
        for cand in candidates:
            index_exact[cand] = e
            contains_index.append((cand, e))

    hit = index_exact.get(norm)
    if hit:
        return hit

    # Containment: candidate inside query or query inside candidate,
    # require length >= 4 to avoid trivial matches like 'pc'
    starts = [(len(cand), e) for cand, e in contains_index
              if len(cand) >= 4 and (cand in norm)]
    if len(starts) == 1:
        return starts[0][1]
    if starts:
        best_len = max(l for l, _ in starts)
        best = [e for l, e in starts if l == best_len]
        if len(best) == 1:
            return best[0]

    # Fuzzy
    best_e, best_score = None, 0.0
    seen = set()
    for cand, e in contains_index:
        if e.slug in seen:
            continue
        score = SequenceMatcher(None, norm, cand).ratio()
        if score > best_score:
            best_score, best_e = score, e
        seen.add(e.slug)
    if best_score >= 0.82:
        return best_e
    return None


def suggest(console_name: str, limit: int = 6):
    """Return up to `limit` (entry, score) suggestions for a name."""
    norm = _normalize(console_name or "")
    scored = []
    seen = set()
    for e in CATALOG:
        if e.slug in seen:
            continue
        seen.add(e.slug)
        candidates = [_normalize(e.name)] + [_normalize(a) for a in e.aliases]
        score = max(SequenceMatcher(None, norm, c).ratio() for c in candidates) if norm else 0.0
        scored.append((score, e))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [(e, round(s, 2)) for s, e in scored[:limit]]
