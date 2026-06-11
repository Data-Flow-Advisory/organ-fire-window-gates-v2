# organ-fire-window-gates-v2

A **pure decision organ** for platform fire-window readiness gates,
re-extracted from discovery-engine's `app/services/fire_window_gates.py`.

It reads a snapshot of fire-window evaluations + blocker booleans + Godmode
health and decides **which readiness gates are open** — advice only, never
an action. The production module composes these same pure predicates over
DB-loaded rows; this organ keeps only the pure core and is *handed* its
facts in `state`.

> **Why v2?** This is a clean fork of `organ-fire-window-gates`. The v1 repo
> had correct gate logic, but its conformance workflow was copy-pasted from
> an unrelated *service-health-monitor* organ — it asserted `output.overall`
> / `output.actions` and loaded `healthy_state.json` samples that did not
> exist, so CI went RED against working code. Per "a failed organ can be
> forked", v2 re-extracts cleanly with a self-consistent harness instead of
> patching in place.

## Contract

See [`CONTRACT.md`](CONTRACT.md). In short:

```python
from organ import decide

result = decide(state, context)   # -> {"output", "rationale", "self_metric"}
```

- **Pure / deterministic / stdlib-only.** No DB, network, or filesystem.
- **Fail-safe:** empty or malformed `state` → every gate CLOSED, confidence `0.0`.

## The four ordered gates

| Gate | Opens when |
|------|-----------|
| **Stage A** | last *N* fire-window evaluations all `all_valid` (default N = 3) |
| **Stage B** | blockers `b1..b5` all resolved |
| **Phase 2** | unlock conditions `p2_1..p2_4` all hold |
| **Phase 3** | Godmode healthy (4 config checks) **and** dream team seeded |

`output.current_stage` names the first incomplete gate (the actionable
frontier), or `"complete"`. `output.blockers` lists only that frontier
gate's failing checks.

## Run it

```bash
# via stdin
echo '{"state": {"recent_evaluations": [{"all_valid": true}]}}' | python3 organ.py

# via a sample file
ORGAN_INPUT=samples/phase_2_frontier.json python3 organ.py

# tests
python3 -m pytest -q
```

## Samples

- `samples/stage_a_pending.json` — a dirty fire breaks the streak; frontier = Stage A.
- `samples/phase_2_frontier.json` — Stage A + B done; frontier = Phase 2 (P2-3/P2-4 failing).
- `samples/all_gates_open.json` — every gate open; loop fully unlocked.
