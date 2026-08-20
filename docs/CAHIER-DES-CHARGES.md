# Cahier des charges — wzmontage

**Produit** : outil de montage de gameplay Warzone **dirigé par chat**, spécialisé **prox-chat**, pour joueurs TikTok qui ne savent pas monter.
**Date** : 2026-06-23 · **Statut** : validé en cadrage (séquencement décidé), à découper en plans par pilier.

---

## 1. Vision produit

Le joueur dépose ses VODs et **dirige le montage en langage naturel** via un chat :
> « garde les vannes prox-chat, monte vers le 1v4, vertical 30s, mets un overlay Uchiha sur le 1v4, finis sur le wipe »

Le programme détecte les bons moments, **les coupe au bon moment**, et applique ce que le chat demande (styles, overlays, effets, voix). Cible = joueurs TikTok non-monteurs.

**Différenciateurs** (vs Eklipse/Allstar/Medal qui auto-clippent mais laissent l'assemblage manuel) :
1. **Chat-direction** en langage naturel (on pilote tout le montage en parlant).
2. Spécialisation **prox-chat** (récupérer les vannes vocales ennemies = le contenu drôle/viral).

---

## 2. Architecture — 3 piliers

1. **LE MOTEUR (fondation)** — détecter → sélectionner → **couper au bon moment** → assembler. C'est la base : un chat qui pilote des cuts pourris ne vaut rien.
2. **LE CHAT DE DIRECTION (le produit)** — interface langage naturel qui traduit les demandes en un **plan de montage** exécuté par le moteur, en itératif. Livré en **app web**.
3. **LES CAPACITÉS OPT-IN (commandées par le chat)** — effets, overlays + assets (anime/Naruto), capture voix prox-chat, musique, formats. **Tout OFF par défaut**, activé seulement sur demande.

---

## 3. Séquencement (décidé)

1. **Pilier 1 — Moteur (cut-quality)** : EN PREMIER. C'est le sous-projet courant (détaillé §4).
2. **Pilier 2 — Chat de direction** : ensuite, en **vraie app web**.
3. **Pilier 3 — Capacités opt-in** : au fil des demandes, branchées sur le chat.

Chaque pilier = un sous-projet avec son propre plan (spec → plan → implémentation TDD + red team).

---

## 4. PILIER 1 — Le moteur (sous-projet courant, détaillé)

### 4.1 Exigences fonctionnelles
- **C1 Détection** : kills/knock/elim (compteur 💀 + bandeau) + mort du joueur. Inchangé.
- **C2 Sélection** : scorer/classer les moments, respecter le budget durée.
- **C3 Cut-IN** : début ~3s avant l'engagement. **Déjà validé, inchangé.**
- **C4 Cut-OUT sur l'action** (le fix principal) : la fin est ancrée sur **la fin réelle de l'action**, pas sur un délai fixe ni sur le beat.
  - corriger le retard du bandeau (~0,4s) sur l'ancre de fin ;
  - couper quand **l'énergie audio retombe** (plus de tir/explosion), via décroissance RMS ;
  - **lead-out ~1,0-1,2s** ("un peu de respiration" : le temps de voir le 💀 monter), puis couper ;
  - le **beat ne déplace la fin que de ≤100 ms, jamais vers le tard**.
- **C5 Marche coupée (un seul clip)** : si un segment contient deux fights séparés par un trou mort (pas d'event + énergie basse au-delà d'un seuil), **on excise le trou** et on recolle les sous-segments actifs en **un seul clip**.
- **C6 Assemblage** : concat des segments, audio du jeu par défaut.

### 4.2 Critères d'acceptation (= ce que les tests vérifient)
- **A1** : après le dernier kill, temps mort de fin ≤ ~1,2s (fini le tail systématique de 1,5s+).
- **A2** : un trou mort interne > seuil (≈3-4s, énergie basse, sans event) est **retiré** → le clip = somme des sous-segments actifs.
- **A3** : le cut-out se cale sur la chute d'énergie audio si elle survient avant le lead-out max.
- **A4** : le beat-snap ne déplace la fin que de ≤100 ms et **jamais vers le tard**.
- **A5** : sans flag d'effet, la sortie ne contient **aucun** effet ; `beat_sync` et `order:hook` sont **OFF par défaut**.
- **A6** : aucune régression sur la détection/sélection existante (les 45 tests actuels restent verts).

### 4.3 Design technique (cible)
- Logique de cut isolée en **fonctions pures testables** sans ffmpeg, ex. :
  `compute_segments(events, audio_env, cfg) -> list[(start, end)]` (gère C4 + C5).
- L'enveloppe d'énergie audio (RMS lissée) est calculée par `audio.py` (déjà la base pour les action-peaks) et passée à la sélection.
- Bascule des défauts : `beat_sync: false`, `order: chronological` ; fallback `cfg.get("beat_sync", False)`.

---

## 5. PILIER 2 — Le chat de direction (web app) — cadré, à détailler plus tard

- **Cerveau** : LLM **Claude API**. Entrée = la liste des moments détectés par le moteur (timestamps + métadonnées : type, score, prox-chat présent, etc.) + la demande en langage naturel. Sortie = un **plan de montage structuré** (EDL : quels moments, ordre, cuts, format, durée, options/effets/overlays par moment) que le moteur exécute.
- **Itératif** : « plus court », « enlève le 2e kill », « mets l'overlay plus tôt » → le plan se met à jour, re-render.
- **App web** : dépôt des VODs, chat, prévisualisation, téléchargement. (Stack à décider au plan du pilier : back Python/FastAPI réutilisant le moteur, front à choisir.)
- **MVP existant** à généraliser : les flags EDL `--add/--drop/--first` sont déjà la version "commandes" — le chat = la couche langage par-dessus.

---

## 6. PILIER 3 — Capacités opt-in (commandées par le chat, OFF par défaut)

- **Effets** (déjà codés dans `effects.py`/`compositor.py`, gardés optionnels) : zoom-punch, ralenti/"boom", beat-fx, sfx, transitions, speed.
- **Overlays + bibliothèque d'assets** : incrustation image/GIF (`overlays.py` existe) ; nécessite une **bibliothèque d'assets** (anime/Uchiha, flammes…). *Risque : curation des assets + IP anime (zone grise).*
- **Capture prox-chat (voix)** : détecter les segments où une **voix ennemie** parle (VAD/whisper), confirmés par le **signal visuel** (noms ennemis en rouge à droite), et garder ces moments + leur audio. *Risque : isoler proprement l'audio prox-chat.*
- **Musique** + **formats** (vertical/horizontal/carré), déjà en place.

---

## 7. Exigences non-fonctionnelles

- **Tout dans le programme**, pas de ffmpeg jetable à la main.
- **Effets OFF par défaut** ; aucun effet sans demande explicite (chat/flag).
- **Logique de décision = fonctions pures, déterministes, testées** (TDD) ; mêmes entrées → mêmes décisions.
- **Vérification adverse (red team)** à la fin de chaque sous-projet.
- **Environnement** : venv `C:\Users\blanc\bottrade\venv` (cv2/librosa) + ffmpeg WinGet. En arrière-plan, PATH à exporter (ni python ni ffmpeg par défaut).

---

## 8. Hors-périmètre (non-objectifs actuels)

- Détection YOLO/serveur (Phase 2, au scaling).
- Les effets eux-mêmes (déjà codés ; ici on les garde seulement optionnels).
- Comptes/paiement (la validation Phase 0 = faire payer 10€ sur un clip livré à la main, séparé).

---

## 9. Découpage en sous-projets (chacun aura son plan)

1. **SP1 — Moteur cut-quality** (courant) : C4 cut-out sur l'action + C5 marche coupée + A5 défauts effets off. → plan + TDD + red team.
2. **SP2 — Chat de direction (web)** : moteur exposé en service + cerveau Claude API + app web.
3. **SP3 — Modules opt-in** : overlays/assets, capture prox-chat, presets de style.
