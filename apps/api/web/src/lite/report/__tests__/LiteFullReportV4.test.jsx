import React from 'react'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import { LiteFullReportV4 } from '../LiteFullReportV4.jsx'
import { splitExposureDollars } from '../ExposureSection.jsx'
import { DIMENSIONS_BY_CODE } from '../../landing/scanDimensionsRegistry.js'
import { EDITORIAL_QUOTE } from '../reportContent.js'

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
  product_name: 'Mens Cruiser Shadow Blue Natural White Sole',
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
          checks: [
            { code: 'price_in_code', label: 'price in your code', state: 'pass' },
            { code: 'price_matches', label: 'code matches page price', state: 'pass' },
            { code: 'price_login', label: 'price hidden behind login', state: 'fail' },
            { code: 'price_said', label: 'quoted in 0 of 7 answers that named you', state: 'fail' },
          ],
        },
        {
          code: 'member_value', name: 'Member Value', earned: 0, max: 15, na: true,
          seen: { earned: 0, max: 9, na: true }, said: { earned: 0, max: 6, na: true },
        },
        {
          code: 'deal_citability', name: 'Deal Citability', earned: 1, max: 6, na: false, blocked: false,
          seen: { earned: 0, max: 4, na: false }, said: { earned: 1, max: 2, na: false },
          checks: [
            { code: 'discount_amount', label: 'clear discount amount', state: 'fail' },
            { code: 'deal_said', label: 'cited on 1 of 2 purchase-intent questions', state: 'advisory' },
          ],
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
    // Part 3: with no generated_headlines on this fixture, the registry
    // default renders in both the hero card AND the section header.
    expect(screen.getAllByText('Agents know who you are').length).toBe(2)
    expect(screen.getAllByText("Agents can knock, but can't read much").length).toBe(2)
    expect(screen.getAllByText('Your value leaks before it reaches the answer').length).toBe(2)
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

  it('F1/F2/1c: the parsed-page card renders the real OfferFeed, product name, and product image (alt = product name)', () => {
    renderReport()
    expect(screen.getAllByText('$105.00').length).toBeGreaterThan(0)
    expect(screen.getByText('Mens Cruiser Shadow Blue Natural White Sole')).toBeInTheDocument()
    const img = screen.getByAltText('Mens Cruiser Shadow Blue Natural White Sole')
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

  it('1c: omits the product image slot entirely when product_image_url is null, but the product name still renders independently', () => {
    renderReport({ product_image_url: null })
    expect(screen.queryByAltText('Mens Cruiser Shadow Blue Natural White Sole')).not.toBeInTheDocument()
    // The offer feed and product name still render — only the image slot is gone.
    expect(screen.getAllByText('$105.00').length).toBeGreaterThan(0)
    expect(screen.getByText('Mens Cruiser Shadow Blue Natural White Sole')).toBeInTheDocument()
  })

  it('1c: omits the product name line when product_name is null, but the image still renders independently', () => {
    renderReport({ product_name: null })
    expect(screen.queryByText('Mens Cruiser Shadow Blue Natural White Sole')).not.toBeInTheDocument()
    const img = screen.getByAltText("Product, as parsed from the merchant's own markup")
    expect(img).toHaveAttribute('src', 'https://cdn.example.com/allbirds-cruiser.jpg')
  })

  it('1c: an onError-failed image removes the whole image slot (including caption), not just the broken <img>', () => {
    renderReport()
    const img = screen.getByAltText('Mens Cruiser Shadow Blue Natural White Sole')
    fireEvent.error(img)
    expect(screen.queryByAltText('Mens Cruiser Shadow Blue Natural White Sole')).not.toBeInTheDocument()
    expect(screen.queryByText(/The merchant's own image, from the same markup we scored/)).not.toBeInTheDocument()
    // The product name and offers are unaffected by the image failing.
    expect(screen.getAllByText('Mens Cruiser Shadow Blue Natural White Sole').length).toBeGreaterThan(0)
  })

  // Partial-read report state: a blocked dim alongside otherwise-measured
  // Visibility/Accessibility is exactly the partial_read shape (Part 1a),
  // so it now reads the `unread` treatment (Part 4a) instead of the
  // older, undifferentiated "N/M" — still never a fabricated zero.
  it('a blocked True Value dimension in an otherwise-measured run reads unread, never a fabricated zero', () => {
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
    expect(screen.getAllByText(/PTS UNREAD/).length).toBeGreaterThan(0)
    expect(screen.queryByText('0/8')).not.toBeInTheDocument()
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

describe('LiteFullReportV4 — Part 3: generated pillar headlines', () => {
  const GENERATED_HEADLINES = {
    visibility: { headline: 'You hold 35% share of all brand mentions.', source: 'generated' },
    accessibility: { headline: 'Agent Access earns 5 of 6 points.', source: 'generated' },
    true_value: { headline: "Couldn't be measured this run", source: 'default' },
  }

  it('renders the stored headline in both the hero card and the matching section header, never regenerating', () => {
    renderReport({ generated_headlines: GENERATED_HEADLINES })

    expect(screen.getAllByText('You hold 35% share of all brand mentions.').length).toBe(2)
    expect(screen.getAllByText('Agent Access earns 5 of 6 points.').length).toBe(2)
    expect(screen.getAllByText("Couldn't be measured this run").length).toBe(2)

    // The pre-Part-3 hardcoded defaults are gone from the DOM entirely
    // when a real generated headline is present for every pillar.
    expect(screen.queryByText('Agents know who you are')).not.toBeInTheDocument()
    expect(screen.queryByText("Agents can knock, but can't read much")).not.toBeInTheDocument()
  })

  it('falls back to the registry default per pillar when generated_headlines is null (older run)', () => {
    renderReport({ generated_headlines: null })
    expect(screen.getAllByText('Agents know who you are').length).toBe(2)
  })

  it('falls back independently per pillar when only some pillars have a generated headline', () => {
    renderReport({
      generated_headlines: {
        visibility: { headline: 'You hold 35% share of all brand mentions.', source: 'generated' },
        accessibility: null,
        true_value: null,
      },
    })
    expect(screen.getAllByText('You hold 35% share of all brand mentions.').length).toBe(2)
    expect(screen.getAllByText("Agents can knock, but can't read much").length).toBe(2)
    expect(screen.getAllByText('Your value leaks before it reaches the answer').length).toBe(2)
  })
})

describe('LiteFullReportV4 — Part 1a/1b/1d: True Value expander parity with the mock', () => {
  it('every dimension-level "How it\'s scored" panel opens as StateChip pills sourced from the run\'s own checks[], and collapses on a second click', () => {
    renderReport()
    const tv = within(document.getElementById('tv'))
    // price_truth, deal_citability, value_protocols each render one — member_value is N/A in this fixture and uses the WHY N/A affordance instead.
    const buttons = tv.getAllByRole('button', { name: "How it's scored" })
    expect(buttons).toHaveLength(3)

    const ptButton = buttons[0]
    expect(ptButton).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(ptButton)
    expect(ptButton).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('price in your code')).toBeInTheDocument()
    expect(screen.getByText('price hidden behind login')).toBeInTheDocument()

    fireEvent.click(ptButton)
    expect(ptButton).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('price in your code')).not.toBeInTheDocument()
  })

  it('Deal Citability renders its own checks[], independent of Price Truth', () => {
    renderReport()
    const dcButton = within(document.getElementById('tv')).getAllByRole('button', { name: "How it's scored" })[1]
    fireEvent.click(dcButton)
    expect(screen.getByText('clear discount amount')).toBeInTheDocument()
    expect(screen.getByText('cited on 1 of 2 purchase-intent questions')).toBeInTheDocument()
  })

  it('the scored-caption text is registry-driven, not a literal — perturbing DIMENSIONS_BY_CODE.price_truth.scoredCaption changes the render', () => {
    const original = DIMENSIONS_BY_CODE.price_truth.scoredCaption
    DIMENSIONS_BY_CODE.price_truth.scoredCaption = [{ text: 'PERTURBED CAPTION TEXT', bold: true }]
    try {
      renderReport()
      fireEvent.click(within(document.getElementById('tv')).getAllByRole('button', { name: "How it's scored" })[0])
      expect(screen.getByText('PERTURBED CAPTION TEXT')).toBeInTheDocument()
    } finally {
      DIMENSIONS_BY_CODE.price_truth.scoredCaption = original
    }
  })

  it('WHY N/A (Member Value) opens and closes on repeated clicks', () => {
    renderReport()
    const whyNa = screen.getByRole('button', { name: /WHY N\/A/ })
    expect(whyNa).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(whyNa)
    expect(whyNa).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText(/Neither the site crawl nor a direct model check/)).toBeInTheDocument()
    fireEvent.click(whyNa)
    expect(whyNa).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText(/Neither the site crawl nor a direct model check/)).not.toBeInTheDocument()
  })

  it('ADJUST ASSUMPTIONS opens and closes on repeated clicks', () => {
    renderReport()
    const adjust = screen.getByRole('button', { name: /ADJUST ASSUMPTIONS/ })
    fireEvent.click(adjust)
    expect(screen.getByLabelText('Annual revenue')).toBeInTheDocument()
    fireEvent.click(adjust)
    expect(screen.queryByLabelText('Annual revenue')).not.toBeInTheDocument()
  })

  it('Share of Mentions / Recommendation Strength "How it\'s scored" panels also open and close on repeated clicks', () => {
    renderReport()
    const viz = within(document.getElementById('viz'))
    const [somButton, rsButton] = viz.getAllByRole('button', { name: "How it's scored" })

    fireEvent.click(somButton)
    expect(somButton).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(somButton)
    expect(somButton).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(rsButton)
    expect(rsButton).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(rsButton)
    expect(rsButton).toHaveAttribute('aria-expanded', 'false')
  })

  it('1d: the True Value pillar header uses Expand/Collapse, not a duplicate "How it\'s scored" — the editorial sentence renders at most once', () => {
    renderReport()
    expect(within(document.getElementById('tv')).getAllByRole('button', { name: "How it's scored" })).toHaveLength(3)
    expect(screen.queryAllByText(EDITORIAL_QUOTE).length).toBeLessThanOrEqual(1)
  })
})

describe('splitExposureDollars — Part 4c: remainder-to-largest rounding', () => {
  it('sums exactly to the modeled total even when independent rounding would drift', () => {
    const reasons = [{ impact_weight: 0.34 }, { impact_weight: 0.33 }, { impact_weight: 0.33 }]
    const dollars = splitExposureDollars(100, reasons)
    expect(dollars.reduce((a, b) => a + b, 0)).toBe(100)
  })

  it('assigns the rounding remainder to the largest share', () => {
    const reasons = [{ impact_weight: 0.6 }, { impact_weight: 0.4 }]
    const dollars = splitExposureDollars(10, reasons)
    expect(dollars[0]).toBeGreaterThanOrEqual(dollars[1])
    expect(dollars.reduce((a, b) => a + b, 0)).toBe(10)
  })

  it('returns [] for no reasons', () => {
    expect(splitExposureDollars(1000, [])).toEqual([])
  })

  it('a single reason gets the full exposure', () => {
    expect(splitExposureDollars(500, [{ impact_weight: 1 }])).toEqual([500])
  })
})

describe('LiteFullReportV4 — Part 4: run-tailored exposure reasons', () => {
  const EXPOSURE_REASONS = [
    { id: 'pt_seen', text: 'Your price checks earn 2 of 5 points on your own site.', impact_weight: 0.5, severity_rank: 1 },
    { id: 'catalog_context', text: "Catalog & Context earns 2 of 8 points — much of your catalog isn't readable to agents.", impact_weight: 0.3, severity_rank: 2 },
    { id: 'agent_access', text: "Agent Access earns 4 of 6 points — agents can't fully reach your site.", impact_weight: 0.2, severity_rank: 3 },
  ]

  it('renders each selected reason as its own line with the modeled-dollar/provenance format', () => {
    renderReport({ pillars: { exposure_reasons: EXPOSURE_REASONS } })
    for (const reason of EXPOSURE_REASONS) {
      expect(screen.getByText(reason.text)).toBeInTheDocument()
    }
    expect(screen.getAllByText(/≈ \$[\d,]+\/yr · modeled/).length).toBe(3)
    expect(screen.getByText(/split across reasons is modeled/)).toBeInTheDocument()
  })

  it('shows the modeled figure with no reason breakdown when nothing triggers this run', () => {
    renderReport({ pillars: { exposure_reasons: [] } })
    expect(screen.getByText('Modeled annual exposure')).toBeInTheDocument()
    expect(screen.queryByText(/≈ \$[\d,]+\/yr · modeled/)).not.toBeInTheDocument()
    expect(screen.queryByText(/split across reasons is modeled/)).not.toBeInTheDocument()
  })

  it('falls back to no breakdown when the payload predates Part 4 (exposure_reasons absent)', () => {
    renderReport()
    expect(screen.getByText('Modeled annual exposure')).toBeInTheDocument()
    expect(screen.queryByText(/≈ \$[\d,]+\/yr · modeled/)).not.toBeInTheDocument()
  })

  it('fewer than 3 triggered reasons renders fewer lines, never padded', () => {
    renderReport({ pillars: { exposure_reasons: [EXPOSURE_REASONS[0]] } })
    expect(screen.getAllByText(/≈ \$[\d,]+\/yr · modeled/).length).toBe(1)
  })
})

describe('Leadgen session: every report walkthrough/TrueSync CTA opens RequestFormModal with the right copy, none link to parleo.io', () => {
  it('no walkthrough/TrueSync anchor to parleo.io remains anywhere in the report', () => {
    renderReport()
    // #truesync in-page jump links (FixesTable's provenance, etc.) are
    // fine and expected to remain — only an outbound parleo.io href is
    // the thing this session removed.
    const parleoLinks = screen.queryAllByRole('link').filter((a) => (a.getAttribute('href') || '').includes('parleo.io'))
    expect(parleoLinks).toHaveLength(0)
  })

  it('every "Book your walkthrough" button (FunnelGate, FixesTable\'s "N MORE FIXES" upsell, ClosingFork) opens the same full-analysis-walkthrough copy', () => {
    renderReport()
    const walkthroughButtons = screen.getAllByRole('button', { name: 'Book your walkthrough' })
    // DOM order: FunnelGate, FixesTable, ClosingFork.
    expect(walkthroughButtons.length).toBe(3)

    for (const button of walkthroughButtons) {
      fireEvent.click(button)
      const dialog = screen.getByRole('dialog')
      expect(within(dialog).getByText('BOOK YOUR WALKTHROUGH')).toBeInTheDocument()
      expect(within(dialog).getByText("Let's walk through your audit together.")).toBeInTheDocument()
      expect(within(dialog).getByPlaceholderText('Anything you want us to focus on in the read-out?')).toBeInTheDocument()
      fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
    }
  })

  it('TrueSyncBand\'s "Talk to us about TrueSync" opens the truesync copy', () => {
    renderReport()
    fireEvent.click(screen.getAllByRole('button', { name: 'Talk to us about TrueSync' })[0])
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('TRUESYNC')).toBeInTheDocument()
    expect(within(dialog).getByText("Let's stop the leak.")).toBeInTheDocument()
    expect(within(dialog).getByPlaceholderText('Tell us about your loyalty program and deals…')).toBeInTheDocument()
  })

  it('ClosingFork renders both CTAs, each opening its own copy', () => {
    renderReport()
    const walkthroughButtons = screen.getAllByRole('button', { name: 'Book your walkthrough' })
    const trueSyncButtons = screen.getAllByRole('button', { name: 'Talk to us about TrueSync' })
    // FixesTable + FunnelGate + ClosingFork's own walkthrough button = 3;
    // TrueSyncBand + ClosingFork's own TrueSync button = 2.
    expect(walkthroughButtons.length).toBe(3)
    expect(trueSyncButtons.length).toBe(2)

    fireEvent.click(trueSyncButtons[trueSyncButtons.length - 1])
    expect(within(screen.getByRole('dialog')).getByText('TRUESYNC')).toBeInTheDocument()
  })

  it('the modal carries brand_name and report_token from the report context (Part 2c)', () => {
    renderReport()
    fireEvent.click(screen.getAllByRole('button', { name: 'Talk to us about TrueSync' })[0])
    // Fill and submit isn't needed here — the context ride-along is an
    // onSubmit-closure concern (useDemoRequestModal.js), covered by its
    // own unit test; this just asserts the modal actually opened wired
    // to a report-context CTA, i.e. the button click reached open().
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
