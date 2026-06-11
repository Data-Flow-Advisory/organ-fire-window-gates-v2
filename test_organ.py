"""Tests for the fire-window-gates organ. Vanilla pytest, stdlib only."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
ORGAN = ROOT / "organ.py"
_spec = importlib.util.spec_from_file_location("fwg_organ", ORGAN)
organ = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(organ)
decide = organ.decide


# --------------------------------------------------------------------------- #
# builders                                                                     #
# --------------------------------------------------------------------------- #

def _evals(*flags):
    return [{"all_valid": bool(f)} for f in flags]


def _full_state():
    return {
        "recent_evaluations": _evals(True, True, True),
        "stage_a_min_clean_fires": 3,
        "stage_b_checks": {"b1": True, "b2": True, "b3": True, "b4": True, "b5": True},
        "phase_2_checks": {"p2_1": True, "p2_2": True, "p2_3": True, "p2_4": True},
        "phase_3_checks": {
            "godmode_exists": True,
            "godmode_has_standing_directive": True,
            "godmode_execution_target_is_local_cron": True,
            "godmode_role_is_set": True,
            "dream_team_seeded": True,
        },
    }


# --------------------------------------------------------------------------- #
# shape / contract                                                             #
# --------------------------------------------------------------------------- #

def test_return_shape():
    r = decide({}, {})
    assert set(r.keys()) == {"output", "rationale", "self_metric"}
    assert isinstance(r["rationale"], str)
    assert "confidence" in r["self_metric"]
    c = r["self_metric"]["confidence"]
    assert isinstance(c, (int, float)) and 0.0 <= c <= 1.0


def test_output_keys():
    out = decide(_full_state(), {})["output"]
    for k in [
        "stage_a_complete", "stage_b_complete", "phase_2_unlocked",
        "phase_3_complete", "godmode_healthy", "current_stage",
        "blockers", "next_actions",
    ]:
        assert k in out


# --------------------------------------------------------------------------- #
# fail-safe (conservative on empty / malformed)                               #
# --------------------------------------------------------------------------- #

def test_empty_state_all_closed():
    out = decide({}, {})["output"]
    assert out["stage_a_complete"] is False
    assert out["stage_b_complete"] is False
    assert out["phase_2_unlocked"] is False
    assert out["phase_3_complete"] is False
    assert out["current_stage"] == "stage_a"
    assert decide({}, {})["self_metric"]["confidence"] == 0.0


def test_none_state_does_not_raise():
    out = decide(None, None)["output"]
    assert out["current_stage"] == "stage_a"


def test_garbage_types_fail_closed():
    state = {
        "recent_evaluations": "not-a-list",
        "stage_b_checks": 42,
        "phase_2_checks": ["wrong"],
        "phase_3_checks": None,
    }
    out = decide(state, {})["output"]
    assert out["stage_a_complete"] is False
    assert out["stage_b_complete"] is False
    assert out["phase_2_unlocked"] is False
    assert out["phase_3_complete"] is False


def test_truthy_non_bool_is_not_accepted():
    # Mirrors the source's defensive "must be strictly bool True" guard.
    state = {"stage_b_checks": {"b1": 1, "b2": "yes", "b3": True, "b4": True, "b5": True}}
    assert decide(state, {})["output"]["stage_b_complete"] is False


# --------------------------------------------------------------------------- #
# Stage A — streak gate                                                        #
# --------------------------------------------------------------------------- #

def test_stage_a_three_clean_opens():
    out = decide({"recent_evaluations": _evals(True, True, True)}, {})["output"]
    assert out["stage_a_complete"] is True


def test_stage_a_one_dirty_closes():
    out = decide({"recent_evaluations": _evals(True, True, False)}, {})["output"]
    assert out["stage_a_complete"] is False
    assert out["current_stage"] == "stage_a"


def test_stage_a_too_few_rows_closes():
    out = decide({"recent_evaluations": _evals(True, True)}, {})["output"]
    assert out["stage_a_complete"] is False


def test_stage_a_threshold_override_from_state():
    st = {"recent_evaluations": _evals(True, True), "stage_a_min_clean_fires": 2}
    assert decide(st, {})["output"]["stage_a_complete"] is True


def test_stage_a_threshold_override_from_context():
    st = {"recent_evaluations": _evals(True, True)}
    assert decide(st, {"stage_a_min_clean_fires": 2})["output"]["stage_a_complete"] is True


def test_stage_a_state_overrides_context_threshold():
    st = {"recent_evaluations": _evals(True, True, True, True), "stage_a_min_clean_fires": 4}
    # state asks for 4 clean; context's 2 must NOT win.
    assert decide(st, {"stage_a_min_clean_fires": 2})["output"]["stage_a_complete"] is True
    st2 = {"recent_evaluations": _evals(True, True, True), "stage_a_min_clean_fires": 4}
    assert decide(st2, {"stage_a_min_clean_fires": 2})["output"]["stage_a_complete"] is False


def test_stage_a_nonpositive_threshold_falls_back_to_default():
    # 0 / negative override is ignored → default 3.
    st = {"recent_evaluations": _evals(True, True), "stage_a_min_clean_fires": 0}
    assert decide(st, {})["output"]["stage_a_complete"] is False
    st3 = {"recent_evaluations": _evals(True, True, True), "stage_a_min_clean_fires": -5}
    assert decide(st3, {})["output"]["stage_a_complete"] is True


# --------------------------------------------------------------------------- #
# Stage B / Phase 2 conjunctions                                              #
# --------------------------------------------------------------------------- #

def test_stage_b_all_true_opens():
    st = {"stage_b_checks": {"b1": True, "b2": True, "b3": True, "b4": True, "b5": True}}
    assert decide(st, {})["output"]["stage_b_complete"] is True


def test_stage_b_one_false_closes():
    st = {"stage_b_checks": {"b1": True, "b2": True, "b3": False, "b4": True, "b5": True}}
    assert decide(st, {})["output"]["stage_b_complete"] is False


def test_stage_b_missing_key_closes():
    st = {"stage_b_checks": {"b1": True, "b2": True, "b3": True, "b4": True}}
    assert decide(st, {})["output"]["stage_b_complete"] is False


def test_phase_2_all_true_opens():
    st = {"phase_2_checks": {"p2_1": True, "p2_2": True, "p2_3": True, "p2_4": True}}
    assert decide(st, {})["output"]["phase_2_unlocked"] is True


# --------------------------------------------------------------------------- #
# Phase 3 — godmode health AND dream team                                     #
# --------------------------------------------------------------------------- #

def test_phase_3_requires_dream_team():
    st = {"phase_3_checks": {
        "godmode_exists": True,
        "godmode_has_standing_directive": True,
        "godmode_execution_target_is_local_cron": True,
        "godmode_role_is_set": True,
        "dream_team_seeded": False,
    }}
    out = decide(st, {})["output"]
    assert out["godmode_healthy"] is True
    assert out["phase_3_complete"] is False


def test_phase_3_godmode_unhealthy_closes():
    st = {"phase_3_checks": {
        "godmode_exists": True,
        "godmode_has_standing_directive": False,
        "godmode_execution_target_is_local_cron": True,
        "godmode_role_is_set": True,
        "dream_team_seeded": True,
    }}
    out = decide(st, {})["output"]
    assert out["godmode_healthy"] is False
    assert out["phase_3_complete"] is False


# --------------------------------------------------------------------------- #
# progression / frontier + blockers                                           #
# --------------------------------------------------------------------------- #

def test_frontier_is_first_incomplete_gate():
    st = _full_state()
    st["phase_2_checks"]["p2_4"] = False
    out = decide(st, {})["output"]
    assert out["current_stage"] == "phase_2"
    assert any("P2-4" in b for b in out["blockers"])


def test_blockers_only_report_frontier():
    st = _full_state()
    st["stage_b_checks"]["b2"] = False  # Stage B is the frontier
    st["phase_2_checks"]["p2_1"] = False  # later gate — must NOT appear
    out = decide(st, {})["output"]
    assert out["current_stage"] == "stage_b"
    assert any("B2" in b for b in out["blockers"])
    assert not any("P2-1" in b for b in out["blockers"])


def test_all_gates_open_complete():
    out = decide(_full_state(), {})["output"]
    assert out["stage_a_complete"]
    assert out["stage_b_complete"]
    assert out["phase_2_unlocked"]
    assert out["phase_3_complete"]
    assert out["current_stage"] == "complete"
    assert out["blockers"] == []


def test_confidence_scales_with_sections():
    assert decide({}, {})["self_metric"]["confidence"] == 0.0
    assert decide(_full_state(), {})["self_metric"]["confidence"] == 1.0
    partial = {"recent_evaluations": _evals(True, True, True),
               "stage_b_checks": {"b1": True, "b2": True, "b3": True, "b4": True, "b5": True}}
    assert decide(partial, {})["self_metric"]["confidence"] == 0.5


def test_gates_open_counter():
    sm = decide(_full_state(), {})["self_metric"]
    assert sm["gates_open"] == 4
    assert sm["gates_total"] == 4


# --------------------------------------------------------------------------- #
# determinism + CLI runner                                                     #
# --------------------------------------------------------------------------- #

def test_determinism():
    st = _full_state()
    st["phase_2_checks"]["p2_3"] = False
    a, b = decide(st, {}), decide(st, {})
    assert a == b


def test_samples_run_through_cli():
    for s in sorted((ROOT / "samples").glob("*.json")):
        proc = subprocess.run(
            [sys.executable, str(ORGAN)],
            env={"ORGAN_INPUT": str(s), "PATH": __import__("os").environ.get("PATH", "")},
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, f"{s.name}: {proc.stderr}"
        result = json.loads(proc.stdout)
        assert set(result.keys()) == {"output", "rationale", "self_metric"}
        assert 0.0 <= result["self_metric"]["confidence"] <= 1.0
        assert result["output"]["current_stage"] in {
            "stage_a", "stage_b", "phase_2", "phase_3", "complete"
        }


def test_sample_expectations():
    # cross-check the three samples land where their names claim.
    def _run(name):
        return decide(json.loads((ROOT / "samples" / name).read_text())["state"], {})["output"]

    assert _run("stage_a_pending.json")["current_stage"] == "stage_a"
    assert _run("phase_2_frontier.json")["current_stage"] == "phase_2"
    assert _run("all_gates_open.json")["current_stage"] == "complete"
