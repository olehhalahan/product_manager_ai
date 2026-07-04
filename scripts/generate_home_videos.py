#!/usr/bin/env python3
"""Generate rich Cartozo homepage demo videos (walnut UI mockups)."""
from __future__ import annotations

import math
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "static" / "home-media"
FPS = 30

# ORYZO / Cartozo palette
WALNUT = (16, 9, 4)
BARK = (56, 36, 22)
CORK = (64, 55, 46)
CREAM = (255, 237, 215)
DRIFT = (108, 95, 81)
EMBER = (220, 80, 0)
GREEN = (74, 222, 128)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _lerp_color(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (
        int(_lerp(c1[0], c2[0], t)),
        int(_lerp(c1[1], c2[1], t)),
        int(_lerp(c1[2], c2[2], t)),
    )


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _draw_dashed_hline(draw: ImageDraw.ImageDraw, y: int, x0: int, x1: int, color: tuple, width: int = 1, dash: int = 6) -> None:
    x = x0
    while x < x1:
        draw.line([(x, y), (min(x + dash, x1), y)], fill=color, width=width)
        x += dash * 2


def _draw_feed_window(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    filename: str = "product_feed.csv",
    badge: str = "CSV",
) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    draw.rectangle(box, fill=BARK, outline=CORK, width=1)
    bar_h = 36
    draw.rectangle([x0, y0, x1, y0 + bar_h], fill=(24, 14, 8))
    _draw_dashed_hline(draw, y0 + bar_h, x0, x1, CORK)
    f_sm = _font(11)
    draw.text((x0 + 14, y0 + 11), filename.upper(), fill=DRIFT, font=f_sm)
    bw = draw.textbbox((0, 0), badge, font=f_sm)
    bw_w = bw[2] - bw[0]
    bx1 = x1 - 12
    bx0 = bx1 - bw_w - 16
    draw.rectangle([bx0, y0 + 8, bx1, y0 + 26], outline=CORK, width=1)
    draw.text((bx0 + 8, y0 + 10), badge, fill=DRIFT, font=f_sm)
    return x0 + 12, y0 + bar_h + 8, x1 - 12, y1 - 12


def _draw_table_header(draw: ImageDraw.ImageDraw, inner: tuple, cols: list[str]) -> int:
    x0, y0, x1, _ = inner
    f = _font(10, bold=True)
    col_w = (x1 - x0) // len(cols)
    y = y0 + 4
    for i, label in enumerate(cols):
        draw.text((x0 + i * col_w + 4, y), label.upper(), fill=DRIFT, font=f)
    _draw_dashed_hline(draw, y0 + 22, x0, x1, CORK)
    return y0 + 30


def _draw_row(
    draw: ImageDraw.ImageDraw,
    inner: tuple,
    y: int,
    cols: list[str],
    *,
    widths: list[int] | None = None,
    colors: list[tuple] | None = None,
    highlight: float = 0.0,
) -> int:
    x0, _, x1, _ = inner
    n = len(cols)
    col_w = (x1 - x0) // n
    if highlight > 0:
        draw.rectangle([x0, y - 2, x1, y + 22], fill=(int(BARK[0] + 20 * highlight), int(BARK[1] + 12 * highlight), int(BARK[2] + 8 * highlight)))
    f = _font(11)
    for i, text in enumerate(cols):
        c = colors[i] if colors else CREAM
        max_chars = (widths[i] if widths else 18)
        t = text if len(text) <= max_chars else text[: max_chars - 1] + "…"
        draw.text((x0 + i * col_w + 4, y), t, fill=c, font=f)
    _draw_dashed_hline(draw, y + 20, x0, x1, (CORK[0], CORK[1], CORK[2], 128) if False else CORK)
    return y + 26


def _draw_scanline(draw: ImageDraw.ImageDraw, inner: tuple, scan_y: float, alpha: float) -> None:
    x0, y0, x1, y1 = inner
    sy = int(y0 + (y1 - y0) * scan_y)
    for i in range(4):
        a = int(180 * alpha * (1 - i / 4))
        draw.line([(x0, sy + i), (x1, sy + i)], fill=(220, 80, 0, a), width=1)
    draw.line([(x0, sy), (x1, sy)], fill=EMBER, width=2)


def _draw_score_pill(draw: ImageDraw.ImageDraw, x: int, y: int, score: int, target: int, t: float) -> None:
    val = int(_lerp(score, target, _ease(t)))
    label = f"Q {val}"
    f = _font(12, bold=True)
    bb = draw.textbbox((0, 0), label, font=f)
    w, h = bb[2] - bb[0] + 16, bb[3] - bb[1] + 10
    col = _lerp_color(DRIFT, EMBER, _ease(t) if target > score else 0)
    draw.rounded_rectangle([x, y, x + w, y + h], radius=12, outline=CORK, fill=(32, 20, 12))
    draw.text((x + 8, y + 4), label, fill=col, font=f)


def _draw_badge(draw: ImageDraw.ImageDraw, cx: int, cy: int, text: str, *, pulse: float = 0.0) -> None:
    f = _font(13, bold=True)
    bb = draw.textbbox((0, 0), text, font=f)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    pad_x, pad_y = 18, 10
    x0 = cx - (tw + pad_x * 2) // 2
    y0 = cy - (th + pad_y * 2) // 2
    glow = int(40 + 30 * pulse)
    draw.rounded_rectangle([x0 - 2, y0 - 2, x0 + tw + pad_x * 2 + 2, y0 + th + pad_y * 2 + 2], radius=20, fill=(glow, glow // 3, 0))
    draw.rounded_rectangle([x0, y0, x0 + tw + pad_x * 2, y0 + th + pad_y * 2], radius=18, fill=BARK, outline=EMBER, width=1)
    draw.text((x0 + pad_x, y0 + pad_y - 1), text, fill=CREAM, font=f)


def _brand_header(draw: ImageDraw.ImageDraw, w: int, label: str) -> None:
    draw.text((32, 24), "CARTOZO FEED-1", fill=DRIFT, font=_font(11))
    draw.text((32, 44), label.upper(), fill=CREAM, font=_font(22, bold=True))


def frame_main_demo(t: float, duration: float) -> Image.Image:
    w, h = 960, 540
    img = Image.new("RGB", (w, h), WALNUT)
    draw = ImageDraw.Draw(img)

    # Ambient glow
    for r in range(3):
        gx = int(w * 0.72 + math.sin(t * 1.2) * 20)
        gy = int(h * 0.35 + math.cos(t * 0.9) * 15)
        rad = 180 + r * 40
        col = (int(BARK[0] * 0.4), int(BARK[1] * 0.35), int(BARK[2] * 0.3))
        draw.ellipse([gx - rad, gy - rad, gx + rad, gy + rad], fill=col)

    phase = t / duration
    _brand_header(draw, w, "Full catalog optimization")

    box = (48, 88, w - 48, h - 56)
    inner = _draw_feed_window(draw, box)
    cols_hdr = ["id", "title", "brand", "score"]
    y = _draw_table_header(draw, inner, cols_hdr)

    before_rows = [
        ("12345", "Generic Chair Black", "Unknown", "42"),
        ("12346", "Blue Shirt", "—", "38"),
        ("12347", "Running Shoes", "Nike?", "51"),
        ("12348", "Desk Lamp White", "—", "44"),
    ]
    after_rows = [
        ("12345", "IKEA Black Dining Chair Modern Kitchen", "IKEA", "91"),
        ("12346", "Mens Cotton Oxford Shirt Blue Slim Fit", "Brooks", "86"),
        ("12347", "Nike Air Max 90 White Mens Running", "Nike", "88"),
        ("12348", "LED Desk Lamp Adjustable White Office", "Philips", "84"),
    ]

    morph_start, morph_end = 0.28, 0.62
    scan_start, scan_end = 0.18, 0.32
    if scan_start <= phase <= scan_end:
        st = (phase - scan_start) / (scan_end - scan_start)
        _draw_scanline(draw, inner, st, 1.0 - abs(st - 0.5) * 2)

    for i, (b, a) in enumerate(zip(before_rows, after_rows)):
        row_phase = _ease(max(0, min(1, (phase - morph_start - i * 0.06) / (morph_end - morph_start))))
        title = b[1] if row_phase < 0.5 else a[1]
        if 0.45 < row_phase < 0.55:
            title = a[1][: int(len(a[1]) * ((row_phase - 0.45) / 0.1))] or b[1][:8]
        score_b, score_a = int(b[3]), int(a[3])
        score = int(_lerp(score_b, score_a, _ease(max(0, (row_phase - 0.3) / 0.7))) if row_phase > 0 else score_b)
        hl = 0.35 if 0.4 < row_phase < 0.75 else 0.0
        colors = [DRIFT, CREAM if row_phase > 0.5 else DRIFT, DRIFT, EMBER if score >= 80 else DRIFT]
        y = _draw_row(draw, inner, y, [b[0], title, a[2] if row_phase > 0.6 else b[2], str(score)], colors=colors, highlight=hl, widths=[6, 28, 10, 4])

    if phase > 0.72:
        bt = _ease(min(1, (phase - 0.72) / 0.12))
        _draw_badge(draw, w // 2, h - 28, "MERCHANT READY", pulse=math.sin(t * 4) * 0.5 + 0.5 if phase > 0.85 else 0)

    if phase < 0.18:
        draw.text((inner[0], inner[1] - 18), "BEFORE", fill=DRIFT, font=_font(10, bold=True))
    elif phase < morph_end:
        draw.text((inner[0], inner[1] - 18), "OPTIMIZING…", fill=EMBER, font=_font(10, bold=True))
    else:
        draw.text((inner[0], inner[1] - 18), "AFTER", fill=GREEN, font=_font(10, bold=True))

    return img


def frame_titles(t: float, duration: float) -> Image.Image:
    w, h = 640, 400
    img = Image.new("RGB", (w, h), WALNUT)
    draw = ImageDraw.Draw(img)
    _brand_header(draw, w, "Title rewrite")
    inner = _draw_feed_window(draw, (28, 82, w - 28, h - 36), badge="INTENT")
    y = _draw_table_header(draw, inner, ["sku", "title", "match"])

    pairs = [
        ("SKU-01", "Blue Shirt", "Mens Cotton Oxford Shirt Blue Slim Fit", 47),
        ("SKU-02", "Shoes", "Nike Air Max 90 White Mens Running Shoe", 52),
        ("SKU-03", "Chair", "IKEA Black Dining Chair Modern Kitchen Set", 61),
    ]
    phase = t / duration
    for i, (sku, before, after, match) in enumerate(pairs):
        p = _ease(max(0, min(1, (phase - 0.15 - i * 0.12) / 0.35)))
        title = before if p < 0.5 else after
        if 0.45 < p < 0.55:
            title = after[: max(1, int(len(after) * ((p - 0.45) / 0.1)))]
        m = int(_lerp(30, match, _ease(max(0, (p - 0.4) / 0.6))) if p > 0 else 30)
        y = _draw_row(
            draw, inner, y,
            [sku, title, f"+{m}%"],
            colors=[DRIFT, CREAM if p > 0.5 else DRIFT, EMBER if m > 40 else DRIFT],
            highlight=0.3 if 0.3 < p < 0.7 else 0,
            widths=[8, 30, 6],
        )
    if phase > 0.05 and phase < 0.55:
        _draw_scanline(draw, inner, min(1, phase * 1.8), 0.8)
    return img


def frame_disapproval(t: float, duration: float) -> Image.Image:
    w, h = 640, 400
    img = Image.new("RGB", (w, h), WALNUT)
    draw = ImageDraw.Draw(img)
    _brand_header(draw, w, "Disapproval fix")
    inner = _draw_feed_window(draw, (28, 82, w - 28, h - 36), badge="GMC")
    y = _draw_table_header(draw, inner, ["id", "issue", "status"])

    issues = [
        ("8821", "Missing GTIN", "1234567890123", "approved"),
        ("8822", "Invalid brand", "IKEA", "approved"),
        ("8823", "Image too small", "1200×1200 added", "approved"),
    ]
    phase = t / duration
    for i, (pid, issue, fix, status) in enumerate(issues):
        p = _ease(max(0, min(1, (phase - 0.12 - i * 0.14) / 0.3)))
        mid = issue if p < 0.55 else fix
        stat = "disapproved" if p < 0.7 else status
        sc = (239, 68, 68) if stat == "disapproved" else GREEN
        y = _draw_row(
            draw, inner, y,
            [pid, mid, stat.upper()],
            colors=[DRIFT, CREAM if p > 0.5 else DRIFT, sc],
            highlight=0.35 if 0.2 < p < 0.75 else 0,
            widths=[6, 28, 12],
        )
    if phase > 0.65:
        _draw_badge(draw, w // 2, h - 24, "3 ISSUES FIXED", pulse=0.3)
    return img


def render_video(name: str, duration: float, frame_fn, *, width: int | None = None, height: int | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / name
    total = int(duration * FPS)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        sample = frame_fn(0, duration)
        w, h = sample.size if width is None else (width, height)
        for i in range(total):
            t = i / FPS
            frame = frame_fn(t, duration)
            if frame.size != (w, h):
                frame = frame.resize((w, h), Image.Resampling.LANCZOS)
            frame.save(tmp_path / f"frame_{i:05d}.png")
        pattern = str(tmp_path / "frame_%05d.png")
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(FPS),
            "-i", pattern,
            "-c:v", "libvpx-vp9",
            "-pix_fmt", "yuv420p",
            "-b:v", "1800k",
            "-crf", "32",
            str(out_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    # Poster from mid-frame
    poster = frame_fn(duration * 0.55, duration)
    poster_path = OUT / name.replace(".webm", "-poster.jpg")
    poster.save(poster_path, quality=88, optimize=True)
    print(f"Wrote {out_path} ({w}x{h}, {duration}s) + {poster_path}")


def main() -> None:
    render_video("cartozo-demo.webm", 10.0, frame_main_demo)
    render_video("gallery-titles.webm", 7.0, frame_titles)
    render_video("gallery-disapproval.webm", 7.0, frame_disapproval)
    # Hero uses main demo poster
    poster = OUT / "cartozo-demo-poster.jpg"
    frame_main_demo(5.5, 10.0).save(poster, quality=90, optimize=True)
    print(f"Wrote {poster}")


if __name__ == "__main__":
    main()
