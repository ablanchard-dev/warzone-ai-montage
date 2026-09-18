import os
import sys

import pytest

# Rend le package `wzmontage` importable quand on lance pytest.
sys.path.insert(0, os.path.dirname(__file__))

_FONT = os.path.join(os.path.dirname(__file__), "assets", "fonts", "impact.ttf")


@pytest.fixture(scope="session", autouse=True)
def _police_factice_si_absente():
    """Le depot ne redistribue pas impact.ttf (police systeme, .gitignore). Depuis que
    text_overlay leve si la police manque, un clone frais (la CI) faisait echouer 21 tests
    d'echappement qui ne portent pas sur la police. Un fichier factice suffit : ces tests
    ne lancent pas ffmpeg avec. Une vraie police deja presente n'est jamais touchee ; les
    tests de police absente utilisent leurs propres chemins temporaires."""
    if os.path.exists(_FONT):
        yield
        return
    os.makedirs(os.path.dirname(_FONT), exist_ok=True)
    with open(_FONT, "wb") as f:
        f.write(b"police factice de test")
    try:
        yield
    finally:
        os.remove(_FONT)

# ─────────────────────────────────────────────────────────────────────────────────────────
# « la suite n'a besoin ni du reseau ni d'une cle » — tenu ici, pas seulement ecrit.
#
# Mesure du 18/09/2026 : 196 tests passent avec TOUTE sortie reseau bloquee et les variables
# de cle retirees de l'environnement. C'etait vrai, et tenu par rien. Un test qui appellerait
# une API passerait au vert sur une machine connectee et casserait chez qui clone.
# # Risque concret ici : Whisper TELECHARGE son modele au premier usage. Un test qui toucherait la transcription tirerait des centaines de Mo, sans que rien ne l'annonce.
#
# La boucle locale reste ouverte : la couverture et le debogueur s'en servent, et l'interdire
# testerait pytest plutot que le produit.
#
# La PREUVE que ce blocage mord vit dans `test_la_suite_ne_sort_pas_du_poste.py` — un fichier que pytest COLLECTE.
# Le meme controle ecrit ici ne tournerait jamais, et le compte de tests ne bougerait pas.
import socket as _socket

_CONNECT = _socket.socket.connect
_CONNECT_EX = _socket.socket.connect_ex


class SortieReseauInterdite(RuntimeError):
    """Un test a tente de sortir. La suite n'est pas censee en avoir besoin."""


def _est_local(adresse) -> bool:
    try:
        hote = adresse[0]
    except (TypeError, IndexError):
        return False
    return hote in {"127.0.0.1", "::1", "localhost", ""}


def _refuser(vrai):
    def _appel(self, adresse, *a, **kw):
        if not _est_local(adresse):
            raise SortieReseauInterdite(f"sortie reseau vers {adresse!r}")
        return vrai(self, adresse, *a, **kw)
    return _appel


_socket.socket.connect = _refuser(_CONNECT)
_socket.socket.connect_ex = _refuser(_CONNECT_EX)
