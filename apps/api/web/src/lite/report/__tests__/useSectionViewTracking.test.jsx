/**
 * useSectionViewTracking — jsdom's global IntersectionObserver stub
 * (src/test-setup.js) stores its callback but never invokes it, so
 * this file installs its own controllable mock (manually fired via
 * `.callback([...])`) scoped to each test, restored afterward.
 */
import React from 'react'
import { render } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import { useSectionViewTracking } from '../useSectionViewTracking.js'
import { track } from '../../analytics.js'
import { EVENTS } from '../../analyticsEvents.js'

vi.mock('../../analytics.js', () => ({
  track: vi.fn(),
}))

class TestIntersectionObserver {
  constructor(callback, options) {
    this.callback = callback
    this.options = options
    TestIntersectionObserver.instances.push(this)
  }
  observe(el) { this.element = el }
  unobserve() {}
  disconnect() {}
}
TestIntersectionObserver.instances = []

function fire(id, entry) {
  const instance = TestIntersectionObserver.instances.find((o) => o.element?.id === id)
  instance.callback([{ isIntersecting: true, intersectionRatio: 1, ...entry }])
}

function TestComp({ ids, renderedIds = ids }) {
  useSectionViewTracking(ids)
  return <>{renderedIds.map((id) => <div id={id} key={id} />)}</>
}

beforeEach(() => {
  TestIntersectionObserver.instances = []
  vi.stubGlobal('IntersectionObserver', TestIntersectionObserver)
  vi.useFakeTimers()
  track.mockClear()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('useSectionViewTracking', () => {
  it('fires section_viewed once a section is ≥50% visible for 1s', () => {
    render(<TestComp ids={['viz']} />)
    fire('viz', { isIntersecting: true, intersectionRatio: 0.6 })
    vi.advanceTimersByTime(1000)
    expect(track).toHaveBeenCalledWith(EVENTS.SECTION_VIEWED, { section: 'viz' })
  })

  it('does not fire before the 1s dwell completes', () => {
    render(<TestComp ids={['viz']} />)
    fire('viz', { isIntersecting: true, intersectionRatio: 0.6 })
    vi.advanceTimersByTime(600)
    expect(track).not.toHaveBeenCalled()
  })

  it('cancels the dwell timer if the section leaves view before 1s, and never fires', () => {
    render(<TestComp ids={['viz']} />)
    fire('viz', { isIntersecting: true, intersectionRatio: 0.6 })
    vi.advanceTimersByTime(500)
    fire('viz', { isIntersecting: false, intersectionRatio: 0 })
    vi.advanceTimersByTime(600)
    expect(track).not.toHaveBeenCalled()
  })

  it('fires at most once per section even if it re-enters view after being seen', () => {
    render(<TestComp ids={['viz']} />)
    fire('viz', { isIntersecting: true, intersectionRatio: 0.6 })
    vi.advanceTimersByTime(1000)
    expect(track).toHaveBeenCalledTimes(1)

    fire('viz', { isIntersecting: false, intersectionRatio: 0 })
    fire('viz', { isIntersecting: true, intersectionRatio: 0.6 })
    vi.advanceTimersByTime(1000)
    expect(track).toHaveBeenCalledTimes(1)
  })

  it('tracks each id in the list independently', () => {
    render(<TestComp ids={['viz', 'tv']} />)
    fire('viz', { isIntersecting: true, intersectionRatio: 0.6 })
    vi.advanceTimersByTime(1000)
    expect(track).toHaveBeenCalledWith(EVENTS.SECTION_VIEWED, { section: 'viz' })
    expect(track).not.toHaveBeenCalledWith(EVENTS.SECTION_VIEWED, { section: 'tv' })

    fire('tv', { isIntersecting: true, intersectionRatio: 0.6 })
    vi.advanceTimersByTime(1000)
    expect(track).toHaveBeenCalledWith(EVENTS.SECTION_VIEWED, { section: 'tv' })
  })

  it('skips ids with no matching DOM element without throwing', () => {
    expect(() => render(<TestComp ids={['viz', 'does-not-exist']} renderedIds={['viz']} />)).not.toThrow()
    expect(TestIntersectionObserver.instances).toHaveLength(1)
  })
})
