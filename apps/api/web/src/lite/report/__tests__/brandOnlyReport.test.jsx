/**
 * Non-commerce sites get a non-commerce report.
 *
 * Emcube, Marketlytics and Wealthsimple were all correctly typed
 * brand_only by apps/pipeline/scan/site_typing.py, scored 10-22, and
 * were then rendered as failing STORES: three pillars, a composite out
 * of 100, a "Not agent-ready" chip and a ranked list of storefront
 * fixes for a site with no storefront. The typing was right — the
 * report just never saw it, because site_type was not on the row.
 *
 * Two things this variant must be careful about, and both have tests
 * here: it must never fire on a site whose discovery merely FAILED
 * (commerce_discovery_failure is a different, opposite claim), and it
 * must never change a score — the scorer's numbers are the scorer's.
 */
import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import { LiteFullReportV4 } from '../LiteFullReportV4.jsx'
import { isBrandOnlyReport } from '../reportDerive.js'
import { BRAND_ONLY_COPY } from '../reportContent.js'

function brandOnlyReport({ siteType = 'brand_only' } = {}) {
  return {
    status: 'complete',
    locked: false,
    overall: [
      { name: 'Marketlytics', role: 'primary', metrics: { som: 18, mention_rate: 21 } },
      { name: 'Amplitude', role: 'competitor', metrics: { som: 51, mention_rate: 62 } },
    ],
    visibility_breakdown: {
      mention_rate: [{ entity: 'Marketlytics', is_primary: true, mentioned_queries: 5, total_queries: 24, rate_pct: 21 }],
      share_of_mentions: [
        { entity: 'Marketlytics', is_primary: true, mentions: 4, share_pct: 18 },
        { entity: 'Amplitude', is_primary: false, mentions: 12, share_pct: 51 },
      ],
      totals: { total_mentions: 16, total_queries: 24 },
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
        sitemaps_read: 1, product_urls_found: 0, tiers_attempted: ['sitemap'],
        robots_ok: true, homepage_fetched: true, product_pages_fetched: 0,
      },
    },
    composite: 16,
    pillars: {
      visibility: {
        score: 30, max: 100,
        dimensions: [
          { code: 'share_of_mentions', name: 'Share of Mentions', earned: 7, max: 25, na: false, evidence: [] },
          { code: 'recommendation_strength', name: 'Recommendation Strength', earned: 5, max: 15, na: false, evidence: [] },
        ],
      },
      accessibility: {
        score: 30, max: 100,
        dimensions: [
          { code: 'agent_access', name: 'Agent Access', earned: 5, max: 6, na: false, blocked: false, evidence: [], checks: [{ code: 'robots', label: 'robots.txt', state: 'pass' }] },
          { code: 'catalog_context', name: 'Catalog & Context', earned: 0, max: 8, na: false, blocked: false, evidence: [], checks: [{ code: 'markup', label: 'complete markup', state: 'fail' }] },
          { code: 'protocol_feed', name: 'Protocol & Feed Presence', earned: 0, max: 6, na: true, blocked: false, evidence: [], checks: [{ code: 'llms', label: 'llms.txt', state: 'na' }] },
        ],
      },
      true_value: {
        score: 0, max: 100,
        dimensions: [
          {
            code: 'price_truth', name: 'Price Truth', earned: 0, max: 12, na: false, blocked: false,
            seen: { earned: 0, max: 5, na: false }, said: { earned: 0, max: 7, na: false },
            checks: [{ code: 'price_in_code', label: 'price in your code', state: 'fail' }],
          },
          {
            code: 'value_protocols', name: 'Value Protocols', earned: 0, max: 7, na: false, blocked: false,
            seen: { earned: 0, max: 7, na: false }, said: null,
            checks: [{ code: 'ucp', label: 'UCP discounts', state: 'fail' }],
          },
        ],
      },
      composite: 16,
      member_value_na: false,
      state: 'scored',
      tv_pct: 0,
      fixes: {
        visible: [
          { code: 'catalog_context', name: 'Add product markup', fix_human: 'Publish Product markup on your product pages', impact: 8, fix_owner: 'ENG' },
        ],
        remaining_count: 3,
      },
      verdict: null,
      gap_areas_total: 4,
      gap_areas_parleo_fixes: 1,
      parleo_fixable_points: 7,
      exposure_reasons: [],
    },
  }
}

function renderIt(report) {
  return render(<LiteFullReportV4 report={report} token="tok-brand" />)
}

// ─── the predicate ─────────────────────────────────────────────────────

describe('isBrandOnlyReport — reads the recorded type, never infers one', () => {
  it('is true only for brand_only', () => {
    expect(isBrandOnlyReport(brandOnlyReport())).toBe(true)
  })

  it.each(['commerce_normal', 'commerce_discovery_failure'])('%s is not brand-only', (siteType) => {
    expect(isBrandOnlyReport(brandOnlyReport({ siteType }))).toBe(false)
  })

  it('a missing site_type is not brand-only — nothing was established', () => {
    const report = brandOnlyReport()
    delete report.scan.site_type
    expect(isBrandOnlyReport(report)).toBe(false)
    expect(isBrandOnlyReport({})).toBe(false)
    expect(isBrandOnlyReport(null)).toBe(false)
  })

  it('a low score alone never makes a report brand-only', () => {
    // The inference site_typing.py exists to replace: a commerce site
    // whose discovery failed scores just as low and is NOT a non-store.
    const report = brandOnlyReport({ siteType: 'commerce_discovery_failure' })
    report.composite = 10
    expect(isBrandOnlyReport(report)).toBe(false)
  })
})

// ─── the hero ──────────────────────────────────────────────────────────

describe('brand-only report — the hero leads with Visibility', () => {
  it('shows the visibility score in place of a composite out of 100', () => {
    const { container } = renderIt(brandOnlyReport())
    expect(container.textContent).toContain(`/40 ${BRAND_ONLY_COPY.scoreLabel}`)
  })

  it('explains in one line why the store-side pillars are blank', () => {
    renderIt(brandOnlyReport())
    expect(screen.getAllByText(BRAND_ONLY_COPY.heroNote).length).toBeGreaterThan(0)
  })

  it('the status chip does not read as failure, in any of the three headers', () => {
    const { container } = renderIt(brandOnlyReport())
    // The hero, the desktop rail and the phone summary each carry a
    // verdict chip — all three take the variant, or the page
    // contradicts itself.
    expect(screen.getAllByText(BRAND_ONLY_COPY.statusChip).length).toBe(3)
    expect(container.textContent).not.toContain('Not agent-ready')
    expect(container.textContent).not.toContain('/100')
  })

  it('a commerce report keeps the composite and the ready/not-ready chip', () => {
    const { container } = renderIt(brandOnlyReport({ siteType: 'commerce_normal' }))
    expect(container.textContent).not.toContain(BRAND_ONLY_COPY.statusChip)
    expect(container.textContent).toContain('Not agent-ready')
  })
})

// ─── accessibility ─────────────────────────────────────────────────────

describe('brand-only report — the accessibility rows that apply', () => {
  it('shows Agent Access and Protocol & Feed, and not Catalog & Context', () => {
    const { container } = renderIt(brandOnlyReport())
    expect(container.textContent).toContain('Agent Access')
    expect(container.textContent).toContain('Protocol & Feed Presence')
    expect(container.textContent).not.toContain('Catalog & Context')
  })

  it('says why Catalog & Context is absent rather than silently dropping it', () => {
    renderIt(brandOnlyReport())
    expect(screen.getByText(BRAND_ONLY_COPY.accessibilityNote)).toBeInTheDocument()
  })

  it('a commerce report still shows all three rows', () => {
    const { container } = renderIt(brandOnlyReport({ siteType: 'commerce_normal' }))
    expect(container.textContent).toContain('Catalog & Context')
    expect(container.textContent).not.toContain(BRAND_ONLY_COPY.accessibilityNote)
  })
})

// ─── true value ────────────────────────────────────────────────────────

describe('brand-only report — True Value is not applicable', () => {
  it('reads as not applicable, not as a failing pillar', () => {
    const { container } = renderIt(brandOnlyReport())
    expect(screen.getByText(BRAND_ONLY_COPY.trueValueHeading)).toBeInTheDocument()
    expect(container.textContent).toContain(BRAND_ONLY_COPY.trueValueBody)
  })

  it('points to the fix a non-store site actually has: a storefront URL', () => {
    const { container } = renderIt(brandOnlyReport())
    expect(container.textContent).toMatch(/storefront/i)
  })

  it('does not render the per-dimension breakdown of zeros', () => {
    const { container } = renderIt(brandOnlyReport())
    expect(container.textContent).not.toContain('YOUR PAGE, AS PARSED')
    expect(container.textContent).not.toContain('WHAT AGENTS COULD READ OF YOUR VALUE')
  })

  it('a commerce report keeps its True Value breakdown', () => {
    const { container } = renderIt(brandOnlyReport({ siteType: 'commerce_normal' }))
    expect(container.textContent).not.toContain(BRAND_ONLY_COPY.trueValueHeading)
  })
})

// ─── presentation only ─────────────────────────────────────────────────

describe('brand-only report — no score moves', () => {
  it('Visibility reports exactly the numbers the scorer produced', () => {
    const { container } = renderIt(brandOnlyReport())
    // 7 + 5 earned against a 25 + 15 max, unchanged by the variant.
    expect(container.textContent).toContain('Visibility12/40')
  })

  it('the variant is driven only by site_type, with identical pillars', () => {
    const brandOnly = renderIt(brandOnlyReport())
    const commerce = renderIt(brandOnlyReport({ siteType: 'commerce_normal' }))

    for (const container of [brandOnly.container, commerce.container]) {
      expect(container.textContent).toContain('Visibility12/40')
    }
  })
})
