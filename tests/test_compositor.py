"""Le compositeur construit le filtergraph ffmpeg : c'est LUI qui monte.

131 lignes, appelées à chaque segment rendu, et aucun test jusqu'ici. Un filtergraph
malformé ne se voit pas à la lecture : ffmpeg refuse, ou pire, rend autre chose.

Deux garanties testées ici sont des DÉCISIONS produit écrites en commentaire dans le
module, donc jamais prouvées :
  - les effets (zoom/shake) vont sur le gameplay net UNIQUEMENT, jamais sur le fond
    flou — « sinon toute l'image respire = l'effet dégueu signalé par Alex » ;
  - la vitesse est appliquée AVANT le split, pour que le fond et le premier plan
    restent synchrones.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wzmontage.compositor import FORMATS, build_segment_filtergraph  # noqa: E402

SRC = (1920, 1080)


def _graph(spec, fps=60, src_fps=60):
    g, dims = build_segment_filtergraph(spec, SRC[0], SRC[1], fps, src_fps=src_fps)
    return g, dims


def _labels(graph):
    """(labels consommés, labels produits) du filtergraph."""
    consommes, produits = set(), set()
    for chaine in graph.split(";"):
        chaine = chaine.strip()
        if not chaine:
            continue
        # les [x] en tête sont des entrées, ceux en queue des sorties
        tete = re.match(r"^(\[[^\]]+\])+", chaine)
        if tete:
            consommes |= set(re.findall(r"\[([^\]]+)\]", tete.group(0)))
        queue = re.search(r"(\[[^\]]+\])+$", chaine)
        if queue:
            produits |= set(re.findall(r"\[([^\]]+)\]", queue.group(0)))
    return consommes, produits


# --- contrat structurel : ce que ffmpeg exige ---------------------------------

@pytest.mark.parametrize("fmt", ["vertical", "fullscreen", "square", "facecam_top", "inconnu"])
def test_tout_label_consomme_est_produit(fmt):
    """Un label consommé sans être produit = ffmpeg refuse le graphe."""
    graph, _ = _graph({"format": fmt})
    consommes, produits = _labels(graph)
    orphelins = consommes - produits - {"0:v"}
    assert not orphelins, f"labels jamais définis dans le graphe {fmt} : {orphelins}"


@pytest.mark.parametrize("fmt", ["vertical", "fullscreen", "square", "facecam_top", "inconnu"])
def test_le_graphe_sort_toujours_sur_v(fmt):
    """`render_segment` fait `-map [v]` : si la sortie change de nom, le rendu casse."""
    graph, _ = _graph({"format": fmt})
    assert graph.rstrip().endswith("[v]"), f"format {fmt} : la sortie n'est plus [v]"


def test_un_format_inconnu_retombe_en_vertical_et_ne_plante_pas():
    _, dims = _graph({"format": "n_importe_quoi"})
    assert dims == FORMATS["vertical"]


@pytest.mark.parametrize("fmt,attendu", [
    ("vertical", (1080, 1920)),
    ("fullscreen", (1920, 1080)),
    ("square", (1080, 1080)),
    ("facecam_top", (1080, 1920)),
])
def test_chaque_format_rend_ses_dimensions(fmt, attendu):
    _, dims = _graph({"format": fmt})
    assert dims == attendu


# --- décisions produit, écrites en commentaire et jamais prouvées -------------

def test_les_effets_ne_touchent_QUE_le_gameplay_net_pas_le_fond_flou():
    """La décision d'Alex : le fond reste stable, seul le centre punche.

    En vertical le fond est la branche `[v0]` (celle qui finit par `boxblur`) et le
    gameplay net la branche `[v1]`. Le zoom doit être dans la seconde, jamais la
    première — sinon toute l'image respire."""
    spec = {"format": "vertical", "zoom_punch": [1.0, 2.0]}
    graph, _ = _graph(spec)

    branche_fond = next(c for c in graph.split(";") if c.strip().startswith("[v0]"))
    branche_net = next(c for c in graph.split(";") if c.strip().startswith("[v1]"))

    assert "boxblur" in branche_fond, "la branche [v0] n'est plus le fond flou"
    assert "zoompan" in branche_net, "le zoom n'est pas appliqué au gameplay net"
    assert "zoompan" not in branche_fond, \
        "le zoom a atterri sur le fond flou : toute l'image va respirer"


def test_la_vitesse_est_appliquee_AVANT_le_split():
    """Sinon le fond et le premier plan se désynchronisent."""
    graph, _ = _graph({"format": "vertical", "speed": 2.0})
    i_setpts = graph.index("setpts")
    i_split = graph.index("split")
    assert i_setpts < i_split, "la vitesse est appliquée après le split : désynchro"


def test_une_vitesse_de_1_n_ajoute_aucun_filtre():
    """`speed=1.0` doit être un vrai no-op, pas un `setpts=PTS/1.0` inutile."""
    graph, _ = _graph({"format": "vertical", "speed": 1.0})
    assert "setpts" not in graph


def test_une_spec_vide_donne_un_clip_brut_utilisable():
    """« Tout est OPTIONNEL (spec vide = clip brut) » — la promesse du module."""
    graph, dims = _graph({})
    assert dims == FORMATS["vertical"]
    assert "zoompan" not in graph and "drawtext" not in graph
    assert graph.rstrip().endswith("[v]")


def test_le_zoom_utilise_le_framerate_de_la_SOURCE_pas_celui_de_sortie():
    """Documenté dans la signature : `src_fps` sert au zoompan, sinon ralenti.

    Un zoompan calé sur le fps de sortie au lieu de la source produit un effet
    ralenti — un défaut visible, mais silencieux côté code."""
    g30, _ = _graph({"format": "vertical", "zoom_punch": [1.0]}, fps=60, src_fps=30)
    g60, _ = _graph({"format": "vertical", "zoom_punch": [1.0]}, fps=60, src_fps=60)
    assert g30 != g60, "le graphe ignore src_fps : le zoom sera ralenti"


# ---------------------------------------------------------------------------
# 17/09/2026 — LES DEUX CROPS ENTRENT BRUTS DANS LE FILTERGRAPH
#
# `--intro-crop W:H:X:Y` est une option de ligne de commande, et `facecam_crop` une clé
# de spec : les deux sont recopiées telles quelles dans `crop={...}`. Elles contiennent
# des `:` par construction, donc on ne peut pas les échapper — il faut les VALIDER.
#
# Ce que ça coûte aujourd'hui : une faute de frappe (`1920x1080`) part chez ffmpeg et
# revient en erreur de graphe, loin de la cause ; et une valeur qui contient `,` ou `[`
# ajoute des filtres au graphe sans que rien ne le dise. Le module applique déjà la
# bonne doctrine pour la police : « on échoue ici, où le fait est connu, avec le geste
# de réparation dans le message ».

import wzmontage.montage as montage_mod  # noqa: E402


@pytest.mark.parametrize("mauvais", [
    "1920x1080",                     # faute de frappe courante : des x au lieu des :
    "960:540:480",                   # trois champs au lieu de quatre
    "960:540:480:0,drawbox=c=red@1", # une virgule = un filtre en plus dans le graphe
    "960:540:480:[v]",               # un séparateur de flux
    "-1:540:480:0",                  # dimension négative
    "",                              # vide
])
def test_un_crop_malforme_est_refuse_avant_ffmpeg(mauvais):
    with pytest.raises(ValueError) as e:
        montage_mod._vfilter(1080, 1920, 60, True, crop=mauvais)
    assert "W:H:X:Y" in str(e.value), "le message doit dire la forme attendue"


def test_un_crop_correct_passe_toujours():
    graphe = montage_mod._vfilter(1080, 1920, 60, True, crop="960:540:480:0")
    assert "crop=960:540:480:0," in graphe


def test_le_crop_de_facecam_de_la_spec_est_valide_lui_aussi():
    with pytest.raises(ValueError):
        build_segment_filtergraph(
            {"format": "facecam_top", "facecam_crop": "960:540:480:0,drawbox=c=red@1"},
            *SRC)
