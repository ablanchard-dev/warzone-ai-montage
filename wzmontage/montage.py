"""Assemblage du montage final.

Philosophie Warzone : on GARDE l'audio du jeu (voix / prox chat) bien présent,
et on ajoute la musique en FOND léger (post-prod). Coupes franches, victoire en
clôture. Option format vertical 9:16 (fond flou) + sous-titres du prox chat.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Dict, List

from .models import Candidate, SpeechSegment
from .overlays import _escape_path
from .utils import ffprobe, run


def analyze_music(music_path) -> dict:
    import librosa
    import numpy as np

    y, sr = librosa.load(str(music_path), sr=None, mono=True)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    return {"bpm": float(np.atleast_1d(tempo)[0]), "beats": [float(b) for b in beats]}


def _vfilter(w: int, h: int, fps: int, vertical: bool,
             crop: str | None = None, speed: float = 1.0) -> str:
    pre = f"crop={crop}," if crop else ""               # crop optionnel (ex: facecams casteurs)
    sp = f",setpts=PTS/{speed}" if speed and speed != 1.0 else ""   # accélération
    if vertical:
        # fond flou plein cadre + vidéo centrée (look TikTok/Shorts)
        return (
            f"[0:v]{pre}split=2[v0][v1];"
            f"[v0]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},boxblur=20:5[bg];"
            f"[v1]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={fps},format=yuv420p{sp}[v]"
        )
    return (
        f"[0:v]{pre}scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p{sp}[v]"
    )


def _extract(video, start: float, dur: float, out, w, h, fps, vertical,
             speed: float = 1.0, crop: str | None = None, spec: dict | None = None) -> None:
    if spec:
        from . import compositor
        src_w, src_h, src_fps = compositor._probe_dims(str(video))
        fc, _ = compositor.build_segment_filtergraph(spec, src_w, src_h, fps, src_fps=src_fps)
    else:
        fc = _vfilter(w, h, fps, vertical, crop=crop, speed=speed)
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}", "-i", str(video), "-t", f"{dur:.3f}",
        "-filter_complex", fc,
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "48000", "-ac", "2", "-r", str(fps),
    ]
    if speed and speed != 1.0:
        cmd += ["-filter:a", f"atempo={speed}"]      # garde l'audio synchro avec la vidéo accélérée
    cmd += [str(out)]
    run(cmd)


_PUNCH = Path(__file__).resolve().parent.parent / "assets" / "sfx" / "punch.wav"


def _add_sfx(part, rel_times, tmp, i, gain: float = 3.5):
    """Mixe le SFX punch sur l'audio du segment à chaque kill (rel_times en s).
    Post-étape isolée : vidéo COPIÉE (rapide), n'altère pas le rendu vidéo. OPTIONNEL.
    Renvoie le nouveau chemin (ou `part` inchangé si pas de SFX dispo)."""
    if not rel_times or not _PUNCH.exists():
        return part
    n = len(rel_times)
    split = f"[1:a]asplit={n}" + "".join(f"[s{k}]" for k in range(n)) + ";"
    delays = "".join(
        f"[s{k}]adelay={int(t * 1000)}|{int(t * 1000)},volume={gain}[p{k}];"
        for k, t in enumerate(rel_times))
    mix_in = "[0:a]" + "".join(f"[p{k}]" for k in range(n))
    fc = split + delays + f"{mix_in}amix=inputs={n + 1}:duration=first:normalize=0[a]"
    out = tmp / f"clip_{i:03d}_sfx.mp4"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", str(part), "-i", str(_PUNCH), "-filter_complex", fc,
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", str(out)])
    return out


def _concat_xfade(parts, out, tdur: float = 0.3, kind: str = "fade"):
    """Concatène les segments avec transition xfade (vidéo) + acrossfade (audio) entre
    chaque. OPTIONNEL (sinon concat franc, chemin par défaut). Tous les parts ont mêmes
    dims/fps (garanti par le rendu). Renvoie le chemin de sortie."""
    parts = [str(p) for p in parts]
    if len(parts) == 1:
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-i", parts[0], "-c", "copy", str(out)])
        return out
    durs = [ffprobe(p)["duration"] for p in parts]
    inputs = []
    for p in parts:
        inputs += ["-i", p]
    vchain, achain = [], []
    prev_v, prev_a = "[0:v]", "[0:a]"
    cum = durs[0]
    for k in range(1, len(parts)):
        offset = max(0.0, cum - tdur)
        vlab, alab = f"[vx{k}]", f"[ax{k}]"
        vchain.append(f"{prev_v}[{k}:v]xfade=transition={kind}:duration={tdur}:"
                      f"offset={offset:.3f}{vlab}")
        achain.append(f"{prev_a}[{k}:a]acrossfade=d={tdur}{alab}")
        prev_v, prev_a = vlab, alab
        cum += durs[k] - tdur
    fc = ";".join(vchain + achain)
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs,
         "-filter_complex", fc, "-map", prev_v, "-map", prev_a,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-movflags", "+faststart", str(out)])
    return out


def _ts(x: float) -> str:
    h = int(x // 3600); m = int((x % 3600) // 60); s = int(x % 60)
    ms = int(round((x - int(x)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _to_srt(lines) -> str:
    out = []
    for i, (s, e, text) in enumerate(lines, 1):
        out.append(f"{i}\n{_ts(s)} --> {_ts(e)}\n{text}\n")
    return "\n".join(out)


def build_montage(selected: List[Candidate], music_path, output_path, cfg: dict,
                  speech_by_video: Dict[str, List[SpeechSegment]] | None = None,
                  mute_gameplay: bool = False, zoom: bool = False, sfx: bool = False,
                  layout: str = "blurfill", transitions: str | None = None,
                  beat_fx: bool = False):
    out = cfg["output"]
    w, h, fps = out["width"], out["height"], out["fps"]
    vertical = h > w
    want_subs = bool(out.get("subtitles")) and speech_by_video

    # Beat-sync : on CALE les coupes sur les beats de la musique (feel "monté", pas "collé").
    # beat_fx (option) = en plus, des punchs de zoom DOUX sur le beat (pulse au tempo).
    beat = None
    beats: List[float] = []
    music_total = None
    if music_path and (cfg["editing"].get("beat_sync", True) or beat_fx):
        try:
            info = analyze_music(music_path)
            bpm = info["bpm"]
            beats = info.get("beats", [])
            if 40.0 <= bpm <= 220.0:
                beat = 60.0 / bpm
        except Exception:
            beat, beats = None, []
        try:
            music_total = ffprobe(str(music_path))["duration"]
        except Exception:
            music_total = None
    beat_peak = cfg["editing"].get("beat_fx_peak", 1.08)     # pic beat (doux) vs 1.18 kills
    beat_stride = int(cfg["editing"].get("beat_fx_stride", 2))  # 1 beat sur N (anti sur-zoom)
    min_clip = cfg["editing"].get("min_clip_s", 4.0)
    # Grille des beats en temps musique-local (avec boucles si le montage dépasse la musique).
    beats_timeline: List[float] = []
    if beats:
        total_est = sum(c.duration for c in selected) + 2.0
        if music_total and music_total > 0:
            k = 0
            while k * music_total <= total_est and k <= 200:
                beats_timeline.extend(k * music_total + b for b in beats)
                k += 1
        else:
            beats_timeline = list(beats)
        beats_timeline.sort()

    tmp = Path(tempfile.mkdtemp(prefix="wz_montage_"))
    parts: List[Path] = []
    srt_lines = []
    offset = 0.0
    intro_offset = 0.0           # durée des segments d'intro = moment où la musique démarre

    for i, c in enumerate(selected):
        part = tmp / f"clip_{i:03d}.mp4"
        dur = c.duration
        if beats_timeline and not c.is_intro:
            # CALER LA COUPE SUR LE BEAT (phase-aware) : la FIN du segment tombe sur le plus
            # grand beat <= fin naturelle (jamais au-delà → respecte death-trim/max_clip), et
            # >= min_clip. Comme les segments sont contigus, chaque coupe tombe sur un beat.
            mlt_target = (offset + c.duration) - intro_offset
            mlt_lo = (offset + min_clip) - intro_offset
            snapped = [tb for tb in beats_timeline if mlt_lo <= tb <= mlt_target]
            if snapped:
                dur = (max(snapped) + intro_offset) - offset
        # Effets OPTIONNELS et INDÉPENDANTS (zoom / sfx / layout) — rien d'imposé.
        rel = []
        if not c.is_intro and c.kill_times:
            # Le bandeau "ENNEMI ABATTU" s'affiche ~0.4s APRÈS le kill (gars déjà couché,
            # vue déjà bougée) -> on tire les effets plus tôt pour tomber sur le TIR.
            kill_lead = 0.4
            rel = [round(max(0.0, (kt - c.start) / max(c.speed, 1e-6) - kill_lead), 3)
                   for kt in c.kill_times if c.start <= kt <= c.end]

        # Beat-FX (option) : punchs de zoom DOUX calés sur le beat de la musique tombant
        # DANS ce segment (le clip "pulse" au tempo). Temps de beat (timeline) = début de
        # la musique (intro_offset) + temps-beat + boucles ; ramené en temps-local segment.
        # On en garde 1 sur `beat_stride` et on évite les doublons avec les punchs de kill.
        beat_pts = []
        if beat_fx and zoom and beats and music_total and not c.is_intro:
            kmax = int((offset + dur) / music_total) + 2
            for k in range(kmax):
                for j in range(0, len(beats), max(1, beat_stride)):
                    tau = (intro_offset + beats[j] + k * music_total) - offset
                    if 0.12 <= tau <= dur - 0.12 and all(abs(tau - r) > 0.20 for r in rel):
                        beat_pts.append(round(tau, 3))

        centers = rel + beat_pts
        peaks = [1.18] * len(rel) + [beat_peak] * len(beat_pts)
        spec = None
        if (zoom and centers) or layout == "facecam-top":   # compositeur si zoom OU layout spécial
            fmt = ("facecam_top" if layout == "facecam-top"
                   else "vertical" if vertical else "fullscreen")
            spec = {"format": fmt, "speed": c.speed}
            if zoom and centers:
                spec["zoom_punch"] = centers
                spec["zoom_peaks"] = peaks
        _extract(c.video, c.start, dur, part, w, h, fps, vertical,
                 speed=c.speed, crop=c.crop, spec=spec)
        if sfx and rel:                      # SFX punch (option indépendante)
            part = _add_sfx(part, rel, tmp, i)
        real = ffprobe(part)["duration"]
        if c.is_intro:
            intro_offset += real
        if want_subs:
            for seg in speech_by_video.get(c.video, []):
                if seg.end <= c.start or seg.start >= c.end:
                    continue
                s = max(seg.start, c.start) - c.start + offset
                e = min(seg.end, c.end) - c.start + offset
                srt_lines.append((s, e, seg.text))
        parts.append(part)
        offset += real

    # Concaténation : transitions xfade (optionnel) OU concat franc (défaut, copie).
    concat = tmp / "concat.mp4"
    if transitions and len(parts) > 1:
        _concat_xfade(parts, concat, tdur=0.3, kind=transitions)
    else:
        listfile = tmp / "list.txt"
        listfile.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(listfile), "-c", "copy", str(concat)])
    total = ffprobe(concat)["duration"]

    cur = concat
    if music_path:
        fade = min(2.0, total / 4.0)
        mvol = cfg["editing"]["music_volume"]
        gvol = cfg["editing"]["game_audio_volume"]
        st_out = max(0.0, total - fade)
        if intro_offset > 0.05:
            # Intro (casteurs) = audio original SEUL, zéro musique (voix distinctes).
            # Gameplay (dès le grappin) = la MUSIQUE démarre PILE, voix du jeu coupée.
            ms = intro_offset
            ms_ms = int(round(ms * 1000))
            fc = (
                f"[0:a]volume='if(lt(t,{ms:.3f}),1,0)':eval=frame[a0];"
                f"[1:a]adelay={ms_ms}|{ms_ms},volume=0.9,"
                f"afade=t=out:st={st_out:.3f}:d={fade:.3f}[a1];"
                f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
            )
        else:
            fc = (
                f"[0:a]volume={gvol}[a0];"
                f"[1:a]volume={mvol},afade=t=out:st={st_out:.3f}:d={fade:.3f}[a1];"
                f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
            )
        mixed = tmp / "mixed.mp4"
        run([
            "ffmpeg", "-y",
            "-i", str(cur),
            "-stream_loop", "-1", "-i", str(music_path),
            "-filter_complex", fc,
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            str(mixed),
        ])
        cur = mixed
    elif mute_gameplay and intro_offset > 0.05:
        # Pas de musique : on coupe l'audio du gameplay (voix du jeu), on garde l'intro casteurs.
        # → clip "muet" prêt à recevoir un vrai son dans TikTok par-dessus.
        gated = tmp / "gated.mp4"
        run(["ffmpeg", "-y", "-i", str(cur),
             "-af", f"volume='if(lt(t,{intro_offset:.3f}),1,0)':eval=frame",
             "-c:v", "copy", "-c:a", "aac", str(gated)])
        cur = gated

    if want_subs and srt_lines:
        srt = tmp / "subs.srt"
        srt.write_text(_to_srt(srt_lines), encoding="utf-8")
        run([
            "ffmpeg", "-y", "-i", str(cur),
            # Le chemin entre DANS le filtre, pas en argument : sur Windows le `C:` et
            # les antislashs étaient avalés par ffmpeg (« Unable to parse option value
            # "UsersblancAppData…" as image size » — mesuré le 15/08). Les sous-titres
            # ne fonctionnaient donc jamais ici. Même échappement que les overlays.
            "-vf", f"subtitles={_escape_path(str(srt))}:"
                   f"force_style='Fontsize=18,Outline=2,Alignment=2'",
            "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(output_path),
        ])
    else:
        run(["ffmpeg", "-y", "-i", str(cur), "-c", "copy", "-movflags", "+faststart", str(output_path)])
    return output_path
