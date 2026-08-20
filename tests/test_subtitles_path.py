"""Les sous-titres : le chemin entre DANS le filtre, donc il doit être échappé.

`montage.py` construit `-vf subtitles={srt}:force_style=...`. Le fichier `.srt` vit
dans un dossier TEMPORAIRE, donc un chemin ABSOLU Windows. Mesuré le 15/08 : ffmpeg
avalait les antislashs et lisait le reste comme une taille d'image —
« Unable to parse option value "UsersblancAppData..." as image size ».
**La fonctionnalité sous-titres ne marchait donc jamais sur cette machine**, et
l'échec n'arrivait qu'au rendu final, avec un message qui n'accuse pas le chemin.

Distinction utile trouvée en balayant : tous les AUTRES chemins du montage (musique,
punch, segments, sortie) passent par `-i` ou en argument — ils ne traversent aucun
analyseur de filtre et n'ont donc jamais eu ce problème.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from wzmontage.overlays import _escape_path  # noqa: E402

SOURCE_MONTAGE = (RACINE / "wzmontage" / "montage.py").read_text(encoding="utf-8")


def test_le_chemin_des_sous_titres_est_echappe_dans_le_filtre():
    """Lecture des sources : un câblage manquant ne lève jamais d'erreur ici,
    il produit juste un rendu qui échoue chez l'utilisateur."""
    ligne = next(l for l in SOURCE_MONTAGE.splitlines() if "subtitles=" in l)
    assert "_escape_path" in ligne, \
        f"le chemin des sous-titres entre nu dans le filtre : {ligne.strip()}"


def test_les_autres_chemins_restent_des_ARGUMENTS():
    """Garde-fou de portée : si un futur changement déplaçait la musique ou le
    punch dans un filtergraph, il faudrait les échapper aussi."""
    for motif in (r'"-i", str\(music_path\)', r'"-i", str\(_PUNCH\)'):
        assert re.search(motif, SOURCE_MONTAGE), \
            f"{motif} n'est plus passé en argument : vérifier l'échappement"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent")
def test_ffmpeg_accepte_un_srt_en_chemin_absolu(tmp_path):
    """La preuve qui compte : le rendu passe avec un vrai chemin temporaire."""
    srt = tmp_path / "subs.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nTEST\n\n", encoding="utf-8")
    base = tmp_path / "base.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc=size=320x180:rate=25:duration=1", "-t", "1",
         "-c:v", "libx264", "-preset", "ultrafast", str(base)], check=True)
    sortie = tmp_path / "out.mp4"
    r = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(base),
         "-vf", f"subtitles={_escape_path(str(srt))}:"
                f"force_style='Fontsize=18,Outline=2,Alignment=2'",
         "-pix_fmt", "yuv420p", str(sortie)],
        capture_output=True, text=True)
    assert sortie.exists() and sortie.stat().st_size > 0, \
        f"les sous-titres échouent sur un chemin absolu : {r.stderr.strip()[:200]}"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent")
def test_le_chemin_NON_echappe_echoue_vraiment(tmp_path):
    """Preuve que le correctif porte sur un défaut RÉEL, pas imaginaire :
    la forme d'origine doit échouer sur la même machine."""
    srt = tmp_path / "subs.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nTEST\n\n", encoding="utf-8")
    base = tmp_path / "base.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc=size=320x180:rate=25:duration=1", "-t", "1",
         "-c:v", "libx264", "-preset", "ultrafast", str(base)], check=True)
    sortie = tmp_path / "out_nu.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(base),
         "-vf", f"subtitles={srt}:force_style='Fontsize=18,Outline=2,Alignment=2'",
         "-pix_fmt", "yuv420p", str(sortie)],
        capture_output=True, text=True)
    assert not sortie.exists() or sortie.stat().st_size == 0, \
        "le chemin nu passe : ce système n'a pas le défaut, l'échappement reste inoffensif"
