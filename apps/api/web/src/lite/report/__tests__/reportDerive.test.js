/**
 * Mobile rail replacement (RM1): buildNavItems was extracted from
 * ReportRail.jsx so the desktop rail and the new phone sections sheet
 * (MobileReportNav.jsx) share one source of per-section score labels —
 * these tests lock in that shared contract directly, independent of
 * either renderer.
 */
import { describe, it, expect } from 'vitest'
import {
  buildNavItems, deriveReportViewedState, partialReadFailurePoint,
  deriveScoreBandHeadline, resolvePillarHeadline,
  PILLAR_VISIBILITY, PILLAR_ACCESSIBILITY, PILLAR_TRUE_VALUE,
  NOT_MEASURABLE_HEADLINE,
} from '../reportDerive.js'

function _pillars(overrides = {}) {
  return {
    visibility: { dimensions: [{ code: 'x', earned: 25, max: 40, na: false }] },
    accessibility: { dimensions: [{ code: 'y', earned: 8, max: 20, na: false }] },
    true_value: { dimensions: [{ code: 'z', earned: 3, max: 40, na: false }] },
    ...overrides,
  }
}

describe('buildNavItems', () => {
  it('returns one entry per nav id except "fun", in NAV_IDS order', () => {
    const items = buildNavItems({ pillars: _pillars(), composite: 40, exposure: 100000, active: 'score' })
    expect(items.map((i) => i.id)).toEqual(['score', 'viz', 'acc', 'tv', 'fix', 'truesync', 'exp'])
  })

  it('scores composite/pillar rows as earned/max, rounded', () => {
    const items = buildNavItems({ pillars: _pillars(), composite: 40.4, exposure: 100000, active: 'score' })
    const byId = Object.fromEntries(items.map((i) => [i.id, i.score]))
    expect(byId.score).toBe('40/100')
    expect(byId.viz).toBe('25/40')
    expect(byId.acc).toBe('8/20')
    expect(byId.tv).toBe('3/40')
  })

  it('caps the ranked-fixes score at +20 even when the true gap is larger', () => {
    const items = buildNavItems({
      pillars: _pillars({
        visibility: { dimensions: [{ code: 'x', earned: 0, max: 40, na: false }] },
        accessibility: { dimensions: [{ code: 'y', earned: 0, max: 20, na: false }] },
        true_value: { dimensions: [{ code: 'z', earned: 0, max: 40, na: false }] },
      }),
      composite: 0, exposure: 100000, active: 'score',
    })
    expect(items.find((i) => i.id === 'fix').score).toBe('+20')
  })

  it('the fix score never goes negative when a pillar is already at its max', () => {
    const items = buildNavItems({
      pillars: _pillars({
        visibility: { dimensions: [{ code: 'x', earned: 40, max: 40, na: false }] },
        accessibility: { dimensions: [{ code: 'y', earned: 20, max: 20, na: false }] },
        true_value: { dimensions: [{ code: 'z', earned: 40, max: 40, na: false }] },
      }),
      composite: 100, exposure: 0, active: 'score',
    })
    expect(items.find((i) => i.id === 'fix').score).toBe('+0')
  })

  it('truesync always reads "TrueSync", never a number', () => {
    const items = buildNavItems({ pillars: _pillars(), composite: 40, exposure: 100000, active: 'score' })
    expect(items.find((i) => i.id === 'truesync').score).toBe('TrueSync')
  })

  it('formats exposure as $NK under $1M and $N.NM / $NM at or above it', () => {
    const at = (exposure) => buildNavItems({ pillars: _pillars(), composite: 40, exposure, active: 'score' }).find((i) => i.id === 'exp').score
    expect(at(45000)).toBe('$45K')
    expect(at(2_500_000)).toBe('$2.5M')
    expect(at(12_000_000)).toBe('$12M')
    expect(at(null)).toBe('—')
  })

  it('marks exactly the active id `on`, every other id false', () => {
    const items = buildNavItems({ pillars: _pillars(), composite: 40, exposure: 100000, active: 'tv' })
    const on = items.filter((i) => i.on)
    expect(on).toHaveLength(1)
    expect(on[0].id).toBe('tv')
  })

  it('composite null renders 0/100, never a fabricated score', () => {
    const items = buildNavItems({ pillars: _pillars(), composite: null, exposure: 100000, active: 'score' })
    expect(items.find((i) => i.id === 'score').score).toBe('0/100')
  })

  it('omits the transcript row entirely when transcript is null/absent', () => {
    const items = buildNavItems({ pillars: _pillars(), composite: 40, exposure: 100000, active: 'score' })
    expect(items.find((i) => i.id === 'transcript')).toBeUndefined()
  })

  it('includes a transcript row scored query_index/total_queries when transcript is present', () => {
    const items = buildNavItems({
      pillars: _pillars(), composite: 40, exposure: 100000, active: 'score',
      transcript: { query_index: 14, total_queries: 24 },
    })
    const row = items.find((i) => i.id === 'transcript')
    expect(row).toBeDefined()
    expect(row.score).toBe('14/24')
    // Placed between visibility and accessibility, per the widget's spec.
    expect(items.map((i) => i.id)).toEqual(['score', 'viz', 'transcript', 'acc', 'tv', 'fix', 'truesync', 'exp'])
  })
})

describe('deriveReportViewedState — analytics report_viewed.state vocabulary', () => {
  const fullyMeasuredPillars = {
    visibility: { dimensions: [{ code: 'x', earned: 25, max: 40, na: false, blocked: false }] },
    accessibility: { dimensions: [{ code: 'y', earned: 8, max: 20, na: false, blocked: false }] },
    true_value: { dimensions: [{ code: 'z', earned: 3, max: 40, na: false, blocked: false }] },
  }

  function withBlockedDim() {
    return {
      ...fullyMeasuredPillars,
      true_value: { dimensions: [{ code: 'z', earned: 0, max: 40, na: false, blocked: true }] },
    }
  }

  it('a clean, fully-measured run derives "scored"', () => {
    expect(deriveReportViewedState(fullyMeasuredPillars, null)).toBe('scored')
  })

  it('a blocked dimension with degraded_reason="blocked" derives "blocked"', () => {
    expect(deriveReportViewedState(withBlockedDim(), 'blocked')).toBe('blocked')
  })

  it('a blocked dimension with no named degraded_reason derives "partial"', () => {
    expect(deriveReportViewedState(withBlockedDim(), null)).toBe('partial')
  })

  it('degraded_reason="unreachable" derives "blocked" — a wall that never answered (Lululemon)', () => {
    expect(deriveReportViewedState(withBlockedDim(), 'unreachable')).toBe('blocked')
  })

  it('an unreachable discoveryOutcome code derives "blocked" too', () => {
    expect(deriveReportViewedState(withBlockedDim(), null, { code: 'unreachable' })).toBe('blocked')
  })

  it('with no named degraded_reason, a blocking discoveryOutcome code derives "blocked" too', () => {
    expect(deriveReportViewedState(withBlockedDim(), null, { code: 'sitemaps_robots_disallowed' })).toBe('blocked')
  })
})

describe('partialReadFailurePoint — Discovery follow-up (Part 4)', () => {
  it('degradedReason still wins outright when set, regardless of discoveryOutcome', () => {
    expect(partialReadFailurePoint('no_product_pages_found', { code: 'sitemaps_refused' })).toBe('no_product_pages_found')
    expect(partialReadFailurePoint('blocked', { code: 'no_sitemap' })).toBe('blocked')
  })

  it('a genuine refusal/short-circuit code reads as "blocked", never our own limitation', () => {
    for (const code of ['product_pages_refused', 'sitemaps_refused', 'sitemaps_robots_disallowed', 'short_circuited']) {
      expect(partialReadFailurePoint(null, { code })).toBe('blocked')
    }
  })

  it('a not-found-shaped code reads as "no_product_pages_found"', () => {
    for (const code of [
      'no_sitemap', 'product_sitemap_unrecognized', 'sitemap_children_unprobed',
      'sitemaps_non_catalog', 'homepage_no_links', 'rescue_tiers_skipped',
      'product_pages_unreadable', 'unknown',
    ]) {
      expect(partialReadFailurePoint(null, { code })).toBe('no_product_pages_found')
    }
  })

  it('no discoveryOutcome and no degradedReason falls back to "partial", the original case', () => {
    expect(partialReadFailurePoint(null, null)).toBe('partial')
    expect(partialReadFailurePoint(undefined, undefined)).toBe('partial')
  })

  it('a code that is not a discovery failure at all (product_pages_read) also falls back to "partial"', () => {
    expect(partialReadFailurePoint(null, { code: 'product_pages_read' })).toBe('partial')
  })
})

describe('deriveScoreBandHeadline — Part B score-derived fallback', () => {
  function _report(pillarKey, earned, max) {
    return { pillars: { [pillarKey]: { dimensions: [{ code: 'x', earned, max, na: false }] } } }
  }

  it('>= .75 is the positive band, per pillar', () => {
    expect(deriveScoreBandHeadline(_report(PILLAR_VISIBILITY, 30, 40), PILLAR_VISIBILITY))
      .toBe('Agents recognize you and bring you up often')
    expect(deriveScoreBandHeadline(_report(PILLAR_ACCESSIBILITY, 15, 18), PILLAR_ACCESSIBILITY))
      .toBe('Agents can read most of what you publish')
    expect(deriveScoreBandHeadline(_report(PILLAR_TRUE_VALUE, 30, 40), PILLAR_TRUE_VALUE))
      .toBe('Your value reaches agents clearly')
  })

  it('.40 - .75 (inclusive of .40) is the mixed band, per pillar', () => {
    expect(deriveScoreBandHeadline(_report(PILLAR_VISIBILITY, 25, 40), PILLAR_VISIBILITY))
      .toBe("Agents know you, but don't always mention you")
    expect(deriveScoreBandHeadline(_report(PILLAR_ACCESSIBILITY, 8, 20), PILLAR_ACCESSIBILITY))
      .toBe("Agents can knock, but can't read everything")
    expect(deriveScoreBandHeadline(_report(PILLAR_TRUE_VALUE, 20, 50), PILLAR_TRUE_VALUE))
      .toBe("Some of your value reaches the answer, some doesn't")
  })

  it('< .40 is the negative band — the pre-Part-B line, unchanged', () => {
    expect(deriveScoreBandHeadline(_report(PILLAR_VISIBILITY, 5, 40), PILLAR_VISIBILITY))
      .toBe('Agents know who you are')
    expect(deriveScoreBandHeadline(_report(PILLAR_ACCESSIBILITY, 2, 20), PILLAR_ACCESSIBILITY))
      .toBe("Agents can knock, but can't read much")
    expect(deriveScoreBandHeadline(_report(PILLAR_TRUE_VALUE, 3, 40), PILLAR_TRUE_VALUE))
      .toBe('Your value leaks before it reaches the answer')
  })

  it('max === 0 (nothing measured) reads as not-measurable, never a fabricated negative band', () => {
    expect(deriveScoreBandHeadline(_report(PILLAR_VISIBILITY, 0, 0), PILLAR_VISIBILITY)).toBe(NOT_MEASURABLE_HEADLINE)
  })

  it('the exact regression this fixes: a 14/18 accessibility score never reads the negative line', () => {
    const headline = deriveScoreBandHeadline(_report(PILLAR_ACCESSIBILITY, 14, 18), PILLAR_ACCESSIBILITY)
    expect(headline).not.toBe("Agents can knock, but can't read much")
    expect(headline).toBe('Agents can read most of what you publish')
  })
})

describe('resolvePillarHeadline — priority: generated > not_measurable > derived', () => {
  const report = { pillars: { visibility: { dimensions: [{ code: 'x', earned: 25, max: 40, na: false }] } } }

  it('a generated headline wins outright, regardless of the real score', () => {
    const withGenerated = { ...report, generated_headlines: { visibility: { headline: 'You hold 35% share.', source: 'generated' } } }
    expect(resolvePillarHeadline(withGenerated, PILLAR_VISIBILITY)).toEqual({ headline: 'You hold 35% share.', source: 'generated' })
  })

  it('an explicit not_measurable source is honored verbatim, never overridden by a derived band', () => {
    const withNotMeasurable = { ...report, generated_headlines: { visibility: { headline: NOT_MEASURABLE_HEADLINE, source: 'not_measurable' } } }
    expect(resolvePillarHeadline(withNotMeasurable, PILLAR_VISIBILITY)).toEqual({ headline: NOT_MEASURABLE_HEADLINE, source: 'not_measurable' })
  })

  it('no generated_headlines at all falls through to a score-derived line, source "derived"', () => {
    expect(resolvePillarHeadline(report, PILLAR_VISIBILITY)).toEqual({
      headline: "Agents know you, but don't always mention you", source: 'derived',
    })
  })

  it('a legacy source value (pre-Part-B "default") also falls through to derivation, not a crash', () => {
    const legacy = { ...report, generated_headlines: { visibility: { headline: 'Agents know who you are', source: 'default' } } }
    expect(resolvePillarHeadline(legacy, PILLAR_VISIBILITY)).toEqual({
      headline: "Agents know you, but don't always mention you", source: 'derived',
    })
  })

  it('reports source "not_measurable" (not "derived") when the derived band itself has nothing to measure', () => {
    const nothingMeasured = { pillars: { visibility: { dimensions: [{ code: 'x', earned: 0, max: 0, na: false }] } } }
    expect(resolvePillarHeadline(nothingMeasured, PILLAR_VISIBILITY)).toEqual({
      headline: NOT_MEASURABLE_HEADLINE, source: 'not_measurable',
    })
  })
})
