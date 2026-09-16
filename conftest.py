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
