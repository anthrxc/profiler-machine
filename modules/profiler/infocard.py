# modules/profiler/infocard.py
# Renders person info cards by drawing text onto designation-specific templates.

import os
import cv2
from PIL import Image, ImageDraw, ImageFont

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

BOT_ROW1_Y              = 105
BOT_ROW2_Y              = 135
BOT_LEFT_X              = 90
BOT_RIGHT_X             = 420

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
    # Square crop from center
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


def render_card_with_face_data(person, face_age=None, face_sex=None, crime_chance=None):
    """
    Render an infocard for a person.
    person: (id, ssn, name, designation, notes, last_seen_ts, last_seen_feed)
    Returns a PIL Image (RGBA, 650x200).
    """
    _, ssn, name, designation, notes, last_seen_ts, last_seen_feed = person

    font_sm   = _load_font(15)
    font_bold = _load_font_bold(18)

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

    # Description bar
    text_color = HIGHLIGHT_TEXT_COLOR.get(designation, (0, 0, 0))
    truncated = _truncate_text(draw, notes or "", font_sm, DESC_MAX_W)
    draw.text((DESC_X, DESC_Y), truncated, font=font_sm, fill=text_color)

    # Bottom rows
    sex_str = face_sex if face_sex else "?"
    age_str = str(int(face_age)) if face_age is not None else "?"

    draw.text((BOT_LEFT_X, BOT_ROW1_Y), f"SSN: {ssn}", font=font_sm, fill=TEXT_WHITE)
    draw.text((BOT_RIGHT_X, BOT_ROW1_Y), f"Sex: {sex_str}", font=font_sm, fill=TEXT_WHITE)
    draw.text((BOT_LEFT_X, BOT_ROW2_Y), f"Designation: {designation.upper()}", font=font_sm, fill=TEXT_WHITE)
    draw.text((BOT_RIGHT_X, BOT_ROW2_Y), f"Age: {age_str}", font=font_sm, fill=TEXT_WHITE)

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

    # Dark red background
    bg_alpha = int(210 * alpha)
    draw.rectangle([(0, 0), (W - 1, H - 1)],
                   fill=(30, 0, 0, bg_alpha))

    # Red border
    border_alpha = int(255 * alpha)
    draw.rectangle([(0, 0), (W - 1, H - 1)],
                   outline=(180, 20, 20, border_alpha), width=2)

    # Accent bar at top
    draw.rectangle([(0, 0), (W - 1, 4)],
                   fill=(200, 30, 30, border_alpha))

    font_hdr  = _load_font_bold(14)
    font_body = _load_font(13)
    font_sm   = _load_font(11)

    text_alpha = int(255 * alpha)
    red_bright = (255, 80,  80,  text_alpha)
    white      = (220, 220, 220, text_alpha)
    grey       = (140, 140, 140, text_alpha)

    # ⚠ ALERT header
    draw.text((12, 10), f"⚠  ALERT  —  RULE {rule_id}", font=font_hdr, fill=red_bright)

    # Divider
    draw.line([(12, 32), (W - 12, 32)], fill=(100, 20, 20, text_alpha), width=1)

    # Condition label
    truncated = label if len(label) <= 70 else label[:67] + "..."
    draw.text((12, 38), truncated, font=font_body, fill=white)

    # Subject names
    if names:
        name_str = "  ".join(n.upper() for n in names[:4])
        if len(names) > 4:
            name_str += f"  +{len(names) - 4} more"
        draw.text((12, 62), name_str, font=font_sm, fill=grey)

    # Timestamp
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

    # Clamp to frame bounds
    if y1 < 0 or x2 > fw:
        return frame

    alpha = card_rgba[:, :, 3:4] / 255.0
    card_bgr = card_rgba[:, :, :3][:, :, ::-1]   # RGB → BGR

    roi = frame[y1:y2, x1:x2].astype(np.float32)
    blended = alpha * card_bgr + (1.0 - alpha) * roi
    frame[y1:y2, x1:x2] = blended.astype(np.uint8)

    return frame


def pil_to_qpixmap(pil_img):
    from PyQt5.QtGui import QImage, QPixmap
    rgba = pil_img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(data, rgba.width, rgba.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg)