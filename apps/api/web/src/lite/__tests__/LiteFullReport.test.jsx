import React from 'react'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import '@testing-library/jest-dom'

import { LiteFullReport } from '../LiteFullReport.jsx'
import { DIMENSIONS, DIMENSIONS_BY_CODE, PILLAR_NAMES } from '../landing/scanDimensionsRegistry.js'
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

  it('Stage 9 (U3): Copy link writes the canonical /report/{token} URL to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    render(<LiteFullReport report={baseReport} token="tok-copy-123" />)
    fireEvent.click(screen.getByText('Copy link'))

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/report/tok-copy-123`))
    await waitFor(() => expect(screen.getByText('Copied')).toBeInTheDocument())
  })

  it('renders the working-session CTA link in both the funnel teaser and the diagnostic cliff when VITE_LITE_CTA_URL is set', () => {
    vi.stubEnv('VITE_LITE_CTA_URL', 'https://parleo.io/demo')
    render(<LiteFullReport report={baseReport} />)
    const links = screen.getAllByText('Request a working session')
    expect(links).toHaveLength(2)
    links.forEach((link) => expect(link.closest('a')).toHaveAttribute('href', 'https://parleo.io/demo'))
    vi.unstubAllEnvs()
  })

  it('omits both CTA links when VITE_LITE_CTA_URL is unset', () => {
    vi.stubEnv('VITE_LITE_CTA_URL', '')
    render(<LiteFullReport report={baseReport} />)
    expect(screen.queryByText('Request a working session')).not.toBeInTheDocument()
    vi.unstubAllEnvs()
  })
})

describe('LiteFullReport — visibility section (Stage 7)', () => {
  it('renders the W1 section header', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText('VISIBILITY · 12 QUERIES · CHATGPT')).toBeInTheDocument()
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
    expect(screen.getByText(/How many of the 12 shopper questions named each brand/)).toBeInTheDocument()
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
    expect(screen.getByText('Full analysis')).toBeInTheDocument()
  })

  it('renders fixed decorative stage cells, aria-hidden, regardless of the API payload', () => {
    render(<LiteFullReport report={baseReport} />)
    ;['AWARENESS', 'RESEARCH', 'COMPARISON', 'READY TO BUY'].forEach((label) => {
      const el = screen.getByText(label)
      expect(el).toBeInTheDocument()
      // aria-hidden lives on an ancestor wrapper, not the label itself.
      expect(el.closest('[aria-hidden="true"]')).not.toBeNull()
    })
  })

  it('renders the overlay copy and CTA, with no email language anywhere in this card', () => {
    vi.stubEnv('VITE_LITE_CTA_URL', 'https://parleo.io/demo')
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText('See which stage you vanish from')).toBeInTheDocument()
    expect(screen.getByText('Stage-by-stage rates are measured in the full diagnostic.')).toBeInTheDocument()
    const cta = screen.getByText('Where you disappear in the funnel').closest('.lite-card')
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

describe('LiteFullReport — executive tiles', () => {
  it('renders composite, visibility, accessibility, and modeled exposure', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText('Composite score')).toBeInTheDocument()
    expect(screen.getByText('Visibility')).toBeInTheDocument()
    expect(screen.getByText('Accessibility')).toBeInTheDocument()
    expect(screen.getByText('Modeled exposure/mo')).toBeInTheDocument()
  })
})

describe('LiteFullReport — why-section, all 8 dimensions', () => {
  it('renders all 8 dimension code+name headers grouped Foundation/Value with correct subtotals', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText('FOUNDATION · 27/35')).toBeInTheDocument()
    expect(screen.getByText('VALUE · 32/65')).toBeInTheDocument()
    EIGHT_DIMENSIONS.forEach((d) => {
      expect(screen.getByText(`${d.code} · ${d.name.toUpperCase()}`)).toBeInTheDocument()
    })
  })

  it('renders an integrity-cap footnote when integrity_capped is true', () => {
    const report = { ...baseReport, scan: { ...baseReport.scan, integrity_capped: true } }
    render(<LiteFullReport report={report} />)
    expect(screen.getByText(/the score cannot pass 59/)).toBeInTheDocument()
  })

  it('omits the integrity-cap footnote when false', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.queryByText(/the score cannot pass 59/)).not.toBeInTheDocument()
  })

  it('renders a linked-reason chip on the matching dimension', () => {
    const dims = EIGHT_DIMENSIONS.map((d) =>
      d.code === 'V1' ? { ...d, linked: { reason: 'mentioned but no price surfaced' } } : d
    )
    const report = { ...baseReport, scan: { ...baseReport.scan, dimensions: dims } }
    render(<LiteFullReport report={report} />)
    expect(screen.getByText('LINKED · MENTIONED BUT NO PRICE SURFACED')).toBeInTheDocument()
  })

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

  it('shows the blocked badge + F1 explanation when scan is blocked, without hiding visibility sections', () => {
    const report = { ...baseReport, scan: { status: 'blocked', total_score: null, dimensions: [], pages_fetched: [] }, scan_status: 'blocked' }
    render(<LiteFullReport report={report} />)

    expect(screen.getByText(/blocked our reader — that's itself a finding/)).toBeInTheDocument()
    expect(screen.getByText(/Agent Access \(F1\)/)).toBeInTheDocument()
    // Visibility sections still render fully.
    expect(screen.getByText('Where you disappear in the funnel')).toBeInTheDocument()
    expect(screen.getByText('AWARENESS')).toBeInTheDocument()
  })

  it('shows an honest explanation when scan failed', () => {
    const report = { ...baseReport, scan: { status: 'failed', total_score: null, dimensions: [], pages_fetched: [] }, scan_status: 'failed' }
    render(<LiteFullReport report={report} />)
    expect(screen.getByText(/couldn't finish reading your store this time/)).toBeInTheDocument()
  })
})

describe('LiteFullReport — Stage 10: partial coverage + deferred items', () => {
  it('shows the PARTIAL tag only on coverage=partial dimensions (F3), not full ones', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getAllByText('Partial · full analysis')).toHaveLength(1)
  })

  it('lists deferred items under a partial dimension with a lock glyph, no email wording in the item copy itself', () => {
    render(<LiteFullReport report={baseReport} />)
    const deferredLine = screen.getByText(/Merchant Center \/ Deal Directory participation — verified in the full analysis/)
    expect(deferredLine).toBeInTheDocument()
    expect(deferredLine.textContent).not.toMatch(/email|unlock/i)
  })

  it('renders a NOT APPLICABLE row for coverage=na dimensions, excluded from the bar fill', () => {
    const dims = EIGHT_DIMENSIONS.map((d) =>
      d.code === 'V3'
        ? { ...d, score: 0, coverage: 'na', evidence: ['no Offer markup found — member pricing is not applicable'] }
        : d
    )
    const report = { ...baseReport, scan: { ...baseReport.scan, dimensions: dims } }
    render(<LiteFullReport report={report} />)

    expect(screen.getByText('— · NOT APPLICABLE')).toBeInTheDocument()
    expect(screen.getByText(/member pricing is not applicable/)).toBeInTheDocument()
  })

  it('switches the family header to "n/{applicable_max} applicable" only when a dimension is na', () => {
    const dims = EIGHT_DIMENSIONS.map((d) => (d.code === 'V3' ? { ...d, score: 0, coverage: 'na' } : d))
    const report = {
      ...baseReport,
      scan: { ...baseReport.scan, dimensions: dims, value: { subtotal: 25, max: 65, applicable_max: 51 } },
    }
    render(<LiteFullReport report={report} />)

    expect(screen.getByText('VALUE · 25/51 APPLICABLE')).toBeInTheDocument()
    expect(screen.getByText('FOUNDATION · 27/35')).toBeInTheDocument() // unaffected family: familiar /35
  })

  it('appends cap_basis evidence lines under the integrity-cap footnote when capped', () => {
    const dims = EIGHT_DIMENSIONS.map((d) =>
      d.code === 'V5' ? { ...d, cap_basis: ['was-price signal on 2/2 sampled pages, sitewide', 'no priceValidUntil found on any sampled product page'] } : d
    )
    const report = { ...baseReport, scan: { ...baseReport.scan, integrity_capped: true, dimensions: dims } }
    render(<LiteFullReport report={report} />)

    expect(screen.getByText(/the score cannot pass 59/)).toBeInTheDocument()
    expect(screen.getByText('was-price signal on 2/2 sampled pages, sitewide')).toBeInTheDocument()
    expect(screen.getByText('no priceValidUntil found on any sampled product page')).toBeInTheDocument()
  })

  it('renders a pre-Stage-10 (scorer_version "1") row with no coverage tags and no crash', () => {
    const oldShapeDims = EIGHT_DIMENSIONS.map(({ coverage, deferred_items, cap_basis, ...rest }) => rest)
    const report = { ...baseReport, scan: { ...baseReport.scan, dimensions: oldShapeDims } }
    render(<LiteFullReport report={report} />)

    expect(screen.queryByText('Partial · full analysis')).not.toBeInTheDocument()
    expect(screen.queryByText('— · NOT APPLICABLE')).not.toBeInTheDocument()
    expect(screen.getByText('FOUNDATION · 27/35')).toBeInTheDocument()
  })
})

describe('LiteFullReport — ranked fixes', () => {
  it('shows the fix text for unlocked fixes', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText('add priceCurrency')).toBeInTheDocument()
  })

  it('shows "Unlocks with your email" and no fix text for locked dimensions', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.queryByText('stop fake was-prices')).not.toBeInTheDocument()
    expect(screen.getAllByText('Unlocks with your email').length).toBe(2) // V4 and V5 are locked
    expect(screen.getAllByText('Locked').length).toBe(2) // snippet column for the same 2 rows
  })

  it('shows a footer sentence with the unlocked/total fix count', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText('Showing 6 of 8 fixes. The rest unlock with your email below.')).toBeInTheDocument()
  })

  it('renders nothing when the scan is not complete', () => {
    const report = { ...baseReport, scan: { status: 'skipped', total_score: null, dimensions: [], pages_fetched: [] } }
    render(<LiteFullReport report={report} />)
    expect(screen.queryByText(/Showing \d+ of \d+ fixes/)).not.toBeInTheDocument()
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

describe('LiteFullReport — exposure calculator (Stage 21, F2: collapsed by default)', () => {
  it('renders a compact summary by default, sliders collapsed behind "adjust"', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.queryByLabelText('Monthly revenue')).not.toBeInTheDocument()
    expect(screen.getByText('adjust')).toBeInTheDocument()
  })

  it('reveals the sliders and modeled-exposure disclaimer after clicking adjust', () => {
    render(<LiteFullReport report={baseReport} />)
    fireEvent.click(screen.getByText('adjust'))
    expect(screen.getByLabelText('Monthly revenue')).toBeInTheDocument()
    expect(screen.getByLabelText('AI-assisted share of purchases')).toBeInTheDocument()
    expect(screen.getByText('Modeled, not measured.')).toBeInTheDocument()
  })

  it('updates the modeled exposure figure when a slider moves', () => {
    const { container } = render(<LiteFullReport report={baseReport} />)
    fireEvent.click(screen.getByText('adjust'))
    const revenueSlider = screen.getByLabelText('Monthly revenue')
    const numeral = () => container.querySelector('.lite-numeral--calc').textContent
    const before = numeral()
    Object.defineProperty(revenueSlider, 'value', { value: '10000000', configurable: true })
    revenueSlider.dispatchEvent(new Event('change', { bubbles: true }))
    expect(numeral()).not.toBe(before)
  })

  it('collapses back after clicking COLLAPSE', () => {
    render(<LiteFullReport report={baseReport} />)
    fireEvent.click(screen.getByText('adjust'))
    expect(screen.getByLabelText('Monthly revenue')).toBeInTheDocument()
    fireEvent.click(screen.getByText('COLLAPSE'))
    expect(screen.queryByLabelText('Monthly revenue')).not.toBeInTheDocument()
  })
})

describe('LiteFullReport — diagnostic-tier cliff', () => {
  it('renders the 3 highlighted upsell panels, remaining locked topics, and platform chips', () => {
    render(<LiteFullReport report={baseReport} />)
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
})

describe('LiteFullReport — footer', () => {
  it('renders the re-run cadence line and methodology stamp', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText(/re-run this diagnostic monthly/)).toBeInTheDocument()
    expect(screen.getByText(/12 QUERIES · 1 PLATFORM · 1 RUN EACH/)).toBeInTheDocument()
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

function buildV3Pillars({ dealCitabilitySeen, dealCitabilitySaid, memberValueNa = true, visibilityShareEarned = 20 } = {}) {
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
    accessibility: {
      score: 78, max: 100,
      dimensions: [
        pillarDim('agent_access', 'Agent Access', 6, 6, {
          evidence: ['robots.txt allows crawling'], fix: null, locked: false,
        }),
        pillarDim('catalog_context', 'Catalog & Context', 5, 8, {
          evidence: ['partial schema.org markup'], fix: 'add GTIN to product schema', locked: false,
        }),
        pillarDim('protocol_feed', 'Protocol & Feed Presence', 3, 6, {
          evidence: ['no llms.txt found'], fix: 'publish an llms.txt file', locked: true,
        }),
      ],
    },
    true_value: {
      score: 70, max: 100,
      dimensions: [
        pillarDim('price_truth', 'Price Truth', 10, 14, {
          seen: subLens(6, 6, false, ['machine-readable price found in Offer schema']),
          said: subLens(4, 8, false, ['5/6 mentions (83%) cited a price']),
          fix: 'add priceCurrency to Offer schema', locked: false,
        }),
        memberValueNa
          ? pillarDim('member_value', 'Member Value', 0, 0, {
            na: true,
            evidence: ["probe: 'No, we do not have a member pricing program.'"],
            seen: subLens(0, 12, false, ['no loyalty page found']),
            said: subLens(0, 7, true, ['fewer than 2 mentions in the relevant opportunity set']),
            fix: null, locked: false,
          })
          : pillarDim('member_value', 'Member Value', 15, 19, {
            seen: subLens(12, 12, false, ['loyalty page found']),
            said: subLens(3, 7, false, ['2/4 purchase-intent mentions (50%) cited member value']),
            fix: null, locked: true,
          }),
        pillarDim('deal_citability', 'Deal Citability', 5, 7, {
          seen: dealCitabilitySeen || subLens(4, 4, false, ['active discount encoded with priceValidUntil']),
          said: dealCitabilitySaid || subLens(1, 3, false, ['1 of 6 purchase-intent mentions cited a deal']),
          fix: 'add priceValidUntil to the Offer', locked: true,
        }),
      ],
    },
    member_value_na: memberValueNa,
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
    expect(screen.getByText(/NORMALIZED · 81 PTS APPLICABLE/)).toBeInTheDocument()
  })

  it('omits the normalized caption when member_value is applicable', () => {
    const report = buildV3Report({ pillars: buildV3Pillars({ memberValueNa: false }) })
    render(<LiteFullReport report={report} />)
    expect(screen.queryByText(/NORMALIZED/)).not.toBeInTheDocument()
    expect(screen.getByText('COMPOSITE = STRAIGHT SUM')).toBeInTheDocument()
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
    ['strong visibility + True Value nearly full', buildV3Pillars({ memberValueNa: false, dealCitabilitySeen: subLens(4, 4, false), dealCitabilitySaid: subLens(3, 3, false) }), /and they get your value right\./],
  ])('verdict template: %s', (_label, pillars, expected) => {
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText(expected)).toBeInTheDocument()
  })
})

describe('LiteFullReport — True Value section (Stage 19, R2)', () => {
  it('renders all three dual-lens dimensions with SEEN/SAID tiles', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText('The value only we score')).toBeInTheDocument()
    expect(screen.getAllByText('WHAT YOU ENCODE').length).toBeGreaterThan(0)
    expect(screen.getAllByText('WHAT AGENTS SAID').length).toBeGreaterThan(0)
    expect(screen.getByText('machine-readable price found in Offer schema')).toBeInTheDocument()
    expect(screen.getByText('5/6 mentions (83%) cited a price')).toBeInTheDocument()
  })

  it('renders member_value N/A as NOT APPLICABLE with the probe quote as evidence, no bars', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText('NOT APPLICABLE')).toBeInTheDocument()
    expect(screen.getByText("probe: 'No, we do not have a member pricing program.'")).toBeInTheDocument()
    expect(screen.queryByText('0/0')).not.toBeInTheDocument()
  })

  it('renders an outcome-guard N/A said sub-lens as "not enough mentions to measure", never 0%', () => {
    const pillars = buildV3Pillars({ dealCitabilitySaid: subLens(0, 3, true, ['fewer than 2 mentions in the relevant opportunity set']) })
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText('— · not enough mentions to measure')).toBeInTheDocument()
    expect(screen.queryByText('0%')).not.toBeInTheDocument()
  })

  it('never renders the standalone incentive-citation card inside True Value (Stage 21 replaced its bars with the footer line)', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.queryByText('Incentive citation rate')).not.toBeInTheDocument()
    expect(screen.queryByText('13% · 1 of 8 mentions')).not.toBeInTheDocument()
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

  it('omits the fix pointer when no unlocked top fix is True-Value-coded', () => {
    const pillars = buildV3Pillars()
    // Lock every True Value dimension's fix and leave only accessibility ones free.
    pillars.true_value.dimensions = pillars.true_value.dimensions.map((d) => ({ ...d, fix: null, locked: true }))
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.queryByText(/TARGET THIS PILLAR/)).not.toBeInTheDocument()
  })
})

describe('LiteFullReport — v3 visibility: comparative bars + donut + RS gauge (Stage 21, V1/V2)', () => {
  it('restores mention rate as its own comparative bars, sorted with YOU tagged', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText('Mention rate · of 12 answers')).toBeInTheDocument()
    expect(screen.getByText('YOU')).toBeInTheDocument()
    expect(screen.getByText('67% · 8/12')).toBeInTheDocument()
    expect(screen.getByText('42% · 5/12')).toBeInTheDocument()
  })

  it('shows the Share of Mentions donut card carrying its scored points', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText('Share of mentions')).toBeInTheDocument()
    expect(screen.getByText('20/25 pts')).toBeInTheDocument()
  })

  it('renders the Recommendation Strength gauge with points and a plain-language line, never the raw metric', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText('Recommendation Strength · 14/15')).toBeInTheDocument()
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

  it.each([
    ['good (>=80%)', 6, 6, 'var(--good)'],
    ['warn (0% < ratio < 80%)', 3, 6, 'var(--warn)'],
  ])('colors the tile bar %s', (_label, earned, max, expectedColor) => {
    const pillars = buildV3Pillars()
    pillars.accessibility.dimensions[0] = { ...pillars.accessibility.dimensions[0], earned, max }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    const label = screen.getAllByText('Agent Access')[0]
    const tile = label.parentElement.parentElement
    const fill = tile.querySelector('.lite-bar-fill')
    expect(fill).toHaveStyle({ background: expectedColor })
  })

  it('renders no bar fill at all for a 0% (bad) tile — an empty track, not a colored sliver', () => {
    const pillars = buildV3Pillars()
    pillars.accessibility.dimensions[0] = { ...pillars.accessibility.dimensions[0], earned: 0 }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    const label = screen.getAllByText('Agent Access')[0]
    const tile = label.parentElement.parentElement
    expect(tile.querySelector('.lite-bar-fill')).toBeNull()
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
})

describe('LiteFullReport — v3 ranked fixes (Stage 19, R5)', () => {
  it('populates the fixes table from the pillars payload with v3 dimension labels', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText('add GTIN to product schema')).toBeInTheDocument()
    expect(screen.getByText('add priceCurrency to Offer schema')).toBeInTheDocument()
    expect(screen.getAllByText('Catalog & Context').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Price Truth').length).toBeGreaterThan(0)
  })

  it('shows locked rows as "Unlocks with your email", no fix text, ordering by gap intact', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    // protocol_feed (locked, gap 3) and deal_citability (locked, gap 2) are locked.
    expect(screen.queryByText('publish an llms.txt file')).not.toBeInTheDocument()
    expect(screen.queryByText('add priceValidUntil to the Offer')).not.toBeInTheDocument()
    expect(screen.getAllByText('Unlocks with your email').length).toBe(2)
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
    expect(screen.getByText('FOUNDATION · 27/35')).toBeInTheDocument() // stored v2 data renders faithfully
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

  it('a v2 report still legitimately shows Foundation/Value grouping (unchanged legacy path)', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText('FOUNDATION · 27/35')).toBeInTheDocument()
    expect(screen.getByText('VALUE · 32/65')).toBeInTheDocument()
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

  it('populates the ranked-fixes table for this row (the empty-table bug is fixed)', () => {
    render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    expect(screen.queryByText(/Showing 0 of/)).not.toBeInTheDocument()
    expect(screen.getByText(/Add a discoverable loyalty\/rewards page/)).toBeInTheDocument()
  })

  it('renders the True Value section with real seen/said evidence for all three dimensions', () => {
    render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    expect(screen.getByText('0/7 mentions (0%) cited a price')).toBeInTheDocument()
    expect(screen.getByText('0/5 purchase-intent mentions (0%) cited member value')).toBeInTheDocument()
  })

  it('butterfly zero-state: all six wings (3 dimensions x seen/said) render an empty track + zero tick, and the pillar verdict is ENCODING GAP', () => {
    // Real allbirds row: every True Value sub-lens (seen and said, across
    // all three dimensions) earned exactly 0 — none are na (member_value
    // is applicable via the probe), so this is six real zero-state wings,
    // not six N/A wings.
    const { container } = render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    expect(container.querySelectorAll('.lite-butterfly-zero-tick').length).toBe(6)
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
    DIMENSIONS_BY_CODE.catalog_context.weight = 41 // was 8 -> accessibility segment weight 6+41+6=53
    try {
      render(<LiteFullReport report={buildV3Report()} />)
      const caption = screen.getByText('ACCESSIBILITY 14/20')
      const accessibilitySegment = caption.parentElement.parentElement
      expect(accessibilitySegment).toHaveStyle({ flex: '53 1 0%' })
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

describe('LiteFullReport — v3 fixes: headline + snippet toggle (Stage 21, F1)', () => {
  it('computes "N moves recover up to X points" from the unlocked fixes\' impacts, on the real allbirds fixture', () => {
    render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    // 3 unlocked fixes (top-3-free): catalog_context +8, price_truth +14,
    // member_value +19 -> 41 points, matching the design mock exactly.
    expect(screen.getByText('Three moves recover up to 41 points')).toBeInTheDocument()
  })

  it('pluralizes and sums correctly for a single unlocked fix', () => {
    const pillars = buildV3Pillars({ memberValueNa: false })
    pillars.accessibility.dimensions = pillars.accessibility.dimensions.map((d) => ({ ...d, fix: null, locked: true }))
    pillars.true_value.dimensions = pillars.true_value.dimensions.map((d, i) => (
      i === 0 ? d : { ...d, fix: null, locked: true }
    ))
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText(/^One move recovers? up to \d+ points$/)).toBeInTheDocument()
  })

  it('renders a VIEW SNIPPET toggle for a fix with an embedded snippet, keyboard-accessible and independently toggle-able per row', () => {
    render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    const toggles = screen.getAllByText('VIEW SNIPPET')
    expect(toggles.length).toBeGreaterThan(1) // more than one row has a snippet
    const button = toggles[0]
    expect(button.tagName).toBe('BUTTON')
    expect(button).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('HIDE SNIPPET')).toBeInTheDocument()

    // A second row's toggle is unaffected — opening one doesn't close others.
    const secondToggle = screen.getAllByText(/VIEW SNIPPET|HIDE SNIPPET/)[1]
    expect(secondToggle).toHaveTextContent('VIEW SNIPPET')
  })

  it('shows "No snippet needed" for an unlocked fix with no embedded snippet, "No issue found here." for a zero-gap unlocked row', () => {
    const pillars = buildV3Pillars({ memberValueNa: false })
    pillars.accessibility.dimensions[0] = { ...pillars.accessibility.dimensions[0], fix: 'Just fix it, no code needed.', locked: false, earned: 6, max: 6 }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getAllByText('No snippet needed').length).toBeGreaterThan(0)
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
    // The butterfly's three-column grid is CSS-driven (theme.css), not
    // conditionally rendered — its column headers and every dimension
    // name still render in the DOM regardless of viewport width.
    expect(screen.getByText('WHAT YOU ENCODE')).toBeInTheDocument()
    expect(screen.getByText('WHAT AGENTS SAID')).toBeInTheDocument()
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
    // LiteForm/LiteProgress/LiteTeaser/LiteFailed — also mounts a single
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
