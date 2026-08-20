# -*- coding: utf-8 -*-
"""Compositeur de segment (cœur du moteur, Phase B).

C'est LE programme qui monte : à partir d'une *spec* (la tranche de timeline d'un
segment : layout + effets + overlays choisis), il COMPOSE automatiquement les primitives
(effects/layouts/overlays/sfx) en UN filtergraph ffmpeg et rend le segment.

Aucun montage à la main : la spec est remplie par la détection (défauts) puis par
l'utilisateur (chat / UI) — le programme exécute. Tout est OPTIONNEL (spec vide = clip brut).
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from . import effects, overlays

FORMATS = {"vertical": (1080, 1920), "fullscreen": (1920, 1080), "square": (1080, 1080),
           "facecam_top": (1080, 1920)}


def _probe_dims(clip: str) -> tuple[int, int, int]:
    """Renvoie (width, height, fps_source_arrondi)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate", "-of", "csv=p=0", clip],
        capture_output=True, text=True, check=True).stdout.strip().split(",")
    w, h = int(out[0]), int(out[1])
    num, den = (out[2].split("/") + ["1"])[:2]
    fps = float(num) / float(den) if float(den) else float(num)
    return w, h, round(fps)


def build_segment_filtergraph(spec: dict, src_w: int, src_h: int, fps: int = 60,
                              src_fps: int | None = None):
    """Compose la spec en un filter_complex [0:v] -> [v]. Renvoie (graph, (out_w,out_h)).

    `fps` = framerate de SORTIE (cadence finale) ; `src_fps` = framerate de la SOURCE
    (pour zoompan, sinon ralenti). Ordre : effets (zoom) -> cadrage -> overlays texte.
    """
    if src_fps is None:
        src_fps = fps
    fmt = spec.get("format", "vertical")
    out_w, out_h = FORMATS.get(fmt, FORMATS["vertical"])

    # Vitesse (setpts) : AVANT le split → s'applique au fond ET au premier plan (synchro).
    speed = spec.get("speed", 1.0)
    speed_chain = f"setpts=PTS/{speed}," if (speed and speed != 1.0) else ""

    # Effets VISUELS (zoom_punch, shake) : UNIQUEMENT sur le gameplay net (premier plan),
    # JAMAIS sur le fond flou → le fond reste stable, seul le centre "punche". (sinon toute
    # l'image respire = l'effet dégueu signalé par Alex).
    fx = []
    centers = spec.get("zoom_punch") or []
    if centers:
        fx.append(effects.zoom_punch_filter(centers, src_w, src_h,
                                             peak=spec.get("zoom_peak", 1.18),
                                             peaks=spec.get("zoom_peaks"), fps=src_fps))
    for sh in (spec.get("shake") or []):
        fx.append(effects.shake_filter(sh["t0"], sh.get("dur", 0.4), src_w, src_h,
                                       amp_px=sh.get("amp", 64)))
    fx_chain = (",".join(fx) + ",") if fx else ""

    texts = ""
    for t in (spec.get("text") or []):
        texts += "," + overlays.text_overlay(
            t["t0"], t["t1"], text=t.get("text"), textfile=t.get("textfile"),
            fontsize=t.get("fontsize", 200))

    if fmt == "vertical":
        graph = (
            f"[0:v]{speed_chain}split=2[v0][v1];"
            f"[v0]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h},boxblur=20:5[bg];"
            f"[v1]{fx_chain}scale={out_w}:{out_h}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={fps},format=yuv420p{texts}[v]")
    elif fmt == "facecam_top":  # facecam/stream en haut + gameplay blur-fill en bas
        top_h = spec.get("facecam_h", 600)
        bot_h = out_h - top_h
        fc_crop = spec.get("facecam_crop", "960:540:480:0")
        graph = (
            f"[0:v]{speed_chain}split=3[fc][bg][fg];"
            f"[fc]crop={fc_crop},scale={out_w}:{top_h},setsar=1[top];"
            f"[bg]scale={out_w}:{bot_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{bot_h},boxblur=20:5[bgb];"
            f"[fg]{fx_chain}scale={out_w}:{bot_h}:force_original_aspect_ratio=decrease[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2[bottom];"
            f"[top][bottom]vstack=inputs=2,fps={fps},format=yuv420p{texts}[v]")
    else:  # fullscreen / square : un seul plan → fx sur toute l'image
        graph = (
            f"[0:v]{speed_chain}{fx_chain}scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
            f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p{texts}[v]")
    return graph, (out_w, out_h)


def render_segment(clip: str, start: float, dur: float, spec: dict, out: str,
                   fps: int = 60) -> str:
    """LE PROGRAMME rend un segment composé selon la spec (aucun ffmpeg à la main)."""
    src_w, src_h, src_fps = _probe_dims(clip)
    graph, _ = build_segment_filtergraph(spec, src_w, src_h, fps, src_fps=src_fps)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", clip,
           "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-c:a", "aac", "-r", str(fps), out]
    subprocess.run(cmd, check=True)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Rendre un segment composé via le programme.")
    ap.add_argument("--clip", required=True)
    ap.add_argument("--start", type=float, default=10.0)
    ap.add_argument("--dur", type=float, default=4.0)
    ap.add_argument("--spec", help="fichier JSON de spec (sinon démo)")
    ap.add_argument("--out", default="out_phaseA/compositor_demo.mp4")
    a = ap.parse_args()
    if a.spec:
        spec = json.load(open(a.spec, encoding="utf-8"))
    else:  # spec démo : vertical + zoom-punch+shake sur 2 "kills" + BOOM
        spec = {
            "format": "vertical",
            "zoom_punch": [1.5, 3.0],
            "shake": [{"t0": 1.45, "dur": 0.4}, {"t0": 2.95, "dur": 0.4}],
            "text": [{"text": "BOOM", "t0": 1.4, "t1": 2.0}],
        }
    out = render_segment(a.clip, a.start, a.dur, spec, a.out)
    print(f"PROGRAMME -> montage composé : {out}  (spec: {json.dumps(spec, ensure_ascii=False)})")
