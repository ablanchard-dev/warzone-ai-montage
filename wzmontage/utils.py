"""Utilitaires : exécution ffmpeg/ffprobe, vérifs, listing des vidéos."""
from __future__ import annotations

import json
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
