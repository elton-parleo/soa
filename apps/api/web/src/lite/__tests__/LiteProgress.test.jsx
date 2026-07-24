import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import '@testing-library/jest-dom'

import { LiteProgress, LiteFailed } from '../LiteProgress.jsx'

describe('LiteProgress — LLM query track (unchanged behavior)', () => {
  it('maps generating_queries to the query-design message', () => {
    render(<LiteProgress phaseData={{ status: 'generating', phase: 'generating_queries' }} />)
    expect(screen.getByText('Designing your 12-query diagnostic…')).toBeInTheDocument()
  })

  it('maps queued to a waiting message', () => {
    render(<LiteProgress phaseData={{ status: 'pending', phase: 'queued' }} />)
    expect(screen.getByText(/Queued/)).toBeInTheDocument()
  })

  it('maps analyzing to the analyzing message', () => {
    render(<LiteProgress phaseData={{
      status: 'running', phase: 'analyzing',
      progress: { completed_runs: 12, total_runs: 12 },
    }} />)
    expect(screen.getByText('Analyzing responses…')).toBeInTheDocument()
  })

  it('maps running with progress to a 1-indexed query count', () => {
    render(<LiteProgress phaseData={{
      status: 'running', phase: 'running',
      progress: { completed_runs: 4, total_runs: 12 },
    }} />)
    expect(screen.getByText('Running query 5 of 12 against ChatGPT…')).toBeInTheDocument()
    expect(screen.getByText('4 of 12 queries complete')).toBeInTheDocument()
  })

  it('caps the displayed query number at the total when completed_runs reaches it', () => {
    render(<LiteProgress phaseData={{
      status: 'running', phase: 'running',
      progress: { completed_runs: 12, total_runs: 12 },
    }} />)
    expect(screen.getByText('Running query 12 of 12 against ChatGPT…')).toBeInTheDocument()
  })

  it('renders a passed-in error banner', () => {
    render(<LiteProgress phaseData={{ status: 'pending', phase: 'queued' }} error="Could not check status." />)
    expect(screen.getByText('Could not check status.')).toBeInTheDocument()
  })
})

describe('LiteProgress — scan track', () => {
  it('is omitted entirely when no store_url was submitted', () => {
    render(<LiteProgress phaseData={{ status: 'pending', phase: 'queued', scan_status: null }} />)
    expect(screen.queryByText(/Reading your store/)).not.toBeInTheDocument()
  })

  it('shows a queued message before the scan has a status yet', () => {
    render(<LiteProgress phaseData={{ status: 'pending', phase: 'queued', scan_status: null }} storeUrl="acme.com" />)
    expect(screen.getByText(/Queued to read acme.com/)).toBeInTheDocument()
  })

  it('shows the reading-in-progress message while scan_status is running', () => {
    render(<LiteProgress phaseData={{ status: 'running', phase: 'running', scan_status: 'running' }} storeUrl="https://acme.com" />)
    expect(screen.getByText(/Reading acme.com like an agent/)).toBeInTheDocument()
  })

  it('shows a completion checkmark when scan_status is complete', () => {
    render(<LiteProgress phaseData={{ status: 'running', phase: 'analyzing', scan_status: 'complete' }} storeUrl="acme.com" />)
    expect(screen.getByText(/Finished reading acme.com/)).toBeInTheDocument()
  })

  it('shows an honest, non-error badge when the scan is blocked', () => {
    render(<LiteProgress phaseData={{ status: 'running', phase: 'running', scan_status: 'blocked' }} storeUrl="acme.com" />)
    expect(screen.getByText(/blocked our reader — that itself is a finding/)).toBeInTheDocument()
  })

  it('shows an honest, non-error badge when the scan failed', () => {
    render(<LiteProgress phaseData={{ status: 'running', phase: 'running', scan_status: 'failed' }} storeUrl="acme.com" />)
    expect(screen.getByText(/couldn't finish reading acme.com/)).toBeInTheDocument()
  })

  it('shows an honest, non-error badge when the scan was skipped', () => {
    render(<LiteProgress phaseData={{ status: 'running', phase: 'running', scan_status: 'skipped' }} storeUrl="acme.com" />)
    expect(screen.getByText(/didn't get a chance to read acme.com/)).toBeInTheDocument()
  })
})

describe('LiteFailed', () => {
  it('calls onRetry when the button is clicked', () => {
    const onRetry = vi.fn()
    render(<LiteFailed onRetry={onRetry} />)
    screen.getByText('Try again').click()
    expect(onRetry).toHaveBeenCalled()
  })
})
