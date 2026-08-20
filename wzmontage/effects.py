# -*- coding: utf-8 -*-
"""Primitives d'effets vidéo (couche 1 du cahier des charges).

Chaque effet = une fonction qui produit un fragment de filtergraph ffmpeg,
généré par le code (jamais piloté en filtre brut par l'utilisateur/LLM — cf. sécurité).

Effets disponibles :
- zoom_punch : zoom rapide centré sur un instant (le "boom" sur un kill). Implémenté
  via `scale` time-varying (eval=frame, piloté par le timestamp `t`) puis crop centré
  fixe → évite le jitter connu de `zoompan` (arrondi par frame). Prouvé sur clip réel
  (out_phaseA/zoompunch_test.mp4, frames normal/peak vérifiées le 2026-06-15).
"""
from __future__ import annotations

from typing import Sequence


def _punch_env(center: float, atk: float = 0.08, rel: float = 0.18,
               tvar: str = "t") -> str:
    """Enveloppe 'punch' (variable temps = `tvar`) : 0 AVANT le kill, montée RAPIDE (atk)
    jusqu'au pic, puis descente douce (rel). Démarre PILE au kill → bien synchro."""
    t0, tp, t1 = center, center + atk, center + atk + rel
    return (f"if(between({tvar},{t0:.3f},{t1:.3f}),"
            f"if(lt({tvar},{tp:.3f}),({tvar}-{t0:.3f})/{atk:.3f},"
            f"1-({tvar}-{tp:.3f})/{rel:.3f}),0)")


def zoom_punch_zexpr(centers: Sequence[float], peak: float = 1.18,
                     atk: float = 0.08, rel: float = 0.18, tvar: str = "t",
                     peaks: Sequence[float] | None = None) -> str:
    """Facteur de zoom z : 1.0 au repos, pic PILE sur chaque centre. Plusieurs centres =
    max des punchs (pas d'addition). Pic subtil par défaut (1.18).

    `peaks` (optionnel) = pic PROPRE à chaque centre (même longueur que `centers`) → permet
    de mixer des punchs forts (kills) et doux (beats) : z = 1 + max_i((peak_i-1)*env_i)."""
    if not centers:
        return "1"
    if peaks is None:
        peaks = [peak] * len(centers)
    terms = [f"{pk - 1.0:.3f}*({_punch_env(c, atk, rel, tvar)})"
             for c, pk in zip(centers, peaks)]
    m = terms[0]
    for e in terms[1:]:
        m = f"max({m},{e})"
    return f"1+({m})"


def zoom_punch_filter(centers: Sequence[float], out_w: int, out_h: int,
                      peak: float = 1.18, atk: float = 0.08, rel: float = 0.18,
                      fps: int = 60, peaks: Sequence[float] | None = None) -> str:
    """Zoom-punch SUBTIL, CENTRÉ et bien timé, via `zoompan` (qui gère le recadrage centré
    par frame en interne — l'approche scale+crop dérivait en bas-droite). Le temps est
    `on/fps` (index de frame de sortie). Sortie de taille fixe out_w x out_h.
    `peaks` = pic par-centre (kills forts / beats doux), sinon `peak` pour tous."""
    z = zoom_punch_zexpr(centers, peak=peak, atk=atk, rel=rel, tvar=f"(on/{fps})", peaks=peaks)
    return (f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s={out_w}x{out_h}:fps={fps}")


def shake_filter(t0: float, dur: float, out_w: int, out_h: int,
                 amp_px: int = 64, freq_x: float = 10.0, freq_y: float = 13.0,
                 decay: float = 6.0) -> str:
    """Secousse caméra amortie sur l'impact (le 'boom' d'un kill). OPTIONNELLE :
    n'agit que dans [t0, t0+dur], identité ailleurs (appelée seulement si la timeline
    le demande — jamais automatique en dur).

    crop centré avec offset sin sur x/y (fréquences différentes → mouvement non
    circulaire), enveloppe exponentielle décroissante. Marge via léger upscale pour
    éviter les bords noirs. Prouvé sur clip réel (mesure du déplacement inter-frame
    vs sans-shake, 2026-06-15)."""
    m = int(amp_px)
    env = f"if(between(t,{t0:.3f},{t0 + dur:.3f}),exp(-{decay:.1f}*(t-{t0:.3f})),0)"
    x = f"{m}+{m}*({env})*sin(2*PI*{freq_x}*(t-{t0:.3f}))"
    y = f"{m}+{m}*({env})*cos(2*PI*{freq_y}*(t-{t0:.3f}))"
    return (f"scale={out_w + 2 * m}:{out_h + 2 * m},"
            f"crop={out_w}:{out_h}:x='{x}':y='{y}',setsar=1")


def slowmo_filter(factor: float = 2.5, fps: int = 60, interpolate: bool = True) -> str:
    """Ralenti OPTIONNEL (le 'gros moment'). factor>1 ralentit (2.5 = 0.4x vitesse).

    interpolate=True → `minterpolate` (optical flow, mci/aobmc/vsbmc) génère des frames
    intermédiaires → ralenti FLUIDE (sinon frames dupliquées = saccadé). Coûteux en CPU
    (~30s pour 1s de 1080p) → réserver aux fenêtres courtes. Vidéo seule ; l'audio du
    moment ralenti est géré à part (musique/mute). À appliquer sur une PIECE de segment
    (la timeline découpe le 1x / le ralenti / le 1x). Prouvé : 1s -> 2.43s @60fps (2026-06-15)."""
    f = f"setpts={factor}*PTS"
    if interpolate:
        f += f",minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:vsbmc=1"
    return f


if __name__ == "__main__":
    # Auto-test isolé : rend un extrait d'un clip avec un zoom-punch et vérifie la sortie.
    #   python -m wzmontage.effects --clip "CLIP.mp4" --ss 10 --dur 3 --at 1.5
    import argparse
    import subprocess
    import sys
    from pathlib import Path

    ap = argparse.ArgumentParser(description="Test isolé du zoom_punch.")
    ap.add_argument("--clip", required=True)
    ap.add_argument("--ss", type=float, default=10.0, help="début de l'extrait (s)")
    ap.add_argument("--dur", type=float, default=3.0, help="durée de l'extrait (s)")
    ap.add_argument("--at", type=float, action="append", default=None,
                    help="instant(s) du punch dans l'extrait (répétable)")
    ap.add_argument("--peak", type=float, default=1.35)
    ap.add_argument("--out", default="out_phaseA/zoompunch_test.mp4")
    a = ap.parse_args()
    centers = a.at or [a.dur / 2.0]

    # probe résolution
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", a.clip],
        capture_output=True, text=True, check=True)
    w, h = (int(x) for x in probe.stdout.strip().split(","))
    filt = zoom_punch_filter(centers, w, h, peak=a.peak)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{a.ss}", "-i", a.clip, "-t", f"{a.dur}",
           "-filter:v", filt, "-an", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "20", a.out]
    subprocess.run(cmd, check=True)
    print(f"OK -> {a.out}  ({w}x{h}, punch @ {centers})")
    sys.exit(0)
