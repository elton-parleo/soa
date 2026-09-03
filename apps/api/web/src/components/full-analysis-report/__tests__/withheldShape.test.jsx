/**
 * SHAPE regression for withheld values on the Full Analysis report.
 *
 * The bug this locks is not any one render site — it is a PATTERN. When
 * the crawl is blocked, cycle_scoring_full.py withholds composite,
 * verdict and tv_pct (returning null) precisely so the report cannot
 * assert things it never measured. Six separate consumers then treated
 * ABSENT as ZERO / FALSE / WORST and reconstructed the assertion anyway:
 *
 *   composite ?? 0            -> "0/100" in the nav
 *   verdict === 'AGENT-READY' -> "Not agent-ready", in red risk styling
 *   Number(null) -> 0         -> True Value 0 -> MAXIMUM modeled exposure
 *   formatCurrency(null)      -> "$0"
 *   earned/max ratio 0        -> "Your value leaks before it reaches the answer"
 *   tv.earned === 0           -> "They never talk about your value."
 *
 * Fixing the six was the easy half. A field-by-field sweep cannot prove
 * a SEVENTH consumer will not be added, so this test asserts the shape
 * over the whole rendered report instead of per call site: with the
 * report in state='unverified', the DOM must contain no verdict string,
 * no dollar figure, no severity styling, and no numeric score.
 *
 * If you are here because this test failed, you probably added a
 * consumer that reads a withheld value without asking whether it was
 * withheld. Route it through ./withheld.js rather than relaxing the
 * assertion.
 */
import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import FullAnalysisReport from '../../FullAnalysisReport.jsx'
import { verdictDisplay } from '../withheld.js'

vi.mock('../../../api.js', () => ({
  api: {
    getShareLink: vi.fn(), createShareLink: vi.fn(), revokeShareLink: vi.fn(), getMetrics: vi.fn(),
  },
}))

// Faithful to cycle_scoring_full.py's real blocked branch: max 0.0 (out
// of the applicable denominator), blocked:true on BOTH the dimension and
// its seen sub-lens, and the said row still attached.
const blockedDim = (code, name, seenMax, said) => ({
  code, name, earned: 0.0, max: 0.0, na: false, blocked: true, evidence: [],
  seen: { earned: 0.0, max: seenMax, na: false, blocked: true, evidence: ['blocked this run'] },
  said: said || null,
  said_envelope: said ? { state: 'measured', numerator: said.earned, denominator: said.max } : null,
  checks: [{ id: `${code}_blocked_0`, label: 'Checked on product pages', state: 'blocked', evidence: 'blocked this run' }],
  fix: null, fix_human: null,
})

// Modeled on the real cycle 20260902-230523-sephora-full: every fetch
// 403'd, so the five PDP-dependent dimensions are blocked while
// agent_access and value_protocols stay real-scored (requires_pdp=false),
// and Visibility is fully intact at 23/32.
const UNVERIFIED_REPORT = {
  cycle_code: 'blocked-cycle', rendered: true, degraded: true, reason: 'blocked',
  composite: null, verdict: null, scorer_version: '6', total_queries: 307,
  pillars: {
    composite: null, verdict: null, member_value_na: false, scorer_version: '6',
    state: 'unverified', tv_pct: null, unmeasured_count: 2,
    gap_areas_total: 4, gap_areas_parleo_fixes: 2, parleo_fixable_points: 0,
    exposure_reasons: [],
    visibility: {
      score: 72, max: 100.0,
      dimensions: [
        { code: 'share_of_mentions', name: 'Share of mentions', earned: 18, max: 22, na: false, evidence: [] },
        { code: 'recommendation_strength', name: 'Recommendation strength', earned: 5, max: 10, na: false, evidence: [] },
      ],
    },
    accessibility: {
      score: 0, max: 100.0,
      dimensions: [
        { code: 'agent_access', name: 'Agent access', earned: 0.0, max: 5, na: false, blocked: false, evidence: [], checks: [], fix: null, fix_human: null },
        blockedDim('catalog_context', 'Catalog context', 8),
        blockedDim('protocol_feed', 'Protocol feed', 5),
      ],
    },
    true_value: {
      score: 0, max: 100.0,
      dimensions: [
        blockedDim('price_truth', 'Price truth', 7, { earned: 0.0, max: 9, na: false, evidence: [] }),
        blockedDim('deal_citability', 'Deal citability', 7, { earned: 4, max: 5, na: false, evidence: [] }),
        { code: 'value_protocols', name: 'Value protocols', earned: 0.0, max: 14, na: false, evidence: [], seen: null, said: null, checks: [], fix: null, fix_human: null },
      ],
    },
    fixes: { visible: [], remaining_count: 0 },
  },
  platform_matrix: [], competitor_set: null, scan: { degraded_reason: 'blocked' }, offers: null,
  product_image_url: null, product_name: null,
  // The $10B probe estimate that made the un-suppressed figure $1.7B.
  revenue_estimate_usd: 10_000_000_000,
  evidence: null, continuation: null, generated_headlines: null, transcript: null,
}

async function renderUnverified() {
  const { container } = render(
    <FullAnalysisReport cycleCode="blocked-cycle" report={UNVERIFIED_REPORT} readOnly />,
  )
  await waitFor(() => expect(screen.getByText('AGENTIC VALUE SCORE')).toBeInTheDocument())
  return container
}

beforeEach(() => { vi.clearAllMocks() })

describe('Full Analysis — withheld values are never reconstructed', () => {
  it('renders no verdict string anywhere', async () => {
    const container = await renderUnverified()
    // The verdict is withheld server-side; no surface may re-derive it,
    // in either direction. Three chips render it (hero, rail, mobile nav).
    expect(container.textContent).not.toMatch(/Not agent-ready/i)
    expect(container.textContent).not.toMatch(/\bAgent-ready\b/i)
    expect(screen.getAllByText(/Unverified this run/i).length).toBeGreaterThan(0)
  })

  it('renders no dollar figure anywhere', async () => {
    const container = await renderUnverified()
    // Catches both failure modes: the saturated maximum ($1.7B, from
    // Number(null) -> trueValue 0 -> invisibility 1.0) and the
    // fabricated floor ($0, from formatCurrency(null)).
    expect(container.textContent).not.toMatch(/\$\s?[\d,]/)
  })

  it('applies no severity styling to a WITHHELD value', async () => {
    await renderUnverified()
    // Scoped to the verdict chip deliberately. An earlier draft of this
    // test forbade --red-tint anywhere in the tree and failed — on
    // price_truth's "IN ANSWERS" meter, which is red because said.earned
    // is a genuinely MEASURED zero from 310 run signals, not a withheld
    // one. That red is correct and must stay. The distinction is the
    // whole point of isWithheld(): 0 is a real result, only absent is
    // absent, and blanket-greying measured zeros would be its own kind
    // of dishonesty.
    for (const chip of screen.getAllByText(/Unverified this run/i)) {
      const styled = chip.closest('span[style]') || chip
      expect(styled.getAttribute('style') || '').not.toContain('--red-tint')
    }
    expect(verdictDisplay(UNVERIFIED_REPORT.pillars).tone).toBe('neutral')
  })

  it('still shows severity on a genuinely measured zero', async () => {
    const container = await renderUnverified()
    // The guard on over-correcting: price_truth's said half really did
    // score 0/9 this run, and the report should say so plainly.
    expect(container.innerHTML).toContain('--red-tint')
  })

  it('renders no numeric composite score, in any surface', async () => {
    const container = await renderUnverified()
    expect(container.textContent).not.toMatch(/\b0\/100\b/)
    // The em-dash placeholder is the only acceptable rendering.
    expect(container.textContent).toMatch(/—/)
  })

  it('still renders the measured half — Visibility is answer-side and intact', async () => {
    const container = await renderUnverified()
    // The point of rendering a degraded report at all. If this ever
    // fails we have withheld too much and should have fallen back.
    expect(container.textContent).toMatch(/18\/22|Share of mentions/i)
    expect(container.textContent).toMatch(/307/)
  })

  it('says why each blocked pillar could not be fully measured', async () => {
    const container = await renderUnverified()
    // Per-pillar, inline with the score it qualifies — not one banner
    // elsewhere on the page.
    expect(container.textContent).toMatch(/measurable this run/i)
  })
})
