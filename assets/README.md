# Bibliothèque d'assets (couche 1)

Assets utilisés par les overlays/SFX. Deux origines :

- **Bundlés** (ici, livrés avec l'outil) : libres de droits / licence claire uniquement.
- **Uploads utilisateur** : déposés par le user (ses propres images/GIF/sons). Stockés
  par utilisateur, isolés, validés (type réel via ffprobe, taille bornée) — cf. sécurité.

## Catégories
- `fonts/` — polices pour les overlays texte (drawtext). **Non versionnée** : `impact.ttf` est une
  police système Windows, `.gitignore` l'exclut. Sur un clone, déposer un `.ttf` à ce chemin pour
  les textes incrustés (sinon `text_overlay` lève une erreur qui le dit).
- `anime/` — overlays thématiques (Uchiha/sharingan, flammes…). PNG/GIF transparents.
- `memes/` — images/GIF drôles.
- `sfx/` — sons d'impact / risers. **Non versionné** (`.gitignore` exclut les `.wav`) : si
  `punch.wav` manque, `--sfx` génère un thump grave amorti au même niveau dans le dossier du rendu.

## Règle
Toute référence d'asset dans une opération de la timeline est résolue **uniquement**
vers cette bibliothèque ou les uploads de l'utilisateur — jamais un chemin/URL arbitraire
(barrière de sécurité, cf. cahier des charges §12).
