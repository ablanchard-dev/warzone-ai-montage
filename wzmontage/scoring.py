"""Notation des moments et sélection globale (toutes vidéos confondues).

Logique inspirée des moteurs existants : on récompense la DENSITÉ d'action
(multikills, 2v1/3v1, squad wipes), la victoire, et la voix collée à un kill
(les "derniers mots" / réactions = cœur du contenu prox chat).
"""
from __future__ import annotations

from typing import List

from .models import Candidate, Event

KILLY = {"kill", "knock", "elim"}
KILL_VALUE = {"elim": 1.0, "kill": 1.0, "knock": 0.6}


def build_candidates(events: List[Event], video_duration: float, cfg: dict) -> List[Candidate]:
    sc = cfg["scoring"]
    ed = cfg["editing"]
    ev = sorted(events, key=lambda e: e.t)

    # Regroupe les événements proches en clusters
    clusters = []
    for e in ev:
        if clusters and e.t - clusters[-1]["raw_end"] <= sc["merge_gap_s"]:
            c = clusters[-1]
            c["raw_end"] = e.t
            c["events"].append(e)
        else:
            clusters.append({"raw_start": e.t, "raw_end": e.t, "events": [e]})

    cands: List[Candidate] = []
    for c in clusters:
        kinds = {e.type for e in c["events"]}
        n_kills = sum(1 for e in c["events"] if e.type in KILLY)
        kill_score = sum(KILL_VALUE.get(e.type, 0.0) for e in c["events"])
        has_victory = "victory" in kinds
        has_speech = "speech" in kinds

        score = kill_score * sc["kill_weight"]
        if n_kills >= 4:
            score *= sc["wipe_multiplier"]
        elif n_kills >= 3:
            score *= sc["multikill_multiplier"]
        elif n_kills >= 2:
            score *= 1.3

        # Bonus de densité : beaucoup de kills en peu de temps
        span = max(0.5, c["raw_end"] - c["raw_start"])
        score *= 1.0 + min(1.0, n_kills / span)

        # Clusters basés seulement sur l'audio (sans détection vision)
        if kill_score == 0 and "action" in kinds:
            score += sc["audio_only_weight"] * len(c["events"])

        # Voix + kill = "derniers mots" / réaction d'équipe
        if has_speech and n_kills >= 1:
            score *= sc["voice_kill_multiplier"]
        elif has_speech:
            score += sc["speech_weight"]

        if has_victory:
            score += sc["victory_bonus"]

        # Bornes adaptatives + clamp
        start = max(0.0, c["raw_start"] - ed["lead_in_s"])
        end = min(video_duration, c["raw_end"] + ed["lead_out_s"])
        if end - start < ed["min_clip_s"]:
            end = min(video_duration, start + ed["min_clip_s"])
        if end - start > ed["max_clip_s"]:
            end = start + ed["max_clip_s"]

        cands.append(Candidate(c["events"][0].video, start, end, score,
                               n_kills, has_victory, has_speech, kinds))
    return cands


def select_global(cands: List[Candidate], cfg: dict) -> List[Candidate]:
    """Garde les meilleurs moments de toutes les vidéos jusqu'à la durée cible.

    La structure n'est PAS imposée :
      - ending = auto       -> finit sur le moment le plus fort (pas forcément une victoire)
                 victory    -> finit sur une victoire si elle existe
                 none       -> aucun final imposé
      - order  = chronological -> ordre chrono (par vidéo puis temps) [défaut]
                 build_up      -> montée en puissance (score croissant)
                 hook          -> gros moment en ouverture, puis montée
    """
    ed = cfg["editing"]
    min_total, max_total = ed["min_total_seconds"], ed["max_total_seconds"]
    ending = ed.get("ending", "auto")
    order = ed.get("order", "chronological")

    ranked = sorted(cands, key=lambda c: c.score, reverse=True)
    chosen: List[Candidate] = []
    total = 0.0
    for c in ranked:
        if total + c.duration > max_total:
            if total >= min_total:
                break
            continue
        chosen.append(c)
        total += c.duration
    if not chosen:
        return []

    # Choix du final (climax), sans forcer un type de moment
    finale = None
    if ending == "victory":
        vics = [c for c in chosen if c.has_victory]
        finale = max(vics or chosen, key=lambda c: c.score)
    elif ending == "auto":
        finale = max(chosen, key=lambda c: c.score)
    # ending == "none" -> pas de final réservé

    body = [c for c in chosen if c is not finale]
    if order == "chronological":
        body.sort(key=lambda c: (c.video, c.start))
    elif order == "hook":
        body.sort(key=lambda c: c.score)
        if body:
            body = [body.pop()] + body      # le plus fort restant en ouverture
    else:  # build_up
        body.sort(key=lambda c: c.score)

    return body + ([finale] if finale else [])
