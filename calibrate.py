#!/usr/bin/env python3
"""Calibrage du HUD Warzone : aperçu d'une zone + extraction d'un template de kill.

1) Repère dans un clip un instant où l'icône de kill / mise à terre flashe à l'écran.
2) Aperçu de la zone (ajuste X Y W H jusqu'à bien cadrer l'icône) :

    python calibrate.py clip.mp4 -t 73.5 -r 0.30 0.35 0.40 0.30

3) Quand c'est bien cadré, sauvegarde le template :

    python calibrate.py clip.mp4 -t 73.5 -r 0.42 0.46 0.06 0.06 --save-template templates/knock.png

Les valeurs r = X Y Largeur Hauteur sont des FRACTIONS de l'écran (0..1).
Reporte ensuite ta zone de recherche dans config.yaml (vision.search_region).
"""
from __future__ import annotations

import argparse
from pathlib import Path


def grab_frame(video, t):
    import cv2

    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise SystemExit("Impossible de lire cette frame (vérifie le temps -t).")
    return frame


def crop(frame, region):
    h, w = frame.shape[:2]
    x, y, rw, rh = region
    return frame[int(y * h):int((y + rh) * h), int(x * w):int((x + rw) * w)]


def main():
    ap = argparse.ArgumentParser(description="Calibrage HUD Warzone.")
    ap.add_argument("video")
    ap.add_argument("-t", "--time", type=float, required=True,
                    help="Instant (s) où l'icône est visible")
    ap.add_argument("-r", "--region", type=float, nargs=4,
                    metavar=("X", "Y", "W", "H"), required=True,
                    help="Zone en fractions 0..1")
    ap.add_argument("--save-template",
                    help="Chemin du PNG à sauvegarder (ex: templates/knock.png)")
    ap.add_argument("--preview", default="preview.png", help="Image d'aperçu du crop")
    args = ap.parse_args()

    import cv2

    frame = grab_frame(args.video, args.time)
    sub = crop(frame, tuple(args.region))
    cv2.imwrite(args.preview, sub)
    print(f"Aperçu : {args.preview}  (taille {sub.shape[1]}x{sub.shape[0]} px)")

    if args.save_template:
        dest = Path(args.save_template)
        dest.parent.mkdir(parents=True, exist_ok=True)
        gray = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)
        cv2.imwrite(str(dest), gray)
        print(f"Template sauvegardé : {dest}")
        print("→ Nomme-le kill.png / knock.png / elim.png pour qu'il soit pris en compte.")


if __name__ == "__main__":
    main()
