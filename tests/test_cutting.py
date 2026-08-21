"""Critères d'acceptation A1-A5 du cahier des charges (§4.2).

Un test par critère nommé, plus les cas limites qui les cassent. Aucun ffmpeg :
si ces règles se dégradent, ça doit se voir en une seconde, pas au visionnage.
"""
import pytest

from wzmontage.cutting import (compute_segments, excise_dead_gaps, quiet_after,
                               resolve_end, snap_to_beat)

CFG = {"editing": {
    "banner_lag_s": 0.4,
    "lead_out_min_s": 1.0,
    "lead_out_s": 1.2,
    "quiet_ratio": 0.25,
    "quiet_hold_s": 0.35,
    "dead_gap_min_s": 3.5,
    "dead_gap_pad_s": 0.4,
    "beat_snap_max_s": 0.1,
    "min_clip_s": 4.0,
}}

STEP = 0.05


def env_from(spans, total=60.0, loud=1.0, soft=0.02):
    """Enveloppe synthétique : `spans` = liste de (t0, t1) bruyants, le reste calme."""
    times, vals = [], []
    t = 0.0
    while t <= total:
        times.append(round(t, 3))
        vals.append(loud if any(a <= t <= b for a, b in spans) else soft)
        t += STEP
    return (times, vals)


# --- A1 : temps mort de fin <= ~1,2 s après le DERNIER KILL RÉEL -------------

def test_A1_le_temps_mort_de_fin_ne_depasse_pas_le_lead_out():
    env = env_from([(0.0, 30.0)])          # ça tire encore : aucune chute d'énergie
    banner = 20.0
    vrai_kill = banner - CFG["editing"]["banner_lag_s"]
    end = resolve_end(banner, env, CFG, video_duration=60.0)
    assert end - vrai_kill <= CFG["editing"]["lead_out_s"] + 1e-9


def test_A1_le_retard_du_bandeau_est_retire_et_pas_seulement_documente():
    """Sans la correction, la fin traînerait de `banner_lag_s` en plus. Mutation :
    mettre banner_lag_s a 0 doit RALLONGER le clip -- si ce test passe encore, la
    correction n'est pas branchee."""
    env = env_from([(0.0, 30.0)])
    avec = resolve_end(20.0, env, CFG, 60.0)
    sans = resolve_end(20.0, env, {"editing": dict(CFG["editing"], banner_lag_s=0.0)}, 60.0)
    assert sans - avec == pytest.approx(0.4, abs=1e-6)


# --- A3 : le cut-out se cale sur la chute d'énergie si elle vient avant ------

def test_A3_la_chute_d_energie_avance_la_coupe():
    # tirs jusqu'à 19,6 (= l'ancre) puis silence : on doit couper au minimum vital
    env = env_from([(0.0, 19.6)])
    end = resolve_end(20.0, env, CFG, 60.0)
    anchor = 20.0 - 0.4
    assert end == pytest.approx(anchor + CFG["editing"]["lead_out_min_s"], abs=0.1)


def test_A3_sans_chute_on_garde_la_borne_dure():
    env = env_from([(0.0, 30.0)])
    end = resolve_end(20.0, env, CFG, 60.0)
    assert end == pytest.approx(20.0 - 0.4 + 1.2, abs=1e-9)


def test_A3_la_respiration_minimale_est_toujours_laissee():
    """Le 💀 monte APRÈS le kill. Couper à l'instant où le bruit tombe volerait la
    récompense : il doit rester `lead_out_min_s` quoi qu'il arrive."""
    env = env_from([(0.0, 19.0)])          # silence bien avant l'ancre
    end = resolve_end(20.0, env, CFG, 60.0)
    assert end - (20.0 - 0.4) >= CFG["editing"]["lead_out_min_s"] - 1e-9


def test_quiet_after_rend_none_quand_le_calme_ne_TIENT_pas():
    """Un creux de 0,1 s entre deux rafales n'est pas la fin du combat."""
    env = env_from([(0.0, 19.6), (19.7, 30.0)])
    assert quiet_after(env, 19.6, 21.0, CFG) is None


def test_quiet_after_est_relatif_au_pic_local_pas_a_un_seuil_absolu():
    """Un combat DEUX FOIS moins fort doit être coupé au même endroit. Un seuil
    absolu le raterait entièrement -- c'est le défaut que `ratio` existe pour éviter."""
    fort = env_from([(0.0, 19.6)], loud=1.0, soft=0.02)
    faible = env_from([(0.0, 19.6)], loud=0.5, soft=0.01)
    assert resolve_end(20.0, fort, CFG, 60.0) == pytest.approx(
        resolve_end(20.0, faible, CFG, 60.0), abs=1e-9)


# --- A4 : le beat déplace la fin de <= 100 ms, JAMAIS vers le tard -----------

def test_A4_le_beat_ne_repousse_jamais_la_fin():
    end = 20.0
    assert snap_to_beat(end, [20.05, 20.5, 21.0], CFG) == end


def test_A4_le_beat_avance_la_fin_de_100ms_au_plus():
    assert snap_to_beat(20.0, [19.95], CFG) == pytest.approx(19.95)
    assert snap_to_beat(20.0, [19.5], CFG) == 20.0        # trop loin : ignoré


def test_A4_sans_musique_la_fin_ne_bouge_pas():
    assert snap_to_beat(20.0, [], CFG) == 20.0


# --- A2 / C5 : le trou mort interne est excisé ------------------------------

def test_A2_un_trou_mort_interne_est_retire():
    # fight 0-5, trou 5-15, fight 15-20
    env = env_from([(0.0, 5.0), (15.0, 20.0)])
    segs = excise_dead_gaps(0.0, 20.0, [2.0, 17.0], env, CFG)
    assert len(segs) == 2
    assert segs[0][1] < segs[1][0]
    assert sum(e - s for s, e in segs) < 20.0


def test_A2_un_trou_trop_court_n_est_pas_un_trou_mort():
    env = env_from([(0.0, 5.0), (7.0, 20.0)])     # 2 s de calme seulement
    assert excise_dead_gaps(0.0, 20.0, [2.0, 17.0], env, CFG) == [(0.0, 20.0)]


def test_A2_un_silence_qui_porte_un_event_n_est_pas_mort():
    """Une réanimation ne fait pas de bruit mais c'est de l'action. L'énergie seule
    ne peut pas trancher -- c'est pour ça que les events entrent dans la décision."""
    env = env_from([(0.0, 5.0), (15.0, 20.0)])
    segs = excise_dead_gaps(0.0, 20.0, [2.0, 10.0, 17.0], env, CFG)
    assert segs == [(0.0, 20.0)]


def test_A2_ne_rend_jamais_une_liste_vide():
    env = env_from([])                             # tout est calme
    segs = excise_dead_gaps(0.0, 20.0, [], env, CFG)
    assert segs and all(e > s for s, e in segs)


def test_A2_sans_enveloppe_le_clip_reste_entier():
    assert excise_dead_gaps(0.0, 20.0, [2.0], None, CFG) == [(0.0, 20.0)]


# --- compute_segments : l'ordre C4 -> A4 -> C5 ------------------------------

def test_compute_segments_ferme_la_fin_avant_d_exciser():
    """Si l'excision passait EN PREMIER, le temps mort final serait vu comme un trou
    interne et le dernier sous-segment serait tronqué au mauvais endroit."""
    env = env_from([(0.0, 5.0), (15.0, 19.6)])
    segs = compute_segments(20.0, 0.0, [2.0, 17.0], env, CFG, 60.0)
    assert segs[-1][1] == pytest.approx(20.0 - 0.4 + 1.0, abs=0.1)
    assert len(segs) == 2


def test_compute_segments_ne_rend_pas_un_segment_negatif():
    segs = compute_segments(0.1, 5.0, [], None, CFG, 60.0)
    assert all(e > s for s, e in segs)


# --- A5 : les défauts livrés sont OFF ---------------------------------------

def test_A5_les_defauts_du_config_livre_sont_off():
    """Le cahier (§4.2 A5) : sans drapeau, aucun effet ; beat_sync et order:hook OFF.
    Ce test lit le VRAI config.yaml -- un défaut qui dérive doit rougir ici."""
    import pathlib

    import yaml
    root = pathlib.Path(__file__).resolve().parents[1]
    cfg = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    ed = cfg["editing"]
    assert ed.get("beat_sync") is False, "beat_sync doit être OFF par défaut (A5)"
    assert ed.get("order") == "chronological", "order doit être chronological (A5)"
    assert ed["lead_out_s"] <= 1.2, "A1 : le lead-out livré doit tenir sous 1,2 s"


# --- Le BRANCHEMENT, pas seulement la fonction pure -------------------------
# Une fonction juste que personne n'appelle est un test vert sans garantie.
# Ces trois-là échouent si le câblage saute, même si cutting.py reste parfait.

def _cfg_reel():
    import pathlib

    import yaml
    root = pathlib.Path(__file__).resolve().parents[1]
    return yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))


def test_build_candidates_applique_bien_C4():
    """La fin d'un candidat doit suivre resolve_end, pas `action_end + lead_out`."""
    from wzmontage.models import Event
    from wzmontage.scoring import build_candidates

    cfg = _cfg_reel()
    ev = [Event("v.mp4", 20.0, "kill", 1.0)]
    env = env_from([(0.0, 30.0)], total=60.0)
    c = build_candidates(ev, 60.0, cfg, env=env)[0]
    attendu = 20.0 - cfg["editing"]["banner_lag_s"] + cfg["editing"]["lead_out_s"]
    assert c.end == pytest.approx(attendu, abs=1e-6)


def test_build_candidates_remplit_segments_quand_il_y_a_un_trou():
    """C5 câblé : deux fights séparés par un trou mort -> le Candidate porte ses
    sous-segments. S'il reste vide, le rendu produira le trou."""
    from wzmontage.models import Event
    from wzmontage.scoring import build_candidates

    cfg = _cfg_reel()
    ev = [Event("v.mp4", 5.0, "kill", 1.0), Event("v.mp4", 18.0, "kill", 1.0)]
    env = env_from([(0.0, 6.0), (16.0, 25.0)], total=60.0)
    c = build_candidates(ev, 60.0, cfg, env=env)[0]
    assert len(c.segments) >= 2, "le trou mort n'a pas été excisé par le pipeline"
    assert sum(e - s for s, e in c.segments) < c.end - c.start


def test_build_candidates_sans_enveloppe_reste_correct():
    """Sans audio analysable, on ne devine pas : clip d'un seul tenant, borne dure."""
    from wzmontage.models import Event
    from wzmontage.scoring import build_candidates

    cfg = _cfg_reel()
    ev = [Event("v.mp4", 20.0, "kill", 1.0)]
    c = build_candidates(ev, 60.0, cfg, env=None)[0]
    assert c.segments == []
    assert c.end == pytest.approx(20.0 - cfg["editing"]["banner_lag_s"]
                                  + cfg["editing"]["lead_out_s"], abs=1e-6)
