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

describe('LiteTeaser — pre-Stage-4 content, unchanged', () => {
  it('renders rival share of voice per entity with role labeling', () => {
    render(<LiteTeaser report={baseTeaser} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.getByText('Acme Co (you)')).toBeInTheDocument()
    expect(screen.getByText('Rival Co')).toBeInTheDocument()
    expect(screen.getByText('62.5%')).toBeInTheDocument()
  })

  it('shows the unlock prompt for the stage-level detail', () => {
    render(<LiteTeaser report={baseTeaser} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.getByText(/unlock the full stage-by-stage diagnostic/)).toBeInTheDocument()
  })

  it('rejects an invalid email without calling the API', async () => {
    render(<LiteTeaser report={baseTeaser} token="tok-1" onUnlocked={() => {}} />)
    fireEvent.change(screen.getByPlaceholderText('you@company.com'), { target: { value: 'not-an-email' } })
    fireEvent.click(screen.getByText('Unlock full report'))

    await waitFor(() => expect(screen.getByText(/valid email/)).toBeInTheDocument())
    expect(liteApi.setEmail).not.toHaveBeenCalled()
  })

  it('unlocks and hands the full report back to the caller on valid email', async () => {
    const fullReport = { status: 'complete', locked: false, overall: [], by_stage: {} }
    liteApi.setEmail.mockResolvedValue(fullReport)
    const onUnlocked = vi.fn()

    render(<LiteTeaser report={baseTeaser} token="tok-1" onUnlocked={onUnlocked} />)
    fireEvent.change(screen.getByPlaceholderText('you@company.com'), { target: { value: 'visitor@example.com' } })
    fireEvent.click(screen.getByText('Unlock full report'))

    await waitFor(() => expect(onUnlocked).toHaveBeenCalledWith(fullReport))
    expect(liteApi.setEmail).toHaveBeenCalledWith('tok-1', 'visitor@example.com')
  })
})

describe('LiteTeaser — Stage 4 additions', () => {
  it('renders the composite score', () => {
    render(<LiteTeaser report={baseTeaser} token="tok-1" onUnlocked={() => {}} />)
    // Math.round(62.5) -> 63, scoped to the "Composite score" line since the
    // Visibility dial can independently round to the same displayed number.
    expect(screen.getByText('Composite score').textContent).toContain('63')
  })

  it('renders visibility and accessibility dials', () => {
    render(<LiteTeaser report={baseTeaser} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.getByText('Visibility')).toBeInTheDocument()
    expect(screen.getByText('Accessibility')).toBeInTheDocument()
  })

  it('dims the accessibility dial with a badge when the scan is not complete', () => {
    render(<LiteTeaser report={{ ...baseTeaser, scan_status: 'running' }} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.getByText('scanning…')).toBeInTheDocument()
  })

  it('shows no badge and the real value when the scan is complete', () => {
    const report = { ...baseTeaser, scan_status: 'complete', accessibility: 74 }
    render(<LiteTeaser report={report} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.queryByText('scanning…')).not.toBeInTheDocument()
    expect(screen.getByText('74')).toBeInTheDocument()
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
