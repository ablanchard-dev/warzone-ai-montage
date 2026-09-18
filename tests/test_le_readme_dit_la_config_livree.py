"""Ce que le README promet d'un clone frais est-il ce que `config.yaml` livre ?

Le README ouvre sa section « How it works » sur une phrase qu'un utilisateur lit AVANT de
lancer quoi que ce soit :

    > Out of the box (fresh clone), the pipeline runs **two** signals: red kill-banner
    > detection and Whisper voice. Two more are **opt-in**.

et la détaille dans un tableau dont la colonne `Status` dit, ligne par ligne, « On by default »
ou « Opt-in ».

Mesuré le 18/09/2026 : sur 190 tests, **aucun ne mentionne le README**. `test_config_wiring.py`
vérifie que les réglages ATTEIGNENT le code — c'est une autre question, et une bonne. Mais rien
ne tenait le lien entre la phrase publiée et le fichier livré. Un `use_action_peaks: true` posé
un soir pour un essai, et le clone frais ne se comporte plus comme le README le décrit, sans
qu'une seule ligne rougisse.

Trois liens sont tenus ici, et aucun n'est recopié :

1. **La prose contre le tableau** : le nombre écrit en toutes lettres (« two ») doit être le
   nombre de lignes `On by default`. Deux endroits du même fichier qui se contredisent, c'est
   le défaut le plus discret qui soit.
2. **Le tableau contre la config** : chaque ligne `Opt-in` qui nomme un réglage
   (`audio.use_action_peaks: true`) exige que le fichier LIVRÉ porte l'inverse.
3. **« templates are not shipped »** : aucun gabarit ne doit être suivi par git.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[1]
README = (RACINE / "README.md").read_text(encoding="utf-8")
CONFIG = yaml.safe_load((RACINE / "config.yaml").read_text(encoding="utf-8"))

NOMBRES = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def lignes_du_tableau_des_signaux() -> list[tuple[str, str]]:
    """(nom du signal, cellule Status) pour chaque ligne du tableau des signaux."""
    lignes: list[tuple[str, str]] = []
    for ligne in README.splitlines():
        if not ligne.startswith("| ") or ligne.startswith("| ---"):
            continue
        cellules = [c.strip() for c in ligne.strip("|").split("|")]
        if len(cellules) != 4 or cellules[0] in {"Signal", "Option"}:
            continue
        statut = cellules[3]
        if "default" in statut or "Opt-in" in statut:
            lignes.append((cellules[0], statut))
    return lignes


def _valeur(chemin: str):
    """La valeur livrée pour `a.b`, ou None si absente."""
    noeud = CONFIG
    for part in chemin.split("."):
        if not isinstance(noeud, dict) or part not in noeud:
            return None
        noeud = noeud[part]
    return noeud


def test_le_tableau_des_signaux_est_lisible():
    """Un garde qui ne trouve plus le tableau ne garde plus rien : il doit le dire."""
    lignes = lignes_du_tableau_des_signaux()
    assert len(lignes) >= 3, (
        f"le tableau des signaux n'est plus lisible ({len(lignes)} ligne(s)) — "
        "les deux tests suivants passeraient en ne comparant rien"
    )


def test_le_nombre_ecrit_en_toutes_lettres_est_celui_du_tableau():
    """« the pipeline runs **two** signals » doit compter les lignes `On by default`."""
    trouve = re.search(r"pipeline runs \*\*(\w+)\*\* signals", README)
    assert trouve, "le README n'annonce plus combien de signaux tournent par défaut"
    annonce = NOMBRES.get(trouve.group(1).lower())
    assert annonce is not None, f"nombre non reconnu : {trouve.group(1)!r}"

    par_defaut = [nom for nom, statut in lignes_du_tableau_des_signaux() if "default" in statut]
    assert len(par_defaut) == annonce, (
        f"la prose annonce {annonce} signaux par défaut, le tableau en marque "
        f"{len(par_defaut)} : {par_defaut}"
    )


def test_chaque_signal_dit_OPT_IN_est_eteint_dans_la_config_livree():
    """Le tableau contre le fichier. Un `true` posé pour un essai casse la promesse."""
    fautes: list[str] = []
    for nom, statut in lignes_du_tableau_des_signaux():
        if "Opt-in" not in statut:
            continue
        for cle, attendu in re.findall(r"`([\w.]+):\s*(\w+)`", statut):
            livree = _valeur(cle)
            # Le README dit « mets ça à `true` pour l'activer » ⇒ le livré doit être l'inverse.
            if attendu == "true" and livree is not False:
                fautes.append(f"{nom} : le README dit opt-in via `{cle}: true`, "
                              f"mais config.yaml livre {cle}={livree!r}")
    assert not fautes, "\n  ".join(["le clone frais ne fait pas ce que le README décrit :"] + fautes)


def test_aucun_gabarit_n_est_livre_comme_le_README_l_annonce():
    """« templates are not shipped » : un gabarit suivi par git ferait du vision un signal
    actif sans que personne ait lancé `calibrate.py`."""
    assert "templates are not shipped" in README, (
        "le README n'annonce plus que les gabarits ne sont pas livrés — cette garde ne vise "
        "plus rien"
    )
    dossier = _valeur("vision.templates_dir") or "templates"
    suivis = subprocess.run(
        ["git", "ls-files", dossier],
        cwd=RACINE, capture_output=True, text=True, check=False,
    ).stdout.split()
    assert not suivis, f"des gabarits sont suivis par git alors que le README dit le contraire : {suivis}"


@pytest.mark.parametrize(
    "faux_statut,doit_tomber",
    [
        ("Opt-in (set `audio.use_action_peaks: true`)", True),
        ("On by default", False),
    ],
)
def test_le_garde_sait_distinguer_opt_in_et_defaut(faux_statut, doit_tomber):
    """Le détecteur prouve qu'il lit vraiment la colonne, et pas n'importe quoi."""
    trouve = bool(re.findall(r"`([\w.]+):\s*(\w+)`", faux_statut)) and "Opt-in" in faux_statut
    assert trouve is doit_tomber
