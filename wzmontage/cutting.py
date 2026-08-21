"""Où couper — C4 et C5 du cahier des charges, en fonctions PURES.

Rien ici ne touche ffmpeg ni le disque. C'est délibéré : ces règles décident du
sort de chaque clip, donc elles doivent pouvoir être mises en défaut sans rendre
une vidéo. Le rendu d'un montage coûte des minutes ; un test doit coûter des
millisecondes, sinon personne ne le lance et la règle dérive en silence.

L'enveloppe d'énergie est un couple `(times, vals)`, vals normalisées 0..1,
telles que `audio.energy_envelope` les produit.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

Envelope = Tuple[Sequence[float], Sequence[float]]


def _window_peak(env: Envelope, t0: float, t1: float) -> float:
    times, vals = env
    inside = [v for tt, v in zip(times, vals) if t0 <= tt <= t1]
    return max(inside) if inside else 0.0


def quiet_after(env: Optional[Envelope], t0: float, until: float, cfg: dict,
                look_back: float = 2.0) -> Optional[float]:
    """Premier instant >= t0 où l'énergie retombe ET Y RESTE — la fin des tirs.

    Le seuil est RELATIF au pic de l'action elle-même, jamais absolu : un combat au
    pistolet et un combat à l'explosif n'ont pas le même niveau, et un seuil fixe
    couperait le premier en plein milieu tout en ne coupant jamais le second.

    Renvoie None si l'énergie ne retombe pas avant `until` — l'appelant garde alors
    sa borne dure. None veut dire « je ne sais pas », jamais « coupe tout de suite ».
    """
    if not env:
        return None
    times, vals = env
    if not times:
        return None
    ed = cfg["editing"]
    ratio = ed.get("quiet_ratio", 0.25)
    hold = ed.get("quiet_hold_s", 0.35)

    ref = _window_peak(env, t0 - look_back, t0)
    if ref <= 0.0:
        return None
    thr = ref * ratio

    run_start: Optional[float] = None
    for tt, v in zip(times, vals):
        if tt < t0:
            continue
        if tt > until:
            break
        if v <= thr:
            if run_start is None:
                run_start = tt
            elif tt - run_start >= hold:
                return run_start
        else:
            run_start = None
    return None


def resolve_end(action_end: float, env: Optional[Envelope], cfg: dict,
                video_duration: float) -> float:
    """C4 — la fin est ancrée sur la fin RÉELLE de l'action, pas sur un délai fixe.

    `action_end` est l'instant du BANDEAU, qui s'affiche après le kill. On retire ce
    retard AVANT de compter la respiration : sinon chaque clip traîne le retard du
    bandeau EN PLUS du lead-out, et le temps mort qu'on croit régler à 1,2 s en vaut
    1,6 dans la vidéo livrée.

    Puis on laisse `lead_out_min_s` de respiration — le temps de voir le compteur 💀
    monter, c'est la récompense du spectateur — et jamais plus de `lead_out_s`.
    """
    ed = cfg["editing"]
    lag = ed.get("banner_lag_s", 0.4)
    lo_min = ed.get("lead_out_min_s", 1.0)
    lo_max = ed.get("lead_out_s", 1.2)

    anchor = action_end - lag
    hard = anchor + lo_max
    q = quiet_after(env, anchor, hard, cfg)
    end = hard if q is None else min(hard, max(anchor + lo_min, q + lo_min))
    return min(video_duration, end)


def snap_to_beat(end: float, beats: Sequence[float], cfg: dict) -> float:
    """A4 — le beat ne déplace la fin que de <= beat_snap_max_s, et JAMAIS vers le tard.

    Repousser la fin pour tomber sur un temps rallongerait le temps mort que C4 vient
    précisément de supprimer. Le beat est un ornement, la fin de l'action est la
    règle : en cas de conflit, c'est l'ornement qui cède.
    """
    if not beats:
        return end
    mx = cfg["editing"].get("beat_snap_max_s", 0.1)
    earlier = [b for b in beats if end - mx <= b <= end]
    return max(earlier) if earlier else end


def excise_dead_gaps(start: float, end: float, event_times: Sequence[float],
                     env: Optional[Envelope], cfg: dict) -> List[Tuple[float, float]]:
    """C5 — un trou mort INTERNE est retiré, et les sous-segments actifs recollés.

    Cas réel : deux fights dans le même cluster, séparés par dix secondes où il se
    plaque derrière un rocher. Couper en deux clips casse la continuité ; garder le
    trou fait décrocher. On excise le trou et on recolle : UN clip, sans temps mort.

    Un trou n'est mort que s'il est SILENCIEUX **et** sans aucun événement. L'énergie
    seule ne suffit pas : une réanimation se fait en silence mais porte un event, et
    se faire relever fait partie de l'action.

    Renvoie toujours au moins un segment — jamais une liste vide, qui supprimerait le
    clip sans que personne ne l'ait décidé.
    """
    whole = [(start, end)]
    if not env:
        return whole
    times, vals = env
    ed = cfg["editing"]
    gap_min = ed.get("dead_gap_min_s", 3.5)
    ratio = ed.get("quiet_ratio", 0.25)
    pad = ed.get("dead_gap_pad_s", 0.4)
    if not times or end - start <= gap_min:
        return whole

    ref = _window_peak(env, start, end)
    if ref <= 0.0:
        return whole
    thr = ref * ratio
    evs = [t for t in event_times if start <= t <= end]

    quiet_runs: List[Tuple[float, float]] = []
    run_start: Optional[float] = None
    for tt, v in zip(times, vals):
        if tt < start or tt > end:
            continue
        if v <= thr:
            if run_start is None:
                run_start = tt
        elif run_start is not None:
            quiet_runs.append((run_start, tt))
            run_start = None
    if run_start is not None:
        quiet_runs.append((run_start, end))

    dead: List[Tuple[float, float]] = []
    for g0, g1 in quiet_runs:
        # On rend `pad` de chaque côté : la queue d'un tir et l'amorce du suivant font
        # partie de l'action, les couper au ras s'entend comme un défaut de montage.
        g0, g1 = g0 + pad, g1 - pad
        if g1 - g0 < gap_min:
            continue
        if any(g0 <= e <= g1 for e in evs):
            continue
        dead.append((g0, g1))
    if not dead:
        return whole

    segs: List[Tuple[float, float]] = []
    cur = start
    for g0, g1 in dead:
        if g0 > cur:
            segs.append((cur, g0))
        cur = max(cur, g1)
    if end > cur:
        segs.append((cur, end))
    segs = [s for s in segs if s[1] - s[0] > 0.2]
    return segs or whole


def compute_segments(action_end: float, start: float, event_times: Sequence[float],
                     env: Optional[Envelope], cfg: dict, video_duration: float,
                     beats: Sequence[float] = ()) -> List[Tuple[float, float]]:
    """C4 + C5 en une passe : la fonction que le cahier des charges nomme.

    Ordre imposé : on ferme d'abord la fin sur l'action (C4), on la cale
    éventuellement sur un beat (A4), PUIS on excise les trous (C5). L'inverse ferait
    travailler l'excision sur une fenêtre qui contient encore le temps mort final, et
    ce trou-là passerait pour un trou interne.
    """
    end = resolve_end(action_end, env, cfg, video_duration)
    end = snap_to_beat(end, beats, cfg)
    if end <= start:
        floor = cfg["editing"].get("min_clip_s", 4.0)
        return [(start, min(video_duration, start + floor))]
    return excise_dead_gaps(start, end, event_times, env, cfg)
