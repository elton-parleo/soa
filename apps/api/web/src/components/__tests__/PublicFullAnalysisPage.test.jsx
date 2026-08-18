/**
 * 2e: the public /fa/{token} viewer — renders from the token payload
 * with no app chrome and no auth-walled links, and falls back to the
 * shared not-found card for any non-rendering response (unknown,
 * revoked, expired — the backend collapses all three to one 404, so
 * there is deliberately only one card to assert against here).
 */
import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import PublicFullAnalysisPage from '../PublicFullAnalysisPage.jsx'
import { publicFullAnalysisApi } from '../../publicFullAnalysisApi.js'

vi.mock('../../publicFullAnalysisApi.js', () => ({
  publicFullAnalysisApi: { getReport: vi.fn() },
}))

// FullAnalysisReport.jsx imports api.js unconditionally at module scope
// (FullAnalysisShareControl's own dependency) even though readOnly mode
// never calls it — mocked the same way FullAnalysisReportGate.test.jsx
// already does, so this file never touches the real Supabase client.
vi.mock('../../api.js', () => ({
  api: {
    getShareLink: vi.fn(),
    createShareLink: vi.fn(),
    revokeShareLink: vi.fn(),
    getMetrics: vi.fn(),
  },
}))

const FULL_REPORT = {
  cycle_code: 'shared-cycle', rendered: true,
  composite: 55, verdict: 'NOT AGENT-READY', scorer_version: '6', total_queries: 24,
  pillars: {
    composite: 55, verdict: 'NOT AGENT-READY', member_value_na: false, scorer_version: '6',
    state: 'scored', tv_pct: 15, gap_areas_total: 4, gap_areas_parleo_fixes: 2, parleo_fixable_points: 6.5,
    exposure_reasons: [],
    visibility: { score: 31, max: 32, dimensions: [] },
    accessibility: { score: 14, max: 18, dimensions: [] },
    true_value: { score: 5, max: 33, dimensions: [] },
    fixes: { visible: [], remaining_count: 0 },
  },
  platform_matrix: [], competitor_set: null, scan: null, offers: null,
  product_image_url: null, product_name: null, revenue_estimate_usd: null,
  evidence: {
    platform: 'chatgpt', stage: 'Comparison', persona: 'shopper', query_text: 'test query',
    answer_excerpt: 'excerpt', run_id: 4242, uncited_eligible_offers: 0,
    price_observation: { stated_price: 10, ground_truth_true_cost: 8, delta_pct: 25 },
  },
  continuation: null, generated_headlines: null, transcript: null,
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('PublicFullAnalysisPage — renders the report with no app chrome', () => {
  it('fetches by token and renders the report, no "Back to dashboard" and no Share control', async () => {
    publicFullAnalysisApi.getReport.mockResolvedValue(FULL_REPORT)
    render(<PublicFullAnalysisPage token="tok-123" />)

    await waitFor(() => expect(screen.getByText('AGENTIC VALUE SCORE')).toBeInTheDocument())
    expect(publicFullAnalysisApi.getReport).toHaveBeenCalledWith('tok-123')
    expect(screen.queryByText('← Back to dashboard')).not.toBeInTheDocument()
    expect(screen.queryByText('Share report')).not.toBeInTheDocument()
  })

  it('never renders the Analyst layer section or its nav entry (the one section with no public equivalent)', async () => {
    publicFullAnalysisApi.getReport.mockResolvedValue(FULL_REPORT)
    render(<PublicFullAnalysisPage token="tok-123" />)

    await waitFor(() => expect(screen.getByText('AGENTIC VALUE SCORE')).toBeInTheDocument())
    expect(screen.queryByText('Analyst layer')).not.toBeInTheDocument()
  })

  it('renders the Evidence "View coding" toggle but never the Response Explorer deep link', async () => {
    publicFullAnalysisApi.getReport.mockResolvedValue(FULL_REPORT)
    render(<PublicFullAnalysisPage token="tok-123" />)

    await waitFor(() => expect(screen.getByText('What an agent actually said')).toBeInTheDocument())
    expect(screen.getByText('View coding')).toBeInTheDocument()
    expect(screen.queryByText('View in Response Explorer →')).not.toBeInTheDocument()
  })
})

describe('PublicFullAnalysisPage — not-found state', () => {
  it('shows the not-found card on a 404 (unknown/revoked/expired — all indistinguishable)', async () => {
    const err = new Error('Not found.')
    err.status = 404
    publicFullAnalysisApi.getReport.mockRejectedValue(err)
    render(<PublicFullAnalysisPage token="dead-token" />)

    await waitFor(() => expect(screen.getByText("We couldn't find this report")).toBeInTheDocument())
    expect(screen.getByText(/mistyped, revoked, or no longer available/)).toBeInTheDocument()
  })

  it('shows a distinct rate-limited message on a 429', async () => {
    const err = new Error('Too many requests')
    err.status = 429
    publicFullAnalysisApi.getReport.mockRejectedValue(err)
    render(<PublicFullAnalysisPage token="tok-123" />)

    await waitFor(() => expect(screen.getByText('Too many requests')).toBeInTheDocument())
  })

  it('falls back to the not-found card if the payload somehow comes back rendered=false', async () => {
    publicFullAnalysisApi.getReport.mockResolvedValue({ cycle_code: 'x', rendered: false, reason: 'not_scored' })
    render(<PublicFullAnalysisPage token="tok-123" />)

    await waitFor(() => expect(screen.getByText("We couldn't find this report")).toBeInTheDocument())
  })
})
