/**
 * section_expanded fires from two shared primitives (see each file's
 * own "Analytics session" doc comment): useCollapsible (Collapsible.jsx,
 * local expanders) and SectionCollapseButton.jsx (top-level sections).
 * Both only on the closed→open transition.
 */
import React from 'react'
import { renderHook, act } from '@testing-library/react'
import { render, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import { useCollapsible } from '../Collapsible.jsx'
import { SectionCollapseButton } from '../SectionCollapseButton.jsx'
import { track } from '../../analytics.js'
import { EVENTS } from '../../analyticsEvents.js'

vi.mock('../../analytics.js', () => ({
  track: vi.fn(),
}))

beforeEach(() => {
  track.mockClear()
})

describe('useCollapsible — section_expanded', () => {
  it('fires section_expanded with {section, control} on the closed→open transition', () => {
    const { result } = renderHook(() => useCollapsible(false, { section: 'tv', control: 'price_truth' }))
    act(() => result.current[1]())
    expect(track).toHaveBeenCalledWith(EVENTS.SECTION_EXPANDED, { section: 'tv', control: 'price_truth' })
  })

  it('does not fire on the open→closed transition', () => {
    const { result } = renderHook(() => useCollapsible(false, { section: 'tv', control: 'price_truth' }))
    act(() => result.current[1]()) // open
    track.mockClear()
    act(() => result.current[1]()) // close
    expect(track).not.toHaveBeenCalled()
  })

  it('never throws and never tracks when no trackingId is passed', () => {
    const { result } = renderHook(() => useCollapsible(false))
    expect(() => act(() => result.current[1]())).not.toThrow()
    expect(track).not.toHaveBeenCalled()
  })
})

describe('SectionCollapseButton — section_expanded', () => {
  it('fires section_expanded with {section, control: "section"} on open', () => {
    const onClick = vi.fn()
    const { getByRole } = render(<SectionCollapseButton open={false} onClick={onClick} section="viz" />)
    fireEvent.click(getByRole('button'))
    expect(track).toHaveBeenCalledWith(EVENTS.SECTION_EXPANDED, { section: 'viz', control: 'section' })
    expect(onClick).toHaveBeenCalled()
  })

  it('does not fire when already open (a click there is a collapse)', () => {
    const onClick = vi.fn()
    const { getByRole } = render(<SectionCollapseButton open onClick={onClick} section="viz" />)
    fireEvent.click(getByRole('button'))
    expect(track).not.toHaveBeenCalled()
    expect(onClick).toHaveBeenCalled()
  })

  it('never throws and never tracks when no section id is passed', () => {
    const onClick = vi.fn()
    const { getByRole } = render(<SectionCollapseButton open={false} onClick={onClick} />)
    expect(() => fireEvent.click(getByRole('button'))).not.toThrow()
    expect(track).not.toHaveBeenCalled()
  })
})
