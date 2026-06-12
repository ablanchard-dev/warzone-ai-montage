#!/usr/bin/env python3
"""Montage automatique des moments forts de Warzone, à partir d'un dossier de clips.

Exemples :
    python main.py ./clips -m musique.mp3 -o montage.mp4
    python main.py ./clips -m musique.mp3 --no-vision        # sans templates HUD
    python main.py ./clips -m musique.mp3 --no-voice         # sans transcription
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

# Console Windows en cp1252 par défaut -> les caractères Unicode (→, é, ✓...)
# font planter print(). On force UTF-8 sur stdout/stderr.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

import yaml

from wzmontage.audio import detect_action_peaks, extract_audio, transcribe_voice
from wzmontage.killdetect import detect_kill_banners
from wzmontage.models import Candidate
from wzmontage.montage import build_montage
from wzmontage.scoring import build_candidates, select_global
from wzmontage.utils import ensure_tools, ffprobe, list_videos
from wzmontage.vision import detect_victory, detect_visual_events, load_templates


FORMATS = {
    "horizontal": (1920, 1080),
    "vertical": (1080, 1920),
    "square": (1080, 1080),
}


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_formats(arg, cfg):
    """Renvoie une liste de (nom, (w, h)). Plusieurs formats = plusieurs fichiers."""
    if not arg:
        return [(None, (cfg["output"]["width"], cfg["output"]["height"]))]
    out = []
    for name in arg.split(","):
        name = name.strip().lower()
        if name not in FORMATS:
            raise SystemExit(f"Format inconnu : {name} (choix : {', '.join(FORMATS)})")
        out.append((name, FORMATS[name]))
    return out


def output_name(base, fmt_name, n_formats):
    if n_formats <= 1 or not fmt_name:
        return base
    p = Path(base)
    return str(p.with_name(f"{p.stem}_{fmt_name}{p.suffix}"))


def parse_manual_segment(spec: str, videos) -> Candidate:
    """Override manuel (chat-direction) -> Candidate forcé.

    Formats acceptés :
        'nom_clip@last:17'   -> les 17 dernières secondes du clip
        'nom_clip@103-120'   -> la plage 103s à 120s
    'nom_clip' = n'importe quelle sous-chaîne du nom de fichier.
    """
    if "@" not in spec:
        raise SystemExit(f"--add invalide (il manque '@') : {spec}")
    key, rng = spec.rsplit("@", 1)
    key, rng = key.strip(), rng.strip().lower()
    matches = [v for v in videos if key.lower() in Path(v).name.lower()]
    if not matches:
        raise SystemExit(f"--add : aucun clip ne correspond à « {key} »")
    if len(matches) > 1:
        print(f"  ⚠ --add : « {key} » correspond à {len(matches)} clips, "
              f"je prends {Path(matches[0]).name}")
    video = str(matches[0])
    dur = ffprobe(video)["duration"]
    if rng.startswith("last:"):
        start, end = dur - float(rng[len("last:"):]), dur
    elif "-" in rng:
        a, b = rng.split("-", 1)
        start, end = float(a), float(b)
    else:
        raise SystemExit(f"--add : plage invalide « {rng} » (attendu 'last:N' ou 'A-B')")
    start = max(0.0, min(start, dur))
    end = max(start, min(end, dur))
    return Candidate(video, start, end, score=999.0, n_kills=0, kinds={"manual"})


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Montage automatique des moments forts de Warzone (multi-clips).")
    ap.add_argument("input", help="Dossier de clips Warzone (ou un seul fichier)")
    ap.add_argument("-m", "--music", help="Musique de fond (ajoutée en post)")
    ap.add_argument("-o", "--output", default="montage.mp4")
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("-f", "--format", default=None,
                    help="horizontal | vertical | square (virgules pour plusieurs fichiers)")
    ap.add_argument("--max-seconds", type=float,
                    help="Durée max du montage (override config)")
    ap.add_argument("--ending", choices=["auto", "victory", "none"],
                    help="Comment finir le montage (override config)")
    ap.add_argument("--no-voice", action="store_true",
                    help="Désactive la transcription voix / sous-titres")
    ap.add_argument("--no-vision", action="store_true",
                    help="Désactive la détection visuelle des kills")
    ap.add_argument("--add", action="append", default=[], metavar="SPEC",
                    help="Forcer un segment (placé dans l'ordre chrono) : "
                         "'nom_clip@last:17' = 17 dernières s, ou 'nom_clip@103-120' = plage. "
                         "Répétable.")
    ap.add_argument("--drop", action="append", default=[], metavar="SPEC",
                    help="Retirer les segments chevauchant SPEC ('nom_clip@A-B'). Répétable.")
    ap.add_argument("--first", action="append", default=[], metavar="SPEC",
                    help="Épingler un segment en TÊTE du montage (après l'intro) : "
                         "'nom_clip@last:17' ou 'nom_clip@A-B'. Répétable.")
    ap.add_argument("--intro", metavar="PATH",
                    help="Fichier d'intro mis TOUT au début, gardé à vitesse normale (ex: clip casteurs).")
    ap.add_argument("--intro-crop", metavar="W:H:X:Y",
                    help="Crop appliqué à l'intro (ex: 310:1080:0:0 pour la colonne facecams gauche).")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="Accélère les segments gameplay (ex: 1.15). L'intro reste à 1x.")
    ap.add_argument("--mute-gameplay", action="store_true",
                    help="Coupe l'audio du gameplay (garde l'intro casteurs) → clip muet prêt pour un son TikTok.")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.max_seconds:
        cfg["editing"]["max_total_seconds"] = args.max_seconds
    if args.ending:
        cfg["editing"]["ending"] = args.ending
    use_victory = cfg["vision"].get("detect_victory", True) and not args.no_vision
    ensure_tools(need_tesseract=use_victory)

    videos = list_videos(args.input)
    if not videos:
        raise SystemExit(f"Aucune vidéo trouvée dans : {args.input}")
    print(f"→ {len(videos)} vidéo(s) à analyser")

    # Détection des kills SANS calibrage : bandeau rouge "ENNEMI ABATTU" du HUD.
    # Les templates (calibrate.py) restent un BONUS optionnel s'ils existent.
    templates = [] if args.no_vision else load_templates(cfg["vision"]["templates_dir"])

    all_cands = []
    speech_by_video = {}

    for v in videos:
        info = ffprobe(v)
        print(f"\n• {Path(v).name}  ({info['duration']:.0f}s, "
              f"{info['width']}x{info['height']})")
        events = []

        if not args.no_vision:
            print("  vision : kills (bandeau ENNEMI ABATTU, sans calibrage)...")
            events += detect_kill_banners(v, fps=info["fps"])

        if templates:
            print("  vision : kills / mises à terre (templates)...")
            events += detect_visual_events(
                v, templates, tuple(cfg["vision"]["search_region"]),
                threshold=cfg["vision"]["threshold"],
                sample_fps=cfg["vision"]["sample_fps"], fps=info["fps"])
        if use_victory:
            events += detect_victory(
                v, tuple(cfg["vision"]["victory_region"]), fps=info["fps"])

        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / "a.wav"
            extract_audio(v, wav, sr=cfg["audio"]["sr"])
            # Les pics audio ne génèrent un extrait que si activés : par défaut les
            # KILLS sont la colonne vertébrale (l'audio ne déclenche pas seul).
            if cfg["audio"].get("use_action_peaks", False):
                events += detect_action_peaks(
                    wav, v, sr=cfg["audio"]["sr"],
                    percentile=cfg["audio"]["percentile"],
                    min_gap=cfg["audio"]["min_gap_s"])
            if not args.no_voice:
                print("  voix : transcription (whisper)...")
                segs, sev = transcribe_voice(
                    wav, v, model_size=cfg["audio"]["whisper_model"],
                    language=cfg["audio"].get("language"))
                if segs:
                    speech_by_video[str(v)] = segs
                    events += sev

        cands = build_candidates(events, info["duration"], cfg)
        print(f"  → {len(cands)} moments candidats")
        all_cands += cands

    if not all_cands:
        raise SystemExit("Aucun moment détecté. Baisse audio.percentile ou ajoute des templates.")

    # --drop : retirer les candidats AVANT la sélection → libère le budget. Un clip qu'on
    # remplace via --add (ex: le montage ranked) ne doit pas bouffer le quota puis être jeté.
    for spec in args.drop:
        d = parse_manual_segment(spec, videos)
        before = len(all_cands)
        all_cands = [c for c in all_cands
                     if not (c.video == d.video and c.start < d.end and c.end > d.start)]
        print(f"   - drop : {before - len(all_cands)} candidat(s) retiré(s) "
              f"({Path(d.video).name} {d.start:.0f}-{d.end:.0f}s)")

    selected = select_global(all_cands, cfg)

    # --add : forcer des segments, replacés dans l'ordre chronologique (par vidéo puis temps)
    for spec in args.add:
        manual = parse_manual_segment(spec, videos)
        selected.append(manual)
        print(f"   + segment manuel : {Path(manual.video).name} "
              f"{manual.start:.0f}-{manual.end:.0f}s")
    if args.add and cfg["editing"].get("order", "chronological") == "chronological":
        selected.sort(key=lambda c: (c.video, c.start))

    # --first : épingler des segments en TÊTE (priment sur l'ordre, ex : hook d'ouverture)
    if args.first:
        front = [parse_manual_segment(spec, videos) for spec in args.first]
        for f in front:
            print(f"   ↑ en tête : {Path(f.video).name} {f.start:.0f}-{f.end:.0f}s")
        selected = front + selected

    # --speed : accélère les segments gameplay (l'intro, ajoutée après, reste à 1x)
    if args.speed and args.speed != 1.0:
        for c in selected:
            c.speed = args.speed

    # --intro : clip d'intro tout au début, vitesse normale (crop optionnel pour les facecams)
    if args.intro:
        intro_dur = ffprobe(args.intro)["duration"]
        selected = [Candidate(args.intro, 0.0, intro_dur, score=999.0,
                              crop=args.intro_crop, speed=1.0, is_intro=True)] + selected
        print(f"   ▶ intro : {Path(args.intro).name} ({intro_dur:.0f}s, x1"
              + (f", crop {args.intro_crop}" if args.intro_crop else "") + ")")

    total = sum(c.duration for c in selected)
    print(f"\n→ {len(selected)} extraits retenus (~{total:.0f}s)")
    for c in selected:
        tags = []
        if c.has_victory:
            tags.append("VICTOIRE")
        if c.n_kills >= 3:
            tags.append(f"{c.n_kills}K")
        elif c.n_kills == 2:
            tags.append("2K")
        if c.has_speech:
            tags.append("voix")
        print(f"   {Path(c.video).name}  {c.start:.0f}-{c.end:.0f}s  "
              f"score={c.score:.1f}  {' '.join(tags)}")

    print("\n→ Montage et mixage...")
    formats = resolve_formats(args.format, cfg)
    speech = speech_by_video if not args.no_voice else None
    for fmt_name, (w, h) in formats:
        cfg_fmt = {**cfg, "output": {**cfg["output"], "width": w, "height": h}}
        out_path = output_name(args.output, fmt_name, len(formats))
        label = f" [{fmt_name}]" if fmt_name else ""
        print(f"   montage{label} {w}x{h}...")
        build_montage(selected, args.music, out_path, cfg_fmt, speech_by_video=speech,
                      mute_gameplay=args.mute_gameplay)
        print(f"   ✓ {out_path}")
    print("✓ Terminé.")


if __name__ == "__main__":
    main()
