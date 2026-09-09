/**
 * The Create Study modal in brand mode, and — the half that matters more
 * — the modal with the brand block untouched.
 *
 * The compatibility claim is byte-for-byte: an existing user who opens
 * this modal and never touches the Syndicated brand block sends the
 * request this modal sent before the block existed, key for key. That is
 * asserted against a frozen key list rather than by spot-checking a few
 * fields, so a stray key added in future fails here rather than reaching
 * the API.
 *
 * The catalog fixture is imported from the pipeline's test directory, not
 * copied: one Wiggle & Snug catalog, shared with
 * apps/pipeline/tests/test_catalog_tiers.py, so the modal's promises and
 * the generator's output are checked against the same record.
 */
import React from 'react'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import CreateStudyModal, { TIER_ROWS } from '../CreateStudyModal.jsx'
import { api } from '../../api.js'
import { truesyncApi } from '../../truesyncApi.js'
import fixture from '../../../../../pipeline/tests/fixtures/wiggle_and_snug_catalog.json'

vi.mock('../../api.js', () => ({
  api: {
    getQueryConstraints: vi.fn(),
    getEntities: vi.fn(),
    generateStudy: vi.fn(),
  },
}))

vi.mock('../../truesyncApi.js', () => ({
  truesyncApi: {
    getMerchants: vi.fn(),
    getMerchantCatalog: vi.fn(),
    getMerchantIncentives: vi.fn(),
  },
}))

const CONSTRAINTS = {
  category:      ['Skincare', 'Baby Care'],
  stage:         ['Awareness', 'Research', 'Comparison', 'Ready to Buy'],
  specificity:   ['Broad', 'Mid', 'Narrow'],
  persona:       ['Beauty Enthusiast', 'Value-Conscious'],
  status:        ['Active'],
  study_pattern: ['retailer', 'brand_at_retail'],
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getQueryConstraints.mockResolvedValue(CONSTRAINTS)
  api.getEntities.mockResolvedValue([])
  api.generateStudy.mockResolvedValue({ study_type: 'wiggle_1a2b3c' })
  truesyncApi.getMerchants.mockResolvedValue(fixture.merchants)
  truesyncApi.getMerchantCatalog.mockResolvedValue(fixture.catalog)
  truesyncApi.getMerchantIncentives.mockResolvedValue(fixture.incentives)
})

async function renderModal() {
  const onCreated = vi.fn()
  const utils = render(
    <CreateStudyModal open onClose={vi.fn()} onCreated={onCreated} />,
  )
  await screen.findByText('Skincare')
  return { ...utils, onCreated }
}

const brandToggle = () =>
  screen.getByLabelText(/Ground questions in a brand's published catalog/i, {
    selector: 'input',
  })

async function enableBrand() {
  fireEvent.click(brandToggle())
  const select = await screen.findByLabelText('Syndicated brand')
  fireEvent.change(select, { target: { value: 'wiggle-and-snug' } })
  await screen.findByTestId('catalog-readback')
}

function submit() {
  fireEvent.click(screen.getByText(/Generate Questions/i))
}

// ── untouched: today's request, key for key ──────────────────────────────

// The exact keys this modal sent before the syndicated-brand block
// existed. Frozen deliberately: a spot-check of a few fields would not
// notice a new key leaking into every existing user's request.
const LEGACY_KEYS = [
  'study_name', 'description', 'target_count', 'study_pattern',
  'retailer_names', 'allowed_categories', 'stage_targets',
  'rotate_named_retailer', 'naming_rule_enabled', 'personas',
  'specificity_mode',
]

describe('with the brand block untouched', () => {
  it('sends exactly the keys it sent before the block existed', async () => {
    await renderModal()
    fireEvent.change(screen.getByLabelText('Study Name'), {
      target: { value: 'Prestige Beauty' },
    })
    submit()

    await waitFor(() => expect(api.generateStudy).toHaveBeenCalled())
    const payload = api.generateStudy.mock.calls[0][0]
    expect(Object.keys(payload).sort()).toEqual([...LEGACY_KEYS].sort())
  })

  it('carries no syndicated_merchant and no tier_config', async () => {
    await renderModal()
    fireEvent.change(screen.getByLabelText('Study Name'), {
      target: { value: 'Prestige Beauty' },
    })
    submit()

    await waitFor(() => expect(api.generateStudy).toHaveBeenCalled())
    const payload = api.generateStudy.mock.calls[0][0]
    expect(payload).not.toHaveProperty('syndicated_merchant')
    expect(payload).not.toHaveProperty('tier_config')
  })

  it('shows the plain question count, not the two-part tally', async () => {
    await renderModal()
    expect(screen.getByText(/50 questions total/)).toBeInTheDocument()
    expect(screen.queryByTestId('tally')).not.toBeInTheDocument()
  })

  it('starts with the toggle off', async () => {
    await renderModal()
    expect(brandToggle()).not.toBeChecked()
    expect(screen.queryByLabelText('Syndicated brand')).not.toBeInTheDocument()
  })

  it('reads no catalog at all', async () => {
    await renderModal()
    expect(truesyncApi.getMerchantCatalog).not.toHaveBeenCalled()
    expect(truesyncApi.getMerchantIncentives).not.toHaveBeenCalled()
  })
})

// ── toggled on but with no brand chosen ──────────────────────────────────

describe('toggled on with no brand chosen', () => {
  it('still sends today\'s payload — the toggle is an intention, the select is the fact', async () => {
    await renderModal()
    fireEvent.change(screen.getByLabelText('Study Name'), {
      target: { value: 'Prestige Beauty' },
    })
    fireEvent.click(brandToggle())
    await screen.findByLabelText('Syndicated brand')
    submit()

    await waitFor(() => expect(api.generateStudy).toHaveBeenCalled())
    const payload = api.generateStudy.mock.calls[0][0]
    expect(Object.keys(payload).sort()).toEqual([...LEGACY_KEYS].sort())
  })
})

// ── brand mode ───────────────────────────────────────────────────────────

describe('in brand mode', () => {
  it('offers the merchants TrueSync says have a published catalog', async () => {
    await renderModal()
    fireEvent.click(brandToggle())
    const select = await screen.findByLabelText('Syndicated brand')
    expect(within(select).getByText('Wiggle & Snug (trueshopstore.com)')).toBeInTheDocument()
  })

  it('reads the catalog back with counts computed from the record', async () => {
    await renderModal()
    await enableBrand()
    expect(screen.getByTestId('catalog-readback')).toHaveTextContent(
      '5 products, 19 variants, 6 GTINs, 2 live codes, Member Rewards (2 tiers)',
    )
  })

  it('says a republish needs a regeneration, not a refresh', async () => {
    await renderModal()
    await enableBrand()
    expect(screen.getByTestId('catalog-readback')).toHaveTextContent(
      /Republish the catalog and regenerate to refresh the expected answers/,
    )
  })

  it('shows four tier rows with their source tags', async () => {
    await renderModal()
    await enableBrand()

    for (const row of TIER_ROWS) {
      const el = screen.getByTestId(`tier-${row.key}`)
      expect(el).toHaveTextContent(row.title)
      expect(el).toHaveTextContent(row.source)
    }
  })

  it('shows each additive tier its real count, from this brand\'s catalog', async () => {
    await renderModal()
    await enableBrand()

    // One price question per variant; GTIN and pack count ride along on
    // it as secondary expectations rather than as questions of their own.
    expect(screen.getByTestId('tier-catalog_accuracy')).toHaveTextContent('19 questions')
    expect(screen.getByTestId('tier-value_incentives')).toHaveTextContent('6 questions')
    expect(screen.getByTestId('tier-brand_direct')).toHaveTextContent('12 questions')
  })

  it('says the control tier uses the stage counts rather than adding to them', async () => {
    await renderModal()
    await enableBrand()
    fireEvent.click(screen.getByLabelText('Category control'))

    expect(screen.getByTestId('tier-category_control'))
      .toHaveTextContent('uses the stage counts above')
  })

  it('defaults the control tier off and the other three on', async () => {
    await renderModal()
    await enableBrand()

    expect(screen.getByLabelText('Brand-direct')).toBeChecked()
    expect(screen.getByLabelText('Catalog accuracy')).toBeChecked()
    expect(screen.getByLabelText('Value & incentives')).toBeChecked()
    expect(screen.getByLabelText('Category control')).not.toBeChecked()
  })
})

// ── the examples ─────────────────────────────────────────────────────────

describe('the examples', () => {
  async function openExamples() {
    await renderModal()
    await enableBrand()
    fireEvent.click(screen.getByText(/Examples of what gets asked/))
    return screen.findByTestId('tier-examples')
  }

  it('are real questions about real Wiggle & Snug variants', async () => {
    const examples = await openExamples()
    expect(examples).toHaveTextContent(
      'What does the Wiggle & Snug Snug-Fit Diapers Size 1 small pack cost?',
    )
  })

  it('carry the published expected answer', async () => {
    const examples = await openExamples()
    expect(examples).toHaveTextContent('Expected: $17.99')
  })

  it('show the pack count as a second expectation on the price question', async () => {
    const examples = await openExamples()
    expect(examples).toHaveTextContent('96 count')
  })

  it('show the value tier\'s real code and what it takes off', async () => {
    const examples = await openExamples()
    expect(examples).toHaveTextContent(
      'Is there a first-order promo code for Wiggle & Snug, and what does it take off?',
    )
    expect(examples).toHaveTextContent('Expected: WELCOME10, 10.00% off')
  })

  it('mark the brand-direct example as illustrative, because AI writes the wording', async () => {
    const examples = await openExamples()
    expect(examples).toHaveTextContent(
      /Wording is written by AI at generation time/,
    )
    expect(examples).toHaveTextContent('Expected: brand named, trueshopstore.com cited')
  })

  it('drop a tier\'s example when the tier is unticked', async () => {
    await renderModal()
    await enableBrand()
    fireEvent.click(screen.getByLabelText('Catalog accuracy'))
    fireEvent.click(screen.getByText(/Examples of what gets asked/))

    const examples = await screen.findByTestId('tier-examples')
    expect(examples).not.toHaveTextContent('Snug-Fit Diapers Size 1 small pack (96 ct) cost?')
  })
})

// ── the tally ────────────────────────────────────────────────────────────

describe('the tally', () => {
  it('opens green on the defaults, inside the shared 100', async () => {
    await renderModal()
    fireEvent.change(screen.getByLabelText('Study Name'), {
      target: { value: 'Wiggle & Snug' },
    })
    await enableBrand()

    // 50 stage + 12 brand-direct AI-written; 19 accuracy + 6 value from
    // the catalog. A feature whose defaults open on a red tally has the
    // wrong defaults, which is why pack count stopped being its own
    // question.
    expect(screen.getByTestId('tally')).toHaveTextContent(
      '62 AI-written + 25 from the catalog = 87 questions — within the 100 limit',
    )
    expect(screen.getByText(/Generate Questions/i)).not.toBeDisabled()
  })

  it('names both halves and measures them against the shared 100', async () => {
    await renderModal()
    await enableBrand()
    // Push the stage counts past what the catalog leaves room for.
    fireEvent.change(document.getElementById('stage-Awareness'), {
      target: { value: '30' },
    })

    await waitFor(() => expect(screen.getByTestId('tally')).toHaveTextContent(
      '79 AI-written + 25 from the catalog = 104 questions '
      + '— over the 100 limit, reduce a stage or untick a tier',
    ))
  })

  it('comes back within the limit when a tier is unticked', async () => {
    await renderModal()
    await enableBrand()
    fireEvent.click(screen.getByLabelText('Catalog accuracy'))

    await waitFor(() => expect(screen.getByTestId('tally')).toHaveTextContent(
      '62 AI-written + 6 from the catalog = 68 questions — within the 100 limit',
    ))
  })

  it('blocks submission while over the shared ceiling', async () => {
    await renderModal()
    await enableBrand()
    fireEvent.change(document.getElementById('stage-Awareness'), {
      target: { value: '30' },
    })

    await waitFor(() =>
      expect(screen.getByText(/Generate Questions/i)).toBeDisabled())
  })

  it('counts the control tier as adding nothing', async () => {
    await renderModal()
    await enableBrand()
    fireEvent.click(screen.getByLabelText('Brand-direct'))
    fireEvent.click(screen.getByLabelText('Catalog accuracy'))
    fireEvent.click(screen.getByLabelText('Value & incentives'))
    fireEvent.click(screen.getByLabelText('Category control'))

    await waitFor(() => expect(screen.getByTestId('tally')).toHaveTextContent(
      '50 questions total — within the 100 limit',
    ))
  })
})

// ── the request ──────────────────────────────────────────────────────────

describe('the brand-mode request', () => {
  it('carries the merchant and a tier_config naming all four tiers', async () => {
    await renderModal()
    fireEvent.change(screen.getByLabelText('Study Name'), {
      target: { value: 'Wiggle & Snug' },
    })
    await enableBrand()
    await waitFor(() =>
      expect(screen.getByText(/Generate Questions/i)).not.toBeDisabled())
    submit()

    await waitFor(() => expect(api.generateStudy).toHaveBeenCalled())
    const payload = api.generateStudy.mock.calls[0][0]

    expect(payload.syndicated_merchant).toBe('wiggle-and-snug')
    expect(payload.tier_config).toEqual({
      brand_direct: { enabled: true, count: 12 },
      catalog_accuracy: { enabled: true },
      value_incentives: { enabled: true },
      category_control: { enabled: false },
    })
  })

  it('sends the STAGE total as target_count, not the grand total', async () => {
    await renderModal()
    fireEvent.change(screen.getByLabelText('Study Name'), {
      target: { value: 'Wiggle & Snug' },
    })
    await enableBrand()
    await waitFor(() =>
      expect(screen.getByText(/Generate Questions/i)).not.toBeDisabled())
    submit()

    await waitFor(() => expect(api.generateStudy).toHaveBeenCalled())
    // Catalog questions are not generated from target_count and would
    // inflate every stage bucket if they were folded into it.
    expect(api.generateStudy.mock.calls[0][0].target_count).toBe(50)
  })
})

// ── TrueSync being unreachable ───────────────────────────────────────────

describe('when TrueSync cannot be reached', () => {
  it('says so and leaves the study generatable', async () => {
    truesyncApi.getMerchants.mockRejectedValue(new Error('TrueSync is unreachable'))
    await renderModal()

    await screen.findByText(/No syndicated brands available/)
    expect(brandToggle()).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Study Name'), {
      target: { value: 'Prestige Beauty' },
    })
    submit()

    await waitFor(() => expect(api.generateStudy).toHaveBeenCalled())
    expect(Object.keys(api.generateStudy.mock.calls[0][0]).sort())
      .toEqual([...LEGACY_KEYS].sort())
  })

  it('keeps the block usable when only the incentives read fails', async () => {
    truesyncApi.getMerchantIncentives.mockRejectedValue(new Error('504'))
    await renderModal()
    await enableBrand()

    // The catalog tier is unaffected; the value tier simply has nothing
    // to build, which is a smaller loss than the block going dark.
    expect(screen.getByTestId('tier-catalog_accuracy')).toHaveTextContent('19 questions')
    expect(screen.getByTestId('tier-value_incentives')).toHaveTextContent('0 questions')
  })

  it('explains a catalog read that fails outright', async () => {
    truesyncApi.getMerchantCatalog.mockRejectedValue(new Error('no TrueSync merchant'))
    await renderModal()
    fireEvent.click(brandToggle())
    fireEvent.change(await screen.findByLabelText('Syndicated brand'), {
      target: { value: 'wiggle-and-snug' },
    })

    await screen.findByText(/Could not read that catalog/)
    expect(screen.queryByTestId('tier-catalog_accuracy')).not.toBeInTheDocument()
  })
})
