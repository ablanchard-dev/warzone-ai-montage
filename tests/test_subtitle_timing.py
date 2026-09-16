"""Les sous-titres doivent suivre l'image rendue, pas le temps du clip source.

Revue 17/09 : le temps d'un sous-titre etait calcule lineairement (t - c.start + offset).
(1) Quand un trou mort interne est excise (C5), tout ce qui suit le trou tombait plus tard
    que l'image, jusqu'a apres la coupe. (2) Avec --speed, les effets de zoom etaient
    divises par la vitesse mais pas les sous-titres : le texte trainait derriere le son.
"""
from wzmontage.cutting import source_to_rendered


def test_sans_trou_ni_vitesse_le_temps_est_local_au_clip():
    assert source_to_rendered(14.0, start=10.0, segments=[], speed=1.0) == 4.0


def test_apres_un_trou_excise_le_temps_recule_de_la_duree_du_trou():
    # clip 0-20, trou 8-12 excise : 14 s source joue a 8 + (14-12) = 10 s rendu
    assert source_to_rendered(14.0, start=0.0, segments=[(0.0, 8.0), (12.0, 20.0)], speed=1.0) == 10.0


def test_un_instant_dans_le_trou_retombe_sur_la_reprise():
    assert source_to_rendered(9.5, start=0.0, segments=[(0.0, 8.0), (12.0, 20.0)], speed=1.0) == 8.0


def test_la_vitesse_compresse_le_temps_rendu():
    assert abs(source_to_rendered(12.0, start=0.0, segments=[], speed=1.2) - 10.0) < 1e-9


def test_trou_et_vitesse_ensemble():
    # (8 s + 2 s) / 1.25 = 8 s
    assert abs(source_to_rendered(14.0, start=0.0, segments=[(0.0, 8.0), (12.0, 20.0)], speed=1.25) - 8.0) < 1e-9
