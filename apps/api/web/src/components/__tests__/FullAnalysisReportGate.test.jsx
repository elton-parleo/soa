import React from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
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
  // Also AnalystLayerSection's own fetch, on the new-report path.
  api.getMetrics.mockResolvedValue({
    entities: [{ code: 'M001', name: 'Allbirds', role: 'primary' }, { code: 'M002', name: 'Nike', role: 'competitor' }],
    slices: { overall: { M001: { mention_rate: 70, som: 24, rsi: 0.5, position_index: 2.4, pdi: 0.82, deal_citation_rate: 12 } } },
  })
})

// A FULL fixture — every Phase 1 payload key present — used for the
// "everything renders from real data" tests.
const FULL_REPORT = {
  cycle_code: 'new-cycle', rendered: true,
  composite: 82, verdict: 'AGENT-READY', scorer_version: '6', total_queries: 480,
  revenue_estimate_usd: 12_000_000,
  pillars: {
    composite: 82, verdict: 'AGENT-READY', member_value_na: false, scorer_version: '6',
    state: 'scored', tv_pct: 70,
    gap_areas_total: 4, gap_areas_parleo_fixes: 2, parleo_fixable_points: 6.5,
    exposure_reasons: [],
    visibility: { score: 90, max: 100, dimensions: [
      { code: 'share_of_mentions', name: 'Share of Mentions', earned: 20, max: 22, na: false, evidence: [] },
      { code: 'recommendation_strength', name: 'Recommendation Strength', earned: 8, max: 10, na: false, evidence: [] },
    ] },
    accessibility: { score: 100, max: 100, dimensions: [
      { code: 'agent_access', name: 'Agent Access', earned: 5, max: 5, na: false, blocked: false, evidence: [], checks: [] },
      { code: 'catalog_context', name: 'Catalog & Context', earned: 8, max: 8, na: false, blocked: false, evidence: [], checks: [] },
      { code: 'protocol_feed', name: 'Protocol & Feed Presence', earned: 5, max: 5, na: false, blocked: false, evidence: [], checks: [] },
    ] },
    true_value: { score: 70, max: 100, dimensions: [
      {
        code: 'price_truth', name: 'Price Truth', earned: 10, max: 16, na: false,
        seen: { earned: 5, max: 7, na: false, evidence: [] },
        said: { earned: 5, max: 9, na: false, evidence: [] },
        said_envelope: { value: 55, numerator: 5, denominator: 9, state: 'measured' },
        fix: null, fix_human: null,
      },
      {
        code: 'deal_citability', name: 'Deal Citability', earned: 8, max: 12, na: false, fix_owner: 'TRUESYNC',
        seen: { earned: 5, max: 7, na: false, evidence: [] },
        said: { earned: 3, max: 5, na: false, evidence: [] },
        said_envelope: { value: 30, numerator: 30, denominator: 100, state: 'measured' },
        fix: 'expose_promos', fix_human: 'Expose your promotions in agent-readable form.',
      },
      {
        code: 'member_value', name: 'Member Value', earned: 0, max: 0, na: true,
        seen: { earned: 0, max: 5, na: true, evidence: [] },
        said: { earned: 0, max: 4, na: true, evidence: [] },
        said_envelope: { value: null, numerator: null, denominator: null, state: 'na' },
        fix: null, fix_human: null,
      },
      {
        code: 'value_protocols', name: 'Value Protocols', earned: 5, max: 14, na: false,
        seen: { earned: 5, max: 14, na: false, evidence: [] }, said: null,
        fix: 'declare_ucp', fix_human: 'Declare UCP discount capability.',
      },
    ] },
    fixes: {
      visible: [
        { code: 'deal_citability', name: 'Deal Citability', fix_human: 'Expose your promotions in agent-readable form.', impact: 4.0, fix_owner: 'TRUESYNC' },
        { code: 'value_protocols', name: 'Value Protocols', fix_human: 'Declare UCP discount capability.', impact: 9.0, fix_owner: 'TRUESYNC' },
      ],
      remaining_count: 0,
    },
  },
  platform_matrix: [
    {
      platform: 'chatgpt', platform_name: 'ChatGPT', total_runs: 240,
      share_of_mentions: { value: 27, numerator: 27, denominator: 100, state: 'measured' },
      recommendation_strength_band: '1st + endorsed',
      agent_access: 'allowed',
      price_truth_said: { value: 61, numerator: 61, denominator: 100, state: 'measured' },
      deal_citability: { value: 12, numerator: 12, denominator: 100, state: 'measured' },
      member_value: 'cited_no_price',
    },
    {
      platform: 'perplexity', platform_name: 'Perplexity', total_runs: 240,
      share_of_mentions: { value: 24, numerator: 24, denominator: 100, state: 'measured' },
      recommendation_strength_band: 'Listed',
      agent_access: 'blocked',
      price_truth_said: { value: null, numerator: 0, denominator: 1, state: 'na' },
      deal_citability: { value: 21, numerator: 21, denominator: 100, state: 'measured' },
      member_value: 'never_cited',
    },
  ],
  competitor_set: {
    overall: [
      { entity: 'Allbirds', is_primary: true, share_pct: 24 },
      { entity: 'Nike', is_primary: false, share_pct: 46 },
    ],
    by_stage: {
      'Ready to Buy': [
        { entity: 'Allbirds', is_primary: true, share_pct: 15 },
        { entity: 'Nike', is_primary: false, share_pct: 55 },
      ],
    },
  },
  scan: {
    status: 'complete', pages_fetched: ['https://example.com/product-1'],
    discovery_trace: { robots_ok: true, homepage_fetched: true, sitemaps_read: 6, product_urls_found: 1940, product_pages_fetched: 120 },
  },
  offers: [
    { name: 'List price', value: '$110.00', readable: 'seen', channel: 'SCHEMA.ORG' },
    { name: 'Availability', value: 'InStock', readable: 'seen', channel: 'SCHEMA.ORG' },
  ],
  product_image_url: null, product_name: "Men's Wool Runner",
  evidence: {
    run_id: 501, platform: 'perplexity', stage: 'Ready to Buy', persona: 'Value-Conscious',
    query_text: 'Are Allbirds shoes worth the price?', answer_excerpt: 'Allbirds runners typically retail around $110–125…',
    price_observation: { stated_price: 120, ground_truth_true_cost: 93.5, delta_pct: 28.3, accurate: false },
    uncited_eligible_offers: 2,
  },
  continuation: null,
}

describe('FullAnalysisReportGate — render-gate behavior', () => {
  it('an old/classic cycle (rendered: false) falls back to MetricsDashboard', async () => {
    api.getFullAnalysisReport.mockResolvedValue({ cycle_code: 'old-cycle', rendered: false, reason: 'no crawl attached yet' })

    render(<FullAnalysisReportGate cycleCode="old-cycle" />)

    await waitFor(() => expect(api.getCycle).toHaveBeenCalledWith('old-cycle'))
    expect(screen.queryByText('AGENTIC VALUE SCORE')).not.toBeInTheDocument()
  })

  it('a cycle with an attached, current-version crawl renders the Full Analysis report from real payload data', async () => {
    api.getFullAnalysisReport.mockResolvedValue(FULL_REPORT)

    render(<FullAnalysisReportGate cycleCode="new-cycle" />)

    await waitFor(() => expect(screen.getByText('AGENTIC VALUE SCORE')).toBeInTheDocument())
    expect(screen.getAllByText('82').length).toBeGreaterThan(0)
    expect(api.getCycle).not.toHaveBeenCalled()
  })

  it('a network/resolve error also falls back to the classic dashboard, never a blank page', async () => {
    api.getFullAnalysisReport.mockRejectedValue(new Error('boom'))

    render(<FullAnalysisReportGate cycleCode="broken-cycle" />)

    await waitFor(() => expect(api.getCycle).toHaveBeenCalledWith('broken-cycle'))
    expect(screen.queryByText('AGENTIC VALUE SCORE')).not.toBeInTheDocument()
  })
})

describe('FullAnalysisReportGate — full payload renders every section', () => {
  it('platform matrix renders real per-platform rows, including a blocked crawler', async () => {
    api.getFullAnalysisReport.mockResolvedValue(FULL_REPORT)
    render(<FullAnalysisReportGate cycleCode="new-cycle" />)

    // Both platform names also appear in the hero's own platform tags —
    // getAllByText, not getByText, since two real renders of the same
    // platform name isn't a duplication bug.
    await waitFor(() => expect(screen.getAllByText('ChatGPT').length).toBeGreaterThan(0))
    expect(screen.getAllByText('Perplexity').length).toBeGreaterThan(0)
    expect(screen.getByText('Blocked')).toBeInTheDocument()
    expect(screen.getByText('Admitted')).toBeInTheDocument()
  })

  it('ranked fixes render from pillars.fixes, unlocked (no remaining-count upsell)', async () => {
    api.getFullAnalysisReport.mockResolvedValue(FULL_REPORT)
    render(<FullAnalysisReportGate cycleCode="new-cycle" />)

    await waitFor(() => expect(screen.getByText('Expose your promotions in agent-readable form.')).toBeInTheDocument())
    expect(screen.getByText('Declare UCP discount capability.')).toBeInTheDocument()
    expect(screen.queryByText(/MORE FIXES IDENTIFIED/)).not.toBeInTheDocument()
  })

  it('evidence card renders the exemplar and toggles the coding panel', async () => {
    api.getFullAnalysisReport.mockResolvedValue(FULL_REPORT)
    render(<FullAnalysisReportGate cycleCode="new-cycle" />)

    await waitFor(() => expect(screen.getByText(/Allbirds runners typically retail/)).toBeInTheDocument())
    expect(screen.queryByText(/run_id/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('View coding'))
    expect(screen.getByText(/run_id/)).toBeInTheDocument()
  })

  it('the stage selector switches the competitor graph and rank label', async () => {
    api.getFullAnalysisReport.mockResolvedValue(FULL_REPORT)
    render(<FullAnalysisReportGate cycleCode="new-cycle" />)

    await waitFor(() => expect(screen.getByText('YOUR AUTO-SELECTED COMPETITOR SET, BY STAGE')).toBeInTheDocument())
    // The hero's own share-of-mentions tile also reads "2nd of 2" — both
    // are correct, real renders of the same rank, not a duplication bug.
    expect(screen.getAllByText('2nd of 2').length).toBeGreaterThan(0)

    fireEvent.click(screen.getByText('Ready to Buy'))
    // 15% (Allbirds) vs 55% (Nike) at Ready to Buy — still 2nd of 2, but
    // now scoped to that stage specifically.
    expect(screen.getByText(/2nd of 2 · READY TO BUY/)).toBeInTheDocument()
  })
})

describe('FullAnalysisReportGate — envelope states render as states, never a fabricated zero', () => {
  it('an N/A True Value dimension renders "Not applicable this cycle"', async () => {
    api.getFullAnalysisReport.mockResolvedValue(FULL_REPORT)
    render(<FullAnalysisReportGate cycleCode="new-cycle" />)
    await waitFor(() => expect(screen.getByText('NOT APPLICABLE')).toBeInTheDocument())
  })

  it('a platform matrix cell with a too-thin opportunity set renders "unmeasured", never a bare number', async () => {
    api.getFullAnalysisReport.mockResolvedValue(FULL_REPORT)
    render(<FullAnalysisReportGate cycleCode="new-cycle" />)
    await waitFor(() => expect(screen.getAllByText('Unmeasured').length).toBeGreaterThan(0))
  })
})

describe('FullAnalysisReportGate — minimal payload (optional keys absent)', () => {
  const MINIMAL_REPORT = {
    cycle_code: 'minimal-cycle', rendered: true,
    composite: 40, verdict: 'NOT AGENT-READY', scorer_version: '6', total_queries: 100,
    pillars: {
      composite: 40, verdict: 'NOT AGENT-READY', member_value_na: false, scorer_version: '6',
      state: 'scored', tv_pct: 20, gap_areas_total: 4, gap_areas_parleo_fixes: 2, parleo_fixable_points: 0,
      exposure_reasons: [],
      visibility: { score: 40, max: 100, dimensions: [] },
      accessibility: { score: 40, max: 100, dimensions: [] },
      true_value: { score: 20, max: 100, dimensions: [] },
      fixes: { visible: [], remaining_count: 0 },
    },
    // Every Phase 1 optional key absent/null — platform_matrix, competitor_set,
    // scan, offers, evidence, revenue_estimate_usd, continuation.
    platform_matrix: [], competitor_set: null, scan: null, offers: null,
    product_image_url: null, product_name: null, revenue_estimate_usd: null,
    evidence: null, continuation: null,
  }

  it('renders the hero and pillar sections without crashing when every optional section is absent', async () => {
    api.getFullAnalysisReport.mockResolvedValue(MINIMAL_REPORT)
    render(<FullAnalysisReportGate cycleCode="minimal-cycle" />)

    await waitFor(() => expect(screen.getByText('AGENTIC VALUE SCORE')).toBeInTheDocument())
    expect(screen.getAllByText('40').length).toBeGreaterThan(0)
    // Sections whose payload key is absent collapse gracefully (2c) —
    // never a placeholder or a crash.
    expect(screen.queryByText(/PLATFORMS × EVERY PILLAR DIMENSION/)).not.toBeInTheDocument()
    expect(screen.queryByText('What an agent actually said')).not.toBeInTheDocument()
    expect(screen.queryByText('YOUR AUTO-SELECTED COMPETITOR SET, BY STAGE')).not.toBeInTheDocument()
  })
})

describe('FullAnalysisReportGate — continuation strip', () => {
  it('present with per-pillar deltas when the cycle traces back to an audit', async () => {
    api.getFullAnalysisReport.mockResolvedValue({
      ...FULL_REPORT,
      continuation: {
        source_lite_request_id: 5, audit_composite: 60, audit_verdict: 'NOT AGENT-READY',
        audit_date: '2026-07-01', audit_platforms_note: 'chatgpt × 5 runs/query',
        pillar_deltas: [
          { pillar: 'visibility', audit_score: 70, full_score: 90, delta: 20, comparable: true },
          { pillar: 'accessibility', audit_score: 100, full_score: 100, delta: 0, comparable: true },
          { pillar: 'true_value', audit_score: 50, full_score: 70, delta: null, comparable: false },
        ],
      },
    })

    render(<FullAnalysisReportGate cycleCode="new-cycle" />)

    await waitFor(() => expect(screen.getByText(/CONTINUED FROM YOUR AUDIT/)).toBeInTheDocument())
    expect(screen.getByText('▲ 20.0 PTS')).toBeInTheDocument()
    expect(screen.getByText('RESCORED AT FULL SCALE')).toBeInTheDocument()
  })

  it('absent for a cycle created the ordinary way', async () => {
    api.getFullAnalysisReport.mockResolvedValue(FULL_REPORT)

    render(<FullAnalysisReportGate cycleCode="new-cycle" />)

    await waitFor(() => expect(screen.getByText('AGENTIC VALUE SCORE')).toBeInTheDocument())
    expect(screen.queryByText(/CONTINUED FROM YOUR AUDIT/)).not.toBeInTheDocument()
  })
})
