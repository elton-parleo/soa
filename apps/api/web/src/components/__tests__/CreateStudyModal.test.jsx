import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import CreateStudyModal, {
  distribute,
  inferCategories,
  MAX_QUESTIONS,
  PRESETS,
} from '../CreateStudyModal.jsx'
import { api } from '../../api.js'

vi.mock('../../api.js', () => ({
  api: {
    getQueryConstraints: vi.fn(),
    getEntities: vi.fn(),
    generateStudy: vi.fn(),
  },
}))

// Deliberately NOT the real constants.py values. Every option list in the
// modal has to come from GET /api/studies/constraints at runtime — adding
// a value there is a constants edit plus a migration plus a redeploy, and
// the frontend is meant to pick it up with no change at all. A test that
// asserted against the real values would pass just as happily against a
// hardcoded list.
const CONSTRAINTS = {
  category:      ['Skincare', 'Haircare', 'Baby Care', 'Invented Category'],
  stage:         ['Awareness', 'Research', 'Comparison', 'Ready to Buy'],
  specificity:   ['Broad', 'Mid', 'Narrow'],
  persona:       ['Beauty Enthusiast', 'Invented Persona'],
  status:        ['Active', 'Paused'],
  study_pattern: ['retailer', 'brand_at_retail', 'invented_pattern'],
}

const ENTITIES = [
  { id: 1, name: 'Sephora', category: 'beauty', type: 'Retailer' },
  { id: 2, name: 'Ulta Beauty', category: 'beauty', type: 'Retailer' },
]

beforeEach(() => {
  vi.clearAllMocks()
  api.getQueryConstraints.mockResolvedValue(CONSTRAINTS)
  api.getEntities.mockResolvedValue(ENTITIES)
  api.generateStudy.mockResolvedValue({ study_type: 'acme_1a2b3c' })
})

async function renderModal(props = {}) {
  const onCreated = props.onCreated || vi.fn()
  const utils = render(
    <CreateStudyModal open onClose={props.onClose || vi.fn()} onCreated={onCreated} />
  )
  await screen.findByText('Skincare')
  return { ...utils, onCreated }
}

function stageInput(stage) {
  return document.getElementById(`stage-${stage}`)
}

function chip(name) {
  return screen.getByRole('checkbox', { name })
}

async function fillName(value) {
  fireEvent.change(screen.getByLabelText('Study Name'), { target: { value } })
}

// Names the first retailer, taking the study out of its unbranded state.
// An empty list IS the unbranded study, so a freshly-opened modal is
// unbranded until something is picked.
async function pickRetailer(name = 'Sephora') {
  fireEvent.focus(screen.getByLabelText('Retailer 1'))
  fireEvent.mouseDown(await screen.findByText(name))
}

// ─── pure helpers ─────────────────────────────────────────────────────────

describe('inferCategories', () => {
  it('matches a category however the user spaces or cases it', () => {
    const cats = ['Skincare', 'Baby Care']
    expect(inferCategories('A skincare study', cats)).toEqual(['Skincare'])
    expect(inferCategories('A SKIN CARE study', cats)).toEqual(['Skincare'])
    expect(inferCategories('all about baby-care', cats)).toEqual(['Baby Care'])
  })

  it('returns nothing when nothing matches, rather than guessing', () => {
    expect(inferCategories('a study about widgets', ['Skincare'])).toEqual([])
    expect(inferCategories('', ['Skincare'])).toEqual([])
  })

  it('only ever returns values it was given', () => {
    expect(inferCategories('skincare and haircare', ['Skincare'])).toEqual(['Skincare'])
  })
})

describe('distribute', () => {
  it('always sums to exactly the total', () => {
    for (const preset of PRESETS.filter(p => p.weights)) {
      for (const total of [1, 7, 50, 97]) {
        const counts = distribute(CONSTRAINTS.stage, total, preset.value)
        const sum = Object.values(counts).reduce((a, b) => a + b, 0)
        expect(sum).toBe(total)
      }
    }
  })

  it('weights by position, not by stage name', () => {
    const decision = distribute(CONSTRAINTS.stage, 40, 'decision')
    const stages = CONSTRAINTS.stage
    expect(decision[stages[3]]).toBeGreaterThan(decision[stages[0]])

    const discovery = distribute(CONSTRAINTS.stage, 40, 'discovery')
    expect(discovery[stages[0]]).toBeGreaterThan(discovery[stages[3]])
  })

  it('returns nothing for the custom preset, which has no weights', () => {
    expect(distribute(CONSTRAINTS.stage, 40, 'custom')).toEqual({})
  })
})

// ─── option lists come from the constraints endpoint ──────────────────────

describe('option lists render from the constraints response', () => {
  it('renders study patterns, categories and stages the endpoint returned', async () => {
    await renderModal()

    // Values that exist nowhere in constants.py — they can only have come
    // from the mocked endpoint response.
    expect(screen.getByRole('radio', { name: 'invented_pattern' })).toBeInTheDocument()
    expect(chip('Invented Category')).toBeInTheDocument()
    for (const stage of CONSTRAINTS.stage) {
      expect(stageInput(stage)).toBeInTheDocument()
    }
  })

  it('renders personas from the endpoint under Advanced', async () => {
    await renderModal()
    fireEvent.click(screen.getByRole('button', { name: /Advanced/ }))
    expect(chip('Invented Persona')).toBeInTheDocument()
  })

  it('offers no way to create a new category', async () => {
    await renderModal()
    // category is NOT NULL with a CHECK constraint, so a free-text
    // category cannot be persisted; a control that errors on use is
    // worse than no control.
    expect(screen.queryByText(/add category/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/new category/i)).not.toBeInTheDocument()
  })
})

// ─── category inference and its lock ──────────────────────────────────────

describe('category inference', () => {
  it('infers live from the name and description as the user types', async () => {
    await renderModal()
    expect(chip('Skincare')).toHaveAttribute('aria-checked', 'false')

    await fillName('A skincare study')
    await waitFor(() => expect(chip('Skincare')).toHaveAttribute('aria-checked', 'true'))

    fireEvent.change(screen.getByLabelText('What to ask about'), {
      target: { value: 'also covers haircare' },
    })
    await waitFor(() => expect(chip('Haircare')).toHaveAttribute('aria-checked', 'true'))
  })

  it('shows a distinct helper line when nothing can be inferred yet', async () => {
    await renderModal()
    expect(screen.getByText(/Nothing inferred yet/)).toBeInTheDocument()

    await fillName('A skincare study')
    await waitFor(() =>
      expect(screen.queryByText(/Nothing inferred yet/)).not.toBeInTheDocument()
    )
  })

  it('stops inferring permanently once the user edits a chip', async () => {
    await renderModal()
    await fillName('A skincare study')
    await waitFor(() => expect(chip('Skincare')).toHaveAttribute('aria-checked', 'true'))

    fireEvent.click(chip('Baby Care'))
    expect(chip('Baby Care')).toHaveAttribute('aria-checked', 'true')

    // Typing a new category into the name must NOT move the chips now.
    await fillName('A haircare study')
    await waitFor(() => {})
    expect(chip('Haircare')).toHaveAttribute('aria-checked', 'false')
    expect(chip('Baby Care')).toHaveAttribute('aria-checked', 'true')
    expect(chip('Skincare')).toHaveAttribute('aria-checked', 'true')
  })

  it('keeps the chips visible and authoritative throughout', async () => {
    await renderModal()
    await fillName('A skincare study')
    fireEvent.click(chip('Skincare'))          // deselect what was inferred
    expect(chip('Skincare')).toHaveAttribute('aria-checked', 'false')
    // No mode toggle anywhere — inference is a derived value, not a rule,
    // so a control claiming to be "in auto mode" would be lying.
    expect(screen.queryByText(/auto/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/manual/i)).not.toBeInTheDocument()
  })
})

describe('the inference reset control', () => {
  it('is hidden until the first chip edit', async () => {
    await renderModal()
    expect(screen.queryByRole('button', { name: /Reset to inferred/ })).not.toBeInTheDocument()

    fireEvent.click(chip('Skincare'))
    expect(screen.getByRole('button', { name: /Reset to inferred/ })).toBeInTheDocument()
  })

  it('re-infers from the fields as they are NOW, not from a prior selection', async () => {
    await renderModal()
    await fillName('A skincare study')
    await waitFor(() => expect(chip('Skincare')).toHaveAttribute('aria-checked', 'true'))

    fireEvent.click(chip('Baby Care'))              // locks inference
    await fillName('A haircare study')              // chips must not move
    expect(chip('Haircare')).toHaveAttribute('aria-checked', 'false')

    fireEvent.click(screen.getByRole('button', { name: /Reset to inferred/ }))

    // Re-inferred from "A haircare study" — NOT restored to the earlier
    // {Skincare} selection.
    expect(chip('Haircare')).toHaveAttribute('aria-checked', 'true')
    expect(chip('Skincare')).toHaveAttribute('aria-checked', 'false')
    expect(chip('Baby Care')).toHaveAttribute('aria-checked', 'false')
  })

  it('hides itself again after resetting, and comes back on the next edit', async () => {
    await renderModal()
    await fillName('A skincare study')
    fireEvent.click(chip('Baby Care'))

    fireEvent.click(screen.getByRole('button', { name: /Reset to inferred/ }))
    expect(screen.queryByRole('button', { name: /Reset to inferred/ })).not.toBeInTheDocument()

    fireEvent.click(chip('Baby Care'))
    expect(screen.getByRole('button', { name: /Reset to inferred/ })).toBeInTheDocument()
  })

  it('does not un-lock inference', async () => {
    await renderModal()
    await fillName('A skincare study')
    fireEvent.click(chip('Baby Care'))
    fireEvent.click(screen.getByRole('button', { name: /Reset to inferred/ }))

    await fillName('A haircare study')
    await waitFor(() => {})
    expect(chip('Haircare')).toHaveAttribute('aria-checked', 'false')
  })
})

// ─── questions by stage ───────────────────────────────────────────────────

describe('questions by stage', () => {
  it('derives the total live from the cells, with no separate total input', async () => {
    await renderModal()
    expect(screen.getByText('50 questions total')).toBeInTheDocument()

    // Balanced across four stages puts 13/13/12/12 in the cells; raising
    // the first from 13 to 20 has to move the derived total to 57.
    fireEvent.change(stageInput('Awareness'), { target: { value: '20' } })
    await waitFor(() =>
      expect(screen.getByText(/questions total/).textContent).toBe('57 questions total')
    )

    // Nothing the user could type a total into — two sources of truth
    // invites a silent reconciliation where nobody knows which won.
    expect(screen.queryByLabelText(/total/i)).not.toBeInTheDocument()
  })

  it('switches the preset to custom when a cell is edited', async () => {
    await renderModal()
    expect(screen.getByRole('radio', { name: 'Balanced' })).toHaveAttribute('aria-checked', 'true')

    fireEvent.change(stageInput('Research'), { target: { value: '30' } })

    expect(screen.getByRole('radio', { name: 'Custom' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('radio', { name: 'Balanced' })).toHaveAttribute('aria-checked', 'false')
  })

  it('applying a preset rewrites the cells and keeps the total', async () => {
    await renderModal()
    fireEvent.click(screen.getByRole('radio', { name: 'Decision-weighted' }))

    const first = Number(stageInput('Awareness').value)
    const last = Number(stageInput('Ready to Buy').value)
    expect(last).toBeGreaterThan(first)
    expect(screen.getByText('50 questions total')).toBeInTheDocument()
  })

  it('warns past the hundred-question ceiling and blocks submit', async () => {
    await renderModal()
    await fillName('A study')
    expect(screen.queryByText(/over the 100-question ceiling/)).not.toBeInTheDocument()

    fireEvent.change(stageInput('Awareness'), { target: { value: '90' } })

    expect(await screen.findByText(/over the 100-question ceiling/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Generate Questions/ })).toBeDisabled()
    expect(MAX_QUESTIONS).toBe(100)
  })
})

// ─── retailers and the naming rule ────────────────────────────────────────

describe('retailers to name', () => {
  it('offers no roles — no primary, no competitor', async () => {
    await renderModal()
    // A retailer has to be named for this helper line to be on screen: with
    // an empty list the study is unbranded and a line about how names are
    // used has nothing to describe. The assertions are unchanged — this
    // only puts the form into the state the line belongs to.
    await pickRetailer()
    expect(screen.queryByText(/primary entity is chosen at cycle creation/i)).toBeInTheDocument()
    expect(screen.queryByRole('radio', { name: /primary/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('radio', { name: /competitor/i })).not.toBeInTheDocument()
  })

  it('adds and removes rows, and picks from the entity registry', async () => {
    await renderModal()
    fireEvent.click(screen.getByRole('button', { name: '⊕ Add retailer' }))
    expect(screen.getByLabelText('Retailer 2')).toBeInTheDocument()

    fireEvent.focus(screen.getByLabelText('Retailer 1'))
    fireEvent.mouseDown(await screen.findByText('Sephora'))
    expect(screen.getByLabelText('Retailer 1')).toHaveValue('Sephora')

    fireEvent.click(screen.getByRole('button', { name: 'Remove retailer 2' }))
    expect(screen.queryByLabelText('Retailer 2')).not.toBeInTheDocument()
  })

  it('defaults the rotation checkbox on', async () => {
    await renderModal()
    await pickRetailer()   // rotation is hidden while the study is unbranded
    expect(screen.getByRole('checkbox', { name: /Rotate which retailer is named first/ })).toBeChecked()
  })
})

describe('the naming rule', () => {
  it('defaults on', async () => {
    await renderModal()
    expect(
      screen.getByRole('checkbox', { name: /Only name entities in Comparison and Ready to Buy/ })
    ).toBeChecked()
  })

  it('accepts an empty retailer list with the rule turned off', async () => {
    // Reversed rule. This combination used to be a blocking validation
    // error. It is a legitimate study: with no names anywhere the naming
    // rule has nothing to govern, so its value cannot make the study
    // invalid either way.
    await renderModal()
    await fillName('A study')

    fireEvent.click(
      screen.getByRole('checkbox', { name: /Only name entities in Comparison and Ready to Buy/ })
    )

    expect(screen.queryByText(/no retailers are listed/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Generate Questions/ })).toBeEnabled()
  })

  it('accepts an empty retailer list with the rule left on', async () => {
    await renderModal()
    await fillName('A study')
    expect(screen.getByRole('button', { name: /Generate Questions/ })).toBeEnabled()
  })

  it('is inert rather than hidden while the study is unbranded', async () => {
    // A control that vanishes leaves the reader wondering where it went;
    // one that greys out with a reason teaches how the fields relate.
    await renderModal()

    const box = screen.getByRole('checkbox', { name: /Only name entities in Comparison and Ready to Buy/ })
    expect(box).toBeInTheDocument()
    expect(box).toBeDisabled()
    expect(screen.getByText('Not applicable')).toBeInTheDocument()
    expect(screen.getByText(/No retailers are named anywhere in this study/)).toBeInTheDocument()
  })

  it('becomes live again once a retailer is named', async () => {
    await renderModal()
    await pickRetailer()

    const box = screen.getByRole('checkbox', { name: /Only name entities in Comparison and Ready to Buy/ })
    expect(box).toBeEnabled()
    expect(screen.queryByText('Not applicable')).not.toBeInTheDocument()
    expect(screen.getByText(/Awareness and Research questions describe the need/)).toBeInTheDocument()
  })
})

// ─── payload ──────────────────────────────────────────────────────────────

describe('the generation payload', () => {
  it('sends every structured field, with the total derived from the cells', async () => {
    const { onCreated } = await renderModal()

    await fillName('Prestige skincare study')
    fireEvent.change(screen.getByLabelText('What to ask about'), {
      target: { value: 'Where shoppers buy prestige serums' },
    })
    fireEvent.click(screen.getByRole('radio', { name: 'brand_at_retail' }))

    fireEvent.focus(screen.getByLabelText('Retailer 1'))
    fireEvent.mouseDown(await screen.findByText('Sephora'))

    fireEvent.change(stageInput('Awareness'), { target: { value: '5' } })
    fireEvent.change(stageInput('Research'), { target: { value: '5' } })
    fireEvent.change(stageInput('Comparison'), { target: { value: '5' } })
    fireEvent.change(stageInput('Ready to Buy'), { target: { value: '5' } })

    fireEvent.click(screen.getByRole('button', { name: /Advanced/ }))
    fireEvent.click(chip('Beauty Enthusiast'))
    fireEvent.click(screen.getByRole('radio', { name: 'Even split' }))

    fireEvent.click(screen.getByRole('button', { name: /Generate Questions/ }))

    await waitFor(() => expect(api.generateStudy).toHaveBeenCalled())
    expect(api.generateStudy.mock.calls[0][0]).toEqual({
      study_name: 'Prestige skincare study',
      description: 'Where shoppers buy prestige serums',
      target_count: 20,
      study_pattern: 'brand_at_retail',
      retailer_names: ['Sephora'],
      allowed_categories: ['Skincare'],
      stage_targets: {
        'Awareness': 5, 'Research': 5, 'Comparison': 5, 'Ready to Buy': 5,
      },
      rotate_named_retailer: true,
      naming_rule_enabled: true,
      personas: ['Beauty Enthusiast'],
      specificity_mode: 'even_split',
    })

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith('acme_1a2b3c'))
  })

  it('omits blank retailer rows', async () => {
    await renderModal()
    await fillName('A study')
    fireEvent.click(screen.getByRole('button', { name: '⊕ Add retailer' }))
    fireEvent.focus(screen.getByLabelText('Retailer 1'))
    fireEvent.mouseDown(await screen.findByText('Sephora'))

    fireEvent.click(screen.getByRole('button', { name: /Generate Questions/ }))
    await waitFor(() => expect(api.generateStudy).toHaveBeenCalled())
    expect(api.generateStudy.mock.calls[0][0].retailer_names).toEqual(['Sephora'])
  })

  it('surfaces a failure without closing the modal', async () => {
    api.generateStudy.mockRejectedValue(new Error('Study name already taken'))
    const { onCreated } = await renderModal()
    await fillName('A study')

    fireEvent.click(screen.getByRole('button', { name: /Generate Questions/ }))

    expect(await screen.findByText('Study name already taken')).toBeInTheDocument()
    expect(onCreated).not.toHaveBeenCalled()
  })

  it('needs a study name before it will submit', async () => {
    await renderModal()
    expect(screen.getByRole('button', { name: /Generate Questions/ })).toBeDisabled()
  })
})


// ─── unbranded studies ────────────────────────────────────────────────────
//
// An empty retailer list IS the unbranded study. There is deliberately no
// mode control: a toggle claiming "this is unbranded" could disagree with
// a list that has three retailers in it, and a control that can contradict
// the state it describes will eventually misreport it — the same reason
// the categories field has no auto-versus-manual toggle.

describe('the unbranded state', () => {
  it('offers no mode control — the list is the only truth', async () => {
    await renderModal()
    expect(screen.queryByRole('checkbox', { name: /unbranded/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('radio', { name: /unbranded/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^unbranded$/i })).not.toBeInTheDocument()
  })

  it('shows the panel, hides rotation and disables the naming rule when empty', async () => {
    await renderModal()

    expect(screen.getByText('Unbranded study — no retailers named')).toBeInTheDocument()
    expect(
      screen.queryByRole('checkbox', { name: /Rotate which retailer is named first/ })
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole('checkbox', { name: /Only name entities in Comparison and Ready to Buy/ })
    ).toBeDisabled()
  })

  it('names the three consequences, as information rather than a problem', async () => {
    await renderModal()
    const panel = screen.getByText(/Every question describes the need without naming a retailer/)

    expect(panel).toHaveTextContent(/every retailer mention has to be earned/i)
    expect(panel).toHaveTextContent(/weigh products and buying criteria rather than one retailer against another/i)
    expect(panel).toHaveTextContent(/strictest way to measure share of mentions/i)

    // Never framed as an error or a warning: no error copy, and being
    // unbranded is not on its own a reason submit is blocked.
    expect(screen.queryByText(/no retailers are listed/i)).not.toBeInTheDocument()
    await fillName('An unbranded study')
    expect(screen.getByRole('button', { name: /Generate Questions/ })).toBeEnabled()
  })

  it('restores all three the moment a retailer is added back', async () => {
    await renderModal()
    await pickRetailer()

    expect(screen.queryByText('Unbranded study — no retailers named')).not.toBeInTheDocument()
    expect(
      screen.getByRole('checkbox', { name: /Rotate which retailer is named first/ })
    ).toBeInTheDocument()
    expect(
      screen.getByRole('checkbox', { name: /Only name entities in Comparison and Ready to Buy/ })
    ).toBeEnabled()
  })

  it('returns to unbranded when the last retailer is removed', async () => {
    await renderModal()
    await pickRetailer()
    expect(screen.queryByText('Unbranded study — no retailers named')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Remove retailer 1' }))

    expect(await screen.findByText('Unbranded study — no retailers named')).toBeInTheDocument()
    expect(
      screen.queryByRole('checkbox', { name: /Rotate which retailer is named first/ })
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole('checkbox', { name: /Only name entities in Comparison and Ready to Buy/ })
    ).toBeDisabled()
  })

  it('submits an empty retailer list rather than blocking', async () => {
    await renderModal()
    await fillName('An unbranded study')
    fireEvent.click(screen.getByRole('button', { name: /Generate Questions/ }))

    await waitFor(() => expect(api.generateStudy).toHaveBeenCalled())
    expect(api.generateStudy.mock.calls[0][0].retailer_names).toEqual([])
  })
})
