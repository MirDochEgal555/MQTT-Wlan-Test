"""
Image Generator for E-Ink Desk Display (Tischkarte).
Renders high-contrast, crisp e-paper layouts using Pillow.
Supports B/W, 3-color accents, and 1-bit Floyd-Steinberg dithering.
"""

import argparse
import os
from datetime import datetime
from typing import Optional, Tuple
from PIL import Image, ImageDraw, ImageFont


def _load_font(size: int, bold: bool = False, serif: bool = False) -> ImageFont.ImageFont:
    """Attempts to load a high quality system font with graceful fallbacks."""
    font_paths = []
    if serif:
        font_paths.extend([
            "/System/Library/Fonts/Supplemental/Georgia Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Georgia.ttf",
            "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        ])
    else:
        font_paths.extend([
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ])

    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue

    # Fallback to default
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def generate_menu_card(
    title: str = "Kürbissuppe",
    subtitle: str = "mit gerösteten Kürbiskernen & Steirischem Kernöl",
    price: str = "6,90 €",
    badge: str = "HEUTE EMPFOHLEN",
    table_name: str = "TISCH 12",
    version: int = 1,
    width: int = 800,
    height: int = 480,
    output_path: Optional[str] = None,
    dither_eink: bool = False,
    accent_color: Tuple[int, int, int] = (180, 20, 20),  # Red accent for 3-color EPD
) -> Image.Image:
    """
    Renders an e-ink desk card with crisp typography, elegant borders, and clean layout.
    """
    # Background (off-white for realistic e-paper look: 250, 250, 248)
    bg_color = (252, 252, 250)
    fg_black = (20, 20, 22)
    fg_gray = (100, 100, 105)

    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # 1. Outer Border & Frame
    margin = 16
    draw.rectangle([margin, margin, width - margin, height - margin], outline=fg_black, width=3)
    inner_margin = margin + 6
    draw.rectangle([inner_margin, inner_margin, width - inner_margin, height - inner_margin], outline=fg_gray, width=1)

    # Decorative corner accents
    corner_size = 14
    for cx, cy, dx, dy in [
        (margin + 2, margin + 2, 1, 1),
        (width - margin - 2, margin + 2, -1, 1),
        (margin + 2, height - margin - 2, 1, -1),
        (width - margin - 2, height - margin - 2, -1, -1),
    ]:
        draw.line([(cx, cy), (cx + dx * corner_size, cy)], fill=fg_black, width=2)
        draw.line([(cx, cy), (cx, cy + dy * corner_size)], fill=fg_black, width=2)

    # 2. Header: Table badge and Lab label
    font_badge = _load_font(18, bold=True, serif=False)
    font_small = _load_font(14, bold=False, serif=False)

    badge_text = badge.upper()
    pill_w = 260
    pill_h = 34
    pill_x0 = (width - pill_w) // 2
    pill_y0 = margin + 18

    # Rounded pill for badge
    draw.rounded_rectangle([pill_x0, pill_y0, pill_x0 + pill_w, pill_y0 + pill_h], radius=6, fill=fg_black)
    b_bbox = draw.textbbox((0, 0), badge_text, font=font_badge)
    bw = b_bbox[2] - b_bbox[0]
    bh = b_bbox[3] - b_bbox[1]
    draw.text((pill_x0 + (pill_w - bw) // 2, pill_y0 + (pill_h - bh) // 2 - 2), badge_text, fill=bg_color, font=font_badge)

    # Table identifier on top left
    draw.text((inner_margin + 16, margin + 22), table_name, fill=fg_black, font=font_small)

    # Date / Time on top right
    now_str = datetime.now().strftime("%H:%M")
    time_text = f"Stand {now_str} Uhr"
    t_bbox = draw.textbbox((0, 0), time_text, font=font_small)
    draw.text((width - inner_margin - 16 - (t_bbox[2] - t_bbox[0]), margin + 22), time_text, fill=fg_gray, font=font_small)

    # Header divider line
    div_y = pill_y0 + pill_h + 16
    draw.line([(inner_margin + 20, div_y), (width - inner_margin - 20, div_y)], fill=fg_gray, width=1)

    # 3. Main Dish Title
    font_title = _load_font(44, bold=True, serif=True)
    title_bbox = draw.textbbox((0, 0), title, font=font_title)
    tw = title_bbox[2] - title_bbox[0]
    title_y = div_y + 35

    # If title is too wide for one line, scale down or wrap
    if tw > width - 100:
        font_title = _load_font(32, bold=True, serif=True)
        title_bbox = draw.textbbox((0, 0), title, font=font_title)
        tw = title_bbox[2] - title_bbox[0]

    draw.text(((width - tw) // 2, title_y), title, fill=fg_black, font=font_title)

    # 4. Subtitle / Description
    font_sub = _load_font(20, bold=False, serif=True)
    sub_bbox = draw.textbbox((0, 0), subtitle, font=font_sub)
    sw = sub_bbox[2] - sub_bbox[0]
    sub_y = title_y + (title_bbox[3] - title_bbox[1]) + 20

    # Wrap subtitle if needed
    if sw > width - 120 and " " in subtitle:
        words = subtitle.split(" ")
        mid = len(words) // 2
        line1 = " ".join(words[:mid])
        line2 = " ".join(words[mid:])
        l1_bb = draw.textbbox((0, 0), line1, font=font_sub)
        l2_bb = draw.textbbox((0, 0), line2, font=font_sub)
        draw.text(((width - (l1_bb[2] - l1_bb[0])) // 2, sub_y), line1, fill=fg_gray, font=font_sub)
        draw.text(((width - (l2_bb[2] - l2_bb[0])) // 2, sub_y + 26), line2, fill=fg_gray, font=font_sub)
        price_y = sub_y + 65
    else:
        draw.text(((width - sw) // 2, sub_y), subtitle, fill=fg_gray, font=font_sub)
        price_y = sub_y + 45

    # 5. Price Tag (prominent, high contrast)
    font_price = _load_font(52, bold=True, serif=False)
    price_bbox = draw.textbbox((0, 0), price, font=font_price)
    pw = price_bbox[2] - price_bbox[0]
    draw.text(((width - pw) // 2, price_y), price, fill=fg_black, font=font_price)

    # 6. Footer metadata & E-Ink status bar
    footer_div_y = height - margin - 46
    draw.line([(inner_margin + 20, footer_div_y), (width - inner_margin - 20, footer_div_y)], fill=fg_gray, width=1)

    font_footer = _load_font(13, bold=False, serif=False)
    footer_text = f"E-Ink Tischkarte · Version {version} · Akku: 98% · YUPSALE Kommunikationslabor"
    draw.text((inner_margin + 16, footer_div_y + 12), footer_text, fill=fg_gray, font=font_footer)

    # E-paper indicator logo on right
    epd_tag = "EPD 800x480"
    epd_bb = draw.textbbox((0, 0), epd_tag, font=font_footer)
    draw.text((width - inner_margin - 16 - (epd_bb[2] - epd_bb[0]), footer_div_y + 12), epd_tag, fill=fg_gray, font=font_footer)

    # Optional 1-bit Floyd-Steinberg dithering
    if dither_eink:
        # Convert to 1-bit monochrome for true e-ink bitmap representation
        img = img.convert("1", dither=Image.Dither.FLOYDSTEINBERG).convert("RGB")

    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        img.save(output_path, "PNG", optimize=True)

    return img


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="E-Ink Menu Card Image Generator")
    parser.add_argument("--title", default="Kürbissuppe", help="Dish name")
    parser.add_argument("--subtitle", default="mit gerösteten Kürbiskernen & Steirischem Kernöl", help="Description")
    parser.add_argument("--price", default="6,90 €", help="Price string")
    parser.add_argument("--badge", default="HEUTE EMPFOHLEN", help="Header badge")
    parser.add_argument("--version", type=int, default=1, help="Image version number")
    parser.add_argument("--output", default="images/menu.png", help="Output PNG path")
    parser.add_argument("--dither", action="store_true", help="Apply 1-bit EPD dithering")
    args = parser.parse_args()

    out_file = generate_menu_card(
        title=args.title,
        subtitle=args.subtitle,
        price=args.price,
        badge=args.badge,
        version=args.version,
        output_path=args.output,
        dither_eink=args.dither,
    )
    print(f"Generated menu card image at: {args.output}")
