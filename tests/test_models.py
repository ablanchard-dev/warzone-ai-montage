"""Tests des structures de données (wzmontage.models)."""
from wzmontage.models import Candidate, Event, SpeechSegment


def test_candidate_duration():
    assert Candidate("v", 10.0, 25.0).duration == 15.0


def test_candidate_zero_duration():
    assert Candidate("v", 5.0, 5.0).duration == 0.0


def test_candidate_defaults():
    c = Candidate("v", 0.0, 4.0)
    assert c.score == 0.0
    assert c.n_kills == 0
    assert c.has_victory is False
    assert c.has_speech is False
    assert c.kinds == set()
    assert c.crop is None
    assert c.speed == 1.0
    assert c.is_intro is False


def test_candidate_kinds_are_independent_instances():
    a = Candidate("v", 0.0, 1.0)
    b = Candidate("v", 0.0, 1.0)
    a.kinds.add("kill")
    assert b.kinds == set()  # default_factory -> pas de set partagé


def test_event_defaults_confidence():
    e = Event("v", 12.5, "kill")
    assert e.conf == 1.0
    assert e.type == "kill"
    assert e.t == 12.5


def test_speech_segment_fields():
    s = SpeechSegment("v", 1.0, 3.0, "gg")
    assert s.start == 1.0
    assert s.end == 3.0
    assert s.text == "gg"


def test_speech_segment_default_text():
    assert SpeechSegment("v", 1.0, 2.0).text == ""
