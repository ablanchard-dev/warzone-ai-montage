"""Deux detecteurs sur le meme bandeau ne doivent pas compter deux kills.

Revue 17/09 : avec des templates calibres (opt-in), main.py additionnait les evenements
du detecteur OCR de bandeau et du detecteur d'icones. Un seul kill devenait deux
(bonus x1.3, etiquette « 2K », double zoom) ; et une MORT classee par l'OCR redevenait
un kill cote icone, qui ne sait pas distinguer.
"""
from wzmontage.models import Event
from wzmontage.vision import merge_template_events

V = "clip.mp4"


def test_un_kill_vu_par_les_deux_detecteurs_compte_une_fois():
    ocr = [Event(V, 10.0, "knock", 1.0)]
    tpl = [Event(V, 10.4, "kill", 0.9)]
    assert merge_template_events(ocr, tpl, window_s=1.5) == ocr


def test_une_mort_classee_par_l_ocr_n_est_pas_recomptee_en_kill_par_l_icone():
    ocr = [Event(V, 30.0, "death", 1.0)]
    tpl = [Event(V, 30.2, "kill", 0.8)]
    merged = merge_template_events(ocr, tpl, window_s=1.5)
    assert [e.type for e in merged] == ["death"]


def test_un_kill_vu_seulement_par_l_icone_est_conserve():
    ocr = [Event(V, 10.0, "knock", 1.0)]
    tpl = [Event(V, 40.0, "kill", 0.9)]
    merged = merge_template_events(ocr, tpl, window_s=1.5)
    assert sorted(e.t for e in merged) == [10.0, 40.0]
