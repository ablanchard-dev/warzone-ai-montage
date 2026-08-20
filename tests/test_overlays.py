"""Le texte utilisateur finit dans un filtergraph ffmpeg : il doit être inoffensif.

L'outil est piloté au chat, donc la spec — et son champ `text` — vient de l'utilisateur.
Deux défauts trouvés le 15/08, tous deux **mesurés en lançant ffmpeg**, pas déduits :

1. `,` `;` `[` `]` n'étaient pas échappés. `text="x,drawbox=c=red@1:t=fill"` produisait
   un filtergraph contenant un vrai `drawbox`. Avant d'être une injection, c'est un bug
   de correction : « salut, ça va » cassait le rendu.
2. Le `:` était échappé avec UN backslash et ffmpeg refusait quand même. Il en faut
   DEUX — le `:` est consommé par l'analyseur de filtergraph ET par celui des arguments,
   là où `,` ne l'est que par un seul.

Cette asymétrie n'est pas devinable. Le test qui l'épingle existe pour qu'un futur
« nettoyage » qui uniformiserait les échappements soit rattrapé.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from wzmontage.overlays import _escape_drawtext, text_overlay  # noqa: E402

METACARACTERES = {
    "virgule": "salut, ca va",
    "deux-points": "score: 12",
    "point-virgule": "boom; boom",
    "crochets": "[BOOM]",
    "pourcent": "100% headshot",
    "apostrophe": "c'est parti",
    "backslash": "a\\b",
    "injection": "x,drawbox=c=red@1:t=fill",
}


def test_l_asymetrie_mesuree_est_respectee():
    """UN backslash pour la virgule, DEUX pour le deux-points.

    Établi en essayant chaque forme sur un rendu réel. Uniformiser les deux casse
    ffmpeg : c'est exactement le « nettoyage » que ce test doit rattraper."""
    assert _escape_drawtext("a,b") == "a\\,b", "la virgule prend UN backslash"
    assert _escape_drawtext("a:b") == "a\\\\:b", "le deux-points en prend DEUX"


@pytest.mark.parametrize("nom", sorted(METACARACTERES))
def test_aucun_separateur_ne_reste_nu(nom):
    """Un séparateur non précédé d'un backslash termine le filtre en cours."""
    frag = text_overlay(0.0, 1.0, text=METACARACTERES[nom])
    debut = frag.index("text=") + len("text=")
    fin = frag.index(":fontcolor", debut)
    valeur = frag[debut:fin]
    for i, c in enumerate(valeur):
        if c in ",;[]":
            assert i > 0 and valeur[i - 1] == "\\", \
                f"{nom} : le caractère {c!r} sort du filtre (position {i} dans {valeur!r})"


def test_une_tentative_d_injection_ne_produit_aucun_filtre_reel():
    frag = text_overlay(0.0, 1.0, text="x,drawbox=c=red@1:t=fill")
    assert "drawbox=c=red@1:t=fill" not in frag, \
        "le payload apparaît tel quel : un vrai drawbox sera exécuté"


def test_le_chemin_textfile_ne_touche_a_rien():
    """La voie recommandée pour le texte utilisateur : rien n'est concaténé."""
    frag = text_overlay(0.0, 1.0, textfile="hook.txt")
    assert "textfile=hook.txt" in frag
    # attention : `drawtext=` contient la sous-chaîne `text=`. On teste le SÉPARATEUR
    # d'option, sinon le test se croit malin et ne prouve rien.
    assert ":text=" not in frag, "le chemin textfile ne doit poser aucun text= inline"


def test_sans_texte_ni_fichier_la_fonction_refuse():
    with pytest.raises(ValueError):
        text_overlay(0.0, 1.0)


def test_la_fenetre_et_le_fondu_sont_bornes():
    frag = text_overlay(2.0, 5.0, text="GG", fade=0.1)
    assert "enable='between(t,2.000,5.000)'" in frag
    assert "alpha=" in frag and "if(lt(t,2.000),0," in frag, \
        "le fondu ne démarre plus au début de la fenêtre"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent")
@pytest.mark.parametrize("nom", sorted(METACARACTERES))
def test_ffmpeg_accepte_reellement_le_graphe(nom, tmp_path):
    """La seule preuve qui compte : le rendu passe.

    Un test qui vérifie seulement la présence de backslashes peut être vert avec un
    échappement que ffmpeg refuse — c'est précisément ce qui est arrivé au `:`."""
    frag = text_overlay(0.0, 1.0, text=METACARACTERES[nom])
    script = tmp_path / "graph.txt"
    script.write_text(f"[0:v]{frag}[v]", encoding="utf-8")
    sortie = tmp_path / "out.png"
    r = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25:duration=1",
         "-filter_complex_script", str(script), "-map", "[v]",
         "-frames:v", "1", str(sortie)],
        cwd=RACINE, capture_output=True, text=True)
    assert sortie.exists() and sortie.stat().st_size > 0, \
        f"ffmpeg refuse le graphe pour {nom} : {r.stderr.strip()[:200]}"


# --- les CHEMINS aussi passent dans le filtre --------------------------------
# `textfile=` est la voie RECOMMANDÉE pour le texte utilisateur — et elle cassait
# sur tout chemin absolu Windows, à cause du `:` du lecteur. Un outil piloté au chat
# produit naturellement des chemins absolus. Mesuré le 15/08 :
#   textfile=C:/Users/... -> « No option name near '/Users/...' », graphe refusé.

from wzmontage.overlays import _escape_path  # noqa: E402

CHEMIN_ABSOLU = "C:/Users/blanc/wzmontage/assets/fonts/impact.ttf"


def test_le_deux_points_du_lecteur_prend_DEUX_backslashes():
    """Même asymétrie que pour le texte : un seul backslash ne suffit pas."""
    echappe = _escape_path(CHEMIN_ABSOLU)
    assert echappe.startswith("C" + "\\" * 2 + ":/"), \
        f"le ':' du lecteur n'est pas neutralisé : {echappe[:12]!r}"


def test_les_antislashs_windows_deviennent_des_slashs():
    """ffmpeg accepte `/` partout ; garder `\\` mélange séparateur et échappement."""
    echappe = _escape_path(r"C:\dossier\fichier.txt")
    assert "/dossier/fichier.txt" in echappe
    # les seuls backslashes restants sont ceux qui échappent le ':'
    assert echappe.replace("\\" * 2 + ":", "") .count("\\") == 0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent")
def test_ffmpeg_accepte_un_textfile_en_chemin_absolu(tmp_path):
    hook = tmp_path / "hook.txt"
    hook.write_text("BOOM", encoding="utf-8")
    frag = text_overlay(0.0, 1.0, textfile=str(hook))
    script = tmp_path / "g.txt"
    script.write_text(f"[0:v]{frag}[v]", encoding="utf-8")
    sortie = tmp_path / "o.png"
    r = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25:duration=1",
         "-filter_complex_script", str(script), "-map", "[v]",
         "-frames:v", "1", str(sortie)],
        cwd=RACINE, capture_output=True, text=True)
    assert sortie.exists() and sortie.stat().st_size > 0, \
        f"la voie RECOMMANDÉE échoue sur un chemin absolu : {r.stderr.strip()[:200]}"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent")
def test_ffmpeg_accepte_une_police_en_chemin_absolu(tmp_path):
    police = RACINE / "assets" / "fonts" / "impact.ttf"
    if not police.exists():
        pytest.skip("police bundlée absente")
    frag = text_overlay(0.0, 1.0, text="GG", fontfile=str(police))
    script = tmp_path / "g.txt"
    script.write_text(f"[0:v]{frag}[v]", encoding="utf-8")
    sortie = tmp_path / "o.png"
    r = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25:duration=1",
         "-filter_complex_script", str(script), "-map", "[v]",
         "-frames:v", "1", str(sortie)],
        cwd=RACINE, capture_output=True, text=True)
    assert sortie.exists() and sortie.stat().st_size > 0, \
        f"une police en chemin absolu casse le graphe : {r.stderr.strip()[:200]}"
