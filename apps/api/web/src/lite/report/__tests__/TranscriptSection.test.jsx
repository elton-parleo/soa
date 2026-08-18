/**
 * TranscriptSection — renders per narrative_case, hidden when
 * report.transcript is null, the "Show the full answer" expander
 * toggles and fires transcript_answer_expanded (not section_expanded),
 * and highlight spans paint as a brand mark / dotted-underline claim.
 */
import React from 'react'
import { render, fireEvent, screen, waitFor } from '@testing-library/react'
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

describe('TranscriptSection — narrative boxes gated by payload presence (TRANSCRIPT_NARRATIVE_ENABLED)', () => {
  it('renders the transcript without the duo boxes when right/leaked are absent from the payload', () => {
    const transcript = _transcript()
    delete transcript.right
    delete transcript.leaked
    const { container } = render(<TranscriptSection report={{ transcript }} open onToggle={() => {}} />)

    // The section itself, the question, and the answer still render —
    // only the flagged boxes are gone.
    expect(screen.getByText('Best designer handbags under $500?')).toBeInTheDocument()
    expect(screen.queryByText(/WHAT WENT RIGHT/)).not.toBeInTheDocument()
    expect(screen.queryByText(/WHAT LEAKED/)).not.toBeInTheDocument()
    expect(container.querySelector('[style*="grid-template-columns"]')).not.toBeInTheDocument()
  })

  it('still shows the provenance line (query index/date) with the boxes absent', () => {
    const transcript = _transcript()
    delete transcript.right
    delete transcript.leaked
    render(<TranscriptSection report={{ transcript }} open onToggle={() => {}} />)
    expect(screen.getByText(/Query 14 of 24/)).toBeInTheDocument()
  })

  it('renders the duo boxes when right/leaked are both present', () => {
    render(<TranscriptSection report={{ transcript: _transcript() }} open onToggle={() => {}} />)
    expect(screen.getByText(/WHAT WENT RIGHT/)).toBeInTheDocument()
    expect(screen.getByText(/WHAT LEAKED/)).toBeInTheDocument()
  })

  it('treats an explicit null the same as an absent key (no boxes)', () => {
    const transcript = _transcript({ right: null, leaked: null })
    render(<TranscriptSection report={{ transcript }} open onToggle={() => {}} />)
    expect(screen.queryByText(/WHAT WENT RIGHT/)).not.toBeInTheDocument()
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

  it('paints a stale_price span with the same dotted style but a distinct hover label from value_claim', () => {
    const transcript = _transcript({
      response_text: 'Acme Co lists it at $110 on their own site.',
      preview_cutoff: 45,
      spans: [
        { start: 0, end: 7, kind: 'brand' },
        { start: 20, end: 24, kind: 'stale_price' },
      ],
    })
    const { container } = render(<TranscriptSection report={{ transcript }} open onToggle={() => {}} />)
    const stale = Array.from(container.querySelectorAll('span')).find((el) => el.title === 'your price, quoted stale')
    expect(stale).toBeTruthy()
    expect(stale.style.borderBottom).toContain('dotted')
    expect(stale.textContent).toBe('$110')
  })

  it('never underlines the primary brand name as an off-site value_claim span', () => {
    const transcript = _transcript({
      response_text: 'Acme Co lists it at $110 on their own site.',
      preview_cutoff: 45,
      spans: [{ start: 0, end: 7, kind: 'brand' }],
    })
    const { container } = render(<TranscriptSection report={{ transcript }} open onToggle={() => {}} />)
    expect(container.querySelectorAll('mark')).toHaveLength(1)
    expect(container.querySelector('mark').textContent).toBe('Acme Co')
    const dotted = Array.from(container.querySelectorAll('span')).filter(
      (el) => el.style.borderBottom && el.style.borderBottom.includes('dotted'),
    )
    expect(dotted).toHaveLength(0)
  })
})

describe('TranscriptSection — provenance legend (DTC fix)', () => {
  it('shows the off-site legend only when a value_claim span is present', () => {
    render(<TranscriptSection report={{ transcript: _transcript() }} open onToggle={() => {}} />)
    expect(screen.getByText(/sourced outside your markup/)).toBeInTheDocument()
  })

  it('shows the stale-price legend when only a stale_price span is present', () => {
    const transcript = _transcript({
      spans: [{ start: 0, end: 7, kind: 'brand' }, { start: 32, end: 36, kind: 'stale_price' }],
    })
    render(<TranscriptSection report={{ transcript }} open onToggle={() => {}} />)
    expect(screen.getByText(/your own price, quoted stale/)).toBeInTheDocument()
    expect(screen.queryByText(/sourced outside your markup/)).not.toBeInTheDocument()
  })

  it('omits the dotted-underline legend entirely when no third-party or stale-price span exists', () => {
    const transcript = _transcript({
      spans: [{ start: 0, end: 7, kind: 'brand' }],
      leaked: 'Nothing leaked in this run.',
    })
    render(<TranscriptSection report={{ transcript }} open onToggle={() => {}} />)
    expect(screen.queryByText(/Dotted underline/)).not.toBeInTheDocument()
    expect(screen.getByText(/Query 14 of 24/)).toBeInTheDocument()
  })
})

describe('TranscriptSection — Price Truth link', () => {
  it('links the "Price Truth" phrase in LEAKED copy to the True Value pillar section', () => {
    const transcript = _transcript({
      leaked: 'The agent quoted your price as $110.00 — your net right now is $93.50. This is the Price Truth gap measured across all 24 answers.',
    })
    render(<TranscriptSection report={{ transcript }} open onToggle={() => {}} />)
    const link = screen.getByRole('link', { name: 'Price Truth' })
    expect(link).toHaveAttribute('href', '#tv')
  })

  it('renders LEAKED copy with no "Price Truth" mention as plain text, no stray link', () => {
    const transcript = _transcript({ leaked: "Nothing leaked in this run — it's a clean mention." })
    render(<TranscriptSection report={{ transcript }} open onToggle={() => {}} />)
    expect(screen.queryByRole('link', { name: 'Price Truth' })).not.toBeInTheDocument()
    expect(screen.getByText(/clean mention/)).toBeInTheDocument()
  })
})

// ─── Transcript browsing (2b/2c/2d) — all opt-in via `browsable` +
// `fetchIndex`/`fetchDetail`. Every test above this point mounts the
// component with NEITHER prop, and all still pass unchanged — proving
// lite's own call sites (which never pass them) render byte-for-byte
// as before.
function _indexPage(overrides = {}) {
  return {
    // Pre-sorted by index ascending, as list_transcript_index's own
    // `rows.sort(key=lambda r: r["index"])` guarantees server-side —
    // the frontend trusts that order rather than re-sorting.
    queries: [
      { query_id: 2, index: 14, total_queries: 24, query_text: 'Best designer handbags under $500?', stage: 'Ready to Buy', persona: 'Value-Conscious', narrative_case: 'value_gap', runs: [{ run_id: 701, platform: 'chatgpt', run_number: 1 }, { run_id: 702, platform: 'claude', run_number: 1 }] },
      { query_id: 3, index: 15, total_queries: 24, query_text: 'Where can I find affordable totes?', stage: 'Research', persona: 'Value-Conscious', narrative_case: 'mentioned_no_leak', runs: [{ run_id: 703, platform: 'chatgpt', run_number: 1 }] },
      { query_id: 1, index: 16, total_queries: 24, query_text: 'Do any brands sell licensed replicas?', stage: 'Research', persona: 'Value-Conscious', narrative_case: 'not_mentioned', runs: [{ run_id: 700, platform: 'chatgpt', run_number: 1 }] },
    ],
    page: 1, page_size: 25, total_queries: 3, curated_run_id: 701,
    ...overrides,
  }
}

const RUNS_BY_ID = {
  700: _transcript({ run_id: 700, query_index: 16, query_text: 'Do any brands sell licensed replicas?', narrative_case: 'not_mentioned' }),
  701: _transcript({ run_id: 701 }), // the curated pick, query_index 14
  702: _transcript({ run_id: 702, platform: 'claude', query_index: 14 }),
  703: _transcript({ run_id: 703, query_index: 15, query_text: 'Where can I find affordable totes?', narrative_case: 'mentioned_no_leak' }),
}

function _fetchDetail() {
  return vi.fn((runId) => Promise.resolve(RUNS_BY_ID[runId]))
}

describe('TranscriptSection — browsable=false (default)', () => {
  it('never renders the nav bar even when fetchIndex/fetchDetail are passed, if browsable is omitted', () => {
    render(
      <TranscriptSection
        report={{ transcript: _transcript() }} open onToggle={() => {}}
        fetchIndex={vi.fn()} fetchDetail={_fetchDetail()}
      />,
    )
    expect(screen.queryByText('Browse all queries')).not.toBeInTheDocument()
    expect(screen.queryByText("PARLEO'S PICK")).not.toBeInTheDocument()
  })
})

describe('TranscriptSection — browsable nav bar', () => {
  it('shows the curated-pick badge and a disabled prev arrow on the initial (curated) transcript', async () => {
    const fetchIndex = vi.fn(() => Promise.resolve(_indexPage()))
    render(
      <TranscriptSection
        report={{ transcript: _transcript() }} open onToggle={() => {}}
        browsable fetchIndex={fetchIndex} fetchDetail={_fetchDetail()}
      />,
    )
    expect(await screen.findByText("PARLEO'S PICK")).toBeInTheDocument()
    // The badge itself is independent of the (async) index fetch, but
    // prev/next enablement isn't computed until the index has loaded —
    // wait on Next (which SHOULD end up enabled) rather than racing the
    // still-in-flight fetchIndex call.
    await waitFor(() => expect(screen.getByLabelText('Next query')).not.toBeDisabled())
    expect(screen.getByLabelText('Previous query')).toBeDisabled()
  })

  it('advances to the next query on Next click, fetching its default (curated-platform-or-first) run', async () => {
    const fetchIndex = vi.fn(() => Promise.resolve(_indexPage()))
    const fetchDetail = _fetchDetail()
    render(
      <TranscriptSection
        report={{ transcript: _transcript() }} open onToggle={() => {}}
        browsable fetchIndex={fetchIndex} fetchDetail={fetchDetail}
      />,
    )
    await screen.findByText("PARLEO'S PICK")
    fireEvent.click(screen.getByLabelText('Next query'))
    await waitFor(() => expect(fetchDetail).toHaveBeenCalledWith(703))
    expect(await screen.findByText('Where can I find affordable totes?')).toBeInTheDocument()
    expect(screen.getByText('← Back to pick')).toBeInTheDocument()
  })

  it('walks back to the prior query via the Previous arrow, fetching its run just like Next', async () => {
    const fetchIndex = vi.fn(() => Promise.resolve(_indexPage()))
    const fetchDetail = _fetchDetail()
    render(
      <TranscriptSection
        report={{ transcript: _transcript() }} open onToggle={() => {}}
        browsable fetchIndex={fetchIndex} fetchDetail={fetchDetail}
      />,
    )
    await screen.findByText("PARLEO'S PICK")
    fireEvent.click(screen.getByLabelText('Next query'))
    await screen.findByText('Where can I find affordable totes?')
    fireEvent.click(screen.getByLabelText('Previous query'))
    await screen.findByText('Best designer handbags under $500?')
    expect(fetchDetail).toHaveBeenNthCalledWith(1, 703)
    expect(fetchDetail).toHaveBeenNthCalledWith(2, 701)
  })

  it('"Back to pick" restores the original curated transcript with no fetch at all', async () => {
    const fetchIndex = vi.fn(() => Promise.resolve(_indexPage()))
    const fetchDetail = _fetchDetail()
    render(
      <TranscriptSection
        report={{ transcript: _transcript() }} open onToggle={() => {}}
        browsable fetchIndex={fetchIndex} fetchDetail={fetchDetail}
      />,
    )
    await screen.findByText("PARLEO'S PICK")
    fireEvent.click(screen.getByLabelText('Next query'))
    await screen.findByText('Where can I find affordable totes?')
    fetchDetail.mockClear()
    fireEvent.click(screen.getByText('← Back to pick'))
    await screen.findByText("PARLEO'S PICK")
    expect(screen.getByText('Best designer handbags under $500?')).toBeInTheDocument()
    expect(fetchDetail).not.toHaveBeenCalled()
  })

  it('fires transcript_navigated with direction on Next, and with picker on Back to pick', async () => {
    const fetchIndex = vi.fn(() => Promise.resolve(_indexPage()))
    const fetchDetail = _fetchDetail()
    render(
      <TranscriptSection
        report={{ transcript: _transcript() }} open onToggle={() => {}}
        browsable fetchIndex={fetchIndex} fetchDetail={fetchDetail}
      />,
    )
    await screen.findByText("PARLEO'S PICK")
    track.mockClear()
    fireEvent.click(screen.getByLabelText('Next query'))
    await screen.findByText('Where can I find affordable totes?')
    expect(track).toHaveBeenCalledWith(EVENTS.TRANSCRIPT_NAVIGATED, expect.objectContaining({ direction: 'next', platform: 'chatgpt', narrative_case: 'mentioned_no_leak' }))

    fireEvent.click(screen.getByText('← Back to pick'))
    await screen.findByText("PARLEO'S PICK")
    expect(track).toHaveBeenCalledWith(EVENTS.TRANSCRIPT_NAVIGATED, expect.objectContaining({ picker: true, platform: 'chatgpt', narrative_case: 'value_gap' }))
  })

  it('supports ArrowRight/ArrowLeft keyboard navigation once the index has loaded', async () => {
    const fetchIndex = vi.fn(() => Promise.resolve(_indexPage()))
    const fetchDetail = _fetchDetail()
    render(
      <TranscriptSection
        report={{ transcript: _transcript() }} open onToggle={() => {}}
        browsable fetchIndex={fetchIndex} fetchDetail={fetchDetail}
      />,
    )
    await screen.findByText("PARLEO'S PICK")
    fireEvent.keyDown(document, { key: 'ArrowRight' })
    await screen.findByText('Where can I find affordable totes?')
    fireEvent.keyDown(document, { key: 'ArrowLeft' })
    await screen.findByText('Best designer handbags under $500?')
  })

  it('never navigates on arrow keys typed into an input (e.g. the query-picker filter)', async () => {
    const fetchIndex = vi.fn(() => Promise.resolve(_indexPage()))
    const fetchDetail = _fetchDetail()
    render(
      <TranscriptSection
        report={{ transcript: _transcript() }} open onToggle={() => {}}
        browsable fetchIndex={fetchIndex} fetchDetail={fetchDetail}
      />,
    )
    await screen.findByText("PARLEO'S PICK")
    fireEvent.click(screen.getByText('Browse all queries'))
    const filterInput = await screen.findByLabelText('Filter queries')
    fireEvent.keyDown(filterInput, { key: 'ArrowRight' })
    expect(screen.getByText("PARLEO'S PICK")).toBeInTheDocument() // unchanged, no navigation happened
  })
})

describe('TranscriptSection — query picker', () => {
  it('opens the picker on "Browse all queries", loading the full index via fetchIndex', async () => {
    const fetchIndex = vi.fn(() => Promise.resolve(_indexPage()))
    render(
      <TranscriptSection
        report={{ transcript: _transcript() }} open onToggle={() => {}}
        browsable fetchIndex={fetchIndex} fetchDetail={_fetchDetail()}
      />,
    )
    await screen.findByText("PARLEO'S PICK")
    fireEvent.click(screen.getByText('Browse all queries'))
    expect(await screen.findByText('Do any brands sell licensed replicas?')).toBeInTheDocument()
    expect(screen.getByText('Where can I find affordable totes?')).toBeInTheDocument()
  })

  it('jumps to the selected query on click and fires transcript_navigated with picker: true', async () => {
    const fetchIndex = vi.fn(() => Promise.resolve(_indexPage()))
    const fetchDetail = _fetchDetail()
    render(
      <TranscriptSection
        report={{ transcript: _transcript() }} open onToggle={() => {}}
        browsable fetchIndex={fetchIndex} fetchDetail={fetchDetail}
      />,
    )
    await screen.findByText("PARLEO'S PICK")
    fireEvent.click(screen.getByText('Browse all queries'))
    track.mockClear()
    fireEvent.click(await screen.findByText('Do any brands sell licensed replicas?'))
    await waitFor(() => expect(fetchDetail).toHaveBeenCalledWith(700))
    expect(track).toHaveBeenCalledWith(EVENTS.TRANSCRIPT_NAVIGATED, expect.objectContaining({ picker: true, position: '16/24' }))
  })

  it('filters the query list by typed text', async () => {
    const fetchIndex = vi.fn(() => Promise.resolve(_indexPage()))
    render(
      <TranscriptSection
        report={{ transcript: _transcript() }} open onToggle={() => {}}
        browsable fetchIndex={fetchIndex} fetchDetail={_fetchDetail()}
      />,
    )
    await screen.findByText("PARLEO'S PICK")
    fireEvent.click(screen.getByText('Browse all queries'))
    const filterInput = await screen.findByLabelText('Filter queries')
    fireEvent.change(filterInput, { target: { value: 'totes' } })
    expect(screen.getByText('Where can I find affordable totes?')).toBeInTheDocument()
    expect(screen.queryByText('Do any brands sell licensed replicas?')).not.toBeInTheDocument()
  })
})

describe('TranscriptSection — platform/run selector', () => {
  it('renders no run selector for a single-run query', async () => {
    const fetchIndex = vi.fn(() => Promise.resolve(_indexPage()))
    render(
      <TranscriptSection
        report={{ transcript: _transcript() }} open onToggle={() => {}}
        browsable fetchIndex={fetchIndex} fetchDetail={_fetchDetail()}
      />,
    )
    await screen.findByText("PARLEO'S PICK")
    // Query 14 (the curated pick) has TWO runs in _indexPage — switch to
    // query 15's single-run row via Next to see the no-selector case.
    fireEvent.click(screen.getByLabelText('Next query'))
    await screen.findByText('Where can I find affordable totes?')
    expect(screen.queryByText(/run 1/)).not.toBeInTheDocument()
  })

  it('renders a run pill per platform/run for a multi-run query, and switches on click', async () => {
    const fetchIndex = vi.fn(() => Promise.resolve(_indexPage()))
    const fetchDetail = _fetchDetail()
    render(
      <TranscriptSection
        report={{ transcript: _transcript() }} open onToggle={() => {}}
        browsable fetchIndex={fetchIndex} fetchDetail={fetchDetail}
      />,
    )
    await screen.findByText("PARLEO'S PICK") // query 14 (run 701) has a sibling run 702 (claude)
    const claudePill = await screen.findByText(/claude · run 1/)
    fireEvent.click(claudePill)
    await waitFor(() => expect(fetchDetail).toHaveBeenCalledWith(702))
  })
})
