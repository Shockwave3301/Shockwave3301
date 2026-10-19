#!/usr/bin/env python3
"""Build the animated SVG cards used in README.md.

Every section is a row of fixed-width cards. On a wide screen they sit side by side; on a
phone GitHub shrinks each card to the screen width and the row wraps, so text stays readable.
Text is converted to outlines, so the cards look the same everywhere and need no web fonts.
Each card is written twice, for GitHub's light and dark themes.

    pip install fonttools brotli uharfbuzz
    python scripts/build-readme-art.py --fonts DIR

DIR must contain InterDisplay-Bold.otf, Inter-Regular.otf, Inter-Medium.otf and
Inter-SemiBold.otf (https://rsms.me/inter) and jetbrains-mono-latin-400-normal.woff2 (npm
package @fontsource/jetbrains-mono). Cards embed the icons in assets/icons and the logos in
assets/logos.
"""

import argparse
import base64
import io
import pathlib
import re
import struct
from xml.sax.saxutils import escape

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ASSETS = pathlib.Path(__file__).resolve().parent.parent / "assets"
CARDS = ASSETS / "cards"

THEMES = {
    "light": dict(
        bg1="#ffffff", bg2="#f6f8fa", border="#d0d7de", text="#1f2328", muted="#59636e",
        accent1="#0969da", accent2="#8250df", dots="#afb8c1", laser="#e5484d", green="#1a7f37",
        suffix="",
    ),
    "dark": dict(
        bg1="#0d1117", bg2="#161b22", border="#30363d", text="#e6edf3", muted="#9198a1",
        accent1="#4493f8", accent2="#ab7df8", dots="#3d444d", laser="#ff6369", green="#3fb950",
        suffix="-dark",
    ),
}

# Shown under the headline: where I live, then languages with their levels.
LOCATION = "Tashkent, Uzbekistan"
LANGUAGES = [("English", "C1"), ("Russian", "Native")]

# (logo file in assets/logos; company; years; role; what I built), oldest first. Dates come
# from the resume. Logos in ICON_LOGOS are app icons without a name, so the company name is
# set beside them.
TIMELINE = [
    ("funbox", "FunBox", "2018–2020", "Frontend Developer", "SMS marketing platform for mobile operators"),
    ("mws-ai", "MTS AI", "2020–2023", "Frontend Developer", "No-code chatbot builder used by 200+ businesses"),
    ("x5-tech", "X5 Digital", "2023–2024", "Senior Frontend Developer", "5ka.ru, Pyaterochka's online grocery store"),
    ("smartprice", "Smart Price", "2024–now", "Lead Frontend Developer",
     "Self-checkout cash payments, robot fleet, shelf labels"),
]

ICON_LOGOS = {"funbox"}

# (illustration, company, title, description, stat) for the project cards.
PROJECTS = [
    ("cash", "SMART PRICE", "Self-checkout cash payments",
     "Connected cash recyclers to kiosks already running in stores over a real-time WebSocket layer.",
     "2,000+ kiosks"),
    ("robots", "SMART PRICE", "Robot fleet dashboard",
     "Live status, routes, schedules and diagnostics for autonomous cleaning robots, built from scratch.",
     "200+ robots"),
    ("labels", "SMART PRICE", "Shelf label linking",
     "Links digital price tags to products by scanner, phone camera or hand. Piloted in 12 stores.",
     "6 → 50 labels a minute"),
    ("grocery", "X5 DIGITAL", "5ka.ru storefront",
     "Homepage, catalog, product pages and cart of Pyaterochka's online grocery delivery.",
     "270K+ orders on peak days"),
    ("chatbot", "MTS AI", "No-code chatbot builder",
     "Drag-and-drop flow editor and a live WebSocket debugging view, used for QA and client demos.",
     "200+ businesses"),
    ("onscan", "OPEN SOURCE", "onscan-next",
     "Typed library for hardware barcode scanners in React, Vue and Angular, with simulate() for tests.",
     "MIT · on npm"),
]

# (figure, caption) for the numbers cards. Pyaterochka had 25,533 stores on 31 Dec 2025, and
# 7,315 of them offered express delivery (x5.ru); a quarter of all stores with three
# self-checkouts is 19,150 kiosks. 2,000 kiosks with cash recyclers at about 300 cash
# transactions each a day is 600,000.
NUMBERS = [
    ("19,000+", "Self-checkout kiosks running my frontend"),
    ("2,000+", "Kiosks with cash recyclers on my payment UI"),
    ("~600K", "Cash payments a day through those kiosks"),
    ("7,300+", "Pyaterochka stores delivering from the online store I built"),
]

# (group, items without an icon, [(icon file in assets/icons, name)]) for the stack cards.
STACK = [
    ("Core", ["TanStack Query & Router", "REST APIs", "WebSocket"], [
        ("typescript", "TypeScript"), ("javascript", "JavaScript"), ("react", "React"),
        ("redux", "Redux"), ("tanstack", "TanStack"),
    ]),
    ("UI", ["CSS Modules"], [
        ("chakraui", "Chakra UI"), ("radixui", "Radix"), ("materialui", "Material UI"), ("css3", "CSS"),
        ("sass", "Sass"), ("storybook", "Storybook"), ("figma", "Figma"),
    ]),
    ("Testing & tooling", ["Mock Service Worker"], [
        ("vitest", "Vitest"), ("jest", "Jest"), ("playwright", "Playwright"), ("vite", "Vite"),
        ("webpack", "Webpack"),
    ]),
]

# (icon file in assets/icons, name) for the AI card. claude-code.svg (the Claude Code droid)
# and open-design.svg are hand-drawn; Codex uses the OpenAI logo.
AI_TOOLS = [
    ("claude-code", "Claude Code"), ("openai", "Codex"), ("opencode", "OpenCode"),
    ("coderabbit", "CodeRabbit"), ("open-design", "OpenDesign"),
]

# (kind, label, value, card width) for the contact cards.
CONTACTS = [
    ("email", "Email", "shockwave3301@proton.me", 290),
    ("telegram", "Telegram", "@shockwave3301", 228),
    ("linkedin", "LinkedIn & CV", "Upon request", 228),
]

# Card widths. The README gives every card 8px of margin on each side (hspace), so cards sit
# 16px apart and rows come to about 800px, which fits GitHub's README column. On narrower
# screens the rows wrap. GitHub drops vspace, so cards that share rows carry the same 16px
# below them as transparent space instead.
QUARTER, THIRD, FULL, GAP = 182, 250, 780, 16

# EAN-13 drawn on the kiosk screen; 460 is the GS1 prefix for Russia.
BARCODE = "4601234567893"


def num(v, digits=2):
    return f"{v:.{digits}f}".rstrip("0").rstrip(".")


def outline(v):
    return num(v, 1)


class Font:
    def __init__(self, path):
        tt = TTFont(path)
        tt.flavor = None
        data = io.BytesIO()
        tt.save(data)
        self.hb = hb.Font(hb.Face(data.getvalue()))
        self.glyphs = tt.getGlyphSet()
        self.order = tt.getGlyphOrder()
        self.upem = tt["head"].unitsPerEm

    def shape(self, text, size, tracking=0, features=None):
        """Return [(glyph name, x, y offset)] and the total advance, in px."""
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hb, buf, features or {})
        scale = size / self.upem
        placed, x = [], 0.0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            placed.append((self.order[info.codepoint], x + pos.x_offset * scale, pos.y_offset * scale))
            x += pos.x_advance * scale + tracking
        return placed, x - tracking

    def width(self, text, size, tracking=0, features=None):
        return self.shape(text, size, tracking, features)[1]

    def draw(self, placed, size, x, y):
        scale = size / self.upem
        pen = SVGPathPen(self.glyphs, ntos=outline)
        for name, gx, gy in placed:
            self.glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, x + gx, y - gy)))
        return pen.getCommands()

    def path(self, text, size, x, y, tracking=0, features=None):
        return self.draw(self.shape(text, size, tracking, features)[0], size, x, y)

    def wrap(self, text, size, max_width):
        lines = [""]
        for word in text.split():
            candidate = f"{lines[-1]} {word}".strip()
            if lines[-1] and self.width(candidate, size) > max_width:
                lines.append(word)
            else:
                lines[-1] = candidate
        return lines


def text(font, s, size, x, y, fill, align="left", attrs="", tracking=0, features=None):
    """A line of text as an outlined path, aligned left, center or right on x."""
    w = font.width(s, size, tracking, features)
    x0 = {"left": x, "center": x - w / 2, "right": x - w}[align]
    return f'<path fill="{fill}" {attrs} d="{font.path(s, size, x0, y, tracking, features)}"/>'


def lines(font, rows, size, x, y, leading, fill, attrs=""):
    d = " ".join(font.path(row, size, x, y + leading * i) for i, row in enumerate(rows))
    return f'<path fill="{fill}" {attrs} d="{d}"/>'


def anim(attr, frames, period, mode="linear", spline="0.4 0 0.2 1", transform=None):
    """SMIL animation through (seconds, value) frames over one loop of `period` seconds.

    Frames start at 0, and the last value is held until the loop restarts. With mode="spline"
    every segment eases with `spline`.
    """
    if frames[-1][0] < period:
        frames = [*frames, (period, frames[-1][1])]
    times = ";".join(num(t / period, 4) for t, _ in frames)
    values = ";".join(str(v) for _, v in frames)
    tag = "animateTransform" if transform else "animate"
    kind = f' type="{transform}"' if transform else ""
    calc = f' calcMode="{mode}"' if mode != "linear" else ""
    if mode == "spline":
        calc += f' keySplines="{";".join([spline] * (len(frames) - 1))}"'
    return (f'<{tag} attributeName="{attr}"{kind} values="{values}" keyTimes="{times}"{calc} '
            f'dur="{num(period)}s" repeatCount="indefinite"/>')


def move(frames, period, mode="spline"):
    """Translate animation through (seconds, (dx, dy)) frames."""
    return anim("transform", [(t, f"{num(dx)} {num(dy)}") for t, (dx, dy) in frames], period, mode,
                transform="translate")


def discrete(attr, keyframes, total):
    """SMIL animation holding each (time, value) until the next one."""
    times = ";".join(num(t / total, 5) if t else "0" for t, _ in keyframes)
    values = ";".join(str(v) for _, v in keyframes)
    return (f'<animate attributeName="{attr}" calcMode="discrete" dur="{num(total)}s" '
            f'repeatCount="indefinite" keyTimes="{times}" values="{values}"/>')


def card(W, H, c, title, body, defs="", glow=None, below=0):
    """Wrap body in the shared card look: soft gradient, accent glow, dot grid and border.

    `below` adds that much transparent space under the card, for the gap between rows.
    """
    gx, gy = glow or (W * 0.85, 0)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{num(W)}" height="{num(H + below)}" viewBox="0 0 {num(W)} {num(H + below)}" fill="none">
<title>{escape(title)}</title>
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{c['bg1']}"/><stop offset="1" stop-color="{c['bg2']}"/></linearGradient>
<radialGradient id="glow" cx="{num(gx)}" cy="{num(gy)}" r="380" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="{c['accent2']}" stop-opacity="0.14"/><stop offset="1" stop-color="{c['accent2']}" stop-opacity="0"/></radialGradient>
<linearGradient id="laser" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{c['laser']}" stop-opacity="0"/><stop offset="0.5" stop-color="{c['laser']}" stop-opacity="0.3"/><stop offset="1" stop-color="{c['laser']}" stop-opacity="0"/></linearGradient>
<linearGradient id="accent" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{c['accent1']}"/><stop offset="1" stop-color="{c['accent2']}"/></linearGradient>
<pattern id="dots" width="18" height="18" patternUnits="userSpaceOnUse"><circle cx="9" cy="9" r="1" fill="{c['dots']}"/></pattern>
<linearGradient id="fade" x1="0" y1="0" x2="1" y2="0"><stop offset="0.35" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#fff" stop-opacity="0.9"/></linearGradient>
<mask id="dots-mask"><rect width="{num(W)}" height="{num(H)}" fill="url(#fade)"/></mask>
<clipPath id="card"><rect width="{num(W)}" height="{num(H)}" rx="16"/></clipPath>
{defs}
</defs>
<g clip-path="url(#card)">
<rect width="{num(W)}" height="{num(H)}" fill="url(#bg)"/>
<rect width="{num(W)}" height="{num(H)}" fill="url(#glow)"/>
<rect width="{num(W)}" height="{num(H)}" fill="url(#dots)" mask="url(#dots-mask)"/>
</g>
<rect x="0.5" y="0.5" width="{num(W - 1)}" height="{num(H - 1)}" rx="15.5" stroke="{c['border']}"/>
{body}
</svg>
"""


def mix(a, b, t):
    """Blend two #rrggbb colors."""
    pa, pb = (int(a[i:i + 2], 16) for i in (1, 3, 5)), (int(b[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(u + (v - u) * t):02x}" for u, v in zip(pa, pb))


def ean13_modules(code):
    left = ["0001101", "0011001", "0010011", "0111101", "0100011",
            "0110001", "0101111", "0111011", "0110111", "0001011"]
    right = ["".join("1" if b == "0" else "0" for b in p) for p in left]
    even = [p[::-1] for p in right]
    parity = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG",
              "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"][int(code[0])]
    bits = "101"
    for d, p in zip(code[1:7], parity):
        bits += (left if p == "L" else even)[int(d)]
    bits += "01010"
    for d in code[7:]:
        bits += right[int(d)]
    return bits + "101"


def barcode(x, y, module, height, fill):
    """EAN-13 bars for BARCODE with guard bars a little longer."""
    bars = ean13_modules(BARCODE)
    guards = set(range(0, 3)) | set(range(45, 50)) | set(range(92, 95))
    rects, i = [], 0
    while i < len(bars):
        if bars[i] == "1":
            j = i
            while j < len(bars) and bars[j] == "1" and (j in guards) == (i in guards):
                j += 1
            h = height + (module * 5 if i in guards else 0)
            rects.append(f'<rect x="{num(x + i * module)}" y="{num(y)}" width="{num((j - i) * module)}" height="{num(h)}"/>')
            i = j
        else:
            i += 1
    return f'<g fill="{fill}">{"".join(rects)}</g>'


def icon_uri(name, c):
    """Data URI for an icon in assets/icons, preferring its dark variant on the dark theme."""
    svg = ASSETS / "icons" / f"{name}{c['suffix']}.svg"
    if not svg.exists():
        svg = ASSETS / "icons" / f"{name}.svg"
    return "data:image/svg+xml;base64," + base64.b64encode(svg.read_bytes()).decode()


def logo(name, c, x, y, height):
    """An <image> for a logo in assets/logos at the given height, and its width.

    Uses the logo's -dark file on the dark theme when there is one.
    """
    path = ASSETS / "logos" / f"{name}{c['suffix']}.png"
    png = (path if path.exists() else ASSETS / "logos" / f"{name}.png").read_bytes()
    png_w, png_h = struct.unpack(">II", png[16:24])
    w = png_w * height / png_h
    return (f'<image href="data:image/png;base64,{base64.b64encode(png).decode()}" x="{num(x)}" y="{num(y)}" '
            f'width="{num(w)}" height="{num(height)}"/>'), w


# Hero ------------------------------------------------------------------------------------


def title_block(fonts, c, left, pill_y, pill_size, head, base1, base2, info_y, stacked=False):
    """Availability pills, two-line headline, then location and language pills.

    Returns (markup, defs). With stacked, as on phones, the work-format pill goes below the
    availability pill and the language pills below the location.
    """
    display, medium, semibold = fonts["display"], fonts["medium"], fonts["semibold"]
    out = []

    # Availability pill with a pulsing dot, then the work-format pill.
    pill_text = "Open to lead & senior roles"
    pill_h = round(pill_size * 2.15)
    dot_x, dot_y, dot_r = left + pill_h / 2 + 1, pill_y + pill_h / 2, pill_size * 0.32
    pill_w = dot_x - left + 16 + medium.width(pill_text, pill_size) + 14
    out.append(f'<rect x="{left}" y="{pill_y}" width="{num(pill_w)}" height="{pill_h}" rx="{num(pill_h / 2)}" '
               f'fill="{c["green"]}" fill-opacity="0.12" stroke="{c["green"]}" stroke-opacity="0.35"/>')
    out.append(f'<circle cx="{num(dot_x)}" cy="{num(dot_y)}" r="{num(dot_r)}" fill="{c["green"]}">'
               f'<animate attributeName="r" values="{num(dot_r)};{num(dot_r * 2.6)}" dur="2s" repeatCount="indefinite"/>'
               '<animate attributeName="opacity" values="0.5;0" dur="2s" repeatCount="indefinite"/></circle>')
    out.append(f'<circle cx="{num(dot_x)}" cy="{num(dot_y)}" r="{num(dot_r)}" fill="{c["green"]}"/>')
    out.append(text(medium, pill_text, pill_size, dot_x + 16, dot_y + pill_size * 0.36, c["green"]))
    format_text = "Remote · Hybrid · Relocation"
    format_w = 28 + medium.width(format_text, pill_size)
    fx, fy = (left, pill_y + pill_h + 8) if stacked else (left + pill_w + 10, pill_y)
    out.append(f'<rect x="{num(fx)}" y="{num(fy)}" width="{num(format_w)}" height="{pill_h}" rx="{num(pill_h / 2)}" '
               f'fill="{c["text"]}" fill-opacity="0.05" stroke="{c["border"]}"/>')
    out.append(text(medium, format_text, pill_size, fx + 14, fy + pill_h / 2 + pill_size * 0.36, c["muted"]))

    out.append(text(display, "Senior / Lead", head, left - 2, base1, c["text"]))
    out.append(f'<path fill="url(#headline)" d="{display.path("Frontend Engineer", head, left - 2, base2)}"/>')
    headline_w = display.width("Frontend Engineer", head)

    # Location: a map pin with a ripple spreading under its tip.
    px, tip = left + 7, info_y + 8
    out.append(f'<ellipse cx="{num(px)}" cy="{num(tip)}" rx="3" ry="1.2" fill="none" stroke="{c["accent1"]}" stroke-width="1.5">'
               '<animate attributeName="rx" values="3;12" dur="2s" repeatCount="indefinite"/>'
               '<animate attributeName="ry" values="1.2;4.5" dur="2s" repeatCount="indefinite"/>'
               '<animate attributeName="opacity" values="0.6;0" dur="2s" repeatCount="indefinite"/></ellipse>')
    out.append(f'<path fill="{c["accent1"]}" fill-rule="evenodd" d="M{num(px)} {num(tip)}c0 0-7-6.6-7-11.5a7 7 0 0 1 14 0'
               f'c0 4.9-7 11.5-7 11.5zm0-14.2a2.7 2.7 0 1 0 0 5.4 2.7 2.7 0 0 0 0-5.4z"/>')
    loc_size = pill_size + 1.5
    loc_x = left + 22
    out.append(text(medium, LOCATION, loc_size, loc_x, info_y + loc_size * 0.36, c["text"]))

    # Languages as pills, each with its level in a small badge.
    x = left if stacked else loc_x + medium.width(LOCATION, loc_size) + 18
    y = info_y + 18 if stacked else info_y - pill_h / 2
    badge_size = pill_size - 2
    for name, level in LANGUAGES:
        name_w = medium.width(name, pill_size)
        badge_w = semibold.width(level, badge_size) + 14
        w = 12 + name_w + 8 + badge_w + 5
        out.append(f'<rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{pill_h}" rx="{num(pill_h / 2)}" '
                   f'fill="{c["text"]}" fill-opacity="0.05" stroke="{c["border"]}"/>')
        out.append(text(medium, name, pill_size, x + 12, y + pill_h / 2 + pill_size * 0.36, c["text"]))
        bx, bh = x + 12 + name_w + 8, pill_h - 10
        out.append(f'<rect x="{num(bx)}" y="{num(y + 5)}" width="{num(badge_w)}" height="{bh}" rx="{num(bh / 2)}" '
                   f'fill="{c["accent1"]}" fill-opacity="0.14"/>')
        out.append(text(semibold, level, badge_size, bx + 7, y + pill_h / 2 + badge_size * 0.36, c["accent1"]))
        x += w + 8

    defs = (f'<linearGradient id="headline" x1="{left - 2}" y1="0" x2="{num(left - 2 + headline_w)}" y2="0" '
            f'gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="{c["accent1"]}"/>'
            f'<stop offset="1" stop-color="{c["accent2"]}"/></linearGradient>')
    return "\n".join(out), defs


def hero(fonts, c):
    """Desktop header: title on the left, the self-checkout kiosk on the right, in one card."""
    W, H = FULL, 280
    title, title_defs = title_block(fonts, c, 36, 36, 14, 46, 132, 184, 228)
    device, device_defs = kiosk_device(fonts, c)
    body = f'{title}\n<g transform="translate(484 0)">{device}</g>'
    return card(W, H, c, "Senior / Lead Frontend Engineer", body, title_defs + device_defs, glow=(640, 40))


def hero_mobile(fonts, c):
    """Phone header: the same card stacked, title above the kiosk."""
    W, H = 360, 552
    title, title_defs = title_block(fonts, c, 22, 22, 13, 36, 134, 176, 212, stacked=True)
    device, device_defs = kiosk_device(fonts, c)
    body = f'{title}\n<g transform="translate(32 264)">{device}</g>'
    return card(W, H, c, "Senior / Lead Frontend Engineer", body, title_defs + device_defs, glow=(W, 220))


def kiosk_device(fonts, c):
    """A self-checkout kiosk looping through a cash purchase: cart, insert cash, change,
    thank you, then scanning the next customer's items back into the cart.

    Drawn in a 296 by 280 box; returns (markup, defs) for a header card to place.
    """
    display, regular, medium, semibold = fonts["display"], fonts["regular"], fonts["medium"], fonts["semibold"]
    # The screen keeps its own light UI in both themes, like the real device.
    ink, grey, rule, blue, green = "#1f2328", "#656d76", "#d8dee4", "#0969da", "#1a7f37"
    period, fade = 11.6, 0.25
    bounds = [0, 2.2, 5.6, 7.0, 8.6, period]
    sx, sy, sw, sh = 58, 28, 180, 196
    mid = sx + sw / 2

    def state(k, body):
        start, end = bounds[k], bounds[k + 1]
        if k == 0:
            frames = [(0, 1), (end - fade, 1), (end, 0), (period - fade, 0), (period, 1)]
        else:
            frames = [(0, 0), (start - fade, 0), (start, 1), (end - fade, 1), (end, 0)]
        return f'<g opacity="{1 if k == 0 else 0}">{anim("opacity", frames, period)}{"".join(body)}</g>'

    def row(name, price, y):
        return text(regular, name, 11, sx + 14, y, ink) + text(medium, price, 11, sx + sw - 14, y, ink, "right")

    out = []
    # Device body, screen, and the scanner window under the screen.
    out.append(f'<rect x="48" y="14" width="200" height="252" rx="22" fill="url(#bezel)" stroke="{c["border"]}"/>')
    out.append(f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="12" fill="#ffffff"/>')
    out.append('<rect x="108" y="238" width="80" height="14" rx="5" fill="#0b0d10"/>')
    beep = [(0, 0), (9.4, 0), (9.45, 0.9), (9.85, 0), (10.6, 0), (10.65, 0.9), (11.05, 0)]
    out.append(f'<rect x="108" y="238" width="80" height="14" rx="5" fill="#ff6369" opacity="0">'
               f'{anim("opacity", beep, period)}</rect>')
    out.append(f'<circle cx="226" cy="245" r="3" fill="{c["green"]}"/>')

    out.append(f'<g clip-path="url(#screen)">')
    out.append(text(medium, "Self-checkout", 10, sx + 14, sy + 18, grey))
    out.append(f'<rect x="{sx}" y="{sy + 26}" width="{sw}" height="1" fill="{rule}"/>')

    # Cart, with the cash button being pressed.
    press = [(0, 0), (1.4, 0), (1.55, 0.2), (1.95, 0)]
    ripple_r = [(0, 0), (1.4, 0), (1.95, 44)]
    ripple_o = [(0, 0), (1.4, 0.45), (1.95, 0)]
    out.append(state(0, [
        row("Milk 1L", "89.90 ₽", sy + 50), row("Bread", "54.90 ₽", sy + 68),
        f'<rect x="{sx + 14}" y="{sy + 80}" width="{sw - 28}" height="1" fill="{rule}"/>',
        text(regular, "Total", 11, sx + 14, sy + 101, grey),
        text(semibold, "144.80 ₽", 16, sx + sw - 14, sy + 102, ink, "right"),
        text(regular, "Choose payment", 10, mid, sy + 134, grey, "center"),
        f'<rect x="{sx + 14}" y="{sy + 144}" width="72" height="34" rx="8" fill="#fff" stroke="{rule}"/>',
        text(medium, "Card", 11.5, sx + 50, sy + 165, ink, "center"),
        f'<g clip-path="url(#cash-button)"><rect x="{sx + 94}" y="{sy + 144}" width="72" height="34" fill="{blue}"/>',
        f'<rect x="{sx + 94}" y="{sy + 144}" width="72" height="34" fill="#000" opacity="0">{anim("opacity", press, period)}</rect>',
        f'<circle cx="{sx + 130}" cy="{sy + 161}" r="0" fill="#fff" opacity="0">{anim("r", ripple_r, period)}'
        f'{anim("opacity", ripple_o, period)}</circle></g>',
        text(medium, "Cash", 11.5, sx + 130, sy + 165, "#fff", "center"),
    ]))

    # Insert cash: two notes slide into the slot and the inserted total counts up.
    def note(slide_at, appear_at=None):
        shown = "" if appear_at is None else anim("opacity", [(0, 0), (appear_at, 0), (appear_at + 0.25, 1)], period)
        return (f'<g opacity="{0 if appear_at else 1}">{shown}<g>'
                f'{move([(0, (0, 0)), (slide_at, (0, 0)), (slide_at + 0.5, (0, 44))], period)}'
                f'<rect x="{mid - 32}" y="{sy + 82}" width="64" height="32" rx="3" fill="#2da44e"/>'
                f'<rect x="{mid - 28}" y="{sy + 86}" width="56" height="24" rx="2" stroke="#fff" stroke-opacity="0.5"/>'
                + text(semibold, "100 ₽", 10.5, mid, sy + 102, "#fff", "center") + "</g></g>")

    out.append(state(1, [
        text(semibold, "Insert cash", 13, mid, sy + 52, ink, "center"),
        text(regular, "Due 144.80 ₽", 10.5, mid, sy + 69, grey, "center"),
        f'<g clip-path="url(#slot)">{note(2.7)}{note(3.95, appear_at=3.45)}</g>',
        f'<rect x="{mid - 46}" y="{sy + 118}" width="92" height="5" rx="2.5" fill="{ink}"/>',
        text(regular, "Inserted", 10.5, mid, sy + 150, grey, "center"),
        f'<g>{discrete("opacity", [(0, 1), (3.2, 0)], period)}'
        + text(semibold, "0 ₽", 16, mid, sy + 172, ink, "center") + "</g>",
        f'<g opacity="0">{discrete("opacity", [(0, 0), (3.2, 1), (4.45, 0)], period)}'
        + text(semibold, "100 ₽", 16, mid, sy + 172, ink, "center") + "</g>",
        f'<g opacity="0">{discrete("opacity", [(0, 0), (4.45, 1)], period)}'
        + text(semibold, "200 ₽", 16, mid, sy + 172, ink, "center") + "</g>",
    ]))

    # Change drops out as coins.
    coins = []
    for i, dx in enumerate((-22, 0, 22)):
        at = 5.75 + 0.12 * i
        coins.append(f'<g opacity="0">{anim("opacity", [(0, 0), (at, 0), (at + 0.1, 1)], period)}<g>'
                     f'{move([(0, (0, -26)), (at, (0, -26)), (at + 0.35, (0, 0))], period)}'
                     f'<circle cx="{mid + dx}" cy="{sy + 140}" r="9" fill="#e3b341" stroke="#bf8700" stroke-width="1.5"/>'
                     "</g></g>")
    out.append(state(2, [
        text(semibold, "Take your change", 12.5, mid, sy + 58, ink, "center"),
        text(display, "55.20 ₽", 26, mid, sy + 100, green, "center"),
        *coins,
    ]))

    # Thank you, with the check drawing itself.
    out.append(state(3, [
        f'<circle cx="{mid}" cy="{sy + 84}" r="24" fill="{green}"/>',
        f'<path d="M{num(mid - 10)} {sy + 84}l7 7 13-14" stroke="#fff" stroke-width="3.5" stroke-linecap="round" '
        f'stroke-linejoin="round" stroke-dasharray="32" stroke-dashoffset="0">'
        f'{anim("stroke-dashoffset", [(0, 32), (7.15, 32), (7.5, 0)], period)}</path>',
        text(semibold, "Thank you!", 15, mid, sy + 138, ink, "center"),
        text(regular, "Have a nice day", 10.5, mid, sy + 156, grey, "center"),
    ]))

    # Scan the next customer's items: the laser sweeps, each beep adds a row.
    def appear(at, body):
        return f'<g opacity="0">{discrete("opacity", [(0, 0), (at, 1)], period)}{body}</g>'

    def between(start, end, body):
        return f'<g opacity="0">{discrete("opacity", [(0, 0), (start, 1), (end, 0)], period)}{body}</g>'

    sweep = [(0, (0, 0)), (8.8, (0, 0)), (9.4, (0, 40)), (10.0, (0, 0)), (10.6, (0, 40)), (11.2, (0, 0))]
    out.append(state(4, [
        text(semibold, "Scan your items", 12.5, mid, sy + 50, ink, "center"),
        barcode(mid - 38, sy + 62, 0.8, 34, ink),
        f'<g>{move(sweep, period)}<rect x="{mid - 48}" y="{sy + 53}" width="96" height="16" fill="url(#screen-laser)"/>'
        f'<rect x="{mid - 48}" y="{sy + 60}" width="96" height="2" rx="1" fill="#e5484d"/></g>',
        appear(9.45, row("Milk 1L", "89.90 ₽", sy + 128)),
        appear(10.65, row("Bread", "54.90 ₽", sy + 146)),
        appear(9.45, f'<rect x="{sx + 14}" y="{sy + 156}" width="{sw - 28}" height="1" fill="{rule}"/>'
               + text(regular, "Total", 11, sx + 14, sy + 176, grey)),
        between(9.45, 10.65, text(semibold, "89.90 ₽", 14, sx + sw - 14, sy + 177, ink, "right")),
        appear(10.65, text(semibold, "144.80 ₽", 14, sx + sw - 14, sy + 177, ink, "right")),
    ]))
    out.append("</g>")

    defs = (f'<linearGradient id="bezel" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2d333b"/>'
            '<stop offset="1" stop-color="#1c2128"/></linearGradient>'
            '<linearGradient id="screen-laser" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#e5484d" stop-opacity="0"/>'
            '<stop offset="0.5" stop-color="#e5484d" stop-opacity="0.3"/><stop offset="1" stop-color="#e5484d" stop-opacity="0"/></linearGradient>'
            f'<clipPath id="screen"><rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="12"/></clipPath>'
            f'<clipPath id="slot"><rect x="{sx}" y="{sy}" width="{sw}" height="120"/></clipPath>'
            f'<clipPath id="cash-button"><rect x="{sx + 94}" y="{sy + 144}" width="72" height="34" rx="8"/></clipPath>')
    return "\n".join(out), defs


# Timeline --------------------------------------------------------------------------------


def timeline_layout(fonts):
    """Role and description lines for every timeline card, and the shared card height."""
    semibold, regular = fonts["semibold"], fonts["regular"]
    layouts = []
    for _, _, _, role, built in TIMELINE:
        roles = semibold.wrap(role, 13, QUARTER - 36)
        desc_top = 120 + 17 * (len(roles) - 1) + 21
        descs = regular.wrap(built, 12, QUARTER - 36)
        layouts.append((roles, desc_top, descs))
    H = max(top + 16 * (len(d) - 1) for _, top, d in layouts) + 22
    return layouts, H


def timeline(fonts, c, n):
    """One stop on the career timeline. A pulse runs along the track from card to card."""
    W = QUARTER
    layouts, H = timeline_layout(fonts)
    roles, desc_top, descs = layouts[n]
    name, company, years, _, _ = TIMELINE[n]
    display, semibold, regular, mono = fonts["display"], fonts["semibold"], fonts["regular"], fonts["mono"]
    last = n == len(TIMELINE) - 1
    track_y, node_x = 24, 26
    x0 = node_x if n == 0 else 0
    x1 = node_x if last else W
    period, speed, step = 6.0, 245.0, W + GAP
    t_at = lambda x: 0.5 + (n * step + x - node_x) / speed  # noqa: E731
    out = [f'<rect x="{x0}" y="{track_y - 1}" width="{x1 - x0}" height="2" fill="{c["border"]}"/>']

    # The pulse, visible only while it crosses this card.
    t_in, t_out = t_at(x0), t_at(x1)
    out.append(f'<g opacity="0">{discrete("opacity", [(0, 0), (t_in, 1), (t_out, 0)], period)}<g>'
               f'{move([(0, (x0, track_y)), (t_in, (x0, track_y)), (t_out, (x1, track_y))], period, "linear")}'
               '<rect x="-34" y="-1.5" width="34" height="3" rx="1.5" fill="url(#trail)"/>'
               f'<circle r="3.5" fill="{c["accent2"]}"/></g></g>')

    hit = t_at(node_x)
    if last:
        out.append(f'<circle cx="{node_x}" cy="{track_y}" r="6" fill="{c["green"]}">'
                   '<animate attributeName="r" values="6;15" dur="2s" repeatCount="indefinite"/>'
                   '<animate attributeName="opacity" values="0.45;0" dur="2s" repeatCount="indefinite"/></circle>')
        out.append(f'<circle cx="{node_x}" cy="{track_y}" r="6" fill="{c["green"]}"/>')
    else:
        flash = [(0, c["bg1"]), (hit - 0.05, c["bg1"]), (hit + 0.1, c["accent1"]), (hit + 0.8, c["bg1"])]
        out.append(f'<circle cx="{node_x}" cy="{track_y}" r="6" fill="{c["bg1"]}" stroke="{c["accent1"]}" '
                   f'stroke-width="2.5">{anim("fill", flash, period)}</circle>')
    out.append(text(mono, years, 12, 18, 52, c["green"] if last else c["muted"]))

    if name in ICON_LOGOS:
        # A rounded app-icon tile with the company name beside it.
        size = 32
        image, _ = logo(name, c, 18, 80 - size / 2, size)
        out.append(f'<clipPath id="icon"><rect x="18" y="{80 - size / 2}" width="{size}" height="{size}" rx="8"/></clipPath>')
        out.append(f'<g clip-path="url(#icon)">{image}</g>')
        out.append(text(display, company, 21, 18 + size + 9, 87.5, c["text"]))
    else:
        height = 34 if name == "mws-ai" else 26
        image, _ = logo(name, c, 18, 80 - height / 2, height)
        out.append(image)
    out.append(lines(semibold, roles, 13, 18, 120, 17, c["text"]))
    out.append(lines(regular, descs, 12, 18, desc_top, 16, c["muted"]))
    defs = (f'<linearGradient id="trail" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{c["accent1"]}" '
            f'stop-opacity="0"/><stop offset="1" stop-color="{c["accent2"]}"/></linearGradient>')
    return card(W, H, c, f"{company}, {years}", "\n".join(out), defs, below=GAP)


# Projects --------------------------------------------------------------------------------


def illustration(kind, fonts, c):
    """Animated drawing for the top band of a project card, in a 258 by 112 box."""
    display, regular, medium, semibold, mono = (fonts[k] for k in ("display", "regular", "medium", "semibold", "mono"))
    surface, line = f'fill="{c["bg1"]}" stroke="{c["border"]}"', c["border"]
    out = []
    if kind == "cash":
        # A banknote slides into the cash recycler and the amount floats up.
        p = 3.4
        out.append(f'<rect x="84" y="30" width="90" height="70" rx="10" {surface}/>')
        out.append(f'<rect x="96" y="76" width="66" height="12" rx="3" fill="{c["accent1"]}" fill-opacity="0.15"/>')
        out.append(f'<g clip-path="url(#into-slot)"><g>'
                   f'{anim("opacity", [(0, 1), (1.3, 1), (1.31, 0), (2.5, 0), (2.8, 1)], p)}'
                   f'{move([(0, (0, 0)), (0.8, (0, 0)), (1.3, (0, 30)), (1.31, (0, 0))], p)}'
                   f'<rect x="105" y="20" width="48" height="26" rx="3" fill="#2da44e"/>'
                   f'<rect x="108" y="23" width="42" height="20" rx="2" stroke="#fff" stroke-opacity="0.5"/>'
                   + text(semibold, "100 ₽", 9.5, 129, 36.5, "#fff", "center") + "</g></g>")
        out.append(f'<rect x="99" y="50" width="60" height="4" rx="2" fill="{c["text"]}"/>')
        out.append(f'<g opacity="0">{anim("opacity", [(0, 0), (1.3, 0), (1.45, 1), (2.3, 0)], p)}<g>'
                   f'{move([(0, (0, 0)), (1.3, (0, 0)), (2.3, (0, -8))], p)}'
                   + text(semibold, "+100 ₽", 11, 129, 86, c["green"], "center") + "</g></g>")
        defs = '<clipPath id="into-slot"><rect x="0" y="0" width="258" height="52"/></clipPath>'
    elif kind == "robots":
        # Robots drive their routes on a floor map.
        routes = [
            ("M44 26H114Q124 26 124 36V74Q124 84 114 84H44Q34 84 34 74V36Q34 26 44 26Z", c["accent1"], 7),
            ("M152 20H214Q224 20 224 30V44Q224 54 214 54H152Q142 54 142 44V30Q142 20 152 20Z", c["accent2"], 5.5),
            ("M152 68H220Q226 68 226 74V86Q226 92 220 92H152Q146 92 146 86V74Q146 68 152 68Z", c["green"], 6.5),
        ]
        out.append(f'<rect x="16" y="10" width="226" height="92" rx="10" fill="url(#floor)" stroke="{line}"/>')
        for d, color, dur in routes:
            out.append(f'<path d="{d}" stroke="{color}" stroke-opacity="0.45" stroke-width="1.5" stroke-dasharray="4 4"/>')
            out.append(f'<g><animateMotion path="{d}" dur="{dur}s" repeatCount="indefinite"/>'
                       f'<circle r="9" fill="{color}" fill-opacity="0.18"/>'
                       f'<circle r="5" fill="{color}" stroke="{c["bg1"]}" stroke-width="1.5"/></g>')
        defs = (f'<pattern id="grid" width="14" height="14" patternUnits="userSpaceOnUse">'
                f'<path d="M14 0H0V14" stroke="{line}" stroke-opacity="0.6"/></pattern>'
                f'<linearGradient id="floor" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{c["bg1"]}"/>'
                f'<stop offset="1" stop-color="{c["bg2"]}"/></linearGradient>')
        out.insert(1, '<rect x="17" y="11" width="224" height="90" rx="9" fill="url(#grid)"/>')
    elif kind == "labels":
        # A digital price tag is scanned and linked to its product.
        p = 3.6
        tag_ink = "#1f2328"
        out.append('<rect x="56" y="22" width="146" height="68" rx="6" fill="#e6e9ee" stroke="#c9d1d9"/>')
        out.append(barcode(66, 34, 0.32, 40, tag_ink))
        out.append(text(regular, "Milk 1L", 10, 108, 40, "#57606a"))
        out.append(text(display, "89.90", 26, 108, 72, tag_ink))
        out.append(text(medium, "₽", 13, 108 + display.width("89.90", 26) + 3, 72, tag_ink))
        out.append(f'<g opacity="0">{anim("opacity", [(0, 0), (0.6, 0), (0.7, 1), (1.5, 1), (1.6, 0)], p)}<g>'
                   f'{move([(0, (0, 0)), (0.6, (0, 0)), (1.5, (0, 40))], p, "linear")}'
                   f'<rect x="60" y="30" width="44" height="2" rx="1" fill="{c["laser"]}"/></g></g>')
        badge = [(0, 1), (0.3, 1), (0.45, 0), (1.65, 0), (1.8, 1)]
        out.append(f'<g>{anim("opacity", badge, p)}'
                   f'<rect x="166" y="10" width="72" height="24" rx="12" fill="{c["green"]}"/>'
                   + text(semibold, "✓ Linked", 11, 202, 26.5, "#fff", "center") + "</g>")
        defs = ""
    elif kind == "grocery":
        # Adding apples to the cart: a dot flies to the cart and the badge counts up.
        p = 3.6
        out.append(f'<rect x="40" y="12" width="98" height="88" rx="10" {surface}/>')
        out.append('<circle cx="89" cy="38" r="15" fill="#e5534b"/>')
        out.append('<path d="M89 24c2-5 6-6 9-5-1 4-5 6-9 5z" fill="#2da44e"/>')
        out.append(text(medium, "Apples", 10.5, 50, 70, c["text"]))
        out.append(text(semibold, "119 ₽", 10.5, 50, 87, c["text"]))
        out.append(f'<circle cx="118" cy="82" r="10" fill="{c["accent1"]}"/>')
        out.append('<path d="M118 77v10M113 82h10" stroke="#fff" stroke-width="2" stroke-linecap="round"/>')
        for at in (0.6, 2.0):
            out.append(f'<g opacity="0">{anim("opacity", [(0, 0), (at, 0), (at + 0.05, 1), (at + 0.5, 1), (at + 0.55, 0)], p)}<g>'
                       f'{move([(0, (0, 0)), (at, (0, 0)), (at + 0.5, (72, -30))], p)}'
                       f'<circle cx="118" cy="82" r="4" fill="{c["accent2"]}"/></g></g>')
        out.append(f'<path d="M168 40h8l6 26h28l5-18h-36" stroke="{c["text"]}" stroke-width="2.2" '
                   'stroke-linecap="round" stroke-linejoin="round"/>')
        out.append(f'<circle cx="186" cy="74" r="3" fill="{c["text"]}"/><circle cx="206" cy="74" r="3" fill="{c["text"]}"/>')
        out.append(f'<circle cx="214" cy="36" r="10" fill="{c["accent2"]}"/>')
        for count, start, end in (("1", 0, 1.1), ("2", 1.1, 2.5), ("3", 2.5, p)):
            frames = [(0, 1 if start == 0 else 0)] + ([(start, 1)] if start else []) + ([(end, 0)] if end < p else [])
            out.append(f'<g opacity="{1 if start == 0 else 0}">{discrete("opacity", frames, p)}'
                       + text(semibold, count, 11, 214, 40, "#fff", "center") + "</g>")
        defs = ""
    elif kind == "chatbot":
        # A message travels through the flow and the bot replies.
        p = 4.0
        edge1 = "M76 56C88 56 88 32 100 32"
        edge2 = "M76 56C88 56 88 80 100 80"
        out.append(f'<path d="{edge1}" stroke="{line}" stroke-width="1.5"/><path d="{edge2}" stroke="{line}" stroke-width="1.5"/>')
        for x, y, w, label in ((18, 42, 58, "Start"), (100, 18, 62, "Greet"), (100, 66, 62, "Hand off")):
            out.append(f'<rect x="{x}" y="{y}" width="{w}" height="28" rx="8" {surface}/>')
            out.append(text(medium, label, 10.5, x + w / 2, y + 18, c["text"], "center"))
        out.append(f'<rect x="100" y="18" width="62" height="28" rx="8" stroke="{c["accent1"]}" stroke-width="1.5" opacity="0">'
                   f'{anim("opacity", [(0, 0), (0.9, 0), (1.0, 1), (2.6, 1), (2.8, 0)], p)}</rect>')
        out.append(f'<g opacity="0">{anim("opacity", [(0, 0), (0.4, 0), (0.45, 1), (0.95, 1), (1.0, 0)], p)}'
                   f'<circle r="3.5" fill="{c["accent1"]}"><animateMotion path="{edge1}" dur="{num(p)}s" '
                   f'keyPoints="0;0;1;1" keyTimes="0;{num(0.4 / p, 4)};{num(0.95 / p, 4)};1" calcMode="linear" '
                   'repeatCount="indefinite"/></circle></g>')
        out.append(f'<path d="M178 30h56a8 8 0 0 1 8 8v22a8 8 0 0 1-8 8h-48l-8 8v-8a8 8 0 0 1-8-8V38a8 8 0 0 1 8-8z" {surface}/>')
        for i in range(3):
            out.append(f'<g opacity="0">{anim("opacity", [(0, 0), (1.0, 0), (1.05, 1), (1.9, 1), (1.95, 0)], p)}'
                       f'<circle cx="{198 + 9 * i}" cy="49" r="2.6" fill="{c["muted"]}">'
                       f'{anim("cy", [(0, 49), (1.05 + 0.12 * i, 49), (1.25 + 0.12 * i, 45), (1.45 + 0.12 * i, 49)], p)}'
                       "</circle></g>")
        out.append(f'<g>{anim("opacity", [(0, 1), (0.3, 1), (0.4, 0), (1.95, 0), (2.05, 1)], p)}'
                   + text(medium, "Hi! How can", 10, 210, 46, c["text"], "center")
                   + text(medium, "I help?", 10, 210, 59, c["text"], "center") + "</g>")
        defs = ""
    else:
        # A terminal installs the package and a scan comes through.
        p = 4.4
        no_liga = {"liga": False, "calt": False}
        out.append(f'<rect x="18" y="10" width="222" height="92" rx="8" fill="#0d1117" stroke="{line}"/>')
        for i, color in enumerate(("#ff5f57", "#febc2e", "#28c840")):
            out.append(f'<circle cx="{32 + 11 * i}" cy="22" r="3.5" fill="{color}"/>')
        out.append(text(mono, "$", 11, 30, 46, "#3fb950", features=no_liga))
        out.append(text(mono, "npm i onscan-next", 11, 44, 46, "#e6edf3", features=no_liga))
        out.append(text(mono, "+ onscan-next@1.0.1", 11, 30, 64, "#8b949e", features=no_liga))
        out.append(text(mono, "scan:", 11, 30, 84, "#d2a8ff", features=no_liga))
        adv = mono.width("0", 11)
        code_x = 30 + 6 * adv
        widths = [(0, num(len(BARCODE) * adv)), (0.6, 0)]
        widths += [(1.0 + 0.06 * k, num(k * adv)) for k in range(1, len(BARCODE) + 1)]
        out.append(f'<clipPath id="code"><rect x="{num(code_x)}" y="72" width="{widths[0][1]}" height="18">'
                   f'{discrete("width", widths, p)}</rect></clipPath>')
        out.append(f'<g clip-path="url(#code)">' + text(mono, BARCODE, 11, code_x, 84, "#7ee787", features=no_liga) + "</g>")
        cursor = [(t, num(code_x + float(w) + 1)) for t, w in widths]
        out.append(f'<rect x="{num(code_x + float(widths[0][1]) + 1)}" y="74" width="{num(adv - 1)}" height="13" '
                   f'fill="#e6edf3" fill-opacity="0.8">{discrete("x", cursor, p)}'
                   '<animate attributeName="opacity" values="1;0;1" keyTimes="0;0.5;1" calcMode="discrete" dur="1s" '
                   'repeatCount="indefinite"/></rect>')
        defs = ""
    return "\n".join(out), defs


def project_layout(fonts):
    regular = fonts["regular"]
    descs = [regular.wrap(desc, 12.5, THIRD - 32) for *_, desc, _ in PROJECTS]
    return descs, 176 + 17 * (max(map(len, descs)) - 1) + 56


def project(fonts, c, n):
    kind, company, title, _, stat = PROJECTS[n]
    W = THIRD
    descs, H = project_layout(fonts)
    regular, medium, semibold = fonts["regular"], fonts["medium"], fonts["semibold"]
    band, band_defs = illustration(kind, fonts, c)
    out = [f'<rect x="0.5" y="0.5" width="{W - 1}" height="112" fill="{c["accent2"]}" fill-opacity="0.04"/>',
           f'<rect x="0" y="112" width="{W}" height="1" fill="{c["border"]}"/>',
           band,
           text(semibold, company, 10.5, 16, 136, c["muted"], tracking=0.8),
           text(semibold, title, 15, 16, 157, c["text"]),
           lines(regular, descs[n], 12.5, 16, 177, 17, c["text"], 'fill-opacity="0.78"')]
    chip_w = medium.width(stat, 11.5) + 22
    chip_y = H - 38
    out.append(f'<rect x="16" y="{chip_y}" width="{num(chip_w)}" height="24" rx="12" fill="{c["accent1"]}" '
               f'fill-opacity="0.1" stroke="{c["accent1"]}" stroke-opacity="0.3"/>')
    out.append(text(medium, stat, 11.5, 27, chip_y + 16, c["accent1"]))
    return card(W, H, c, title, "\n".join(out), band_defs, below=GAP)


# Numbers ---------------------------------------------------------------------------------


def odometer(font, s, size, x, y, start, mask_id, period=9.0):
    """Draw text whose digits spin one full turn and land back on their value.

    Outside the spin every frame shows the real figure, so a still image reads correctly.
    Digits reuse the #digit-N shapes defined by number(). Returns (mask definition, markup).
    """
    placed, width = font.shape(s, size, features={"tnum": True})
    assert len(placed) == len(s), s
    step = size * 1.1
    static = [p for p, ch in zip(placed, s) if not ch.isdigit()]
    strips = []
    columns = [(gx, ch) for (_, gx, _), ch in zip(placed, s) if ch.isdigit()]
    for j, (gx, ch) in enumerate(columns):
        uses = "".join(f'<use href="#digit-{(int(ch) + k) % 10}" x="{num(x + gx)}" y="{num(y + k * step)}"/>'
                       for k in range(11))
        # Columns further right spin a little longer, like an odometer settling.
        end = start + 1.1 + 0.15 * j
        strips.append(f'<g><animateTransform attributeName="transform" type="translate" '
                      f'values="0 0;0 0;0 {num(-10 * step)};0 {num(-10 * step)}" '
                      f'keyTimes="0;{num(start / period, 4)};{num(end / period, 4)};1" calcMode="spline" '
                      f'keySplines="0 0 1 1;0.3 0.1 0.2 1;0 0 1 1" dur="{num(period)}s" '
                      f'repeatCount="indefinite"/>{uses}</g>')
    # The window fades out at the top and bottom, so spinning digits roll in and out softly.
    mask = (f'<mask id="{mask_id}"><rect x="{num(x - 4)}" y="{num(y - 0.98 * size)}" width="{num(width + 8)}" '
            f'height="{num(1.24 * size)}" fill="url(#window)"/></mask>')
    markup = (f'<path d="{font.draw(static, size, x, y)}"/>'
              f'<g mask="url(#{mask_id})">{"".join(strips)}</g>')
    return mask, markup


def number(fonts, c, n):
    W, size, top, leading = QUARTER, 34, 88, 18
    display, regular = fonts["display"], fonts["regular"]
    captions = [regular.wrap(caption, 13, W - 40) for _, caption in NUMBERS]
    H = top + leading * (max(map(len, captions)) - 1) + 24
    figure = NUMBERS[n][0]
    digits = "".join(f'<path id="digit-{d}" d="{display.path(str(d), size, 0, 0, features={"tnum": True})}"/>'
                     for d in range(10))
    mask, markup = odometer(display, figure, size, 20, 58, 0.6 + 0.25 * n, "digits-window")
    out = [f'<g fill="{mix(c["accent1"], c["accent2"], n / (len(NUMBERS) - 1))}">{markup}</g>',
           lines(regular, captions[n], 13, 20, top, leading, c["text"], 'fill-opacity="0.85"')]
    defs = ('<linearGradient id="window" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#000"/>'
            '<stop offset="0.2" stop-color="#fff"/><stop offset="0.8" stop-color="#fff"/>'
            f'<stop offset="1" stop-color="#000"/></linearGradient>{digits}{mask}')
    return card(W, H, c, f"{figure} {NUMBERS[n][1]}", "\n".join(out), defs, below=GAP)


# Stack and AI ----------------------------------------------------------------------------


def stack_layout():
    tile_h, gap = 72, 8
    tops = [48 + 15 * (len(extras) - 1) + 20 for _, extras, _ in STACK]
    rows = [-(-len(items) // 3) for *_, items in STACK]
    return tops, max(t + r * (tile_h + gap) - gap for t, r in zip(tops, rows)) + 16


def stack(fonts, c, n):
    """One stack group as a grid of named icon tiles. A wave lifts the tiles one by one."""
    W, tile_w, tile_h, gap, icon = THIRD, 70, 72, 8, 30
    medium, regular = fonts["medium"], fonts["regular"]
    group, extras, items = STACK[n]
    tops, H = stack_layout()
    pad = (W - 3 * tile_w - 2 * gap) / 2
    out = [text(medium, group, 15, pad, 30, c["text"]),
           lines(regular, extras, 11.5, pad, 48, 15, c["muted"])]
    period = 6.0
    for j, (name, label) in enumerate(items):
        x = pad + (j % 3) * (tile_w + gap)
        y = tops[n] + (j // 3) * (tile_h + gap)
        start = 0.5 + 0.35 * n + 0.1 * j
        times = [(0, 0), (start, 0), (start + 0.25, 1), (start + 0.6, 0)]
        out.append(
            f'<g>{move([(t, (0, -6 * v)) for t, v in times], period)}'
            f'<rect x="{num(x + 0.5)}" y="{num(y + 0.5)}" width="{tile_w - 1}" height="{tile_h - 1}" rx="12" '
            f'fill="{c["text"]}" fill-opacity="0.03" stroke="{c["border"]}">'
            f'{anim("stroke", [(t, c["accent1"] if v else c["border"]) for t, v in times], period)}</rect>'
            f'<image href="{icon_uri(name, c)}" x="{num(x + (tile_w - icon) / 2)}" y="{num(y + 11)}" '
            f'width="{icon}" height="{icon}"/>'
            + text(medium, label, 10.5, x + tile_w / 2, y + tile_h - 12, c["muted"], "center") + "</g>"
        )
    return card(W, H, c, f"{group}: " + ", ".join(label for _, label in items), "\n".join(out), below=GAP)


def ai_card(fonts, c, wide):
    """AI tools in a row. A pulse runs along the track below and lights each tile it passes.

    The wide version fills the README column with the title on the left; the compact one,
    for phones, puts the title above the tiles.
    """
    medium, regular = fonts["medium"], fonts["regular"]
    if wide:
        W, H, left, top = FULL, 176, 190, 24
        tile_w, tile_h, gap, icon, label_size = 96, 92, 24, 40, 12
        title_x, title_y = 32, top + tile_h / 2
    else:
        W, H, left, top = 396, 178, 12, 66
        tile_w, tile_h, gap, icon, label_size = 68, 68, 8, 30, 10
        title_x, title_y = 18, 32
    out = [text(medium, "AI toolkit", 17 if wide else 15, title_x, title_y, c["text"]),
           text(regular, "Coding · review · design", 12.5 if wide else 11.5, title_x, title_y + 20, c["muted"])]
    track = top + tile_h + (30 if wide else 22)
    xs = [left + j * (tile_w + gap) for j in range(len(AI_TOOLS))]
    centers = [x + tile_w / 2 for x in xs]
    period, start, travel = 5.0, 0.6, 2.0
    out.append(f'<rect x="{num(centers[0])}" y="{track - 0.75}" width="{num(centers[-1] - centers[0])}" height="1.5" '
               f'fill="{c["border"]}"/>')
    for cx in centers:
        out.append(f'<rect x="{num(cx - 0.75)}" y="{top + tile_h}" width="1.5" height="{track - top - tile_h}" '
                   f'fill="{c["border"]}"/>')
    out.append(f'<g>{move([(0, (centers[0], track)), (start, (centers[0], track)), (start + travel, (centers[-1], track))], period, "linear")}'
               f'{anim("opacity", [(0, 0), (start, 0), (start + 0.1, 1), (start + travel, 1), (start + travel + 0.2, 0)], period)}'
               '<rect x="-34" y="-1.5" width="34" height="3" rx="1.5" fill="url(#trail)"/>'
               f'<circle r="3.5" fill="{c["accent2"]}"/></g>')
    for (name, label), x, cx in zip(AI_TOOLS, xs, centers):
        hit = start + travel * (cx - centers[0]) / (centers[-1] - centers[0])
        times = [(0, 0), (hit - 0.1, 0), (hit, 1), (hit + 0.6, 0)]
        out.append(f'<rect x="{num(x - 3)}" y="{top - 3}" width="{tile_w + 6}" height="{tile_h + 6}" rx="14" '
                   f'stroke="{c["accent2"]}" stroke-width="3" stroke-opacity="0">'
                   f'{anim("stroke-opacity", [(t, 0.3 * v) for t, v in times], period)}</rect>')
        out.append(f'<rect x="{num(x + 0.5)}" y="{top + 0.5}" width="{tile_w - 1}" height="{tile_h - 1}" rx="12" '
                   f'fill="{c["bg1"]}" stroke="{c["border"]}">'
                   f'{anim("stroke", [(t, c["accent2"] if v else c["border"]) for t, v in times], period)}</rect>')
        out.append(f'<image href="{icon_uri(name, c)}" x="{num(cx - icon / 2)}" y="{top + (14 if wide else 10)}" '
                   f'width="{icon}" height="{icon}"/>')
        out.append(text(medium, label, label_size, cx, top + tile_h - (13 if wide else 10), c["muted"], "center"))
    defs = (f'<linearGradient id="trail" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{c["accent1"]}" '
            f'stop-opacity="0"/><stop offset="1" stop-color="{c["accent2"]}"/></linearGradient>')
    return card(W, H, c, "AI toolkit: " + ", ".join(label for _, label in AI_TOOLS), "\n".join(out), defs)


# Contact ---------------------------------------------------------------------------------


def contact(fonts, c, kind):
    label, value, W = next((lbl, val, w) for k, lbl, val, w in CONTACTS if k == kind)
    H, tile, tx = 76, 44, 16
    ty = (H - tile) / 2
    cx, cy = tx + tile / 2, ty + tile / 2
    medium, regular = fonts["medium"], fonts["regular"]
    period = 4.0
    out = [f'<clipPath id="tile"><rect x="{tx}" y="{num(ty)}" width="{tile}" height="{tile}" rx="12"/></clipPath>']
    if kind == "email":
        # A letter slides up out of the envelope, holds, and slides back in.
        out.append(f'<rect x="{tx}" y="{num(ty)}" width="{tile}" height="{tile}" rx="12" fill="url(#brand)"/>')
        body_y = cy - 5
        rise = move([(0, (0, 0)), (1.2, (0, 0)), (1.8, (0, -9)), (2.8, (0, -9)), (3.3, (0, 0))], period)
        out.append(f'<g clip-path="url(#tile)"><g>{rise}'
                   f'<rect x="{num(cx - 7)}" y="{num(body_y + 1)}" width="14" height="12" rx="1.5" fill="url(#brand)" '
                   'stroke="#fff" stroke-width="1.6"/>'
                   f'<path d="M{num(cx - 4)} {num(body_y + 4.5)}h8M{num(cx - 4)} {num(body_y + 7.5)}h5" stroke="#fff" '
                   'stroke-width="1.4" stroke-linecap="round"/></g></g>')
        out.append(f'<rect x="{num(cx - 11)}" y="{num(body_y)}" width="22" height="15" rx="2.5" fill="url(#brand)" '
                   'stroke="#fff" stroke-width="1.8"/>')
        out.append(f'<path d="M{num(cx - 10)} {num(body_y + 1.5)}L{num(cx)} {num(body_y + 8.5)}L{num(cx + 10)} {num(body_y + 1.5)}" '
                   'stroke="#fff" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>')
    elif kind == "telegram":
        # The paper plane flies off to the top right and glides back in from the bottom left.
        out.append(f'<rect x="{tx}" y="{num(ty)}" width="{tile}" height="{tile}" rx="12" fill="#229ed9"/>')
        flight = [(0, (0, 0)), (1.4, (0, 0)), (1.9, (34, -34)), (1.901, (-34, 34)), (2.6, (0, 0))]
        out.append(f'<g clip-path="url(#tile)"><g>{move(flight, period)}'
                   f'<path transform="translate({num(cx - 12)} {num(cy - 12)})" fill="#fff" '
                   'd="M2.6 11.4L20.6 4.3c.8-.3 1.5.2 1.2 1.4l-3.1 14.5c-.2 1-.8 1.3-1.7.8l-4.7-3.5-2.3 2.2'
                   'c-.3.3-.5.5-1 .5l.3-4.8 8.8-7.9c.4-.3-.1-.5-.6-.2L6.6 14.1 2 12.7c-1-.3-1-1 .6-1.3z"/></g></g>')
    else:
        # LinkedIn mark with a padlock badge whose shackle lifts, as if about to open.
        out.append(f'<rect x="{tx}" y="{num(ty)}" width="{tile}" height="{tile}" rx="12" fill="#0a66c2"/>')
        out.append(f'<path transform="translate({num(cx - 12)} {num(cy - 12)})" fill="#fff" '
                   'd="M4.9 9.6h3.6V20H4.9zM6.7 3.8a2.1 2.1 0 1 1 0 4.2 2.1 2.1 0 0 1 0-4.2zM10.7 9.6h3.4v1.4'
                   'c.5-.9 1.7-1.7 3.4-1.7 3.6 0 4.3 2.4 4.3 5.4V20h-3.6v-4.6c0-1.1 0-2.5-1.5-2.5s-1.8 1.2-1.8 2.4V20'
                   'h-3.6z"/>')
        bx, by = tx + tile - 1, ty + tile - 1
        out.append(f'<circle cx="{num(bx)}" cy="{num(by)}" r="10" fill="{c["bg1"]}" stroke="{c["border"]}"/>')
        out.append(f'<rect x="{num(bx - 4)}" y="{num(by - 0.5)}" width="8" height="6" rx="1.4" fill="{c["muted"]}"/>')
        lift = move([(0, (0, 0)), (1.5, (0, 0)), (1.8, (0, -1.8)), (2.5, (0, -1.8)), (2.8, (0, 0))], period, "linear")
        out.append(f'<path d="M{num(bx - 2.5)} {num(by - 0.5)}v-2a2.5 2.5 0 0 1 5 0v2" stroke="{c["muted"]}" '
                   f'stroke-width="1.6" stroke-linecap="round">{lift}</path>')

    tx_text = tx + tile + 14
    out.append(text(regular, label, 11.5, tx_text, 32, c["muted"]))
    out.append(text(medium, value, 15, tx_text, 53, c["text"]))
    # A small arrow nudges toward the corner to show the card is a link.
    out.append(f'<path d="M{W - 25} 24L{W - 16} 15M{W - 22.5} 15H{W - 16}V21.5" stroke="{c["muted"]}" '
               'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
               '<animateTransform attributeName="transform" type="translate" values="0 0;2 -2;0 0" '
               'keyTimes="0;0.5;1" calcMode="spline" keySplines="0.4 0 0.6 1;0.4 0 0.6 1" dur="2s" '
               'repeatCount="indefinite"/></path>')
    defs = (f'<linearGradient id="brand" x1="{tx}" y1="{num(ty)}" x2="{tx + tile}" y2="{num(ty + tile)}" '
            f'gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="{c["accent1"]}"/>'
            f'<stop offset="1" stop-color="{c["accent2"]}"/></linearGradient>')
    return card(W, H, c, f"{label}: {value}", "\n".join(out), defs, glow=(W, 0), below=GAP)


def themed(light, dark):
    """Merge a card's light and dark versions into one SVG that follows prefers-color-scheme.

    Phone layouts use this: their <picture> source is picked by screen width, so it can't
    also be picked by theme the way the other cards are.
    """
    open_tag = light[:light.index(">", light.index("<svg")) + 1]
    title = re.search(r"<title>.*?</title>", light).group(0)

    def body(svg, prefix):
        inner = svg[svg.index(">", svg.index("<svg")) + 1:svg.rindex("</svg>")]
        inner = re.sub(r"<title>.*?</title>", "", inner, count=1)
        if prefix:
            inner = re.sub(r'id="([^"]+)"', rf'id="{prefix}\1"', inner)
            inner = re.sub(r"url\(#([^)]+)\)", rf"url(#{prefix}\1)", inner)
            inner = re.sub(r'href="#([^"]+)"', rf'href="#{prefix}\1"', inner)
        return inner

    style = ("<style>.dark{display:none}"
             "@media (prefers-color-scheme: dark){.light{display:none}.dark{display:inline}}</style>")
    return (f'{open_tag}\n{title}\n{style}\n<g class="light">{body(light, "")}</g>\n'
            f'<g class="dark">{body(dark, "d-")}</g>\n</svg>\n')


def builds():
    """(file name, builder, phone) for every card. Phone variants get one file for both themes."""
    yield "hero", hero, False
    yield "hero-mobile", hero_mobile, True
    for n in range(len(TIMELINE)):
        yield f"timeline-{n + 1}", lambda f, c, n=n: timeline(f, c, n), False
    for n, (kind, *_) in enumerate(PROJECTS):
        yield f"project-{kind}", lambda f, c, n=n: project(f, c, n), False
    for n in range(len(NUMBERS)):
        yield f"number-{n + 1}", lambda f, c, n=n: number(f, c, n), False
    for n, (group, *_) in enumerate(STACK):
        yield f"stack-{group.split()[0].lower()}", lambda f, c, n=n: stack(f, c, n), False
    yield "ai", lambda f, c: ai_card(f, c, wide=True), False
    yield "ai-mobile", lambda f, c: ai_card(f, c, wide=False), True
    for kind, *_ in CONTACTS:
        yield f"contact-{kind}", lambda f, c, kind=kind: contact(f, c, kind), False


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--fonts", required=True, type=pathlib.Path)
    args = parser.parse_args()
    fonts = {
        "display": Font(args.fonts / "InterDisplay-Bold.otf"),
        "regular": Font(args.fonts / "Inter-Regular.otf"),
        "medium": Font(args.fonts / "Inter-Medium.otf"),
        "semibold": Font(args.fonts / "Inter-SemiBold.otf"),
        "mono": Font(args.fonts / "jetbrains-mono-latin-400-normal.woff2"),
    }
    CARDS.mkdir(exist_ok=True)
    for old in CARDS.glob("*.svg"):
        old.unlink()
    for name, build, phone in builds():
        if phone:
            (CARDS / f"{name}.svg").write_text(themed(build(fonts, THEMES["light"]), build(fonts, THEMES["dark"])))
        else:
            for colors in THEMES.values():
                (CARDS / f"{name}{colors['suffix']}.svg").write_text(build(fonts, colors))
    files = list(CARDS.glob("*.svg"))
    total = sum(f.stat().st_size for f in files)
    print(f"{len(files)} cards in {CARDS.relative_to(ASSETS.parent)}, {total // 1024} KB")


if __name__ == "__main__":
    main()
