"""Détection des VRAIS kills via le bandeau du HUD + OCR.

Trigger = flash de pixels rouges dans la zone du bandeau (cheap, sans calibrage).
Puis OCR du texte pour ne garder QUE les vrais kills (le rouge seul ne suffit pas :
sur Black Ops 7, "COÉQUIPIER À TERRE" et "VOUS ÊTES À TERRE" sont AUSSI rouges) :
  - "ENNEMI ABATTU" / "ÉLIMINATION"     -> kill (gardé)
  - "COÉQUIPIER À TERRE" (pote)          -> ignoré
  - "VOUS ÊTES À TERRE / ABATTU" (mort)  -> événement 'death' (à éviter au montage)
  - faux positif (rien lu)               -> ignoré

Si l'OCR est indisponible, on retombe sur l'ancien comportement (tout rouge = kill).
"""
from __future__ import annotations

from typing import List

from .models import Event

_OCR = None

# Dégradations constatées pendant l'analyse, à re-signaler À LA FIN du run.
# L'avertissement imprimé au moment où le problème survient est correct, mais il
# défile : sur plusieurs clips, il finit des centaines de lignes au-dessus du
# « ✓ Terminé. ». Le détail était honnête et le mot de la fin mentait par omission.
_DEGRADATIONS: List[str] = []


def degradations() -> List[str]:
    """Raisons pour lesquelles la détection a tourné en mode dégradé (vide si tout va bien)."""
    return list(_DEGRADATIONS)


def _get_ocr():
    """Charge RapidOCR une seule fois. False si indisponible (-> fallback rouge seul)."""
    global _OCR
    if _OCR is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _OCR = RapidOCR()
        except Exception:
            _OCR = False
            # Le repli est VOULU (cf. docstrings ci-dessous), mais il était muet :
            # sans OCR, _classify_banner renvoie "kill" pour TOUT bandeau — donc un
            # montage peut contenir tes morts, et rien ne le disait. On ne change pas
            # le comportement (c'est une décision produit), on le rend visible.
            msg = ("OCR indisponible (rapidocr_onnxruntime absent) : tout bandeau est "
                   "compte KILL et la detection de down retombe sur le rouge seul. "
                   "Le montage peut contenir des morts. -> pip install rapidocr-onnxruntime")
            _DEGRADATIONS.append(msg)
            print("ATTENTION -> " + msg)
    return _OCR


def _red_fraction(bgr_roi) -> float:
    """Fraction de pixels ROUGE vif dans la zone (déclencheur du bandeau)."""
    import cv2

    hsv = cv2.cvtColor(bgr_roi, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    red = (((h <= 8) | (h >= 172)) & (s >= 110) & (v >= 90))
    return float(red.mean())


def _is_downed(frame) -> bool:
    """True si le prompt de self-revive est à l'écran = tu es À TERRE (mort imminente).

    Ce n'est PAS un bandeau rouge haut-droite : quand tu tombes, le jeu affiche au
    CENTRE-BAS « MAINTENEZ [touche] POUR VOUS RÉANIMER OU [touche] POUR ABANDONNER ».
    On OCR cette bande (y≈0.79, upscale ×2) et on cherche RÉANIMER / ABANDONNER —
    mots qui n'apparaissent QUE dans cet état (prouvé : 0 faux positif sur les 3 clips)."""
    import cv2

    ocr = _get_ocr()
    if not ocr:
        return False
    h, w = frame.shape[:2]
    roi = frame[int(0.74 * h):int(0.86 * h), int(0.28 * w):int(0.74 * w)]
    if not roi.size:
        return False
    roi = cv2.resize(roi, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    res, _ = ocr(roi)
    txt = ("".join(r[1] for r in res)).upper() if res else ""
    return "REANIM" in txt or "ABANDONN" in txt


def _strip_accents(s: str) -> str:
    """Sans ça, « ÉLIMINATION » ne matchait PAS le motif 'ELIMINAT' : l'OCR rend le É
    accentué. Seul « ENNEMI » sauvait la détection — donc une élimination annoncée
    sans le mot « ennemi » passait en 'skip', silencieusement."""
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _classify_banner(frame) -> str:
    """OCR le bandeau haut-droite -> 'knock' | 'elim' | 'death' | 'skip'.

    KNOCK vs ELIM : « ENNEMI ABATTU / À TERRE » = tu l'as mis à terre (le FIGHT, ce
    qu'on montre) ; « ÉLIMINATION / ÉLIMINÉ » = la confirmation (la validation). Les
    deux produisent un bandeau rouge, donc DEUX événements pour UN SEUL adversaire.
    Le modèle (`models.Event`) et `scoring.KILLY` prévoyaient déjà ces deux types ;
    seule cette fonction les écrasait en 'kill', rendant la règle « couper sur le
    knock, pas le confirm » inapplicable et gonflant le compte de kills.

    Renvoie 'kill' (type neutre, déjà dans KILLY) si l'OCR est indisponible : on ne
    sait pas lequel des deux c'est, et inventer serait pire que rester neutre."""
    ocr = _get_ocr()
    if not ocr:
        return "kill"
    h, w = frame.shape[:2]
    roi = frame[int(0.07 * h):int(0.36 * h), int(0.66 * w):w]   # bandeaux empilés haut-droite
    res, _ = ocr(roi)
    txt = _strip_accents(("".join(r[1] for r in res)).upper()) if res else ""
    if "VOUS" in txt:                          # VOUS ÊTES À TERRE/ABATTU = ta mort
        return "death"
    if "COEQUIPIER" in txt or "EQUIPIER" in txt:
        return "skip"                          # AVANT tout le reste : « COÉQUIPIER À TERRE »
    if "ELIMIN" in txt:                        # ELIMINATION / ENNEMI ELIMINE -> le confirm
        return "elim"                          # (testé AVANT 'ENNEMI' : les deux coexistent)
    if "ENNEMI" in txt or "ABATTU" in txt:
        return "knock"                         # ENNEMI ABATTU -> le fight
    return "skip"                              # faux positif, rien lu, etc.


def merge_knock_confirm(events: List[Event], window_s: float = 10.0) -> List[Event]:
    """Un 'elim' qui suit un 'knock' de moins de `window_s` = LE MÊME adversaire.

    On garde le KNOCK (son instant et son type) et on jette le confirm : c'est
    exactement la règle d'Alex « couper sur le knock, pas le confirm », et ça évite
    de compter un seul ennemi deux fois (ce qui déclenchait à tort les bonus
    multikill de `scoring`, calés sur n_kills >= 2 / 3 / 4).

    Deux 'knock' rapprochés = deux adversaires : on n'y touche PAS.

    `window_s` est un RÉGLAGE, pas une constante physique : la valeur juste dépend de
    ta façon de finir un knock. Mesuré sur les 4 clips en cache, les paires de kills
    rapprochées tombaient entre 2,6 s et 8,0 s — d'où 10 s comme point de départ."""
    out: List[Event] = []
    knock_idx: int | None = None               # index dans `out` du knock en attente
    for e in sorted(events, key=lambda x: x.t):
        if e.type == "knock":
            knock_idx = len(out)
            out.append(e)
            continue
        if e.type == "elim" and knock_idx is not None and (e.t - out[knock_idx].t) <= window_s:
            # Le knock a été CONFIRMÉ : un seul adversaire, mais bel et bien tué.
            # On garde l'INSTANT du knock (la règle de coupe) et on repasse le type à
            # 'kill' — sinon le couple vaudrait 0.6 (valeur d'un knock non confirmé)
            # au lieu de 1.0, et un vrai kill pèserait MOINS qu'un kill instantané.
            k = out[knock_idx]
            out[knock_idx] = Event(k.video, k.t, "kill", k.conf)
            knock_idx = None                   # UN knock n'absorbe qu'UN confirm
            continue
        if e.type == "elim":
            knock_idx = None                   # elim isolé (kill instantané) : on le garde
        out.append(e)
    return out


def detect_kill_banners(video_path, region=(0.79, 0.11, 0.20, 0.13),
                        sample_fps: float = 5.0, fps: float | None = None,
                        min_gap: float = 1.5, on_frac: float = 0.33,
                        ocr_offset: float = 0.5,
                        death_scan_s: float = 5.0, death_scan_fps: float = 4.0,
                        merge_confirm_s: float = 10.0,
                        cache_dir: str = ".wz_detcache", use_cache: bool = True) -> List[Event]:
    """Renvoie les Events de kills RÉELS (type 'kill') + tes morts (type 'death').

    2 temps : (1) on repère les FRONTS MONTANTS rouges (déclencheur cheap, sans calibrage) ;
    (2) pour chaque front, on OCR une frame `ocr_offset` secondes PLUS TARD (le bandeau est
    alors stabilisé/lisible — l'OCR pile sur l'apparition rate le texte en cours d'animation).

    CACHE : la détection vision est lente (OCR). On met en cache les events par clip,
    clé = chemin + mtime + taille + params. Re-render quasi instantané si le clip n'a pas changé.
    """
    import hashlib
    import json
    import os

    params = (region, sample_fps, fps, min_gap, on_frac, ocr_offset,
              death_scan_s, death_scan_fps, merge_confirm_s, "v3-knock-elim")
    cpath = None
    try:
        st = os.stat(video_path)
        key = hashlib.md5(
            f"{os.path.abspath(str(video_path))}|{int(st.st_mtime)}|{st.st_size}|{params}".encode()
        ).hexdigest()
        cpath = os.path.join(cache_dir, key + ".json")
    except OSError:
        cpath = None
    if use_cache and cpath and os.path.exists(cpath):
        with open(cpath, encoding="utf-8") as f:
            data = json.load(f)
        return [Event(d["video"], d["t"], d["type"], d["conf"]) for d in data]

    import cv2

    cap = cv2.VideoCapture(str(video_path))
    if fps is None:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / sample_fps)))

    # --- Passe 1 : fronts montants rouges -> instants candidats ---
    cands: List[float] = []
    idx = 0
    last = -1e9
    active = False
    while True:
        if not cap.grab():
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            t = idx / fps
            h, w = frame.shape[:2]
            x, y, rw, rh = region
            roi = frame[int(y * h):int((y + rh) * h), int(x * w):int((x + rw) * w)]
            frac = _red_fraction(roi) if roi.size else 0.0
            now = frac >= on_frac
            if now and not active and (t - last) >= min_gap:
                cands.append(t)
                last = t
            active = now
        idx += 1

    # --- Passe 2 : OCR un peu après chaque front (bandeau lisible) -> classer ---
    events: List[Event] = []
    for t in cands:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round((t + ocr_offset) * fps)))
        ok, frame = cap.read()
        if not ok:                                  # repli : la frame du front
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
            ok, frame = cap.read()
        if not ok:
            continue
        kind = _classify_banner(frame)              # OCR : knock ? confirm ? pote ? ta mort ?
        if kind in ("knock", "elim", "kill"):
            events.append(Event(str(video_path), float(t), kind, 1.0))
        elif kind == "death":
            events.append(Event(str(video_path), float(t), "death", 1.0))
        # 'skip' (pote / faux positif) -> ignoré

    # --- Passe 3 : ES-TU MORT JUSTE APRÈS UN KILL ? (le cas "je kill puis je suis dead") ---
    # L'état "à terre" (prompt de réanimation au centre-bas) n'est PAS un bandeau rouge
    # haut-droite -> la passe 1/2 ne peut pas le voir. On scanne donc quelques secondes
    # APRÈS chaque kill et, si on trouve l'état à terre, on émet un 'death' à son APPARITION.
    if _get_ocr():
        kills = sorted(e.t for e in events if e.type in ("kill", "knock", "elim"))
        deaths: List[float] = []
        for kt in kills:
            t = kt
            while t <= kt + death_scan_s:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
                ok, frame = cap.read()
                if ok and _is_downed(frame):
                    if all(abs(t - d) > min_gap for d in deaths):
                        deaths.append(t)
                    break                       # mort trouvée pour ce kill -> stop
                t += 1.0 / death_scan_fps
        for d in deaths:
            events.append(Event(str(video_path), float(d), "death", 1.0))

    cap.release()
    # Un 'elim' qui suit son 'knock' = le MÊME adversaire : on absorbe le confirm et
    # on garde l'instant du knock. Fait AVANT la mise en cache pour que le cache
    # contienne le résultat final (la clé porte déjà `merge_confirm_s`).
    events = merge_knock_confirm(events, merge_confirm_s)
    if cpath:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(cpath, "w", encoding="utf-8") as f:
                json.dump([{"video": e.video, "t": e.t, "type": e.type, "conf": e.conf}
                           for e in events], f)
        except OSError:
            pass
    return events
