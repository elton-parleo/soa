/**
 * The tier section of the Full Analysis report.
 *
 * What is being held to here is honesty about absence: a rate with no
 * sample renders a state chip and not a zero, a tier that could not be
 * built says so rather than reading as 0%, and the validated agreement
 * rate is blank in words until a human records one.
 */
import React from 'react'
import { render, screen, within } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import { TierAccuracySection } from '../TierAccuracySection.jsx'

function tier(overrides = {}) {
  return {
    tier: 'catalog_accuracy',
    label: 'Catalog accuracy',
    counts: { exact: 6, stale: 2, wrong: 2, absent: 3, unscoreable: 1 },
    scored: 10,
    samples: 14,
    accuracy: 0.6,
    staleness: 0.2,
    wrong_rate: 0.2,
    answered_rate: 0.7692,
    unscoreable_rate: 0.0714,
    visibility: { runs: 14, mentioned: 11, rate: 0.7857 },
    source_attribution: { brand_domain: 4, retailer: 8, none: 2 },
    secondary: [
      {
        type: 'gtin', label: 'GTIN volunteered',
        counts: { exact: 1, stale: 0, wrong: 0, absent: 13, unscoreable: 0 },
        scored: 1, samples: 14, accuracy: 1, staleness: 0,
        answered_rate: 0.0714, unscoreable_rate: 0,
      },
      {
        type: 'pack_count', label: 'Pack count',
        counts: { exact: 8, stale: 0, wrong: 2, absent: 4, unscoreable: 0 },
        scored: 10, samples: 14, accuracy: 0.8, staleness: 0,
        answered_rate: 0.7143, unscoreable_rate: 0,
      },
    ],
    surfaces: [{
      platform: 'chatgpt',
      counts: { exact: 6, stale: 2, wrong: 2, absent: 3, unscoreable: 1 },
      scored: 10, samples: 14, accuracy: 0.6, staleness: 0.2,
      unscoreable_rate: 0.0714,
      visibility: { runs: 14, mentioned: 11, rate: 0.7857 },
    }],
    ...overrides,
  }
}

function section(overrides = {}) {
  return {
    tiers: [tier()],
    value_survival: 0.75,
    value_survival_samples: 8,
    study: {
      syndicated_merchant: 'wiggle-and-snug',
      merchant: { brand: 'Wiggle & Snug', domain: 'trueshopstore.com' },
      expected_nulls: {},
      unavailable: {},
    },
    extraction_validation: null,
    ...overrides,
  }
}

function renderSection(props = {}) {
  return render(
    <TierAccuracySection
      tierAccuracy={props.tierAccuracy === undefined ? section() : props.tierAccuracy}
      open
      onToggle={() => {}}
      {...props}
    />,
  )
}

// ── absence ──────────────────────────────────────────────────────────────

describe('when there is nothing to report', () => {
  it('renders nothing at all rather than an empty panel', () => {
    const { container } = renderSection({ tierAccuracy: null })
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing when the section exists but has no tiers', () => {
    const { container } = renderSection({ tierAccuracy: section({ tiers: [] }) })
    expect(container).toBeEmptyDOMElement()
  })
})

// ── the five outcomes ────────────────────────────────────────────────────

describe('the outcome columns', () => {
  it('shows all five, including unreadable as its own column', () => {
    renderSection()
    for (const label of ['Exact', 'Stale', 'Wrong', 'Not addressed', 'Unreadable']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0)
    }
  })

  it('counts every outcome, not only the scored ones', () => {
    renderSection()
    const row = screen.getByTestId('tier-row-catalog_accuracy')
    // 6 exact, 2 stale, 2 wrong, 3 absent, 1 unscoreable.
    expect(row).toHaveTextContent('6')
    expect(row).toHaveTextContent('3')
    expect(row).toHaveTextContent('1')
  })
})

// ── rates carry their sample ─────────────────────────────────────────────

describe('rates', () => {
  it('never appear without the sample they rest on', () => {
    renderSection()
    const row = screen.getByTestId('tier-row-catalog_accuracy')
    expect(row).toHaveTextContent('60%')
    expect(row).toHaveTextContent('n=10 scored')
    expect(row).toHaveTextContent('79%')
    expect(row).toHaveTextContent('n=14 runs')
  })

  it('render a state chip, not a zero, when there is no sample', () => {
    renderSection({
      tierAccuracy: section({
        tiers: [tier({
          tier: 'category_control', label: 'Category control',
          counts: { exact: 0, stale: 0, wrong: 0, absent: 5, unscoreable: 0 },
          scored: 0, accuracy: null, staleness: null,
        })],
      }),
    })
    const row = screen.getByTestId('tier-row-category_control')
    expect(within(row).getAllByText('No sample').length).toBeGreaterThan(0)
    expect(row).not.toHaveTextContent('0%')
  })

  it('render a measured zero as zero', () => {
    renderSection({
      tierAccuracy: section({ tiers: [tier({ accuracy: 0, scored: 4 })] }),
    })
    expect(screen.getByTestId('tier-row-catalog_accuracy')).toHaveTextContent('0%')
  })
})

// ── value survival ───────────────────────────────────────────────────────

describe('value survival', () => {
  it('is stated with its sample', () => {
    renderSection()
    const block = screen.getByTestId('value-survival')
    expect(block).toHaveTextContent('75%')
    expect(block).toHaveTextContent('n=8 scored')
  })

  it('is omitted when the value tier was not run', () => {
    renderSection({ tierAccuracy: section({ value_survival: null }) })
    expect(screen.queryByTestId('value-survival')).not.toBeInTheDocument()
  })
})

// ── the validated agreement rate ─────────────────────────────────────────

describe('the extraction validation line', () => {
  it('says "not validated" in words rather than printing a number', () => {
    renderSection()
    const block = screen.getByTestId('extraction-validation')
    expect(block).toHaveTextContent('Not validated')
    expect(block).toHaveTextContent(/No hand-check of the extraction pass/)
    expect(block).not.toHaveTextContent('%')
  })

  it('states the recorded rate once a human has recorded one', () => {
    renderSection({
      tierAccuracy: section({
        extraction_validation: {
          sample_size: 40, agreed: 37, agreement_rate: 0.925,
          validated_by: 'elton', validated_at: '2026-09-10T12:00:00Z',
        },
      }),
    })
    const block = screen.getByTestId('extraction-validation')
    expect(block).toHaveTextContent('Extraction validated at 93%')
    expect(block).toHaveTextContent('40 hand-checked answers')
    expect(block).toHaveTextContent('elton')
  })
})

// ── the header context ───────────────────────────────────────────────────

describe('the header context', () => {
  it('renders the expected-nulls notes the study wrote before the run', () => {
    renderSection({
      tierAccuracy: section({
        study: {
          ...section().study,
          expected_nulls: {
            category_control: 'Near zero. Wiggle & Snug is not expected to win these.',
          },
        },
      }),
    })
    expect(screen.getByTestId('expected-nulls')).toHaveTextContent(
      'Near zero. Wiggle & Snug is not expected to win these.',
    )
  })

  it('says a tier could not be built rather than letting it read as zero', () => {
    renderSection({
      tierAccuracy: section({
        study: {
          ...section().study,
          unavailable: { value_incentives: '504 from TrueSync' },
        },
      }),
    })
    const block = screen.getByTestId('tier-unavailable')
    expect(block).toHaveTextContent('Not built')
    expect(block).toHaveTextContent('504 from TrueSync')
    expect(block).toHaveTextContent('not scored at zero')
  })

  it('names the brand the study is grounded in', () => {
    renderSection()
    expect(screen.getByText(/WIGGLE & SNUG/)).toBeInTheDocument()
  })
})

// ── per surface ──────────────────────────────────────────────────────────

describe('the per-surface table', () => {
  it('shows one row per tier and surface', () => {
    renderSection()
    const row = screen.getByTestId('surface-row-catalog_accuracy-chatgpt')
    expect(row).toHaveTextContent('chatgpt')
    expect(row).toHaveTextContent('60%')
  })
})

// ── source attribution ───────────────────────────────────────────────────

describe('the source attribution table', () => {
  it('keeps brand-domain and retailer citations as separate counts', () => {
    renderSection()
    const row = screen.getByTestId('source-row-catalog_accuracy')
    expect(row).toHaveTextContent('4')
    expect(row).toHaveTextContent('8')
    expect(row).toHaveTextContent('2')
  })
})

// ── the drill-down affordance ────────────────────────────────────────────

describe('the drill-down', () => {
  it('is offered when a handler is given', () => {
    const calls = []
    renderSection({ onDrillDown: (t) => calls.push(t) })
    screen.getByRole('button', { name: 'Catalog accuracy' }).click()
    expect(calls).toEqual(['catalog_accuracy'])
  })

  it('is absent for a viewer with no handler, and the label still renders', () => {
    renderSection({ onDrillDown: undefined })
    expect(screen.queryByRole('button', { name: 'Catalog accuracy' })).not.toBeInTheDocument()
    // The label appears in the tier table and again in the per-surface
    // table — both as plain text, neither as a control.
    expect(screen.getAllByText('Catalog accuracy').length).toBeGreaterThan(0)
  })
})

// ── secondary signals ────────────────────────────────────────────────────

describe('the volunteered-alongside table', () => {
  it('gives each secondary its own row, rate and sample', () => {
    renderSection()
    const row = screen.getByTestId('secondary-row-catalog_accuracy-pack_count')
    expect(row).toHaveTextContent('Pack count')
    expect(row).toHaveTextContent('80%')
    expect(row).toHaveTextContent('n=10 stated')
    expect(row).toHaveTextContent('n=14 answers')
  })

  it('keeps GTIN and pack count as separate rows', () => {
    renderSection()
    expect(screen.getByTestId('secondary-row-catalog_accuracy-gtin')).toBeInTheDocument()
    expect(screen.getByTestId('secondary-row-catalog_accuracy-pack_count')).toBeInTheDocument()
  })

  it('says neither moves the accuracy above it', () => {
    renderSection()
    expect(screen.getByText(/Neither is asked for, so neither moves the accuracy/))
      .toBeInTheDocument()
  })

  it('warns that a restated pack count is an echo, not knowledge', () => {
    renderSection()
    expect(screen.getByText(/echoing\s+the question rather than knowing it/))
      .toBeInTheDocument()
  })

  it('is omitted entirely when no tier carries a secondary', () => {
    renderSection({
      tierAccuracy: section({ tiers: [tier({ secondary: [] })] }),
    })
    expect(screen.queryByText(/Volunteered alongside/)).not.toBeInTheDocument()
  })
})

// ─── The brand-direct split ───────────────────────────────────────────────
//
// Shaped as tier_accuracy.py now produces it for cycle
// 20260915-113207-wiggle-snug-full: 66 runs, 33 per surface, two of which
// cited the brand's own record.

function assessments(counts, assessed) {
  const order = ['grounded', 'echoed', 'misattributed', 'fabricated', 'acknowledged_unknown']
  const label = {
    grounded: 'Grounded', echoed: 'Brand echoed', misattributed: 'Misattributed',
    fabricated: 'Fabricated', acknowledged_unknown: 'Said it could not find us',
  }
  return order.map((o) => ({
    outcome: o, label: label[o], count: counts[o] || 0,
    rate: assessed ? Math.round(((counts[o] || 0) / assessed) * 10000) / 10000 : null,
  }))
}

const BRAND_TIER = {
  tier: 'brand_direct', label: 'Brand-direct',
  counts: {
    grounded: 2, echoed: 16, misattributed: 13, fabricated: 6,
    acknowledged_unknown: 26, absent: 3, unscoreable: 0,
  },
  assessments: assessments(
    { grounded: 2, echoed: 16, misattributed: 13, fabricated: 6, acknowledged_unknown: 26 },
    63,
  ),
  assessed: 63, samples: 66, scored: 63,
  accuracy: null, staleness: null, wrong_rate: null,
  grounded_rate: 0.0317, harmful_rate: 0.3016,
  visibility_retired: 'Reported as Brand echoed below. Naming the brand is not the same as knowing it.',
  source_attribution: { brand_domain: 2, retailer: 37, none: 27 },
  secondary: [], near_miss: 0,
  surfaces: [
    {
      platform: 'chatgpt', assessed: 31, samples: 33,
      counts: { grounded: 2, echoed: 4, misattributed: 11, fabricated: 0, acknowledged_unknown: 14, absent: 2 },
      assessments: assessments(
        { grounded: 2, echoed: 4, misattributed: 11, fabricated: 0, acknowledged_unknown: 14 }, 31),
    },
    {
      platform: 'gemini', assessed: 32, samples: 33,
      counts: { grounded: 0, echoed: 12, misattributed: 2, fabricated: 6, acknowledged_unknown: 12, absent: 1 },
      assessments: assessments(
        { grounded: 0, echoed: 12, misattributed: 2, fabricated: 6, acknowledged_unknown: 12 }, 32),
    },
  ],
}

describe('the brand-direct tier', () => {
  const withBrand = (extra = {}) => section({ tiers: [BRAND_TIER, tier()], ...extra })

  it('is shown as a split, with every assessment named', () => {
    render(<TierAccuracySection tierAccuracy={withBrand()} open onToggle={() => {}} />)
    // The column headers, not the prose above them — the prose names two
    // of these as well, which is the point of scoping to the table.
    const headers = within(screen.getByTestId('brand-direct-split'))
      .getAllByRole('columnheader').map((h) => h.textContent)
    expect(headers).toEqual([
      'Brand-direct', 'Grounded', 'Brand echoed', 'Misattributed',
      'Fabricated', 'Said it could not find us', 'Assessed',
    ])
  })

  it('prints no accuracy or staleness for it — there is no number to match', () => {
    render(<TierAccuracySection tierAccuracy={withBrand()} open onToggle={() => {}} />)
    const row = screen.getByTestId('tier-row-brand_direct')
    // The catalog tier's 60% is still in the table; the brand row shows
    // state chips where its accuracy would be, never a zero.
    expect(within(row).queryByText('60%')).not.toBeInTheDocument()
    expect(within(row).getAllByText(/no sample|—|see below/).length).toBeGreaterThan(0)
  })

  it('retires visibility rather than printing a second number for one fact', () => {
    render(<TierAccuracySection tierAccuracy={withBrand()} open onToggle={() => {}} />)
    const row = screen.getByTestId('tier-row-brand_direct')
    expect(within(row).getByText('see below')).toBeInTheDocument()
  })

  it('splits by surface, because the two fail differently', () => {
    render(<TierAccuracySection tierAccuracy={withBrand()} open onToggle={() => {}} />)
    expect(screen.getByTestId('brand-split-chatgpt')).toBeInTheDocument()
    expect(screen.getByTestId('brand-split-gemini')).toBeInTheDocument()
    // Two grounded runs, both on one surface.
    expect(within(screen.getByTestId('brand-split-chatgpt'))).toBeTruthy()
  })

  it('says how many answers never named the brand and kept them out', () => {
    render(<TierAccuracySection tierAccuracy={withBrand()} open onToggle={() => {}} />)
    expect(screen.getByTestId('brand-direct-split'))
      .toHaveTextContent('3 answers never named the brand at all')
  })

  it('is absent entirely from a study that has no brand-direct tier', () => {
    render(<TierAccuracySection tierAccuracy={section()} open onToggle={() => {}} />)
    expect(screen.queryByTestId('brand-direct-split')).not.toBeInTheDocument()
  })
})

describe('the value-survival headline', () => {
  it('says what it leaves out and why', () => {
    render(
      <TierAccuracySection
        open onToggle={() => {}}
        tierAccuracy={section({
          value_survival: 0.5, value_survival_samples: 4,
          low_information: {
            scored: 2, exact: 2, rate: 1,
            note: 'Points at one per dollar is the category default.',
          },
        })}
      />,
    )
    const note = screen.getByTestId('low-information')
    expect(note).toHaveTextContent('2 questions are kept out of that figure')
    expect(note).toHaveTextContent('category default')
  })

  it('says nothing when nothing was excluded', () => {
    render(<TierAccuracySection tierAccuracy={section()} open onToggle={() => {}} />)
    expect(screen.queryByTestId('low-information')).not.toBeInTheDocument()
  })
})

describe('near-miss codes', () => {
  it('are counted beside wrong rather than inside it silently', () => {
    render(
      <TierAccuracySection
        open onToggle={() => {}}
        tierAccuracy={section({ tiers: [tier({ near_miss: 1 })] })}
      />,
    )
    expect(screen.getByTestId('tier-row-catalog_accuracy'))
      .toHaveTextContent('(1 near miss)')
  })
})
