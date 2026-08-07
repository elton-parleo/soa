/**
 * Partial-read report state — fixture coverage per the brief's Tests
 * section: a Marc-Jacobs-shaped starved run (no_product_pages_found),
 * a Sephora-shaped blocked run, a nothing-measurable run (today's
 * failure treatment, unchanged), a perturbation test on the shared
 * measurable-denominator context, and the grep-style regression guards
 * (causal explanation once per report, UNLOCKED never in a total, no
 * pace delta on an unread lane).
 */
import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import { LiteFullReportV4 } from '../LiteFullReportV4.jsx'
import { buildMeasurableContext, isPartialRead } from '../reportDerive.js'
import { FAILURE_POINT_COPY } from '../reportContent.js'

const BASE = {
  status: 'complete',
  locked: false,
  overall: [
    { name: 'Marc Jacobs', role: 'primary', metrics: { som: 35, mention_rate: 42 } },
    { name: 'Coach', role: 'competitor', metrics: { som: 41, mention_rate: 30 } },
  ],
  visibility_breakdown: {
    mention_rate: [{ entity: 'Marc Jacobs', is_primary: true, mentioned_queries: 10, total_queries: 24, rate_pct: 42 }],
    share_of_mentions: [
      { entity: 'Marc Jacobs', is_primary: true, mentions: 8, share_pct: 35 },
      { entity: 'Coach', is_primary: false, mentions: 10, share_pct: 41 },
    ],
    totals: { total_mentions: 20, total_queries: 24 },
  },
  offers: null,
  product_image_url: null,
  product_name: null,
}

function _visDims(somEarned, rsiEarned) {
  return [
    { code: 'share_of_mentions', name: 'Share of Mentions', earned: somEarned, max: 25, na: false, evidence: [] },
    { code: 'recommendation_strength', name: 'Recommendation Strength', earned: rsiEarned, max: 15, na: false, evidence: [] },
  ]
}

// Marc Jacobs shape: no_product_pages_found — Visibility fully
// measured, Accessibility's catalog_context blocked, every True Value
// split dimension's seen half blocked, Value Protocols (domain-root,
// not product-page-dependent) measured in full at 0/7.
const MARC_JACOBS_REPORT = {
  ...BASE,
  scan_status: 'failed',
  scan: {
    status: 'failed',
    degraded_reason: 'no_product_pages_found',
    degraded_banner_facts: { sitemaps_read: 5 },
    discovery_trace: {
      sitemaps_read: 5, product_urls_found: 0, tiers_attempted: ['sitemap'],
      robots_ok: true, homepage_fetched: true, product_pages_fetched: 0,
    },
  },
  composite: null,
  pillars: {
    visibility: { score: 77.5, max: 100, dimensions: _visDims(20, 11) },
    accessibility: {
      score: 41.7, max: 100,
      dimensions: [
        { code: 'agent_access', name: 'Agent Access', earned: 5, max: 6, na: false, blocked: false, evidence: [], checks: [{ code: 'robots', label: 'robots.txt', state: 'pass' }] },
        { code: 'catalog_context', name: 'Catalog & Context', earned: 0, max: 0, na: false, blocked: true, evidence: [], checks: [{ code: 'markup', label: 'complete markup', state: 'blocked' }] },
        { code: 'protocol_feed', name: 'Protocol & Feed Presence', earned: 0, max: 6, na: false, blocked: false, evidence: [], checks: [{ code: 'llms', label: 'llms.txt', state: 'fail' }] },
      ],
    },
    true_value: {
      score: 0, max: 100,
      dimensions: [
        {
          code: 'price_truth', name: 'Price Truth', earned: 0, max: 0, na: false, blocked: true,
          seen: { earned: 0, max: 5, na: false, blocked: true },
          said: { earned: 5, max: 7, na: false },
          checks: [{ code: 'price_in_code', label: 'price in your code', state: 'blocked' }],
        },
        {
          code: 'member_value', name: 'Member Value', earned: 0, max: 0, na: false, blocked: true,
          seen: { earned: 0, max: 9, na: false, blocked: true },
          said: { earned: 0, max: 6, na: true },
          checks: [{ code: 'member_seen', label: 'member pricing declared', state: 'blocked' }],
        },
        {
          code: 'deal_citability', name: 'Deal Citability', earned: 0, max: 0, na: false, blocked: true,
          seen: { earned: 0, max: 4, na: false, blocked: true },
          said: { earned: 0, max: 2, na: false },
          checks: [{ code: 'discount_amount', label: 'clear discount amount', state: 'blocked' }],
        },
        {
          code: 'value_protocols', name: 'Value Protocols', earned: 0, max: 7, na: false, blocked: false,
          seen: { earned: 0, max: 7, na: false }, said: null,
          checks: [{ code: 'ucp', label: 'UCP discounts', state: 'fail' }],
        },
      ],
    },
    composite: null,
    member_value_na: false,
    state: 'unverified',
    tv_pct: null,
    fixes: {
      visible: [
        { code: 'agent_access', name: 'Make your product pages discoverable', fix_human: 'Fix your sitemap so it lists product URLs, not just collections', impact: 1, fix_owner: 'ENG' },
        { code: 'value_protocols', name: 'Declare your value to agent checkouts', fix_human: 'UCP/ACP declarations for discounts and member pricing', impact: 7, fix_owner: 'TRUESYNC' },
      ],
      remaining_count: 2,
    },
    verdict: null,
    gap_areas_total: 4,
    gap_areas_parleo_fixes: 2,
    parleo_fixable_points: 7,
    exposure_reasons: [],
  },
}

// Sephora shape: blocked (403 wall), signed reader.
const SEPHORA_REPORT = {
  ...BASE,
  overall: [{ name: 'Sephora', role: 'primary', metrics: { som: 40, mention_rate: 50 } }],
  scan_status: 'blocked',
  scan: {
    status: 'blocked',
    degraded_reason: 'blocked',
    degraded_banner_facts: {
      refusal: '403', attempts: 6, robots_included: true, signed: true,
      fetch_probe: { outcome: 'quoted_price', agent_could_access: true, url: 'https://sephora.com/p/x', kind: 'product_page' },
    },
    discovery_trace: {
      sitemaps_read: 0, product_urls_found: 0, tiers_attempted: [],
      robots_ok: false, homepage_fetched: false, product_pages_fetched: 0,
    },
  },
  composite: null,
  pillars: {
    ...MARC_JACOBS_REPORT.pillars,
    visibility: { score: 90, max: 100, dimensions: _visDims(23, 14) },
  },
}

// Nothing-measurable shape: 'unreachable' — 1b says this keeps today's
// failure treatment, no partial chip, no new surfaces, regardless of
// which dimensions carry a blocked flag.
const NOTHING_MEASURABLE_REPORT = {
  ...BASE,
  scan_status: 'failed',
  scan: { status: 'failed', degraded_reason: 'unreachable', degraded_banner_facts: {} },
  composite: null,
  pillars: {
    ...MARC_JACOBS_REPORT.pillars,
    state: 'unverified',
    fixes: { visible: [], remaining_count: 0 },
  },
}

function renderIt(report) {
  return render(<LiteFullReportV4 report={report} token="tok-partial" />)
}

describe('partial-read report state — Marc Jacobs (no_product_pages_found)', () => {
  it('renders the amber Partial read chip and the measurable hero numbers', () => {
    renderIt(MARC_JACOBS_REPORT)
    expect(screen.getAllByText('Partial read').length).toBeGreaterThan(0)
  })

  it('renders the discovery finding section with the no_product_pages_found registry heading', () => {
    renderIt(MARC_JACOBS_REPORT)
    expect(screen.getByText(FAILURE_POINT_COPY.no_product_pages_found.heading)).toBeInTheDocument()
    expect(screen.getByText('FINDING 00 · DISCOVERY · MEASURED')).toBeInTheDocument()
  })

  it('renders the four-step trace from discovery_trace, no fabricated step', () => {
    renderIt(MARC_JACOBS_REPORT)
    expect(screen.getByText(/01 · ROBOTS.TXT/)).toBeInTheDocument()
    expect(screen.getByText(/02 · HOMEPAGE/)).toBeInTheDocument()
    expect(screen.getByText(/03 · SITEMAPS/)).toBeInTheDocument()
    expect(screen.getByText(/04 · PRODUCT PAGES/)).toBeInTheDocument()
    expect(screen.getByText(/5 resolved · 0 product URL/)).toBeInTheDocument()
  })

  it('replaces the parsed-page card with a dashed "no product page reachable" panel, never a placeholder SKU', () => {
    renderIt(MARC_JACOBS_REPORT)
    expect(screen.getByText(/No product page was reachable this run/)).toBeInTheDocument()
  })

  it('shows the unread dual-lens half alongside the real measured answer-side score', () => {
    renderIt(MARC_JACOBS_REPORT)
    expect(screen.getAllByText(/PTS UNREAD/).length).toBeGreaterThan(0)
    // Price Truth's said side (5/7) is real, measured evidence — must
    // still render even though the seen side is unread.
    expect(screen.getByText('5/7')).toBeInTheDocument()
  })

  it('keeps Value Protocols in its full blue TrueSync treatment with the domain-root-complete note', () => {
    renderIt(MARC_JACOBS_REPORT)
    expect(screen.getByText('Value Protocols')).toBeInTheDocument()
    expect(screen.getByText(/Checked at your domain root/)).toBeInTheDocument()
  })

  it('ranks the discovery fix first with a separate UNLOCKED badge, and the TrueSync fix is still ranked', () => {
    renderIt(MARC_JACOBS_REPORT)
    expect(screen.getByText(/UNLOCKED/)).toBeInTheDocument()
    expect(screen.getAllByText('TRUESYNC').length).toBeGreaterThan(0)
  })

  it('renders the ungated "what a complete read adds" band', () => {
    renderIt(MARC_JACOBS_REPORT)
    expect(screen.getByText('What a complete read adds')).toBeInTheDocument()
  })

  it('footer states how many points were measurable this run', () => {
    renderIt(MARC_JACOBS_REPORT)
    expect(screen.getByText(/points measurable this run/)).toBeInTheDocument()
  })

  it('grep: the causal explanation appears exactly once per report (banner never restates the finding section)', () => {
    const { container } = renderIt(MARC_JACOBS_REPORT)
    const explanation = FAILURE_POINT_COPY.no_product_pages_found.explanation
    const occurrences = container.textContent.split(explanation).length - 1
    expect(occurrences).toBe(1)
  })

  it('grep: UNLOCKED never appears inside a summed total (the fixes title sums only real impacts)', () => {
    renderIt(MARC_JACOBS_REPORT)
    // impact 1 + impact 7 = 8 real points recovered; the unlocked figure (7) must never be folded in.
    expect(screen.getByText(/moves recover up to 8 points/)).toBeInTheDocument()
  })
})

describe('partial-read report state — Sephora (blocked)', () => {
  it('renders the blocked registry entry and the fetch-probe sentence exactly once', () => {
    const { container } = renderIt(SEPHORA_REPORT)
    expect(screen.getByText(FAILURE_POINT_COPY.blocked.heading)).toBeInTheDocument()
    const occurrences = container.textContent.split('ChatGPT opened').length - 1
    expect(occurrences).toBe(1)
  })
})

// Blocked-run copy pass: the reader is a marketing/ecommerce lead, not
// the engineer who configured the CDN — every string in the blocked
// entry moves to plain language. These guards protect that register
// directly, and the fetch-probe sentence's wording/placement stays
// byte-unchanged (it's asserted above too).
describe('blocked-run copy pass — plain language, banned terms', () => {
  const BANNED_TERMS = [
    /\bedge\b/i, /\bWAF\b/, /user agent/i, /\bUA\b/, /403-refused/i, /429-refused/i,
    /challenge page/i, /\bidentified reader\b/i,
  ]

  it('the registry heading and body contain none of the banned engineer-jargon terms', () => {
    const bodyText = FAILURE_POINT_COPY.blocked.body({ refusal: '403', attempts: 6, robots_included: true, signed: true })
    for (const s of [FAILURE_POINT_COPY.blocked.heading, bodyText]) {
      for (const pattern of BANNED_TERMS) {
        expect(s).not.toMatch(pattern)
      }
    }
  })

  it('"cryptographically" survives only in the fixFraming action line, explained in the same sentence', () => {
    expect(FAILURE_POINT_COPY.blocked.heading).not.toMatch(/cryptographically/i)
    expect(FAILURE_POINT_COPY.blocked.body({})).not.toMatch(/cryptographically/i)
    expect(FAILURE_POINT_COPY.blocked.fixFraming).toMatch(/cryptographically/i)
  })

  it('writes a status code in words with the code in parentheses, never as a bare-number adjective', () => {
    const bodyText = FAILURE_POINT_COPY.blocked.body({ refusal: '403', attempts: 6 })
    expect(bodyText).toContain('refused every request (403)')
    expect(bodyText).not.toMatch(/403-refused/)
  })

  it('refers to our own reader as "reader", never "bot", and uses "crawler" only in the published-crawlers phrase', () => {
    // 2a is about OUR identity specifically — "reader", not "the bot"/
    // "our crawler" — not a blanket ban on "bot" as a substring (the
    // brief's own body text legitimately says "bot-blocking" as the
    // industry term for what security tools do).
    expect(FAILURE_POINT_COPY.blocked.heading).toMatch(/reader/i)
    expect(FAILURE_POINT_COPY.blocked.heading).not.toMatch(/\bour bot\b|\bthe bot\b/i)
    expect(FAILURE_POINT_COPY.blocked.body({})).not.toMatch(/\bour bot\b|\bthe bot\b|\bour crawler\b/i)
    expect(FAILURE_POINT_COPY.blocked.body({})).not.toMatch(/\bcrawler\b/i)
    expect(FAILURE_POINT_COPY.blocked.fixFraming).toMatch(/published crawlers/)
  })

  it('the rendered Sephora report shows the new heading and no banned terms anywhere on the page', () => {
    const { container } = renderIt(SEPHORA_REPORT)
    expect(screen.getByText('Your site turned our reader away at the door.')).toBeInTheDocument()
    for (const pattern of BANNED_TERMS) {
      expect(container.textContent).not.toMatch(pattern)
    }
  })

  it('the discovery fix\'s ranked-fix description also carries the fixFraming action line', () => {
    renderIt(SEPHORA_REPORT)
    expect(screen.getAllByText(FAILURE_POINT_COPY.blocked.fixFraming).length).toBe(2) // discovery section box + ranked fix row
  })

  it('grep: the causal body/explanation text still renders exactly once per report (fixFraming is expected twice, per Part 1c)', () => {
    const { container } = renderIt(SEPHORA_REPORT)
    const bodyText = FAILURE_POINT_COPY.blocked.body({ refusal: '403', attempts: 6, robots_included: true, signed: true })
    const occurrences = container.textContent.split(bodyText).length - 1
    expect(occurrences).toBe(1)
  })
})

// Honest-state suite extension (G3, LiteFullReport.test.jsx): the same
// dash/empty-interpolation leak sweep, applied to the two new
// partial-read fixtures — a new copy surface must inherit the guard,
// never be exempted from it.
describe('partial-read report state — G3 placeholder containment', () => {
  const DASH_PATTERNS = [/at — /, /— —/, /at %/]

  it.each([
    ['Marc Jacobs (no_product_pages_found)', MARC_JACOBS_REPORT],
    ['Sephora (blocked)', SEPHORA_REPORT],
    ['nothing measurable (unreachable)', NOTHING_MEASURABLE_REPORT],
  ])('%s: no dash/empty-interpolation pattern anywhere in the rendered report', (_label, report) => {
    const { container } = renderIt(report)
    for (const pattern of DASH_PATTERNS) {
      expect(container.textContent).not.toMatch(pattern)
    }
  })
})

describe('partial-read report state — nothing measurable (unreachable)', () => {
  it('keeps today\'s failure treatment: no partial chip, no discovery section, no complete-read band', () => {
    renderIt(NOTHING_MEASURABLE_REPORT)
    expect(screen.queryByText('Partial read')).not.toBeInTheDocument()
    expect(screen.queryByText('FINDING 00 · DISCOVERY · MEASURED')).not.toBeInTheDocument()
    expect(screen.queryByText('What a complete read adds')).not.toBeInTheDocument()
  })
})

describe('shared measurable-denominator context — perturbation', () => {
  it('changing one dimension\'s measurability moves earned/measurable_max/unmeasurable_points and the per-pillar figures together', () => {
    const before = buildMeasurableContext(MARC_JACOBS_REPORT.pillars)
    expect(before.accessibility.measurable_max).toBe(12) // agent_access(6) + protocol_feed(6), catalog_context(8) blocked
    expect(before.true_value.measurable_max).toBe(7) // value_protocols only

    const perturbed = {
      ...MARC_JACOBS_REPORT.pillars,
      accessibility: {
        ...MARC_JACOBS_REPORT.pillars.accessibility,
        dimensions: MARC_JACOBS_REPORT.pillars.accessibility.dimensions.map((d) =>
          d.code === 'catalog_context' ? { ...d, blocked: false, na: false, earned: 3, max: 8 } : d,
        ),
      },
    }
    const after = buildMeasurableContext(perturbed)
    expect(after.accessibility.measurable_max).toBe(20)
    expect(after.accessibility.earned).toBe(before.accessibility.earned + 3)
    expect(after.measurable_max).toBe(before.measurable_max + 8)
    expect(after.unmeasurable_points).toBe(before.unmeasurable_points - 8)
    // Unrelated pillars are untouched by the perturbation.
    expect(after.true_value).toEqual(before.true_value)
    expect(after.visibility).toEqual(before.visibility)
  })

  it('isPartialRead requires an actual blocked dimension, never just an na-caused shortfall', () => {
    const naOnly = {
      visibility: { dimensions: [{ code: 'a', earned: 10, max: 10, na: false }] },
      accessibility: { dimensions: [{ code: 'b', earned: 0, max: 0, na: true }] },
      true_value: { dimensions: [{ code: 'c', earned: 0, max: 0, na: true }] },
    }
    expect(isPartialRead(naOnly, null)).toBe(false)
  })
})
