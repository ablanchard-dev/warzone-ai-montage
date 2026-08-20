"""Tests de la classification des bandeaux et de la fusion knock/confirm.

Aucun de ces tests n'a besoin d'une vidéo ni d'OCR réel : on injecte un faux OCR
qui rend le texte voulu. C'est ce qui rend ce module testable — il ne l'était pas.
"""
import numpy as np

from wzmontage import killdetect
from wzmontage.killdetect import merge_knock_confirm
from wzmontage.models import Event

FRAME = np.zeros((360, 640, 3), dtype=np.uint8)


def _with_ocr_text(monkeypatch_text):
    """Remplace l'OCR par une fonction qui rend toujours le texte donné."""
    killdetect._OCR = lambda roi: ([[None, monkeypatch_text, 0.99]], None)


def _no_ocr():
    killdetect._OCR = False


def _classify(text):
    _with_ocr_text(text)
    try:
        return killdetect._classify_banner(FRAME)
    finally:
        killdetect._OCR = None


# --- classification ---------------------------------------------------------

def test_ennemi_abattu_est_un_knock():
    assert _classify("ENNEMI ABATTU") == "knock"


def test_elimination_accentuee_est_un_elim():
    # Piège corrigé : l'ancien motif 'ELIMINAT' ne matchait PAS "ÉLIMINATION"
    # (le É accentué). Seul le mot "ENNEMI" sauvait la détection.
    assert _classify("ÉLIMINATION") == "elim"


def test_ennemi_elimine_est_un_elim_pas_un_knock():
    # Contient ENNEMI **et** ÉLIMINÉ : l'ordre des tests doit trancher pour 'elim'.
    assert _classify("ENNEMI ÉLIMINÉ") == "elim"


def test_vous_etes_a_terre_est_une_mort():
    assert _classify("VOUS ÊTES À TERRE") == "death"


def test_coequipier_est_ignore():
    assert _classify("COÉQUIPIER À TERRE") == "skip"


def test_coequipier_abattu_est_ignore_lui_aussi():
    # Celui-ci PROUVE le garde-fou « coéquipier » : sans lui, le mot ABATTU
    # suffirait à classer le down d'un pote comme un knock ennemi, et ses morts
    # entreraient dans le montage. (Trouvé par mutation : le test au-dessus
    # passait pour une autre raison et ne couvrait pas le garde-fou.)
    assert _classify("COÉQUIPIER ABATTU") == "skip"


def test_sans_ocr_le_type_reste_neutre():
    # On ne sait pas si c'est un knock ou un confirm : rester neutre plutôt qu'inventer.
    _no_ocr()
    try:
        assert killdetect._classify_banner(FRAME) == "kill"
    finally:
        killdetect._OCR = None


# --- fusion knock / confirm -------------------------------------------------

def _ev(t, kind):
    return Event("clip.mp4", t, kind, 1.0)


def test_le_confirm_qui_suit_un_knock_est_absorbe():
    out = merge_knock_confirm([_ev(10.0, "knock"), _ev(13.0, "elim")], window_s=10.0)
    assert [(e.t, e.type) for e in out] == [(10.0, "kill")]


def test_un_knock_confirme_vaut_un_kill_complet_pas_un_simple_knock():
    # KILL_VALUE : knock = 0.6, kill/elim = 1.0. Si la fusion laissait le type
    # 'knock', un vrai kill (knock puis achevement) pesserait MOINS qu'un kill
    # instantane -- l'inverse de ce qu'on veut. Le type repasse donc a 'kill'.
    from wzmontage.scoring import KILL_VALUE

    out = merge_knock_confirm([_ev(10.0, "knock"), _ev(13.0, "elim")], window_s=10.0)
    assert KILL_VALUE[out[0].type] == KILL_VALUE["elim"]


def test_un_knock_NON_confirme_reste_un_knock():
    # Ennemi mis a terre puis releve par son equipe : ce n'est pas un kill.
    out = merge_knock_confirm([_ev(10.0, "knock")], window_s=10.0)
    assert out[0].type == "knock"


def test_on_garde_l_instant_du_knock_pas_celui_du_confirm():
    # C'est la règle « couper sur le knock, pas le confirm ».
    out = merge_knock_confirm([_ev(10.0, "knock"), _ev(18.0, "elim")], window_s=10.0)
    assert out[0].t == 10.0


def test_deux_knocks_rapproches_restent_deux_adversaires():
    out = merge_knock_confirm([_ev(10.0, "knock"), _ev(12.0, "knock")], window_s=10.0)
    assert len(out) == 2


def test_un_elim_isole_est_conserve():
    # Kill instantané : pas de knock avant, l'élimination est le seul événement.
    out = merge_knock_confirm([_ev(30.0, "elim")], window_s=10.0)
    assert [(e.t, e.type) for e in out] == [(30.0, "elim")]


def test_un_confirm_trop_tardif_compte_comme_un_autre_adversaire():
    out = merge_knock_confirm([_ev(10.0, "knock"), _ev(25.0, "elim")], window_s=10.0)
    assert len(out) == 2


def test_les_morts_ne_sont_jamais_absorbees():
    out = merge_knock_confirm([_ev(10.0, "knock"), _ev(11.0, "death")], window_s=10.0)
    assert sorted(e.type for e in out) == ["death", "knock"]


def test_un_seul_confirm_est_absorbe_par_knock():
    # knock -> elim (absorbé) -> elim (nouveau, le 1er confirm a libéré le knock)
    out = merge_knock_confirm(
        [_ev(10.0, "knock"), _ev(12.0, "elim"), _ev(14.0, "elim")], window_s=10.0
    )
    assert len(out) == 2


def test_le_compte_de_kills_n_est_plus_gonfle():
    # Cas mesuré sur les clips en cache : 2 bandeaux à 4,4 s d'écart. Avant, cela
    # donnait n_kills = 2 et déclenchait un bonus multikill pour UN SEUL ennemi.
    events = [_ev(90.8, "knock"), _ev(95.2, "elim")]
    killy = {"kill", "knock", "elim"}
    assert sum(1 for e in merge_knock_confirm(events) if e.type in killy) == 1
