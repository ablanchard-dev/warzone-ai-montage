"""Notation des moments et sélection globale (toutes vidéos confondues).

Logique inspirée des moteurs existants : on récompense la DENSITÉ d'action
(multikills, 2v1/3v1, squad wipes), la victoire, et la voix collée à un kill
(les "derniers mots" / réactions = cœur du contenu prox chat).
"""
from __future__ import annotations

from typing import List

from .cutting import excise_dead_gaps, resolve_end, snap_to_beat
from .models import Candidate, Event

KILLY = {"kill", "knock", "elim"}
KILL_VALUE = {"elim": 1.0, "kill": 1.0, "knock": 0.6}


def build_candidates(events: List[Event], video_duration: float, cfg: dict,
                     env=None, beats=()) -> List[Candidate]:
    """`env` = enveloppe d'énergie (audio.energy_envelope), `beats` = temps de la musique.

    Les deux sont OPTIONNELS et le résultat reste correct sans eux : on retombe sur le
    lead-out fixe et sur un clip d'un seul tenant. Un pipeline sans audio ne doit pas
    rendre des clips faux, il doit rendre des clips moins fins.

    Note : `cutting.compute_segments` compose C4+A4+C5 d'une traite, mais ici les
    clamps min/max et le death-trim s'intercalent ENTRE la fin et l'excision. On appelle
    donc les trois briques dans le même ordre plutôt que la composition toute faite.
    """
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

        # Bornes adaptatives + clamp. La fin du lead-out se base sur la dernière ACTION
        # (kill/voix…), pas sur une éventuelle mort, sinon on rallongerait jusqu'à elle.
        non_death = [e.t for e in c["events"] if e.type != "death"]
        action_end = max(non_death) if non_death else c["raw_end"]
        # Symétrique de la ligne au-dessus, qui manquait : le DÉBUT doit lui aussi
        # ignorer les morts. Cas réel : tu te fais mettre à terre, tu te relèves et
        # tu tues 8 s plus tard -> même cluster (fenêtre merge_gap_s = 15 s) ->
        # `raw_start` valait ta mise à terre, et le clip S'OUVRAIT DESSUS.
        action_start = min(non_death) if non_death else c["raw_start"]
        death_guard = ed.get("death_guard_s", 0.4)
        start = max(0.0, action_start - ed["lead_in_s"])
        # C4 : la fin est ancrée sur la fin RÉELLE de l'action (retard du bandeau
        # retiré, chute d'énergie audio), plus sur `action_end + délai fixe`.
        end = resolve_end(action_end, env, cfg, video_duration)
        end = snap_to_beat(end, beats, cfg)
        if end - start < ed["min_clip_s"]:
            # On rallonge par le DÉBUT, pas par la fin. Rallonger la fin remettrait
            # exactement le temps mort que C4 vient de supprimer : un clip d'un seul
            # kill avec lead_in 3 s finissait à start+4 s, soit 1,4 s après le kill,
            # au-dessus du plafond A1 de 1,2 s. Trouvé par le test de câblage, pas
            # par relecture -- le clamp est plus vieux que la règle qu'il cassait.
            manque = ed["min_clip_s"] - (end - start)
            # Plancher : jamais avant une mort qui précède l'action. La règle d'Alex
            # (« ne me montre pas en train de crever ») prime sur la durée minimale ;
            # sans ce plancher, rallonger par le début rouvrait le clip sur sa mise à
            # terre — le défaut même que le death-trim existe pour empêcher.
            morts_avant = [e.t for e in c["events"]
                           if e.type == "death" and e.t < action_start]
            plancher = max(morts_avant) + death_guard if morts_avant else 0.0
            start = max(plancher, start - manque)
            if end - start < ed["min_clip_s"]:      # bloqué par le plancher : plus le choix
                end = min(video_duration, start + ed["min_clip_s"])
        if end - start > ed["max_clip_s"]:
            end = start + ed["max_clip_s"]

        # DEATH-TRIM (règle Alex : "tjr le clip où je meurs") — borne DURE appliquée APRÈS
        # les clamps : le segment se termine AVANT que tu sois à terre/mort. On coupe
        # `death_guard_s` avant l'apparition de l'état "à terre". Si ça rend le clip court,
        # tant pis : mieux vaut court que de te montrer en train de crever.
        deaths_after = sorted(e.t for e in c["events"] if e.type == "death" and e.t > start)
        if deaths_after:
            end = min(end, deaths_after[0] - death_guard)

        kill_times = [e.t for e in c["events"] if e.type in KILLY and e.t < end]
        # C5 : APRÈS les clamps et le death-trim, sinon l'excision travaillerait sur
        # une fenêtre qui contient encore du temps mort de fin, et le prendrait pour
        # un trou interne.
        segs = excise_dead_gaps(start, end, [e.t for e in c["events"]], env, cfg)
        cands.append(Candidate(c["events"][0].video, start, end, score,
                               n_kills, has_victory, has_speech, kinds,
                               kill_times=kill_times,
                               segments=segs if len(segs) > 1 else []))
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
