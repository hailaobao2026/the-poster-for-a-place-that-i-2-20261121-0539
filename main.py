#!/usr/bin/env python3
"""VELMARA - a travel poster for a place that does not exist.

A floating island with a lighthouse drifts above a sea of clouds at dusk,
under a ringed planet. The poster is drawn entirely with code: a software
framebuffer, scanline polygon/ellipse fills, thick-stroke vector
letterforms (no font file, no image library) and a hand-written PNG
encoder from zlib. Standard library only, so it runs in the grading
sandbox (python:3.13-slim, no network).

Writes 1024x1024 entry.png to $MAKEFUN_OUTPUT_DIR (default /output),
mode 0644. Deterministic: fixed seed, no clock, no network.
"""

import math
import os
import struct
import zlib

W, H = 1024, 1024
OUT_NAME = "entry.png"

# ---------------------------------------------------------------- colours

def C(hexs):
    return (int(hexs[0:2], 16), int(hexs[2:4], 16), int(hexs[4:6], 16))


def mix(a, b, t):
    return (round(a[0] + (b[0] - a[0]) * t),
            round(a[1] + (b[1] - a[1]) * t),
            round(a[2] + (b[2] - a[2]) * t))


# ---------------------------------------------------------------- framebuffer

buf = bytearray(W * H * 3)


def put(x, y, col):
    if 0 <= x < W and 0 <= y < H:
        i = (y * W + x) * 3
        buf[i] = col[0]
        buf[i + 1] = col[1]
        buf[i + 2] = col[2]


def blend_px(x, y, col, a):
    if 0 <= x < W and 0 <= y < H:
        i = (y * W + x) * 3
        buf[i] = round(buf[i] * (1 - a) + col[0] * a)
        buf[i + 1] = round(buf[i + 1] * (1 - a) + col[1] * a)
        buf[i + 2] = round(buf[i + 2] * (1 - a) + col[2] * a)


def _fill_span(y, xa, xb, col, alpha=1.0):
    xa = max(0, xa)
    xb = min(W, xb)
    if xb <= xa:
        return
    if alpha >= 1.0:
        i = (y * W + xa) * 3
        buf[i:i + (xb - xa) * 3] = bytes(col) * (xb - xa)
    else:
        for x in range(xa, xb):
            blend_px(x, y, col, alpha)


def fill_rect(x0, y0, x1, y1, col):
    x0 = max(0, int(x0))
    y0 = max(0, int(y0))
    x1 = min(W, int(x1))
    y1 = min(H, int(y1))
    row = bytes(col) * (x1 - x0)
    for y in range(y0, y1):
        i = (y * W + x0) * 3
        buf[i:i + len(row)] = row


def _row_spans(y, pts):
    xs = []
    n = len(pts)
    for k in range(n):
        x1, y1 = pts[k]
        x2, y2 = pts[(k + 1) % n]
        if (y1 <= y + 0.5 < y2) or (y2 <= y + 0.5 < y1):
            t = (y + 0.5 - y1) / (y2 - y1)
            xs.append(x1 + t * (x2 - x1))
    xs.sort()
    return xs


def fill_polygon(pts, col, alpha=1.0):
    ys = [p[1] for p in pts]
    y0 = max(0, int(math.floor(min(ys))))
    y1 = min(H, int(math.ceil(max(ys))) + 1)
    for y in range(y0, y1):
        xs = _row_spans(y, pts)
        for k in range(0, len(xs) - 1, 2):
            _fill_span(y, int(math.ceil(xs[k])), int(math.floor(xs[k + 1])),
                       col, alpha)


def fill_ellipse(cx, cy, rx, ry, col, alpha=1.0):
    y0 = max(0, int(cy - ry))
    y1 = min(H, int(cy + ry) + 1)
    for y in range(y0, y1):
        dy = (y + 0.5 - cy) / ry
        if abs(dy) >= 1:
            continue
        dx = rx * math.sqrt(1 - dy * dy)
        _fill_span(y, int(math.ceil(cx - dx)), int(math.floor(cx + dx)),
                   col, alpha)


def fill_circle(cx, cy, r, col, alpha=1.0):
    fill_ellipse(cx, cy, r, r, col, alpha)


def thick_line(x1, y1, x2, y2, w, col):
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        fill_circle(x1, y1, w / 2, col)
        return
    nx, ny = -dy / length * w / 2, dx / length * w / 2
    fill_polygon([(x1 + nx, y1 + ny), (x2 + nx, y2 + ny),
                  (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)], col)
    fill_circle(x1, y1, w / 2, col)
    fill_circle(x2, y2, w / 2, col)


def radial_glow(cx, cy, r, col, peak):
    """Soft round glow; squared-distance falloff, no sqrt per pixel."""
    x0 = max(0, int(cx - r))
    x1 = min(W, int(cx + r) + 1)
    y0 = max(0, int(cy - r))
    y1 = min(H, int(cy + r) + 1)
    r2 = r * r
    for y in range(y0, y1):
        dy = y + 0.5 - cy
        for x in range(x0, x1):
            dx = x + 0.5 - cx
            q = (dx * dx + dy * dy) / r2
            if q < 1:
                blend_px(x, y, col, peak * (1 - q) * (1 - q))


# ---------------------------------------------------------------- deterministic RNG

_seed = [20261121]


def rnd():
    _seed[0] = (_seed[0] * 1103515245 + 12345) & 0x7FFFFFFF
    return _seed[0] / 0x7FFFFFFF


# ---------------------------------------------------------------- sky

SKY_STOPS = [(0.00, C("191238")), (0.28, C("2E1B52")), (0.50, C("6B2D63")),
             (0.68, C("B4453F")), (0.84, C("E8722E")), (1.00, C("F7B733"))]


def _sky_color(t):
    for k in range(len(SKY_STOPS) - 1):
        t0, c0 = SKY_STOPS[k]
        t1, c1 = SKY_STOPS[k + 1]
        if t0 <= t <= t1:
            return mix(c0, c1, (t - t0) / (t1 - t0))
    return SKY_STOPS[-1][1]


def paint_sky():
    for y in range(H):
        col = _sky_color(y / (H - 1))
        i = y * W * 3
        buf[i:i + W * 3] = bytes(col) * W


def paint_stars():
    # Sparse stars, only in the deep-violet upper sky; keep clear of the
    # name band and of the planet.
    for _ in range(90):
        x = rnd() * W
        y = rnd() * 400
        if y < 245 and 130 < x < 890:
            continue
        if math.hypot(x - 785, y - 335) < 200:
            continue
        r = 1.0 if rnd() < 0.6 else 1.8
        fade = 1.0 - y / 520.0
        col = mix(C("FFF4DC"), C("B9A8D8"), rnd() * 0.5)
        fill_circle(x, y, r, col, alpha=0.35 + 0.6 * fade)


# ---------------------------------------------------------------- planet

PLANET = (785, 335, 108)


def _disc_span(y, cx, cy, r):
    dy = (y + 0.5 - cy) / r
    if abs(dy) >= 1:
        return None
    dx = r * math.sqrt(1 - dy * dy)
    return (int(math.ceil(cx - dx)), int(math.floor(cx + dx)))


def draw_ring(cx, cy, rx, ry, tilt_deg, col, front):
    th = math.radians(tilt_deg)
    ct, st = math.cos(th), math.sin(th)
    for y in range(max(0, int(cy - ry) - 4), min(H, int(cy + ry) + 5)):
        for x in range(max(0, int(cx - rx) - 4), min(W, int(cx + rx) + 5)):
            dx, dy = x + 0.5 - cx, y + 0.5 - cy
            lx = dx * ct + dy * st
            ly = -dx * st + dy * ct
            rr = math.hypot(lx / rx, ly / ry)
            if 0.86 <= rr <= 1.0 and ((ly >= 0) == front):
                put(x, y, col)


def draw_planet():
    cx, cy, r = PLANET
    radial_glow(cx, cy, 195, C("F4C882"), 0.30)
    draw_ring(cx, cy, 168, 52, -12, C("E9C98F"), front=False)
    fill_circle(cx, cy, r, C("F4D9A0"))
    # Horizontal bands across the disc.
    for (lo, hi, col) in ((-62, -32, C("E8BE78")), (-6, 16, C("D9A45C")),
                          (40, 68, C("E8BE78"))):
        for y in range(int(cy + lo), int(cy + hi) + 1):
            span = _disc_span(y, cx, cy, r)
            if span:
                _fill_span(y, span[0], span[1], col)
    # Dusk shadow on the left limb.
    ex, ey, erx, ery = cx - 44, cy - 4, 92, 100
    for y in range(max(0, int(ey - ery)), min(H, int(ey + ery) + 1)):
        for x in range(max(0, int(ex - erx)), min(W, int(ex + erx) + 1)):
            if (((x + 0.5 - ex) / erx) ** 2 + ((y + 0.5 - ey) / ery) ** 2 <= 1
                    and math.hypot(x + 0.5 - cx, y + 0.5 - cy) <= r):
                blend_px(x, y, C("8A6A5A"), 0.38)
    draw_ring(cx, cy, 168, 52, -12, C("E9C98F"), front=True)


def draw_birds():
    col = C("241A3E")
    for (x, y, s) in [(170, 330, 14), (235, 300, 11), (290, 352, 9),
                      (205, 392, 8)]:
        thick_line(x - s, y + s * 0.45, x, y, 3, col)
        thick_line(x, y, x + s, y + s * 0.45, 3, col)


# ---------------------------------------------------------------- island

ROCK = [(322, 478), (392, 460), (468, 466), (548, 454), (628, 462),
        (702, 472), (668, 532), (622, 592), (566, 642), (516, 672),
        (484, 650), (436, 606), (384, 556), (340, 512)]


def draw_island():
    fill_polygon(ROCK, C("332A45"))
    # Cool facet of shadow on the left underside.
    fill_polygon([(340, 498), (392, 464), (440, 472), (420, 530),
                  (385, 575), (352, 535)], C("241D38"))
    # Warm rim light along the sun-facing right edge (thin strip).
    fill_polygon([(628, 462), (700, 472), (666, 532), (620, 592),
                  (566, 642), (600, 598), (652, 534), (684, 486),
                  (656, 468)], C("F7B733"))
    # Grassy cap.
    fill_ellipse(512, 462, 180, 20, C("607850"))
    fill_ellipse(512, 456, 160, 13, C("6E8A5E"))


def draw_lighthouse():
    radial_glow(512, 372, 46, C("FFD76A"), 0.75)
    fill_rect(492, 384, 532, 462, C("F5EFE0"))
    fill_rect(524, 384, 532, 462, C("E3D9C2"))  # shaded side of the tower
    fill_rect(498, 362, 526, 384, C("FFD76A"))  # lamp room
    fill_rect(496, 362, 499, 384, C("332A45"))
    fill_rect(525, 362, 528, 384, C("332A45"))
    fill_polygon([(488, 362), (536, 362), (512, 336)], C("C4452B"))
    fill_circle(512, 334, 3, C("C4452B"))
    fill_rect(506, 410, 518, 430, C("332A45"))  # window
    fill_rect(504, 442, 520, 462, C("332A45"))  # door


# ---------------------------------------------------------------- clouds & falls

CLOUDS = [
    (512, 775, 760, 64, C("F9E7C8")),
    (180, 800, 320, 58, C("E8B98A")),
    (860, 795, 300, 55, C("E8B98A")),
    (512, 830, 420, 62, C("E8B98A")),
    (120, 870, 300, 58, C("D9A06F")),
    (900, 865, 310, 60, C("D9A06F")),
    (430, 900, 360, 66, C("E8B98A")),
    (700, 905, 300, 60, C("7A5578")),
    (180, 940, 320, 62, C("7A5578")),
    (850, 950, 320, 64, C("7A5578")),
    (512, 975, 460, 70, C("4A3360")),
    (350, 960, 260, 48, C("5E4370")),
    (680, 965, 260, 48, C("5E4370")),
    (240, 1000, 340, 60, C("4A3360")),
    (800, 1005, 340, 62, C("4A3360")),
]


def draw_clouds():
    fill_rect(0, 770, W, H, C("2A1E44"))
    for (cx, cy, rx, ry, col) in CLOUDS:
        fill_ellipse(cx, cy, rx, ry, col)


def draw_light_path():
    fill_polygon([(488, 800), (536, 800), (580, 1000), (444, 1000)],
                 C("E8B34B"), alpha=0.12)
    fill_polygon([(502, 800), (522, 800), (544, 1000), (480, 1000)],
                 C("F7D774"), alpha=0.10)


def draw_waterfall():
    fill_polygon([(498, 640), (526, 640), (540, 806), (484, 806)],
                 C("8CB4CD"))
    fill_polygon([(506, 640), (518, 640), (524, 806), (500, 806)],
                 C("F0F6FA"))
    thick_line(510, 660, 508, 800, 3, C("EAF4FA"))
    # Low puffs tuck the foot of the falls into the cloud sea.
    fill_ellipse(470, 832, 90, 26, C("E8B98A"))
    fill_ellipse(556, 838, 80, 24, C("D9A06F"))
    # Mist at the base.
    fill_ellipse(512, 802, 46, 16, C("E8F0F8"), alpha=0.55)
    fill_ellipse(512, 806, 30, 12, C("E8F0F8"), alpha=0.50)
    fill_ellipse(512, 808, 20, 9, C("E8F0F8"), alpha=0.45)


# ---------------------------------------------------------------- type

# Bold geometric capitals on a 7 x 10 unit cell, built from thick strokes.
# Each letter is a list of segments; advance is 8.4 units, so letters never
# touch (widest drawn extent is ~6.95 units).
LETTERS = {
    "V": [((0.9, 0.6), (3.5, 9.4)), ((6.1, 0.6), (3.5, 9.4))],
    "E": [((0.9, 0.6), (0.9, 9.4)), ((0.9, 0.6), (6.1, 0.6)),
          ((0.9, 5.0), (5.0, 5.0)), ((0.9, 9.4), (6.1, 9.4))],
    "L": [((0.9, 0.6), (0.9, 9.4)), ((0.9, 9.4), (6.1, 9.4))],
    "M": [((0.9, 9.4), (0.9, 0.6)), ((0.9, 0.6), (3.5, 5.4)),
          ((3.5, 5.4), (6.1, 0.6)), ((6.1, 0.6), (6.1, 9.4))],
    "A": [((0.9, 9.4), (3.5, 0.6)), ((3.5, 0.6), (6.1, 9.4)),
          ((1.95, 6.6), (5.05, 6.6))],
    "R": [((0.9, 0.6), (0.9, 9.4)), ((0.9, 0.6), (5.3, 0.6)),
          ((5.3, 0.6), (5.3, 5.0)), ((0.9, 5.0), (5.3, 5.0)),
          ((4.2, 5.0), (6.1, 9.4))],
}


def draw_word(word, x0, y0, unit, stroke, col):
    x = x0
    for ch in word:
        for (ax, ay), (bx, by) in LETTERS[ch]:
            thick_line(x + ax * unit, y0 + ay * unit,
                       x + bx * unit, y0 + by * unit,
                       stroke * unit, col)
        x += 8.4 * unit


def draw_name():
    unit = 12.4  # cap height 124 px
    width = 6 * 8.4 * unit + 7 * unit
    x0 = (W - width) / 2
    y0 = 96
    draw_word("VELMARA", x0 + 4, y0 + 5, unit, 1.7, C("2A1B4A"))
    draw_word("VELMARA", x0, y0, unit, 1.7, C("FFF4DC"))
    fill_rect(412, 246, 612, 250, C("E8B34B"))
    fill_polygon([(512, 238), (522, 248), (512, 258), (502, 248)],
                 C("E8B34B"))


# ---------------------------------------------------------------- PNG output

def _chunk(tag, data):
    body = tag + data
    return (struct.pack(">I", len(data)) + body +
            struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))


def write_png(path):
    raw = b"".join(b"\x00" + bytes(buf[y * W * 3:(y + 1) * W * 3])
                   for y in range(H))
    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) +
           _chunk(b"IDAT", zlib.compress(raw, 6)) + _chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def main():
    paint_sky()
    paint_stars()
    radial_glow(512, 700, 380, C("F7B733"), 0.30)
    draw_planet()
    draw_birds()
    draw_island()
    draw_lighthouse()
    draw_clouds()
    draw_light_path()
    draw_waterfall()
    draw_name()

    outdir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, OUT_NAME)
    write_png(path)
    os.chmod(path, 0o644)
    print("wrote %s %d bytes" % (path, os.path.getsize(path)))


if __name__ == "__main__":
    main()
