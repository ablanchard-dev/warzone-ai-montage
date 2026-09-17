"""Chaque option de la ligne de commande atteint-elle vraiment le code ?

Même doctrine que `test_config_wiring.py`, sur l'autre moitié des boutons. Ce dépôt a
déjà payé cette leçon deux fois le 15/08, mesuré en lançant le programme :

  - `--zoom` et `--sfx` étaient **inertes en silence** : l'option existait, se tapait,
    s'affichait dans l'aide, et ne changeait rien au rendu ;
  - `--add` et `--first` étaient **inatteignables** — le chemin qui les lisait ne pouvait
    pas être emprunté.

Un bouton qu'on tourne et qui ne fait rien est la forme la plus frustrante de l'échec
silencieux : on croit piloter. Et il ne lève jamais rien, donc aucun test de comportement
ne le trouve. Seule la lecture des SOURCES l'attrape.

Aujourd'hui les 25 options sont bien lues — mais par ABSENCE de bug, pas par une serrure.
Ce fichier est la serrure : la 26e option ajoutée sans être branchée fait rougir la suite.
"""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
MAIN = ROOT / "main.py"


def options_declarees(source: str) -> set[str]:
    """Le `dest` de chaque `add_argument`, déduit comme argparse le déduit lui-même."""
    arbre = ast.parse(source)
    dests: set[str] = set()

    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call):
            continue
        cible = noeud.func
        if not (isinstance(cible, ast.Attribute) and cible.attr == "add_argument"):
            continue

        explicite = next(
            (kw.value.value for kw in noeud.keywords
             if kw.arg == "dest" and isinstance(kw.value, ast.Constant)),
            None,
        )
        if explicite:
            dests.add(explicite)
            continue

        # Comme argparse : la première option longue gagne, sinon le premier nom positionnel.
        longues = [a.value for a in noeud.args
                   if isinstance(a, ast.Constant) and str(a.value).startswith("--")]
        if longues:
            dests.add(longues[0][2:].replace("-", "_"))
        elif noeud.args and isinstance(noeud.args[0], ast.Constant):
            dests.add(str(noeud.args[0].value).lstrip("-").replace("-", "_"))

    return dests


def options_jamais_lues(source: str) -> set[str]:
    return {
        dest for dest in options_declarees(source)
        if not re.search(r"args\." + re.escape(dest) + r"\b", source)
    }


def test_aucune_option_declaree_ne_reste_morte():
    source = MAIN.read_text(encoding="utf-8")

    declarees = options_declarees(source)
    assert len(declarees) >= 20, (
        f"le garde ne trouve plus que {len(declarees)} options : il ne garde plus rien"
    )

    mortes = options_jamais_lues(source)
    assert not mortes, (
        "ces options existent dans l'aide et ne sont lues nulle part : " + repr(sorted(mortes))
    )


def test_le_garde_VOIT_une_option_ajoutee_sans_etre_branchee():
    """Un garde qu'on ne peut pas faire tomber sur commande ne prouve rien.

    Sans lui, le test du dessus prouverait surtout que la déduction ne trouve rien.
    """
    faux = (
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--zoom-peak', type=float, default=1.18)\n"
        "p.add_argument('--branchee', type=int, default=3)\n"
        "args = p.parse_args()\n"
        "print(args.branchee)\n"
    )

    assert options_declarees(faux) == {"zoom_peak", "branchee"}
    assert options_jamais_lues(faux) == {"zoom_peak"}


def test_un_dest_explicite_est_suivi_sous_son_vrai_nom():
    """`dest=` renomme l'option : la suivre sous le nom de l'option accuserait à tort."""
    faux = (
        "p.add_argument('--no-voix', dest='voix', action='store_false')\n"
        "print(args.voix)\n"
    )

    assert options_declarees(faux) == {"voix"}
    assert options_jamais_lues(faux) == set()
