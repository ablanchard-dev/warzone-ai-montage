"""`--sfx` ne doit pas être muet sur un clone neuf.

Mesuré le 17/09 : `.gitignore` exclut `*.wav`, donc `assets/sfx/punch.wav` n'existe que sur la
machine d'Alex. Sur un clone, `_add_sfx` voyait le fichier absent et rendait le segment tel quel,
sans un mot : `--sfx` et `--fx` (annoncés dans le README) ne produisaient aucun son. La mesure du
15/08 (« SHA-256 différent ») avait été faite là où le fichier existait.
"""
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wzmontage import montage  # noqa: E402


def test_sans_punch_wav_un_son_est_genere_et_il_n_est_pas_silencieux(tmp_path, monkeypatch):
    monkeypatch.setattr(montage, "_PUNCH", tmp_path / "absent" / "punch.wav")
    src = montage._punch_source(tmp_path)
    assert src.exists()
    with wave.open(str(src)) as w:
        assert w.getframerate() == 44100 and w.getnchannels() == 1 and w.getsampwidth() == 2
        duree = w.getnframes() / w.getframerate()
        pcm = w.readframes(w.getnframes())
    assert 0.1 <= duree <= 0.4, duree
    crete = max(abs(int.from_bytes(pcm[i:i + 2], "little", signed=True)) for i in range(0, len(pcm), 2))
    assert crete > 8000, "le son généré est quasi silencieux"


def test_un_punch_wav_present_est_utilise_tel_quel(tmp_path, monkeypatch):
    le_sien = tmp_path / "punch.wav"
    le_sien.write_bytes(b"RIFF-son-d-alex")
    monkeypatch.setattr(montage, "_PUNCH", le_sien)
    assert montage._punch_source(tmp_path / "rendu") == le_sien
    assert le_sien.read_bytes() == b"RIFF-son-d-alex"


def test_un_clip_sans_piste_audio_saute_le_sfx_au_lieu_de_faire_planter_le_montage(tmp_path, monkeypatch, capsys):
    # Revue 17/09 : `_extract` ne copie l'audio que s'il existe (-map 0:a?). Sur une source muette,
    # le filtre [0:a]asplit...amix echouait dans ffmpeg et arretait TOUT le montage.
    monkeypatch.setattr(montage, "_PUNCH", tmp_path / "absent" / "punch.wav")
    monkeypatch.setattr(montage, "has_audio", lambda p: False)
    commandes = []
    monkeypatch.setattr(montage, "run", lambda cmd: commandes.append(cmd))
    part = tmp_path / "clip_muet.mp4"
    assert montage._add_sfx(part, [0.5], tmp_path, 0) == part
    assert commandes == []
    assert "audio" in capsys.readouterr().out.lower()


def test_add_sfx_mixe_bien_un_son_quand_le_fichier_du_depot_manque(tmp_path, monkeypatch):
    monkeypatch.setattr(montage, "_PUNCH", tmp_path / "absent" / "punch.wav")
    monkeypatch.setattr(montage, "has_audio", lambda p: True)
    commandes = []
    monkeypatch.setattr(montage, "run", lambda cmd: commandes.append(cmd))
    part = tmp_path / "clip.mp4"
    out = montage._add_sfx(part, [0.5, 1.2], tmp_path, 0)
    assert out != part, "le segment est revenu sans SFX : --sfx muet en silence"
    assert len(commandes) == 1
    entrees = [commandes[0][k + 1] for k, a in enumerate(commandes[0]) if a == "-i"]
    assert len(entrees) == 2 and Path(entrees[1]).exists()
