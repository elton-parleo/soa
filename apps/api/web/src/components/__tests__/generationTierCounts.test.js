import { describe, it, expect } from 'vitest'
import {
  tierCounts, tierCountsText, shortfalls,
} from '../generationTierCounts.js'

// C80512's shape: 50 stage questions, 12 brand-direct, 19 + 6 from the
// catalog. The report showed 50.
const C80512 = {
  brand_direct:     { enabled: true, count: 12, requested: 12 },
  catalog_accuracy: { enabled: true, count: 19 },
  value_incentives: { enabled: true, count: 6 },
  category_control: { enabled: false, stage_total: 50 },
}

describe('tierCounts', () => {
  it('counts every tier, not just the stage questions', () => {
    const counts = tierCounts(C80512)
    expect(counts.stage).toBe(50)
    expect(counts.brandDirect).toBe(12)
    expect(counts.fromCatalog).toBe(25)
    expect(counts.total).toBe(87)
  })

  it('says the whole thing in one line', () => {
    expect(tierCountsText(tierCounts(C80512))).toBe(
      '50 stage + 12 brand-direct + 25 from the catalog = 87',
    )
  })

  it('leaves out a tier that was never asked for, rather than printing a zero', () => {
    const counts = tierCounts({
      ...C80512, brand_direct: { enabled: false, count: 0 },
    })
    expect(tierCountsText(counts)).toBe('50 stage + 25 from the catalog = 75')
    expect(counts.total).toBe(75)
  })

  it('does not count a tier that is switched off but still carries a count', () => {
    const counts = tierCounts({
      ...C80512, value_incentives: { enabled: false, count: 6 },
    })
    expect(counts.fromCatalog).toBe(19)
    expect(counts.total).toBe(81)
  })

  it('is null for an ungrounded study, where the stage count is the study', () => {
    expect(tierCounts(null)).toBeNull()
    expect(tierCounts({ category_control: { enabled: false, stage_total: 50 } })).toBeNull()
  })

  it('names each catalog tier separately, since they are different questions', () => {
    expect(tierCounts(C80512).byTier).toEqual([
      { tier: 'catalog_accuracy', count: 19 },
      { tier: 'value_incentives', count: 6 },
    ])
  })
})

describe('shortfalls', () => {
  it('reports a tier that produced less than it asked for', () => {
    expect(shortfalls({
      ...C80512,
      brand_direct: { enabled: true, count: 9, requested: 12, shortfall: 3 },
    })).toEqual([
      { tier: 'brand_direct', short: 3, requested: 12, delivered: 9 },
    ])
  })

  it('reports a tier that could not be built at all', () => {
    expect(shortfalls({
      ...C80512,
      brand_direct: { enabled: true, count: 0, unavailable: 'catalog unreachable' },
    })).toEqual([
      { tier: 'brand_direct', reason: 'catalog unreachable' },
    ])
  })

  it('says nothing about a tier that delivered what it asked for', () => {
    expect(shortfalls(C80512)).toEqual([])
  })

  it('ignores a disabled tier — not asked for is not short', () => {
    expect(shortfalls({
      ...C80512,
      brand_direct: { enabled: false, count: 0, shortfall: 12 },
    })).toEqual([])
  })
})
