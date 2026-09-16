"""Selection des bandeaux : un front REJETE par l'OCR ne doit pas masquer le vrai kill.

Mesure 16/09 sur un vrai clip (2026.06.14 - 16.31.37) : un pic rouge a 84,40 s (hors
bandeau) cree un candidat, l'OCR le rejette ; le vrai bandeau ENNEMI ABATTU devient
rouge a 85,40 s, soit < 1,5 s apres, et n'etait jamais candidat. OCR a 86,0 s : knock.
Le kill etait perdu. L'ecart minimal ne vaut qu'entre bandeaux ACCEPTES.
"""
from wzmontage.killdetect import select_banner_events


def _samples(red_at, step=0.2, end=6.0):
    """(t, fraction rouge) toutes les 0,2 s ; rouge (0.5) aux instants donnes."""
    n = int(round(end / step))
    ts = [round(i * step, 2) for i in range(n + 1)]
    return [(t, 0.5 if t in red_at else 0.0) for t in ts]


def test_un_front_rejete_ne_masque_pas_le_bandeau_qui_suit():
    samples = _samples([round(4.4, 2), round(5.4, 2)])
    verdicts = {4.4: "skip", 5.4: "knock"}
    events = select_banner_events(samples, lambda t: verdicts[round(t, 2)], on_frac=0.33, min_gap=1.5)
    assert events == [(5.4, "knock")]


def test_deux_fronts_acceptes_trop_proches_restent_un_seul_bandeau():
    samples = _samples([1.0, 2.0])
    events = select_banner_events(samples, lambda t: "knock", on_frac=0.33, min_gap=1.5)
    assert events == [(1.0, "knock")]


def test_un_bandeau_qui_reste_rouge_ne_compte_qu_une_fois():
    samples = _samples([1.0, 1.2, 1.4, 1.6])
    events = select_banner_events(samples, lambda t: "knock", on_frac=0.33, min_gap=1.5)
    assert events == [(1.0, "knock")]
