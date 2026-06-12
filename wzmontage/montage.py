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
             speed: float = 1.0, crop: str | None = None) -> None:
    fc = _vfilter(w, h, fps, vertical, crop=crop, speed=speed)
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}", "-i", str(video), "-t", f"{dur:.3f}",
        "-filter_complex", fc,
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-ar", "48000", "-ac", "2", "-r", str(fps),
    ]
    if speed and speed != 1.0:
        cmd += ["-filter:a", f"atempo={speed}"]      # garde l'audio synchro avec la vidéo accélérée
    cmd += [str(out)]
    run(cmd)


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
                  mute_gameplay: bool = False):
    out = cfg["output"]
    w, h, fps = out["width"], out["height"], out["fps"]
    vertical = h > w
    want_subs = bool(out.get("subtitles")) and speech_by_video

    # Beat-sync : on quantifie la durée de chaque extrait sur la grille des temps
    # de la musique → les coupes tombent sur le beat (feel "monté", pas "collé").
    beat = None
    if music_path and cfg["editing"].get("beat_sync", True):
        try:
            bpm = analyze_music(music_path)["bpm"]
            if 40.0 <= bpm <= 220.0:
                beat = 60.0 / bpm
        except Exception:
            beat = None

    tmp = Path(tempfile.mkdtemp(prefix="wz_montage_"))
    parts: List[Path] = []
    srt_lines = []
    offset = 0.0
    intro_offset = 0.0           # durée des segments d'intro = moment où la musique démarre

    for i, c in enumerate(selected):
        part = tmp / f"clip_{i:03d}.mp4"
        dur = c.duration
        if beat:
            dur = max(beat, round(c.duration / beat) * beat)
        _extract(c.video, c.start, dur, part, w, h, fps, vertical,
                 speed=c.speed, crop=c.crop)
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

    # Concaténation (même codec partout -> copie)
    listfile = tmp / "list.txt"
    listfile.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
    concat = tmp / "concat.mp4"
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
            "-vf", f"subtitles={srt}:force_style='Fontsize=18,Outline=2,Alignment=2'",
            "-c:a", "copy", str(output_path),
        ])
    else:
        run(["ffmpeg", "-y", "-i", str(cur), "-c", "copy", str(output_path)])
    return output_path
