#!/usr/bin/env python3
"""Cinematic Cartozo homepage films — Higgsfield-style walnut UI motion."""
from __future__ import annotations

import math
import random
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "static" / "home-media"
FPS = 30
W_CINEMA, H_CINEMA = 1280, 720

WALNUT = (16, 9, 4)
BARK = (56, 36, 22)
CORK = (64, 55, 46)
CREAM = (255, 237, 215)
DRIFT = (108, 95, 81)
EMBER = (220, 80, 0)
GREEN = (74, 222, 128)
RED = (239, 68, 68)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _lerp_color(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(_lerp(c1[i], c2[i], t)) for i in range(3))  # type: ignore


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _dashed_hline(draw: ImageDraw.ImageDraw, y: int, x0: int, x1: int, color: tuple, dash: int = 8) -> None:
    x = x0
    while x < x1:
        draw.line([(x, y), (min(x + dash, x1), y)], fill=color, width=1)
        x += dash * 2


def _vignette(img: Image.Image, strength: float = 0.72) -> Image.Image:
    w, h = img.size
    overlay = Image.new("RGB", (w, h), (0, 0, 0))
    od = ImageDraw.Draw(overlay)
    steps = 28
    for i in range(steps):
        t = i / steps
        c = int(255 * strength * t * t)
        margin_x = int((w * 0.12) * t)
        margin_y = int((h * 0.14) * t)
        od.rectangle([margin_x, margin_y, w - margin_x, h - margin_y], outline=(c, c, c))
    od.rectangle([0, 0, w, int(h * 0.22)], fill=(0, 0, 0))
    od.rectangle([0, int(h * 0.78), w, h], fill=(0, 0, 0))
    return Image.blend(img, overlay, alpha=0.55)


def _ambient_orbs(draw: ImageDraw.ImageDraw, w: int, h: int, t: float) -> None:
    specs = [
        (0.72, 0.32, 220, EMBER, 0.14),
        (0.18, 0.68, 180, BARK, 0.2),
        (0.5, 0.55, 140, CORK, 0.08),
    ]
    for cx, cy, rad, col, alpha in specs:
        x = int(w * cx + math.sin(t * 0.9 + cx * 6) * 28)
        y = int(h * cy + math.cos(t * 0.7 + cy * 5) * 22)
        for ring in range(4):
            r = rad - ring * 28
            if r < 20:
                continue
            c = _lerp_color(WALNUT, col, alpha * (1 - ring * 0.2))
            draw.ellipse([x - r, y - r, x + r, y + r], fill=c)


def _particles(draw: ImageDraw.ImageDraw, w: int, h: int, t: float, density: int = 40) -> None:
    rng = random.Random(int(t * 1000) % 99991)
    for _ in range(density):
        px = rng.randint(0, w)
        py = rng.randint(0, h)
        life = (math.sin(t * 3 + px * 0.01) + 1) * 0.5
        if life < 0.35:
            continue
        r = rng.uniform(0.6, 2.2)
        col = EMBER if rng.random() > 0.65 else CREAM
        a = int(180 * life * rng.uniform(0.2, 0.9))
        draw.ellipse([px - r, py - r, px + r, py + r], fill=_lerp_color(WALNUT, col, a / 255))


def _cinema_overlay(
    draw: ImageDraw.ImageDraw,
    w: int,
    h: int,
    *,
    chip: str,
    title: str,
    subtitle: str,
    opacity: float = 1.0,
) -> None:
    if opacity <= 0:
        return
    grad_h = int(h * 0.42)
    for i in range(grad_h):
        t = i / grad_h
        c = int(16 * (1 - t) + 0 * t)
        draw.line([(0, h - grad_h + i), (w, h - grad_h + i)], fill=(c, c // 2, c // 4))

    f_chip = _font(11, bold=True)
    f_title = _font(42, bold=True)
    f_sub = _font(18)

    y = h - int(h * 0.28)
    draw.text((48, y - 56), chip.upper(), fill=EMBER, font=f_chip)
    draw.text((48, y - 28), title.upper(), fill=CREAM, font=f_title)
    draw.text((48, y + 28), subtitle, fill=DRIFT, font=f_sub)

    # Higgsfield-style corner tag
    tag = "CARTOZO STUDIO"
    draw.text((w - 48 - draw.textbbox((0, 0), tag, font=f_chip)[2], 48), tag, fill=DRIFT, font=f_chip)


def _draw_panel(
    base: Image.Image,
    box: tuple[int, int, int, int],
    scale: float,
    angle: float,
) -> Image.Image:
    """Render UI panel to separate layer and paste with transform."""
    x0, y0, x1, y1 = box
    pw, ph = x1 - x0, y1 - y0
    panel = Image.new("RGB", (pw, ph), WALNUT)
    pd = ImageDraw.Draw(panel)
    pd.rectangle([0, 0, pw - 1, ph - 1], fill=(42, 26, 14), outline=CORK, width=2)
    bar = 40
    pd.rectangle([0, 0, pw, bar], fill=(20, 11, 6))
    _dashed_hline(pd, bar, 0, pw, CORK)
    pd.text((14, 12), "PRODUCT_FEED.CSV", fill=DRIFT, font=_font(12))
    pd.text((pw - 72, 12), "LIVE", fill=EMBER, font=_font(11, bold=True))
    return panel


def _draw_feed_table(
    draw: ImageDraw.ImageDraw,
    inner: tuple[int, int, int, int],
    headers: list[str],
    rows: list[tuple[list[str], list[tuple], float]],
) -> None:
    x0, y0, x1, y1 = inner
    col_n = len(headers)
    col_w = (x1 - x0) // col_n
    y = y0
    fh = _font(11, bold=True)
    for i, h in enumerate(headers):
        draw.text((x0 + i * col_w + 6, y), h.upper(), fill=DRIFT, font=fh)
    _dashed_hline(draw, y + 18, x0, x1, CORK)
    y += 28
    fr = _font(13)
    for cells, colors, hl in rows:
        if hl > 0:
            draw.rectangle([x0, y - 4, x1, y + 22], fill=(int(56 + 24 * hl), int(36 + 14 * hl), int(22 + 10 * hl)))
        for ci, cell in enumerate(cells):
            c = colors[ci] if colors else CREAM
            draw.text((x0 + ci * col_w + 6, y), cell[:28], fill=c, font=fr)
        _dashed_hline(draw, y + 22, x0, x1, CORK)
        y += 28


def _scanline(draw: ImageDraw.ImageDraw, inner: tuple, p: float) -> None:
    x0, y0, x1, y1 = inner
    sy = int(y0 + (y1 - y0) * p)
    for off in range(-3, 4):
        draw.line([(x0, sy + off), (x1, sy + off)], fill=_lerp_color(WALNUT, EMBER, max(0, 0.5 - abs(off) * 0.15)), width=1)
    draw.line([(x0, sy), (x1, sy)], fill=EMBER, width=3)


def _metric_bar(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    label: str,
    val: float,
    t_anim: float,
    pct_label: str | None = None,
) -> None:
    draw.text((x, y), label.upper(), fill=DRIFT, font=_font(11, bold=True))
    bw, bh = w, 12
    draw.rectangle([x, y + 18, x + bw, y + 18 + bh], outline=CORK, width=1)
    fill_w = max(0, int(bw * _ease(t_anim) * max(0.0, min(1.0, val))))
    if fill_w > 0:
        draw.rectangle([x + 1, y + 19, x + fill_w, y + 17 + bh], fill=EMBER if val > 0.7 else DRIFT)
    shown = pct_label if pct_label is not None else f"{int(val * 100)}%"
    draw.text((x + bw + 12, y + 16), shown, fill=CREAM, font=_font(14, bold=True))


def frame_catalog_cinema(t: float, duration: float) -> Image.Image:
    w, h = W_CINEMA, H_CINEMA
    img = Image.new("RGB", (w, h), WALNUT)
    draw = ImageDraw.Draw(img)
    phase = t / duration
    _ambient_orbs(draw, w, h, t)

    zoom = 1.0 + 0.06 * math.sin(phase * math.pi)
    pw, ph = int(w * 0.62 * zoom), int(h * 0.58 * zoom)
    px, py = (w - pw) // 2, int(h * 0.12 + math.sin(t * 0.5) * 8)
    box = (px, py, px + pw, py + ph)
    inner_margin = 16
    inner = (box[0] + inner_margin, box[1] + 48, box[2] - inner_margin, box[3] - inner_margin)

    draw.rectangle(box, fill=(38, 24, 14), outline=CORK, width=2)
    draw.rectangle([box[0], box[1], box[2], box[1] + 40], fill=(18, 10, 5))
    draw.text((box[0] + 18, box[1] + 12), "PRODUCT_FEED.CSV  ·  12,418 SKUS", fill=CREAM, font=_font(13, bold=True))
    draw.text((box[2] - 120, box[1] + 12), "AI ENGINE", fill=EMBER, font=_font(12, bold=True))

    before = [
        ("12345", "Generic Chair", "42"),
        ("8821", "Blue Shirt", "38"),
        ("3310", "Shoes", "51"),
        ("9022", "Lamp", "44"),
        ("7712", "Watch", "47"),
    ]
    after = [
        ("12345", "IKEA Black Dining Chair Modern Kitchen", "91"),
        ("8821", "Mens Oxford Shirt Blue Slim Fit", "86"),
        ("3310", "Nike Air Max 90 White Running", "88"),
        ("9022", "LED Desk Lamp Adjustable White", "84"),
        ("7712", "Seiko 5 Sports Automatic Steel", "89"),
    ]

    morph0, morph1 = 0.22, 0.58
    scan0, scan1 = 0.12, 0.28
    if scan0 <= phase <= scan1:
        _scanline(draw, inner, (phase - scan0) / (scan1 - scan0))

    rows_data = []
    for i, (b, a) in enumerate(zip(before, after)):
        rp = _ease(clamp((phase - morph0 - i * 0.04) / (morph1 - morph0)))
        title = b[1] if rp < 0.48 else a[1]
        if 0.42 < rp < 0.52:
            title = a[1][: max(2, int(len(a[1]) * ((rp - 0.42) / 0.1)))]
        score = int(_lerp(int(b[2]), int(a[2]), _ease(max(0, (rp - 0.25) / 0.75))))
        hl = 0.5 if 0.3 < rp < 0.7 else 0
        colors = [DRIFT, CREAM if rp > 0.45 else DRIFT, EMBER if score > 80 else DRIFT]
        rows_data.append(([b[0], title, str(score)], colors, hl))

    _draw_feed_table(draw, inner, ["id", "title", "score"], rows_data)

    if phase > 0.08 and phase < morph1:
        _particles(draw, w, h, t, 55)

    overlay_op = clamp((phase - 0.02) / 0.12) if phase < 0.15 else (1.0 if phase < 0.72 else clamp(1 - (phase - 0.72) / 0.15))
    chip = "FLAGSHIP WORKFLOW"
    title = "Full catalog rewrite"
    sub = "12,418 SKUs · titles rebuilt · Merchant spec aligned"
    if phase > morph1:
        chip = "EXPORT READY"
        title = "Merchant ready"
        sub = "Quality avg 42 → 87 · CSV validated for Google Shopping"
    _cinema_overlay(draw, w, h, chip=chip, title=title, subtitle=sub, opacity=overlay_op)

    img = _vignette(img)
    if phase > 0.15 and phase < 0.65:
        img = img.filter(ImageFilter.GaussianBlur(radius=0.3))
    return img


def frame_titles_cinema(t: float, duration: float) -> Image.Image:
    w, h = W_CINEMA, H_CINEMA
    img = Image.new("RGB", (w, h), WALNUT)
    draw = ImageDraw.Draw(img)
    phase = t / duration
    _ambient_orbs(draw, w, h, t + 1)

    box = (int(w * 0.1), int(h * 0.14), int(w * 0.9), int(h * 0.72))
    inner = (box[0] + 20, box[1] + 50, box[2] - 20, box[3] - 20)
    draw.rectangle(box, fill=(38, 24, 14), outline=CORK, width=2)
    draw.text((box[0] + 20, box[1] + 16), "INTENT MATCH ENGINE", fill=CREAM, font=_font(16, bold=True))

    pairs = [
        ("SKU-01", "Blue Shirt", "Mens Cotton Oxford Shirt Blue Slim Fit", 0.47),
        ("SKU-02", "Shoes", "Nike Air Max 90 White Mens Running", 0.58),
        ("SKU-03", "Chair", "IKEA Black Dining Chair Modern Kitchen", 0.61),
        ("SKU-04", "Jacket", "Patagonia Nano Puff Hoody Mens Black", 0.54),
    ]
    rows = []
    for i, (sku, before, after, match) in enumerate(pairs):
        p = _ease(clamp((phase - 0.1 - i * 0.08) / 0.35))
        title = before if p < 0.5 else after
        if 0.45 < p < 0.55:
            title = after[: max(1, int(len(after) * ((p - 0.45) / 0.1)))]
        m = int(match * 100 * _ease(max(0, (p - 0.35) / 0.65)))
        rows.append(([sku, title, f"+{m}% intent"], [DRIFT, CREAM if p > 0.5 else DRIFT, EMBER if m > 35 else DRIFT], 0.45 if 0.25 < p < 0.65 else 0))
    _draw_feed_table(draw, inner, ["sku", "title", "lift"], rows)

    if 0.05 < phase < 0.5:
        _scanline(draw, inner, min(1, phase * 1.6))
        _particles(draw, w, h, t, 35)

    _cinema_overlay(
        draw, w, h,
        chip="TITLE STUDIO",
        title="Intent-aligned titles",
        subtitle="Search queries mapped to every SKU — CTR lift without guessing",
        opacity=clamp(phase / 0.1) if phase < 0.12 else 0.92,
    )
    return _vignette(img)


def frame_disapproval_cinema(t: float, duration: float) -> Image.Image:
    w, h = W_CINEMA, H_CINEMA
    img = Image.new("RGB", (w, h), WALNUT)
    draw = ImageDraw.Draw(img)
    phase = t / duration
    _ambient_orbs(draw, w, h, t + 2)

    box = (int(w * 0.1), int(h * 0.14), int(w * 0.9), int(h * 0.72))
    inner = (box[0] + 20, box[1] + 50, box[2] - 20, box[3] - 20)
    draw.rectangle(box, fill=(38, 24, 14), outline=CORK, width=2)
    draw.text((box[0] + 20, box[1] + 16), "MERCHANT CENTER · DISAPPROVAL RECOVERY", fill=CREAM, font=_font(15, bold=True))

    issues = [
        ("8821", "Missing GTIN", "1234567890123 added"),
        ("8822", "Invalid brand", "Brand normalized → IKEA"),
        ("8823", "Image too small", "1200×1200 image linked"),
        ("8824", "Policy: identifier", "GTIN + MPN filled"),
    ]
    rows = []
    for i, (pid, issue, fix) in enumerate(issues):
        p = _ease(clamp((phase - 0.08 - i * 0.1) / 0.28))
        mid = issue if p < 0.55 else fix
        stat = "DISAPPROVED" if p < 0.72 else "APPROVED"
        sc = RED if stat == "DISAPPROVED" else GREEN
        rows.append(([pid, mid, stat], [DRIFT, CREAM if p > 0.5 else DRIFT, sc], 0.4 if 0.15 < p < 0.7 else 0))
    _draw_feed_table(draw, inner, ["id", "fix applied", "status"], rows)

    if phase > 0.55:
        _particles(draw, w, h, t, 25)

    _cinema_overlay(
        draw, w, h,
        chip="GMC RECOVERY",
        title="Disapprovals fixed",
        subtitle="Missing GTIN, brand gaps, image policy — resolved in batch",
        opacity=0.9,
    )
    return _vignette(img)


def frame_performance_cinema(t: float, duration: float) -> Image.Image:
    w, h = W_CINEMA, H_CINEMA
    img = Image.new("RGB", (w, h), WALNUT)
    draw = ImageDraw.Draw(img)
    phase = t / duration
    _ambient_orbs(draw, w, h, t + 3)

    draw.text((48, 48), "SHOPPING PERFORMANCE · AFTER CARTOZO", fill=DRIFT, font=_font(12, bold=True))
    draw.text((48, 78), "LIFT REPORT", fill=CREAM, font=_font(36, bold=True))

    metrics = [
        ("Feed quality score", 0.42, 0.87),
        ("Click-through rate", 0.38, 0.61),
        ("Impression share", 0.45, 0.72),
        ("Disapproval rate", 0.22, 0.04, True),
    ]
    y = 160
    for item in metrics:
        label, start, end = item[0], item[1], item[2]
        invert = len(item) > 3 and item[3]
        anim = _ease(clamp((phase - 0.1) / 0.55))
        val = _lerp(start, end, anim)
        if invert:
            bar_val = clamp(1 - val / max(start, 0.01), 0, 1)
            pct_label = f"{int(val * 100)}%"
        else:
            bar_val = val
            pct_label = f"{int(val * 100)}%"
        _metric_bar(draw, 48, y, 420, label, bar_val, anim, pct_label)
        y += 56

    if phase > 0.2:
        _particles(draw, w, h, t, 30)

    _cinema_overlay(
        draw, w, h,
        chip="PERFORMANCE",
        title="Real shopping lift",
        subtitle="Better titles + clean feeds → more impressions, fewer disapprovals",
        opacity=clamp(phase / 0.08) if phase < 0.1 else 0.88,
    )
    return _vignette(img)


def render_video(name: str, duration: float, frame_fn) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / name
    total = int(duration * FPS)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for i in range(total):
            t = i / FPS
            frame_fn(t, duration).save(tmp_path / f"frame_{i:05d}.png")
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-framerate", str(FPS),
                "-i", str(tmp_path / "frame_%05d.png"),
                "-c:v", "libvpx-vp9",
                "-pix_fmt", "yuv420p",
                "-b:v", "4500k",
                "-crf", "30",
                str(out_path),
            ],
            check=True,
            capture_output=True,
        )
    poster = frame_fn(duration * 0.45, duration)
    poster_path = OUT / name.replace(".webm", "-poster.jpg")
    poster.save(poster_path, quality=92, optimize=True)
    print(f"Wrote {out_path} + {poster_path}")


def main() -> None:
    render_video("cartozo-demo.webm", 12.0, frame_catalog_cinema)
    render_video("gallery-titles.webm", 9.0, frame_titles_cinema)
    render_video("gallery-disapproval.webm", 9.0, frame_disapproval_cinema)
    render_video("cinema-performance.webm", 8.0, frame_performance_cinema)
    frame_catalog_cinema(6.0, 12.0).save(OUT / "cartozo-demo-poster.jpg", quality=92, optimize=True)


if __name__ == "__main__":
    main()
