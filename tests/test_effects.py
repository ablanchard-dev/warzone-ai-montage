"""Les primitives d'effets : on ÉVALUE la courbe, on ne compare pas des chaînes.

`effects.py` ne rend que du texte (des fragments de filtergraph), donc un test qui
cherche un mot-clé prouve seulement qu'un mot est là. Ce qu'Alex juge à l'œil, lui,
c'est la COURBE : quand le zoom démarre, où il culmine, et ce qui se passe quand
deux kills sont proches.

Ces tests traduisent l'expression ffmpeg en Python et l'évaluent, ce qui permet de
prouver les garanties écrites dans les docstrings du module :
  - « 0 AVANT le kill, montée RAPIDE jusqu'au pic, puis descente douce » ;
  - « Plusieurs centres = max des punchs (PAS d'addition) » — sinon deux kills
    rapprochés donneraient un zoom cumulé, exactement l'effet dégueu à éviter ;
  - « pic PILE sur chaque centre » (synchro).
"""
import math
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wzmontage import effects  # noqa: E402


# --- évaluateur du sous-ensemble d'expressions ffmpeg utilisé ici -------------

def _if(cond, a, b):
    return a if cond else b


def _between(x, a, b):
    return a <= x <= b


def _lt(a, b):
    return a < b


def _eval(expr: str, t: float) -> float:
    """Évalue une expression ffmpeg en y injectant `t`."""
    py = expr
    py = re.sub(r"\bbetween\(", "_between(", py)
    py = re.sub(r"\blt\(", "_lt(", py)
    py = re.sub(r"\bif\(", "_if(", py)
    py = py.replace("PI", "math.pi")
    return float(eval(py, {"_if": _if, "_between": _between, "_lt": _lt,
                           "max": max, "math": math, "t": t}))


def test_l_evaluateur_est_fidele_sur_un_cas_connu():
    """Garde-fou de l'outil de mesure lui-même : sans lui, les tests ci-dessous
    pourraient être verts parce que l'évaluateur est faux."""
    assert _eval("if(between(t,0,1),5,9)", 0.5) == 5
    assert _eval("if(between(t,0,1),5,9)", 2.0) == 9
    assert _eval("max(3,if(lt(t,1),1,2))", 0.0) == 3


# --- la courbe de zoom -------------------------------------------------------

def test_au_repos_le_zoom_vaut_exactement_1():
    assert effects.zoom_punch_zexpr([]) == "1"


def test_le_zoom_est_a_1_AVANT_le_kill():
    """« 0 AVANT le kill » : pas de zoom qui s'amorce en avance, sinon l'effet
    précède l'action et se voit."""
    z = effects.zoom_punch_zexpr([2.0], peak=1.4)
    for t in (0.0, 1.0, 1.9, 1.999):
        assert _eval(z, t) == pytest.approx(1.0), f"le zoom a démarré à t={t}, avant le kill"


def test_le_pic_tombe_PILE_a_l_attaque_et_vaut_le_peak_demande():
    z = effects.zoom_punch_zexpr([2.0], peak=1.4, atk=0.08, rel=0.18)
    assert _eval(z, 2.08) == pytest.approx(1.4, abs=1e-6)


def test_le_zoom_revient_a_1_apres_le_relachement():
    z = effects.zoom_punch_zexpr([2.0], peak=1.4, atk=0.08, rel=0.18)
    fin = 2.0 + 0.08 + 0.18
    assert _eval(z, fin) == pytest.approx(1.0, abs=1e-6)
    assert _eval(z, fin + 0.5) == pytest.approx(1.0)


def test_la_montee_est_plus_RAPIDE_que_la_descente():
    """« montée RAPIDE puis descente douce » : la forme de l'effet, pas un détail."""
    z = effects.zoom_punch_zexpr([2.0], peak=1.4, atk=0.08, rel=0.18)
    milieu_montee = _eval(z, 2.0 + 0.04)      # moitié de l'attaque
    milieu_descente = _eval(z, 2.08 + 0.09)   # moitié du relâchement
    assert milieu_montee == pytest.approx(milieu_descente, abs=0.02), \
        "les deux demi-hauteurs devraient coïncider"
    # et l'attaque dure bien moins longtemps que le relâchement
    assert 0.08 < 0.18


def test_deux_kills_proches_prennent_le_MAX_jamais_la_somme():
    """La garantie explicite du module. Une addition ferait un zoom cumulé sur
    deux kills rapprochés — l'effet exagéré qu'on cherche à éviter."""
    z = effects.zoom_punch_zexpr([2.0, 2.05], peak=1.4)
    pic = max(_eval(z, t / 1000) for t in range(1900, 2400))
    assert pic == pytest.approx(1.4, abs=1e-3), \
        f"pic mesuré {pic:.3f} : les punchs s'additionnent au lieu de se maximiser"


def test_un_pic_PROPRE_a_chaque_centre_est_respecte():
    """`peaks` = mixer des punchs forts (kills) et doux (beats). C'est ce réglage
    qu'Alex doit arbitrer sur les 3 versions beat-fx."""
    z = effects.zoom_punch_zexpr([1.0, 5.0], peaks=[1.5, 1.05])
    assert _eval(z, 1.08) == pytest.approx(1.5, abs=1e-6)
    assert _eval(z, 5.08) == pytest.approx(1.05, abs=1e-6)


def test_le_zoom_ne_descend_JAMAIS_sous_1():
    """Un facteur < 1 dézoomerait et ferait apparaître des bords noirs."""
    z = effects.zoom_punch_zexpr([2.0, 4.0], peaks=[1.4, 1.1])
    assert min(_eval(z, t / 100) for t in range(0, 600)) >= 1.0


# --- le filtre complet et la secousse ----------------------------------------

def test_le_zoompan_utilise_le_temps_en_FRAMES_de_sortie():
    """Le module documente `on/fps` : caler sur `t` donnerait un effet décalé."""
    f = effects.zoom_punch_filter([1.0], 1080, 1920, fps=30)
    assert "(on/30)" in f
    assert "s=1080x1920" in f and "fps=30" in f


def test_la_secousse_garde_une_marge_suffisante_pour_eviter_les_bords_noirs():
    """La docstring promet un upscale de marge : il doit valoir 2x l'amplitude,
    sinon le crop décalé sort de l'image et laisse du noir."""
    amp = 64
    f = effects.shake_filter(1.0, 0.4, 1080, 1920, amp_px=amp)
    m = re.search(r"scale=(\d+):(\d+)", f)
    assert m, "pas d'upscale de marge dans le filtre de secousse"
    assert int(m.group(1)) == 1080 + 2 * amp
    assert int(m.group(2)) == 1920 + 2 * amp


def test_la_secousse_est_nulle_hors_de_sa_fenetre():
    f = effects.shake_filter(1.0, 0.4, 1080, 1920, amp_px=64)
    # l'enveloppe doit etre bornee par un `between` ET retomber a 0 en dehors
    assert re.search(r"if\(between\(t,[\d.]+,[\d.]+\)", f),         "l'enveloppe amortie n'est plus bornée à sa fenêtre"
    assert ",0)" in f, "l'enveloppe ne retombe plus à 0 hors fenêtre"
    # et l'offset au repos vaut exactement la marge -> crop centré, aucun bord noir
    assert re.search(r"x='64\+64\*\(", f), "l'offset de repos n'est plus centré sur la marge"


def test_le_ralenti_ralentit_bien_et_l_interpolation_est_optionnelle():
    assert effects.slowmo_filter(2.5, interpolate=False) == "setpts=2.5*PTS"
    avec = effects.slowmo_filter(2.5, fps=60, interpolate=True)
    assert avec.startswith("setpts=2.5*PTS") and "minterpolate=fps=60" in avec
