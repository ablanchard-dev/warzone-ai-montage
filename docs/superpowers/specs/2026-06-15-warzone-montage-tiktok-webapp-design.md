# Cahier des charges — Outil de montage IA Warzone/CoD pour TikTok (app web)

Date : 2026-06-15
Statut : spécification validée en brainstorming, à relire avant plan d'implémentation
Code existant : `C:\Users\blanc\wzmontage\` (package `wzmontage/`, `main.py`, `config.yaml`)

---

## 1. Vision & positionnement

Outil qui prend des **clips Warzone/Call of Duty** et les monte automatiquement en **clips TikTok** prêts à poster, **dirigeable en langage naturel** ("mets un Uchiha sur le 1v4, BOOM ici, vertical 25s").

- **Cible** : joueurs CoD/Warzone qui veulent poster sur TikTok mais ne savent pas monter.
- **Le moat (à protéger)** : spécialisation CoD — détection des kills sans calibrage, lecture du HUD, prox-chat — **plus** la chat-direction. Pas un éditeur vidéo générique.
- **Contrainte produit clé** : ça reste *vraiment* Warzone/CoD, mais l'utilisateur doit pouvoir ajouter de l'**écriture, des images drôles, des GIF, des overlays anime** — toujours au service du contenu CoD.
- **Forme** : application **web SaaS**. Le client n'installe rien, n'a aucun compte Claude, aucune clé. Il envoie ses clips, dirige en chat, télécharge le résultat.

### Principe directeur
Le **programme** fait le montage, pas l'humain à la main (pas de ffmpeg jetable). Tout est une fonction du produit. Le rendu cible n'est pas "des cuts" mais un **edit TikTok hype** (style anime, BOOM synchro sur le drop).

---

## 2. Périmètre

### Dans le périmètre
- Upload de clips (multi-fichiers), détection auto des temps forts, montage TikTok.
- Chat langage naturel pour diriger le montage, **avec tout toujours modifiable** (auto OU manuel).
- Couche d'overlays : texte animé, images, GIF, assets anime ; effets (zoom-punch, shake, ralenti, transitions) ; layouts (facecam-haut, vertical) ; musique beat-sync ; SFX.
- Export vertical 9:16 (+ 16:9 / 1:1 en option).
- Déploiement web sécurisé (clé Claude côté serveur, jamais exposée).

### Hors périmètre (YAGNI — voir §14)
- Éditeur vidéo généraliste (timeline image par image type Premiere).
- Détection multi-jeux (CoD only au départ).
- Reconnaissance faciale, modération auto avancée (au-delà du minimum légal).
- Édition collaborative temps réel multi-utilisateurs.

---

## 3. Utilisateurs & parcours

**Parcours nominal :**
1. Le user se connecte, upload 1..N clips ShadowPlay/Outplayed.
2. Le programme détecte les kills/temps forts et **propose un premier montage** (avec effets auto sur les kills) — la timeline est pré-remplie.
3. Le user **dirige en chat** ("vertical 25s, garde que le 1v4, mets BOOM sur le wipe, son tendance") OU ajuste via les **contrôles visuels** (boutons, drag).
4. Aperçu → itérations conversationnelles ("non, le BOOM plus tôt", "enlève le texte").
5. Export, téléchargement, post.

**Profils :** joueur non-monteur (parcours guidé, défauts forts) ; joueur avancé (chat précis + contrôle fin).

---

## 4. Architecture générale

```
Couche 0 — App web (front Next.js + back FastAPI). LA clé Claude vit ici, côté serveur.
   │
   ├─ Couche 3 — Chat langage naturel : Claude (tool-use) → opérations structurées
   │                                     (édition conversationnelle de la timeline)
   ├─ Couche 2 — Timeline / modèle projet : source de vérité unique. Auto-remplie par la
   │             détection, 100% éditable (par le chat ET par l'UI visuelle).
   └─ Couche 1 — Primitives de rendu : layouts, effets, overlays, SFX, assets.
                 + Moteur existant : détection kills, scoring, EDL, mix audio, rendu ffmpeg.
```

**Flux d'une commande chat :**
`phrase user → Claude (côté serveur) → opérations structurées validées → mutation de la timeline → rendu ffmpeg → vidéo`.

**Pourquoi cette séparation :** le chat NL est une *porte d'entrée*, pas le moteur. Le LLM ne pilote jamais ffmpeg directement ; il produit des ops d'une **liste blanche** que le code valide et exécute. La timeline persiste entre les commandes → "toujours modifiable" + base commune pour le chat ET l'UI visuelle (donc pas de verrouillage au LLM).

---

## 5. Moteur existant (à conserver et étendre)

État vérifié dans le code (2026-06-15). À garder tel quel, exposé comme primitives de la couche 1/2.

### 5.1 Détection (sans calibrage)
- `killdetect.detect_kill_banners` — bandeau rouge "ENNEMI ABATTU" (le knock = le fight). Méthode fiable, zéro template, régions fractionnaires (résolution-indépendant).
- `vision.detect_visual_events` — templates HUD (bonus optionnel, multi-scale).
- `vision.detect_victory` — écran de victoire (OCR tesseract, optionnel).
- `audio.detect_action_peaks` — pics audio (off par défaut).
- `audio.transcribe_voice` — voix/prox-chat (whisper) → segments + sous-titres.

### 5.2 Scoring / sélection
- `scoring.build_candidates` — clusters d'événements → candidats.
- `scoring.select_global` — sélection sous budget de durée.
- Pondérations (config) : multikill, wipe, voix+kill, victoire, merge_gap.

### 5.3 Chat-direction EDL (le différenciateur actuel)
- `--add "clip@last:17" | "clip@A-B"` (forcer un segment, replacé chrono).
- `--drop "clip@A-B"` (retirer un segment auto).
- `--first "clip@A-B"` (épingler en tête = hook).
- `parse_manual_segment` (helper).

### 5.4 Rendu (`montage.build_montage`)
- Formats : `horizontal` / `vertical` / `square` (multi-sortie).
- Vertical 9:16 **blur-fill** (look TikTok).
- `--intro PATH` + `--intro-crop W:H:X:Y` (intro casteurs gardée à 1x, crop facecams).
- `--speed` (gameplay accéléré, intro reste 1x).
- Musique `-m` : **beat-sync** (durées quantifiées sur la grille des temps), musique démarre après l'intro, voix du jeu coupée sur le gameplay, fade out.
- `--mute-gameplay` (clip muet prêt pour un son TikTok natif).
- Sous-titres prox-chat (SRT incrusté, optionnel).
- Concaténation ffmpeg.

### 5.5 Limites connues actuelles
- Détection ~3-4/4 sur clip test ; région/couleur du bandeau calées pour le HUD 1080p (OK Phase 0, à généraliser via YOLO au scaling).
- Jamais tourné en multi-utilisateur / web (CLI local seulement).

---

## 6. Couche 1 — Primitives de rendu (le nouveau)

Chaque primitive = une **fonction du programme**, paramétrable, déclenchable en auto (défauts) et **toujours modifiable**. Toutes générées par le code à partir d'ops validées (jamais de filtergraph brut piloté par l'user/LLM).

### 6.1 Layouts
- `fullscreen` — plein cadre (16:9).
- `vertical_blurfill` — 9:16 fond flou + vidéo centrée (existant).
- `facecam_top` — **stream/facecam en haut + gameplay en bas** (split TikTok gaming). Paramètres : ratio de partage, source facecam (crop d'un coin du clip ou fichier séparé), bordure.
- HUD toujours visible (contrainte : ne jamais cropper le compteur de kills ni le mini-radar).

### 6.2 Effets (sur l'impact)
- `zoom_punch` — zoom rapide sur l'instant du kill (`zoompan`). Auto sur chaque kill détecté, intensité + durée réglables.
- `shake` — secousse caméra (`crop` + oscillation).
- `slowmo` / `speed_ramp` — ralenti/rampe de vitesse sur le gros moment (`setpts` + interpolation).
- `transition` — flash / whip / cut (`xfade`) entre segments.

### 6.3 Overlays
- `text` — texte animé (hook, "BOOM", call-outs de kills). Gros, lisible, style réglable (police, contour, anim d'entrée). **Distinct des sous-titres prox-chat.**
- `image` — image fixe (meme, sticker).
- `gif` — GIF animé en overlay.
- `anime` — assets thématiques (Uchiha/sharingan, flammes) depuis la bibliothèque.
- Communs : position (ancre + offset), début/fin (timestamp ou "sur tel kill"), échelle, opacité, anim.

### 6.4 SFX / sound design
- SFX ponctuels sur les impacts (punch sur kill, riser avant le drop).
- Mix avec la musique et l'audio du jeu (règles existantes : voix jeu coupée sur gameplay).

### 6.5 Bibliothèque d'assets
- **Bundlée** : pack d'overlays anime/memes/SFX/polices vérifiés (licences claires).
- **Perso** : uploads du user (ses propres images/GIF/sons).
- Toute référence d'asset dans une op = résolue **uniquement** vers la lib vérifiée ou les uploads du user (jamais un chemin/URL arbitraire — cf. sécurité §12).

---

## 7. Couche 2 — Modèle timeline / projet

**Source de vérité unique.** Auto-remplie par la détection (ex. `zoom_punch` auto sur chaque kill), **100% éditable** par le chat ET l'UI visuelle. Le rendu se fait *toujours* à partir d'elle.

Forme (illustratif) :
```json
{
  "format": "vertical",            // vertical | horizontal | square
  "duration_target_s": 25,
  "layout": { "type": "facecam_top", "split": 0.28, "facecam": {...} },
  "music": { "track": "asset_id|upload_id", "beat_sync": true },
  "captions": { "enabled": true, "source": "prox_chat", "style": {...} },
  "segments": [
    { "id": "s1", "clip": "upload_id", "start": 104.0, "end": 120.0,
      "speed": 1.15, "is_intro": false,
      "effects": [ { "type": "zoom_punch", "at": 112.3, "intensity": 1.4 } ],
      "overlays": [ { "type": "text", "text": "BOOM", "anchor": "center", "start": 112.0, "end": 113.5 } ] }
  ],
  "global_overlays": [ { "type": "anime", "asset": "uchiha_01", "start": 5.0, "end": 8.0 } ]
}
```

Propriétés :
- Tout objet (segment, effet, overlay, layout, musique) est **adressable et modifiable** individuellement.
- Le rendu = compilation déterministe timeline → commandes ffmpeg (par TON code).
- Sérialisable → persistée par job (reprise, ré-export, historique).

---

## 8. Couche 3 — Chat langage naturel

Le user décrit ; **Claude (côté serveur)** traduit en **opérations structurées** via *tool-use / structured outputs* ; les ops mutent la timeline.

### 8.1 Modèle & paramètres
- Modèle par défaut : **`claude-opus-4-8`** (la doc API impose Opus par défaut ; ne pas downgrader sans décision explicite).
- Option coût : `claude-haiku-4-5` pour le parsing (tâche courte) — **décision d'Alex**, pas par défaut.
- Tâche = "single LLM call" (extraction → ops structurées), pas un agent.
- `tool_choice` **forcé** sur l'outil d'édition → la sortie est *toujours* des ops, jamais du texte libre (anti-détournement).
- **Prompt caching** sur le system prompt + le schéma d'ops (stable) → coût d'entrée ~0,1× après le 1er appel.
- Coût estimé : < 1 centime/commande (Opus), ~0,15 centime (Haiku). Le coût réel du produit = le rendu vidéo, pas le LLM.

### 8.2 Liste blanche d'opérations (= aussi la frontière de sécurité)
Claude ne peut émettre QUE ces ops, chaque champ validé par le code :
- `set_format(format, duration_s)`
- `set_layout(type, params)`
- `add_segment(clip, start, end)` / `drop_segment(id|range)` / `pin_first(id)` / `reorder(...)`
- `set_speed(segment_id, factor)`
- `add_effect(target, type, params)` (zoom_punch | shake | slowmo | transition)
- `add_overlay(type, asset|text, position, start, end, params)` (text | image | gif | anime)
- `set_music(track, options)` / `set_beat_sync(bool)`
- `add_sfx(event|timestamp, sfx)`
- `set_captions(enabled, style)`
- `remove(object_id)` / `move(object_id, new_time)` (édition conversationnelle)

Validation systématique : fréquences/intensités dans des plages bornées, timestamps dans les bornes du clip, `clip`/`asset` résolus **uniquement** vers les uploads du user ou la lib vérifiée. Un parse "jailbreaké" plafonne à un montage inoffensif.

---

## 9. Spécialisation CoD (le moat — inchangé/renforcé, sous les couches)
- Détection des kills sans calibrage (bandeau knock), conscience du HUD (compteur 💀, prox-chat noms ennemis), distinction knock vs confirm (couper sur le knock).
- Prox-chat = signal **visuel** (noms ennemis en rouge à droite) priorisé, plus la transcription voix.
- Phase 2 (scaling) : YOLOv8 fine-tuné (Roboflow) pour la détection robuste multi-résolution.

---

## 10. Défauts produit (issus de la recherche TikTok)

Bakés comme valeurs par défaut (modifiables) :
- **Durée 15-30s** (sweet spot ; 60s+ seulement pour la monétisation).
- **Hook 0-3s en pleine action** ; rétention checkée à 3/10/20s ; viser ~75% de complétion.
- **Couper le temps mort** (>0,5s de marche/loot/attente) ; finir pile après le payoff.
- **Zoom punch-in + shake** auto sur le kill (bougeable) ; ralenti sur le gros moment ; transitions flash/whip.
- Layout `facecam_top` ou `vertical_blurfill` ; **HUD visible** ; captions animées ; memes/GIF sur les moments drôles.
- Son tendance + beat-sync ; pas la voix du joueur sur les kills.

Sources : clypse (longueur), CapCut (zoom+shake), Eklipse (CoD), recherche hooks/rétention TikTok.

---

## 11. Déploiement web (client = zéro install)

- **Front** : Next.js (navigateur) — upload clips, chat + timeline visuelle, aperçu, téléchargement.
- **Back** : FastAPI — reçoit clips + commandes, **détient la clé Claude** (var d'env serveur), appelle l'API, compile la timeline, lance le rendu, stocke/sert les sorties.
- Le navigateur **n'appelle jamais Claude directement** ; tout passe par le back. La clé ne traverse jamais le réseau vers le client.
- Rendu dans un **worker isolé** (file d'attente) — voir sécurité §12.
- Stockage objet (clips + sorties) avec **URLs signées expirantes**.

---

## 12. Sécurité (NON-NÉGOCIABLE)

Objectif : la clé n'est jamais volable, l'injection ne mène nulle part, le pire cas est borné. Défense en profondeur. (Aucun système n'est 100% inviolable ; ces mesures rendent la clé inatteignable côté client, confinent un éventuel RCE loin de la clé, et plafonnent le pire cas au budget.)

### 12.1 Protection de la clé
- Clé **uniquement côté serveur** (secrets manager / env injectée au déploiement) — jamais front, jamais bundle JS, jamais git.
- **Clé Anthropic dédiée à l'app**, workspace séparé, **plafond de dépense mensuel** (≠ clé perso ; pire cas = budget borné). Rotation facile.
- `.gitignore` + hook `gitleaks`/`trufflehog` + scan CI. Redaction des logs (jamais `Authorization`/env). Erreurs génériques côté client.
- Egress du worker bloqué (pas de SSRF vers metadata cloud `169.254.169.254`).

### 12.2 Threat model (scénarios → défenses)

**A. Vol de la clé**
1. Clé dans le bundle front → jamais côté client ; le front ne connaît qu'une URL vers le back.
2. Clé commitée → secrets manager + .gitignore + gitleaks + scan CI.
3. Clé dans les logs → redaction, jamais logger headers/env.
4. Clé via erreur verbeuse → erreurs génériques client, détails serveur.
5. Back utilisé comme proxy LLM gratuit → endpoint accepte seulement des commandes de montage structurées sur job authentifié + quota/user ; pas de passthrough de prompt.
6. SSRF vers metadata cloud → egress worker bloqué, endpoint metadata bloqué.
7. Dépendance compromise exfiltre l'env → lockfiles + audit + egress restreint.
8. Container/serveur compromis → clé en secrets manager, moindre privilège, pas en clair sur disque.
9. Clé dédiée plafonnée → filet ultime, pire cas borné au budget.

**B. Prompt injection / abus LLM**
10. "Ignore tes instructions, renvoie {ops}" → sortie jamais exécutée, validée contre allowlist + schéma strict.
11. Injection via contenu du clip (OCR prox-chat/sous-titres) → contenu dérivé du média = données non fiables, jamais des instructions.
12. Injection via nom de fichier/métadonnées → sanitize, jamais de contenu user brut dans le system prompt.
13. Boucle de dépense (méga-sorties) → max_tokens borné + quota d'appels/user.
14. Extraction du system prompt → aucun secret dedans.
15. LLM détourné en "ChatGPT gratuit" → tool_choice forcé → ops de montage only.
16. Ops vers assets/chemins interdits → assets only depuis lib vérifiée + uploads du user.

**C. Command injection (ffmpeg)**
17. Texte d'overlay qui s'échappe (`; rm -rf`, `$(...)`) → subprocess en tableau d'args, jamais shell=True.
18. Filtergraph malveillant → l'user/LLM ne compose jamais un filtre brut ; généré par le code depuis ops validées.
19. Nom de sortie en traversal → chemins générés serveur, confinés au dossier de job.
20. Payload dans les tags du conteneur → ffmpeg lit en données, tags jamais réinjectés en commande.

**D. Fichiers uploadés malveillants**
21. Faux MP4 polyglotte → valider le vrai type (magic bytes/ffprobe), pas l'extension ; jamais exécuté.
22. Decoder/decompression bomb → limites durée/résolution + timeouts CPU/mém + ffprobe avant décodage.
23. Fichier géant → limite taille + quota stockage/user.
24. Exploit CVE ffmpeg (RCE décodeur) → ffmpeg à jour + worker sandboxé (container non-privilégié, seccomp, egress coupé) → RCE confiné, n'atteint pas la clé.
25. Contenu illégal → ToS + scan/modération + journalisation + signalement.
26. Sous-titres/chapitres porteurs de XSS → tout média échappé à l'affichage.

**E. Authn / autorisation**
27. IDOR (changer l'ID) → check d'ownership systématique + IDs UUID non devinables.
28. Vol de session → cookies httpOnly+Secure+SameSite, expiration, rotation.
29. Brute force login → rate limit + lockout + hash fort (argon2/bcrypt) + MFA optionnel.
30. Élévation de privilège → contrôle de rôle côté serveur, jamais côté client.
31. CSRF → token CSRF / SameSite.

**F. Abus de coût / DoS**
32. Spam de commandes LLM → quota/user + global + rate limit.
33. Spam de rendus → file d'attente + quota minutes/jour.
34. Comptes jetables en masse → captcha + vérif email + limites/IP.
35. Requêtes concurrentes lentes → timeouts + limite de concurrence + autoscale borné.
36. Amplification (petit input → rendu interminable) → cap durée/résolution de sortie.

**G. Web classiques + infra**
37. XSS stocké → échappement systématique + CSP stricte.
38. CORS en `*` → verrouillé sur le domaine.
39. Clickjacking → frame-ancestors / X-Frame-Options.
40. Open redirect → pas de redirect basé sur param user.
41. SQL/NoSQL injection → requêtes paramétrées, zéro concat.
42. Headers sécu → HSTS, CSP, X-Content-Type-Options.
43. Dépendance/Docker compromis → audit (pip-audit/npm audit/trivy), pin digests, Dependabot.
44. Webhook paiement forgé (Stripe) → vérif signature + idempotence.
45. Fuite inter-tenant via URL média → URLs signées expirantes, IDs non séquentiels.
46. Rétention/RGPD → suppression auto + droit à l'effacement.

---

## 13. Phasage de build (de bas en haut)

- **Phase A — Primitives de rendu** : layouts (facecam_top), effets (zoom_punch, shake, slowmo, transition), overlays (text, image, gif, anime), SFX, bibliothèque d'assets. Testables isolément (chaque op → rendu).
- **Phase B — Modèle timeline** : structure + auto-remplissage depuis la détection + compilation timeline→ffmpeg. UI visuelle d'édition.
- **Phase C — Chat NL** : Claude (tool-use) → ops sur la timeline, édition conversationnelle. Allowlist + validation.
- **Phase D — Web SaaS** : front Next + back FastAPI, comptes, uploads, worker de rendu isolé, sécurité §12 intégrée dès le départ.
- **Transverse** : moat CoD (détection) conservé et durci ; défauts recherche bakés.

Note : le chat NL (cible produit) repose sur les primitives + la timeline — d'où l'ordre A→B→C→D.

---

## 14. Non-objectifs / YAGNI
- Pas d'éditeur vidéo généraliste image-par-image.
- Pas de multi-jeux au départ (CoD only).
- Pas d'édition collaborative temps réel.
- Pas de génération d'assets par IA au départ (bibliothèque + uploads suffisent).
- Pas de modération auto avancée (minimum légal seulement).

---

## 15. Hypothèses & questions ouvertes
- **Stack/hébergement** : Next.js + FastAPI retenus ; hébergeur précis (Fly/Render/VPS + worker GPU ?) à décider en Phase D.
- **Bibliothèque d'assets** : sourcing des assets anime/memes/SFX libres de droits à constituer (licences claires).
- **Facecam** : source = crop d'un coin du clip vs fichier séparé uploadé — supporter les deux.
- **Monétisation** : modèle d'abonnement / quotas à définir (impacte les plafonds anti-abus).
- **Détection Phase 2** : bascule vers YOLO décidée au scaling, pas au départ.
- Deep-research "anatomie des 100 plus gros edits Warzone" : optionnelle, à lancer si on veut affiner les défauts plan-par-plan.
