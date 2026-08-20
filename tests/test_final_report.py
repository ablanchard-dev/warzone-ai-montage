"""Le mot de la fin doit porter ce que l'analyse a constaté.

Sans OCR, `_classify_banner` compte TOUT bandeau comme un kill : le montage peut
contenir les morts. Un avertissement était bien imprimé — mais au moment où le
problème survient, c'est-à-dire à l'analyse du premier clip. Sur plusieurs vidéos
il finit des centaines de lignes au-dessus du « ✓ Terminé. » final.

Le détail était honnête ; la conclusion mentait par omission. Ces tests couvrent
la conclusion, pas l'avertissement.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import final_report  # noqa: E402
from wzmontage import killdetect  # noqa: E402


def test_run_sain_conclut_simplement():
    assert final_report([]) == "✓ Terminé."


def test_run_degrade_ne_conclut_PAS_par_un_termine_serein():
    texte = final_report(["OCR indisponible : le montage peut contenir des morts."])
    # La ligne finale ne doit pas pouvoir se lire comme un succès sans réserve.
    assert texte.strip().splitlines()[-1] != "✓ Terminé."
    assert "DÉGRADÉ" in texte
    assert "peut contenir des morts" in texte


def test_chaque_raison_est_citee_dans_la_conclusion():
    raisons = ["raison A distinctive", "raison B distinctive"]
    texte = final_report(raisons)
    for r in raisons:
        assert r in texte, f"la conclusion tait « {r} »"


def test_absence_docr_enregistre_une_degradation_durable():
    # On force le cas « rapidocr absent » sans toucher à l'environnement.
    killdetect._OCR = None
    killdetect._DEGRADATIONS.clear()
    vrai_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

    def import_qui_echoue(name, *a, **k):
        if name.startswith("rapidocr"):
            raise ImportError("simulé : rapidocr absent")
        return vrai_import(name, *a, **k)

    import builtins
    builtins.__import__ = import_qui_echoue
    try:
        assert killdetect._get_ocr() is False
    finally:
        builtins.__import__ = vrai_import

    raisons = killdetect.degradations()
    assert raisons, "l'absence d'OCR n'a laissé AUCUNE trace consultable en fin de run"
    assert any("rapidocr" in r for r in raisons)
    # et cette trace doit survivre jusqu'à la conclusion
    assert "DÉGRADÉ" in final_report(raisons)


def test_degradations_rend_une_copie():
    # Un appelant qui vide la liste rendue ne doit pas effacer l'état réel.
    killdetect._DEGRADATIONS.clear()
    killdetect._DEGRADATIONS.append("trace")
    killdetect.degradations().clear()
    assert killdetect.degradations() == ["trace"]
    killdetect._DEGRADATIONS.clear()


def test_main_utilise_vraiment_final_report_et_ne_dit_plus_termine_en_dur():
    """Une fonction juste que personne n'appelle ne protège de rien.

    Lecture des SOURCES, comme `test_config_wiring` : le câblage d'un mot de la
    fin ne lève jamais d'erreur s'il manque — c'est le seul moyen de l'attraper.
    """
    src = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    corps = src.split("def main() -> None:", 1)[1]
    assert "final_report(degradations())" in corps, \
        "main() n'appelle pas final_report(degradations())"
    assert 'print("✓ Terminé.")' not in corps, \
        "main() conclut encore par un « ✓ Terminé. » écrit en dur, hors de final_report"
