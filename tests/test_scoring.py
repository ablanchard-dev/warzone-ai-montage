"""Tests de la notation et de la sélection globale (wzmontage.scoring)."""
import copy

import pytest

from wzmontage.models import Candidate, Event
from wzmontage.scoring import build_candidates, select_global

CFG = {
    "scoring": {
        "merge_gap_s": 15.0,
        "kill_weight": 1.0,
        "multikill_multiplier": 2.0,
        "wipe_multiplier": 3.0,
        "voice_kill_multiplier": 1.6,
        "speech_weight": 0.4,
        "victory_bonus": 4.0,
        "audio_only_weight": 0.25,
    },
    "editing": {
        "lead_in_s": 2.0,
        "lead_out_s": 1.5,
        "min_clip_s": 4.0,
        "max_clip_s": 30.0,
        "min_total_seconds": 30,
        "max_total_seconds": 120,
        "ending": "auto",
        "order": "build_up",
    },
}


def cfg(**editing_overrides):
    c = copy.deepcopy(CFG)
    c["editing"].update(editing_overrides)
    return c


# --- build_candidates -------------------------------------------------------

def test_empty_events_no_candidates():
    assert build_candidates([], 100.0, CFG) == []


def test_single_elim_creates_one_candidate():
    cands = build_candidates([Event("v", 10.0, "elim")], 100.0, CFG)
    assert len(cands) == 1
    c = cands[0]
    assert c.n_kills == 1
    assert not c.has_victory
    assert not c.has_speech
    assert c.video == "v"


def test_close_events_merge_into_one_cluster():
    # gap 10s <= merge_gap_s 15s -> un seul cluster
    events = [Event("v", 10.0, "elim"), Event("v", 20.0, "elim")]
    cands = build_candidates(events, 100.0, CFG)
    assert len(cands) == 1
    assert cands[0].n_kills == 2


def test_far_events_split_into_two_clusters():
    # gap 20s > merge_gap_s 15s -> deux clusters
    events = [Event("v", 10.0, "elim"), Event("v", 30.0, "elim")]
    cands = build_candidates(events, 100.0, CFG)
    assert len(cands) == 2


def test_events_are_sorted_before_clustering():
    events = [Event("v", 30.0, "elim"), Event("v", 10.0, "elim")]
    cands = build_candidates(events, 100.0, CFG)
    # même résultat que dans l'ordre chronologique : 2 clusters
    assert len(cands) == 2


def test_knock_scores_less_than_elim():
    knock = build_candidates([Event("v", 10.0, "knock")], 100.0, CFG)[0]
    elim = build_candidates([Event("v", 10.0, "elim")], 100.0, CFG)[0]
    assert knock.score < elim.score


def test_wipe_beats_multikill_beats_pair():
    pair = build_candidates(
        [Event("v", 10.0, "elim"), Event("v", 10.5, "elim")], 100.0, CFG)[0]
    triple = build_candidates(
        [Event("v", 10.0, "elim"), Event("v", 10.2, "elim"),
         Event("v", 10.4, "elim")], 100.0, CFG)[0]
    quad = build_candidates(
        [Event("v", 10.0, "elim"), Event("v", 10.1, "elim"),
         Event("v", 10.2, "elim"), Event("v", 10.3, "elim")], 100.0, CFG)[0]
    assert quad.score > triple.score > pair.score


def test_victory_adds_bonus_and_flag():
    no_vic = build_candidates([Event("v", 10.0, "elim")], 100.0, CFG)[0]
    with_vic = build_candidates(
        [Event("v", 10.0, "elim"), Event("v", 10.5, "victory")], 100.0, CFG)[0]
    assert with_vic.has_victory
    assert with_vic.score == pytest.approx(no_vic.score + CFG["scoring"]["victory_bonus"])


def test_speech_with_kill_applies_voice_multiplier():
    kill_only = build_candidates([Event("v", 10.0, "elim")], 100.0, CFG)[0]
    voiced = build_candidates(
        [Event("v", 10.0, "elim"), Event("v", 10.0, "speech")], 100.0, CFG)[0]
    assert voiced.has_speech
    assert voiced.score == pytest.approx(
        kill_only.score * CFG["scoring"]["voice_kill_multiplier"])


def test_speech_without_kill_adds_flat_weight():
    c = build_candidates([Event("v", 10.0, "speech")], 100.0, CFG)[0]
    assert c.n_kills == 0
    assert c.score == pytest.approx(CFG["scoring"]["speech_weight"])


def test_audio_only_cluster_is_scored():
    events = [Event("v", 10.0, "action"), Event("v", 11.0, "action")]
    c = build_candidates(events, 100.0, CFG)[0]
    assert c.n_kills == 0
    assert c.score == pytest.approx(CFG["scoring"]["audio_only_weight"] * 2)


def test_clip_respects_min_duration():
    c = build_candidates([Event("v", 50.0, "elim")], 100.0, CFG)[0]
    assert c.duration == pytest.approx(CFG["editing"]["min_clip_s"])


def test_clip_respects_max_duration():
    # chaîne d'élims espacées de 14s (<= merge_gap) -> un long cluster
    events = [Event("v", t, "elim") for t in (10.0, 24.0, 38.0, 52.0)]
    c = build_candidates(events, 200.0, CFG)[0]
    assert c.duration == pytest.approx(CFG["editing"]["max_clip_s"])


def test_clip_start_never_negative():
    c = build_candidates([Event("v", 0.5, "elim")], 100.0, CFG)[0]
    assert c.start >= 0.0


def test_clip_end_clamped_to_video_duration():
    c = build_candidates([Event("v", 9.0, "elim")], 10.0, CFG)[0]
    assert c.end <= 10.0


# --- select_global ----------------------------------------------------------

def _cands(n, dur=30.0):
    return [Candidate("v", i * 100.0, i * 100.0 + dur, score=float(n - i))
            for i in range(n)]


def test_select_empty_returns_empty():
    assert select_global([], CFG) == []


def test_select_respects_max_total():
    result = select_global(_cands(10), cfg(max_total_seconds=120))
    assert sum(c.duration for c in result) <= 120


def test_select_keeps_at_least_min_total_when_possible():
    result = select_global(_cands(10), cfg(min_total_seconds=30, max_total_seconds=120))
    assert sum(c.duration for c in result) >= 30


def test_select_ending_victory_puts_victory_last():
    cands = [
        Candidate("v", 0.0, 10.0, score=5.0),
        Candidate("v", 20.0, 30.0, score=10.0, has_victory=True),
        Candidate("v", 40.0, 50.0, score=8.0),
    ]
    result = select_global(cands, cfg(ending="victory", order="build_up"))
    assert result[-1].has_victory


def test_select_order_chronological_sorts_by_start():
    cands = [
        Candidate("v", 80.0, 90.0, score=9.0),
        Candidate("v", 10.0, 20.0, score=5.0),
        Candidate("v", 40.0, 50.0, score=7.0),
    ]
    result = select_global(cands, cfg(ending="none", order="chronological"))
    starts = [c.start for c in result]
    assert starts == sorted(starts)


def test_select_ending_auto_finishes_on_highest_score():
    cands = [
        Candidate("v", 0.0, 10.0, score=5.0),
        Candidate("v", 20.0, 30.0, score=20.0),
        Candidate("v", 40.0, 50.0, score=8.0),
    ]
    result = select_global(cands, cfg(ending="auto", order="build_up"))
    assert result[-1].score == 20.0
