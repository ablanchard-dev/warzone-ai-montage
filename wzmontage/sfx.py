# -*- coding: utf-8 -*-
"""Sound design (couche 1). OPTIONNEL : posé par la timeline.

sfx_mix : pose un SFX (punch, riser…) à un instant sur l'audio d'un segment. Mix par
adelay + amix (pas de normalize → niveaux maîtrisés). SFX bundlés dans assets/sfx/.
Prouvé : +13 dB sur la fenêtre du punch vs fenêtre calme (2026-06-15).
"""
from __future__ import annotations


def sfx_mix(timestamp: float, sfx_index: int = 1, base_index: int = 0,
            gain: float = 2.0) -> str:
    """Fragment de filter_complex audio → produit le label [a].

    Inputs attendus : `[base_index:a]` = audio du segment, `[sfx_index:a]` = le SFX
    (ajouté via `-i assets/sfx/punch.wav`). Le SFX est décalé à `timestamp` (s)."""
    ms = int(round(timestamp * 1000))
    return (f"[{sfx_index}:a]adelay={ms}|{ms},volume={gain}[sfxd];"
            f"[{base_index}:a][sfxd]amix=inputs=2:duration=first:normalize=0[a]")
