import { describe, it, expect } from 'vitest'

import { computeTiers } from '../ActionsPage.jsx'

function rec(id, priority_score, suppressed = false) {
  return { id, priority_score, suppressed }
}

describe('computeTiers', () => {
  it('splits 8 recommendations into a clean 25/50/25', () => {
    const recs = [
      rec(1, 10), rec(2, 9), rec(3, 8), rec(4, 7),
      rec(5, 6), rec(6, 5), rec(7, 4), rec(8, 3),
    ]
    const tiers = computeTiers(recs)
    expect([tiers.get(1), tiers.get(2)]).toEqual(['Critical', 'Critical'])
    expect([tiers.get(3), tiers.get(4), tiers.get(5), tiers.get(6)]).toEqual(
      ['High', 'High', 'High', 'High']
    )
    expect([tiers.get(7), tiers.get(8)]).toEqual(['Moderate', 'Moderate'])
  })

  it('excludes suppressed recommendations from ranking and gives them no tier', () => {
    const recs = [rec(1, 10), rec(2, 9, true), rec(3, 1)]
    const tiers = computeTiers(recs)
    expect(tiers.has(2)).toBe(false)
    // With the suppressed one excluded, only 2 remain -> top one Critical.
    expect(tiers.get(1)).toBe('Critical')
    expect(tiers.get(3)).toBe('High')
  })

  it('does not divide by zero when every recommendation is suppressed', () => {
    const recs = [rec(1, 10, true), rec(2, 9, true)]
    expect(() => computeTiers(recs)).not.toThrow()
    expect(computeTiers(recs).size).toBe(0)
  })

  it('handles an empty list', () => {
    expect(computeTiers([]).size).toBe(0)
  })

  it('gives a single non-suppressed recommendation the top tier', () => {
    const tiers = computeTiers([rec(1, 5)])
    expect(tiers.get(1)).toBe('Critical')
  })
})
