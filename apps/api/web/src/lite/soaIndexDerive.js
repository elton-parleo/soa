/**
 * F5: SoA Index — the report's competitor share table, derived from the
 * same visibility.share_of_mentions the report already receives
 * (lite_visibility.py::build_visibility_payload) — no new backend field,
 * since that payload already carries {entity, is_primary, mentions,
 * share_pct} per entity. This module owns the one thing that isn't
 * already there: the flat, illustrative "if you closed the gap" bar.
 *
 * PROJECTED_SHARE_UPLIFT_PCT is a single named constant — not a model,
 * not per-dimension math — so the report and any other surface that
 * ever needs it import this one value rather than re-typing 17.
 */
export const PROJECTED_SHARE_UPLIFT_PCT = 17

export const SOA_INDEX_PROJECTED_LABEL = 'ILLUSTRATIVE · A FLAT +17 POINTS, NOT A FORECAST'

/**
 * shareOfMentions: visibility.share_of_mentions, as returned by the API
 * ([{entity, is_primary, mentions, share_pct}, ...]).
 *
 * Returns {rows, you, projectedLabel}. rows carry {name, share} for
 * every entity, plus `projected` on the primary row only when its share
 * is a real, measurable number (H1: no fabricated projection over an
 * unmeasurable primary share) — projectedLabel is null in that case too,
 * so the illustrative caption never renders over a missing bar.
 */
export function buildSoaIndexRows(shareOfMentions) {
  const rows = (shareOfMentions || []).map((e) => ({ name: e.entity, share: e.share_pct }))
  const primary = (shareOfMentions || []).find((e) => e.is_primary)
  const primaryMeasurable = primary && typeof primary.share_pct === 'number' && !Number.isNaN(primary.share_pct)

  if (primaryMeasurable) {
    const row = rows.find((r) => r.name === primary.entity)
    if (row) row.projected = Math.min(100, Math.round(primary.share_pct + PROJECTED_SHARE_UPLIFT_PCT))
  }

  return {
    rows,
    you: primary ? primary.entity : null,
    projectedLabel: primaryMeasurable ? SOA_INDEX_PROJECTED_LABEL : null,
  }
}
