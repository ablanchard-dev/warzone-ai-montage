# -*- coding: utf-8 -*-
"""Primitives d'overlays (couche 1). Toutes OPTIONNELLES : posées par la timeline,
jamais automatiques.

- text_overlay : texte hype animé (hook, "BOOM", call-outs). drawtext, police bundlée
  (assets/fonts/impact.ttf), fade-in. Pour le texte UTILISATEUR : `textfile=` (le texte
  est écrit dans un fichier, jamais concaténé dans le filtre → pas d'injection — cf. sécu).
- image_overlay / gif_overlay : sticker/meme/GIF/asset anime posé à une position, sur une
  fenêtre temporelle. overlay filter (transparence respectée). Prouvés sur clip réel
  (overlay_text.png, overlay_image.png vérifiées le 2026-06-15).
"""
from __future__ import annotations

DEFAULT_FONT = "assets/fonts/impact.ttf"  # relatif au cwd : évite le ':' du lecteur Windows


def _escape_drawtext(s: str) -> str:
    """Rend le texte INLINE inoffensif pour drawtext.

    Deux défauts corrigés le 15/08, tous deux **mesurés en lançant ffmpeg** :

    1. Les séparateurs ``,`` ``;`` ``[`` ``]`` n'étaient pas échappés du tout. Un
       texte contenant une virgule SORTAIT du filtre : ``text="x,drawbox=c=red@1"``
       produisait un graphe contenant un vrai ``drawbox``. Avant d'être une injection,
       c'était un bug de correction — un simple « salut, ça va » cassait le rendu.
    2. Le ``:`` était échappé avec UN backslash, et ffmpeg refusait quand même le
       graphe. Il en faut **DEUX** : le ``:`` est consommé à la fois par l'analyseur
       de filtergraph et par celui des arguments de filtre, là où ``,`` ne l'est que
       par un seul. Cette asymétrie n'est pas devinable — elle a été établie en
       essayant chaque forme sur un rendu réel.

    Pour du texte utilisateur, ``textfile=`` reste recommandé : rien n'est concaténé
    dans le filtre du tout, donc aucun échappement à faire confiance.
    """
    out = s.replace("\\", "\\\\")
    out = out.replace(":", "\\\\:")        # DEUX backslashes : deux niveaux d'analyse
    for c in ("'", "%", ",", ";", "[", "]"):
        out = out.replace(c, "\\" + c)
    return out


def _escape_path(p: str) -> str:
    """Rend un CHEMIN utilisable dans une option de filtre ffmpeg.

    Le piège est le `:` du lecteur Windows : `textfile=C:/…` fait échouer le graphe
    (« No option name near '/Users/…' » — mesuré). `DEFAULT_FONT` contourne le
    problème en restant relatif au cwd, mais un appelant qui passe un chemin absolu
    — ce que produit naturellement un outil piloté au chat — tombait dedans, y
    compris sur `textfile=`, **la voie pourtant recommandée pour le texte utilisateur**.

    Mêmes règles que pour le texte : le `:` prend DEUX backslashes (deux niveaux
    d'analyse), les autres séparateurs un seul. Les antislashs Windows sont d'abord
    convertis en `/`, que ffmpeg accepte partout.
    """
    out = p.replace("\\", "/")
    out = out.replace(":", "\\\\:")
    for c in ("'", ",", ";", "[", "]"):
        out = out.replace(c, "\\" + c)
    return out


def text_overlay(t0: float, t1: float, text: str | None = None,
                 textfile: str | None = None, fontfile: str = DEFAULT_FONT,
                 fontsize: int = 200, color: str = "white", border: int = 12,
                 x: str = "(w-text_w)/2", y: str = "(h-text_h)/2",
                 fade: float = 0.1) -> str:
    """Fragment drawtext : texte visible [t0,t1] avec fade-in `fade`. Fournir `text`
    (interne, échappé) OU `textfile` (recommandé pour le texte utilisateur)."""
    if textfile:
        src = f"textfile={_escape_path(textfile)}"
    elif text is not None:
        src = f"text={_escape_drawtext(text)}"
    else:
        raise ValueError("text ou textfile requis")
    alpha = (f"alpha='if(lt(t,{t0:.3f}),0,if(lt(t,{t0 + fade:.3f}),"
             f"(t-{t0:.3f})/{fade:.3f},1))'")
    return (f"drawtext=fontfile={_escape_path(fontfile)}:{src}:fontcolor={color}:fontsize={fontsize}:"
            f"borderw={border}:bordercolor=black:x={x}:y={y}:"
            f"enable='between(t,{t0:.3f},{t1:.3f})':{alpha}")


def image_overlay(x: str = "W-w-40", y: str = "40", t0: float = 0.0,
                  t1: float | None = None) -> str:
    """Fragment overlay pour une image/sticker (2e input). À utiliser dans un
    filter_complex : `[base][img]` + ce fragment + `[v]`. Position x/y (expressions
    overlay : W,H = base ; w,h = overlay). Fenêtre [t0,t1] (t1=None → jusqu'à la fin).
    L'input image s'ajoute via `-i sticker.png`."""
    en = f":enable='between(t,{t0:.3f},{t1:.3f})'" if t1 is not None else ""
    return f"overlay=x={x}:y={y}{en}"


def gif_overlay(x: str = "W-w-40", y: str = "40", t0: float = 0.0,
                t1: float | None = None) -> str:
    """Comme image_overlay, pour un GIF animé. L'input s'ajoute avec la boucle activée :
    `-ignore_loop 0 -i meme.gif` (sinon le GIF ne joue qu'une fois)."""
    return image_overlay(x, y, t0, t1)
