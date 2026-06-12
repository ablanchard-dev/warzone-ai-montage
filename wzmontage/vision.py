"""Détection visuelle dans le HUD Warzone.

- Kills / mises à terre / éliminations : template matching de l'icône qui flashe
  à l'écran (méthode robuste recommandée, indépendante du son).
- Écran de victoire (#1 / VICTOIRE) : OCR sur la zone centrale.

Les templates sont à créer depuis TES propres images via calibrate.py
(ils dépendent de la résolution et du HUD).
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from .models import Event

TEMPLATE_TYPES = ("kill", "knock", "elim")


def load_templates(templates_dir) -> List[Tuple[str, str, "any"]]:
    """Charge les PNG nommés <type>[_xxx].png (type = kill / knock / elim)."""
    import cv2

    out = []
    d = Path(templates_dir)
    if not d.exists():
        return out
    for f in sorted(d.glob("*.png")):
        typ = f.stem.split("_")[0].lower()
        if typ not in TEMPLATE_TYPES:
            continue
        img = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            out.append((typ, f.name, img))
    return out


def _crop(frame, region):
    h, w = frame.shape[:2]
    x, y, rw, rh = region
    return frame[max(0, int(y * h)):int((y + rh) * h),
                 max(0, int(x * w)):int((x + rw) * w)]


def detect_visual_events(video_path, templates, search_region,
                         threshold: float = 0.72, sample_fps: float = 4.0,
                         fps: float | None = None, min_gap: float = 0.6) -> List[Event]:
    """Cherche les icônes de kill/knock/elim dans une zone de l'écran."""
    import cv2

    if not templates:
        return []
    cap = cv2.VideoCapture(str(video_path))
    if fps is None:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / sample_fps)))

    events: List[Event] = []
    idx = 0
    last = {t: -1e9 for t in TEMPLATE_TYPES}
    while True:
        if not cap.grab():
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            t = idx / fps
            roi = cv2.cvtColor(_crop(frame, search_region), cv2.COLOR_BGR2GRAY)
            for typ, _name, tpl in templates:
                # Multi-échelle : robustesse si la footage n'a pas exactement la
                # résolution des templates (l'icône peut être plus grande/petite).
                best = 0.0
                for scale in (0.6, 0.75, 0.9, 1.0, 1.15, 1.3, 1.5):
                    th, tw = int(tpl.shape[0] * scale), int(tpl.shape[1] * scale)
                    if th < 8 or tw < 8 or roi.shape[0] < th or roi.shape[1] < tw:
                        continue
                    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
                    tpl_s = cv2.resize(tpl, (tw, th), interpolation=interp)
                    score = float(cv2.matchTemplate(roi, tpl_s, cv2.TM_CCOEFF_NORMED).max())
                    if score > best:
                        best = score
                if best >= threshold and (t - last[typ]) >= min_gap:
                    events.append(Event(str(video_path), float(t), typ, best))
                    last[typ] = t
        idx += 1
    cap.release()
    return events


VICTORY_WORDS = ["VICTORY", "VICTOIRE", "#1", "WINS", "WIN!"]


def detect_victory(video_path, region, fps: float | None = None,
                   sample_fps: float = 1.0) -> List[Event]:
    """Détecte l'écran de victoire par OCR (optionnel, nécessite tesseract)."""
    try:
        import cv2
        import pytesseract
    except ImportError:
        return []

    cap = cv2.VideoCapture(str(video_path))
    if fps is None:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / sample_fps)))

    events: List[Event] = []
    idx = 0
    last = -1e9
    while True:
        if not cap.grab():
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            t = idx / fps
            g = cv2.cvtColor(_crop(frame, region), cv2.COLOR_BGR2GRAY)
            g = cv2.resize(g, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            _, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            txt = pytesseract.image_to_string(th, config="--psm 7").upper()
            if any(w in txt for w in VICTORY_WORDS) and (t - last) >= 5.0:
                events.append(Event(str(video_path), float(t), "victory", 1.0))
                last = t
        idx += 1
    cap.release()
    return events
