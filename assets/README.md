# Bibliothèque d'assets (couche 1)

Assets utilisés par les overlays/SFX. Deux origines :

- **Bundlés** (ici, livrés avec l'outil) : libres de droits / licence claire uniquement.
- **Uploads utilisateur** : déposés par le user (ses propres images/GIF/sons). Stockés
  par utilisateur, isolés, validés (type réel via ffprobe, taille bornée) — cf. sécurité.

## Catégories
- `fonts/` — polices pour les overlays texte (drawtext). Bundlé : `impact.ttf` (hype).
- `anime/` — overlays thématiques (Uchiha/sharingan, flammes…). PNG/GIF transparents.
- `memes/` — images/GIF drôles.
- `sfx/` — sons d'impact / risers. Bundlé : `punch.wav` (thump grave amorti).

## Règle
Toute référence d'asset dans une opération de la timeline est résolue **uniquement**
vers cette bibliothèque ou les uploads de l'utilisateur — jamais un chemin/URL arbitraire
(barrière de sécurité, cf. cahier des charges §12).
