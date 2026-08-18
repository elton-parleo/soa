/**
 * shareOfMentionsRank — bug fix regression: a scope of just the primary
 * (no competitors at all, e.g. from the NewCycleFlow launch bug this
 * fixes) must never render "1st of 1" / a fabricated-looking rank.
 */
import { describe, it, expect } from 'vitest'
import { shareOfMentionsRank } from '../fullAnalysisDerive.js'

describe('shareOfMentionsRank', () => {
  it('returns null for an empty competitor set', () => {
    expect(shareOfMentionsRank([])).toBeNull()
    expect(shareOfMentionsRank(null)).toBeNull()
    expect(shareOfMentionsRank(undefined)).toBeNull()
  })

  it('returns null for a scope of just the primary — never "1st of 1"', () => {
    const rows = [{ entity: 'Acme', is_primary: true, share_pct: 100 }]
    expect(shareOfMentionsRank(rows)).toBeNull()
  })

  it('ranks correctly with a real competitor set', () => {
    const rows = [
      { entity: 'Acme', is_primary: true, share_pct: 30 },
      { entity: 'Rival Co', is_primary: false, share_pct: 70 },
    ]
    expect(shareOfMentionsRank(rows)).toBe('2nd of 2')
  })

  it('1st/2nd/3rd/4th suffixes with three or more entities', () => {
    const rows = [
      { entity: 'Acme', is_primary: true, share_pct: 50 },
      { entity: 'A', is_primary: false, share_pct: 30 },
      { entity: 'B', is_primary: false, share_pct: 20 },
    ]
    expect(shareOfMentionsRank(rows)).toBe('1st of 3')
  })
})
