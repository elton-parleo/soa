import React from 'react'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import '@testing-library/jest-dom'

import { LiteFullReport } from '../LiteFullReport.jsx'
import { DIMENSIONS, DIMENSIONS_BY_CODE } from '../landing/scanDimensionsRegistry.js'
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

describe('LiteFullReport — exposure calculator', () => {
  it('renders the sliders and modeled-exposure disclaimer', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByLabelText('Monthly revenue')).toBeInTheDocument()
    expect(screen.getByLabelText('AI-assisted share of purchases')).toBeInTheDocument()
    expect(screen.getByText('Modeled, not measured.')).toBeInTheDocument()
  })

  it('updates the modeled exposure figure when a slider moves', () => {
    const { container } = render(<LiteFullReport report={baseReport} />)
    const revenueSlider = screen.getByLabelText('Monthly revenue')
    const numeral = () => container.querySelector('.lite-numeral--calc').textContent
    const before = numeral()
    Object.defineProperty(revenueSlider, 'value', { value: '10000000', configurable: true })
    revenueSlider.dispatchEvent(new Event('change', { bubbles: true }))
    expect(numeral()).not.toBe(before)
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

function buildV3Pillars({ dealCitabilitySeen, dealCitabilitySaid, memberValueNa = true } = {}) {
  return {
    visibility: {
      score: 90, max: 100,
      dimensions: [
        pillarDim('share_of_mentions', 'Share of Mentions', 20, 25, {
          evidence: ['42.0% share of mentions across all tracked brands'],
        }),
        pillarDim('recommendation_strength', 'Recommendation Strength', 14, 15, {
          evidence: ['rsi_score 2.80 (scale -1 to +3)'],
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

describe('LiteFullReport — v3 executive tiles (Stage 19, R1)', () => {
  it('renders three pillar tiles with earned/max from the pillars payload, and the composite', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText('Visibility')).toBeInTheDocument()
    expect(screen.getByText('Accessibility')).toBeInTheDocument()
    expect(screen.getByText('True Value')).toBeInTheDocument()
    expect(screen.getByText('34')).toBeInTheDocument() // visibility earned (20+14)
    expect(screen.getByText('14')).toBeInTheDocument() // accessibility earned (6+5+3)
    expect(screen.getByText('84')).toBeInTheDocument() // composite tile
  })

  it('shows the normalized-81-applicable caption when member_value is N/A', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText(/NORMALIZED · 81 PTS APPLICABLE/)).toBeInTheDocument()
  })

  it('omits the normalized caption when member_value is applicable', () => {
    const report = buildV3Report({ pillars: buildV3Pillars({ memberValueNa: false }) })
    render(<LiteFullReport report={report} />)
    expect(screen.queryByText(/NORMALIZED/)).not.toBeInTheDocument()
  })

  it('never renders the old two-dial layout (Visibility/Accessibility with no third tile) for a v3 row', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    // The v3 tiles always render alongside True Value — a bare two-dial
    // pair (the pre-Stage-19 layout) never appears without it.
    expect(screen.getByText('Visibility')).toBeInTheDocument()
    expect(screen.getByText('Accessibility')).toBeInTheDocument()
    expect(screen.getByText('True Value')).toBeInTheDocument()
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

  it.each([
    ['working', subLens(3, 4, false), subLens(2, 3, false), 'Encoded and cited — this is working.'],
    ['distribution gap', subLens(4, 4, false), subLens(0, 3, false), 'Encoded, but agents rarely cite it — a distribution gap, not an encoding gap.'],
    ['encoding gap', subLens(0, 4, false), subLens(0, 3, false), "Little encoded to cite, and agents aren't citing it."],
    ['cited elsewhere', subLens(0, 4, false), subLens(2, 3, false), 'Agents cite a deal despite little encoded on the page — likely sourced from elsewhere.'],
  ])('deal citability quadrant verdict: %s', (_label, seen, said, expectedText) => {
    const pillars = buildV3Pillars({ dealCitabilitySeen: seen, dealCitabilitySaid: said })
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.getByText(expectedText)).toBeInTheDocument()
  })

  it('absorbs the incentive-citation rows into the True Value section and drops the standalone card', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    // The old standalone card's own title/subtitle must be gone...
    expect(screen.queryByText('Incentive citation rate')).not.toBeInTheDocument()
    // ...but its per-entity rows (reused inside Deal Citability) still render.
    expect(screen.getByText('13% · 1 of 8 mentions')).toBeInTheDocument()
    expect(screen.getByText('40% · 2 of 5 mentions')).toBeInTheDocument()
  })
})

describe('LiteFullReport — v3 visibility section (Stage 19, R3)', () => {
  it('shows Recommendation Strength and Share of Mentions cards carrying scored points', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText('Recommendation Strength')).toBeInTheDocument()
    expect(screen.getByText('14/15 pts')).toBeInTheDocument()
    expect(screen.getByText('20/25 pts')).toBeInTheDocument()
  })

  it('renders mention rate as context inside the Share of Mentions card, not its own scored panel', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.queryByText('Mention rate')).not.toBeInTheDocument() // old standalone card title, gone
    expect(screen.getByText('MENTION RATE')).toBeInTheDocument() // context label inside the SoM card
    expect(screen.getByText(/67% · 8\/12/)).toBeInTheDocument()
  })
})

describe('LiteFullReport — v3 accessibility + methodology (Stage 19, R4)', () => {
  it('regroups accessibility under an Accessibility · n/20 header with the three v3 dimensions', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText('ACCESSIBILITY · 14/20')).toBeInTheDocument()
    expect(screen.getByText('AGENT ACCESS')).toBeInTheDocument()
    expect(screen.getByText('CATALOG & CONTEXT')).toBeInTheDocument()
    expect(screen.getByText('PROTOCOL & FEED PRESENCE')).toBeInTheDocument()
  })

  it('renders the three-pillar methodology legend with registry weights summing to 100', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText('VISIBILITY 40')).toBeInTheDocument()
    expect(screen.getByText('ACCESSIBILITY 20')).toBeInTheDocument()
    expect(screen.getByText('TRUE VALUE 40')).toBeInTheDocument()
    expect(screen.getByText('= 100')).toBeInTheDocument()
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

  it('never renders a crosswalk chip on an na dimension', () => {
    const pillars = buildV3Pillars()
    pillars.accessibility.dimensions[2] = {
      ...pillars.accessibility.dimensions[2],
      na: true,
      linked: { reason: 'absent from most answers' },
    }
    render(<LiteFullReport report={buildV3Report({ pillars })} />)
    expect(screen.queryByText(/^LINKED ·/)).not.toBeInTheDocument()
  })
})

describe('LiteFullReport — v3 ranked fixes (Stage 19, R5)', () => {
  it('populates the fixes table from the pillars payload with v3 dimension labels', () => {
    render(<LiteFullReport report={buildV3Report()} />)
    expect(screen.getByText('add GTIN to product schema')).toBeInTheDocument()
    expect(screen.getByText('add priceCurrency to Offer schema')).toBeInTheDocument()
    expect(screen.getByText('Catalog & Context')).toBeInTheDocument()
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
    expect(screen.getByText('Allbirds')).toBeInTheDocument()
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

  it('remaps this real row\'s crosswalk reasons (originally F1/F2) onto their v3 dimensions', () => {
    render(<LiteFullReport report={ALLBIRDS_V3_REPORT} />)
    expect(screen.getAllByText('LINKED · ABSENT FROM MOST ANSWERS').length).toBe(2) // agent_access + catalog_context
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

  it('perturbing a dimension weight moves the rendered methodology-legend pillar total', () => {
    // MethodologyLegend sums DIMENSIONS live on every render (never a
    // cached export) — same discipline as AnatomyOfAnAnswer's PillarCard.
    const original = DIMENSIONS_BY_CODE.catalog_context.weight
    DIMENSIONS_BY_CODE.catalog_context.weight = 41 // was 8 -> accessibility total 6+41+6=53
    try {
      render(<LiteFullReport report={buildV3Report()} />)
      expect(screen.getByText('ACCESSIBILITY 53')).toBeInTheDocument()
      expect(screen.getByText('= 133')).toBeInTheDocument() // 40 (visibility) + 53 + 40 (true_value)
      expect(screen.queryByText('ACCESSIBILITY 20')).not.toBeInTheDocument()
    } finally {
      DIMENSIONS_BY_CODE.catalog_context.weight = original
    }
  })
})
