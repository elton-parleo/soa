/**
 * Blocked-run report: name the wall, and show what ChatGPT could read.
 *
 * Twelve of the 34 audits in the 30-day review were blocked at the door
 * across seven stores. Two facts the scan already had never reached
 * those reports:
 *
 *   1. WHICH bot-management vendor refused us. The report told every
 *      one of them about "security tools like Cloudflare" whether or
 *      not Cloudflare was the tool involved.
 *   2. What ChatGPT saw at the same URL. On Vans and Warby Parker the
 *      probe came back quoted_price against a 403'd crawl — the single
 *      most useful fact on a blocked report, spent on one clause at the
 *      bottom of a banner. On Adidas and NAPA it came back
 *      could_not_access, which corroborates the block.
 *
 * Neither is ever a score. The last describe block in this file holds
 * that line directly.
 */
import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import { LiteFullReportV4 } from '../LiteFullReportV4.jsx'
import {
  FAILURE_POINT_COPY, EDGE_VENDOR_COPY, EDGE_VENDOR_UNKNOWN_COPY,
  FETCH_PROBE_EVIDENCE_COPY, BLOCKED_ACCESSIBILITY_HEADLINE,
} from '../reportContent.js'

const VENDORS = Object.keys(EDGE_VENDOR_COPY)
const PROBE_OUTCOMES = ['quoted_price', 'opened_no_price', 'could_not_access']

function _visDims() {
  return [
    { code: 'share_of_mentions', name: 'Share of Mentions', earned: 22, max: 25, na: false, evidence: [] },
    { code: 'recommendation_strength', name: 'Recommendation Strength', earned: 13, max: 15, na: false, evidence: [] },
  ]
}

// Every accessibility/true-value dimension blocked — the shape a run
// that never got past the door actually produces.
function _blockedPillars() {
  return {
    visibility: { score: 90, max: 100, dimensions: _visDims() },
    accessibility: {
      score: 0, max: 100,
      dimensions: [
        { code: 'agent_access', name: 'Agent Access', earned: 0, max: 0, na: false, blocked: true, evidence: [], checks: [{ code: 'robots', label: 'robots.txt', state: 'blocked' }] },
        { code: 'catalog_context', name: 'Catalog & Context', earned: 0, max: 0, na: false, blocked: true, evidence: [], checks: [{ code: 'markup', label: 'complete markup', state: 'blocked' }] },
        { code: 'protocol_feed', name: 'Protocol & Feed Presence', earned: 0, max: 0, na: false, blocked: true, evidence: [], checks: [{ code: 'llms', label: 'llms.txt', state: 'blocked' }] },
      ],
    },
    true_value: {
      score: 0, max: 100,
      dimensions: [
        {
          code: 'price_truth', name: 'Price Truth', earned: 0, max: 0, na: false, blocked: true,
          seen: { earned: 0, max: 5, na: false, blocked: true }, said: { earned: 0, max: 7, na: false },
          checks: [{ code: 'price_in_code', label: 'price in your code', state: 'blocked' }],
        },
        {
          code: 'value_protocols', name: 'Value Protocols', earned: 0, max: 0, na: false, blocked: true,
          seen: { earned: 0, max: 7, na: false, blocked: true }, said: null,
          checks: [{ code: 'ucp', label: 'UCP discounts', state: 'blocked' }],
        },
      ],
    },
    composite: null,
    member_value_na: false,
    state: 'unverified',
    tv_pct: null,
    fixes: {
      visible: [
        { code: 'agent_access', name: 'Let verified AI readers in', fix_human: 'generic backend fix text', impact: 6, fix_owner: 'ENG' },
      ],
      remaining_count: 1,
    },
    verdict: null,
    gap_areas_total: 4,
    gap_areas_parleo_fixes: 1,
    parleo_fixable_points: 7,
    exposure_reasons: [],
  }
}

function blockedReport({ vendor = null, probeOutcome = null, price = null, kind = 'product_page' } = {}) {
  const fetchProbe = probeOutcome
    ? {
        outcome: probeOutcome,
        agent_could_access: probeOutcome !== 'could_not_access',
        url: 'https://walled.example.com/p/tee',
        kind,
        price: probeOutcome === 'quoted_price' ? price : null,
      }
    : null
  return {
    status: 'complete',
    locked: false,
    overall: [{ name: 'Vans', role: 'primary', metrics: { som: 40, mention_rate: 50 } }],
    visibility_breakdown: {
      mention_rate: [{ entity: 'Vans', is_primary: true, mentioned_queries: 12, total_queries: 24, rate_pct: 50 }],
      share_of_mentions: [
        { entity: 'Vans', is_primary: true, mentions: 8, share_pct: 40 },
        { entity: 'Converse', is_primary: false, mentions: 12, share_pct: 60 },
      ],
      totals: { total_mentions: 20, total_queries: 24 },
    },
    offers: null,
    product_image_url: null,
    product_name: null,
    scan_status: 'blocked',
    scan: {
      status: 'blocked',
      degraded_reason: 'blocked',
      edge_vendor: vendor,
      site_type: null,
      degraded_banner_facts: {
        refusal: '403', attempts: 6, robots_included: true, signed: true,
        ...(fetchProbe ? { fetch_probe: fetchProbe } : {}),
      },
      discovery_trace: {
        sitemaps_read: 0, product_urls_found: 0, tiers_attempted: [],
        robots_ok: false, homepage_fetched: false, product_pages_fetched: 0,
      },
    },
    composite: null,
    pillars: _blockedPillars(),
  }
}

function renderIt(report) {
  return render(<LiteFullReportV4 report={report} token="tok-blocked" />)
}

// ─── vendor attribution ────────────────────────────────────────────────

describe('blocked run — the wall is named when we recognized it', () => {
  it.each(VENDORS)('%s: the report names the vendor and its own setting', (vendor) => {
    const { container } = renderIt(blockedReport({ vendor }))
    const copy = EDGE_VENDOR_COPY[vendor]

    expect(container.textContent).toContain(copy.name)
    expect(container.textContent).toContain(copy.setting)
  })

  it.each(VENDORS)('%s: no OTHER vendor is named on the same report', (vendor) => {
    const { container } = renderIt(blockedReport({ vendor }))
    for (const other of VENDORS) {
      if (other === vendor) continue
      expect(container.textContent).not.toContain(EDGE_VENDOR_COPY[other].name)
    }
  })

  it('an unrecognized vendor gets the neutral wording, never a guess', () => {
    const { container } = renderIt(blockedReport({ vendor: null }))

    expect(container.textContent).toContain(EDGE_VENDOR_UNKNOWN_COPY.clause)
    for (const vendor of VENDORS) {
      expect(container.textContent).not.toContain(EDGE_VENDOR_COPY[vendor].name)
    }
  })

  it('the finding and the ranked fix name the same wall', () => {
    const { container } = renderIt(blockedReport({ vendor: 'cloudflare' }))
    const line = FAILURE_POINT_COPY.blocked.fixFraming(
      { refusal: '403', attempts: 6 }, 'cloudflare',
    )
    // Once in the discovery section's action box, once as the ranked
    // fix's description — the same string from the same registry entry.
    expect(screen.getAllByText(line).length).toBe(2)
    expect(container.textContent).not.toContain(EDGE_VENDOR_UNKNOWN_COPY.setting)
  })

  it('a vendor name never leaks onto a report with no wall to attribute', () => {
    const report = blockedReport({ vendor: 'cloudflare' })
    report.scan_status = 'complete'
    report.scan.status = 'complete'
    report.scan.degraded_reason = null
    report.scan.edge_vendor = null

    const { container } = renderIt(report)
    expect(container.textContent).not.toContain('Cloudflare')
  })
})

// ─── the fetch probe as evidence ───────────────────────────────────────

describe('blocked run — what ChatGPT saw', () => {
  it.each(PROBE_OUTCOMES)('%s: renders its own fact block', (probeOutcome) => {
    const { container } = renderIt(blockedReport({ probeOutcome, price: '$64.00' }))

    expect(screen.getByText(FETCH_PROBE_EVIDENCE_COPY.label)).toBeInTheDocument()
    expect(container.textContent).toContain('We asked ChatGPT to open your product page itself.')
  })

  it('quoted_price shows the price the probe actually quoted', () => {
    const { container } = renderIt(blockedReport({ probeOutcome: 'quoted_price', price: '$64.00' }))
    expect(container.textContent).toContain('it quoted $64.00')
  })

  it('quoted_price with no price never invents one', () => {
    const { container } = renderIt(blockedReport({ probeOutcome: 'quoted_price', price: null }))
    expect(container.textContent).toContain('it quoted a price')
    expect(container.textContent).not.toMatch(/it quoted (null|undefined|\$\s)/)
  })

  it('could_not_access says so — it corroborates the block', () => {
    const { container } = renderIt(blockedReport({ probeOutcome: 'could_not_access' }))
    expect(container.textContent).toContain("It couldn't access it either.")
    expect(container.textContent).toContain(FETCH_PROBE_EVIDENCE_COPY.could_not_access_note)
  })

  it('a store-root probe is named as the homepage, never as a product page', () => {
    const { container } = renderIt(blockedReport({ probeOutcome: 'quoted_price', price: '$1', kind: 'store_root' }))
    expect(container.textContent).toContain('We asked ChatGPT to open your homepage itself.')
  })

  it('no probe means no fact block at all — never an empty one', () => {
    renderIt(blockedReport({ probeOutcome: null }))
    expect(screen.queryByText(FETCH_PROBE_EVIDENCE_COPY.label)).not.toBeInTheDocument()
  })

  it('the claim appears exactly once per report', () => {
    const { container } = renderIt(blockedReport({ probeOutcome: 'quoted_price', price: '$64.00' }))
    expect(container.textContent.split('We asked ChatGPT to open').length - 1).toBe(1)
  })
})

// ─── the accessibility tile ────────────────────────────────────────────

describe('blocked run — the accessibility headline', () => {
  it.each(PROBE_OUTCOMES)('%s: replaces "Couldn\'t be measured this run"', (probeOutcome) => {
    const { container } = renderIt(blockedReport({ probeOutcome, price: '$64.00' }))

    expect(container.textContent).toContain(BLOCKED_ACCESSIBILITY_HEADLINE[probeOutcome])
  })

  it('without a probe the tile keeps the honest generic headline', () => {
    const { container } = renderIt(blockedReport({ probeOutcome: null }))
    for (const headline of Object.values(BLOCKED_ACCESSIBILITY_HEADLINE)) {
      expect(container.textContent).not.toContain(headline)
    }
    expect(container.textContent).toContain("Couldn't be measured this run")
  })

  it('a probe on a run that is NOT blocked never rewrites the headline', () => {
    const report = blockedReport({ probeOutcome: 'quoted_price', price: '$64.00' })
    report.scan_status = 'failed'
    report.scan.degraded_reason = 'no_product_pages_found'

    const { container } = renderIt(report)
    for (const headline of Object.values(BLOCKED_ACCESSIBILITY_HEADLINE)) {
      expect(container.textContent).not.toContain(headline)
    }
  })
})

// ─── evidence, never points ────────────────────────────────────────────

describe('blocked run — the probe and the vendor change no score', () => {
  it.each([
    ['no probe, no vendor', { probeOutcome: null, vendor: null }],
    ['quoted_price, cloudflare', { probeOutcome: 'quoted_price', price: '$64.00', vendor: 'cloudflare' }],
    ['could_not_access, akamai', { probeOutcome: 'could_not_access', vendor: 'akamai' }],
    ['opened_no_price, no vendor', { probeOutcome: 'opened_no_price', vendor: null }],
  ])('%s: the same numbers render', (_label, opts) => {
    const { container } = renderIt(blockedReport(opts))

    // Visibility is the one pillar a wall can't touch, and it reads the
    // same in every combination above.
    expect(container.textContent).toContain('Visibility35/40')
    // Accessibility and True Value stay unmeasured — the probe proved
    // something about the wall, not about this store's markup.
    expect(container.textContent).toContain('Accessibility0/0')
    expect(container.textContent).toContain('True Value0/0')
    // The hero still withholds a composite rather than inventing one
    // out of 100 for a run that read nothing on-site.
    expect(container.textContent).toContain('35/40 measurable')
  })
})
