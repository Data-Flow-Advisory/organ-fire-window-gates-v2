# Corpus + OSS Audit — organ-fire-window-gates-v2

**Date:** 2026-06-11 · **Auditor:** DFA fleet (item 19962) · stamped in `ports.json` `_checked`.

## (A) Corpus check — is this a duplicate?

| Sibling organ | Capability | Source module | Relationship to v2 |
|---|---|---|---|
| `organ-fire-window-gates` (v1) | **Same** — Stage A/B, Phase 2/3 readiness gates | `fire_window_gates.py` | **Duplicate by design.** v2 is the clean fork; v1 has RED CI (conformance copy-pasted from an unrelated *service-health-monitor* organ — asserts `output.overall`/`output.actions`, loads non-existent `healthy_state.json`). v2 supersedes it. |
| `organ-fire-window-evaluator` | Validates one cloud-fire-report's `metadata_json` (13 leaf predicates) | `fire_window_predicates.py` + `fire_window_evaluator.py` | **Not a duplicate.** Tier-1 per-report metadata validation, different source + different `decide()` contract (`fire_metadata` in, predicate-validity out). |
| `organ-fire-window-predicates` | Validates cloud worker fire-window metadata | fire-window validation logic | **Not a duplicate of v2.** Same Tier-1 metadata-validation capability as `evaluator` (the two appear to overlap *each other* — out of scope for this item). |

**Verdict: DUPLICATE of `organ-fire-window-gates` (v1) — but intentional.**
v2 is the clean re-extraction per the "a failed organ can be forked" rule. The
actionable item is to **archive v1** so the corpus carries one live copy of the
gate logic, not two. v2 is the keeper (green CI, 27 tests, self-consistent
conformance harness). Tracked in a flagging issue on `organ-fire-window-gates`.

## (B) OSS check — should we adopt instead of maintain?

**Verdict: KEEP.** Surveyed generic Python rules engines — `rule-engine`,
`py-rules-engine`, `Arta`, `PredyLogic`, `pyKE`, `Intellect`. All are generic
DSL/predicate-evaluation frameworks; none encodes a "platform fire-window
readiness ladder." This organ's value is its *domain semantics* (which checks
compose into which gate, the strict-`True` guard that catches "passed the
function not its result", the frontier/blocker derivation), not generic boolean
evaluation. Adopting a rules engine would replace ~200 lines of stdlib-only,
deterministic, fail-safe domain logic with a heavier dependency for no gain and
break the organ's stdlib-only contract. Re-survey on the next `oss_checked`
window (21d).

## Faithfulness

`organ.py` still mirrors `fire_window_gates.py`'s pure `*_from_results` /
`*_from_rows` helpers. Sample run + `pytest` clean (27 passed) on 2026-06-11.
