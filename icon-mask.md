# How runtime icon colouring works (CSS mask technique)

This document explains the technique used in this project to recolour design‑time
black icons / line‑art and turn them into the user's chosen theme colour (or a
gradient) — **without ever editing the original SVG or PNG files**.

---

## 1. The problem

The app's UI uses dozens of small icon images (folder, series, collection,
console, genre, cog, etc.). Design‑time they are almost always **pure black
glyphs** sitting on a transparent background, e.g. the genre icons
`ico/genre/g01.png`, the rotating console button icons `ico/consoles/c01.svg`,
or top‑level SVGs like `ico/series.svg`.

We wanted the user to be able to pick *any* colour (or a two‑colour gradient) in
the Settings panel and have every icon change instantly.

There are two classic ways to do that:

| Approach | What it means | Downside |
|----------|----------------|----------|
| **Edit the images** | Rewrite every `.svg` (`fill="#000"` → `currentColor`) or every `.png` pixel | 20+ files, opaque to PNG, ugly, hard to undo, no runtime "live" preview, gradient impossible |
| **CSS mask** | Use the image only as a *shape*, and paint that shape ourselves | Only works if the source is line‑art (monochrome) — see §3 |

This project uses the CSS mask approach.

---

## 2. What a "coloured icon" is vs. "line‑art"

An image pixel can carry two independent pieces of information:

- **Luminance / chroma** — *what* colour the pixel is (its RGB values).
- **Alpha** — *how visible / opaque* the pixel is (transparency).

### Line‑art icons (recolour‑friendly)

- Consist of essentially **one colour** per glyph (usually black or white).
- All the *shape* information lives in the **alpha (transparency) channel**:
  `alpha=0` where the paper is empty, `alpha=1` where the ink is.
  (PNGs are stored against a transparent background, and SVG icons are composed
  of paths with a single `fill`.)

Because the shape is encoded purely in alpha, the actual colour of the ink is
**irrelevant**. You can throw it away entirely and paint the same shape in any
colour you want. That's exactly what we do.

> SVG note: an icon like `c01.svg` is literally a set of `<path>`s with
> `fill="#000000"`. The "image" is the *union of those path areas*; black is only
> a nominal default. Some are even drawn as `white` on transparent, which is
> invisible on a white page but becomes apparent if you darken the background.

### Coloured / photographic icons (NOT recolor‑friendly)

- E.g. the console **model** logos in `console icons/` (Playstation, SNES,
  Dreamcast…): multi‑colour *brand* images with **hue variation and gradients**.
- Their meaning is encoded in the colour itself (the PlayStation logo is
  *blue because it's blue*, not because it happens to be black).
- The alpha channel still defines the silhouette, but the silhouette is only a
  rough outline — recolouring it would produce a flat, monochrome silhouette,
  losing the brand identity. There is no single "ink colour" to replace.

That is the key difference and why we recolor one kind and never touch the other:

| | Line‑art icon | Coloured/brand icon |
|---|---|---|
| Shape lives in | alpha channel | alpha + colour together |
| Replacing colour | safe, preserves shape | destructive, loses identity |
| CSS mask rebuild | ✔ perfect result | ✘ flat wrong‑looking silhouette |

---

## 3. The CSS mask mechanism (how it works)

CSS `mask` is the mirror image of `background`:

- `background-image` paints an image *inside* the element.
- `mask-image: url(...)` defines a **stencil hole** the element's contents must
  pass through. Pixels of the mask that are **opaque** keep the element's
  content visible; pixels that are **transparent in alpha** cut the content away.

So if we set:

```css
.element {
  background: red;              /* whatever colour we want to paint */
  mask: url("ico/series.svg") no-repeat center / contain;
}
```

the browser:
1. Renders the element's background (`red`) over its whole box;
2. Loads `ico/series.svg` and uses **its alpha channel** as the stencil;
3. Keeps only the red pixels that coincide with the non‑transparent ink of the
   icon → it **looks like** the original icon, but in red.

The original image is never modified; it is referenced *by URL* exactly as an
`<img>` would be, but used as a mask instead of being displayed.

### Why this paints in colour/gradient so easily

Because the element still shows its **own** background, the colour is just
regular CSS. That means:

```css
/* solid fill from a CSS variable — theme‑aware */
background: var(--icon-fill);

/* or any valid CSS gradient */
background: linear-gradient(135deg, #e74c3c, #f1c40f);
```

gives you the icon in a **gradient** with zero image editing — something that
would be extremely painful (dirty, aliased PNGs) if done in the images
themselves.

---

## 4. How it's wired up in this project

### CSS variables (style.css `:root`)

```css
--icon-fill: #ffffff;   /* colour painted inside the mask */
--icon-mask: none;      /* default: no mask applied */
```

### The `.mask-icon` class (style.css:356)

```css
.mask-icon {
  display: inline-block;
  background: var(--icon-fill);
  background-color: var(--icon-fill);
  -webkit-mask: var(--icon-mask);
  mask: var(--icon-mask);
  -webkit-mask-repeat: no-repeat;
  mask-repeat: no-repeat;
  -webkit-mask-position: center;
  mask-position: center;
  -webkit-mask-size: contain;
  mask-size: contain;
  transition: background-color 0.2s, background 0.2s;
  vertical-align: middle;
}
```

Each masked icon is a `<span class="mask-icon">` whose `--icon-mask` is set
*inline* to the icon's URL:

```js
span.style.setProperty("--icon-mask", `url("${abs}") center / contain no-repeat`);
```

So the class provides the fill + mask-repeat/position/size defaults, and the
inline variable provides *which* icon shape.

### Runtime swap: `<img>` → masked `<span>` (app.v2.js:6167)

At startup and whenever the DOM changes, every `<img>` is checked:

```js
function isLineArtIconEl(img) {
  const src = img.getAttribute("src") || "";
  const abs = toAbsoluteUrl(src);
  if (/logo\.png/.test(abs) || /zoological/i.test(abs)) return false;   // keep logos
  const isTopLevelSvg   = /\/ico\/[^/]+\.svg(\?|$)/.test(abs);
  const isRotatingIcon  = /\/ico\/(consoles|genre)\/[^/]+\.(svg|png)(\?|$)/.test(abs);
  return isTopLevelSvg || isRotatingIcon;                                 // only line‑art
}
```

Only images whose URL matches the **line‑art** locations (`/ico/*`, rotating
`/ico/consoles` and `/ico/genre` button icons) are candidates. The console
**model** logos in `/icons/` (the brand‑coloured ones) never match, so they are
left as normal `<img>` tags — this is the crux from §2. The matcher is a white‑
list of *art directories*, because "is it line‑art?" is a property of the source
file, not pixels we can afford to scan blindly at runtime.

For a candidate, `convertLineArtIcon` builds a `<span class="mask-icon">`, copies
the `alt` text into `role="img"`/`aria-label` for accessibility, and swaps the
element in place:

```js
const span = document.createElement("span");
span.className = (img.className || "") + " mask-icon";
span.style.setProperty("--icon-mask", `url("${abs}") center / contain no-repeat`);
img.replaceWith(span);
```

A `MutationObserver` (`initIconMaskObserver`, app.v2.js:6191) watches
`document.body` so icons rendered dynamically later (e.g. after a console is
selected) are converted too.

### Theme colour → variable (app.v2.js:5808)

```js
function applyIconColorTheme(theme) {
  let fill = "#ffffff";
  if (theme.iconMatchAccent)          fill = "var(--accent)";
  else if (theme.iconGradient && theme.iconColor1 && theme.iconColor2) {
    const dir = theme.iconGradientDirection === "to bottom right" ? "135deg" : "180deg";
    fill = `linear-gradient(${dir}, ${theme.iconColor1}, ${theme.iconColor2})`;
  } else if (theme.iconColor)         fill = theme.iconColor;
  document.documentElement.style.setProperty("--icon-fill", fill);
}
```

Only **one** CSS variable (`--icon-fill`, declared on `:root`) needs updating and
every masked icon repaints instantly — because every mask just reads that
variable. The gradient case simply assigns a `linear-gradient(...)` value to the
same variable. The original image files are **never** touched, which is also why
the existing `ico-backup/` (a precautionary copy) was verified byte‑for‑byte
identical afterwards.

---

## 5. Why only monochrome line‑art can be recoloured this way

The mask mechanism decides visibility **solely from the mask image's alpha
channel** (in its default *alpha‑mask* mode). Consequences:

1. For a black‑on‑transparent glyph, alpha already *is* the complete shape —
   perfect stencil, perfect result in any colour.
2. For a coloured logo, the *colour information* is simply ignored by the mask
   (alpha is ~all‑or‑nothing around the silhouette). Recolouring would therefore
   produce a **flat monochrome silhouette** of whatever you set in
   `background:` — the red PlayStation‑style accents, the blue, the gradients in
   the image are all lost.

In other words: you can only repaint an image whose *information content* is
single‑colour. Line‑art is exactly that; brand logos are not. There is also a
`mask-mode: luminance` mode that uses brightness instead of alpha (black →
opaque, white → transparent), which similarly assumes the image's ink is
uniformly dark/light — still not suitable for multi‑colour artwork.

---

## 6. When this is the right tool

**Use the mask/background rebuild when:**
- Icons are true line‑art (one ink colour + transparency), SVG or PNG.
- You want a user‑selectable colour or gradient, applied live.
- You must not/do not want to modify source assets.
- You want one code path for hundreds of icons (single CSS variable = global).
- Accessibility is kept (we mirror `alt` into `aria-label`).

**Use regular `<img>` / static assets when:**
- The image is a colour **brand mark** whose colour is part of the meaning.
- The image is photographic/gradient and must show its true colours.
- Sharpness/behaviour must match the original exactly at all sizes
  (mask rendering is generally crisp, but it re‑rasterizes the shape).

---

## 7. Further study

- MDN — `mask-image`, `mask-mode`, `mask-repeat/size/position`
- CSS `mask` shorthand (same value grammar as `background`)
- SVG `<path>` + `fill` vs. `currentColor` (useful if you *ever* want a pure‑CSS
  no‑JS fill for SVGs directly)
- `background-clip: text` is a sibling trick: paint text with any image/gradient
- The WebKit‑prefixed `-webkit-mask` is, as of now, still required for older
  Chromium/WebKit engines — always ship both prefixed and unprefixed.