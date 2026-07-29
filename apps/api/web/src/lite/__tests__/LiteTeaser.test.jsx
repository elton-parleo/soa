import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import { LiteTeaser } from '../LiteTeaser.jsx'
import { liteApi } from '../liteApi.js'

vi.mock('../liteApi.js', () => ({
  liteApi: { setEmail: vi.fn() },
}))

beforeEach(() => {
  vi.clearAllMocks()
})

const baseTeaser = {
  status: 'complete',
  locked: true,
  overall: [
    { name: 'Acme Co', role: 'primary', som: 62.5 },
    { name: 'Rival Co', role: 'competitor', som: 37.5 },
  ],
  visibility: 62.5,
  accessibility: null,
  composite: 62.5,
  scan_status: null,
}

describe('LiteTeaser — email gate flow, unchanged behavior', () => {
  it('renders rival share of mentions per entity with role labeling', () => {
    render(<LiteTeaser report={baseTeaser} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.getByText('Acme Co (you)')).toBeInTheDocument()
    expect(screen.getByText('Rival Co')).toBeInTheDocument()
    expect(screen.getByText('62.5%')).toBeInTheDocument()
  })

  it('shows the unlock prompt gating the full report', () => {
    render(<LiteTeaser report={baseTeaser} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.getByText('Want the full report?')).toBeInTheDocument()
  })

  it('rejects an invalid email without calling the API', async () => {
    render(<LiteTeaser report={baseTeaser} token="tok-1" onUnlocked={() => {}} />)
    fireEvent.change(screen.getByPlaceholderText('you@company.com'), { target: { value: 'not-an-email' } })
    fireEvent.click(screen.getByText('Unlock the full report'))

    await waitFor(() => expect(screen.getByText(/valid email/)).toBeInTheDocument())
    expect(liteApi.setEmail).not.toHaveBeenCalled()
  })

  it('unlocks and hands the full report back to the caller on valid email', async () => {
    const fullReport = { status: 'complete', locked: false, overall: [], by_stage: {} }
    liteApi.setEmail.mockResolvedValue(fullReport)
    const onUnlocked = vi.fn()

    render(<LiteTeaser report={baseTeaser} token="tok-1" onUnlocked={onUnlocked} />)
    fireEvent.change(screen.getByPlaceholderText('you@company.com'), { target: { value: 'visitor@example.com' } })
    fireEvent.click(screen.getByText('Unlock the full report'))

    await waitFor(() => expect(onUnlocked).toHaveBeenCalledWith(fullReport))
    expect(liteApi.setEmail).toHaveBeenCalledWith('tok-1', 'visitor@example.com')
  })
})

describe('LiteTeaser — Stage 13 (W4/W5): competitor_source-driven rival card', () => {
  const soloTeaser = {
    ...baseTeaser,
    competitor_source: 'none',
    overall: [{ name: 'Acme Co', role: 'primary', som: 100 }],
  }

  it('solo run (competitor_source none): shows the quiet note, no rival bars', () => {
    render(<LiteTeaser report={soloTeaser} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.getByText('Competitor comparison unavailable for this run.')).toBeInTheDocument()
    expect(screen.queryByText('Acme Co (you)')).not.toBeInTheDocument()
  })

  it('competitor_source generated: shows the provenance line above the rival bars', () => {
    render(<LiteTeaser report={{ ...baseTeaser, competitor_source: 'generated' }} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.getByText('Competitors auto-selected by ChatGPT')).toBeInTheDocument()
    expect(screen.getByText('Acme Co (you)')).toBeInTheDocument()
  })

  it('competitor_source manual: no provenance line', () => {
    render(<LiteTeaser report={{ ...baseTeaser, competitor_source: 'manual' }} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.queryByText('Competitors auto-selected by ChatGPT')).not.toBeInTheDocument()
  })

  it('competitor_source absent (pre-Stage-13 report): behaves exactly like manual — no crash, no provenance line', () => {
    render(<LiteTeaser report={baseTeaser} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.queryByText('Competitors auto-selected by ChatGPT')).not.toBeInTheDocument()
    expect(screen.getByText('Acme Co (you)')).toBeInTheDocument()
  })
})

describe('LiteTeaser — hero score card', () => {
  it('renders the composite score', () => {
    render(<LiteTeaser report={baseTeaser} token="tok-1" onUnlocked={() => {}} />)
    // Math.round(62.5) -> 63, scoped to the "Agent commerce score" label
    // since other numbers (visibility etc.) can independently render 63 too.
    expect(screen.getByText('Agent commerce score').parentElement.textContent).toContain('63')
  })

  it('renders a band pill matching the composite score', () => {
    render(<LiteTeaser report={baseTeaser} token="tok-1" onUnlocked={() => {}} />)
    // 62.5 rounds display-wise but the band itself is computed on the raw value (62.5 -> Readable but not countable, 60-79).
    expect(screen.getByText(/Readable but not countable/)).toBeInTheDocument()
  })

  it('renders visibility and accessibility family bars', () => {
    render(<LiteTeaser report={baseTeaser} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.getByText('Visibility')).toBeInTheDocument()
    expect(screen.getByText('Accessibility')).toBeInTheDocument()
  })

  it('shows a badge instead of a bar for accessibility when the scan is not complete', () => {
    render(<LiteTeaser report={{ ...baseTeaser, scan_status: 'running' }} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.getByText('scanning…')).toBeInTheDocument()
  })

  it('shows the real value and no badge when the scan is complete', () => {
    const report = { ...baseTeaser, scan_status: 'complete', accessibility: 74 }
    render(<LiteTeaser report={report} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.queryByText('scanning…')).not.toBeInTheDocument()
    const matches = screen.getAllByText((_, node) => (
      node?.classList?.contains('lite-mono') && node.textContent === '74/100'
    ))
    expect(matches.length).toBeGreaterThan(0)
  })

  it('renders the 4-segment band scale', () => {
    render(<LiteTeaser report={baseTeaser} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.getByText('INVISIBLE <40')).toBeInTheDocument()
    expect(screen.getByText('VALUE VISIBLE 80+')).toBeInTheDocument()
  })

  it('renders a verbatim worst-answer excerpt when the API provides one', () => {
    const report = {
      ...baseTeaser,
      worst_mention_excerpt: { text: 'I could not find Acme Co among recommended options.', platform: 'chatgpt' },
    }
    render(<LiteTeaser report={report} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.getByText(/I could not find Acme Co/)).toBeInTheDocument()
  })

  it('renders nothing for the worst-answer section when the field is absent (todays real API)', () => {
    render(<LiteTeaser report={baseTeaser} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.queryByText('A real agent answer')).not.toBeInTheDocument()
  })
})

describe('LiteTeaser — Stage 7: data-driven verdict, never stage-based', () => {
  it('derives a share-based verdict from overall[].som when a rival is present', () => {
    render(<LiteTeaser report={baseTeaser} token="tok-1" onUnlocked={() => {}} />)
    // Rival Co's som is 37.5 -> rounds to 38%.
    expect(screen.getByText('Rival Co took 38% of all mentions.')).toBeInTheDocument()
  })

  it('never mentions a funnel stage anywhere on the pre-gate teaser', () => {
    const { container } = render(<LiteTeaser report={baseTeaser} token="tok-1" onUnlocked={() => {}} />)
    const text = container.textContent.toLowerCase()
    ;['awareness', 'research', 'comparison', 'ready to buy', 'stage-by-stage'].forEach((word) => {
      expect(text).not.toContain(word)
    })
  })

  it('does not promise a stage-by-stage breakdown, or a fix-unlock, in the email-gate copy (Part 4, F4)', () => {
    render(<LiteTeaser report={baseTeaser} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.getByText('Get your private report link sent to your inbox, with a monthly re-run included.')).toBeInTheDocument()
    expect(screen.queryByText(/ranked fixes/)).not.toBeInTheDocument()
    expect(screen.queryByText(/why-section/)).not.toBeInTheDocument()
  })
})

describe('LiteTeaser — R6 honest version fallback (Stage 19)', () => {
  it('shows the previous-methodology notice for a completed scan with no scorer_version (implicit v1)', () => {
    const report = { ...baseTeaser, scan_status: 'complete' }
    render(<LiteTeaser report={report} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.getByText('SCORED UNDER A PREVIOUS METHODOLOGY')).toBeInTheDocument()
  })

  it('shows the notice for an explicit scorer_version "2" row', () => {
    const report = { ...baseTeaser, scan_status: 'complete', scorer_version: '2' }
    render(<LiteTeaser report={report} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.getByText('SCORED UNDER A PREVIOUS METHODOLOGY')).toBeInTheDocument()
  })

  it('never shows the notice for a scorer_version "3" row', () => {
    const report = { ...baseTeaser, scan_status: 'complete', scorer_version: '3' }
    render(<LiteTeaser report={report} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.queryByText('SCORED UNDER A PREVIOUS METHODOLOGY')).not.toBeInTheDocument()
  })

  it('never shows the notice when there is no scan at all (nothing to be "previous" about)', () => {
    render(<LiteTeaser report={baseTeaser} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.queryByText('SCORED UNDER A PREVIOUS METHODOLOGY')).not.toBeInTheDocument()
  })
})
