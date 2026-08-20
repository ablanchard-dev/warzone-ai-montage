# -*- coding: utf-8 -*-
"""Primitives de layout & transitions (couche 1). Toutes OPTIONNELLES : choisies par
la timeline, jamais imposées.

- facecam_top : split TikTok gaming (facecam/stream en haut, gameplay en bas). Le
  gameplay est en blur-fill → le HUD reste ENTIER visible (contrainte produit). Prouvé
  sur clip réel (facecam_top_test.mp4, frame vérifiée le 2026-06-15).
- transition_xfade : flash / whip / cut entre deux segments via xfade. Prouvé
  (transition_test.mp4, fadewhite, 2026-06-15).

Le layout vertical blur-fill simple existe déjà dans montage._vfilter.
"""
from __future__ import annotations


def facecam_top_filtergraph(out_w: int = 1080, out_h: int = 1920, top_h: int = 600,
                            fc_crop: str = "960:540:480:0", blur: bool = True,
                            facecam_input: str | None = None) -> str:
    """filter_complex pour le layout facecam-haut → produit le label [v] (out_w x out_h).

    - top_h : hauteur de la bande facecam (le gameplay occupe out_h - top_h).
    - fc_crop : zone "w:h:x:y" à prélever comme facecam quand facecam_input est None
      (facecam = crop du gameplay lui-même). Si facecam_input est fourni (ex "[1:v]"),
      cette source est utilisée à la place.
    - le gameplay (bas) est mis en blur-fill → 16:9 entier visible, HUD préservé.
    """
    bot_h = out_h - top_h
    if facecam_input:
        top = (f"{facecam_input}scale={out_w}:{top_h}:force_original_aspect_ratio=increase,"
               f"crop={out_w}:{top_h},setsar=1[top];")
        split = "[0:v]split=2[bg][fg];"
    else:
        split = "[0:v]split=3[fc][bg][fg];"
        top = f"[fc]crop={fc_crop},scale={out_w}:{top_h},setsar=1[top];"
    if blur:
        bottom = (f"[bg]scale={out_w}:{bot_h}:force_original_aspect_ratio=increase,"
                  f"crop={out_w}:{bot_h},boxblur=20:5[bgb];"
                  f"[fg]scale={out_w}:{bot_h}:force_original_aspect_ratio=decrease[fgs];"
                  f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2[bottom];")
    else:
        bottom = (f"[bg]scale={out_w}:{bot_h}:force_original_aspect_ratio=decrease,"
                  f"pad={out_w}:{bot_h}:(ow-iw)/2:(oh-ih)/2[bottom];[fg]nullsink;")
    return (split + top + bottom +
            "[top][bottom]vstack=inputs=2,format=yuv420p[v]")


def transition_xfade(kind: str = "fadewhite", duration: float = 0.3,
                     offset: float = 0.0) -> str:
    """Fragment xfade pour enchaîner deux flux étiquetés (à insérer dans un
    filter_complex : `[a][b]` + ce fragment + `[v]`). kind : fade | fadewhite (flash) |
    fadeblack | wipeleft/right (whip) | slideup/down | dissolve … (transitions xfade).
    offset = instant (s) où démarre la transition dans le flux A."""
    return f"xfade=transition={kind}:duration={duration:.3f}:offset={offset:.3f}"
