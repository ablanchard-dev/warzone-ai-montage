# Phase A — Primitives de rendu : TERMINÉE (2026-06-15)

Loop auto-rythmé. Chaque primitive : recherche → preuve par rendu réel sur les clips
ShadowPlay (`C:\Users\blanc\Videos\NVIDIA\Call of Duty  Black Ops 7\`, clips du 14/06)
→ codification. Sorties de test : `wzmontage/out_phaseA/`. Local, gratuit (zéro hébergement).

**RÈGLE PRODUIT (user 15/06) :** tous les effets/overlays/layouts sont des OPTIONS,
jamais forcés "à chaque fois". L'auto sur les kills = un défaut activable/désactivable,
et tout reste modifiable. Les primitives ne se déclenchent que si la timeline les appelle.

## Effets — `wzmontage/effects.py`
- [x] **zoom_punch** — scale(eval=frame, piloté par `t`) + crop centré (évite le jitter zoompan). Multi-kill = max des triangles. Prouvé (frames normal/peak + auto-test).
- [x] **shake** — crop + offset sin amorti (x/y fréquences ≠), marge via upscale. Prouvé (déplacement inter-frame +4.4 vs ref).
- [x] **slowmo** — `setpts*PTS` + `minterpolate` (optical flow). Prouvé : 1s→2.43s @60fps. Caveat CPU (~30s/1s 1080p) → fenêtres courtes.

## Layouts & transitions — `wzmontage/layouts.py`
- [x] **facecam_top** — facecam haut + gameplay blur-fill bas → 1080x1920, HUD entier préservé. Prouvé (frame vérifiée).
- [x] **transition_xfade** — flash/whip/cut entre segments (xfade). Prouvé (fadewhite, 2.7s).

## Overlays — `wzmontage/overlays.py`
- [x] **text** — drawtext, police bundlée Impact, fade-in. `textfile=` pour texte user (anti-injection). Prouvé ("BOOM").
- [x] **image / gif / anime** — overlay filter, position + fenêtre. GIF via `-ignore_loop 0`. Prouvé (sticker incrusté).

## Sound design — `wzmontage/sfx.py`
- [x] **sfx_mix** — adelay + amix. Prouvé : +13 dB sur la fenêtre du punch.

## Bibliothèque d'assets — `assets/`
- [x] structure `fonts/ anime/ memes/ sfx/` + `manifest.json` + `README.md`. Bundlés : `fonts/impact.ttf`, `sfx/punch.wav`. Réfs résolues uniquement ici ou uploads user (sécu §12).

## Notes techniques apprises
- `crop` : pas d'`eval=frame` pour w/h (dims figées) → zoom = `scale` time-varying + crop fixe.
- Chemins en DUR dans Python = pas convertis par MSYS → utiliser `C:/...` (pas `/c/...`) dans les littéraux Python ; les args passés par bash, eux, sont convertis.
- `-ss`/`-t` AVANT `-i` = options d'entrée (fenêtre lue) ; APRÈS = sortie (tronque).
- drawtext + chemin Windows `C:` casse le parseur → bundler la police, chemin relatif.
- ffmpeg 8.0.1. Clips 1920x1080 60fps. Forcer dims paires (yuv420p).
- **xfade / tout re-encodage : TOUJOURS forcer `-pix_fmt yuv420p`** (sinon dérive en yuv444p = "paramètre d'encodage non pris en charge" sur les lecteurs Windows). Corrigé dans `_concat_xfade`, `_extract`, sorties subs/copy + `-movflags +faststart`.

## Phase B — moteur (le PROGRAMME monte) : EN COURS
- [x] **compositor.py** — compose une *spec* (layout + effets + overlays) en un filtergraph et rend le segment. Le programme monte depuis une spec, pas de ffmpeg à la main.
- [x] **Intégration `main.py --fx`** — `python main.py <clips> --fx -f vertical` détecte les kills (kill_times câblés dans Candidate/scoring) → compose zoom-punch + shake auto sur chaque kill → sort le montage vertical. Prouvé end-to-end sur le clip 14/06 (3 moments, 2×2K, sortie 1080x1920 23s). `--fx` OFF par défaut (pipeline existant intact).
- [x] **facecam_top dans --fx** (`main.py --layout facecam-top`) — prouvé (facecam_fx.mp4, 1080x1920).
- [x] **SFX punch dans --fx** — `montage.py:_add_sfx` (post-étape isolée, vidéo copiée → n'altère pas le rendu vidéo ni le mix musique). Mix punch sur chaque kill.
- [x] **Transitions entre segments** — `montage.py:_concat_xfade` + `main.py --transitions <kind>` (fade/fadewhite/wipe…). Chemin optionnel ; concat franc reste le défaut. xfade vidéo + acrossfade audio. Prouvé (4.02+4.02→7.75s).
- [x] **VALIDÉ END-TO-END** : `python main.py "<clip>" --fx --transitions fadewhite -f vertical` → détection kills → montage vertical 1080x1920 22.6s avec zoom-punch+shake+SFX sur kills + transitions flash. UNE commande, pipeline existant intact (fx/transitions OFF par défaut). (2026-06-15)
- [x] **Effets retravaillés (retour Alex)** : zoom-punch SUBTIL (peak 1.18) qui démarre PILE sur le kill (montée 0.08s) ; **shake auto SUPPRIMÉ** ; effets uniquement sur le gameplay net (pas le fond flou). Sorties **yuv420p + faststart**.
- [x] **BUG ZOOM "cam bizarre" DIAGNOSTIQUÉ + RÉGLÉ** (méthode : point blanc statique traqué image par image avec cv2). L'approche `scale=eval=frame`+`crop` ancrait au coin haut-gauche (le lien filtergraph garde la taille d'init → crop ne peut pas centrer) → l'image glissait en bas-droite + zoom réel 1.62 au lieu de 1.18. **Refait avec `zoompan`** (centrage interne par frame) → mesuré : y stable 540→542, zoom max 1.183. C'est `effects.zoom_punch_filter`.
- [x] **Option `--audio {game|mix|music|clean}`** — `main.py`. Défaut **game** = son du jeu + **prox-chat** gardés (le moat), rien coupé. mix = jeu+musique, music = musique seule, clean = muet (pour son TikTok au post). Testé mode music (song_full.mp3 sur 16.16).
- [x] **ZOOM VALIDÉ PAR ALEX ("beaucoup mieux")** : zoompan centré + subtil 1.18 + punch net (atk 0.08 / rel 0.18) + **kill_lead 0.4s** (tiré avant le bandeau "ENNEMI ABATTU" qui arrive ~0.4s après le vrai kill) + fg-only. Tout via les défauts `--fx`. C'est verrouillé.
- [x] **Effets = options INDÉPENDANTES** (retour Alex) : `--zoom`, `--sfx`, `--fx`(=les deux), `--layout`, `--audio {game|mix|music|clean}` (défaut game = jeu+prox-chat), `--transitions`, `--max-seconds`. Rien d'imposé.
- [x] **BUG SLOWMO réglé** : `zoompan` recevait le fps de SORTIE (30) alors que la source est 60 → ralenti 2×. Fix = `zoompan` tourne au fps SOURCE (probé via `_probe_dims`), la cadence finale reste gérée par le layout/`-r`. Prouvé (point statique : punch à 1.1s à 30fps de sortie).
- [x] **DÉTECTION KILLS RÉÉCRITE (OCR) — make-or-break** : le rouge seul flaguait "COÉQUIPIER À TERRE" + "VOUS ÊTES À TERRE" (ta mort) comme kills (tous rouges sur BO7). Maintenant : trigger rouge → **OCR (rapidocr-onnxruntime, pip gratuit) +0.5s** → garde QUE "ENNEMI ABATTU/ÉLIMINATION", jette pote+faux positifs, flague 'death'. Prouvé sur les 3 clips (faux positif 84.4 éliminé, 3K récupéré, décisions limites vérifiées). `killdetect.py`.
- [x] **Death-trim** (retour Alex "tjr le clip où je meurs") : le segment se termine AVANT que tu sois à terre/mort. Méthode prouvée par diagnostic image par image : ta mort (frappe de précision ~0.7s après le kill 21.8s du clip 16.31) = PAS un bandeau rouge haut-droite mais le prompt de self-revive au CENTRE-BAS « MAINTENEZ … POUR VOUS RÉANIMER OU … POUR ABANDONNER ». Détecteur = OCR de la bande y≈0.79 (upscale ×2), mots **RÉANIMER/ABANDONNER** (prouvé : 4/4 downed=True, 5/5 normal=False, 0 faux positif). `killdetect._is_downed` + passe 3 (scan ~5s/4fps après CHAQUE kill → émet un event 'death' à l'apparition de l'état à terre). `scoring.build_candidates` : borne DURE `end = death_t − death_guard_s(0.4)` appliquée APRÈS les clamps ; `action_end` (lead-out) basé sur les events ≠ death ; `kill_times` filtrés `< end` (pas de zoom sur le kill suicide rogné). Détecté sur 16.31 : death=22.5s → segment coupé à 22.1s (les 2 kills 13.8/21.8 gardés). **VÉRIFIÉ END-TO-END** : montage v4 des 3 clips ranked → segment 16.31 passe de `12-23s` (v3, montrait la mise à terre) à `12-22s` ; frames du montage à 32.8-34.0s = gameplay vivant (arme levée) puis flash → segment suivant, JAMAIS le prompt de réanimation ; scan du détecteur sur TOUTE la v4 = **0 frame "à terre"**. La mort a disparu du montage final.
- [~] **BEAT-DRIVEN (en cours, le levier "monté")** : caler les effets sur le BEAT, pas juste le kill.
  - **Découverte** : `librosa` n'était PAS installé dans le venv (`bottrade/venv`) → `analyze_music` levait `ModuleNotFoundError`, avalé par le `except` → **`beat_sync` n'a JAMAIS tourné** (no-op silencieux). Installé (`pip install librosa`). song_full.mp3 = 119.7 BPM, 263 beats (~0.5s).
  - **Option `--beat-fx`** (indépendante, off par défaut ; nécessite `-m … --audio mix/music` + `--zoom/--fx`) : punchs de zoom DOUX (peak 1.08 vs 1.18 kills) calés sur les beats RÉELS tombant dans chaque segment (1 sur `beat_fx_stride`=2, dédup vs kills) → le clip pulse au tempo. `effects.zoom_punch_filter(peaks=…)` (pic par-centre), `compositor` passe `zoom_peaks`, `montage` calcule les beats-dans-le-segment via l'offset timeline.
  - **CUTS CALÉS SUR LE BEAT (phase-aware)** — remplace l'ancienne quantif "durée = multiple du beat" (qui ne calait rien sans phase). Maintenant la FIN de chaque segment tombe sur le plus grand beat ≤ fin naturelle (jamais au-delà → respecte death-trim/max_clip), ≥ min_clip ; segments contigus → chaque coupe tombe sur un beat. Grille `beats_timeline` (music-local, avec boucles), calage en espace music-local via `intro_offset`. Validé : 5 coupes test toutes `sur_beat=True` + `dur≤nat` (death-safe). (Retour Alex "caler les coupes sur le beat".)
  - **lead_in 2.0 → 3.0s** (retour Alex "manque le début de l'action") : investigué sur 16.31 — l'engagement est visible ~2.8s avant le 1er kill (ennemi en vue à 11.0s, kill 13.8s), le lead-in 2s rognait le début. À ajuster avec lui (compromis temps mort).
  - Reste : juger le rendu (goût Alex) ; interaction beat-fx × transitions (drift d'offset) ; ⚠️ **`merge_gap=15s` sur-fusionne** (16.31 : kills 14s & 21.8s = 2 plays distincts + ~7s de repositionnement mort entre) → peut-être splitter si grand trou sans action.
- [x] **MEILLEURE ACTION EN OUVERTURE (hook)** — retour Alex "le programme ne met pas la meilleure action en premier". Config `order: chronological → hook` (le code gérait déjà `hook` : le plus haut score ouvre, le reste en montée). Avec les 3 clips ranked, le 3K (score 7.9) ouvre désormais le montage.
- [x] **CACHE DE DÉTECTION** — `killdetect.detect_kill_banners(cache_dir=".wz_detcache")` : events par clip en JSON, clé = chemin+mtime+taille+params. La vision (OCR, lente ~140s/clip) ne tourne qu'une fois ; re-render quasi instantané (itérer ordre/pulse/effets sans re-détecter). Flags CLI `--beat-peak`/`--beat-stride` pour régler le pulse à la volée (override cfg).
- [ ] **pulse beat-fx à régler** (retour Alex "à ajuster", direction non précisée) → sortir variantes douce/forte depuis le cache, lui faire choisir.
- [ ] **speed-ramp sur beat** (ralenti/accéléré calé tempo) — `effects.slowmo_filter` existe, à câbler.
- [ ] Reste (avec Alex) : durée = option `--max-seconds` (existe) ; slowmo→speed-ramp sur beat ; images/gif/texte à la demande ; couper QUE sa voix en gardant le prox-chat.
- [ ] transitions (xfade) ENTRE segments dans build_montage
- [ ] modèle timeline persistant + UI d'édition (bouger/éditer chaque op)

## Phase C (NE PAS faire en autonome — besoin du feu vert d'Alex)
- Chat NL (Claude côté serveur) : "Uchiha sur le 1v4" → remplit la spec → le programme exécute.
  Touche sa clé API (pennies) + décision produit → à valider avec lui d'abord.
