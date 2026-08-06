import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import { LiteFullReportV4 } from '../LiteFullReportV4.jsx'

// Canonical sample numbers used throughout this stage's mocks:
// Visibility 25/40, Accessibility 8/20, True Value 7/40, composite 40.
const FULL_REPORT = {
  status: 'complete',
  locked: false,
  overall: [
    { name: 'Allbirds', role: 'primary', metrics: { som: 35, mention_rate: 42 } },
    { name: 'Nike', role: 'competitor', metrics: { som: 41, mention_rate: 30 } },
  ],
  scan: { status: 'complete', degraded_reason: null, degraded_banner_facts: null },
  scan_status: 'complete',
  visibility: 62.5, accessibility: 40, composite: 40,
  visibility_breakdown: {
    mention_rate: [{ entity: 'Allbirds', is_primary: true, mentioned_queries: 10, total_queries: 24, rate_pct: 42 }],
    share_of_mentions: [
      { entity: 'Amazon', is_primary: false, mentions: 10, share_pct: 41 },
      { entity: 'Allbirds', is_primary: true, mentions: 8, share_pct: 35 },
      { entity: 'Nordstrom', is_primary: false, mentions: 2, share_pct: 9 },
    ],
    totals: { total_mentions: 20, total_queries: 24 },
  },
  offers: [
    { name: 'List price', value: '$105.00', channel: 'schema.org', eligibility: '1 of 4 pages', freshness: 'live', readable: 'seen' },
    { name: 'Availability', value: 'In stock', channel: 'schema.org', eligibility: '1 of 4 pages', freshness: 'live', readable: 'seen' },
    { name: 'Shipping', value: 'Not declared', channel: 'none found', eligibility: 'not found', freshness: 'stale', readable: 'invisible' },
    { name: 'Member price', value: 'N/A', channel: 'none found', eligibility: 'no loyalty program', freshness: 'stale', readable: 'invisible' },
    { name: 'Deals and promos', value: 'Not encoded', channel: 'none', eligibility: '0 of 4 pages', freshness: 'stale', readable: 'invisible' },
    { name: 'Checkout value', value: 'Nothing declared', channel: 'UCP / ACP', eligibility: 'no declaration found', freshness: 'stale', readable: 'invisible' },
  ],
  product_image_url: 'https://cdn.example.com/allbirds-cruiser.jpg',
  pillars: {
    visibility: {
      score: 62.5, max: 100,
      dimensions: [
        { code: 'share_of_mentions', name: 'Share of Mentions', earned: 18, max: 25, na: false, evidence: [] },
        { code: 'recommendation_strength', name: 'Recommendation Strength', earned: 7, max: 15, na: false, evidence: [] },
      ],
    },
    accessibility: {
      score: 40, max: 100,
      dimensions: [
        { code: 'agent_access', name: 'Agent Access', earned: 5, max: 6, na: false, blocked: false, evidence: [], checks: [{ code: 'robots', label: 'robots.txt', state: 'pass' }] },
        { code: 'catalog_context', name: 'Catalog & Context', earned: 2, max: 8, na: false, blocked: false, evidence: [], checks: [{ code: 'complete_markup', label: 'complete markup', state: 'fail' }] },
        { code: 'protocol_feed', name: 'Protocol & Feed Presence', earned: 1, max: 6, na: false, blocked: false, evidence: [], checks: [{ code: 'llms', label: 'llms.txt', state: 'pass' }] },
      ],
    },
    true_value: {
      score: 17.5, max: 100,
      dimensions: [
        {
          code: 'price_truth', name: 'Price Truth', earned: 2, max: 12, na: false, blocked: false,
          seen: { earned: 2, max: 5, na: false, blocked: false },
          said: { earned: 0, max: 7, na: false },
        },
        {
          code: 'member_value', name: 'Member Value', earned: 0, max: 15, na: true,
          seen: { earned: 0, max: 9, na: true }, said: { earned: 0, max: 6, na: true },
        },
        {
          code: 'deal_citability', name: 'Deal Citability', earned: 1, max: 6, na: false, blocked: false,
          seen: { earned: 0, max: 4, na: false }, said: { earned: 1, max: 2, na: false },
        },
        {
          code: 'value_protocols', name: 'Value Protocols', earned: 0, max: 7, na: false, blocked: false,
          checks: [{ code: 'ucp', label: 'UCP discounts', state: 'fail' }],
        },
      ],
    },
    composite: 40,
    member_value_na: true,
    state: 'scored',
    tv_pct: 12,
    fixes: {
      visible: [
        { code: 'catalog_context', name: 'Add readable product data to every product page', fix_human: 'Name, price, availability, so agents can read what you sell', impact: 12, fix_owner: 'ENG' },
        { code: 'price_truth', name: 'Put your price in your page code', fix_human: 'A price agents can quote, matching the one shoppers see', impact: 8, fix_owner: 'ENG' },
      ],
      remaining_count: 4,
    },
    verdict: 'NOT AGENT-READY',
    gap_areas_total: 4,
    gap_areas_parleo_fixes: 2,
    parleo_fixable_points: 13,
  },
}

function renderReport(overrides = {}) {
  const report = { ...FULL_REPORT, ...overrides, pillars: { ...FULL_REPORT.pillars, ...(overrides.pillars || {}) } }
  return render(<LiteFullReportV4 report={report} token="tok-full" />)
}

describe('LiteFullReportV4 — full scored run renders without crashing', () => {
  it('renders the rail, score hero, and every section', () => {
    renderReport()
    expect(screen.getAllByText('Allbirds').length).toBeGreaterThan(0)
    expect(screen.getByText('Agents know who you are')).toBeInTheDocument()
    expect(screen.getByText("Agents can knock, but can't read much")).toBeInTheDocument()
    expect(screen.getByText('Your value leaks before it reaches the answer')).toBeInTheDocument()
    expect(screen.getByText('Where you disappear in the funnel')).toBeInTheDocument()
    expect(screen.getByText('Encoded, declared, and kept in sync')).toBeInTheDocument()
    expect(screen.getByText('What the gap is worth')).toBeInTheDocument()
    expect(screen.getByText('Stop the leak')).toBeInTheDocument()
  })

  it('F3/F4: fixable hook and fixes table read counts from the run, not literals', () => {
    renderReport()
    expect(screen.getByText('Parleo can fix 2 of your 4 major gaps.')).toBeInTheDocument()
    expect(screen.getByText('Add readable product data to every product page')).toBeInTheDocument()
    expect(screen.getAllByText('ENG').length).toBeGreaterThan(0)
    expect(screen.getByText('4 MORE FIXES IDENTIFIED, NOT RANKED IN THIS SAMPLE')).toBeInTheDocument()
  })

  it('F1/F2: the parsed-page card renders the real OfferFeed and product image', () => {
    renderReport()
    expect(screen.getAllByText('$105.00').length).toBeGreaterThan(0)
    const img = screen.getByAltText("Product, as parsed from the merchant's own markup")
    expect(img).toHaveAttribute('src', 'https://cdn.example.com/allbirds-cruiser.jpg')
  })

  it('member_value_na row shows N/A, not a fabricated score', () => {
    renderReport()
    expect(screen.getByText('Member Value')).toBeInTheDocument()
    expect(screen.getAllByText('N/A').length).toBeGreaterThan(0)
  })
})

describe('LiteFullReportV4 — H1/H2 honest states', () => {
  it('omits the parsed-page card and shows the honest banner when offers is null', () => {
    renderReport({ offers: null, product_image_url: null })
    expect(screen.queryByText('$105.00')).not.toBeInTheDocument()
    expect(screen.getByText(/No product page parsed cleanly enough this run/)).toBeInTheDocument()
  })

  it('omits the product image slot entirely when product_image_url is null', () => {
    renderReport({ product_image_url: null })
    expect(screen.queryByAltText("Product, as parsed from the merchant's own markup")).not.toBeInTheDocument()
    // The offer feed itself still renders — only the image slot is gone.
    expect(screen.getAllByText('$105.00').length).toBeGreaterThan(0)
  })

  it('a blocked True Value dimension reads unmeasured, never a fabricated zero', () => {
    renderReport({
      pillars: {
        true_value: {
          ...FULL_REPORT.pillars.true_value,
          dimensions: FULL_REPORT.pillars.true_value.dimensions.map((d) =>
            d.code === 'price_truth' ? { ...d, blocked: true, seen: { ...d.seen, blocked: true } } : d,
          ),
        },
      },
    })
    expect(screen.getAllByText('N/M').length).toBeGreaterThan(0)
  })

  it('gap_areas_total/parleo_fixes come from the payload, not a hardcoded 4/2', () => {
    renderReport({ pillars: { gap_areas_total: 3, gap_areas_parleo_fixes: 1, parleo_fixable_points: 5 } })
    expect(screen.getByText('Parleo can fix 1 of your 3 major gaps.')).toBeInTheDocument()
  })

  it('no fixes payload at all renders no crash and no fixes table', () => {
    renderReport({ pillars: { fixes: null } })
    expect(screen.queryByText('4 MORE FIXES IDENTIFIED, NOT RANKED IN THIS SAMPLE')).not.toBeInTheDocument()
  })
})
