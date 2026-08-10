import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import FullAnalysisReportGate from '../FullAnalysisReportGate.jsx'
import { api } from '../../api.js'

vi.mock('../../api.js', () => ({
  api: {
    getFullAnalysisReport: vi.fn(),
    getCycle: vi.fn(),
    getCycleEntities: vi.fn(),
    getCycleTruecostSnapshots: vi.fn(),
    getCycles: vi.fn(),
    getPositions: vi.fn(),
    getMetrics: vi.fn(),
    resumeCycle: vi.fn(),
  },
}))

// The gate's fallback path renders the real MetricsDashboard.jsx, which
// renders Sidebar.jsx, which calls useAuth() — not under test here, so
// stubbed the same way a logged-in session would look.
vi.mock('../../AuthContext.jsx', () => ({
  useAuth: () => ({ session: { user: { email: 'test@example.com' } }, signOut: vi.fn() }),
}))

beforeEach(() => {
  vi.clearAllMocks()
  // MetricsDashboard fetches cycle/metrics data on mount — give it enough
  // to render its own loading/empty state without throwing.
  api.getCycle.mockResolvedValue({ cycle_code: 'old-cycle', status: 'complete', cycle_mode: 'query' })
  api.getCycleEntities.mockResolvedValue([])
  api.getMetrics.mockResolvedValue({ entities: [], slices: {} })
})

const RENDERED_REPORT = {
  cycle_code: 'new-cycle', rendered: true,
  composite: 82, verdict: 'AGENT-READY', scorer_version: '6', total_queries: 480,
  pillars: {
    composite: 82, verdict: 'AGENT-READY', member_value_na: false, scorer_version: '6',
    visibility: { score: 90, max: 100, dimensions: [
      { code: 'share_of_mentions', name: 'Share of Mentions', earned: 20, max: 22, na: false },
    ] },
    accessibility: { score: 100, max: 100, dimensions: [
      { code: 'agent_access', name: 'Agent Access', earned: 5, max: 5, na: false },
    ] },
    true_value: { score: 70, max: 100, dimensions: [
      {
        code: 'deal_citability', name: 'Deal Citability', earned: 8, max: 12, na: false, fix_owner: 'TRUESYNC',
        seen: { earned: 5, max: 7, na: false },
        said_envelope: { value: 30, numerator: 30, denominator: 100, state: 'measured' },
      },
      {
        code: 'member_value', name: 'Member Value', earned: 0, max: 0, na: true,
        seen: { earned: 0, max: 5, na: true },
        said_envelope: { value: null, numerator: null, denominator: null, state: 'na' },
      },
    ] },
  },
  continuation: null,
}

describe('FullAnalysisReportGate — render-gate behavior', () => {
  it('an old/classic cycle (rendered: false) falls back to MetricsDashboard', async () => {
    api.getFullAnalysisReport.mockResolvedValue({ cycle_code: 'old-cycle', rendered: false, reason: 'no crawl attached yet' })

    render(<FullAnalysisReportGate cycleCode="old-cycle" />)

    await waitFor(() => expect(api.getCycle).toHaveBeenCalledWith('old-cycle'))
    expect(screen.queryByText('Full Analysis')).not.toBeInTheDocument()
  })

  it('a cycle with an attached, current-version crawl renders the Full Analysis report', async () => {
    api.getFullAnalysisReport.mockResolvedValue(RENDERED_REPORT)

    render(<FullAnalysisReportGate cycleCode="new-cycle" />)

    await waitFor(() => expect(screen.getByText('Full Analysis')).toBeInTheDocument())
    expect(screen.getByText('82')).toBeInTheDocument()
    expect(api.getCycle).not.toHaveBeenCalled()
  })

  it('a network/resolve error also falls back to the classic dashboard, never a blank page', async () => {
    api.getFullAnalysisReport.mockRejectedValue(new Error('boom'))

    render(<FullAnalysisReportGate cycleCode="broken-cycle" />)

    await waitFor(() => expect(api.getCycle).toHaveBeenCalledWith('broken-cycle'))
    expect(screen.queryByText('Full Analysis')).not.toBeInTheDocument()
  })
})

describe('FullAnalysisReportGate — N/A and not-measured states', () => {
  it('renders an unmeasured chip for an N/A dimension, never a bare zero', async () => {
    api.getFullAnalysisReport.mockResolvedValue(RENDERED_REPORT)

    render(<FullAnalysisReportGate cycleCode="new-cycle" />)

    await waitFor(() => expect(screen.getByText('Not applicable this cycle')).toBeInTheDocument())
  })

  it('renders a measured said-envelope as a percentage', async () => {
    api.getFullAnalysisReport.mockResolvedValue(RENDERED_REPORT)

    render(<FullAnalysisReportGate cycleCode="new-cycle" />)

    await waitFor(() => expect(screen.getByText('30%')).toBeInTheDocument())
  })
})

describe('FullAnalysisReportGate — continuation banner', () => {
  it('present when the cycle traces back to an audit', async () => {
    api.getFullAnalysisReport.mockResolvedValue({
      ...RENDERED_REPORT,
      continuation: {
        source_lite_request_id: 5, audit_composite: 60, audit_verdict: 'NOT AGENT-READY',
        audit_date: '2026-07-01', audit_platforms_note: 'chatgpt × 5 runs/query',
      },
    })

    render(<FullAnalysisReportGate cycleCode="new-cycle" />)

    await waitFor(() => expect(screen.getByText(/Your audit scored 60 on 2026-07-01/)).toBeInTheDocument())
  })

  it('absent for a cycle created the ordinary way', async () => {
    api.getFullAnalysisReport.mockResolvedValue(RENDERED_REPORT)

    render(<FullAnalysisReportGate cycleCode="new-cycle" />)

    await waitFor(() => expect(screen.getByText('Full Analysis')).toBeInTheDocument())
    expect(screen.queryByText(/Your audit scored/)).not.toBeInTheDocument()
  })
})
