"""Structures de données partagées."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Set


@dataclass
class Event:
    """Un événement détecté à un instant donné d'une vidéo."""
    video: str
    t: float
    type: str          # 'kill' | 'knock' | 'elim' | 'victory' | 'action' | 'speech'
    conf: float = 1.0


@dataclass
class SpeechSegment:
    """Un passage parlé transcrit (prox chat, équipe, etc.)."""
    video: str
    start: float
    end: float
    text: str = ""


@dataclass
class Candidate:
    """Un moment candidat = un cluster d'événements -> un extrait potentiel."""
    video: str
    start: float
    end: float
    score: float = 0.0
    n_kills: int = 0
    has_victory: bool = False
    has_speech: bool = False
    kinds: Set[str] = field(default_factory=set)
    crop: str | None = None      # crop ffmpeg "w:h:x:y" appliqué avant le formatage (ex: intro casteurs)
    speed: float = 1.0           # 1.0 = normal ; >1 = accéléré (gameplay)
    is_intro: bool = False       # segment d'intro (casteurs) : PAS de musique dessus, audio original gardé
    kill_times: list = field(default_factory=list)  # instants (clip time) des kills du cluster -> effets fx

    @property
    def duration(self) -> float:
        return self.end - self.start
