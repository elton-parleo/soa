/**
 * TranscriptSection — renders per narrative_case, hidden when
 * report.transcript is null, the "Show the full answer" expander
 * toggles and fires transcript_answer_expanded (not section_expanded),
 * and highlight spans paint as a brand mark / dotted-underline claim.
 */
import React from 'react'
import { render, fireEvent, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import { TranscriptSection } from '../TranscriptSection.jsx'
import { track } from '../../analytics.js'
import { EVENTS } from '../../analyticsEvents.js'

vi.mock('../../analytics.js', () => ({
  track: vi.fn(),
}))

beforeEach(() => {
  track.mockClear()
})

function _transcript(overrides = {}) {
  return {
    run_id: 701,
    platform: 'chatgpt',
    query_text: 'Best designer handbags under $500?',
    stage: 'Ready to Buy',
    persona: 'Value-Conscious',
    query_index: 14,
    total_queries: 24,
    asked_at: '2026-08-07T00:00:00',
    response_text: 'Acme Co is a strong pick — it runs about $275 at Zappos. Coach is also worth a look.',
    preview_cutoff: 40,
    spans: [
      { start: 0, end: 7, kind: 'brand' },
      { start: 32, end: 45, kind: 'value_claim' },
    ],
    narrative_case: 'value_gap',
    selection_tier: 1,
    right: "You're named first, unprompted.",
    leaked: 'Your price came from Zappos, not your site.',
    ...overrides,
  }
}

describe('TranscriptSection — visibility', () => {
  it('renders nothing when report.transcript is null', () => {
    const { container } = render(<TranscriptSection report={{ transcript: null }} open onToggle={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders the section, chat bubbles, and duo boxes when transcript is present', () => {
    render(<TranscriptSection report={{ transcript: _transcript() }} open onToggle={() => {}} />)
    expect(screen.getByText('Best designer handbags under $500?')).toBeInTheDocument()
    expect(screen.getByText(/WHAT WENT RIGHT/)).toBeInTheDocument()
    expect(screen.getByText(/WHAT LEAKED/)).toBeInTheDocument()
    expect(screen.getByText("You're named first, unprompted.")).toBeInTheDocument()
    expect(screen.getByText('Your price came from Zappos, not your site.')).toBeInTheDocument()
  })

  it('collapses to nothing when the outer section is closed (open=false)', () => {
    render(<TranscriptSection report={{ transcript: _transcript() }} open={false} onToggle={() => {}} />)
    expect(screen.queryByText('Best designer handbags under $500?')).not.toBeInTheDocument()
  })
})

describe('TranscriptSection — narrative_case phrasing', () => {
  it.each([
    ['value_gap', 'value gap shows most clearly'],
    ["mentioned_no_leak", "where you're named"],
    ['not_mentioned', 'left out'],
    ['uncoded', 'recorded answer'],
  ])('renders case-appropriate intro copy for narrative_case=%s', (narrativeCase, expectedFragment) => {
    const { container } = render(<TranscriptSection report={{ transcript: _transcript({ narrative_case: narrativeCase }) }} open onToggle={() => {}} />)
    const intro = container.querySelector('p')
    expect(intro.textContent).toMatch(new RegExp(expectedFragment, 'i'))
  })
})

describe('TranscriptSection — full-answer expander', () => {
  it('shows only the collapsed preview by default, with a "Show the full answer" button', () => {
    render(<TranscriptSection report={{ transcript: _transcript() }} open onToggle={() => {}} />)
    expect(screen.getByText('Show the full answer')).toBeInTheDocument()
    expect(screen.queryByText(/Coach is also worth a look/)).not.toBeInTheDocument()
  })

  it('reveals the full answer and flips the button label on click', () => {
    render(<TranscriptSection report={{ transcript: _transcript() }} open onToggle={() => {}} />)
    fireEvent.click(screen.getByText('Show the full answer'))
    expect(screen.getByText(/Coach is also worth a look/)).toBeInTheDocument()
    expect(screen.getByText('Hide the full answer')).toBeInTheDocument()
  })

  it('fires transcript_answer_expanded (not section_expanded) on open, never on close', () => {
    render(<TranscriptSection report={{ transcript: _transcript() }} open onToggle={() => {}} />)
    fireEvent.click(screen.getByText('Show the full answer'))
    expect(track).toHaveBeenCalledWith(EVENTS.TRANSCRIPT_ANSWER_EXPANDED, {})
    expect(track).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByText('Hide the full answer'))
    expect(track).toHaveBeenCalledTimes(1) // still just the one open-transition call
  })

  it('omits the expander entirely when the full response already fits the preview', () => {
    const transcript = _transcript({ response_text: 'Short answer.', preview_cutoff: 13 })
    render(<TranscriptSection report={{ transcript }} open onToggle={() => {}} />)
    expect(screen.queryByText('Show the full answer')).not.toBeInTheDocument()
  })
})

describe('TranscriptSection — span highlighting', () => {
  it('paints a brand span as a <mark> and a value-claim span as a dotted underline', () => {
    const { container } = render(<TranscriptSection report={{ transcript: _transcript() }} open onToggle={() => {}} />)
    const mark = container.querySelector('mark')
    expect(mark).toBeInTheDocument()
    expect(mark.textContent).toBe('Acme Co')

    fireEvent.click(screen.getByText('Show the full answer'))
    const underlined = Array.from(container.querySelectorAll('span')).find(
      (el) => el.style.borderBottom && el.style.borderBottom.includes('dotted'),
    )
    expect(underlined).toBeTruthy()
  })

  it('never renders a highlight for a span past the collapsed preview cutoff', () => {
    const { container } = render(<TranscriptSection report={{ transcript: _transcript() }} open onToggle={() => {}} />)
    // The value_claim span (32-45) starts before preview_cutoff (40), so
    // it should NOT render as a dotted underline until expanded (its end
    // is clipped to the cutoff, so it's still a plain highlighted span
    // rather than being invented past what's shown).
    const underlined = Array.from(container.querySelectorAll('span')).find(
      (el) => el.style.borderBottom && el.style.borderBottom.includes('dotted'),
    )
    // Collapsed: only 40 chars visible, so the claim span (32-45) is
    // clipped to (32-40) — still rendered, just shorter than full.
    expect(underlined).toBeTruthy()
    expect(underlined.textContent.length).toBeLessThanOrEqual(8)
  })
})
