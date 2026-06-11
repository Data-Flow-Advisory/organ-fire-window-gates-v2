# CONTRACT — organ-fire-window-gates-v2

Canonical contract for the fire-window-gates organ. A **pure,
deterministic, stdlib-only** decider re-extracted from discovery-engine's
`app/services/fire_window_gates.py`. It decides which platform-readiness
**gates** are open, given a handed-in snapshot of fire-window evaluations,
blocker booleans, and Godmode/dream-team health.

> This is a clean fork of `organ-fire-window-gates` (v1), whose conformance
> workflow was copy-pasted from an unrelated service-health-monitor organ
> (it asserted `output.overall` / `output.actions` and loaded
> `healthy_state.json` samples that never existed) and therefore went RED
> against correct gate logic. v2 re-extracts the logic and ships a
> self-consistent conformance harness.

## Entry point

```python
def decide(state: dict, context: dict | None = None) -> dict: ...
```

- **Pure** — no DB, no network, no filesystem, no globals. The organ is
  *handed* its facts in `state`; it never fetches them (the production
  module's `recent_evaluations()`, persona loaders, and `PlatformEvent`
  counts stay in the spine).
- **Deterministic** — same `(state, context)` always yields the same output.
- **Fail-safe to the conservative verdict** — on empty / malformed `state`
  every gate is reported CLOSED with low confidence; never a
  confident-wrong "everything open".
- **Stdlib-only.**

A CLI runner (`main()`) reads `{state, context}` from the file named by
`ORGAN_INPUT`, or from stdin, and prints the decision JSON to stdout.
Exit `0` = decided (a "not ready" verdict is still `0`); non-zero = the
organ itself failed (unparseable input).

## Input

```jsonc
{
  "state": {
    "recent_evaluations": [ { "all_valid": true }, ... ],   // newest-first irrelevant
    "stage_a_min_clean_fires": 3,                            // optional threshold override
    "stage_b_checks":  { "b1": true, "b2": true, "b3": true, "b4": true, "b5": true },
    "phase_2_checks":  { "p2_1": true, "p2_2": true, "p2_3": true, "p2_4": true },
    "phase_3_checks":  {
      "godmode_exists": true,
      "godmode_has_standing_directive": true,
      "godmode_execution_target_is_local_cron": true,
      "godmode_role_is_set": true,
      "dream_team_seeded": true
    }
  },
  "context": { "stage_a_min_clean_fires": 3 }                // optional; state wins over context
}
```

Every `state` section is optional; an absent section fails its gate closed.

## The four ordered gates (faithful to the source's pure helpers)

| Gate | Opens when | Source helper |
|------|-----------|---------------|
| **Stage A** | ≥ N `recent_evaluations` AND every one `all_valid` (N = `stage_a_min_clean_fires`, default 3) | `_stage_a_is_complete_for_rows` / `is_recent_streak_clean` |
| **Stage B** | `b1..b5` all strictly `true` | `_stage_b_is_complete_from_results` |
| **Phase 2** | `p2_1..p2_4` all strictly `true` | `_phase_2_is_unlocked_from_results` |
| **Phase 3** | `godmode_healthy` (the four `godmode_*` checks all `true`) AND `dream_team_seeded` | `_phase_3_is_complete_from_results` |

Mirroring the source, conjunction inputs must be **strictly boolean `True`**
— a truthy non-bool (`1`, `"yes"`) is rejected, catching the "passed the
function, not its result" bug. A missing key fails closed.

## Output

```jsonc
{
  "output": {
    "stage_a_complete": false,
    "stage_b_complete": false,
    "phase_2_unlocked": false,
    "phase_3_complete": false,
    "godmode_healthy": false,
    "current_stage": "stage_a",          // first incomplete gate, or "complete"
    "blockers": [ "Stage A: 2/3 clean fire windows (3 evaluation(s) provided)" ],
    "next_actions": [ "Accumulate clean fire-window evaluations", ... ]
  },
  "rationale": "Human-readable why, derivable from state alone.",
  "self_metric": {
    "confidence": 0.0,                   // fraction of the 4 evidence sections supplied
    "sections_present": 0,
    "sections_total": 4,
    "gates_open": 0,
    "gates_total": 4
  }
}
```

`current_stage` is the **actionable frontier** — the first gate (in order
Stage A → Stage B → Phase 2 → Phase 3) that is not yet open, or `"complete"`
when all four are open. `blockers` reports only the frontier gate's failing
checks, so the advice stays actionable. `confidence` is the fraction of the
four evidence sections present (empty state → `0.0`; all four → `1.0`).

## Conformance

`.github/workflows/conformance.yml` enforces this contract on every push/PR:
it shadow-runs `organ.py` on every `samples/*.json` (each a runnable
`{state, context}`) and reports each decision to the job summary, then runs
`test_organ.py`. The tests assert the output shape, the four gate semantics,
the strict-bool guard, fail-safe on empty/`None`/garbage state, threshold
precedence, frontier/blocker behaviour, determinism, and that every sample
runs clean through the CLI.
