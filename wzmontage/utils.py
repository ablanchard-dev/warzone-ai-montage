"""Utilitaires : exécution ffmpeg/ffprobe, vérifs, listing des vidéos."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}


def run(cmd, quiet: bool = True):
    r = subprocess.run(
        [str(c) for c in cmd],
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.PIPE,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(
            "Échec de la commande :\n"
            + " ".join(str(c) for c in cmd)
            + "\n\n"
            + (r.stderr or "")[-2000:]
        )
    return r


def ffprobe(path) -> dict:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate:format=duration",
        "-of", "json", str(path),
    ]
    data = json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)
    # Un fichier AUDIO (musique) n'a aucun flux "v:0" -> streams vide. Seule la
    # duree a du sens pour lui, et c'est tout ce que le beat-sync demande.
    streams = data.get("streams") or []
    s = streams[0] if streams else {}
    num, den = (s.get("avg_frame_rate") or "0/1").split("/")
    den = float(den)
    fps = float(num) / den if den else 30.0
    return {
        "duration": float(data["format"]["duration"]),
        "fps": fps,
        "width": int(s.get("width") or 0),
        "height": int(s.get("height") or 0),
    }


def has_audio(path) -> bool:
    """Vrai si le fichier a au moins une piste audio (une source enregistree sans son n'en a pas)."""
    cmd = ["ffprobe", "-v", "error", "-select_streams", "a",
           "-show_entries", "stream=index", "-of", "csv=p=0", str(path)]
    return bool(subprocess.run(cmd, capture_output=True, text=True).stdout.strip())


def list_videos(path) -> list[Path]:
    """Renvoie la liste des vidéos d'un dossier (récursif) ou un seul fichier."""
    p = Path(path)
    if p.is_file():
        return [p]
    return sorted(f for f in p.rglob("*") if f.suffix.lower() in VIDEO_EXTS)


def ensure_tools(need_tesseract: bool = False) -> None:
    missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
    if need_tesseract and shutil.which("tesseract") is None:
        missing.append("tesseract")
    if missing:
        raise SystemExit(
            "Outils système manquants : " + ", ".join(missing) + " (voir le README)."
        )


_CROP_RE = re.compile(r"^\d+:\d+:\d+:\d+$")


def valider_crop(valeur: str, origine: str) -> str:
    """Rend `valeur` si c'est bien un `W:H:X:Y` de nombres, sinon lève.

    Un crop est la SEULE valeur du produit qu'on ne peut pas échapper : elle contient
    des `:` par construction, et ces `:` doivent rester des séparateurs de ffmpeg. Elle
    entre donc brute dans le filtergraph, et il n'y a qu'une façon de la rendre sûre —
    n'accepter que la forme attendue.

    Ce que ça évite, mesuré le 17/09/2026 sur le code d'alors :
      - `1920x1080` (la faute de frappe naturelle) partait chez ffmpeg et revenait en
        erreur de graphe, loin de la cause et sans dire quoi corriger ;
      - `960:540:480:0,drawbox=c=red@1` ajoutait un VRAI `drawbox` au montage, sans que
        rien ne le signale : une virgule suffit à sortir du filtre.

    Même doctrine que la garde de police dans `overlays.text_overlay` : on échoue ici,
    où le fait est connu, avec le geste de réparation dans le message.
    """
    if not isinstance(valeur, str) or not _CROP_RE.match(valeur):
        raise ValueError(
            "%s invalide : %r. Attendu W:H:X:Y, quatre nombres entiers separes par "
            "des deux-points (ex. 960:540:480:0)." % (origine, valeur)
        )
    return valeur
