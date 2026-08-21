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

from wzmontage.audio import (detect_action_peaks, energy_envelope, extract_audio,
                             transcribe_voice)
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


def resolve_audio(music_path, audio_mode, mute_gameplay):
    """Décide (musique, coupe-son) à partir des drapeaux CLI. Pur -> testable.

    Le sens « --audio mix sans -m » levait déjà une erreur explicite. Le sens
    INVERSE ne disait rien : passer `-m musique.mp3` sans `--audio mix` faisait
    JETER le fichier en silence — le montage sortait sans musique, sans un mot.
    Piège vécu, noté en mémoire comme « -m seul ne fait rien ». Un drapeau qu'il
    faut se souvenir de compléter est un défaut, pas une astuce.

    Renvoie (music, mute, avertissements).
    """
    if audio_mode in ("mix", "music") and not music_path:
        raise SystemExit(f"--audio {audio_mode} nécessite -m <fichier musique>")
    if music_path and audio_mode not in ("mix", "music"):
        raise SystemExit(
            f"-m/--music est IGNORÉ avec --audio {audio_mode}. "
            "Ajoute --audio mix (musique + son du jeu) ou --audio music (musique seule)."
        )
    music = music_path if audio_mode in ("mix", "music") else None
    mute = (audio_mode == "clean") or (mute_gameplay and audio_mode == "game")
    avertissements = []
    if mute_gameplay and audio_mode != "game":
        avertissements.append(
            f"  ⚠ --mute-gameplay ignoré avec --audio {audio_mode} "
            "(il ne s'applique qu'au mode 'game' ; pour la musique seule, --audio music)."
        )
    return music, mute, avertissements


def final_report(degraded) -> str:
    """Mot de la fin du run, portant les dégradations constatées pendant l'analyse.

    Séparé de la boucle de rendu pour être testable. Avant, le run se terminait
    toujours par « ✓ Terminé. » : l'avertissement OCR existait mais était imprimé
    à l'analyse du premier clip, donc des centaines de lignes plus haut. Le détail
    était honnête et la conclusion mentait par omission.
    """
    if not degraded:
        return "✓ Terminé."
    lignes = ["", "⚠ MONTAGE PRODUIT EN MODE DÉGRADÉ :"]
    lignes += [f"   - {raison}" for raison in degraded]
    lignes.append("✓ Terminé — mais relis l'avertissement ci-dessus avant de publier.")
    return "\n".join(lignes)


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
                    help="Accélère les segments gameplay (ex: 1.15). L'intro reste à 1x. "
                         "NE RACCOURCIT PAS le montage : chaque extrait garde sa durée et "
                         "couvre d'autant plus d'action (--speed 2 = 2x plus de jeu dans le "
                         "même temps). Pour un montage plus court, utilise --max-seconds.")
    ap.add_argument("--mute-gameplay", action="store_true",
                    help="Coupe l'audio du gameplay (garde l'intro casteurs) → clip muet prêt pour un son TikTok.")
    ap.add_argument("--fx", action="store_true",
                    help="Raccourci = --zoom + --sfx (tous les effets auto sur les kills). OPTIONNEL.")
    ap.add_argument("--zoom", action="store_true",
                    help="Zoom-punch auto sur les kills détectés. OPTION indépendante, off par défaut.")
    ap.add_argument("--sfx", action="store_true",
                    help="SFX punch auto sur les kills. OPTION indépendante, off par défaut.")
    ap.add_argument("--beat-fx", action="store_true",
                    help="Punchs de zoom DOUX calés sur le beat de la musique (pulse au tempo, feel monté). "
                         "Nécessite -m <musique> + --zoom (ou --fx). OPTION indépendante, off par défaut.")
    ap.add_argument("--beat-peak", type=float, default=None,
                    help="Intensité du pulse beat-fx (défaut 1.08 ; <1.06 = très doux, >1.10 = marqué).")
    ap.add_argument("--beat-stride", type=int, default=None,
                    help="1 pulse beat-fx tous les N beats (défaut 2 ; 3 = plus espacé, 1 = chaque beat).")
    ap.add_argument("--layout", choices=["blurfill", "facecam-top"], default="blurfill",
                    help="Disposition verticale (avec --fx) : blurfill (défaut) ou facecam-top (stream en haut, gameplay en bas).")
    ap.add_argument("--transitions", default=None, metavar="KIND",
                    help="Transition entre segments : fade, fadewhite (flash), wipeleft, slideup… Off par défaut (cut franc).")
    ap.add_argument("--audio", choices=["game", "mix", "music", "clean"], default="game",
                    help="Son : game = jeu + prox-chat (défaut, rien coupé) | mix = jeu + musique | "
                         "music = musique seule | clean = muet (pour coller le son TikTok au post).")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.max_seconds:
        cfg["editing"]["max_total_seconds"] = args.max_seconds
    if args.ending:
        cfg["editing"]["ending"] = args.ending
    # --audio : mode son, rien d'imposé. Défaut = garder le son du jeu (balles + prox-chat = le moat).
    music, mute, avertissements = resolve_audio(args.music, args.audio, args.mute_gameplay)
    for a in avertissements:
        print(a)
    if args.audio == "music":
        cfg["editing"]["game_audio_volume"] = 0.0   # musique seule : jeu coupé sous la musique
    do_zoom = args.zoom or args.fx   # effets indépendants ; --fx = raccourci pour les deux
    do_sfx = args.sfx or args.fx
    if args.beat_fx and (not music or not do_zoom):
        print("  ⚠ --beat-fx ignoré : nécessite une musique (-m … --audio mix/music) ET --zoom/--fx.")
    if args.beat_peak is not None:
        cfg["editing"]["beat_fx_peak"] = args.beat_peak
    if args.beat_stride is not None:
        cfg["editing"]["beat_fx_stride"] = args.beat_stride
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
            kd = cfg.get("killdetect", {})
            events += detect_kill_banners(
                v, fps=info["fps"],
                sample_fps=kd.get("sample_fps", 5.0),
                min_gap=kd.get("min_gap_s", 1.5),
                on_frac=kd.get("on_frac", 0.33),
                ocr_offset=kd.get("ocr_offset_s", 0.5),
                merge_confirm_s=kd.get("merge_confirm_s", 10.0),
                death_scan_s=kd.get("death_scan_s", 5.0),
                death_scan_fps=kd.get("death_scan_fps", 4.0))

        if templates:
            print("  vision : kills / mises à terre (templates)...")
            events += detect_visual_events(
                v, templates, tuple(cfg["vision"]["search_region"]),
                threshold=cfg["vision"]["threshold"],
                sample_fps=cfg["vision"]["sample_fps"], fps=info["fps"])
        if use_victory:
            events += detect_victory(
                v, tuple(cfg["vision"]["victory_region"]), fps=info["fps"])

        env = None
        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / "a.wav"
            extract_audio(v, wav, sr=cfg["audio"]["sr"])
            # Calculée ICI, tant que le wav existe : le dossier temporaire disparaît
            # à la sortie du bloc, et `build_candidates` est appelé après.
            env = energy_envelope(wav, sr=cfg["audio"]["sr"])
            # Les pics audio ne génèrent un extrait que si activés : par défaut les
            # KILLS sont la colonne vertébrale (l'audio ne déclenche pas seul).
            if cfg["audio"].get("use_action_peaks", False):
                events += detect_action_peaks(
                    wav, v, sr=cfg["audio"]["sr"],
                    percentile=cfg["audio"]["percentile"],
                    min_gap=cfg["audio"]["min_gap_s"], env=env)
            if not args.no_voice:
                print("  voix : transcription (whisper)...")
                segs, sev = transcribe_voice(
                    wav, v, model_size=cfg["audio"]["whisper_model"],
                    language=cfg["audio"].get("language"))
                if segs:
                    speech_by_video[str(v)] = segs
                    events += sev

        # ponytail: `beats` reste vide, et ce n'est PAS un oubli. Les beats renvoyés par
        # analyze_music sont en temps MUSIQUE ; les fins de clip sont en temps VIDÉO.
        # Les rapprocher ici callerait des coupes sur des instants qui n'ont aucun
        # rapport avec ce que le spectateur entendra. Le seul endroit correct est
        # l'assemblage, où l'offset de chaque clip dans la piste est connu.
        # `cutting.snap_to_beat` porte déjà la garantie A4 (<= 100 ms, jamais plus
        # tard) et est le seul chemin : le jour où l'assemblage l'appelle, la règle
        # est déjà écrite et testée.
        cands = build_candidates(events, info["duration"], cfg, env=env)
        print(f"  → {len(cands)} moments candidats")
        all_cands += cands

    # On n'abandonne QUE s'il n'y a vraiment rien à monter. `--add` et `--first` sont
    # l'échappatoire quand la détection rate un moment : les ignorer ici les rendait
    # inutilisables dans le seul cas où on les sort — et le message conseillait de
    # baisser un seuil alors que l'utilisateur a déjà dit quoi garder.
    if not all_cands and not args.add and not args.first:
        raise SystemExit("Aucun moment détecté. Baisse audio.percentile, ajoute des "
                         "templates, ou force un segment avec --add / --first.")

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

    # `--zoom` et `--sfx` se calent sur les KILLS (`c.kill_times`). Sans kill détecté,
    # ils ne font rien — et ne le disaient pas : on passait l'option, le rendu sortait
    # inchangé, sans un mot. Vérifié le 15/08 : sortie au hash IDENTIQUE avec et sans
    # `--zoom`. `--beat-fx`, lui, se cale sur la musique et marche sans aucun kill.
    beat_fx_actif = bool(args.beat_fx and music and do_zoom)
    sans_kill = not any(getattr(c, "kill_times", None) for c in selected)
    # `--beat-fx` fournit ses propres centres depuis la musique : dans ce cas le zoom
    # agit malgré l'absence de kills, et avertir serait faux.
    inertes = [n for n, on in (("--zoom", do_zoom and not beat_fx_actif),
                               ("--sfx", do_sfx)) if on]
    if sans_kill and inertes:
        print(f"  ⚠ {' et '.join(inertes)} sans effet : aucun kill détecté dans les "
              f"extraits retenus (ces effets se calent sur les kills). "
              f"--beat-fx, lui, suit la musique.")

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
        build_montage(selected, music, out_path, cfg_fmt, speech_by_video=speech,
                      mute_gameplay=mute, zoom=do_zoom, sfx=do_sfx, layout=args.layout,
                      transitions=args.transitions, beat_fx=args.beat_fx)
        print(f"   ✓ {out_path}")

    from wzmontage.killdetect import degradations
    print(final_report(degradations()))


if __name__ == "__main__":
    main()
