import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import '@testing-library/jest-dom'

import StudyLibrary from '../StudyLibrary.jsx'
import { api } from '../../api.js'

vi.mock('../../api.js', () => ({
  api: {
    getStudies: vi.fn(),
    uploadStudyCsv: vi.fn(),
    getQueryConstraints: vi.fn(),
    getEntities: vi.fn(),
    generateStudy: vi.fn(),
  },
}))

vi.mock('../Sidebar.jsx', () => ({ default: () => <nav /> }))

/**
 * The join between the studies page and the Create Study modal.
 *
 * This file exists because of a bug that neither existing suite could
 * catch. CreateStudyModal.test.jsx renders the modal directly and covers
 * its internals; nothing rendered StudyLibrary and pressed the button. So
 * when the modal was rebuilt and its form state moved inside it, the
 * page's trigger was left calling setAiForm and setAiError — setters that
 * no longer existed anywhere. The handler threw a ReferenceError on its
 * first line and never reached setAiModalOpen, so the button silently did
 * nothing, and both halves of the test suite stayed green.
 *
 * Every test here goes through the real button.
 */

const CONSTRAINTS = {
  category:      ['Skincare', 'Haircare', 'Baby Care'],
  stage:         ['Awareness', 'Research', 'Comparison', 'Ready to Buy'],
  specificity:   ['Broad', 'Mid', 'Narrow'],
  persona:       ['Beauty Enthusiast', 'Value-Conscious'],
  status:        ['Active', 'Paused'],
  study_pattern: ['retailer', 'brand_at_retail', 'brand_vs_brand'],
}

const STUDIES = [
  { id: 'retailer_sephora', name: 'Sephora Retail', category: 'Skincare',
    queryCount: 50, patterns: ['retailer'] },
]

let consoleError

beforeEach(() => {
  vi.clearAllMocks()
  api.getStudies.mockResolvedValue(STUDIES)
  api.getQueryConstraints.mockResolvedValue(CONSTRAINTS)
  api.getEntities.mockResolvedValue([
    { id: 1, name: 'Sephora', category: 'beauty', type: 'Retailer' },
  ])
  api.generateStudy.mockResolvedValue({ study_type: 'acme_1a2b3c' })
  consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  consoleError.mockRestore()
})

async function renderPage() {
  const onSelectStudy = vi.fn()
  render(<StudyLibrary onNavigate={vi.fn()} onSelectStudy={onSelectStudy} />)
  await screen.findByText('Study Library')
  return { onSelectStudy }
}

function trigger() {
  return screen.getByRole('button', { name: /Create Study with AI/ })
}

async function openModal() {
  fireEvent.click(trigger())
  return screen.findByRole('dialog', { name: 'Create Study with AI' })
}

function closeModal() {
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
}

function chip(name) {
  return screen.getByRole('checkbox', { name })
}

const stageInput = (stage) => document.getElementById(`stage-${stage}`)


// ─── the trigger actually opens the modal ─────────────────────────────────

describe('the Create Study with AI trigger', () => {
  it('is on the page before anything is clicked', async () => {
    await renderPage()
    expect(trigger()).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('opens the modal when clicked', async () => {
    await renderPage()
    const dialog = await openModal()

    expect(dialog).toBeInTheDocument()
    expect(screen.getByLabelText('Study Name')).toBeInTheDocument()
  })

  it('throws nothing while handling the click', async () => {
    // The regression itself: the handler died on its first statement, so
    // the two after it never ran. An assertion on the modal alone would
    // pass again the moment the FIRST stale reference was fixed, even
    // with a second one still behind it.
    await renderPage()

    const thrown = []
    const onError = (e) => thrown.push(e.error || e.reason)
    window.addEventListener('error', onError)
    try {
      fireEvent.click(trigger())
      await screen.findByRole('dialog', { name: 'Create Study with AI' })
    } finally {
      window.removeEventListener('error', onError)
    }

    expect(thrown).toEqual([])
  })

  it('loads the modal options through the page, not a direct render', async () => {
    await renderPage()
    await openModal()

    await waitFor(() => expect(api.getQueryConstraints).toHaveBeenCalled())
    expect(api.getEntities).toHaveBeenCalled()
    expect(await screen.findByRole('radio', { name: 'retailer' })).toBeInTheDocument()
  })

  it('closes again from Cancel', async () => {
    await renderPage()
    await openModal()

    closeModal()
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})


// ─── the initialization the trigger used to be responsible for ────────────

describe('a fresh open starts from defaults', () => {
  it('opens empty the first time', async () => {
    await renderPage()
    await openModal()

    expect(screen.getByLabelText('Study Name')).toHaveValue('')
    expect(screen.getByLabelText('What to ask about')).toHaveValue('')
    expect(chip('Skincare')).toHaveAttribute('aria-checked', 'false')
    expect(await screen.findByText('50 questions total')).toBeInTheDocument()
  })

  it('does not show the previous open\'s name and description', async () => {
    // The modal is never unmounted — `open` is a prop and the early
    // return is after the hooks — so without an explicit reset every
    // field survives a close.
    await renderPage()
    await openModal()

    fireEvent.change(screen.getByLabelText('Study Name'), {
      target: { value: 'A skincare study' },
    })
    fireEvent.change(screen.getByLabelText('What to ask about'), {
      target: { value: 'Serums and cleansers' },
    })
    closeModal()

    await openModal()
    expect(screen.getByLabelText('Study Name')).toHaveValue('')
    expect(screen.getByLabelText('What to ask about')).toHaveValue('')
  })

  it('does not carry over inferred or hand-picked categories', async () => {
    await renderPage()
    await openModal()

    fireEvent.change(screen.getByLabelText('Study Name'), {
      target: { value: 'A skincare study' },
    })
    await waitFor(() => expect(chip('Skincare')).toHaveAttribute('aria-checked', 'true'))
    fireEvent.click(chip('Baby Care'))
    closeModal()

    await openModal()
    expect(chip('Skincare')).toHaveAttribute('aria-checked', 'false')
    expect(chip('Baby Care')).toHaveAttribute('aria-checked', 'false')
  })

  it('unlocks inference again, and hides the reset control', async () => {
    await renderPage()
    await openModal()

    fireEvent.click(chip('Skincare'))                     // locks inference
    expect(screen.getByRole('button', { name: /Reset to inferred/ })).toBeInTheDocument()
    closeModal()

    await openModal()
    expect(screen.queryByRole('button', { name: /Reset to inferred/ })).not.toBeInTheDocument()

    // Inference is live again on the new open.
    fireEvent.change(screen.getByLabelText('Study Name'), {
      target: { value: 'A haircare study' },
    })
    await waitFor(() => expect(chip('Haircare')).toHaveAttribute('aria-checked', 'true'))
  })

  it('restores the default preset and stage counts', async () => {
    await renderPage()
    await openModal()

    await screen.findByText('50 questions total')
    fireEvent.change(stageInput('Awareness'), { target: { value: '40' } })
    expect(screen.getByRole('radio', { name: 'Custom' })).toHaveAttribute('aria-checked', 'true')
    closeModal()

    await openModal()
    await waitFor(() =>
      expect(screen.getByRole('radio', { name: 'Balanced' })).toHaveAttribute('aria-checked', 'true')
    )
    expect(screen.getByText('50 questions total')).toBeInTheDocument()
    expect(stageInput('Awareness')).toHaveValue(13)
  })

  it('restores the default study pattern', async () => {
    await renderPage()
    await openModal()

    await screen.findByRole('radio', { name: 'retailer' })
    fireEvent.click(screen.getByRole('radio', { name: 'brand_vs_brand' }))
    expect(screen.getByRole('radio', { name: 'brand_vs_brand' })).toHaveAttribute('aria-checked', 'true')
    closeModal()

    await openModal()
    await waitFor(() =>
      expect(screen.getByRole('radio', { name: 'retailer' })).toHaveAttribute('aria-checked', 'true')
    )
  })

  it('restores the checkboxes, retailer rows and Advanced section', async () => {
    await renderPage()
    await openModal()

    // Naming a retailer takes the study out of its unbranded state, which
    // is what puts the rotation control on screen at all. Every assertion
    // below is unchanged.
    fireEvent.focus(screen.getByLabelText('Retailer 1'))
    fireEvent.mouseDown(await screen.findByText('Sephora'))

    fireEvent.click(screen.getByRole('checkbox', { name: /Rotate which retailer is named first/ }))
    fireEvent.click(screen.getByRole('button', { name: '⊕ Add retailer' }))
    fireEvent.click(screen.getByRole('button', { name: /Advanced/ }))
    expect(screen.getByLabelText('Retailer 2')).toBeInTheDocument()
    closeModal()

    await openModal()
    // The reopened form is unbranded again, so rotation is gone with it —
    // that IS the reset. Naming one puts it back, defaulted on.
    expect(screen.queryByRole('checkbox', { name: /Rotate which retailer is named first/ })).not.toBeInTheDocument()
    fireEvent.focus(screen.getByLabelText('Retailer 1'))
    fireEvent.mouseDown(await screen.findByText('Sephora'))
    expect(screen.getByRole('checkbox', { name: /Rotate which retailer is named first/ })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /Only name entities in Comparison/ })).toBeChecked()
    expect(screen.queryByLabelText('Retailer 2')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Advanced/ })).toHaveAttribute('aria-expanded', 'false')
  })

  it('clears a submit error from the previous open', async () => {
    api.generateStudy.mockRejectedValue(new Error('Study name already taken'))
    await renderPage()
    await openModal()

    fireEvent.change(screen.getByLabelText('Study Name'), { target: { value: 'Taken' } })
    fireEvent.click(screen.getByRole('button', { name: /Generate Questions/ }))
    expect(await screen.findByText('Study name already taken')).toBeInTheDocument()
    closeModal()

    await openModal()
    expect(screen.queryByText('Study name already taken')).not.toBeInTheDocument()
  })
})


// ─── the page still receives what the modal produces ──────────────────────

describe('a successful create, driven from the page', () => {
  it('navigates to the new study and closes the modal', async () => {
    const { onSelectStudy } = await renderPage()
    await openModal()

    fireEvent.change(screen.getByLabelText('Study Name'), {
      target: { value: 'Prestige Beauty' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Generate Questions/ }))

    await waitFor(() => expect(onSelectStudy).toHaveBeenCalledWith('acme_1a2b3c'))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})
