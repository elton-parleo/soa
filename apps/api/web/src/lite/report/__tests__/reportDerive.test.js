/**
 * Mobile rail replacement (RM1): buildNavItems was extracted from
 * ReportRail.jsx so the desktop rail and the new phone sections sheet
 * (MobileReportNav.jsx) share one source of per-section score labels —
 * these tests lock in that shared contract directly, independent of
 * either renderer.
 */
import { describe, it, expect } from 'vitest'
import { buildNavItems } from '../reportDerive.js'

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
})
