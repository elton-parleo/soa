/**
 * Discovery follow-up (Part 4): DiscoveryFinding in isolation. The
 * fuller partialRead.test.jsx exercises it through the whole
 * LiteFullReportV4 tree (Marc Jacobs/Sephora/Michael Kors fixtures);
 * these tests render it directly to pin down the discovery_outcome ->
 * copy/step-fact wiring without the rest of the report around it.
 */
import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import { DiscoveryFinding } from '../DiscoveryFinding.jsx'
import { FAILURE_POINT_COPY, DISCOVERY_OUTCOME_COPY } from '../reportContent.js'

const PILLARS = {
  visibility: { dimensions: [{ code: 'x', earned: 25, max: 40, na: false, blocked: false }] },
  accessibility: { dimensions: [{ code: 'y', earned: 8, max: 20, na: false, blocked: false }] },
  true_value: { dimensions: [{ code: 'z', earned: 0, max: 0, na: false, blocked: true }] },
}

function _report(scanOverrides = {}) {
  return {
    pillars: PILLARS,
    scan_status: 'complete',
    scan: {
      degraded_reason: null,
      degraded_banner_facts: null,
      discovery_trace: {
        sitemaps_read: 3, product_urls_found: 0, robots_ok: true,
        homepage_fetched: true, product_pages_fetched: 0,
      },
      ...scanOverrides,
    },
  }
}

function renderIt(report) {
  return render(<DiscoveryFinding report={report} open onToggle={() => {}} />)
}

describe('DiscoveryFinding — no discovery_outcome (legacy report)', () => {
  it('falls back to the generic 3-bucket FAILURE_POINT_COPY.partial entry', () => {
    renderIt(_report())
    expect(screen.getByText(FAILURE_POINT_COPY.partial.heading)).toBeInTheDocument()
  })

  it('renders no WHAT WE TRIED or EXAMPLE URLS blocks without discovery_outcome', () => {
    renderIt(_report())
    expect(screen.queryByText('WHAT WE TRIED')).not.toBeInTheDocument()
    expect(screen.queryByText('EXAMPLE URLS WE FOUND')).not.toBeInTheDocument()
  })
})

describe('DiscoveryFinding — discovery_outcome present, a "not found" code (our own limitation)', () => {
  const discoveryOutcome = {
    code: 'sitemaps_non_catalog',
    summary: 'we read your sitemaps and checked your homepage and category links, but found nothing that looked like a product catalog',
    product_pages_attempted: 0, product_pages_fetched: 0,
    sitemaps: [{ name: 'sitemap.xml', outcome: 'read', urls: 40, product_urls: 0, http_status: 200, note: null }],
    child_chosen: null,
    example_urls: [],
    tiers: [
      { tier: 'sitemap', outcome: 'found 0' },
      { tier: 'homepage', outcome: 'found 0' },
    ],
    robots_excluded: 0, llm: null, short_circuited: false,
  }

  it('reads the code-specific heading and the summary as the body', () => {
    renderIt(_report({ discovery_outcome: discoveryOutcome }))
    expect(screen.getByText(DISCOVERY_OUTCOME_COPY.sitemaps_non_catalog.heading)).toBeInTheDocument()
    expect(screen.getByText(discoveryOutcome.summary, { exact: false })).toBeInTheDocument()
  })

  it('shows the code-specific explanation in the fix box, never the "blocked" fixFraming framing', () => {
    renderIt(_report({ discovery_outcome: discoveryOutcome }))
    expect(screen.getByText(DISCOVERY_OUTCOME_COPY.sitemaps_non_catalog.explanation, { exact: false })).toBeInTheDocument()
    expect(screen.queryByText(FAILURE_POINT_COPY.blocked.fixFraming(null, null))).not.toBeInTheDocument()
  })

  it('renders WHAT WE TRIED with friendly tier labels next to their raw outcome strings', () => {
    renderIt(_report({ discovery_outcome: discoveryOutcome }))
    expect(screen.getByText('WHAT WE TRIED')).toBeInTheDocument()
    expect(screen.getByText('Sitemap walk')).toBeInTheDocument()
    expect(screen.getByText('Homepage links')).toBeInTheDocument()
    expect(screen.getAllByText('found 0')).toHaveLength(2)
  })

  it('omits the EXAMPLE URLS block when discovery_outcome.example_urls is empty', () => {
    renderIt(_report({ discovery_outcome: discoveryOutcome }))
    expect(screen.queryByText('EXAMPLE URLS WE FOUND')).not.toBeInTheDocument()
  })
})

describe('DiscoveryFinding — discovery_outcome present, a genuine refusal code', () => {
  const discoveryOutcome = {
    code: 'sitemaps_robots_disallowed',
    summary: 'your robots.txt disallows every declared sitemap to readers like ours, and your homepage links did not lead to a product page',
    product_pages_attempted: 0, product_pages_fetched: 0,
    sitemaps: [{ name: 'sitemap.xml', outcome: 'robots_disallowed', urls: null, product_urls: null, http_status: null, note: null }],
    child_chosen: null,
    example_urls: ['https://example.com/products/blue-widget', 'https://example.com/products/red-widget'],
    tiers: [],
    robots_excluded: 2, llm: null, short_circuited: false,
  }

  it('reads the code-specific heading, and never our own-limitation framing for a real refusal', () => {
    renderIt(_report({ discovery_outcome: discoveryOutcome }))
    expect(screen.getByText(DISCOVERY_OUTCOME_COPY.sitemaps_robots_disallowed.heading)).toBeInTheDocument()
  })

  it('the fix box shows fixFraming (the blocked-bucket box shape), not the explanation sentence', () => {
    renderIt(_report({ discovery_outcome: discoveryOutcome }))
    expect(screen.getByText(DISCOVERY_OUTCOME_COPY.sitemaps_robots_disallowed.fixFraming)).toBeInTheDocument()
    expect(screen.queryByText(/What this usually means/)).not.toBeInTheDocument()
  })

  it('renders discovery_outcome.example_urls in a mono EXAMPLE URLS block', () => {
    renderIt(_report({ discovery_outcome: discoveryOutcome }))
    expect(screen.getByText('EXAMPLE URLS WE FOUND')).toBeInTheDocument()
    for (const url of discoveryOutcome.example_urls) {
      expect(screen.getByText(url)).toBeInTheDocument()
    }
  })
})
