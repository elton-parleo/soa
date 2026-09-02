import React from 'react'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import StudyReviewPanel, { describeResolution } from '../StudyReviewPanel.jsx'
import { api } from '../../api.js'

vi.mock('../../api.js', () => ({
  api: { resolveReviewFinding: vi.fn() },
}))

const STUDY = 'prestige_beauty_a1b2c3'

// Shaped exactly like build_provenance_record's output plus the
// review_resolutions key the resolve endpoint adds.
const PROVENANCE = {
  rows_generated: 56,
  replacement_rounds: 1,
  exact_duplicates_dropped: [
    { query_text: 'A repeat?', stage: 'Comparison' },
    { query_text: 'Another repeat?', stage: 'Awareness' },
  ],
  category_drops: [
    { query_text: 'Best baby wipes?', category: 'Baby Care', reason: 'outside' },
  ],
  semantic_duplicate_groups: [
    {
      members: [0, 1], keep: 0,
      member_texts: [
        'What are the best prestige vitamin C serums for brightening dull skin?',
        'What is the best prestige vitamin C serum for brightening and uneven tone?',
      ],
      keep_text: 'What are the best prestige vitamin C serums for brightening dull skin?',
      reason: 'Both ask for a prestige vitamin C serum for brightening.',
    },
  ],
  coherence_findings_by_outcome: {
    label_mismatch: [
      { index: 2, query_text: 'What prestige fragrance notes work best for everyday wear?',
        category: 'Skincare', verdict: 'label_mismatch',
        field: 'category', proposed_value: 'Fragrance',
        reason: 'Question is about fragrance notes but is filed under Skincare.' },
    ],
    out_of_scope: [
      { index: 3, query_text: 'Where can I get the best price on a Dyson Airwrap?',
        category: 'Skincare', verdict: 'out_of_scope',
        reason: 'A Dyson Airwrap is a hair-styling appliance, not a prestige beauty product.' },
    ],
  },
}

const QUERIES = [
  { query_code: 'PRE_020', query_text: PROVENANCE.semantic_duplicate_groups[0].member_texts[0],
    category: 'Skincare', stage: 'Awareness', specificity: 'Broad',
    persona: 'Beauty Enthusiast', status: 'Active' },
  { query_code: 'PRE_048', query_text: PROVENANCE.semantic_duplicate_groups[0].member_texts[1],
    category: 'Skincare', stage: 'Awareness', specificity: 'Broad',
    persona: 'Beauty Enthusiast', status: 'Active' },
  { query_code: 'PRE_031', query_text: PROVENANCE.coherence_findings_by_outcome.label_mismatch[0].query_text,
    category: 'Skincare', stage: 'Research', specificity: 'Broad',
    persona: 'Eco-Conscious / Minimalist', status: 'Active' },
  { query_code: 'PRE_007', query_text: PROVENANCE.coherence_findings_by_outcome.out_of_scope[0].query_text,
    category: 'Skincare', stage: 'Ready to Buy', specificity: 'Narrow',
    persona: 'Value-Conscious', status: 'Active' },
]

beforeEach(() => {
  vi.clearAllMocks()
  api.resolveReviewFinding.mockResolvedValue({ provenance: PROVENANCE })
})

function renderPanel(provenance = PROVENANCE, queries = QUERIES) {
  const onResolved = vi.fn()
  const utils = render(
    <StudyReviewPanel
      studyType={STUDY} provenance={provenance} queries={queries} onResolved={onResolved}
    />
  )
  return { ...utils, onResolved }
}

function expand(provenance = PROVENANCE, queries = QUERIES) {
  const r = renderPanel(provenance, queries)
  fireEvent.click(screen.getByRole('button', { name: 'Review' }))
  return r
}

// ─── the banner ───────────────────────────────────────────────────────────

describe('the banner', () => {
  it('states how many findings are left to review', () => {
    renderPanel()
    expect(screen.getByText('3 findings to review')).toBeInTheDocument()
  })

  it('renders nothing at all without a provenance record', () => {
    const { container } = render(
      <StudyReviewPanel studyType={STUDY} provenance={null} queries={[]} onResolved={vi.fn()} />
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('persists in a resolved state rather than disappearing when everything is handled', () => {
    // Reviewed-and-cleared is different information from
    // never-had-findings; a banner that vanishes reports them the same.
    const resolved = {
      ...PROVENANCE,
      review_resolutions: {
        'dup:0': { action: 'dismissed' },
        'coh:out_of_scope:0': { action: 'dismissed' },
        'coh:label_mismatch:0': { action: 'dismissed' },
      },
    }
    renderPanel(resolved)

    expect(screen.getByText('Reviewed — all 3 findings resolved.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Review' })).toBeInTheDocument()
  })

  it('shows a resolved banner, not an empty panel, for a study with no findings', () => {
    const clean = {
      ...PROVENANCE,
      semantic_duplicate_groups: [],
      coherence_findings_by_outcome: { label_mismatch: [], out_of_scope: [] },
    }
    renderPanel(clean)

    expect(
      screen.getByText('Reviewed — this study generated with no findings to look at.')
    ).toBeInTheDocument()
  })

  it('expands and collapses the panel', () => {
    renderPanel()
    expect(screen.queryByText('Already handled')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Review' }))
    expect(screen.getByText('Already handled')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Hide' }))
    expect(screen.queryByText('Already handled')).not.toBeInTheDocument()
  })
})


// ─── section one: informational only ──────────────────────────────────────

describe('Already handled', () => {
  it('is collapsed by default', () => {
    expand()
    const header = screen.getByRole('button', { name: /Already handled/ })
    expect(header).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('Questions generated')).not.toBeInTheDocument()

    fireEvent.click(header)
    expect(screen.getByText('Questions generated')).toBeInTheDocument()
  })

  it('carries no actions of its own — it is provenance, not a task list', () => {
    expand()
    fireEvent.click(screen.getByRole('button', { name: /Already handled/ }))

    // Scoped to this section's own body. Dismiss/Deactivate buttons exist
    // elsewhere in the panel; the point is that none of them are here.
    const body = screen.getByText('Questions generated').closest('div').parentElement
    expect(within(body).queryByRole('button')).not.toBeInTheDocument()
  })

  it('reports provenance, not a task list', () => {
    expand()
    fireEvent.click(screen.getByRole('button', { name: /Already handled/ }))

    const rows = ['Questions generated', 'Exact duplicates removed',
                  'Outside allowed categories, removed', 'Replacement rounds run',
                  'Final query count']
    rows.forEach(label => expect(screen.getByText(label)).toBeInTheDocument())

    expect(screen.getByText('56')).toBeInTheDocument()   // generated
    expect(screen.getByText('4')).toBeInTheDocument()    // final count (queries.length)
  })
})


// ─── section two: possible duplicates ─────────────────────────────────────

describe('Possible duplicates', () => {
  it('leads with the reason, not the verdict', () => {
    // The reviewer has to be able to disagree with the reasoning, which
    // means reading it before the action.
    expand()
    expect(
      screen.getByText('Both ask for a prestige vitamin C serum for brightening.')
    ).toBeInTheDocument()
  })

  it('shows every member with its id and full labels', () => {
    expand()
    expect(screen.getByText('PRE_020')).toBeInTheDocument()
    expect(screen.getByText('PRE_048')).toBeInTheDocument()
    expect(
      screen.getAllByText('Skincare · Awareness · Broad · Beauty Enthusiast')
    ).toHaveLength(2)
  })

  it("marks the model's recommended keep and offers the other as an alternative", () => {
    expand()
    expect(screen.getByText('Keep')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Keep this' })).toBeInTheDocument()
  })

  it('deactivates the members that were not kept', async () => {
    expand()
    fireEvent.click(screen.getByRole('button', { name: /Deactivate PRE_048/ }))

    await waitFor(() => expect(api.resolveReviewFinding).toHaveBeenCalled())
    expect(api.resolveReviewFinding.mock.calls[0][1]).toEqual({
      finding_id: 'dup:0',
      action: 'deactivate',
      query_codes: ['PRE_048'],
      keep_query_code: 'PRE_020',
    })
  })

  it("lets the reviewer keep a different member than the model picked", async () => {
    // The model's pick is a default, not a decision.
    expand()
    fireEvent.click(screen.getByRole('button', { name: 'Keep this' }))

    expect(screen.getByRole('button', { name: /Deactivate PRE_020/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Deactivate PRE_020/ }))

    await waitFor(() => expect(api.resolveReviewFinding).toHaveBeenCalled())
    expect(api.resolveReviewFinding.mock.calls[0][1]).toMatchObject({
      query_codes: ['PRE_020'],
      keep_query_code: 'PRE_048',
    })
  })

  it('dismisses the group as not duplicates', async () => {
    expand()
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss — not duplicates' }))

    await waitFor(() => expect(api.resolveReviewFinding).toHaveBeenCalled())
    expect(api.resolveReviewFinding.mock.calls[0][1]).toEqual({
      finding_id: 'dup:0', action: 'dismiss',
    })
  })
})


// ─── section three: possible problems ─────────────────────────────────────

describe('Possible problems', () => {
  it('distinguishes an off-brief query from a wrong label', () => {
    expand()
    expect(screen.getByText('Off-brief')).toBeInTheDocument()
    expect(screen.getByText('Wrong label')).toBeInTheDocument()
  })

  it('offers deactivation for an off-brief query', async () => {
    expand()
    fireEvent.click(screen.getByRole('button', { name: /Deactivate PRE_007/ }))

    await waitFor(() => expect(api.resolveReviewFinding).toHaveBeenCalled())
    expect(api.resolveReviewFinding.mock.calls[0][1]).toEqual({
      finding_id: 'coh:out_of_scope:0', action: 'deactivate', query_codes: ['PRE_007'],
    })
  })

  it('shows the single proposed field correction with current and proposed values', () => {
    expand()
    const fix = screen.getByText(/Change/).closest('div')
    expect(within(fix).getByText('category')).toBeInTheDocument()
    expect(within(fix).getByText('Skincare')).toBeInTheDocument()
    expect(within(fix).getByText('Fragrance')).toBeInTheDocument()
  })

  it('applies only the one named field', async () => {
    expand()
    fireEvent.click(screen.getByRole('button', { name: 'Apply correction' }))

    await waitFor(() => expect(api.resolveReviewFinding).toHaveBeenCalled())
    expect(api.resolveReviewFinding.mock.calls[0][1]).toEqual({
      finding_id: 'coh:label_mismatch:0',
      action: 'apply_label',
      query_code: 'PRE_031',
      field: 'category',
      proposed_value: 'Fragrance',
    })
  })

  it('offers dismissal on both kinds', () => {
    expand()
    expect(screen.getByRole('button', { name: 'Dismiss — it belongs' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Dismiss — the label is right' })).toBeInTheDocument()
  })
})


// ─── resolved state, persistence and undo ─────────────────────────────────

describe('resolved findings', () => {
  const resolved = {
    ...PROVENANCE,
    review_resolutions: {
      'dup:0': {
        action: 'deactivated',
        queries: [{ query_code: 'PRE_048', prior_status: 'Active' }],
        kept: 'PRE_020',
      },
      'coh:label_mismatch:0': {
        action: 'label_applied', query_code: 'PRE_031',
        field: 'category', prior_value: 'Skincare', applied_value: 'Fragrance',
      },
      'coh:out_of_scope:0': { action: 'dismissed' },
    },
  }

  it('stay visible, showing what was done, with an Undo', () => {
    expand(resolved)

    expect(screen.getByText('PRE_048 deactivated')).toBeInTheDocument()
    expect(screen.getByText('Applied — category set to Fragrance')).toBeInTheDocument()
    expect(screen.getByText('Dismissed — reviewed and disagreed')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Undo' })).toHaveLength(3)
  })

  it('replace the actions rather than sitting alongside them', () => {
    expand(resolved)
    expect(screen.queryByRole('button', { name: /Deactivate/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Dismiss/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Apply correction' })).not.toBeInTheDocument()
  })

  it('survive a reload, because they come from the stored record', () => {
    // Same component, fresh mount, provenance straight from the server.
    expand(resolved)
    expect(screen.getByText('PRE_048 deactivated')).toBeInTheDocument()
  })

  it('send an undo for the right finding', async () => {
    expand(resolved)
    fireEvent.click(screen.getAllByRole('button', { name: 'Undo' })[0])

    await waitFor(() => expect(api.resolveReviewFinding).toHaveBeenCalled())
    expect(api.resolveReviewFinding.mock.calls[0][1]).toEqual({
      finding_id: 'dup:0', action: 'undo',
    })
  })

  it('are not counted as still needing review', () => {
    renderPanel(resolved)
    expect(screen.getByText('Reviewed — all 3 findings resolved.')).toBeInTheDocument()
  })

  it('mark the kept member as Kept rather than offering the choice again', () => {
    expand(resolved)
    expect(screen.getByText('Kept')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Keep this' })).not.toBeInTheDocument()
  })
})


describe('resolution wiring', () => {
  it('hands the updated record back to the page', async () => {
    const updated = { ...PROVENANCE, review_resolutions: { 'dup:0': { action: 'dismissed' } } }
    api.resolveReviewFinding.mockResolvedValue({ provenance: updated })

    const { onResolved } = expand()
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss — not duplicates' }))

    await waitFor(() => expect(onResolved).toHaveBeenCalledWith(updated))
  })

  it('surfaces a failure without resolving anything', async () => {
    api.resolveReviewFinding.mockRejectedValue(new Error('Query not found in this study.'))

    const { onResolved } = expand()
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss — not duplicates' }))

    expect(await screen.findByText('Query not found in this study.')).toBeInTheDocument()
    expect(onResolved).not.toHaveBeenCalled()
  })

  it('states in the footer that deactivation is reversible', () => {
    expand()
    expect(
      screen.getByText(/sets a query to Paused rather than deleting it/)
    ).toBeInTheDocument()
    expect(screen.getByText(/can be restored/)).toBeInTheDocument()
  })
})


describe('describeResolution', () => {
  it('distinguishes dismissal from every other outcome', () => {
    expect(describeResolution({ action: 'dismissed' }))
      .toBe('Dismissed — reviewed and disagreed')
    expect(describeResolution({
      action: 'deactivated', queries: [{ query_code: 'A_1' }],
    })).toBe('A_1 deactivated')
    expect(describeResolution({
      action: 'label_applied', field: 'category', applied_value: 'Makeup',
    })).toBe('Applied — category set to Makeup')
    expect(describeResolution(null)).toBe('')
  })
})


describe('a finding whose query is missing from the table', () => {
  it('degrades rather than crashing', () => {
    // Findings join to live rows by query_text. A row deleted by hand
    // out from under the record must not take the panel down with it.
    expand(PROVENANCE, [])
    expect(screen.getByText('Off-brief')).toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })
})


describe('the proposed-correction line after it has been applied', () => {
  it('shows what was overwritten, not the value now in the row', () => {
    // The live row already holds the proposed value by then, so reading
    // "from" off it would render "from Fragrance to Fragrance".
    const applied = {
      ...PROVENANCE,
      review_resolutions: {
        'coh:label_mismatch:0': {
          action: 'label_applied', query_code: 'PRE_031', field: 'category',
          prior_value: 'Skincare', applied_value: 'Fragrance',
        },
      },
    }
    const corrected = QUERIES.map(q =>
      q.query_code === 'PRE_031' ? { ...q, category: 'Fragrance' } : q
    )
    expand(applied, corrected)

    const fix = screen.getByText(/Change/).closest('div')
    expect(within(fix).getByText('Skincare')).toBeInTheDocument()
    expect(within(fix).getByText('Fragrance')).toBeInTheDocument()
  })
})
