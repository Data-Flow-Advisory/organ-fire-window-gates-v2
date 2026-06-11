"""organ-fire-window-gates-v2 — pure decider for platform fire-window gates.

A faithful, side-effect-free re-extraction of the gate logic in
discovery-engine ``app/services/fire_window_gates.py``. The production
module composes pure predicates over DB-loaded rows
(``recent_evaluations``, persona configs, PlatformEvent counts). This
organ keeps ONLY the pure predicates and is *handed* the facts in
``state`` — it never fetches them.

Per the orchestrator CONTRACT:
  - No side effects (no DB, no network, no filesystem, no globals).
  - Deterministic given the same ``(state, context)``.
  - Fail-safe to the conservative verdict (every gate CLOSED, low
    confidence) on empty / malformed ``state`` — never a confident-wrong
    "everything is open".
  - Stdlib-only.

Signature: ``decide(state: dict, context: dict | None) -> dict``
Returns ``{output, rationale, self_metric}`` with
``self_metric.confidence`` ∈ [0.0, 1.0] required.

The platform's readiness progresses through four ordered gates, each a
conjunction over its inputs (mirroring the ``*_from_results`` /
``*_for_rows`` pure helpers in the source):

  Stage A   — last N fire-window evaluations all valid (streak gate).
              source: ``_stage_a_is_complete_for_rows`` /
                      ``is_recent_streak_clean``  (min N = 3).
  Stage B   — five blockers B1..B5 all resolved.
              source: ``_stage_b_is_complete_from_results``.
  Phase 2   — four unlock conditions P2-1..P2-4 all hold.
              source: ``_phase_2_is_unlocked_from_results``.
  Phase 3   — Godmode healthy AND dream-team seeded.
              source: ``_phase_3_is_complete_from_results``.
"""
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# Constants — pinned thresholds / key names (mirror the source module).       #
# --------------------------------------------------------------------------- #

# Stage A requires this many consecutive clean fire windows. Pinned in the
# source as ``STAGE_A_MIN_CLEAN_FIRES = 3`` so the count and the threshold
# can't drift apart. Overridable via state/context for testing.
DEFAULT_STAGE_A_MIN_CLEAN_FIRES: int = 3

STAGE_B_KEYS: List[str] = ["b1", "b2", "b3", "b4", "b5"]
PHASE_2_KEYS: List[str] = ["p2_1", "p2_2", "p2_3", "p2_4"]
# The four config checks that compose ``godmode_is_healthy()`` in the source
# (existence + standing directive + local-cron execution target + role set).
GODMODE_HEALTH_KEYS: List[str] = [
    "godmode_exists",
    "godmode_has_standing_directive",
    "godmode_execution_target_is_local_cron",
    "godmode_role_is_set",
]

# Human-readable labels for blocker reporting.
_BLOCKER_LABELS: Dict[str, str] = {
    "b1": "B1: worker_type fix not landed",
    "b2": "B2: envelope schemas not documented",
    "b3": "B3: auditor state persistence not fixed",
    "b4": "B4: Priya persona not resolved",
    "b5": "B5: cost caps not present",
    "p2_1": "P2-1: phase 1 not on main",
    "p2_2": "P2-2: deployed SHA does not match main",
    "p2_3": "P2-3: no fire report landed since deploy",
    "p2_4": "P2-4: existing personas not healthy",
    "godmode_exists": "Godmode persona does not exist",
    "godmode_has_standing_directive": "Godmode has no standing directive",
    "godmode_execution_target_is_local_cron": (
        "Godmode execution target is not local_cron"
    ),
    "godmode_role_is_set": "Godmode role is not set",
    "dream_team_seeded": "Dream team not seeded correctly",
}

_STAGE_ORDER = ["stage_a", "stage_b", "phase_2", "phase_3"]


# --------------------------------------------------------------------------- #
# Pure predicates (faithful to the source's ``*_from_results`` helpers).      #
# --------------------------------------------------------------------------- #

def _is_recent_streak_clean(rows: Any, min_count: int) -> bool:
    """True iff at least ``min_count`` rows AND every one is ``all_valid``.

    Mirrors source ``is_recent_streak_clean``. Empty / short iterable →
    False (no streak to be clean). Non-positive ``min_count`` → False.
    Rows here are plain dicts (JSON), so we read ``all_valid`` as a key.
    """
    if not isinstance(min_count, int) or isinstance(min_count, bool):
        return False
    if min_count <= 0:
        return False
    if not isinstance(rows, list):
        return False
    if len(rows) < min_count:
        return False
    return all(_row_all_valid(r) for r in rows)


def _row_all_valid(row: Any) -> bool:
    """Read the ``all_valid`` flag off one evaluation row, conservatively."""
    if isinstance(row, dict):
        return row.get("all_valid") is True
    # Allow attribute-style rows too (parity with the source's getattr).
    return getattr(row, "all_valid", False) is True


def _all_true(checks: Any, keys: List[str]) -> bool:
    """Pure conjunction: every key present in ``checks`` AND strictly ``True``.

    Mirrors the defensive ``*_from_results`` helpers, which reject non-bool
    inputs (catching the "passed the function, not its result" bug). A
    missing key is treated as not-done → False, so the gate fails closed.
    """
    if not isinstance(checks, dict):
        return False
    for key in keys:
        if checks.get(key) is not True:
            return False
    return True


def _failing_keys(checks: Any, keys: List[str]) -> List[str]:
    """Subset of ``keys`` that are not strictly ``True`` in ``checks``."""
    if not isinstance(checks, dict):
        return list(keys)
    return [k for k in keys if checks.get(k) is not True]


# --------------------------------------------------------------------------- #
# Entry point.                                                                #
# --------------------------------------------------------------------------- #

def decide(state: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Decide which fire-window gates are open from a handed-in snapshot.

    ``state`` keys (all optional; absence fails the relevant gate closed):
      - ``recent_evaluations``: list of ``{"all_valid": bool}`` (newest-first
        ordering is irrelevant — Stage A is a count + conjunction).
      - ``stage_a_min_clean_fires``: int override for the Stage A threshold.
      - ``stage_b_checks``: ``{b1..b5: bool}``.
      - ``phase_2_checks``: ``{p2_1..p2_4: bool}``.
      - ``phase_3_checks``: ``{godmode_exists, godmode_has_standing_directive,
        godmode_execution_target_is_local_cron, godmode_role_is_set,
        dream_team_seeded: bool}``.

    ``context`` (optional): may carry ``stage_a_min_clean_fires`` as a
    threshold override (state takes precedence over context).

    Returns ``{output, rationale, self_metric}``.
    """
    if not isinstance(state, dict):
        state = {}
    if not isinstance(context, dict):
        context = {}

    # Resolve the Stage A threshold: state > context > default. A non-int or
    # non-positive override falls back to the pinned default.
    min_clean = state.get("stage_a_min_clean_fires")
    if not _is_pos_int(min_clean):
        min_clean = context.get("stage_a_min_clean_fires")
    if not _is_pos_int(min_clean):
        min_clean = DEFAULT_STAGE_A_MIN_CLEAN_FIRES

    evals = state.get("recent_evaluations")
    stage_b = state.get("stage_b_checks")
    phase_2 = state.get("phase_2_checks")
    phase_3 = state.get("phase_3_checks")

    # --- the four ordered gates ---------------------------------------- #
    stage_a_complete = _is_recent_streak_clean(evals, min_clean)
    stage_b_complete = _all_true(stage_b, STAGE_B_KEYS)
    phase_2_unlocked = _all_true(phase_2, PHASE_2_KEYS)

    godmode_healthy = _all_true(phase_3, GODMODE_HEALTH_KEYS)
    dream_team_seeded = isinstance(phase_3, dict) and phase_3.get("dream_team_seeded") is True
    phase_3_complete = godmode_healthy and dream_team_seeded

    gate_done = {
        "stage_a": stage_a_complete,
        "stage_b": stage_b_complete,
        "phase_2": phase_2_unlocked,
        "phase_3": phase_3_complete,
    }

    # current_stage = the first gate not yet complete (the actionable
    # frontier); "complete" when all four are open.
    current_stage = "complete"
    for name in _STAGE_ORDER:
        if not gate_done[name]:
            current_stage = name
            break

    blockers = _blockers_for_stage(
        current_stage, evals, min_clean, stage_b, phase_2, phase_3,
        godmode_healthy, dream_team_seeded,
    )
    next_actions = _next_actions(current_stage, blockers)

    # --- confidence: fraction of the four evidence sections supplied --- #
    sections = [evals is not None, stage_b is not None,
                phase_2 is not None, phase_3 is not None]
    sections_present = sum(1 for s in sections if s)
    confidence = round(sections_present / 4.0, 3)
    gates_open = sum(1 for v in gate_done.values() if v)

    output = {
        "stage_a_complete": stage_a_complete,
        "stage_b_complete": stage_b_complete,
        "phase_2_unlocked": phase_2_unlocked,
        "phase_3_complete": phase_3_complete,
        "godmode_healthy": godmode_healthy,
        "current_stage": current_stage,
        "blockers": blockers,
        "next_actions": next_actions,
    }

    return {
        "output": output,
        "rationale": _rationale(current_stage, gate_done, gates_open, blockers),
        "self_metric": {
            "confidence": confidence,
            "sections_present": sections_present,
            "sections_total": 4,
            "gates_open": gates_open,
            "gates_total": 4,
        },
    }


# --------------------------------------------------------------------------- #
# Helpers.                                                                     #
# --------------------------------------------------------------------------- #

def _is_pos_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _blockers_for_stage(
    current_stage: str,
    evals: Any,
    min_clean: int,
    stage_b: Any,
    phase_2: Any,
    phase_3: Any,
    godmode_healthy: bool,
    dream_team_seeded: bool,
) -> List[str]:
    """Human-readable blockers for the current (frontier) gate only.

    Reporting only the frontier keeps the advice actionable — there's no
    point listing Phase 3 blockers while Stage A is still pending.
    """
    if current_stage == "complete":
        return []

    if current_stage == "stage_a":
        n = len(evals) if isinstance(evals, list) else 0
        clean = sum(1 for r in (evals if isinstance(evals, list) else []) if _row_all_valid(r))
        return [
            f"Stage A: {clean}/{min_clean} clean fire windows "
            f"({n} evaluation(s) provided)"
        ]

    if current_stage == "stage_b":
        return [_BLOCKER_LABELS[k] for k in _failing_keys(stage_b, STAGE_B_KEYS)]

    if current_stage == "phase_2":
        return [_BLOCKER_LABELS[k] for k in _failing_keys(phase_2, PHASE_2_KEYS)]

    # phase_3
    failing = _failing_keys(phase_3, GODMODE_HEALTH_KEYS)
    blockers = [_BLOCKER_LABELS[k] for k in failing]
    if not dream_team_seeded:
        blockers.append(_BLOCKER_LABELS["dream_team_seeded"])
    return blockers


def _next_actions(current_stage: str, blockers: List[str]) -> List[str]:
    if current_stage == "complete":
        return ["All gates open — platform ready for full fleet operation"]
    headline = {
        "stage_a": "Accumulate clean fire-window evaluations",
        "stage_b": "Resolve the remaining Stage B blockers",
        "phase_2": "Satisfy the remaining Phase 2 unlock conditions",
        "phase_3": "Bring Godmode and the dream team to healthy",
    }[current_stage]
    return [headline] + blockers


def _rationale(
    current_stage: str,
    gate_done: Dict[str, bool],
    gates_open: int,
    blockers: List[str],
) -> str:
    if current_stage == "complete":
        return (
            "All four gates (Stage A, Stage B, Phase 2, Phase 3) are open; "
            "the autonomous self-improvement loop is fully unlocked."
        )
    open_names = [k for k in _STAGE_ORDER if gate_done[k]]
    opened = ", ".join(open_names) if open_names else "none"
    blk = "; ".join(blockers) if blockers else "no data supplied"
    return (
        f"{gates_open}/4 gates open (open: {opened}). Frontier gate is "
        f"'{current_stage}', blocked by: {blk}."
    )


# --------------------------------------------------------------------------- #
# CLI runner (CONTRACT entrypoint): read {state, context} from ORGAN_INPUT    #
# env file or stdin, print the decision to stdout.                            #
# --------------------------------------------------------------------------- #

def main() -> int:
    import json
    import os
    import sys

    path = os.environ.get("ORGAN_INPUT")
    raw = open(path).read() if path else sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
        state = payload.get("state", {})
        context = payload.get("context")
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"invalid input: {e}"}), file=sys.stderr)
        return 1
    print(json.dumps(decide(state, context), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
