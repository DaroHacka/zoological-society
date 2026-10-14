Console & Computer Icon Naming Guide
======================================

Name your icon files so the script can auto-match them
to your consoles. The matching is case-insensitive and
ignores all non-alphanumeric characters (spaces, hyphens,
underscores, etc.).

MATCHING RULES (in order of priority)
--------------------------------------
1. Exact match: icon name = console name (best)
   e.g. "nes.png"  matches  "NES"

2. Console name contained in icon name (good)
   e.g. "nintendo 3ds.png"  matches  "Nintendo 3DS"
        "sega genesis.png"  matches  "SEGA Genesis"

3. Icon name contained in console name (fallback)
   e.g. "psp.png"     matches  "Sony PSP"   (psp is in sonypsp)
        "vita.png"    matches  "Sony Vita"  (vita is in sonyvita)
        "playstation.png"  matches  "Sony Playstation" (playstation is in sonyplaystation)

IMPORTANT: Use the ACTUAL device name, not an abbreviation.
-----------------------------------------------------------------
|  USE THIS              |  NOT THIS          |  WHY              |
|------------------------|------------------- |-------------------|
|  gameboy.png           |  gb.png            |  "gb" is not in   |
|  gameboy advance.png   |  gba.png           |  "gameboy"         |
|  playstation.png       |  playstation one   |  "one" is extra   |
|  psp.png               |  playstation psp   |  "playstation"    |
|  vita.png              |  playstation vita  |  is extra         |
-----------------------------------------------------------------

SUPPORTED FORMATS
------------------
.png (preferred), .jpg, .jpeg, .gif, .webp

HOW IT WORKS
-------------
Just drop an icon file into this folder and it is picked up
automatically for every console whose name matches -- no
server restart or database changes needed.
