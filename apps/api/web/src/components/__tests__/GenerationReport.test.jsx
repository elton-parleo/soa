import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import GenerationReport from '../GenerationReport.jsx'

// Shaped exactly like build_provenance_record's output — see
// apps/pipeline/generation/query_generator.py.
const PROVENANCE = {
  rows_generated: 47,
  requested_by_stage: { 'Awareness': 13, 'Research': 13, 'Comparison': 12, 'Ready to Buy': 12 },
  delivered_by_stage: { 'Awareness': 13, 'Research': 13, 'Comparison': 10, 'Ready to Buy': 11 },
  shortfall_by_stage: { 'Comparison': 2, 'Ready to Buy': 1 },
  replacement_rounds: 1,
  generation_calls: 6,
  retailers_named: ['Sephora', 'Ulta Beauty'],
  exact_duplicates_dropped: [
    { query_text: 'Which retailer has the best price?', stage: 'Comparison' },
  ],
  category_drops: [
    {
      query_text: 'Where can I get the best price on a Dyson Airwrap?',
      category: 'Haircare',
      reason: "category 'Haircare' is outside the study's allowed categories",
    },
  ],
  semantic_duplicate_groups: [
    {
      members: [3, 19],
      keep: 3,
      member_texts: [
        "What's the best prestige vitamin C serum for brightening dull skin?",
        'Which prestige vitamin C serum works best for brightening and uneven tone?',
      ],
      keep_text: "What's the best prestige vitamin C serum for brightening dull skin?",
      reason: 'Both ask for the best prestige vitamin C serum for brightening.',
    },
  ],
  coherence_findings_by_outcome: {
    label_mismatch: [
      {
        index: 8, query_text: 'Is this scent long-lasting?', category: 'Skincare',
        field: 'category', proposed_value: 'Fragrance', verdict: 'label_mismatch',
      },
    ],
    out_of_scope: [
      {
        index: 22, query_text: 'What is the best baby wipe for sensitive skin?',
        category: 'Skincare', verdict: 'out_of_scope',
        reason: 'Baby care is outside a prestige beauty study.',
      },
    ],
  },
  coherence_ok_count: 45,
}

const CLEAN = {
  rows_generated: 50,
  requested_by_stage: { 'Awareness': 25, 'Comparison': 25 },
  delivered_by_stage: { 'Awareness': 25, 'Comparison': 25 },
  shortfall_by_stage: {},
  replacement_rounds: 0,
  exact_duplicates_dropped: [],
  category_drops: [],
  semantic_duplicate_groups: [],
  coherence_findings_by_outcome: { label_mismatch: [], out_of_scope: [] },
  coherence_ok_count: 50,
}

function expand(provenance = PROVENANCE) {
  render(<GenerationReport provenance={provenance} />)
  fireEvent.click(screen.getByRole('button', { name: /Generation report/ }))
}

describe('rendering at all', () => {
  it('renders nothing without a provenance record', () => {
    const { container } = render(<GenerationReport provenance={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('starts collapsed, with a summary and a review count', () => {
    render(<GenerationReport provenance={PROVENANCE} />)

    expect(screen.getByText(/47 questions generated/)).toBeInTheDocument()
    expect(screen.getByText('3 to review')).toBeInTheDocument()
    // Detail is behind the disclosure.
    expect(screen.queryByText(/Removed automatically/)).not.toBeInTheDocument()
  })

  it('expands to show the detail', () => {
    expand()
    expect(screen.getByText('Removed automatically')).toBeInTheDocument()
    expect(screen.getByText('Flagged for review')).toBeInTheDocument()
  })
})

describe('the removed / flagged split', () => {
  it('says removed rows are gone and this is the only record of them', () => {
    expand()
    expect(
      screen.getByText(/These are not in the study. This report is the only record of them./)
    ).toBeInTheDocument()
  })

  it('says flagged rows are still in the study and nothing was applied', () => {
    // Presenting the two kinds together would make the advisory findings
    // look like work already done, which is the one impression that would
    // stop anyone acting on them.
    expand()
    expect(
      screen.getByText(/Nothing here was applied. Every question below is still in the study/)
    ).toBeInTheDocument()
  })

  it('counts only the flagged findings in the review badge', () => {
    render(<GenerationReport provenance={PROVENANCE} />)
    // 1 semantic group + 1 label mismatch + 1 out of scope = 3.
    // The 2 automatic removals are NOT review work.
    expect(screen.getByText('3 to review')).toBeInTheDocument()
  })

  it('shows no review badge when nothing was flagged', () => {
    render(<GenerationReport provenance={CLEAN} />)
    expect(screen.queryByText(/to review/)).not.toBeInTheDocument()
  })
})

describe('removed automatically', () => {
  it('lists the exact duplicates that were dropped', () => {
    expand()
    expect(screen.getByText('1 exact duplicate')).toBeInTheDocument()
    expect(screen.getByText('Which retailer has the best price?')).toBeInTheDocument()
  })

  it('lists category drops and says why they were not relabelled', () => {
    expand()
    expect(screen.getByText("1 outside the study's categories")).toBeInTheDocument()
    expect(
      screen.getByText(/Dropped rather than relabelled/)
    ).toBeInTheDocument()
    expect(
      screen.getByText('Where can I get the best price on a Dyson Airwrap?')
    ).toBeInTheDocument()
  })
})

describe('flagged for review', () => {
  it('shows a semantic duplicate group with both wordings and the reason', () => {
    expand()
    expect(
      screen.getByText("What's the best prestige vitamin C serum for brightening dull skin?")
    ).toBeInTheDocument()
    expect(
      screen.getByText('Which prestige vitamin C serum works best for brightening and uneven tone?')
    ).toBeInTheDocument()
    expect(
      screen.getByText('Both ask for the best prestige vitamin C serum for brightening.')
    ).toBeInTheDocument()
    expect(screen.getByText('suggested keep')).toBeInTheDocument()
  })

  it('separates off-brief rows from mislabelled ones', () => {
    expand()
    expect(screen.getByText('1 possibly off-brief')).toBeInTheDocument()
    expect(screen.getByText('1 possible mislabel')).toBeInTheDocument()

    expect(
      screen.getByText('What is the best baby wipe for sensitive skin?')
    ).toBeInTheDocument()
    expect(
      screen.getByText('Baby care is outside a prestige beauty study.')
    ).toBeInTheDocument()

    expect(screen.getByText('Is this scent long-lasting?')).toBeInTheDocument()
    expect(screen.getByText('category → Fragrance')).toBeInTheDocument()
  })
})

describe('the stage distribution', () => {
  it('shows delivered against requested for every stage', () => {
    expand()
    // Awareness and Research both delivered 13 of 13.
    expect(screen.getAllByText('13/13')).toHaveLength(2)
    expect(screen.getByText('10/12')).toBeInTheDocument()   // Comparison, short
    expect(screen.getByText('11/12')).toBeInTheDocument()   // Ready to Buy, short
  })

  it('names the short stages in the collapsed summary', () => {
    render(<GenerationReport provenance={PROVENANCE} />)
    expect(screen.getByText(/short on Comparison, Ready to Buy/)).toBeInTheDocument()
  })

  it('reports replacement rounds when any ran', () => {
    expand()
    expect(screen.getByText(/1 replacement round run after removing duplicates/)).toBeInTheDocument()
  })
})

describe('a clean run', () => {
  it('says so plainly rather than rendering empty sections', () => {
    render(<GenerationReport provenance={CLEAN} />)
    expect(
      screen.getByText('50 questions generated, nothing removed or flagged.')
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Generation report/ }))
    expect(screen.queryByText('Removed automatically')).not.toBeInTheDocument()
    expect(screen.queryByText('Flagged for review')).not.toBeInTheDocument()
    expect(screen.getByText(/neither review pass found anything/)).toBeInTheDocument()
  })
})

describe('a partial record', () => {
  it('survives missing sections without throwing', () => {
    // The review passes degrade to empty findings, so a record can
    // legitimately arrive with keys missing.
    render(<GenerationReport provenance={{ rows_generated: 10 }} />)
    fireEvent.click(screen.getByRole('button', { name: /Generation report/ }))
    expect(screen.getByText(/10 questions generated/)).toBeInTheDocument()
  })
})

// ─── Syndicated studies: the study is more than its stage questions ───────
//
// provenance.rows_generated is what the general generator returned — the
// stage questions. The catalog tiers are built afterwards by code that
// never touches that number, so for a grounded study the two differ. The
// first real brand-mode study had 87 questions and this report said 50.

const TIER_CONFIG = {
  brand_direct:     { enabled: true, count: 12, requested: 12 },
  catalog_accuracy: { enabled: true, count: 19 },
  value_incentives: { enabled: true, count: 6 },
  category_control: { enabled: false, stage_total: 50 },
}

const STAGE_ONLY = {
  rows_generated: 50,
  requested_by_stage: { Research: 25, 'Ready to Buy': 25 },
  delivered_by_stage: { Research: 25, 'Ready to Buy': 25 },
  shortfall_by_stage: {},
  exact_duplicates_dropped: [],
  category_drops: [],
  semantic_duplicate_groups: [],
  coherence_findings_by_outcome: { label_mismatch: [], out_of_scope: [] },
}

describe('a study built from catalog tiers', () => {
  it('counts every tier in the collapsed summary, not just the stage half', () => {
    render(<GenerationReport provenance={STAGE_ONLY} tierConfig={TIER_CONFIG} />)
    expect(screen.getByText(/87 questions generated/)).toBeInTheDocument()
    expect(screen.queryByText(/50 questions generated/)).not.toBeInTheDocument()
  })

  it('shows the breakdown that adds up to the total', () => {
    render(<GenerationReport provenance={STAGE_ONLY} tierConfig={TIER_CONFIG} />)
    fireEvent.click(screen.getByRole('button', { name: /Generation report/ }))
    expect(
      screen.getByText('50 stage + 12 brand-direct + 25 from the catalog = 87'),
    ).toBeInTheDocument()
    expect(screen.getByText('catalog accuracy')).toBeInTheDocument()
    expect(screen.getByText('value & incentives')).toBeInTheDocument()
  })

  it('falls back to the snapshot taken at generation when the page has no live config', () => {
    render(<GenerationReport provenance={{ ...STAGE_ONLY, tiers: TIER_CONFIG }} />)
    expect(screen.getByText(/87 questions generated/)).toBeInTheDocument()
  })

  it('prefers the live config, which is what a regenerated tier updates', () => {
    render(
      <GenerationReport
        provenance={{ ...STAGE_ONLY, tiers: TIER_CONFIG }}
        tierConfig={{ ...TIER_CONFIG, brand_direct: { enabled: true, count: 8 } }}
      />,
    )
    expect(screen.getByText(/83 questions generated/)).toBeInTheDocument()
  })

  it('says so when a tier came up short, instead of letting it read as the plan', () => {
    render(
      <GenerationReport
        provenance={STAGE_ONLY}
        tierConfig={{
          ...TIER_CONFIG,
          brand_direct: { enabled: true, count: 9, requested: 12, shortfall: 3 },
        }}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /Generation report/ }))
    expect(
      screen.getByText('brand-direct is 3 short: 9 of 12 requested'),
    ).toBeInTheDocument()
  })

  it('lists the brand-direct questions it threw away and why', () => {
    render(
      <GenerationReport
        provenance={STAGE_ONLY}
        tierConfig={{
          ...TIER_CONFIG,
          brand_direct: {
            enabled: true, count: 12, requested: 12,
            brand_missing_drops: [
              { query_text: 'Which diaper brands are best for sensitive skin?' },
            ],
            intent_duplicate_drops: [
              { query_text: 'How much does the Size 3 small pack cost?' },
            ],
          },
        }}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /Generation report/ }))
    expect(
      screen.getByText('Which diaper brands are best for sensitive skin?'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('How much does the Size 3 small pack cost?'),
    ).toBeInTheDocument()
    expect(screen.getByText(/did not name the brand/)).toBeInTheDocument()
    expect(screen.getByText(/the catalog tier already asks/)).toBeInTheDocument()
  })

  it('leaves an ungrounded study exactly as it was', () => {
    render(<GenerationReport provenance={STAGE_ONLY} />)
    expect(screen.getByText(/50 questions generated/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Generation report/ }))
    expect(screen.queryByText(/Questions in this study/i)).not.toBeInTheDocument()
  })
})
