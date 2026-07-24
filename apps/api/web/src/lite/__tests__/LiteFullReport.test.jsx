import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import '@testing-library/jest-dom'

import { LiteFullReport } from '../LiteFullReport.jsx'

function dim(code, name, score, max, overrides = {}) {
  return { code, name, score, max, evidence: [], fix: null, locked: false, linked: null, ...overrides }
}

const EIGHT_DIMENSIONS = [
  dim('F1', 'Agent Access', 8, 10),
  dim('F2', 'Catalog Context', 10, 15),
  dim('F3', 'Transaction Rails', 9, 10),
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
