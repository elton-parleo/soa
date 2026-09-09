/**
 * The regenerate choice.
 *
 * One property matters more than the rest: rewriting the AI-written tier
 * is OFF by default, and the modal says why. Different question wording
 * breaks run-over-run comparability with every cycle before it, and a
 * checkbox that defaulted on would spend that silently.
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import RegenerateStudyModal from '../RegenerateStudyModal.jsx'
import { api } from '../../api.js'

vi.mock('../../api.js', () => ({
  api: { regenerateStudy: vi.fn() },
}))

beforeEach(() => {
  vi.clearAllMocks()
  api.regenerateStudy.mockResolvedValue({
    study_type: 'ws_1a2b3c', status: 'pending',
    tiers: ['catalog_accuracy', 'value_incentives'],
  })
})

function renderModal(props = {}) {
  const onClose = props.onClose || vi.fn()
  const onStarted = props.onStarted || vi.fn()
  render(
    <RegenerateStudyModal
      open studyType="ws_1a2b3c" merchant="Wiggle & Snug"
      onClose={onClose} onStarted={onStarted} {...props}
    />,
  )
  return { onClose, onStarted }
}

const aiCheckbox = () =>
  screen.getByLabelText(/Also rewrite the AI-written brand questions/i, { selector: 'input' })

describe('the AI choice', () => {
  it('is off by default', () => {
    renderModal()
    expect(aiCheckbox()).not.toBeChecked()
  })

  it('says why leaving it off is the safe answer', () => {
    renderModal()
    expect(screen.getByText(/cannot\s+be compared run-over-run/)).toBeInTheDocument()
  })

  it('sends regenerate_ai false when untouched', async () => {
    renderModal()
    fireEvent.click(screen.getByText('Regenerate'))

    await waitFor(() => expect(api.regenerateStudy).toHaveBeenCalled())
    expect(api.regenerateStudy).toHaveBeenCalledWith('ws_1a2b3c', false)
  })

  it('sends regenerate_ai true when ticked', async () => {
    renderModal()
    fireEvent.click(aiCheckbox())
    fireEvent.click(screen.getByText('Regenerate'))

    await waitFor(() => expect(api.regenerateStudy).toHaveBeenCalled())
    expect(api.regenerateStudy).toHaveBeenCalledWith('ws_1a2b3c', true)
  })
})

describe('what it tells the user', () => {
  it('states that the catalog questions are always rebuilt', () => {
    renderModal()
    expect(screen.getByText(/rebuilt from the record as it is published/)).toBeInTheDocument()
  })

  it('names the brand it will read', () => {
    renderModal()
    expect(screen.getByText(/for Wiggle & Snug/)).toBeInTheDocument()
  })

  it('promises that past measurements survive', () => {
    renderModal()
    expect(screen.getByText(/never deleted/)).toBeInTheDocument()
  })
})

describe('the outcome', () => {
  it('closes and reports back on success', async () => {
    const { onClose, onStarted } = renderModal()
    fireEvent.click(screen.getByText('Regenerate'))

    await waitFor(() => expect(onStarted).toHaveBeenCalled())
    expect(onClose).toHaveBeenCalled()
  })

  it('stays open and shows the error on failure', async () => {
    api.regenerateStudy.mockRejectedValue(new Error('already generating'))
    const { onClose } = renderModal()
    fireEvent.click(screen.getByText('Regenerate'))

    await screen.findByText('already generating')
    expect(onClose).not.toHaveBeenCalled()
  })

  it('renders nothing when closed', () => {
    const { container } = render(
      <RegenerateStudyModal open={false} studyType="ws" onClose={vi.fn()} />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})
