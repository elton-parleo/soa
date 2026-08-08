import React from 'react'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import '@testing-library/jest-dom'

import { LiteFullReport } from '../LiteFullReport.jsx'
import {
  DIMENSIONS, DIMENSIONS_BY_CODE, PILLAR_NAMES, LITE_QUERY_COUNT,
  VERDICT_AGENT_READY, VERDICT_NOT_AGENT_READY,
} from '../landing/scanDimensionsRegistry.js'
import { PUBLIC_AUDIT_BASE_URL } from '../publicUrls.js'
import ALLBIRDS_V3_REPORT from './fixtures/allbirds_v3_report.json'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const COMPONENT_SRC = fs.readFileSync(path.join(__dirname, '../LiteFullReport.jsx'), 'utf8')

function dim(code, name, score, max, overrides = {}) {
  return { code, name, score, max, evidence: [], fix: null, locked: false, linked: null, ...overrides }
}

const EIGHT_DIMENSIONS = [
  dim('F1', 'Agent Access', 8, 10),
  dim('F2', 'Catalog Context', 10, 15),
  dim('F3', 'Protocol & Feed Presence', 9, 10, { coverage: 'partial', deferred_items: [
    { label: 'Merchant Center / Deal Directory participation', reason: 'not crawl-observable' },
  ] }),
  dim('V1', 'Offer Legibility', 6, 15, { fix: 'add priceCurrency', locked: false }),
  dim('V2', 'Loyalty Surface', 6, 14, { fix: 'publish a rewards page', locked: false }),
  dim('V3', 'Member Value', 7, 14, { fix: 'expose member pricing', locked: false }),
  dim('V4', 'Value Rails', 4, 10, { fix: 'add priceValidUntil', locked: true }),
  dim('V5', 'Offer Integrity', 9, 12, { fix: 'stop fake was-prices', locked: true }),
]

const VISIBILITY_BREAKDOWN = {
  mention_rate: [
    { entity: 'Acme Co', is_primary: true, mentioned_queries: 6, total_queries: 12, rate_pct: 50.0 },
    { entity: 'Rival Co', is_primary: false, mentioned_queries: 3, total_queries: 12, rate_pct: 25.0 },
  ],
  share_of_mentions: [
    { entity: 'Acme Co', is_primary: true, mentions: 6, share_pct: 40.0 },
    { entity: 'Rival Co', is_primary: false, mentions: 9, share_pct: 60.0 },
  ],
  totals: { total_mentions: 15, total_queries: 12 },
  incentive_citation: [
    { entity: 'Acme Co', is_primary: true, mentions: 6, cited_answers: 2, rate_pct: 33.3 },
    { entity: 'Rival Co', is_primary: false, mentions: 3, cited_answers: 1, rate_pct: 33.3 },
  ],
}

const baseReport = {
  status: 'complete',
  locked: false,
  overall: [
    { name: 'Acme Co', role: 'primary', metrics: { som: 62.5, mention_rate: 50, position_index: 70, rsi: 1.2 } },
    { name: 'Rival Co', role: 'competitor', metrics: { som: 37.5, mention_rate: 30, position_index: 40, rsi: 0.4 } },
  ],
  by_stage: null, // deprecated Stage 7 — always null on the real API
  visibility_breakdown: VISIBILITY_BREAKDOWN,
  scan: {
    status: 'complete',
    total_score: 59,
    integrity_capped: false,
    foundation: { subtotal: 27, max: 35 },
    value: { subtotal: 32, max: 65 },
    dimensions: EIGHT_DIMENSIONS,
    pages_fetched: [{ url: 'https://acme.com', status: 'fetched' }],
  },
  visibility: 62.5,
  accessibility: 59,
  composite: 61,
  scan_status: 'complete',
}

describe('LiteFullReport — page frame', () => {
  it('renders the report header bar with the primary entity', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText('Acme Co')).toBeInTheDocument() // header bar brand
  })

  it('Stage 9 (U3), audit.parleo.io migration: Copy link writes the canonical /r/{token} URL on PUBLIC_AUDIT_BASE_URL to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    render(<LiteFullReport report={baseReport} token="tok-copy-123" />)
    fireEvent.click(screen.getByText('Copy link'))

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(`${PUBLIC_AUDIT_BASE_URL}/r/tok-copy-123`))
    await waitFor(() => expect(screen.getByText('Copied')).toBeInTheDocument())
  })

  it('renders the ONE Full Diagnostic CTA label in both the funnel teaser and the diagnostic cliff when VITE_LITE_CTA_URL is set (Part 1, M2: one offer, not two)', () => {
    vi.stubEnv('VITE_LITE_CTA_URL', 'https://parleo.io/demo')
    render(<LiteFullReport report={baseReport} />)
    const links = screen.getAllByText('Contact us for a free custom Full Diagnostic')
    expect(links).toHaveLength(2)
    links.forEach((link) => expect(link.closest('a')).toHaveAttribute('href', 'https://parleo.io/demo'))
    vi.unstubAllEnvs()
  })

  it('omits both CTA links when VITE_LITE_CTA_URL is unset', () => {
    vi.stubEnv('VITE_LITE_CTA_URL', '')
    render(<LiteFullReport report={baseReport} />)
    expect(screen.queryByText('Contact us for a free custom Full Diagnostic')).not.toBeInTheDocument()
    vi.unstubAllEnvs()
  })
})

describe('LiteFullReport — visibility section (Stage 7)', () => {
  it('renders the W1 section header', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText(`VISIBILITY · ${LITE_QUERY_COUNT} QUERIES · CHATGPT`)).toBeInTheDocument()
    expect(screen.getByText('How often agents mention you — and your value')).toBeInTheDocument()
  })

  it('renders one mention-rate row per entity with the NN% · n/12 format', () => {
    render(<LiteFullReport report={baseReport} />)
    // "Acme Co (you)" / "Rival Co" also appear in the share-of-mentions
    // legend, so this scopes to the rate/count pairs, which are unique
    // to the mention-rate card.
    expect(screen.getByText('50% · 6/12')).toBeInTheDocument()
    expect(screen.getByText('25% · 3/12')).toBeInTheDocument()
  })

  it('renders the mention-rate subtitle and You/Rivals legend', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText(new RegExp(`How many of the ${LITE_QUERY_COUNT} shopper questions named each brand`))).toBeInTheDocument()
    expect(screen.getByText('You')).toBeInTheDocument()
    expect(screen.getByText('Rivals')).toBeInTheDocument()
  })

  it('renders the share-of-mentions donut with a text-alternative aria-label', () => {
    render(<LiteFullReport report={baseReport} />)
    const donut = screen.getByRole('img', { name: /Acme Co 40% of mentions, Rival Co 60% of mentions/ })
    expect(donut).toBeInTheDocument()
  })

  it('shows the dominant-rival payoff line when a rival holds >=50% of all mentions', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText('15 brand mentions across 12 answers. Half went to one rival.')).toBeInTheDocument()
  })

  it('omits the payoff line when no rival reaches 50% (no fabricated drama)', () => {
    const report = {
      ...baseReport,
      visibility_breakdown: {
        ...VISIBILITY_BREAKDOWN,
        share_of_mentions: [
          { entity: 'Acme Co', is_primary: true, mentions: 8, share_pct: 60 },
          { entity: 'Rival Co', is_primary: false, mentions: 5, share_pct: 40 },
        ],
      },
    }
    render(<LiteFullReport report={report} />)
    expect(screen.queryByText(/Half went to one rival/)).not.toBeInTheDocument()
  })

  it('degrades gracefully without crashing when visibility_breakdown is absent (old API shape)', () => {
    const { visibility_breakdown, ...report } = baseReport
    render(<LiteFullReport report={report} />)
    expect(screen.getByText("Visibility data isn't available for this report yet.")).toBeInTheDocument()
  })
})

describe('LiteFullReport — Stage 13 (W4/W5): competitor_source-driven visibility section', () => {
  const soloReport = {
    ...baseReport,
    competitor_source: 'none',
    overall: [{ name: 'Acme Co', role: 'primary', metrics: { som: 100, mention_rate: 50, position_index: 70, rsi: 1.2 } }],
    visibility_breakdown: {
      mention_rate: [{ entity: 'Acme Co', is_primary: true, mentioned_queries: 6, total_queries: 12, rate_pct: 50.0 }],
      share_of_mentions: [{ entity: 'Acme Co', is_primary: true, mentions: 6, share_pct: 100.0 }],
      totals: { total_mentions: 6, total_queries: 12 },
      incentive_citation: [{ entity: 'Acme Co', is_primary: true, mentions: 6, cited_answers: 2, rate_pct: 33.3 }],
    },
  }

  it('solo run (competitor_source none): still shows mention rate, but no donut and no incentive-citation card', () => {
    render(<LiteFullReport report={soloReport} />)

    expect(screen.getByText('50% · 6/12')).toBeInTheDocument()
    expect(screen.getByText('Competitor comparison unavailable for this run.')).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: /of mentions/ })).not.toBeInTheDocument()
    expect(screen.queryByText('Incentive citation rate')).not.toBeInTheDocument()
  })

  it('solo run never shows the auto-selected provenance line', () => {
    render(<LiteFullReport report={soloReport} />)
    expect(screen.queryByText('Competitors auto-selected by ChatGPT')).not.toBeInTheDocument()
  })

  it('competitor_source generated: shows the provenance line and the normal comparison visuals', () => {
    render(<LiteFullReport report={{ ...baseReport, competitor_source: 'generated' }} />)
    expect(screen.getByText('Competitors auto-selected by ChatGPT')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /of mentions/ })).toBeInTheDocument()
  })

  it('competitor_source mixed: also shows the provenance line', () => {
    render(<LiteFullReport report={{ ...baseReport, competitor_source: 'mixed' }} />)
    expect(screen.getByText('Competitors auto-selected by ChatGPT')).toBeInTheDocument()
  })

  it('competitor_source manual: no provenance line, normal comparison visuals', () => {
    render(<LiteFullReport report={{ ...baseReport, competitor_source: 'manual' }} />)
    expect(screen.queryByText('Competitors auto-selected by ChatGPT')).not.toBeInTheDocument()
    expect(screen.getByRole('img', { name: /of mentions/ })).toBeInTheDocument()
  })
})

describe('LiteFullReport — incentive citation card (Stage 8)', () => {
  it('renders the card title, rubric-honest subtitle, and one row per entity', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText('Incentive citation rate')).toBeInTheDocument()
    expect(screen.getByText(
      'When an answer names the brand, how often it also cites a live, actionable deal or member offer'
    )).toBeInTheDocument()
    expect(screen.getByText('33% · 2 of 6 mentions')).toBeInTheDocument()
    expect(screen.getByText('33% · 1 of 3 mentions')).toBeInTheDocument()
  })

  it('renders the MENTIONED / WITH AN INCENTIVE CITED legend', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText('Mentioned')).toBeInTheDocument()
    expect(screen.getByText('With an incentive cited')).toBeInTheDocument()
  })

  it('shows "— · no mentions" for a zero-mention entity, never 0%', () => {
    const report = {
      ...baseReport,
      visibility_breakdown: {
        ...VISIBILITY_BREAKDOWN,
        incentive_citation: [
          { entity: 'Acme Co', is_primary: true, mentions: 6, cited_answers: 2, rate_pct: 33.3 },
          { entity: 'Rival Co', is_primary: false, mentions: 0, cited_answers: null, rate_pct: null },
        ],
      },
    }
    render(<LiteFullReport report={report} />)
    expect(screen.getByText('— · no mentions')).toBeInTheDocument()
    expect(screen.queryByText('0% · 0 of 0 mentions')).not.toBeInTheDocument()
  })

  it('renders zero-rate primary numerals in --bad (via inline style)', () => {
    const report = {
      ...baseReport,
      visibility_breakdown: {
        ...VISIBILITY_BREAKDOWN,
        incentive_citation: [
          { entity: 'Acme Co', is_primary: true, mentions: 6, cited_answers: 0, rate_pct: 0 },
          { entity: 'Rival Co', is_primary: false, mentions: 3, cited_answers: 1, rate_pct: 33.3 },
        ],
      },
    }
    render(<LiteFullReport report={report} />)
    const label = screen.getByText('0% · 0 of 6 mentions')
    expect(label).toHaveStyle({ color: 'var(--bad-ink)' })
  })

  it('renders the LINKED chip only when the crosswalk fired, sourced from scan.dimensions', () => {
    const report = {
      ...baseReport,
      scan: {
        ...baseReport.scan,
        dimensions: EIGHT_DIMENSIONS.map((d) =>
          d.code === 'V2' ? { ...d, linked: { reason: 'value never cited' } } : d
        ),
      },
    }
    render(<LiteFullReport report={report} />)
    expect(screen.getByText('LINKED · V2 LOYALTY SURFACE 6/14')).toBeInTheDocument()
  })

  it('omits the chip when the crosswalk did not fire', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.queryByText(/^LINKED ·/)).not.toBeInTheDocument()
  })

  it('ignores a linked reason on V2/V3 that is not one of the incentive-citation reasons', () => {
    // "loyalty program never mentioned" is a real, pre-existing
    // link_dimensions() reason — it renders its own DimensionRow chip in
    // the why-section, which is expected. What must NOT happen is the
    // incentive-citation card mistaking it for one of its own reasons.
    const report = {
      ...baseReport,
      scan: {
        ...baseReport.scan,
        dimensions: EIGHT_DIMENSIONS.map((d) =>
          d.code === 'V2' ? { ...d, linked: { reason: 'loyalty program never mentioned' } } : d
        ),
      },
    }
    render(<LiteFullReport report={report} />)
    expect(screen.queryByText(/^LINKED · V2 LOYALTY SURFACE/)).not.toBeInTheDocument()
  })

  it('shows the W5 payoff sentence only when the primary rate is 0 and a rival is >=25%', () => {
    const report = {
      ...baseReport,
      visibility_breakdown: {
        ...VISIBILITY_BREAKDOWN,
        incentive_citation: [
          { entity: 'Acme Co', is_primary: true, mentions: 6, cited_answers: 0, rate_pct: 0 },
          { entity: 'Rival Co', is_primary: false, mentions: 3, cited_answers: 2, rate_pct: 67 },
        ],
      },
    }
    render(<LiteFullReport report={report} />)
    expect(screen.getByText(
      "Agents mention you without your value: 0 of 6 mentions cited a deal or offer. Rival Co's mentions carried one 67% of the time."
    )).toBeInTheDocument()
  })

  it('omits the payoff sentence for the default (nonzero-rate) fixture', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.queryByText(/Agents mention you without your value/)).not.toBeInTheDocument()
  })

  it('does not render the card at all when incentive_citation is empty (missing metrics rows)', () => {
    const report = {
      ...baseReport,
      visibility_breakdown: { ...VISIBILITY_BREAKDOWN, incentive_citation: [] },
    }
    render(<LiteFullReport report={report} />)
    expect(screen.queryByText('Incentive citation rate')).not.toBeInTheDocument()
  })

  it('does not render the card when visibility_breakdown is absent entirely (old API shape)', () => {
    const { visibility_breakdown, ...report } = baseReport
    render(<LiteFullReport report={report} />)
    expect(screen.queryByText('Incentive citation rate')).not.toBeInTheDocument()
  })

  it('gives each entity row an accessible aria-label with both numbers', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByRole('img', {
      name: 'Acme Co: 6 mentions, 2 of those cited a live, actionable incentive',
    })).toBeInTheDocument()
  })
})

describe('LiteFullReport — funnel teaser (G2: decorative, never real data)', () => {
  it('renders the locked framing: title, subtitle, and FULL ANALYSIS tag', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText('Where you disappear in the funnel')).toBeInTheDocument()
    expect(screen.getAllByText('FULL ANALYSIS').length).toBeGreaterThan(0)
  })

  it('renders redacted glyph blocks, aria-hidden, never the real purchase-stage names (Part 6, G2)', () => {
    const { container } = render(<LiteFullReport report={baseReport} />)
    const decorative = container.querySelector('.lite-funnel-decor')
    expect(decorative).not.toBeNull()
    expect(decorative.textContent).toMatch(/▮/)
    ;['Awareness', 'Research', 'Comparison', 'Ready to Buy', 'AWARENESS', 'RESEARCH', 'COMPARISON', 'READY TO BUY'].forEach((label) => {
      expect(decorative.textContent).not.toContain(label)
    })
  })

  it('renders the overlay copy and CTA (Part 1/2, restyled Part 6 G1: via the inline FullDiagnosticGate variant), with no email language anywhere in this card', () => {
    vi.stubEnv('VITE_LITE_CTA_URL', 'https://parleo.io/demo')
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText(/See which stage you vanish from/)).toBeInTheDocument()
    // Also rendered by the closing module (M2: one offer, not two) — at
    // least one instance lives inside the funnel card itself.
    expect(screen.getAllByText('Contact us for a free custom Full Diagnostic').length).toBeGreaterThan(0)
    const cta = screen.getByText('Where you disappear in the funnel').closest('.lite-card')
    expect(cta.textContent).toContain('Contact us for a free custom Full Diagnostic')
    expect(cta.textContent.toLowerCase()).not.toMatch(/email|unlock with your/)
    vi.unstubAllEnvs()
  })

  it('renders identically (fixed constants) whether or not the API sends visibility data', () => {
    const { visibility_breakdown, ...reportWithout } = baseReport
    const { container: withoutVb } = render(<LiteFullReport report={reportWithout} />)
    const { container: withVb } = render(<LiteFullReport report={baseReport} />)
    const decorative = (c) => c.querySelector('[aria-hidden="true"] > div').textContent
    expect(decorative(withoutVb)).toBe(decorative(withVb))
  })
})

describe('LiteFullReport — executive tiles (legacy scorer-version fallback)', () => {
  it('renders composite, visibility, and accessibility — no exposure tile (fetch-resilience stage: legacy template retired)', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText('Composite score')).toBeInTheDocument()
    expect(screen.getByText('Visibility')).toBeInTheDocument()
    expect(screen.getByText('Accessibility')).toBeInTheDocument()
    expect(screen.queryByText(/Modeled exposure/)).not.toBeInTheDocument()
  })
})

// Fetch-resilience stage (hotfix 3, R2): the F1-V5 per-dimension why-
// section (grouped Foundation/Value, integrity-cap footnote, linked-
// reason chips, blocked/failed messaging) is retired — a scan under the
// current scorer version, whatever its status, now renders through the
// v4 pillars layout instead (see the DegradedRunBanner tests below and
// the existing v3 crosswalk-chip tests). Only the true "no scan
// attempted at all" case is left here.
describe('LiteFullReport — why section: no scan submitted', () => {
  it('shows the "add your store URL" prompt when scan is skipped (brand-only submission)', () => {
    const report = { ...baseReport, scan: { status: 'skipped', total_score: null, dimensions: [], pages_fetched: [] }, scan_status: 'skipped' }
    const onAddStoreUrl = vi.fn()
    render(<LiteFullReport report={report} onAddStoreUrl={onAddStoreUrl} />)

    expect(screen.getByText('Add your store URL to see why')).toBeInTheDocument()
    screen.getByText('Add store URL').click()
    expect(onAddStoreUrl).toHaveBeenCalled()
  })

  it('shows the same prompt when there is no scan object at all (legacy/no row)', () => {
    const report = { ...baseReport, scan: null, scan_status: null }
    render(<LiteFullReport report={report} />)
    expect(screen.getByText('Add your store URL to see why')).toBeInTheDocument()
  })
})

// Fetch-resilience stage (hotfix 3, R2): Stage 10's partial/na/cap
// coverage tags and the legacy ranked-fixes table both lived inside the
// now-retired F1-V5 why-section/fix-list — see FixListV3's own tests
// for the current (pillars-driven) fix-ranking behavior, and lite_
// pillars.py's own tests for na/blocked coverage handling server-side.
describe('LiteFullReport — legacy ranked fixes: renders nothing without pillars', () => {
  it('renders nothing when the report has no pillars payload, regardless of scan status', () => {
    const report = { ...baseReport, scan: { status: 'skipped', total_score: null, dimensions: [], pages_fetched: [] } }
    render(<LiteFullReport report={report} />)
    expect(screen.queryByText(/Showing \d+ of \d+ fixes/)).not.toBeInTheDocument()
    expect(screen.queryByText(/RANKED FIXES/)).not.toBeInTheDocument()
  })
})

describe('LiteFullReport — evidence gallery (speculative field)', () => {
  it('renders nothing when evidence_examples is absent (todays real API)', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.queryByText('What agents actually said')).not.toBeInTheDocument()
  })

  it('renders entries when evidence_examples is present', () => {
    const report = {
      ...baseReport,
      evidence_examples: [{ excerpt: 'Acme Co was not mentioned in this answer.', platform: 'chatgpt', stage: 'Research' }],
    }
    render(<LiteFullReport report={report} />)
    expect(screen.getByText('What agents actually said')).toBeInTheDocument()
    expect(screen.getByText(/Acme Co was not mentioned/)).toBeInTheDocument()
  })
})

describe('LiteFullReport — diagnosis card (speculative field)', () => {
  it('renders nothing when report.diagnosis is absent (todays real API)', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.queryByText('Diagnosis')).not.toBeInTheDocument()
  })

  it('renders the crawl summary, headline, body, and start-here callout when present', () => {
    const report = {
      ...baseReport,
      diagnosis: {
        crawlSummary: 'From 12 queries + a crawl of acme.com',
        headline: '5 incentives found. Agents can price 1 of them.',
        body: 'Today an agent sees one crawlable mention.',
        startHere: { title: 'Start here', body: 'Add structured MemberProgram markup.' },
      },
    }
    render(<LiteFullReport report={report} />)
    expect(screen.getByText('From 12 queries + a crawl of acme.com')).toBeInTheDocument()
    expect(screen.getByText('5 incentives found. Agents can price 1 of them.')).toBeInTheDocument()
    expect(screen.getByText('Today an agent sees one crawlable mention.')).toBeInTheDocument()
    expect(screen.getByText('Add structured MemberProgram markup.')).toBeInTheDocument()
  })
})

describe('LiteFullReport — exposure calculator (Stage 21, F2: collapsed by default; annual units Report redesign Part 7)', () => {
  it('renders a compact summary by default, sliders collapsed behind "adjust"', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.queryByLabelText('Annual revenue')).not.toBeInTheDocument()
    expect(screen.getByText('adjust')).toBeInTheDocument()
  })

  it('reveals the sliders and modeled-exposure disclaimer after clicking adjust', () => {
    render(<LiteFullReport report={baseReport} />)
    fireEvent.click(screen.getByText('adjust'))
    expect(screen.getByLabelText('Annual revenue')).toBeInTheDocument()
    expect(screen.getByLabelText('AI-assisted share of purchases')).toBeInTheDocument()
    expect(screen.getByText('Modeled, not measured.')).toBeInTheDocument()
  })

  it('updates the modeled exposure figure when a slider moves', () => {
    const { container } = render(<LiteFullReport report={baseReport} />)
    fireEvent.click(screen.getByText('adjust'))
    const revenueSlider = screen.getByLabelText('Annual revenue')
    const numeral = () => container.querySelector('.lite-numeral--calc').textContent
    const before = numeral()
    Object.defineProperty(revenueSlider, 'value', { value: '100000000', configurable: true })
    revenueSlider.dispatchEvent(new Event('change', { bubbles: true }))
    expect(numeral()).not.toBe(before)
  })

  it('collapses back after clicking COLLAPSE', () => {
    render(<LiteFullReport report={baseReport} />)
    fireEvent.click(screen.getByText('adjust'))
    expect(screen.getByLabelText('Annual revenue')).toBeInTheDocument()
    fireEvent.click(screen.getByText('COLLAPSE'))
    expect(screen.queryByLabelText('Annual revenue')).not.toBeInTheDocument()
  })

  it('never renders "/mo" or "monthly" anywhere in the exposure card (Part 7 grep test)', () => {
    const { container } = render(<LiteFullReport report={baseReport} />)
    fireEvent.click(screen.getByText('adjust'))
    const expCard = container.querySelector('#exp')
    expect(expCard.textContent).not.toMatch(/\/\s*mo\b/i)
    expect(expCard.textContent.toLowerCase()).not.toContain('monthly')
  })
})

describe('LiteFullReport — exposure revenue seeding (Part 5, R3; annual units Report redesign Part 7)', () => {
  it('seeds the annual revenue straight from the probe estimate (no conversion) and shows the ESTIMATED provenance label', () => {
    const report = { ...baseReport, revenue_estimate_usd: 12_000_000 }
    render(<LiteFullReport report={report} />)
    expect(screen.getByText(/\$12,000,000 annual revenue/)).toBeInTheDocument()
    expect(screen.getByText('revenue estimated by ChatGPT · adjust')).toBeInTheDocument()
  })

  it('clamps an estimate below the slider minimum', () => {
    const report = { ...baseReport, revenue_estimate_usd: 5000 } // well under the $120,000 floor
    render(<LiteFullReport report={report} />)
    expect(screen.getByText(/\$120,000 annual revenue/)).toBeInTheDocument()
  })

  it('falls back to the existing static default, with no provenance label, when the probe never ran (revenue_estimate_usd absent)', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText(/\$12,000,000 annual revenue/)).toBeInTheDocument()
    expect(screen.getByText('adjust')).toBeInTheDocument()
    expect(screen.queryByText(/estimated by ChatGPT/)).not.toBeInTheDocument()
  })

  it('falls back to the default, no label, when the probe ran but found nothing (revenue_estimate_usd null)', () => {
    const report = { ...baseReport, revenue_estimate_usd: null }
    render(<LiteFullReport report={report} />)
    expect(screen.getByText(/\$12,000,000 annual revenue/)).toBeInTheDocument()
    expect(screen.queryByText(/estimated by ChatGPT/)).not.toBeInTheDocument()
  })

  it('user adjustment overrides the estimate for that session and drops the provenance label', () => {
    const report = { ...baseReport, revenue_estimate_usd: 12_000_000 }
    render(<LiteFullReport report={report} />)
    fireEvent.click(screen.getByText('revenue estimated by ChatGPT · adjust'))
    const revenueSlider = screen.getByLabelText('Annual revenue')
    Object.defineProperty(revenueSlider, 'value', { value: '24000000', configurable: true })
    revenueSlider.dispatchEvent(new Event('change', { bubbles: true }))
    fireEvent.click(screen.getByText('COLLAPSE'))

    expect(screen.getByText(/\$24,000,000 annual revenue/)).toBeInTheDocument()
    expect(screen.queryByText(/estimated by ChatGPT/)).not.toBeInTheDocument()
    expect(screen.getByText('adjust')).toBeInTheDocument()
  })
})

describe('LiteFullReport — closing diagnostic module (restyled Report redesign Part 6, G4: block-variant FullDiagnosticGate replacing the old cliff card)', () => {
  it('renders the exact heading, the 3 highlighted upsell panels, remaining locked topics, and platform chips', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText(`This report is a ${LITE_QUERY_COUNT}-question sample. The full picture is bigger.`)).toBeInTheDocument()
    expect(screen.getByText('3 more AI platforms')).toBeInTheDocument()
    expect(screen.getByText('Full category run')).toBeInTheDocument()
    expect(screen.getByText('Net price accuracy')).toBeInTheDocument()
    expect(screen.getByText(/Persona-level breakdowns/)).toBeInTheDocument()
    expect(screen.getByText(/Trend over time/)).toBeInTheDocument()
    expect(screen.getByText(/Retail shelf comparison/)).toBeInTheDocument()
    expect(screen.getByText('ChatGPT')).toBeInTheDocument()
    expect(screen.getByText('Gemini')).toBeInTheDocument()
    expect(screen.getByText('Perplexity')).toBeInTheDocument()
    expect(screen.getByText('Claude')).toBeInTheDocument()
  })

  it('renders as a block-variant gate: FULL ANALYSIS pill + CTA, real (non-blurred) content', () => {
    vi.stubEnv('VITE_LITE_CTA_URL', 'https://parleo.io/demo')
    render(<LiteFullReport report={baseReport} />)
    const heading = screen.getByText(`This report is a ${LITE_QUERY_COUNT}-question sample. The full picture is bigger.`)
    expect(heading.closest('[aria-hidden="true"]')).toBeNull()
    const links = screen.getAllByText('Contact us for a free custom Full Diagnostic')
    expect(links.length).toBeGreaterThan(0)
    vi.unstubAllEnvs()
  })
})

describe('LiteFullReport — footer', () => {
  it('renders the re-run cadence line and methodology stamp', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText(/re-run this diagnostic monthly/)).toBeInTheDocument()
    expect(screen.getByText(new RegExp(`${LITE_QUERY_COUNT} QUERIES · 1 PLATFORM · 1 RUN EACH`))).toBeInTheDocument()
    expect(screen.getByText(/SAMPLE, NOT A CATEGORY STUDY/)).toBeInTheDocument()
  })
})

// ─── Stage 19: v3 report UX rendered from the pillars payload ─────────────
// report.pillars is the real API shape build_pillars_payload produces
// (apps/api/app/services/lite_pillars.py) — present only for a
// scorer_version "3" scan. This is the exact shape that used to render
// as zeros/an empty fixes table before this stage (scan.dimensions is
// v1/v2-keyed and unusable for a v3 row).

function subLens(earned, max, na, evidence = []) {
  return { earned, max, na, evidence }
}

function pillarDim(code, name, earned, max, overrides = {}) {
  return { code, name, earned, max, na: false, evidence: [], seen: null, said: null, ...overrides }
}

// Part 3: mirrors lite_pillars.py::_build_fixes_section's ranking rule
// (opportunity size descending, tiebreak by code, only dims with a
// fix_human, top 2 visible) so test fixtures don't hand-maintain a
// second, driftable copy of report.pillars.fixes.
function computeFixesSection(accessibilityDims, trueValueDims) {
  const ranked = [...accessibilityDims, ...trueValueDims]
    .filter((d) => !d.na && d.fix_human)
    .sort((a, b) => {
      const gapA = (a.max || 0) - (a.earned || 0)
      const gapB = (b.max || 0) - (b.earned || 0)
      if (gapB !== gapA) return gapB - gapA
      return a.code.localeCompare(b.code)
    })
  const visible = ranked.slice(0, 2).map((d) => ({
    code: d.code, name: d.name, fix_human: d.fix_human, impact: (d.max || 0) - (d.earned || 0),
  }))
  return { visible, remaining_count: Math.max(0, ranked.length - 2) }
}

function buildV3Pillars({ dealCitabilitySeen, dealCitabilitySaid, memberValueNa = true, visibilityShareEarned = 20 } = {}) {
  const accessibilityDims = [
    pillarDim('agent_access', 'Agent Access', 6, 6, {
      evidence: ['robots.txt allows crawling'], fix: null, fix_human: null, locked: false,
    }),
    pillarDim('catalog_context', 'Catalog & Context', 5, 8, {
      evidence: ['partial schema.org markup'], fix: 'add GTIN to product schema',
      fix_human: 'Add product identifiers so agents can match your listings.', locked: false,
    }),
    pillarDim('protocol_feed', 'Protocol & Feed Presence', 3, 6, {
      evidence: ['no llms.txt found'], fix: 'publish an llms.txt file',
      fix_human: 'Publish an llms.txt file so agents can find you.', locked: true,
    }),
  ]
  const trueValueDims = [
    pillarDim('price_truth', 'Price Truth', 10, 14, {
      seen: subLens(6, 6, false, ['machine-readable price found in Offer schema']),
      said: subLens(4, 8, false, ['5/6 mentions (83%) cited a price']),
      fix: 'add priceCurrency to Offer schema',
      fix_human: 'Add currency to your prices so agents can read them correctly.', locked: false,
    }),
    memberValueNa
      ? pillarDim('member_value', 'Member Value', 0, 0, {
        na: true,
        evidence: ["probe: 'No, we do not have a member pricing program.'"],
        seen: subLens(0, 12, false, ['no loyalty page found']),
        said: subLens(0, 7, true, ['fewer than 2 mentions in the relevant opportunity set']),
        fix: null, fix_human: null, locked: false,
      })
      : pillarDim('member_value', 'Member Value', 15, 19, {
        seen: subLens(12, 12, false, ['loyalty page found']),
        said: subLens(3, 7, false, ['2/4 purchase-intent mentions (50%) cited member value']),
        fix: null, fix_human: null, locked: true,
      }),
    pillarDim('deal_citability', 'Deal Citability', 5, 7, {
      seen: dealCitabilitySeen || subLens(4, 4, false, ['active discount encoded with priceValidUntil']),
      said: dealCitabilitySaid || subLens(1, 3, false, ['1 of 6 purchase-intent mentions cited a deal']),
      fix: 'add priceValidUntil to the Offer',
      fix_human: "Add an end date to your deals so agents can tell they're still active.", locked: true,
    }),
  ]
  return {
    visibility: {
      score: 90, max: 100,
      dimensions: [
        pillarDim('share_of_mentions', 'Share of Mentions', visibilityShareEarned, 25, {
          evidence: ['42.0% share of mentions across all tracked brands'],
        }),
        pillarDim('recommendation_strength', 'Recommendation Strength', 14, 15, {
          evidence: ['Consistently the top pick.'],
        }),
      ],
    },
    accessibility: { score: 78, max: 100, dimensions: accessibilityDims },
    true_value: { score: 70, max: 100, dimensions: trueValueDims },
    member_value_na: memberValueNa,
    fixes: computeFixesSection(accessibilityDims, trueValueDims),
    // Verdict/gate template branching stage (G1): a realistic fully-
    // scored context — tv_pct mirrors true_value.score above (the same
    // earned/applicable*100 computation, not a second definition).
    // Callers needing composite_withheld/unverified override `state`
    // (+ composite/tv_pct as G1 specifies for that state) directly via
    // spread, same pattern already used for `verdict` throughout this
    // file.
    state: 'scored',
    composite: 74,
    tv_pct: 70,
    tv_earned: 21,
    tv_applicable: 30,
    unmeasured_count: 0,
  }
}

const V3_VISIBILITY_BREAKDOWN = {
  mention_rate: [
    { entity: 'Allbirds', is_primary: true, mentioned_queries: 8, total_queries: 12, rate_pct: 66.7 },
    { entity: 'Rothy\'s', is_primary: false, mentioned_queries: 5, total_queries: 12, rate_pct: 41.7 },
  ],
  share_of_mentions: [
    { entity: 'Allbirds', is_primary: true, mentions: 8, share_pct: 62 },
    { entity: "Rothy's", is_primary: false, mentions: 5, share_pct: 38 },
  ],
  totals: { total_mentions: 13, total_queries: 12 },
  incentive_citation: [
    { entity: 'Allbirds', is_primary: true, mentions: 8, cited_answers: 1, rate_pct: 12.5 },
    { entity: "Rothy's", is_primary: false, mentions: 5, cited_answers: 2, rate_pct: 40.0 },
  ],
}

function buildV3Report(overrides = {}) {
  return {
    status: 'complete',
    locked: false,
    overall: [
      { name: 'Allbirds', role: 'primary', metrics: { som: 62, mention_rate: 66.7, position_index: 70, rsi: 2.8 } },
      { name: "Rothy's", role: 'competitor', metrics: { som: 38, mention_rate: 41.7, position_index: 40, rsi: 0.4 } },
    ],
    by_stage: null,
    visibility_breakdown: V3_VISIBILITY_BREAKDOWN,
    scan: { status: 'complete', total_score: 82, integrity_capped: false, scorer_version: '3', dimensions: [], pages_fetched: [] },
    visibility: 90, accessibility: 78, composite: 84,
    scan_status: 'complete',
    pillars: buildV3Pillars(),
    ...overrides,
  }
}

describe('LiteFullReport — email de-gating (Report redesign, Part 8, E1)', () => {
  it('never renders unlock/email-gate language anywhere in a v3/v4 report, regardless of report.locked', () => {
    const { container } = render(<LiteFullReport report={buildV3Report({ locked: true })} />)
    const text = container.textContent.toLowerCase()
    expect(text).not.toMatch(/unlock/)
    expect(text).not.toMatch(/enter your email/)
    expect(text).not.toMatch(/sign up to (see|view|unlock)/)
  })

  it('renders full content identically whether report.locked is true or false (the field is vestigial for a v3/v4 row)', () => {
    const { container: lockedTrue } = render(<LiteFullReport report={buildV3Report({ locked: true })} />)
    const { container: lockedFalse } = render(<LiteFullReport report={buildV3Report({ locked: false })} />)
    expect(lockedTrue.textContent).toBe(lockedFalse.textContent)
  })
})

describe('LiteFullReport — degraded-run banner (fetch-resilience stage, hotfix 3, R1/R2)', () => {
  it('shows the S3 first-person 429 banner and NOT MEASURABLE dimensions when scan_status is blocked', () => {
    const pillars = buildV3Pillars()
    pillars.accessibility.dimensions = pillars.accessibility.dimensions.map((d) => ({
      ...d, blocked: true, earned: 0,
      evidence: ["the store root and every sampled product page were rate-limited or blocked this run — nothing could be measured on-site"],
      checks: null, fix: null, fix_human: null,
    }))
    pillars.true_value.dimensions = pillars.true_value.dimensions.map((d) => ({
      ...d, blocked: true, earned: 0, max: 0, checks: null, fix: null, fix_human: null,
    }))
    const report = buildV3Report({
      pillars, scan_status: 'blocked',
      scan: {
        status: 'blocked', total_score: null, dimensions: [], pages_fetched: [],
        degraded_reason: 'blocked',
        degraded_banner_facts: { refusal: '429', attempts: 6, robots_included: true },
      },
    })
    render(<LiteFullReport report={report} />)

    expect(screen.getByText(/Your site refused every request \(429\) before serving a page, across 6 attempts\./)).toBeInTheDocument()
    expect(screen.getByText(/Your marketing team almost never knows it's on\./)).toBeInTheDocument()
    expect(screen.queryByText(/will hit the same wall/)).not.toBeInTheDocument()
    expect(screen.getAllByText('NOT MEASURABLE').length).toBeGreaterThan(0)
  })

  it('shows the 403-refused wording in plain language, code in parentheses', () => {
    const report = buildV3Report({
      scan_status: 'blocked',
      scan: {
        status: 'blocked', total_score: null, dimensions: [], pages_fetched: [],
        degraded_reason: 'blocked',
        degraded_banner_facts: { refusal: '403', attempts: 3, robots_included: false },
      },
    })
    render(<LiteFullReport report={report} />)
    expect(screen.getByText(/Your site refused every request \(403\) before serving a page, across 3 attempts\./)).toBeInTheDocument()
    expect(screen.queryByText(/403-refused/)).not.toBeInTheDocument()
  })

  // Blocked-run copy pass: the banner reads from the same registry
  // entry as the discovery finding section, and no longer branches on
  // bannerFacts.signed — the copy is uniform regardless of whether the
  // reader was cryptographically verified; that distinction now lives
  // only in the V4 discovery fix's action line (FAILURE_POINT_COPY.
  // blocked.fixFraming), not this banner.
  it('the banner wording is the same whether or not bannerFacts.signed is true, and never says "cryptographically"', () => {
    const signedReport = buildV3Report({
      scan_status: 'blocked',
      scan: {
        status: 'blocked', total_score: null, dimensions: [], pages_fetched: [],
        degraded_reason: 'blocked',
        degraded_banner_facts: { refusal: '403', attempts: 3, robots_included: false, signed: true },
      },
    })
    const { unmount } = render(<LiteFullReport report={signedReport} />)
    expect(screen.getByText(/Your site refused every request \(403\) before serving a page, across 3 attempts\./)).toBeInTheDocument()
    expect(screen.queryByText(/cryptographically/)).not.toBeInTheDocument()
    unmount()

    const unsignedReport = buildV3Report({
      scan_status: 'blocked',
      scan: {
        status: 'blocked', total_score: null, dimensions: [], pages_fetched: [],
        degraded_reason: 'blocked',
        degraded_banner_facts: { refusal: '403', attempts: 3, robots_included: false, signed: false },
      },
    })
    render(<LiteFullReport report={unsignedReport} />)
    expect(screen.getByText(/Your site refused every request \(403\) before serving a page, across 3 attempts\./)).toBeInTheDocument()
    expect(screen.queryByText(/cryptographically/)).not.toBeInTheDocument()
  })

  it('shows the S2 no-product-pages-found banner, never blaming the site', () => {
    const report = buildV3Report({
      scan_status: 'failed',
      scan: {
        status: 'failed', total_score: null, dimensions: [], pages_fetched: [],
        degraded_reason: 'no_product_pages_found',
        degraded_banner_facts: { sitemaps_read: 3 },
      },
    })
    render(<LiteFullReport report={report} />)
    expect(screen.getByText(/We read 3 of your sitemaps but couldn't locate product pages to sample/)).toBeInTheDocument()
    expect(screen.getByText(/this can be our reader's limitation/)).toBeInTheDocument()
  })

  it('shows the generic unreachable banner when scan_status is failed with no degraded_reason', () => {
    const report = buildV3Report({
      scan_status: 'failed',
      scan: { status: 'failed', total_score: null, dimensions: [], pages_fetched: [] },
    })
    render(<LiteFullReport report={report} />)
    expect(screen.getByText(/couldn't finish reading your site this time/)).toBeInTheDocument()
  })

  it('omits the banner entirely for a normal complete run', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.queryByText(/on every page we tried/)).not.toBeInTheDocument()
    expect(screen.queryByText(/couldn't finish reading your site/)).not.toBeInTheDocument()
    expect(screen.queryByText(/couldn't locate product pages/)).not.toBeInTheDocument()
  })

  it('S3: the retired generalization ("will hit the same wall") is gone from the source entirely', () => {
    expect(COMPONENT_SRC).not.toContain('will hit the same wall')
  })

  // Part 2 (P4.b): the Sephora fix — the banner's claim about agents
  // stops being an inference once the fetch probe has an answer.
  it('appends the agent-got-through sentence when the fetch probe reached the page fine', () => {
    const report = buildV3Report({
      scan_status: 'blocked',
      scan: {
        status: 'blocked', total_score: null, dimensions: [], pages_fetched: [],
        degraded_reason: 'blocked',
        degraded_banner_facts: {
          refusal: '403', attempts: 3, robots_included: true,
          fetch_probe: { outcome: 'quoted_price', agent_could_access: true, url: 'https://acme.example.com/products/tee' },
        },
      },
    })
    render(<LiteFullReport report={report} />)
    expect(screen.getByText(/ChatGPT opened it fine — the wall appears specific to unidentified readers like ours/)).toBeInTheDocument()
  })

  it('appends the agent-also-walled sentence when the fetch probe could not access the page either', () => {
    const report = buildV3Report({
      scan_status: 'blocked',
      scan: {
        status: 'blocked', total_score: null, dimensions: [], pages_fetched: [],
        degraded_reason: 'blocked',
        degraded_banner_facts: {
          refusal: '403', attempts: 3, robots_included: true,
          fetch_probe: { outcome: 'could_not_access', agent_could_access: false, url: 'https://acme.example.com/products/tee' },
        },
      },
    })
    render(<LiteFullReport report={report} />)
    expect(screen.getByText(/It reported it couldn't access the page either/)).toBeInTheDocument()
  })

  it('appends nothing when the fetch probe has not run yet', () => {
    const report = buildV3Report({
      scan_status: 'blocked',
      scan: {
        status: 'blocked', total_score: null, dimensions: [], pages_fetched: [],
        degraded_reason: 'blocked',
        degraded_banner_facts: { refusal: '403', attempts: 3, robots_included: true },
      },
    })
    render(<LiteFullReport report={report} />)
    expect(screen.queryByText(/ChatGPT opened it fine/)).not.toBeInTheDocument()
    expect(screen.queryByText(/It reported it couldn't access the page either/)).not.toBeInTheDocument()
  })

  // N4: the no-product-pages-found state never claims "the wall appears
  // specific" (there's no wall — our sampler just never found a page to
  // ask about) — it gets its own honest, sampling-scoped sentence,
  // naming the URL kind that was actually probed.
  it('N4: no-product-pages-found + agent could access -> the sampling-honest sentence, naming the store root', () => {
    const report = buildV3Report({
      scan_status: 'failed',
      scan: {
        status: 'failed', total_score: null, dimensions: [], pages_fetched: [],
        degraded_reason: 'no_product_pages_found',
        degraded_banner_facts: {
          sitemaps_read: 2,
          fetch_probe: { outcome: 'quoted_price', agent_could_access: true, url: 'https://acme.example.com', kind: 'store_root' },
        },
      },
    })
    render(<LiteFullReport report={report} />)
    expect(screen.getByText(/ChatGPT opened your homepage fine — the pages exist; our sampler couldn't locate them this run\./)).toBeInTheDocument()
    expect(screen.queryByText(/the wall appears specific/)).not.toBeInTheDocument()
  })

  it('N4: no-product-pages-found + agent could access a product page -> names "your product page"', () => {
    const report = buildV3Report({
      scan_status: 'failed',
      scan: {
        status: 'failed', total_score: null, dimensions: [], pages_fetched: [],
        degraded_reason: 'no_product_pages_found',
        degraded_banner_facts: {
          sitemaps_read: 2,
          fetch_probe: { outcome: 'opened_no_price', agent_could_access: true, url: 'https://acme.example.com/products/tee', kind: 'product_page' },
        },
      },
    })
    render(<LiteFullReport report={report} />)
    expect(screen.getByText(/ChatGPT opened your product page fine — the pages exist; our sampler couldn't locate them this run\./)).toBeInTheDocument()
  })

  it('N4: no-product-pages-found + agent also could not access -> the universal could-not-access sentence', () => {
    const report = buildV3Report({
      scan_status: 'failed',
      scan: {
        status: 'failed', total_score: null, dimensions: [], pages_fetched: [],
        degraded_reason: 'no_product_pages_found',
        degraded_banner_facts: {
          sitemaps_read: 2,
          fetch_probe: { outcome: 'could_not_access', agent_could_access: false, url: 'https://acme.example.com', kind: 'store_root' },
        },
      },
    })
    render(<LiteFullReport report={report} />)
    expect(screen.getByText(/It reported it couldn't access the page either/)).toBeInTheDocument()
    expect(screen.queryByText(/the pages exist/)).not.toBeInTheDocument()
  })
})

describe('LiteFullReport — Agent Access Matrix (Part 1, M4)', () => {
  const MATRIX = [
    { agent: 'GPTBot', platform: 'OpenAI', role: 'Model training', root: 'blocked', product_pages: 'blocked', rule: 'Disallow: /' },
    { agent: 'OAI-SearchBot', platform: 'OpenAI', role: 'ChatGPT search index', root: 'allowed', product_pages: 'allowed', rule: 'Allow: /' },
    { agent: 'ChatGPT-User', platform: 'OpenAI', role: 'On-demand user fetches', root: 'allowed', product_pages: 'allowed', rule: 'Allow: /' },
    { agent: 'ClaudeBot', platform: 'Anthropic', role: 'Crawling', root: 'allowed', product_pages: 'partial', rule: null },
    { agent: 'PerplexityBot', platform: 'Perplexity', role: 'Search index', root: 'allowed', product_pages: 'allowed', rule: 'Allow: /' },
    { agent: 'Google-Extended', platform: 'Google', role: 'Gemini/AI training control', root: 'allowed', product_pages: 'unknown', rule: null },
  ]

  function reportWithMatrix() {
    return buildV3Report({
      scan: { status: 'complete', total_score: 82, integrity_capped: false, scorer_version: '3', dimensions: [], pages_fetched: [], agent_access_matrix: MATRIX },
    })
  }

  it('renders all six agent rows with their states and the caption, inside Agent Access\'s own panel', () => {
    render(<LiteFullReport report={reportWithMatrix()} />)
    fireEvent.click(screen.getAllByText("HOW IT'S SCORED")[0]) // Agent Access is the first accessibility tile

    for (const row of MATRIX) {
      expect(screen.getByText(row.agent)).toBeInTheDocument()
    }
    expect(screen.getByText(/Read from your robots\.txt — each platform's crawlers are governed separately\./)).toBeInTheDocument()
  })

  it('never renders the matrix table on a different dimension\'s panel', () => {
    render(<LiteFullReport report={reportWithMatrix()} />)
    const catalogHow = screen.getAllByText("HOW IT'S SCORED")[1]
    fireEvent.click(catalogHow)
    const panel = catalogHow.closest('.lite-v4-dim').querySelector('.lite-v4-meth')
    expect(within(panel).queryByText('AGENT ACCESS MATRIX')).not.toBeInTheDocument()
  })

  it('renders nothing when the scan carries no matrix (older/degraded row without one)', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    fireEvent.click(screen.getAllByText("HOW IT'S SCORED")[0])
    expect(screen.queryByText('AGENT ACCESS MATRIX')).not.toBeInTheDocument()
  })

  it('scrolls horizontally rather than overflowing at mobile 360px', () => {
    const { container } = render(<LiteFullReport report={reportWithMatrix()} />)
    fireEvent.click(screen.getAllByText("HOW IT'S SCORED")[0])
    expect(container.querySelector('.lite-agent-matrix-scroll')).toBeInTheDocument()
  })
})

describe('LiteFullReport — v3 hero: segmented bar + verdict (Stage 21, H1/H2)', () => {
  it('renders the composite number and one segmented bar with all three pillar captions', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText('84')).toBeInTheDocument() // composite
    expect(screen.getByText('VISIBILITY 34/40')).toBeInTheDocument()
    expect(screen.getByText('ACCESSIBILITY 14/20')).toBeInTheDocument()
    expect(screen.getByText('TRUE VALUE 15/21')).toBeInTheDocument()
  })

  it('shows the normalized-applicable caption when member_value is N/A', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText(/\*MEMBER VALUE NOT APPLICABLE — SCORED ON 81 POINTS, SHOWN OUT OF 100/)).toBeInTheDocument()
  })

  it('omits the normalized caption when member_value is applicable', () => {
    const report = buildV3Report({ pillars: buildV3Pillars({ memberValueNa: false }) })
    render(<LiteFullReport report={report} />)
    expect(screen.queryByText(/NORMALIZED/)).not.toBeInTheDocument()
    expect(screen.getByText('COMPOSITE = STRAIGHT SUM')).toBeInTheDocument()
  })

  // Fetch-resilience stage (Part C, C2): mirrors the member_value_na
  // legend pattern above, for a different reason — every sampled
  // product page failed to fetch this run, not "doesn't apply."
  it('shows the ENCODE CHECKS BLOCKED legend dagger when a True Value dimension is blocked', () => {
    const pillars = buildV3Pillars()
    pillars.true_value.dimensions[0] = { ...pillars.true_value.dimensions[0], blocked: true, earned: 0, max: 0 }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText(/†ENCODE CHECKS BLOCKED BY SITE — SEE TRUE VALUE/)).toBeInTheDocument()
  })

  it('omits the legend dagger when no True Value dimension is blocked', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.queryByText(/ENCODE CHECKS BLOCKED/)).not.toBeInTheDocument()
  })

  it('never renders the old two-dial/tile layout (no bare "Composite score"/"Modeled exposure/mo" tile pair) for a v3 row', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.queryByText('Composite score')).not.toBeInTheDocument()
  })
})

function zeroTrueValuePillars() {
  const pillars = buildV3Pillars({ memberValueNa: false })
  pillars.true_value.dimensions = pillars.true_value.dimensions.map((d) => (
    d.code === 'member_value'
      ? { ...d, earned: 0, seen: subLens(0, 12, false, []), said: subLens(0, 7, false, []) }
      : { ...d, earned: 0, seen: subLens(0, d.seen.max, false, []), said: subLens(0, d.said.max, false, []) }
  ))
  return pillars
}

describe('LiteFullReport — v3 hero verdict template table', () => {
  it.each([
    ['weak visibility overrides everything else', buildV3Pillars({ visibilityShareEarned: 5 }), /Agents barely know you exist/],
    ['strong visibility + zero True Value', zeroTrueValuePillars(), /they never talk about your value\./],
    ['strong visibility + True Value N/A', buildV3Pillars({ memberValueNa: true, dealCitabilitySeen: subLens(0, 4, false), dealCitabilitySaid: subLens(0, 3, false) }), /your value score is normalized/],
    ['strong visibility + True Value nearly full, no verdict field (pre-G1 report)', buildV3Pillars({ memberValueNa: false, dealCitabilitySeen: subLens(4, 4, false), dealCitabilitySaid: subLens(3, 3, false) }), /and they get your value right\./],
    ['strong visibility + True Value nearly full, verdict AGENT-READY', { ...buildV3Pillars({ memberValueNa: false, dealCitabilitySeen: subLens(4, 4, false), dealCitabilitySaid: subLens(3, 3, false) }), verdict: VERDICT_AGENT_READY }, /and they get your value right\./],
  ])('verdict template: %s', (_label, pillars, expected) => {
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText(expected)).toBeInTheDocument()
  })

  it('Stage 25 (G2): strong visibility + True Value nearly full but verdict is NOT-AGENT-READY (e.g. weak Accessibility) never claims the unqualified win', () => {
    const pillars = {
      ...buildV3Pillars({ memberValueNa: false, dealCitabilitySeen: subLens(4, 4, false), dealCitabilitySaid: subLens(3, 3, false) }),
      verdict: VERDICT_NOT_AGENT_READY,
    }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.queryByText(/and they get your value right\./)).not.toBeInTheDocument()
    expect(screen.getByText(/your value comes through/)).toBeInTheDocument()
    expect(screen.getByText(/still keeps you short of agent-ready/)).toBeInTheDocument()
  })

  it('Report redesign (Part 2): the weak-visibility branch also reads the verdict, not just the two True-Value-strong branches', () => {
    const pillars = { ...buildV3Pillars({ visibilityShareEarned: 5 }), verdict: VERDICT_NOT_AGENT_READY }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText(/Agents barely know you exist/)).toBeInTheDocument()
    expect(screen.getByText(/Below the agent-ready bar\./)).toBeInTheDocument()
  })

  it('Report redesign (Part 2): the zero-True-Value branch appends the readiness line', () => {
    const pillars = { ...zeroTrueValuePillars(), verdict: VERDICT_NOT_AGENT_READY }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText(/they never talk about your value\./)).toBeInTheDocument()
    expect(screen.getByText(/Below the agent-ready bar\./)).toBeInTheDocument()
  })

  it('Report redesign (Part 2): a pre-G1 report (no verdict field at all) appends no readiness clause anywhere', () => {
    const pillars = buildV3Pillars({ visibilityShareEarned: 5 })
    delete pillars.verdict
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.queryByText(/agent-ready bar/)).not.toBeInTheDocument()
  })

  it('Report redesign (Part 2): an AGENT-READY verdict appends the affirmative readiness clause', () => {
    const pillars = { ...buildV3Pillars({ memberValueNa: true }), verdict: VERDICT_AGENT_READY }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText(/your value score is normalized/)).toBeInTheDocument()
    expect(screen.getByText(/You clear the agent-ready bar\./)).toBeInTheDocument()
  })
})

describe('LiteFullReport — v3 hero verdict chip (Stage 25, Part 5/6, G1/A2)', () => {
  it('renders the AGENT-READY chip next to the composite score', () => {
    const pillars = { ...buildV3Pillars(), verdict: VERDICT_AGENT_READY }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText(VERDICT_AGENT_READY)).toBeInTheDocument()
  })

  it('renders the NOT AGENT-READY chip next to the composite score', () => {
    const pillars = { ...buildV3Pillars(), verdict: VERDICT_NOT_AGENT_READY }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText(VERDICT_NOT_AGENT_READY)).toBeInTheDocument()
  })

  it('renders no verdict chip at all for a pre-G1 report with no verdict field', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.queryByText(VERDICT_AGENT_READY)).not.toBeInTheDocument()
    expect(screen.queryByText(VERDICT_NOT_AGENT_READY)).not.toBeInTheDocument()
  })
})

describe('LiteFullReport — True Value section (Stage 19, R2; restyled Report redesign Part 3/4)', () => {
  it('renders all three dual-lens dimensions with live seen/said bars', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText('The value only we score')).toBeInTheDocument()
    expect(screen.getAllByText(/ON YOUR SITE/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/IN ANSWERS/).length).toBeGreaterThan(0)
    // Row summary is the said outcome's own evidence line (Part 4).
    expect(screen.getByText('5/6 mentions (83%) cited a price')).toBeInTheDocument()
  })

  it('renders member_value N/A as a compact NOT APPLICABLE line with a WHY panel containing the probe quote, no bars', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText(/NOT APPLICABLE · no loyalty program found/)).toBeInTheDocument()
    expect(screen.getByText('WHY')).toBeInTheDocument()
    fireEvent.click(screen.getByText('WHY'))
    expect(screen.getByText('"No, we do not have a member pricing program."')).toBeInTheDocument()
    expect(screen.queryByText('0/0')).not.toBeInTheDocument()
  })

  it('renders an outcome-guard N/A said sub-lens as "not enough mentions to measure", never 0%', () => {
    const pillars = buildV3Pillars({ dealCitabilitySaid: subLens(0, 3, true, ['fewer than 2 mentions in the relevant opportunity set']) })
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText('not enough mentions to measure')).toBeInTheDocument()
    expect(screen.queryByText('0%')).not.toBeInTheDocument()
  })

  // Part 1 (P4): a distinct honest state from the generic outcome-guard
  // NA above — enough mention volume existed, but none of it was ever
  // through pass-2 price coding (no soa_pass2_coding_log sentinel), so
  // there is no basis to rate at all. Must never collapse into the
  // same "not enough mentions" copy, and never a 0%.
  it('renders a not_evaluated said sub-lens with its own honest copy, distinct from the generic NA', () => {
    const pillars = buildV3Pillars({
      dealCitabilitySaid: {
        earned: 0, max: 3, na: true, not_evaluated: true,
        evidence: ['this audit predates price-observation coding — re-run for the full picture'],
      },
    })
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText('this audit predates price-observation coding — re-run for the full picture')).toBeInTheDocument()
    expect(screen.queryByText('not enough mentions to measure')).not.toBeInTheDocument()
    expect(screen.queryByText('0%')).not.toBeInTheDocument()
  })

  // Fetch-resilience stage (Part C, B4/C1): every sampled product page
  // failed to fetch this run — the dimension renders NOT MEASURABLE,
  // with the fetch facts surfaced and no leaked said-outcome sentence
  // (which would otherwise sit confusingly next to "NOT MEASURABLE").
  it('renders a blocked True Value dimension as NOT MEASURABLE with the fetch facts, no said-outcome leak, no false-fail chip', () => {
    const blockedFact = "2 of 2 product pages rate-limited our reader (HTTP 429) — couldn't be evaluated."
    const pillars = buildV3Pillars()
    pillars.true_value.dimensions[0] = {
      ...pillars.true_value.dimensions[0],
      blocked: true, earned: 0, max: 0,
      seen: { ...pillars.true_value.dimensions[0].seen, blocked: true, evidence: [blockedFact] },
      checks: [
        { code: 'price_truth_blocked_0', label: 'Machine-readable price present', state: 'blocked', evidence: blockedFact },
      ],
      fix: null, fix_human: null,
    }
    pillars.fixes = computeFixesSection(pillars.accessibility.dimensions, pillars.true_value.dimensions)
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    const row = screen.getAllByText('Price Truth')[0].closest('.lite-v4-dim')
    expect(within(row).getByText('NOT MEASURABLE')).toBeInTheDocument()
    expect(within(row).queryByText(/cited a price/)).not.toBeInTheDocument()
    expect(within(row).getAllByText(blockedFact).length).toBeGreaterThan(0)
    fireEvent.click(within(row).getByText('WHY'))
    expect(within(row).getByText(/not a failing score, it's an unread one/)).toBeInTheDocument()
    expect(row.querySelector('.lite-v4-chip--blocked')).toBeInTheDocument()
    expect(row.querySelector('.lite-v4-chip--fail')).not.toBeInTheDocument()
  })

  it('Report redesign (Part 3, M2): only one dimension row\'s panel stays open at a time within the card — opening a second closes the first', () => {
    const { container } = render(<LiteFullReport report={buildV3Report()} />)
    const hows = container.querySelectorAll('#tv .lite-v4-how')
    expect(hows.length).toBeGreaterThanOrEqual(2)

    fireEvent.click(hows[0])
    expect(hows[0]).toHaveAttribute('aria-expanded', 'true')
    expect(hows[1]).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(hows[1])
    expect(hows[0]).toHaveAttribute('aria-expanded', 'false')
    expect(hows[1]).toHaveAttribute('aria-expanded', 'true')
  })

  it('never renders the standalone incentive-citation card inside True Value (Stage 21 replaced its bars with the footer line)', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.queryByText('Incentive citation rate')).not.toBeInTheDocument()
    expect(screen.queryByText('13% · 1 of 8 mentions')).not.toBeInTheDocument()
  })
})

describe('LiteFullReport — value_protocols single-wing row (Stage 25 Part 6 A1; restyled Report redesign Part 4 T3)', () => {
  function pillarsWithValueProtocols(vpOverrides = {}) {
    const base = buildV3Pillars()
    const vpDim = pillarDim('value_protocols', 'Value Protocols', 7, 7, {
      seen: subLens(7, 7, false, ['declares a UCP shopping-discount capability']),
      said: null,
      fix: null, fix_human: null, locked: false,
      ...vpOverrides,
    })
    return {
      ...base,
      true_value: { ...base.true_value, dimensions: [...base.true_value.dimensions, vpDim] },
    }
  }

  it('renders a SITE ONLY tag and its seen evidence, no answer-side bar', () => {
    const pillars = pillarsWithValueProtocols()
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText('Value Protocols')).toBeInTheDocument()
    expect(screen.getByText('SITE ONLY')).toBeInTheDocument()
    expect(screen.getByText('declares a UCP shopping-discount capability')).toBeInTheDocument()
    // price_truth/deal_citability each show an IN ANSWERS bar (member_
    // value is na by default in this fixture, so it shows none) —
    // value_protocols must not add a bar of its own.
    expect(screen.getAllByText(/IN ANSWERS/).length).toBe(2)
  })

  it('shows the earned/max score next to the dimension name, same as the other three dimensions', () => {
    const pillars = pillarsWithValueProtocols()
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText('7/7')).toBeInTheDocument()
  })
})

describe('LiteFullReport — v3 True Value pillar verdict + footer (Stage 21, T3/T4)', () => {
  it.each([
    // deal_citability stays at a fixed 0/4 seen · 0/3 said baseline in
    // every case (member_value stays na, excluded entirely) — price_truth's
    // seen/said are chosen so the COMBINED (price_truth + deal_citability)
    // aggregate ratio lands in the intended quadrant, not price_truth alone.
    ['working', subLens(6, 6, false), subLens(6, 8, false), 'WORKING', 'Encoded and cited — this is working.'],
    ['distribution gap', subLens(6, 6, false), subLens(0, 8, false), 'DISTRIBUTION GAP', 'Encoded, but agents rarely cite it — a distribution gap, not an encoding gap.'],
    ['encoding gap', subLens(0, 6, false), subLens(0, 8, false), 'ENCODING GAP', "Little encoded to cite, and agents aren't citing it."],
    ['cited elsewhere', subLens(0, 6, false), subLens(6, 8, false), 'CITED ELSEWHERE', 'Agents cite value despite little encoded on the page — likely sourced from elsewhere.'],
  ])('pillar-aggregate quadrant verdict: %s', (_label, priceSeen, priceSaid, expectedChip, expectedLead) => {
    const pillars = buildV3Pillars({ memberValueNa: true, dealCitabilitySeen: subLens(0, 4, false), dealCitabilitySaid: subLens(0, 3, false) })
    pillars.true_value.dimensions[0] = { ...pillars.true_value.dimensions[0], seen: priceSeen, said: priceSaid }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText(`VERDICT · ${expectedChip}`)).toBeInTheDocument()
    expect(screen.getByText(expectedLead)).toBeInTheDocument()
  })

  it('shows the first-mover line when no competitor has a nonzero value-citation signal', () => {
    const report = buildV3Report({
      visibility_breakdown: {
        ...V3_VISIBILITY_BREAKDOWN,
        incentive_citation: [
          { entity: 'Allbirds', is_primary: true, mentions: 8, cited_answers: 0, rate_pct: 0 },
          { entity: "Rothy's", is_primary: false, mentions: 5, cited_answers: 0, rate_pct: 0 },
        ],
      },
    })
    render(<LiteFullReport report={report} />)
    expect(screen.getByText(/No rival cites value either/)).toBeInTheDocument()
  })

  it('names the leading rival\'s citation edge when a competitor has a nonzero signal', () => {
    render(<LiteFullReport report={buildV3Report()} />) // V3_VISIBILITY_BREAKDOWN's Rothy's rate_pct is 40%
    expect(screen.getByText(/Rothy's cites value in 40% of mentions/)).toBeInTheDocument()
  })

  it('points at the top-ranked unlocked True-Value fixes by their actual computed rank, never a hard-coded range', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    // Fixture's ranked fixes: catalog_context(gap3, unlocked #1), price_truth(gap4... — see fixture-derived
    // ranking already covered by the Fixes describe block; this just asserts the pointer text shape.
    const pointer = screen.queryByText(/TARGET THIS PILLAR ↓/)
    expect(pointer).toBeInTheDocument()
    expect(pointer.textContent).toMatch(/^FIXE?S? \d{2}(, \d{2})* TARGET THIS PILLAR ↓$/)
  })

  it('omits the fix pointer when no visible fix (report.pillars.fixes.visible) is True-Value-coded', () => {
    const pillars = buildV3Pillars()
    // Part 3: the pointer now reads pillars.fixes.visible directly (the
    // same list FixListV3 renders), not dimensions[].fix/.locked.
    pillars.fixes = {
      visible: [{ code: 'catalog_context', name: 'Catalog & Context', fix_human: 'x', impact: 3 }],
      remaining_count: 3,
    }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.queryByText(/TARGET THIS PILLAR/)).not.toBeInTheDocument()
  })
})

// ─── N1-N5: not-measurable plumbing consistency stage ───────────────────
// blockedDim() mirrors the exact shape lite_pillars.py's build_pillars_
// payload produces for a seen_blocked True Value dimension (earned/max
// zeroed at the top level, blocked: true, seen carries the real weight
// + blocked flag) — the shape trueValueAggregateSeenSaid/pillarEarnedMax/
// anyTrueValueEncodeBlocked must all correctly exclude (N2/N3).
function blockedDim(code, name, weight, reason) {
  return {
    code, name, earned: 0, max: 0, na: false, blocked: true, evidence: [],
    seen: { earned: 0, max: weight, na: false, evidence: [reason], blocked: true },
    said: subLens(0, 0, false, []),
    checks: null, fix: null, fix_human: null, locked: false,
  }
}

function buildStarvedTrueValuePillars() {
  const accessibilityDims = [
    pillarDim('agent_access', 'Agent Access', 6, 6, { evidence: ['robots.txt allows crawling'] }),
    pillarDim('catalog_context', 'Catalog & Context', 0, 0, {
      blocked: true, evidence: ["couldn't be evaluated — product pages weren't sampled this run"],
      checks: null, fix: null, fix_human: null,
    }),
    pillarDim('protocol_feed', 'Protocol & Feed Presence', 3, 6, { evidence: ['no llms.txt found'] }),
  ]
  const trueValueDims = [
    blockedDim('price_truth', 'Price Truth', 5, "2 of 2 product pages couldn't be evaluated — product pages weren't sampled this run"),
    pillarDim('member_value', 'Member Value', 0, 0, {
      na: true, evidence: ["probe: 'No, we do not have a member pricing program.'"],
      seen: subLens(0, 9, false, ['no loyalty page found']),
      said: subLens(0, 6, true, ['fewer than 2 mentions in the relevant opportunity set']),
    }),
    blockedDim('deal_citability', 'Deal Citability', 4, "2 of 2 product pages couldn't be evaluated — product pages weren't sampled this run"),
    pillarDim('value_protocols', 'Value Protocols', 0, 7, {
      seen: subLens(0, 7, false, ['no protocol profile found']),
      said: null,
    }),
  ]
  return {
    visibility: {
      score: 90, max: 100,
      dimensions: [
        pillarDim('share_of_mentions', 'Share of Mentions', 20, 25, { evidence: ['e'] }),
        pillarDim('recommendation_strength', 'Recommendation Strength', 14, 15, { evidence: ['e'] }),
      ],
    },
    accessibility: { score: 60, max: 100, dimensions: accessibilityDims },
    true_value: { score: 0, max: 100, dimensions: trueValueDims },
    member_value_na: true,
    fixes: { visible: [], remaining_count: 0 },
    // Verdict/gate template branching stage (G1): a True Value dimension
    // (price_truth) is blocked here — the real backend now reads this as
    // state='unverified' (composite/verdict/tv_pct all withheld), never
    // the fabricated 'NOT AGENT-READY' + composite=40 this fixture used
    // to hard-code (the exact shape of the bug this stage fixes).
    verdict: null,
    composite: null,
    state: 'unverified',
    tv_pct: null,
    tv_earned: 0,
    tv_applicable: 7,
    unmeasured_count: 1,
  }
}

describe('LiteFullReport — N1-N5 not-measurable plumbing consistency', () => {
  it('N2: True Value header reads {earned}/{applicable} applicable · {n} not measurable this run', () => {
    const pillars = buildStarvedTrueValuePillars()
    const { container } = render(<LiteFullReport report={buildV3Report({ pillars })} />)
    // True Value applicable max here is JUST value_protocols' 7 (price_truth
    // and deal_citability blocked, member_value na) — 3 dims excluded.
    // textTransform:uppercase is CSS-only — the actual DOM text stays
    // title-case ("True Value"), and JSX expressions render as separate
    // sibling text nodes, so this asserts against container.textContent
    // rather than a single-element getByText match.
    expect(container.textContent).toMatch(/True Value · 0\/7 applicable · 3 not measurable this run/)
  })

  it('N2: header omits the not-measurable clause on a fully-scored run', () => {
    const pillars = buildV3Pillars({ memberValueNa: false })
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.queryByText(/not measurable this run/)).not.toBeInTheDocument()
  })

  it('N2/G1: header still reports its real applicable max; the gate strip withholds the verdict rather than asserting a fabricated 0%', () => {
    const pillars = buildStarvedTrueValuePillars()
    const { container } = render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(container.textContent).toMatch(/True Value · 0\/7 applicable/)
    expect(screen.getByText(/Nothing on-site could be measured this run/)).toBeInTheDocument()
    expect(screen.queryByText(/True Value is at 0%/)).not.toBeInTheDocument()
  })

  it('N2: the C2 dagger legend still renders when a True Value dim is blocked', () => {
    const pillars = buildStarvedTrueValuePillars()
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText(/†ENCODE CHECKS BLOCKED BY SITE/)).toBeInTheDocument()
  })

  it('N2 grep: no hardcoded "/40" True Value denominator anywhere in the source', () => {
    expect(COMPONENT_SRC).not.toMatch(/formatScore\(tv\.earned\)\}\/\{formatScore\(pillarNominalWeight\(PILLAR_TRUE_VALUE\)\)/)
  })

  it('N3: shows UNVERIFIED THIS RUN (not a quadrant label) when an encode wing is blocked', () => {
    const pillars = buildStarvedTrueValuePillars()
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText('VERDICT · UNVERIFIED THIS RUN')).toBeInTheDocument()
    expect(screen.queryByText('VERDICT · ENCODING GAP')).not.toBeInTheDocument()
  })

  it('N3: closing line is the honest could-not-verify sentence, competitor line unchanged', () => {
    const pillars = buildStarvedTrueValuePillars()
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText(/We couldn't read your pages to verify encoding this run — and agents aren't citing your value either\./)).toBeInTheDocument()
    // footerPayoff (competitor line) is independent of encoding state — still renders.
    expect(screen.getByText(/Rothy's cites value in 40% of mentions|No rival cites value either/)).toBeInTheDocument()
  })

  it('N3 grep: no "little encoded"/"nothing encoded" claim renders for an unverified run', () => {
    const pillars = buildStarvedTrueValuePillars()
    const { container } = render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(container.textContent).not.toMatch(/little encoded/i)
    expect(container.textContent).not.toMatch(/nothing encoded/i)
  })

  it('N3: a genuinely-measured encoding-gap run still shows the real quadrant chip (not swallowed by the new branch)', () => {
    const pillars = buildV3Pillars({ memberValueNa: true, dealCitabilitySeen: subLens(0, 4, false), dealCitabilitySaid: subLens(0, 3, false) })
    pillars.true_value.dimensions[0] = { ...pillars.true_value.dimensions[0], seen: subLens(0, 6, false), said: subLens(0, 8, false) }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText('VERDICT · ENCODING GAP')).toBeInTheDocument()
    expect(screen.getByText("Little encoded to cite, and agents aren't citing it.")).toBeInTheDocument()
  })
})

// ─── Verdict/gate template branching stage (G1/G2/G3) ────────────────────
// The gate strip (VerdictGateStrip) reads pillars.state/composite/tv_pct/
// unmeasured_count directly — no local re-derivation — so these fixtures
// set those fields explicitly (via spread over buildV3Pillars' realistic
// scored defaults) the same way `verdict` is already hand-set throughout
// this file, rather than trying to hand-derive them from the dimension
// list a second time.

describe('LiteFullReport — verdict gate strip: state-branched templates (G1/G2)', () => {
  it('scored (pass): unchanged heading/template, real numbers substituted for both placeholders', () => {
    const pillars = { ...buildV3Pillars(), verdict: VERDICT_AGENT_READY, composite: 74, tv_pct: 70 }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText('Why agent-ready:')).toBeInTheDocument()
    expect(screen.getByText(/readiness needs a score of 60\+ AND True Value above 25% of its applicable points\./)).toBeInTheDocument()
    expect(screen.getByText(/You're at 74 — and True Value is at 70%\./)).toBeInTheDocument()
  })

  it('scored (fail): unchanged heading/template, real numbers substituted for both placeholders', () => {
    const pillars = { ...buildV3Pillars(), verdict: VERDICT_NOT_AGENT_READY, composite: 40, tv_pct: 12 }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText('Why not agent-ready:')).toBeInTheDocument()
    expect(screen.getByText(/You're at 40 — and True Value is at 12%\./)).toBeInTheDocument()
  })

  it('composite_withheld: the exact G2 sentence, True Value percentage real, composite withheld', () => {
    const pillars = {
      ...buildV3Pillars(), verdict: null, composite: null,
      state: 'composite_withheld', tv_pct: 16, unmeasured_count: 2,
    }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText("Why there's no verdict this run:")).toBeInTheDocument()
    expect(screen.getByText(
      "Readiness needs a score of 60+ AND True Value above 25% of its applicable points. True Value is at 16% — but 2 dimensions couldn't be measured this run, so a full score and a verdict aren't possible. Re-run once the pages are readable.",
    )).toBeInTheDocument()
    expect(screen.queryByText(/Why agent-ready:|Why not agent-ready:/)).not.toBeInTheDocument()
  })

  it('unverified: the exact G2 sentence, no numbers at all', () => {
    const pillars = {
      ...buildV3Pillars(), verdict: null, composite: null,
      state: 'unverified', tv_pct: null, unmeasured_count: 1,
    }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText("Why there's no verdict this run:")).toBeInTheDocument()
    expect(screen.getByText(
      "Nothing on-site could be measured this run — there's no score to judge. Answer-side results above are real; re-run for the full picture.",
    )).toBeInTheDocument()
  })

  it('a pre-G1 fixture with no state key falls back to scored (rule 6, additive)', () => {
    const pillars = { ...buildV3Pillars(), verdict: VERDICT_AGENT_READY }
    delete pillars.state
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText('Why agent-ready:')).toBeInTheDocument()
  })

  it('G1 invariant, answer-side: a NOT AGENT-READY verdict can only be asserted when the gate strip also has a real composite — this fixture combination cannot legitimately occur, and the withheld/unverified branches above never read pillars.verdict at all', () => {
    // Documents the invariant the backend now enforces at construction
    // time (schemas.py's model_validator) — the frontend's own defense
    // is structural: composite_withheld/unverified branch BEFORE ever
    // touching pillars.verdict, so even a malformed payload can't
    // reach the pass/fail template with withheld data.
    const pillars = { ...buildV3Pillars(), verdict: VERDICT_NOT_AGENT_READY, state: 'unverified', composite: null }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.queryByText(/Why not agent-ready:/)).not.toBeInTheDocument()
    expect(screen.getByText("Why there's no verdict this run:")).toBeInTheDocument()
  })
})

// G3: the em-dash placeholder is a display-site concern (hero big-
// number, stat tiles) — it must never leak into a sentence template.
// Sweeps container.textContent across every gate-strip-relevant
// fixture in this file for the three empty-interpolation patterns.
describe('LiteFullReport — G3: placeholder containment (no dash/empty-interpolation in prose)', () => {
  const DASH_PATTERNS = [/at — /, /— —/, /at %/]

  it.each([
    ['scored pass', { ...buildV3Pillars(), verdict: VERDICT_AGENT_READY, composite: 74, tv_pct: 70 }],
    ['scored fail', { ...buildV3Pillars(), verdict: VERDICT_NOT_AGENT_READY, composite: 40, tv_pct: 12 }],
    ['composite_withheld', { ...buildV3Pillars(), verdict: null, composite: null, state: 'composite_withheld', tv_pct: 16, unmeasured_count: 2 }],
    ['unverified', { ...buildV3Pillars(), verdict: null, composite: null, state: 'unverified', tv_pct: null, unmeasured_count: 1 }],
    ['unverified via a real blocked-dimension fixture', buildStarvedTrueValuePillars()],
    ['member_value N/A', buildV3Pillars({ memberValueNa: true })],
    ['zero True Value', zeroTrueValuePillars()],
  ])('%s: no dash/empty-interpolation pattern anywhere in the rendered report', (_label, pillars) => {
    const { container } = render(<LiteFullReport report={buildV3Report({ pillars })} />)
    for (const pattern of DASH_PATTERNS) {
      expect(container.textContent).not.toMatch(pattern)
    }
  })
})

describe('LiteFullReport — v3 visibility: comparative bars + donut + RS gauge (Stage 21, V1/V2)', () => {
  it('restores mention rate as its own comparative bars, sorted with YOU tagged', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText(`Mention rate · of ${LITE_QUERY_COUNT} answers`)).toBeInTheDocument()
    expect(screen.getByText('YOU')).toBeInTheDocument()
    expect(screen.getByText('67% · 8/12')).toBeInTheDocument()
    expect(screen.getByText('42% · 5/12')).toBeInTheDocument()
  })

  it('shows the Share of Mentions donut card carrying its scored points', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText('Share of mentions')).toBeInTheDocument()
    expect(screen.getByText('20/25 pts')).toBeInTheDocument()
  })

  it('renders the Recommendation Strength row with its points and a plain-language line, never the raw metric', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText('Recommendation Strength')).toBeInTheDocument()
    expect(screen.getByText('14/15')).toBeInTheDocument()
    expect(screen.getByText('Consistently the top pick.')).toBeInTheDocument()
  })

  it('groups rivals past the top one into an "N others" legend line for a 6-competitor set', () => {
    const report = buildV3Report({
      visibility_breakdown: {
        ...V3_VISIBILITY_BREAKDOWN,
        share_of_mentions: [
          { entity: 'Allbirds', is_primary: true, mentions: 7, share_pct: 35 },
          { entity: "Rothy's", is_primary: false, mentions: 4, share_pct: 20 },
          { entity: 'Cariuma', is_primary: false, mentions: 3, share_pct: 15 },
          { entity: 'Skechers', is_primary: false, mentions: 3, share_pct: 15 },
          { entity: 'Cole Haan', is_primary: false, mentions: 2, share_pct: 10 },
          { entity: 'Veja', is_primary: false, mentions: 1, share_pct: 5 },
        ],
      },
    })
    render(<LiteFullReport report={report} />)
    expect(screen.getAllByText("Rothy's").length).toBeGreaterThan(0)
    expect(screen.getByText('4 others')).toBeInTheDocument()
    expect(screen.queryByText('Cariuma')).not.toBeInTheDocument()
  })

  it('never groups when there are only 2 competitors total (primary + 1 rival)', () => {
    const report = buildV3Report({
      competitor_source: 'manual',
      visibility_breakdown: {
        ...V3_VISIBILITY_BREAKDOWN,
        share_of_mentions: [
          { entity: 'Allbirds', is_primary: true, mentions: 7, share_pct: 60 },
          { entity: "Rothy's", is_primary: false, mentions: 5, share_pct: 40 },
        ],
      },
    })
    render(<LiteFullReport report={report} />)
    expect(screen.getAllByText("Rothy's").length).toBeGreaterThan(0)
    expect(screen.queryByText(/other/)).not.toBeInTheDocument()
  })
})

describe('LiteFullReport — v3 accessibility tiles (Stage 21, A)', () => {
  it('renders a dedicated Accessibility · n/20 section with three tiles, title-cased names', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText('ACCESSIBILITY · 14/20')).toBeInTheDocument()
    // Dimension names also appear a second time, in the ranked-fixes
    // table below — the first occurrence in document order is the tile.
    expect(screen.getAllByText('Agent Access').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Catalog & Context').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Protocol & Feed Presence').length).toBeGreaterThan(0)
  })

  it('Report redesign (Part 5): each tile renders the shared DimensionRowV4 — live pips, and a HOW IT\'S SCORED expander', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    const hows = screen.getAllByText("HOW IT'S SCORED")
    expect(hows.length).toBeGreaterThanOrEqual(3) // one per accessibility tile, at minimum
    expect(document.querySelectorAll('.lite-v4-pip').length).toBeGreaterThan(0)
    expect(document.querySelectorAll('.lite-v4-grid4 i').length).toBeGreaterThan(0)
  })

  it('maps a crosswalk chip on a retired code onto its v3 dimension, never rendering the old code', () => {
    const pillars = buildV3Pillars()
    pillars.accessibility.dimensions[0] = {
      ...pillars.accessibility.dimensions[0],
      linked: { reason: 'absent from most answers' },
    }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText('LINKED · ABSENT FROM MOST ANSWERS')).toBeInTheDocument()
    expect(screen.queryByText(/^F1/)).not.toBeInTheDocument()
  })

  it('never renders a crosswalk chip on an na dimension, and the na dimension itself is omitted from the tiles', () => {
    const pillars = buildV3Pillars()
    pillars.accessibility.dimensions[2] = {
      ...pillars.accessibility.dimensions[2],
      na: true,
      linked: { reason: 'absent from most answers' },
    }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.queryByText(/^LINKED ·/)).not.toBeInTheDocument()
    expect(screen.queryByText('Protocol & Feed Presence')).not.toBeInTheDocument()
  })

  // Fetch-resilience stage (Part C, C1): a dimension whose crawl
  // coverage came back 'blocked' (every sampled product page failed to
  // fetch this run) renders as NOT MEASURABLE with blocked-state check
  // chips — never the ordinary pass/fail chips, which would misread
  // "never checked" as "checked and failed."
  it('renders a blocked accessibility dimension as NOT MEASURABLE with blocked-state check chips, never a false fail', () => {
    const blockedFact = "2 of 2 product pages rate-limited our reader (HTTP 429) — couldn't be evaluated."
    const pillars = buildV3Pillars()
    pillars.accessibility.dimensions[1] = {
      ...pillars.accessibility.dimensions[1],
      blocked: true, earned: 0, max: 0,
      evidence: [blockedFact],
      checks: [
        { code: 'catalog_context_blocked_0', label: 'Product+Offer JSON-LD present', state: 'blocked', evidence: blockedFact },
      ],
      fix: null, fix_human: null,
    }
    pillars.fixes = computeFixesSection(pillars.accessibility.dimensions, pillars.true_value.dimensions)
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    const row = screen.getAllByText('Catalog & Context')[0].closest('.lite-v4-dim')
    expect(within(row).getByText('NOT MEASURABLE')).toBeInTheDocument()
    fireEvent.click(within(row).getByText('WHY'))
    expect(within(row).getByText(/not a failing score, it's an unread one/)).toBeInTheDocument()
    expect(within(row).getByText('Product+Offer JSON-LD present')).toBeInTheDocument()
    expect(row.querySelector('.lite-v4-chip--blocked')).toBeInTheDocument()
    expect(row.querySelector('.lite-v4-chip--fail')).not.toBeInTheDocument()
  })
})

describe('LiteFullReport — v3 ranked fixes (Part 3, F1/F2)', () => {
  it('renders the top 2 visible fixes with plain-language fix_human text and their dimension labels', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    // Ranked by gap: price_truth(4), catalog_context(3) — see computeFixesSection.
    expect(screen.getByText('Add currency to your prices so agents can read them correctly.')).toBeInTheDocument()
    expect(screen.getByText('Add product identifiers so agents can match your listings.')).toBeInTheDocument()
    expect(screen.getAllByText('Price Truth').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Catalog & Context').length).toBeGreaterThan(0)
  })

  it('omits ranks beyond 2 entirely — no markup fix, no plain-language fix, no dimension title reaches the DOM for a locked fix — only a bare remaining count', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    // protocol_feed (gap 3, tiebreak loses to catalog_context) and
    // deal_citability (gap 2) are the two ranks beyond the free top 2.
    expect(screen.queryByText('publish an llms.txt file')).not.toBeInTheDocument()
    expect(screen.queryByText('add priceValidUntil to the Offer')).not.toBeInTheDocument()
    expect(screen.queryByText('Publish an llms.txt file so agents can find you.')).not.toBeInTheDocument()
    expect(screen.queryByText(/Add an end date to your deals/)).not.toBeInTheDocument()
    expect(screen.getByText('2 MORE FIXES IDENTIFIED')).toBeInTheDocument()
  })

  it('renders the Full Diagnostic gate under the fixes list when fixes remain, one offer, no email language', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText(/Two fixes get you started/)).toBeInTheDocument()
    const fixCard = screen.getByText('2 MORE FIXES IDENTIFIED').closest('.lite-card')
    expect(fixCard.textContent.toLowerCase()).not.toMatch(/email/)
  })

  it('omits the gate entirely when no fixes remain beyond the visible 2', () => {
    const pillars = buildV3Pillars()
    pillars.fixes = { visible: pillars.fixes.visible, remaining_count: 0 }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.queryByText(/more fixes? identified/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Two fixes get you started/)).not.toBeInTheDocument()
  })
})

describe('LiteFullReport — R6 honest version fallback (Stage 19)', () => {
  it('shows the previous-methodology notice for a v2 row and renders its real (non-zero) composite/pillar scores', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText('SCORED UNDER A PREVIOUS METHODOLOGY')).toBeInTheDocument()
    expect(screen.getByText('Re-run for the current three-pillar score')).toBeInTheDocument()
    // baseReport's real, non-zero v2 values (never masked to 0).
    expect(screen.getByText('61')).toBeInTheDocument() // composite
    expect(screen.getByText('63')).toBeInTheDocument() // visibility, rounded from 62.5
    expect(screen.getByText('59')).toBeInTheDocument() // accessibility
  })

  it('never shows the notice for a v3 row', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.queryByText('SCORED UNDER A PREVIOUS METHODOLOGY')).not.toBeInTheDocument()
  })

  it('never shows the notice when there is no scan at all (nothing to be "previous" about)', () => {
    const report = { ...baseReport, scan: { status: 'skipped', total_score: null, dimensions: [], pages_fetched: [] }, scan_status: 'skipped' }
    render(<LiteFullReport report={report} />)
    expect(screen.queryByText('SCORED UNDER A PREVIOUS METHODOLOGY')).not.toBeInTheDocument()
  })

  it('Stage 25: shows the notice for a genuine scorer_version "3" row (pillars absent, retired under the v4 registry bump) and still renders its real, non-zero legacy scores', () => {
    const v3Report = {
      ...baseReport,
      pillars: undefined,
      scan: { ...baseReport.scan, scorer_version: '3' },
    }
    render(<LiteFullReport report={v3Report} />)
    expect(screen.getByText('SCORED UNDER A PREVIOUS METHODOLOGY')).toBeInTheDocument()
    expect(screen.getByText('61')).toBeInTheDocument() // composite, real not zeroed
  })
})

describe('LiteFullReport — copy sweep (Stage 19)', () => {
  it('a v3 report never renders the retired Foundation/Value two-family labels', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    // "TRUE VALUE · ..." (the new pillar section) legitimately contains
    // the word VALUE — the retired label was the standalone "VALUE ·
    // {subtotal}/65" two-family subtotal, which must be gone.
    expect(screen.queryByText(/^FOUNDATION ·/)).not.toBeInTheDocument()
    expect(screen.queryByText(/^VALUE ·/)).not.toBeInTheDocument()
    expect(screen.queryByText('FOUNDATION')).not.toBeInTheDocument()
  })

  it('fetch-resilience stage: a v2 report no longer shows Foundation/Value grouping either (legacy why-section retired)', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.queryByText(/^FOUNDATION ·/)).not.toBeInTheDocument()
    expect(screen.queryByText(/^VALUE ·/)).not.toBeInTheDocument()
  })

  it('the composite stays named "Agent Commerce Score" territory only via existing labels — never "Store Value Score"', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.queryByText(/Store Value Score/)).not.toBeInTheDocument()
  })
})

// ─── Stage 19 acceptance artifact: the real, previously-broken allbirds
// v3 row ────────────────────────────────────────────────────────────────
// apps/api/web/src/lite/__tests__/fixtures/allbirds_v3_report.json is a
// verbatim GET /report response captured from public_lite.get_lite_report
// against the production allbirds token (98d234...) — the exact row that
// used to render as zeros with an empty fixes table (its scan.dimensions
// array is still all F1-V5-coded zeros in this fixture, proving the old
// bug's root cause; the widget must never touch it for this row).
describe('LiteFullReport — acceptance artifact: real allbirds v3 row', () => {
  it('renders without crashing and shows the real, non-zero composite', () => {
    render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    expect(screen.getAllByText('Allbirds').length).toBeGreaterThan(0)
    expect(screen.getByText('31')).toBeInTheDocument() // real composite
  })

  it('never shows the previous-methodology notice (this row IS v3)', () => {
    render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    expect(screen.queryByText('SCORED UNDER A PREVIOUS METHODOLOGY')).not.toBeInTheDocument()
  })

  it('renders real, non-zero accessibility dimension scores from pillars, not the broken zeroed scan.dimensions', () => {
    render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    // scan.dimensions has F1 at score 0/max 0 (the old bug) — the v3
    // accessibility row for the same underlying dimension is 4.8/6.
    expect(screen.getByText('5/6')).toBeInTheDocument() // agent_access, rounded
  })

  it('remaps this real row\'s crosswalk reason onto catalog_context, but never onto agent_access (bug fix 1: not failing)', () => {
    render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    // agent_access earns 4.8/6 (80%) — genuinely fine, so the chip must
    // not attach there even though the source rule fired on both F1/F2.
    expect(screen.getAllByText('LINKED · ABSENT FROM MOST ANSWERS').length).toBe(1) // catalog_context only
  })

  it('populates the ranked-fixes table for this row with plain-language fixes and the remaining-fixes count (Part 3)', () => {
    render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    expect(screen.getByText('Publish a rewards page agents can find from your menu or footer.')).toBeInTheDocument()
    expect(screen.getByText('Show your prices in a format agents can read directly from the page, not just as text or an image.')).toBeInTheDocument()
    expect(screen.getByText('4 MORE FIXES IDENTIFIED')).toBeInTheDocument()
  })

  it('renders the True Value section with real seen/said evidence for all three dimensions', () => {
    render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    expect(screen.getByText('0/7 mentions (0%) cited a price')).toBeInTheDocument()
    expect(screen.getByText('0/5 purchase-intent mentions (0%) cited member value')).toBeInTheDocument()
  })

  it('zero-state: all six bar-halves (3 dimensions x seen/said) render an empty track + zero tick, and the pillar verdict is ENCODING GAP', () => {
    // Real allbirds row: every True Value sub-lens (seen and said, across
    // all three dimensions) earned exactly 0 — none are na (member_value
    // is applicable via the probe), so this is six real zero-state halves,
    // not six N/A halves.
    const { container } = render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    expect(container.querySelectorAll('.lite-v4-duo-zero').length).toBe(6)
    expect(screen.getByText('VERDICT · ENCODING GAP')).toBeInTheDocument()
    expect(screen.queryByText('0%')).not.toBeInTheDocument() // never a bare 0%, always n/max or the tick
  })
})

describe('LiteFullReport — v3 registry-drivenness (Stage 19)', () => {
  it('component source contains no v3 dimension-name literals', () => {
    for (const dim of DIMENSIONS) {
      expect(COMPONENT_SRC).not.toContain(`'${dim.name}'`)
      expect(COMPONENT_SRC).not.toContain(`"${dim.name}"`)
      expect(COMPONENT_SRC).not.toContain(`>${dim.name}<`)
    }
  })

  it('the v3 PillarTile call sites read PILLAR_NAMES, never a literal pillar-name string', () => {
    // Scoped to ExecutiveTilesV3's <PillarTile> call sites specifically —
    // ExecutiveTilesLegacy's plain <Tile label="Visibility" .../> predates
    // the registry entirely and is a separate, intentionally-static path.
    for (const literal of ['<PillarTile label="Visibility"', '<PillarTile label="Accessibility"', '<PillarTile label="True Value"']) {
      expect(COMPONENT_SRC).not.toContain(literal)
    }
  })

  it('perturbing a dimension weight moves the hero segmented bar\'s live-computed segment width', () => {
    // PillarSegmentedBar's segment width is pillarNominalWeight(pillar),
    // summed from DIMENSIONS live on every render (never a cached
    // export) — same discipline as AnatomyOfAnAnswer's PillarCard.
    const original = DIMENSIONS_BY_CODE.catalog_context.weight
    // Re-weighting session: agent_access/protocol_feed are 5 each now
    // (was 6) -> accessibility segment weight 5+41+5=51.
    DIMENSIONS_BY_CODE.catalog_context.weight = 41 // was 8
    try {
      render(<LiteFullReport report={buildV3Report()} />)
      const caption = screen.getByText('ACCESSIBILITY 14/20')
      const accessibilitySegment = caption.parentElement.parentElement
      expect(accessibilitySegment).toHaveStyle({ flex: '51 1 0%' })
    } finally {
      DIMENSIONS_BY_CODE.catalog_context.weight = original
    }
  })

  it('component source contains no hard-coded pillar-name JSX-text literals outside the legacy tile path', () => {
    // ExecutiveTilesLegacy's plain <Tile label="Visibility" .../> and
    // <Tile label="Accessibility" .../> predate the registry and stay
    // static on purpose (v1/v2 rows never touch PILLAR_NAMES) — every
    // OTHER pillar-name occurrence in the file (hero, True Value,
    // accessibility section headers) must read PILLAR_NAMES.
    const legacyExceptions = [
      'label="Visibility" value={formatScore(report.visibility)}',
      'label="Accessibility" value={formatScore(report.accessibility)}',
    ]
    let stripped = COMPONENT_SRC
    legacyExceptions.forEach((line) => { stripped = stripped.replace(line, '') })
    for (const literal of ['>Visibility<', '>Accessibility<', '>True Value<']) {
      expect(stripped).not.toContain(literal)
    }
  })

  it('perturbing the True Value pillar name moves the butterfly section label', () => {
    // Rendered as mixed case, visually uppercased via CSS text-transform
    // (same convention the design mock itself uses for this label) —
    // the DOM text content stays PILLAR_NAMES' own casing.
    const original = PILLAR_NAMES.true_value
    PILLAR_NAMES.true_value = 'Perturbed Pillar'
    try {
      render(<LiteFullReport report={buildV3Report()} />)
      expect(screen.getByText(/Perturbed Pillar ·/)).toBeInTheDocument()
      expect(screen.queryByText(/True Value ·/)).not.toBeInTheDocument()
    } finally {
      PILLAR_NAMES.true_value = original
    }
  })
})

describe('LiteFullReport — v3 fixes: headline (Part 3, F1/F2)', () => {
  it('computes "N moves recover up to X points" from the visible (top 2) fixes\' impacts, on the real allbirds fixture', () => {
    render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    // Visible: member_value +19, price_truth +14 -> 33 points.
    expect(screen.getByText('Two moves recover up to 33 points')).toBeInTheDocument()
  })

  it('pluralizes and sums correctly for a single visible fix', () => {
    const pillars = buildV3Pillars()
    pillars.fixes = { visible: [pillars.fixes.visible[0]], remaining_count: 3 }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText(/^One move recovers? up to \d+ points$/)).toBeInTheDocument()
  })

  it('sums to zero and reads "Zero moves" when there are no visible fixes at all', () => {
    const pillars = buildV3Pillars()
    pillars.fixes = { visible: [], remaining_count: 0 }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText('Zero moves recover up to 0 points')).toBeInTheDocument()
  })

  it('H2: no VIEW SNIPPET affordance and no markup/code ever renders in the v3 fixes section', () => {
    render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    expect(screen.queryByText('VIEW SNIPPET')).not.toBeInTheDocument()
    expect(screen.queryByText('HIDE SNIPPET')).not.toBeInTheDocument()
    const fixCard = screen.getByText('RANKED FIXES · ORDERED BY MODELED IMPACT').closest('.lite-card')
    expect(fixCard.querySelector('pre')).toBeNull()
  })

  it('H2 grep: no schema.org/JSON-LD vocabulary anywhere in the rendered fixes card', () => {
    render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    const fixCard = screen.getByText('RANKED FIXES · ORDERED BY MODELED IMPACT').closest('.lite-card')
    const text = fixCard.textContent
    for (const marker of ['@type', 'JSON-LD', '{', '<', 'schema.org', 'priceCurrency', 'Offer"']) {
      expect(text).not.toContain(marker)
    }
  })
})

describe('LiteFullReport — Stage 21 bug fix 2: rendered output never leaks the raw RS metric', () => {
  it('the RS gauge shows the banded plain-language line, and "rsi"/"scale" appear nowhere in the rendered report', () => {
    render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    const text = document.body.textContent.toLowerCase()
    expect(text).not.toContain('rsi')
    expect(text).not.toMatch(/scale -?\d/)
  })
})

describe('LiteFullReport — v3 charts render for 2 and 6 competitors, donut aria (Stage 21)', () => {
  it('renders correctly with only 1 competitor (2 entities total)', () => {
    const report = buildV3Report({
      competitor_source: 'manual',
      visibility_breakdown: {
        ...V3_VISIBILITY_BREAKDOWN,
        mention_rate: [
          { entity: 'Allbirds', is_primary: true, mentioned_queries: 8, total_queries: 12, rate_pct: 66.7 },
          { entity: "Rothy's", is_primary: false, mentioned_queries: 5, total_queries: 12, rate_pct: 41.7 },
        ],
        share_of_mentions: [
          { entity: 'Allbirds', is_primary: true, mentions: 8, share_pct: 62 },
          { entity: "Rothy's", is_primary: false, mentions: 5, share_pct: 38 },
        ],
      },
    })
    render(<LiteFullReport report={report} />)
    expect(screen.getByRole('img', { name: /Allbirds 62% of mentions, Rothy's 38% of mentions/ })).toBeInTheDocument()
  })

  it('renders correctly with 5 competitors (6 entities total) — donut aria-label lists every entity', () => {
    const shares = [
      { entity: 'Allbirds', is_primary: true, mentions: 7, share_pct: 35 },
      { entity: "Rothy's", is_primary: false, mentions: 4, share_pct: 20 },
      { entity: 'Cariuma', is_primary: false, mentions: 3, share_pct: 15 },
      { entity: 'Skechers', is_primary: false, mentions: 3, share_pct: 15 },
      { entity: 'Cole Haan', is_primary: false, mentions: 2, share_pct: 10 },
      { entity: 'Veja', is_primary: false, mentions: 1, share_pct: 5 },
    ]
    const report = buildV3Report({ visibility_breakdown: { ...V3_VISIBILITY_BREAKDOWN, share_of_mentions: shares } })
    render(<LiteFullReport report={report} />)
    const donut = screen.getByRole('img', { name: /Allbirds 35% of mentions/ })
    expect(donut.getAttribute('aria-label')).toContain('Veja 5% of mentions')
  })
})

describe('LiteFullReport — mobile render at 360px (Stage 21)', () => {
  const originalInnerWidth = window.innerWidth

  afterEach(() => {
    Object.defineProperty(window, 'innerWidth', { value: originalInnerWidth, configurable: true })
  })

  it('renders the full v3 report without throwing at a 360px viewport', () => {
    Object.defineProperty(window, 'innerWidth', { value: 360, configurable: true })
    expect(() => render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)).not.toThrow()
    // The v4 dimension row's duo-bar grid is CSS-driven (theme.css), not
    // conditionally rendered — its labels and every dimension name still
    // render in the DOM regardless of viewport width.
    expect(screen.getAllByText(/ON YOUR SITE/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/IN ANSWERS/).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Price Truth').length).toBeGreaterThan(0)
  })

  it('mobile: the mini-nav pill row stays a single scrollable line, not a wrapped column (Stage 22, F4)', () => {
    Object.defineProperty(window, 'innerWidth', { value: 360, configurable: true })
    const { container } = render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    // The structural fix is viewport-independent (it's not a media query
    // toggling flex-direction), so the same single-row nav DOM renders at
    // 360px as at desktop width — the horizontal scroll comes from
    // .lite-mini-nav-pills{overflow-x:auto}, not from a layout change.
    const pills = container.querySelector('.lite-mini-nav-pills')
    expect(pills).toBeInTheDocument()
    expect(pills.children.length).toBe(5)
  })
})

describe('LiteFullReport — Stage 22: full-width sticky mini-nav layout fix', () => {
  const THEME_CSS = fs.readFileSync(path.join(__dirname, '../theme.css'), 'utf8')

  function cssBlock(css, selector) {
    const re = new RegExp(selector.replace(/[.[\]]/g, '\\$&') + '\\s*\\{([^}]*)\\}')
    const match = css.match(re)
    return match ? match[1] : null
  }

  it('the mini-nav is NOT a row-flex sibling of the report content inside .lite-root — it is nested with .lite-shell under one .lite-page wrapper', () => {
    const { container } = render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    const root = container.querySelector('.lite-root')
    // .lite-root must keep exactly one direct child (every other view —
    // LiteForm/LiteProgress/LiteFailed — also mounts a single
    // child under it, and its CSS custom properties are scoped here) or
    // the old row-flex bug (nav left, content right) reappears.
    expect(root.children.length).toBe(1)
    const page = root.querySelector(':scope > .lite-page')
    expect(page).toBeInTheDocument()

    const pageChildren = Array.from(page.children)
    const nav = page.querySelector(':scope > .lite-mini-nav')
    const shell = page.querySelector(':scope > .lite-shell')
    expect(nav).toBeInTheDocument()
    expect(shell).toBeInTheDocument()
    // Nav renders above (before, in DOM order) the content wrapper —
    // stacked, not beside it.
    expect(pageChildren.indexOf(nav)).toBeLessThan(pageChildren.indexOf(shell))
  })

  it('the mini-nav has a two-layer structure: a full-width outer bar and a 720px-capped inner row matching the content width', () => {
    const { container } = render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    const nav = container.querySelector('.lite-mini-nav')
    const inner = nav.querySelector(':scope > .lite-mini-nav-inner')
    expect(inner).toBeInTheDocument()
    // Brand/composite + pills live in the inner row, not directly on the
    // full-width outer <nav>.
    expect(inner.querySelector('.lite-mini-nav-pills')).toBeInTheDocument()
  })

  it('every mini-nav anchor href resolves to a rendered section id in the document', () => {
    const { container } = render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    const pills = container.querySelectorAll('.lite-mini-nav-pill')
    expect(pills.length).toBe(5)
    pills.forEach((pill) => {
      const id = pill.getAttribute('href').slice(1)
      expect(container.querySelector(`#${id}`)).toBeInTheDocument()
    })
  })

  it('CSS: .lite-page centers a single full-width child in column direction, leaving .lite-root itself unchanged', () => {
    expect(cssBlock(THEME_CSS, '.lite-root')).toMatch(/display:\s*flex/)
    expect(cssBlock(THEME_CSS, '.lite-root')).toMatch(/justify-content:\s*center/)
    const page = cssBlock(THEME_CSS, '.lite-page')
    expect(page).toMatch(/display:\s*flex/)
    expect(page).toMatch(/flex-direction:\s*column/)
  })

  it('CSS: .lite-mini-nav spans the full outer width (no max-width cap); .lite-mini-nav-inner is capped at 720px like .lite-shell', () => {
    const nav = cssBlock(THEME_CSS, '.lite-mini-nav')
    expect(nav).toMatch(/width:\s*100%/)
    expect(nav).not.toMatch(/max-width/)
    const inner = cssBlock(THEME_CSS, '.lite-mini-nav-inner')
    expect(inner).toMatch(/max-width:\s*720px/)
  })

  it('CSS (F2): anchor targets get scroll-margin-top so a jump does not hide the section header under the sticky bar', () => {
    const rule = THEME_CSS.match(/\.lite-card\[id\],\s*\n?\s*\.lite-card-dark\[id\]\s*\{([^}]*)\}/)
    expect(rule).not.toBeNull()
    expect(rule[1]).toMatch(/scroll-margin-top:\s*\d+px/)
  })

  it('CSS (F3): a print stylesheet hides the mini-nav and removes the report-wrapper max-width, with no row-layout leaking through', () => {
    const printBlock = THEME_CSS.match(/@media print\s*\{([\s\S]*?)\n\}/)
    expect(printBlock).not.toBeNull()
    const body = printBlock[1]
    expect(body).toMatch(/\.lite-mini-nav\s*\{[^}]*display:\s*none/)
    expect(body).toMatch(/\.lite-shell\s*\{[^}]*max-width:\s*none/)
  })
})
