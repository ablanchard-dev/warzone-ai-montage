"""Analyse de la piste audio mélangée (jeu + Discord + voix ennemies).

- Pics d'action (tirs/explosions) via librosa : signal de soutien.
- Transcription voix via faster-whisper (optionnel) : récupère les passages
  parlés (prox chat, derniers mots, réactions) + le texte pour les sous-titres.
  Le filtre VAD de whisper ignore une bonne partie des bruits de jeu.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import numpy as np

from .models import Event, SpeechSegment
from .utils import run


def extract_audio(video_path, wav_path, sr: int = 16000) -> None:
    run(["ffmpeg", "-y", "-i", str(video_path),
         "-vn", "-ac", "1", "-ar", str(sr), str(wav_path)])


def detect_action_peaks(wav_path, video_path, sr: int = 16000, hop: int = 512,
                        percentile: float = 93, min_gap: float = 3.0) -> List[Event]:
    import librosa

    y, _sr = librosa.load(str(wav_path), sr=sr, mono=True)
    if y.size == 0:
        return []
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop)
    thr = float(np.percentile(rms, percentile))
    peak = float(rms.max()) + 1e-9

    events: List[Event] = []
    last = -1e9
    for i in range(1, len(rms) - 1):
        if rms[i] >= thr and rms[i] >= rms[i - 1] and rms[i] >= rms[i + 1]:
            t = float(times[i])
            if t - last >= min_gap:
                events.append(Event(str(video_path), t, "action", float(rms[i] / peak)))
                last = t
    return events


def transcribe_voice(wav_path, video_path, model_size: str = "base",
                     language: str | None = None
                     ) -> Tuple[List[SpeechSegment], List[Event]]:
    """Transcrit la voix. Renvoie (segments, events 'speech'). Vide si faster-whisper absent."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return [], []

    try:
        model = WhisperModel(model_size, device="auto", compute_type="int8")
    except Exception:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")

    try:
        segments, _info = model.transcribe(str(wav_path), language=language, vad_filter=True)
        segments = list(segments)
    except Exception:
        segments, _info = model.transcribe(str(wav_path), language=language)
        segments = list(segments)

    segs: List[SpeechSegment] = []
    events: List[Event] = []
    for s in segments:
        text = (s.text or "").strip()
        if not text:
            continue
        segs.append(SpeechSegment(str(video_path), float(s.start), float(s.end), text))
        events.append(Event(str(video_path), float(s.start), "speech", 1.0))
    return segs, events
