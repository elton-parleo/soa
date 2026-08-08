/**
 * RequestFormModal — leadgen session. Presentational/behavioral tests
 * only: onSubmit is always a mock the test controls, since the modal
 * has no idea what API it's calling (see the component's own
 * docstring). Every test that exercises a real submit path advances
 * mocked Date.now() past MIN_ELAPSED_MS before clicking — the
 * component intentionally treats a too-fast submit as a spam trip
 * (Part 1c), and test code fills + submits far faster than that
 * threshold by default. Mocking Date.now() directly rather than
 * vi.useFakeTimers() — full timer faking stalls @testing-library's own
 * findBy/waitFor polling, which relies on real timers internally.
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import '@testing-library/jest-dom'

import { RequestFormModal, MIN_ELAPSED_MS } from '../RequestFormModal.jsx'

const CTA = {
  eyebrow: 'TRUESYNC',
  title: "Let's stop the leak.",
  messagePlaceholder: 'Tell us about your loyalty program and deals…',
}

let mockNow

beforeEach(() => {
  mockNow = 1_700_000_000_000
  vi.spyOn(Date, 'now').mockImplementation(() => mockNow)
})

afterEach(() => {
  vi.restoreAllMocks()
})

function passTimingGuard() {
  mockNow += MIN_ELAPSED_MS + 100
}

function renderModal(props = {}) {
  const onClose = vi.fn()
  const onSubmit = vi.fn().mockResolvedValue({ ok: true, status: 200, body: { ok: true } })
  const utils = render(
    <RequestFormModal
      open
      onClose={onClose}
      eyebrow={CTA.eyebrow}
      title={CTA.title}
      messagePlaceholder={CTA.messagePlaceholder}
      onSubmit={onSubmit}
      {...props}
    />,
  )
  return { ...utils, onClose, onSubmit }
}

function fillValidForm() {
  fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'Jane Smith' } })
  fireEvent.change(screen.getByLabelText(/^Email/), { target: { value: 'jane@company.com' } })
  fireEvent.change(screen.getByLabelText(/^Company/), { target: { value: 'Acme Corp' } })
}

describe('RequestFormModal — renders per-CTA copy', () => {
  it('shows the eyebrow, title, and message placeholder passed in', () => {
    renderModal()
    expect(screen.getByText('TRUESYNC')).toBeInTheDocument()
    expect(screen.getByText("Let's stop the leak.")).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Tell us about your loyalty program and deals…')).toBeInTheDocument()
  })

  it('shows the Name/Email/Company placeholders from the brief', () => {
    renderModal()
    expect(screen.getByPlaceholderText('Jane Smith')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('jane@company.com')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Acme Corp')).toBeInTheDocument()
  })

  it('renders nothing when open is false', () => {
    const { container } = render(
      <RequestFormModal open={false} onClose={() => {}} eyebrow="X" title="Y" messagePlaceholder="Z" onSubmit={vi.fn()} />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})

describe('RequestFormModal — client-side validation', () => {
  it('shows required-field errors and never calls onSubmit when the form is empty', async () => {
    const { onSubmit } = renderModal()
    passTimingGuard()

    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    expect(await screen.findByText('Name is required')).toBeInTheDocument()
    expect(screen.getByText('Email is required')).toBeInTheDocument()
    expect(screen.getByText('Company is required')).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('flags an invalid email shape', async () => {
    const { onSubmit } = renderModal()
    passTimingGuard()
    fillValidForm()
    fireEvent.change(screen.getByLabelText(/^Email/), { target: { value: 'not-an-email' } })

    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    expect(await screen.findByText('Enter a valid email address')).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('submits with the trimmed field values once valid', async () => {
    const { onSubmit } = renderModal()
    passTimingGuard()
    fillValidForm()
    fireEvent.change(screen.getByLabelText(/^Message/), { target: { value: '  loyalty details  ' } })

    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({
      name: 'Jane Smith', email: 'jane@company.com', company: 'Acme Corp', message: 'loyalty details',
    }))
  })
})

describe('RequestFormModal — success and failure states', () => {
  it('replaces the form with the two-state success design on ok', async () => {
    const { onSubmit } = renderModal()
    passTimingGuard()
    fillValidForm()

    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))
    await waitFor(() => expect(onSubmit).toHaveBeenCalled())

    expect(await screen.findByText('Message sent')).toBeInTheDocument()
    expect(screen.getByText('We’ll get back to you shortly.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Send message/ })).not.toBeInTheDocument()
  })

  it('shows the failure line and preserves entered values when onSubmit resolves not-ok', async () => {
    const onSubmit = vi.fn().mockResolvedValue({ ok: false, status: 500, body: null })
    renderModal({ onSubmit })
    passTimingGuard()
    fillValidForm()

    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    expect(await screen.findByText('Something went wrong — email us at elton@parleo.io')).toBeInTheDocument()
    expect(screen.getByLabelText(/^Name/)).toHaveValue('Jane Smith')
    expect(screen.getByLabelText(/^Email/)).toHaveValue('jane@company.com')
    expect(screen.getByLabelText(/^Company/)).toHaveValue('Acme Corp')
  })

  it('renders per-field errors from a 422 response and preserves entered values', async () => {
    const onSubmit = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      body: { detail: [{ loc: ['body', 'email'], msg: 'email must be a valid email address' }] },
    })
    renderModal({ onSubmit })
    passTimingGuard()
    fillValidForm()

    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    expect(await screen.findByText('email must be a valid email address')).toBeInTheDocument()
    expect(screen.getByLabelText(/^Company/)).toHaveValue('Acme Corp')
  })

  it('disables the button and shows "Sending…" while submitting', async () => {
    let resolveSubmit
    const onSubmit = vi.fn(() => new Promise((resolve) => { resolveSubmit = resolve }))
    renderModal({ onSubmit })
    passTimingGuard()
    fillValidForm()

    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    expect(await screen.findByRole('button', { name: 'Sending…' })).toBeDisabled()
    resolveSubmit({ ok: true, status: 200, body: { ok: true } })
    await screen.findByText('Message sent')
  })
})

describe('RequestFormModal — anti-spam', () => {
  it('honeypot filled: shows success without calling onSubmit', async () => {
    const { onSubmit, container } = renderModal()
    passTimingGuard()
    fillValidForm()
    const honeypot = container.querySelector('input[name="website"]')
    fireEvent.change(honeypot, { target: { value: 'http://spam.example' } })

    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    expect(await screen.findByText('Message sent')).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('submitted faster than MIN_ELAPSED_MS: shows success without calling onSubmit, even with a fully valid form', async () => {
    const { onSubmit } = renderModal()
    fillValidForm()

    // No time advance — this submit happens "instantly" from the
    // component's perspective, same as a script that fills and posts
    // without ever letting a human read the form.
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    expect(await screen.findByText('Message sent')).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })
})

describe('RequestFormModal — close behavior and focus', () => {
  it('closes on the X button', () => {
    const { onClose } = renderModal()
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('closes on backdrop click, not on a click inside the card', () => {
    const { onClose, container } = renderModal()
    const overlay = container.querySelector('.lite-request-modal-overlay')
    const card = container.querySelector('.lite-request-modal-card')

    fireEvent.mouseDown(card)
    expect(onClose).not.toHaveBeenCalled()

    fireEvent.mouseDown(overlay)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('closes on Escape', () => {
    const { onClose } = renderModal()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('returns focus to the previously-focused element when the parent unmounts it on close', () => {
    const trigger = document.createElement('button')
    trigger.textContent = 'Open modal'
    document.body.appendChild(trigger)
    trigger.focus()
    expect(document.activeElement).toBe(trigger)

    const { rerender, onClose } = renderModal()
    // Every CTA call site unmounts the modal on close (demoModal.cta
    // is null once closed) rather than just flipping `open` to false —
    // simulate that here since it's the real-world path.
    rerender(<RequestFormModal open={false} onClose={onClose} eyebrow="X" title="Y" messagePlaceholder="Z" onSubmit={vi.fn()} />)

    expect(document.activeElement).toBe(trigger)
    document.body.removeChild(trigger)
  })

  it('is aria-modal with a dialog role', () => {
    renderModal()
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true')
  })
})
