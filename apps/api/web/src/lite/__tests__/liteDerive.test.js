import { describe, it, expect } from 'vitest'
import {
  looksLikeUrl, deriveBrandFromUrl, domainFromStoreUrl, accessibilityBadgeText,
  groupDimensionsByFamily, rankDimensionsByGap, computeExposure, formatCurrency,
  getScoreBand, getVerdictLine, getDominantRivalPayoff,
} from '../liteDerive.js'

describe('looksLikeUrl', () => {
  it('detects a bare domain as a URL', () => {
    expect(looksLikeUrl('acme.com')).toBe(true)
  })

  it('detects a full https URL', () => {
    expect(looksLikeUrl('https://shop.acme.com/products')).toBe(true)
  })

  it('rejects a plain brand name with no dot', () => {
    expect(looksLikeUrl('Drunk Elephant')).toBe(false)
  })

  it('rejects text containing a dot but also a space', () => {
    expect(looksLikeUrl('Acme Co. Inc')).toBe(false)
  })

  it('rejects empty input', () => {
    expect(looksLikeUrl('')).toBe(false)
    expect(looksLikeUrl(null)).toBe(false)
  })
})

describe('deriveBrandFromUrl', () => {
  it('derives from a bare two-label domain', () => {
    expect(deriveBrandFromUrl('acme.com')).toBe('Acme')
  })

  it('strips a common subdomain prefix', () => {
    expect(deriveBrandFromUrl('shop.acme-store.com')).toBe('Acme Store')
  })

  it('strips www', () => {
    expect(deriveBrandFromUrl('www.glossier.com')).toBe('Glossier')
  })

  it('handles a compound TLD reasonably by taking the leftmost label', () => {
    expect(deriveBrandFromUrl('acme.co.uk')).toBe('Acme')
  })

  it('title-cases hyphenated labels', () => {
    expect(deriveBrandFromUrl('drunk-elephant.com')).toBe('Drunk Elephant')
  })

  it('returns empty string for unparseable input', () => {
    expect(deriveBrandFromUrl('not a url at all')).toBe('')
  })

  it('returns empty string for empty input', () => {
    expect(deriveBrandFromUrl('')).toBe('')
  })
})

describe('domainFromStoreUrl', () => {
  it('strips scheme and www', () => {
    expect(domainFromStoreUrl('https://www.acme.com/products')).toBe('acme.com')
  })

  it('returns empty string when absent', () => {
    expect(domainFromStoreUrl(null)).toBe('')
    expect(domainFromStoreUrl('')).toBe('')
  })

  it('falls back to the raw value if unparseable', () => {
    expect(domainFromStoreUrl('not a url')).toBe('not a url')
  })
})

describe('accessibilityBadgeText', () => {
  it('returns null when the scan is complete', () => {
    expect(accessibilityBadgeText('complete')).toBeNull()
  })

  it.each([
    ['blocked', 'blocked'],
    ['failed', 'failed'],
    ['skipped', 'no store URL'],
    ['running', 'scanning…'],
    [null, 'scanning…'],
    [undefined, 'scanning…'],
  ])('maps %s to %s', (status, expected) => {
    expect(accessibilityBadgeText(status)).toBe(expected)
  })
})

describe('groupDimensionsByFamily', () => {
  it('splits Foundation (F1-F3) from Value (V1-V5)', () => {
    const dims = [
      { code: 'V1' }, { code: 'F1' }, { code: 'V5' }, { code: 'F3' }, { code: 'F2' },
      { code: 'V2' }, { code: 'V3' }, { code: 'V4' },
    ]
    const { foundation, value } = groupDimensionsByFamily(dims)
    expect(foundation.map((d) => d.code)).toEqual(['F1', 'F3', 'F2'])
    expect(value.map((d) => d.code)).toEqual(['V1', 'V5', 'V2', 'V3', 'V4'])
  })

  it('handles an empty/missing list', () => {
    expect(groupDimensionsByFamily(undefined)).toEqual({ foundation: [], value: [] })
  })
})

describe('rankDimensionsByGap', () => {
  it('sorts by (max - score) descending', () => {
    const dims = [
      { code: 'F1', score: 8, max: 10 },   // gap 2
      { code: 'V1', score: 5, max: 15 },   // gap 10
      { code: 'F3', score: 9, max: 10 },   // gap 1
    ]
    const ranked = rankDimensionsByGap(dims)
    expect(ranked.map((d) => d.code)).toEqual(['V1', 'F1', 'F3'])
  })

  it('breaks ties deterministically by code', () => {
    const dims = [
      { code: 'V2', score: 5, max: 10 },  // gap 5
      { code: 'F1', score: 5, max: 10 },  // gap 5
    ]
    const ranked = rankDimensionsByGap(dims)
    expect(ranked.map((d) => d.code)).toEqual(['F1', 'V2'])
  })

  it('does not mutate the input array', () => {
    const dims = [{ code: 'V1', score: 1, max: 10 }, { code: 'F1', score: 9, max: 10 }]
    const original = [...dims]
    rankDimensionsByGap(dims)
    expect(dims).toEqual(original)
  })
})

describe('computeExposure', () => {
  it('applies the documented formula: revenue * share * mentionGap * 0.85', () => {
    // revenue=1,000,000 * share=0.2 * mentionGap=(1-0.6)=0.4 * 0.85 = 68,000
    const exposure = computeExposure({ revenue: 1_000_000, aiSharePct: 20, visibility: 60 })
    expect(exposure).toBeCloseTo(68_000, 5)
  })

  it('treats missing visibility as zero (full mention gap)', () => {
    const exposure = computeExposure({ revenue: 100, aiSharePct: 100, visibility: null })
    expect(exposure).toBeCloseTo(100 * 1 * 1 * 0.85, 5)
  })

  it('clamps AI share to [0, 100]', () => {
    const over = computeExposure({ revenue: 100, aiSharePct: 500, visibility: 0 })
    const under = computeExposure({ revenue: 100, aiSharePct: -20, visibility: 0 })
    expect(over).toBeCloseTo(100 * 1 * 1 * 0.85, 5)
    expect(under).toBe(0)
  })

  it('returns 0 when visibility is 100 (no mention gap)', () => {
    expect(computeExposure({ revenue: 1_000_000, aiSharePct: 50, visibility: 100 })).toBe(0)
  })
})

describe('getScoreBand', () => {
  it.each([
    [0, 'Invisible'],
    [39, 'Invisible'],
    [40, 'Partially readable'],
    [59, 'Partially readable'],
    [60, 'Readable but not countable'],
    [79, 'Readable but not countable'],
    [80, 'Value visible'],
    [100, 'Value visible'],
  ])('maps score %d to band %s', (score, expectedName) => {
    expect(getScoreBand(score).name).toBe(expectedName)
  })

  it('treats a missing score as Invisible rather than throwing', () => {
    expect(getScoreBand(null).name).toBe('Invisible')
    expect(getScoreBand(undefined).name).toBe('Invisible')
  })

  it('carries a tone for each band, used for the pill color', () => {
    expect(getScoreBand(10).tone).toBe('bad')
    expect(getScoreBand(50).tone).toBe('warn')
    expect(getScoreBand(70).tone).toBe('neutral')
    expect(getScoreBand(90).tone).toBe('good')
  })
})

describe('formatCurrency', () => {
  it('formats and rounds to whole dollars with thousands separators', () => {
    expect(formatCurrency(1234567.89)).toBe('$1,234,568')
  })

  it('treats non-numeric input as zero', () => {
    expect(formatCurrency(undefined)).toBe('$0')
  })
})

describe('getVerdictLine', () => {
  it('prefers an explicit report.verdict over everything else', () => {
    const report = { verdict: 'Custom verdict.', visibility_breakdown: { mention_rate: [] } }
    expect(getVerdictLine(report)).toBe('Custom verdict.')
  })

  it('derives from visibility_breakdown when present (full report)', () => {
    const report = {
      visibility_breakdown: {
        mention_rate: [{ entity: 'Acme Co', is_primary: true, mentioned_queries: 5, total_queries: 12, rate_pct: 41.7 }],
        share_of_mentions: [
          { entity: 'Acme Co', is_primary: true, mentions: 5, share_pct: 40 },
          { entity: 'Rival Co', is_primary: false, mentions: 7, share_pct: 60 },
        ],
      },
    }
    expect(getVerdictLine(report)).toBe('Named in 5 of 12 answers. Rival Co took 60% of all mentions.')
  })

  it('omits the rival clause when there is no rival share data', () => {
    const report = {
      visibility_breakdown: {
        mention_rate: [{ entity: 'Acme Co', is_primary: true, mentioned_queries: 5, total_queries: 12 }],
        share_of_mentions: [{ entity: 'Acme Co', is_primary: true, mentions: 5, share_pct: 100 }],
      },
    }
    expect(getVerdictLine(report)).toBe('Named in 5 of 12 answers.')
  })

  it('falls back to a share-only line from report.overall when visibility_breakdown is absent (pre-gate teaser)', () => {
    const report = {
      overall: [
        { name: 'Acme Co', role: 'primary', som: 40 },
        { name: 'Rival Co', role: 'competitor', som: 60 },
      ],
    }
    expect(getVerdictLine(report)).toBe('Rival Co took 60% of all mentions.')
  })

  it('reads som from the nested metrics shape too (full-report entity shape)', () => {
    const report = {
      overall: [
        { name: 'Acme Co', role: 'primary', metrics: { som: 40 } },
        { name: 'Rival Co', role: 'competitor', metrics: { som: 60 } },
      ],
    }
    expect(getVerdictLine(report)).toBe('Rival Co took 60% of all mentions.')
  })

  it('falls back to the generic band-based verdict when there is no rival data at all', () => {
    const report = { composite: 90, overall: [{ name: 'Acme Co', role: 'primary', som: 40 }] }
    expect(getVerdictLine(report)).toBe('Agents can find, read, and price your store end to end.')
  })

  it('never mentions a funnel stage', () => {
    const reports = [
      { visibility_breakdown: {
        mention_rate: [{ entity: 'Acme Co', is_primary: true, mentioned_queries: 5, total_queries: 12 }],
        share_of_mentions: [{ entity: 'Rival Co', is_primary: false, mentions: 7, share_pct: 70 }],
      } },
      { overall: [{ name: 'Rival Co', role: 'competitor', som: 70 }] },
      { composite: 10 },
    ]
    const stageWords = ['awareness', 'research', 'comparison', 'ready to buy']
    reports.forEach((report) => {
      const line = getVerdictLine(report).toLowerCase()
      stageWords.forEach((w) => expect(line).not.toContain(w))
    })
  })
})

describe('getDominantRivalPayoff', () => {
  it('returns the payoff line when a rival holds >=50% of all mentions', () => {
    const vb = {
      share_of_mentions: [
        { entity: 'Acme Co', is_primary: true, mentions: 4, share_pct: 40 },
        { entity: 'Rival Co', is_primary: false, mentions: 6, share_pct: 60 },
      ],
      totals: { total_mentions: 10, total_queries: 12 },
    }
    expect(getDominantRivalPayoff(vb)).toBe('10 brand mentions across 12 answers. Half went to one rival.')
  })

  it('returns null (no fabricated drama) when no rival reaches 50%', () => {
    const vb = {
      share_of_mentions: [
        { entity: 'Acme Co', is_primary: true, mentions: 6, share_pct: 60 },
        { entity: 'Rival Co', is_primary: false, mentions: 4, share_pct: 40 },
      ],
      totals: { total_mentions: 10, total_queries: 12 },
    }
    expect(getDominantRivalPayoff(vb)).toBeNull()
  })

  it('returns null when visibility_breakdown is absent', () => {
    expect(getDominantRivalPayoff(undefined)).toBeNull()
  })
})
