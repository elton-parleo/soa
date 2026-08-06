import { describe, it, expect } from 'vitest'
import { buildSoaIndexRows, PROJECTED_SHARE_UPLIFT_PCT, SOA_INDEX_PROJECTED_LABEL } from '../soaIndexDerive.js'

const SHARE_OF_MENTIONS = [
  { entity: 'Allbirds', is_primary: true, mentions: 10, share_pct: 25 },
  { entity: 'Nike', is_primary: false, mentions: 15, share_pct: 37.5 },
  { entity: 'On', is_primary: false, mentions: 15, share_pct: 37.5 },
]

describe('buildSoaIndexRows', () => {
  it('carries {name, share} for every entity', () => {
    const { rows } = buildSoaIndexRows(SHARE_OF_MENTIONS)
    expect(rows).toEqual([
      { name: 'Allbirds', share: 25, projected: 42 },
      { name: 'Nike', share: 37.5 },
      { name: 'On', share: 37.5 },
    ])
  })

  it('sets projected only on the primary row, as share + PROJECTED_SHARE_UPLIFT_PCT', () => {
    const { rows } = buildSoaIndexRows(SHARE_OF_MENTIONS)
    const you = rows.find((r) => r.name === 'Allbirds')
    expect(you.projected).toBe(Math.round(25 + PROJECTED_SHARE_UPLIFT_PCT))
    expect(rows.find((r) => r.name === 'Nike').projected).toBeUndefined()
  })

  it('caps the projected bar at 100', () => {
    const shares = [{ entity: 'Allbirds', is_primary: true, mentions: 90, share_pct: 90 }]
    const { rows } = buildSoaIndexRows(shares)
    expect(rows[0].projected).toBe(100)
  })

  it('returns the primary entity name as `you`', () => {
    const { you } = buildSoaIndexRows(SHARE_OF_MENTIONS)
    expect(you).toBe('Allbirds')
  })

  it('always pairs the illustrative label with a real projected bar', () => {
    const { projectedLabel } = buildSoaIndexRows(SHARE_OF_MENTIONS)
    expect(projectedLabel).toBe(SOA_INDEX_PROJECTED_LABEL)
    expect(projectedLabel).toMatch(/ILLUSTRATIVE/)
    expect(projectedLabel).toMatch(new RegExp(`\\+${PROJECTED_SHARE_UPLIFT_PCT} POINTS`))
  })

  // H1: no fabricated projection when the primary's own share isn't
  // measurable — SoAIndex must render no projected bar at all.
  it('omits the projected bar and label when the primary has no measurable share', () => {
    const shares = [
      { entity: 'Allbirds', is_primary: true, mentions: 0, share_pct: null },
      { entity: 'Nike', is_primary: false, mentions: 5, share_pct: 100 },
    ]
    const { rows, projectedLabel } = buildSoaIndexRows(shares)
    expect(rows.find((r) => r.name === 'Allbirds').projected).toBeUndefined()
    expect(projectedLabel).toBeNull()
  })

  it('omits the projected bar when there is no primary entity at all', () => {
    const shares = [{ entity: 'Nike', is_primary: false, mentions: 5, share_pct: 100 }]
    const { rows, you, projectedLabel } = buildSoaIndexRows(shares)
    expect(rows.every((r) => r.projected === undefined)).toBe(true)
    expect(you).toBeNull()
    expect(projectedLabel).toBeNull()
  })

  it('handles an empty list without throwing', () => {
    expect(buildSoaIndexRows([])).toEqual({ rows: [], you: null, projectedLabel: null })
    expect(buildSoaIndexRows(undefined)).toEqual({ rows: [], you: null, projectedLabel: null })
  })
})
