"""Chaque réglage de `config.yaml` atteint-il vraiment le code ?

Trouvé le 15/08 : `detect_kill_banners` était appelé avec le seul paramètre `fps`.
Tous ses autres réglages restaient aux valeurs par défaut du code — et aucun n'était
même exposé dans `config.yaml`. Un bouton qu'on tourne et qui ne fait rien est la
forme la plus frustrante de l'échec silencieux : on croit piloter.

Ce test lit les SOURCES (pas le comportement) : c'est le seul moyen d'attraper un
réglage qu'on oublie de brancher, puisqu'un oubli ne lève jamais d'erreur.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _config_block(name: str) -> list[str]:
    """Les clés de premier niveau sous la section `name` de config.yaml."""
    text = (ROOT / "config.yaml").read_text(encoding="utf-8")
    lines = text.splitlines()
    keys, inside = [], False
    for line in lines:
        if re.match(rf"^{re.escape(name)}:\s*(#.*)?$", line):
            inside = True
            continue
        if inside:
            if line and not line[0].isspace():        # section suivante
                break
            m = re.match(r"^\s{2}([A-Za-z_][A-Za-z0-9_]*):", line)
            if m:
                keys.append(m.group(1))
    return keys


def _call_args(func: str) -> str:
    """Le texte de l'appel à `func` dans main.py (parenthèses équilibrées)."""
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    start = src.index(f"{func}(", src.index("events += "))
    i = src.index("(", start)
    depth, j = 0, i
    while j < len(src):
        if src[j] == "(":
            depth += 1
        elif src[j] == ")":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
        j += 1
    raise AssertionError(f"appel à {func} non trouvé dans main.py")


def test_la_section_killdetect_existe():
    assert _config_block("killdetect"), "config.yaml n'expose plus les réglages du détecteur"


def test_chaque_reglage_de_killdetect_est_passe_a_la_fonction():
    keys = _config_block("killdetect")
    call = _call_args("detect_kill_banners")
    manquants = [k for k in keys if f'"{k}"' not in call and f"'{k}'" not in call]
    assert not manquants, (
        "réglages présents dans config.yaml mais JAMAIS transmis à "
        f"detect_kill_banners : {manquants}"
    )


def test_le_reglage_a_caler_est_bien_expose():
    # `merge_confirm_s` décide si un ENNEMI ÉLIMINÉ qui suit un ENNEMI ABATTU est
    # le même adversaire. Sa valeur dépend d'Alex, donc elle doit être réglable
    # sans toucher au code.
    assert "merge_confirm_s" in _config_block("killdetect")


def test_les_reglages_vision_atteignent_leur_fonction():
    # Même garantie pour l'autre détecteur, qui lui était déjà correctement câblé.
    call = _call_args("detect_visual_events")
    for k in ("search_region", "threshold", "sample_fps"):
        assert k in call, f"réglage vision '{k}' non transmis"


# --- l'échappatoire doit rester atteignable ----------------------------------
# Trouvé le 15/08 en lançant l'outil de bout en bout : `--add` et `--first` étaient
# traités APRÈS l'abandon « Aucun moment détecté ». Ils ne pouvaient donc pas servir
# dans le seul cas où on les sort — quand la détection rate le moment. Le message
# conseillait même de baisser un seuil alors que l'utilisateur a déjà dit quoi garder.
# Vérifié après correctif : un clip sans aucun candidat produit bien un montage.

def test_l_abandon_tient_compte_des_segments_forces():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    ligne = next(l for l in src.splitlines() if "if not all_cands" in l)
    assert "args.add" in ligne and "args.first" in ligne, \
        f"l'abandon ignore les segments forcés : {ligne.strip()}"


def test_le_message_d_abandon_mentionne_l_echappatoire():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    i = src.index("Aucun moment détecté")
    message = src[i:i + 220]
    assert "--add" in message, \
        "le message n'indique pas comment forcer un segment"


def test_zoom_et_sfx_previennent_quand_ils_ne_peuvent_rien_faire():
    """Vérifié le 15/08 en lançant l'outil : `--zoom` sur des extraits sans kill
    produisait une sortie au hash IDENTIQUE, sans un mot. Les effets se calent sur
    `c.kill_times` ; sans vision (rapidocr absent) il n'y a pas de kill."""
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "sans effet" in src, "aucun avertissement quand zoom/sfx sont inertes"
    assert "kill_times" in src.split("extraits retenus")[0], \
        "l'avertissement ne se base pas sur la présence réelle de kills"


def test_l_avertissement_epargne_le_beat_fx():
    """`--beat-fx` fournit ses propres centres depuis la musique : prévenir « sans
    effet » serait faux. Mesuré : avec beat-fx le rendu CHANGE sans aucun kill."""
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    # on épingle l'EXPRESSION de garde, pas un nom de variable : renommer la variable
    # ne doit pas suffire à faire passer le test (première version trop faible).
    assert "do_zoom and not beat_fx_actif" in src, \
        "le zoom est déclaré inerte même quand le beat-fx lui fournit des centres"
