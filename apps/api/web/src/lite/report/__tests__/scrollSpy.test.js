/**
 * fix/full-analysis-rail-nav: computeActiveSectionId, extracted out of
 * useReportSections.js's own scroll handler unchanged (same ids-in-
 * order scan, same 140px default threshold) so Full Analysis's own
 * scroll-spy (useActiveNavId.js) can reuse the identical mechanism —
 * its own id set, no focus-mode state to carry.
 *
 * jsdom never lays anything out for real (every element's
 * getBoundingClientRect() is {0,0,0,0} unless a test overrides it) —
 * this is what makes the algorithm itself testable in isolation:
 * stub each id's rect directly, no real scrolling required.
 */
import { describe, it, expect, afterEach } from 'vitest'
import { computeActiveSectionId } from '../scrollSpy.js'

function stubRect(id, top) {
  const el = document.createElement('div')
  el.id = id
  el.getBoundingClientRect = () => ({ top })
  document.body.appendChild(el)
  return el
}

afterEach(() => {
  document.body.innerHTML = ''
})

describe('computeActiveSectionId', () => {
  it('picks the LAST id (in list order) whose top has scrolled at or above the threshold', () => {
    stubRect('a', -50) // well past
    stubRect('b', 10) // just past
    stubRect('c', 300) // not yet
    expect(computeActiveSectionId(['a', 'b', 'c'])).toBe('b')
  })

  it('defaults to the first id when nothing has scrolled past the threshold yet', () => {
    stubRect('a', 500)
    stubRect('b', 800)
    expect(computeActiveSectionId(['a', 'b'])).toBe('a')
  })

  it('skips an id with no matching element in the DOM (a conditional section not rendered this run)', () => {
    stubRect('a', -10)
    // 'b' has no element at all — e.g. the transcript nav id when
    // report.transcript is absent this cycle.
    stubRect('c', 5)
    expect(computeActiveSectionId(['a', 'b', 'c'])).toBe('c')
  })

  it('respects a custom offset', () => {
    stubRect('a', 100)
    stubRect('b', 160)
    expect(computeActiveSectionId(['a', 'b'], 150)).toBe('a')
    expect(computeActiveSectionId(['a', 'b'], 200)).toBe('b')
  })

  it('exactly at the threshold counts as scrolled past (<=, not <)', () => {
    stubRect('a', 140)
    expect(computeActiveSectionId(['a'])).toBe('a')
  })
})
