/**
 * Manufacturer sites (Clorox, request 146): real product pages with
 * Product markup and GTINs, no Offer anywhere, because the brand sells
 * through retailers. Its zero price truth and deal citability are
 * correct scores; the report must stop asking it to publish prices it
 * can't publish.
 *
 * Presentation only, like the brand-only variant — and unlike it, the
 * composite, hero and rail are untouched. The byte-for-byte test below
 * is the guard on that: the same report typed commerce_normal and typed
 * manufacturer must render an identical score hero and rail.
 */
import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import { LiteFullReportV4 } from '../LiteFullReportV4.jsx'
import { isManufacturerReport } from '../reportDerive.js'
import { MANUFACTURER_COPY } from '../reportContent.js'

const PRICE_TRUTH_FIX = 'Show your prices in a format agents can read directly from the page, and make sure it matches what shoppers actually see.'
const DEAL_FIX = 'Make your current deals and bundles readable to agents, with clear terms and an end date.'
const PROTOCOL_FIX = 'Publish a protocol manifest that declares which agent-checkout capabilities your store offers.'

function cloroxReport({ siteType = 'manufacturer' } = {}) {
  return {
    status: 'complete',
    locked: false,
    overall: [
      { name: 'Clorox', role: 'primary', metrics: { som: 38, mention_rate: 55 } },
      { name: 'Lysol', role: 'competitor', metrics: { som: 44, mention_rate: 61 } },
    ],
    visibility_breakdown: {
      mention_rate: [{ entity: 'Clorox', is_primary: true, mentioned_queries: 13, total_queries: 24, rate_pct: 55 }],
      share_of_mentions: [
        { entity: 'Clorox', is_primary: true, mentions: 11, share_pct: 38 },
        { entity: 'Lysol', is_primary: false, mentions: 13, share_pct: 44 },
      ],
      totals: { total_mentions: 29, total_queries: 24 },
    },
    offers: null,
    product_image_url: null,
    product_name: null,
    scan_status: 'complete',
    scan: {
      status: 'complete',
      degraded_reason: null,
      site_type: siteType,
      edge_vendor: null,
      discovery_trace: {
        sitemaps_read: 2, product_urls_found: 140, tiers_attempted: ['sitemap'],
        robots_ok: true, homepage_fetched: true, product_pages_fetched: 2,
      },
    },
    composite: 41,
    pillars: {
      visibility: {
        score: 60, max: 100,
        dimensions: [
          { code: 'share_of_mentions', name: 'Share of Mentions', earned: 15, max: 25, na: false, evidence: [] },
          { code: 'recommendation_strength', name: 'Recommendation Strength', earned: 9, max: 15, na: false, evidence: [] },
        ],
      },
      accessibility: {
        score: 70, max: 100,
        dimensions: [
          { code: 'agent_access', name: 'Agent Access', earned: 6, max: 6, na: false, blocked: false, evidence: [], checks: [{ code: 'robots', label: 'robots.txt', state: 'pass' }] },
          { code: 'catalog_context', name: 'Catalog & Context', earned: 5, max: 8, na: false, blocked: false, evidence: [], checks: [{ code: 'markup', label: 'complete markup', state: 'fail' }] },
          { code: 'protocol_feed', name: 'Protocol & Feed Presence', earned: 0, max: 6, na: false, blocked: false, evidence: [], checks: [{ code: 'llms', label: 'llms.txt', state: 'fail' }] },
        ],
      },
      true_value: {
        score: 12, max: 100,
        dimensions: [
          {
            code: 'price_truth', name: 'Price Truth', earned: 3, max: 12, na: false, blocked: false,
            seen: { earned: 0, max: 5, na: false }, said: { earned: 3, max: 7, na: false },
            checks: [{ code: 'price_in_code', label: 'price in your code', state: 'fail' }],
          },
          {
            code: 'member_value', name: 'Member Value', earned: 0, max: 12, na: false, blocked: false,
            seen: { earned: 0, max: 5, na: false }, said: { earned: 0, max: 7, na: false },
            checks: [{ code: 'member_price', label: 'member price in code', state: 'fail' }],
          },
          {
            code: 'deal_citability', name: 'Deal Citability', earned: 1, max: 10, na: false, blocked: false,
            seen: { earned: 0, max: 4, na: false }, said: { earned: 1, max: 6, na: false },
            checks: [{ code: 'deal_concrete', label: 'concrete deal', state: 'fail' }],
          },
          {
            code: 'value_protocols', name: 'Value Protocols', earned: 0, max: 7, na: false, blocked: false,
            seen: { earned: 0, max: 7, na: false }, said: null,
            checks: [{ code: 'ucp', label: 'UCP discounts', state: 'fail' }],
          },
        ],
      },
      composite: 41,
      member_value_na: false,
      state: 'scored',
      tv_pct: 10,
      fixes: {
        visible: [
          { code: 'price_truth', name: 'Publish machine-readable prices', fix_human: PRICE_TRUTH_FIX, impact: 9, fix_owner: 'ENG' },
          { code: 'value_protocols', name: 'Declare your value protocols', fix_human: PROTOCOL_FIX, impact: 7, fix_owner: 'TRUESYNC' },
          { code: 'deal_citability', name: 'Encode your deals', fix_human: DEAL_FIX, impact: 6, fix_owner: 'TRUESYNC' },
        ],
        remaining_count: 2,
      },
      verdict: null,
      gap_areas_total: 4,
      gap_areas_parleo_fixes: 2,
      parleo_fixable_points: 13,
      exposure_reasons: [],
    },
  }
}

function renderIt(report) {
  return render(<LiteFullReportV4 report={report} token="tok-mfr" />)
}

describe('isManufacturerReport — reads the recorded type, never infers one', () => {
  it('is true only for manufacturer', () => {
    expect(isManufacturerReport(cloroxReport())).toBe(true)
  })

  it.each(['commerce_normal', 'commerce_discovery_failure', 'brand_only'])('%s is not a manufacturer', (siteType) => {
    expect(isManufacturerReport(cloroxReport({ siteType }))).toBe(false)
  })

  it('a missing site_type is not a manufacturer', () => {
    const report = cloroxReport()
    delete report.scan.site_type
    expect(isManufacturerReport(report)).toBe(false)
    expect(isManufacturerReport(null)).toBe(false)
  })
})

describe('manufacturer report — True Value rows', () => {
  it('renders price truth, member value and deal citability as not applicable, with the reason', () => {
    const { container } = renderIt(cloroxReport())
    for (const code of ['price_truth', 'member_value', 'deal_citability']) {
      const row = container.querySelector(`[data-manufacturer-na="${code}"]`)
      expect(row).not.toBeNull()
      expect(row.textContent).toContain('N/A')
      expect(row.textContent).toContain(MANUFACTURER_COPY.dimensionNote)
    }
    expect(container.textContent).toContain(MANUFACTURER_COPY.trueValueNote)
  })

  it('leaves Value Protocols as a normal, scored row', () => {
    const { container } = renderIt(cloroxReport())
    expect(container.querySelector('[data-manufacturer-na="value_protocols"]')).toBeNull()
    expect(screen.getByText('Value Protocols')).toBeInTheDocument()
  })

  it('a commerce_normal report renders none of it', () => {
    const { container } = renderIt(cloroxReport({ siteType: 'commerce_normal' }))
    expect(container.querySelector('[data-manufacturer-na]')).toBeNull()
    expect(container.textContent).not.toContain(MANUFACTURER_COPY.dimensionNote)
  })
})

describe('manufacturer report — ranked fixes', () => {
  it('replaces the price and deal fix text with retailer-feed guidance', () => {
    const { container } = renderIt(cloroxReport())
    expect(container.textContent).not.toContain(PRICE_TRUTH_FIX)
    expect(container.textContent).not.toContain(DEAL_FIX)
    expect(screen.getAllByText(MANUFACTURER_COPY.fixHuman)).toHaveLength(2)
  })

  it('leaves every other fix, and every fix\'s points, exactly as ranked', () => {
    const mfr = renderIt(cloroxReport())
    expect(mfr.container.textContent).toContain(PROTOCOL_FIX)
    const mfrPoints = [...mfr.container.querySelectorAll('.lite-fixrow-points')].map((el) => el.textContent)
    mfr.unmount()

    const normal = renderIt(cloroxReport({ siteType: 'commerce_normal' }))
    const normalPoints = [...normal.container.querySelectorAll('.lite-fixrow-points')].map((el) => el.textContent)
    expect(mfrPoints).toEqual(normalPoints)
  })
})

describe('manufacturer report — the composite stays exactly as scored', () => {
  // React's useId values (":r87:") differ between any two mounts; they
  // are the only thing allowed to.
  const stable = (html) => html.replace(/:r[0-9a-z]+:/g, ':id:')

  it('renders a byte-identical score hero and rail to the same report typed commerce_normal', () => {
    const mfr = renderIt(cloroxReport())
    const mfrHero = stable(mfr.container.querySelector('#score').outerHTML)
    const mfrRail = stable(mfr.container.querySelector('.lite-report-rail').outerHTML)
    mfr.unmount()

    const normal = renderIt(cloroxReport({ siteType: 'commerce_normal' }))
    expect(stable(normal.container.querySelector('#score').outerHTML)).toBe(mfrHero)
    expect(stable(normal.container.querySelector('.lite-report-rail').outerHTML)).toBe(mfrRail)
    expect(mfrHero).toContain('41')
  })

  it('keeps the True Value pillar score on the header', () => {
    const { container } = renderIt(cloroxReport())
    const header = container.querySelector('.lite-tv-header-score')
    expect(header.textContent).not.toContain('N/A')
  })
})
