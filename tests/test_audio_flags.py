"""Aucun drapeau audio ne doit être ignoré en silence.

Piège vécu, noté en mémoire comme « -m seul ne fait rien, il faut --audio mix » :
passer une musique sans le bon mode audio faisait JETER le fichier sans un mot,
et le montage sortait muet. Le sens inverse (--audio mix sans -m) levait déjà une
erreur : la protection existait dans un seul sens.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import resolve_audio  # noqa: E402


def test_musique_avec_mix_est_gardee():
    music, mute, warns = resolve_audio("song.mp3", "mix", False)
    assert music == "song.mp3"
    assert not mute
    assert warns == []


def test_musique_avec_music_coupe_le_jeu_plus_tard_mais_garde_le_fichier():
    music, _, _ = resolve_audio("song.mp3", "music", False)
    assert music == "song.mp3"


def test_musique_SANS_le_bon_mode_audio_leve_une_erreur_au_lieu_de_l_ignorer():
    # LE piège : avant, ceci rendait music=None sans rien dire.
    with pytest.raises(SystemExit) as e:
        resolve_audio("song.mp3", "game", False)
    assert "IGNOR" in str(e.value)
    assert "--audio mix" in str(e.value)


def test_le_message_dit_quoi_faire_pas_seulement_ce_qui_ne_va_pas():
    with pytest.raises(SystemExit) as e:
        resolve_audio("song.mp3", "clean", False)
    msg = str(e.value)
    assert "--audio mix" in msg and "--audio music" in msg


def test_mode_musique_sans_fichier_leve_toujours_une_erreur():
    # La protection qui existait déjà ne doit pas avoir été perdue.
    with pytest.raises(SystemExit):
        resolve_audio(None, "mix", False)


def test_sans_musique_ni_mode_musique_tout_va_bien():
    music, mute, warns = resolve_audio(None, "game", False)
    assert music is None and not mute and warns == []


def test_clean_coupe_le_son():
    _, mute, _ = resolve_audio(None, "clean", False)
    assert mute


def test_mute_gameplay_fonctionne_en_mode_game():
    _, mute, warns = resolve_audio(None, "game", True)
    assert mute
    assert warns == []


def test_mute_gameplay_ignore_ailleurs_est_ANNONCE():
    # Il ne s'applique qu'au mode 'game'. Ailleurs il ne faisait rien, en silence.
    _, mute, warns = resolve_audio("song.mp3", "mix", True)
    assert not mute
    assert warns and "mute-gameplay" in warns[0]
