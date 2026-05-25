# modules/profiler/infocard.py
# Renders person info cards by drawing text onto designation-specific templates.

import os
import cv2
from PIL import Image, ImageDraw, ImageFont

from modules.profiler.heuristics import bri_rgb

CARD_DIR        = os.path.join('assets', 'gui', 'infocards')
ENROLLED_DIR    = os.path.join('database', 'enrolled')
DESC_DIR        = os.path.join('assets', 'descriptions')

CARD_W, CARD_H  = 650, 200

THUMB_X, THUMB_Y        = 9, 9
THUMB_W, THUMB_H        = 75, 75

NAME_X, NAME_Y          = 90, 14
CRIME_X, CRIME_Y        = 400, 14

BAR_Y                   = 47
DESC_X, DESC_Y          = 90, 57
DESC_MAX_W              = 540

# Identity rows (tighter than original to make room for heuristics)
BOT_ROW1_Y              = 100
BOT_ROW2_Y              = 120
BOT_LEFT_X              = 90
BOT_RIGHT_X             = 420

# Heuristics rows
HEUR_SEP_Y              = 138   # thin separator line
HEUR_BAR_Y              = 145   # BRI bar row
HEUR_TAG_Y              = 167   # gait + behavioral tag row

HIGHLIGHT_TEXT_COLOR = {
    'irrelevant':   (0,   0,   0),
    'root':         (0,   0,   0),
    'admin':        (255, 255, 255),
    'threat':       (0,   0,   0),
    'victim':       (0,   0,   0),
    'perpetrator':  (0,   0,   0),
}

TEXT_WHITE = (255, 255, 255)


def _load_font(size=16):
    for name in ["cour.ttf", "DejaVuSansMono.ttf", "LiberationMono-Regular.ttf"]:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _load_font_bold(size=16):
    for name in ["courbd.ttf", "DejaVuSansMono-Bold.ttf", "LiberationMono-Bold.ttf"]:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return _load_font(size)


def _load_card_template(designation):
    path = os.path.join(CARD_DIR, f"{designation}.png")
    if not os.path.exists(path):
        path = os.path.join(CARD_DIR, "irrelevant.png")
    return Image.open(path).convert("RGBA")


def _load_enrolled_image(ssn):
    """Load enrolled face image, square-cropped and resized to thumbnail size."""
    path = os.path.join(ENROLLED_DIR, f"{ssn}.jpg")
    if not os.path.exists(path):
        return None
    img = cv2.imread(path)
    if img is None:
        return None
    h, w = img.shape[:2]
    size = min(h, w)
    x1 = (w - size) // 2
    y1 = (h - size) // 2
    img = img[y1:y1+size, x1:x1+size]
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return Image.fromarray(img).resize((THUMB_W, THUMB_H), Image.LANCZOS)


def _truncate_text(draw, text, font, max_width):
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "...", font=font) > max_width:
        text = text[:-1]
    return text + "..."


def _draw_bri_bar(draw, bri: int, y: int, font):
    """Draw the BRI label, progress bar, and risk score."""
    r, g, b     = bri_rgb(bri)
    risk_color  = (r, g, b, 255)
    risk_dim    = (r, g, b, 190)
    bar_bg      = (20, 20, 20, 180)

    label_x = BOT_LEFT_X
    bar_x1  = label_x + 36
    bar_x2  = bar_x1 + 155
    bar_y1  = y + 3
    bar_y2  = bar_y1 + 9
    fill_x2 = bar_x1 + int(155 * bri / 100)

    draw.text((label_x, y), "BRI", font=font, fill=(160, 160, 160, 255))
    draw.rectangle([(bar_x1, bar_y1), (bar_x2, bar_y2)], fill=bar_bg)
    if fill_x2 > bar_x1:
        draw.rectangle([(bar_x1, bar_y1), (fill_x2, bar_y2)], fill=risk_dim)
    draw.rectangle([(bar_x1, bar_y1), (bar_x2, bar_y2)],
                   outline=(50, 50, 50, 200), width=1)

    score_str = f"{bri:02d}"
    draw.text((bar_x2 + 7, y), score_str, font=font, fill=risk_color)


def render_card_with_face_data(
    person,
    face_age=None,
    face_sex=None,
    crime_chance=None,
    is_tracked=False,
    heuristics=None,
    prev_designation=None,
):
    """
    Render an infocard for a person.
    person:     (id, ssn, name, designation, notes, last_seen_ts, last_seen_feed)
    heuristics: dict from modules.profiler.heuristics.generate(), or None
    Returns a PIL Image (RGBA, 650x200).
    """
    _, ssn, name, designation, notes, last_seen_ts, last_seen_feed = person

    font_sm    = _load_font(14)
    font_bold  = _load_font_bold(18)
    font_track = _load_font_bold(13)
    font_heur  = _load_font(11)

    card = _load_card_template(designation)
    draw = ImageDraw.Draw(card)

    # Enrolled face thumbnail
    face_img = _load_enrolled_image(ssn)
    if face_img:
        card.paste(face_img, (THUMB_X, THUMB_Y))

    # Name
    draw.text((NAME_X, NAME_Y), name or "UNKNOWN", font=font_bold, fill=TEXT_WHITE)

    # Crime % (victim/perpetrator only)
    if designation in ('victim', 'perpetrator') and crime_chance is not None:
        draw.text((CRIME_X, CRIME_Y), f"Crime: {crime_chance}%", font=font_sm, fill=TEXT_WHITE)

    # TRACKING badge — amber pill top-right when actively tracked
    if is_tracked:
        badge_text = "LIVE TRACKING"
        AMBER = (255, 165, 0)
        bw = int(draw.textlength(badge_text, font=font_track)) + 10
        bh = 18
        bx = CARD_W - bw - 6
        by = 6
        draw.rectangle([(bx - 2, by), (bx + bw, by + bh)], fill=(30, 20, 0, 220))
        draw.rectangle([(bx - 2, by), (bx + bw, by + bh)], outline=AMBER, width=1)
        draw.text((bx + 3, by + 2), badge_text, font=font_track, fill=AMBER)

    # PREV badge — dim grey pill showing prior designation after neutralization
    if prev_designation:
        prev_text = f"PREV: {prev_designation.upper()}"
        GREY = (120, 120, 120)
        pw = int(draw.textlength(prev_text, font=font_track)) + 10
        ph = 18
        px = CARD_W - pw - 6
        py = 6 + (26 if is_tracked else 0)
        draw.rectangle([(px - 2, py), (px + pw, py + ph)], fill=(20, 20, 20, 180))
        draw.rectangle([(px - 2, py), (px + pw, py + ph)], outline=GREY, width=1)
        draw.text((px + 3, py + 2), prev_text, font=font_track, fill=GREY)

    # Description bar
    text_color = HIGHLIGHT_TEXT_COLOR.get(designation, (0, 0, 0))
    truncated = _truncate_text(draw, notes or "", font_sm, DESC_MAX_W)
    draw.text((DESC_X, DESC_Y), truncated, font=font_sm, fill=text_color)

    # Identity rows
    sex_str = face_sex if face_sex else "?"
    age_str = str(int(face_age)) if face_age is not None else "?"

    draw.text((BOT_LEFT_X,  BOT_ROW1_Y), f"SSN: {ssn}",                        font=font_sm, fill=TEXT_WHITE)
    draw.text((BOT_RIGHT_X, BOT_ROW1_Y), f"Sex: {sex_str}",                     font=font_sm, fill=TEXT_WHITE)
    draw.text((BOT_LEFT_X,  BOT_ROW2_Y), f"Designation: {designation.upper()}", font=font_sm, fill=TEXT_WHITE)
    draw.text((BOT_RIGHT_X, BOT_ROW2_Y), f"Age: {age_str}",                     font=font_sm, fill=TEXT_WHITE)

    # ── Heuristics section ────────────────────────────────────────────────────
    if heuristics:
        bri     = heuristics['bri']
        micro   = heuristics['micro']
        gait    = heuristics['gait']
        network = heuristics['network']
        tag     = heuristics.get('tag')

        # Separator
        draw.line(
            [(BOT_LEFT_X, HEUR_SEP_Y), (CARD_W - BOT_LEFT_X, HEUR_SEP_Y)],
            fill=(60, 60, 60, 140),
            width=1,
        )

        # BRI bar row
        _draw_bri_bar(draw, bri, HEUR_BAR_Y, font_heur)
        draw.text((310, HEUR_BAR_Y), f"MICRO: {micro:02d}%", font=font_heur,
                  fill=(140, 140, 140, 255))

        # Gait + behavioral tag row
        gait_clr = {
            'LOW':      (60,  200, 80,  255),
            'MODERATE': (220, 165, 30,  255),
            'HIGH':     (220, 55,  55,  255),
        }.get(gait, (180, 180, 180, 255))
        draw.text((BOT_LEFT_X, HEUR_TAG_Y), f"GAIT: {gait}", font=font_heur, fill=gait_clr)

        if tag:
            tag_x   = BOT_LEFT_X + 108
            max_w   = CARD_W - tag_x - 10
            tag_str = _truncate_text(draw, tag, font_heur, max_w)
            draw.text((tag_x, HEUR_TAG_Y), tag_str, font=font_heur,
                      fill=(130, 130, 130, 255))

    return card


def render_alert_card(label: str, names: list, rule_id: int, alpha: float = 1.0):
    """
    Render a red-tinted alert overlay card (CARD_W × 120 px).
    label     — short description string
    names     — list of subject name strings
    rule_id   — rule that fired
    alpha     — 0.0–1.0 opacity applied to the card's alpha channel
    Returns a PIL Image (RGBA).
    """
    W, H = CARD_W, 120
    card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)

    bg_alpha = int(210 * alpha)
    draw.rectangle([(0, 0), (W - 1, H - 1)], fill=(30, 0, 0, bg_alpha))

    border_alpha = int(255 * alpha)
    draw.rectangle([(0, 0), (W - 1, H - 1)],
                   outline=(180, 20, 20, border_alpha), width=2)
    draw.rectangle([(0, 0), (W - 1, 4)],
                   fill=(200, 30, 30, border_alpha))

    font_hdr  = _load_font_bold(14)
    font_body = _load_font(13)
    font_sm   = _load_font(11)

    text_alpha = int(255 * alpha)
    red_bright = (255, 80,  80,  text_alpha)
    white      = (220, 220, 220, text_alpha)
    grey       = (140, 140, 140, text_alpha)

    draw.text((12, 10), f"⚠  ALERT  —  RULE {rule_id}", font=font_hdr, fill=red_bright)
    draw.line([(12, 32), (W - 12, 32)], fill=(100, 20, 20, text_alpha), width=1)

    truncated = label if len(label) <= 70 else label[:67] + "..."
    draw.text((12, 38), truncated, font=font_body, fill=white)

    if names:
        name_str = "  ".join(n.upper() for n in names[:4])
        if len(names) > 4:
            name_str += f"  +{len(names) - 4} more"
        draw.text((12, 62), name_str, font=font_sm, fill=grey)

    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S")
    draw.text((12, 94), ts, font=font_sm, fill=(100, 60, 60, text_alpha))

    return card


def overlay_alert_card_on_frame(frame, alert_card_pil, slot: int = 0):
    """
    Composite an alert card PIL image onto a BGR numpy frame.
    slot — vertical stacking index (0 = bottom, 1 = above that, etc.)
    Modifies frame in-place and returns it.
    """
    import numpy as np
    card_rgba = np.array(alert_card_pil.convert("RGBA"), dtype=np.float32)
    ch, cw    = card_rgba.shape[:2]
    fh, fw    = frame.shape[:2]

    margin = 10
    x1 = margin
    y1 = fh - margin - ch - slot * (ch + 6)
    x2 = x1 + cw
    y2 = y1 + ch

    if y1 < 0 or x2 > fw:
        return frame

    alpha    = card_rgba[:, :, 3:4] / 255.0
    card_bgr = card_rgba[:, :, :3][:, :, ::-1]

    roi     = frame[y1:y2, x1:x2].astype(np.float32)
    blended = alpha * card_bgr + (1.0 - alpha) * roi
    frame[y1:y2, x1:x2] = blended.astype(np.uint8)

    return frame


def pil_to_qpixmap(pil_img):
    from PyQt5.QtGui import QImage, QPixmap
    rgba = pil_img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(data, rgba.width, rgba.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg)