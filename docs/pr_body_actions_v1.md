# Actions v1 — SoA recommendation engine (findings → playbook → prioritized actions)

Adds the Actions feature to AC3: a deterministic recommendation engine that
detects findings from completed cycle metrics, maps them to a curated
remediation playbook, and surfaces prioritized, evidence-linked
recommendations in the Results UI. Also includes the observation-grain
incentive-scoring refactor and ground-truth validity gate this feature
surfaced as prerequisites.

## Core feature

**Data model** — three new tables via Alembic migrations:
- `soa_playbook` — curated remediation play library (22 plays across
  Visibility / Accessibility / True Value Delivery / Fidelity), seeded
  from `docs/playbook_v1.md` (doc and seed reconciled, idempotent upsert
  by `play_id`)
- `soa_findings` — detector output at entity × dimension × surface ×
  persona/stage grain, with `severity`, `metric_snapshot` (the exact
  values that tripped the rule), and `evidence_run_ids`
- `soa_recommendations` — one per (cycle, play), aggregating findings,
  with `priority_score`, status lifecycle (proposed / accepted /
  in_progress / done / dismissed), and composite suppression

**Finding detector** (`services/finding_detector.py`) — deterministic,
read-only over metrics; one registered detector per implemented play
(6 implemented: VIS-01/05/06/07, TVD-01/03; remainder seeded as
`not_implemented` with verified data dependencies). All thresholds in
config, none hardcoded. Idempotent per cycle.

**Recommendation mapper** (`services/recommendation_mapper.py`) —
priority = mean(severity) × cells_affected ÷ effort_weight; TVD-07
composite suppression; upserts by (cycle, play) preserving user-set
status and row ids across regeneration.

**API** (`routers/actions.py`) — generate, list recommendations
(+`include_suppressed`), list findings, PATCH recommendation status.
Response includes `coverage_gaps` (see validity gate).

**Frontend** — new Actions page under Results: recommendation cards with
owner/effort badges, percentile-based priority tier chips
(Critical / High / Moderate; raw score as tooltip), status control, and
evidence deep-links into Response Explorer.

## Coding-stage pass 2 (observation grain)

- Per-observation merchant attribution: every price/offer observation
  persists its own `{stated_price, merchant_name, merchant_slug}` —
  multi-retailer responses yield multiple observations. Versioned as
  pass 2; pass-1 fields untouched (zero regression drift by construction).
- Brand/merchant homonym guard: brand self-references (e.g. "Pampers"
  as source for a Pampers entity) only map to the D2C merchant on
  explicit channel signal; otherwise a distinct queryable
  `brand_self_reference` status.
- Citation extraction per response ({url, domain, context}), written to
  a new `soa_citations` table — raw material for VIS-02 (its detection
  trigger explicitly requires citation extraction).
- Idempotency sentinel (`soa_pass2_coding_log`) so zero-yield runs
  aren't re-queried.
- Cycle 55 fully re-coded from stored raw responses (825/825): 2,072
  price observations vs. 332 legacy scalar rows.

## Observation-grain incentive scoring

- `soa_incentive_scores` migrated to (entity, merchant, run,
  observation) grain; legacy rows preserved and flagged.
- Scorer iterates observations, resolving merchant per observation
  (explicit attribution → link domain → constrained fallback), with
  per-observation failure statuses, payload-level engine-call caching,
  and per-cycle idempotency.
- Merchant table expanded (costco, cvs, walgreens, sams-club, kroger,
  ebay) with normalized name→slug re-resolution over existing coded data
  (no re-code): resolution rate 86.5% → 91.0%.
- Resolution-rate assertion redefined to mapped/(mapped+unmapped) with
  rationale documented; raw mapped share still logged.

## Ground-truth validity gate

- `measurement_status` on scored rows, derived from whether the Deal
  Engine evaluated any deals (confidence rejected as signal — flat in
  the no-data case). TVD detectors and Net Price Accuracy / Offer
  Completeness compute over measured rows only.
- Cells with zero measured rows surface as
  `insufficient_ground_truth_coverage` via `coverage_gaps` — unmeasured
  is never reported as accurate.
- One follow-up migration adds the two indexes (`soa_price_observations.
  run_id`, `soa_incentive_scores.price_observation_id`) that the ORM
  models declared but the original observation-grain migrations didn't
  create — caught by running `alembic check` against a from-scratch DB
  before merge.

## Bugs found & fixed along the way (with regression tests)

- VIS-07 leader selection inverted (`min` on a higher-is-better index)
  + an unreachable threshold unit
- Regeneration silently reset user-set recommendation statuses
  (delete-then-insert → status-preserving upsert)
- Documented-by-test behavior for recommendations whose play stops firing

## Validation

- 249 tests passing (191 pipeline, 49 API, 9 frontend)
- End-to-end pressure-tested on cycle 55 (825 runs): idempotent
  regeneration, status preservation, VIS findings invariant under
  scoring changes
- First real TVD-01 findings produced: 2 cells on Amazon (e.g. 103
  scored observations across 57 runs quoting prices that ignore an
  active Subscribe & Save discount, mean gap 5.3%), with full evidence
  transcripts; 26 cells correctly reported as insufficient coverage
  pending Deal Engine ingestion
- Migration chain verified end-to-end: all 30 migrations apply cleanly
  to a from-scratch database, and `alembic check` reports no structural
  drift between the shared ORM models and the migrations

## Out of scope / follow-ups

- Deal Engine deal ingestion for Target/Walmart/Costco et al.
  (supply-app repo; measurement-status table is the prioritized backlog)
- VIS-02 detector (now unblocked by citation extraction)
- TVD-03 member-tier personas (next study's query design)
- TVD-01 threshold calibration note: gaps cluster at ~5.3%, consistent
  with S&S being a flat 5% mechanic — worth revisiting the 5% threshold
  once more merchants have real deal coverage
