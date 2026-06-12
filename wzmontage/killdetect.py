"""Détection des kills du joueur via le bandeau d'élimination du HUD Warzone.

Quand le joueur abat / met à terre un ennemi, un bandeau ROUGE apparaît en haut
à droite ("ENNEMI ABATTU", "ENNEMI À TERRE", "Xe ÉLIMINATION"). On détecte le
flash de pixels rouges dans cette zone -> instant du kill.

Avantages (vs template matching de calibrate.py) :
- ZÉRO calibrage manuel (le point bloquant du projet)
- ZÉRO dépendance OCR
- robuste : le rouge du bandeau est constant, les bandeaux bleus (coéquipier à
  terre) et oranges (killstreak / UAV) sont naturellement exclus par la teinte.
"""
from __future__ import annotations

from typing import List

from .models import Event


def _red_fraction(bgr_roi) -> float:
    """Fraction de pixels ROUGE vif dans la zone (rouge = bandeau de kill)."""
    import cv2

    hsv = cv2.cvtColor(bgr_roi, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    # rouge = teinte proche de 0 ou 180, saturé et assez lumineux
    red = (((h <= 8) | (h >= 172)) & (s >= 110) & (v >= 90))
    return float(red.mean())


def detect_kill_banners(video_path, region=(0.79, 0.11, 0.20, 0.13),
                        sample_fps: float = 5.0, fps: float | None = None,
                        min_gap: float = 1.5, on_frac: float = 0.33) -> List[Event]:
    """Renvoie un Event 'kill' à chaque apparition du bandeau rouge.

    region = (x, y, w, h) en fractions de l'image. Par défaut = la bande où
    apparaît le bandeau "ENNEMI ABATTU" (sous les compteurs SR/joueurs, dont le
    rouge permanent doit être EXCLU).
    on_frac = fraction de rouge mini : le vrai bandeau est un GROS rectangle
    rouge plein (~40%+ de la zone) ; le bruit (SR rouge, marqueurs) reste ~0.
    min_gap = anti-rebond (s) pour ne pas compter 2x le même bandeau.
    """
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    if fps is None:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / sample_fps)))

    events: List[Event] = []
    idx = 0
    last = -1e9
    active = False
    while True:
        if not cap.grab():
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            t = idx / fps
            h, w = frame.shape[:2]
            x, y, rw, rh = region
            roi = frame[int(y * h):int((y + rh) * h), int(x * w):int((x + rw) * w)]
            frac = _red_fraction(roi) if roi.size else 0.0
            now = frac >= on_frac
            # front montant = le bandeau vient d'apparaître = un kill
            if now and not active and (t - last) >= min_gap:
                events.append(Event(str(video_path), float(t), "kill", float(frac)))
                last = t
            active = now
        idx += 1
    cap.release()
    return events
