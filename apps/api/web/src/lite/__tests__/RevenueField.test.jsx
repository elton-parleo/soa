/**
 * The shared revenue control: a logarithmic slider plus a typed amount.
 * Both surfaces that use it (the report's ADJUST ASSUMPTIONS panel and
 * the landing Stakes widget) get their behavior from here, so it is
 * tested once, directly.
 */
import React, { useState } from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import '@testing-library/jest-dom'

import { RevenueField } from '../RevenueField.jsx'
import { REVENUE_SLIDER_STEPS, REVENUE_SLIDER_MAX, MAX_PLAUSIBLE_REVENUE_USD } from '../liteDerive.js'

function Harness({ initial = 12_000_000, onInteract }) {
  const [revenue, setRevenue] = useState(initial)
  return (
    <>
      <RevenueField revenue={revenue} onRevenueChange={setRevenue} onInteract={onInteract} />
      <output data-testid="value">{revenue}</output>
    </>
  )
}

const amountInput = () => screen.getByLabelText('Annual revenue (exact amount)')
const slider = () => screen.getByLabelText('Annual revenue')
const committed = () => Number(screen.getByTestId('value').textContent)

function type(text) {
  fireEvent.change(amountInput(), { target: { value: text } })
  fireEvent.blur(amountInput())
}

describe('RevenueField — typed amount', () => {
  it.each([
    ['100m', 100_000_000],
    ['1.2b', 1_200_000_000],
    ['$500,000,000', 500_000_000],
    ['750000', 750_000],
  ])('parses %s as %i', (text, expected) => {
    render(<Harness />)
    type(text)
    expect(committed()).toBe(expected)
  })

  it('commits on Enter as well as blur', () => {
    render(<Harness />)
    fireEvent.change(amountInput(), { target: { value: '250m' } })
    fireEvent.keyDown(amountInput(), { key: 'Enter' })
    expect(committed()).toBe(250_000_000)
  })

  it('rejects non-numeric input inline and leaves the value alone', () => {
    render(<Harness initial={12_000_000} />)
    type('abc')
    expect(committed()).toBe(12_000_000)
    expect(amountInput()).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByText(/ENTER AN AMOUNT/)).toBeInTheDocument()
  })

  it('clears the rejection once the text becomes readable', () => {
    render(<Harness />)
    type('abc')
    expect(screen.getByText(/ENTER AN AMOUNT/)).toBeInTheDocument()
    type('2b')
    expect(screen.queryByText(/ENTER AN AMOUNT/)).not.toBeInTheDocument()
    expect(committed()).toBe(2_000_000_000)
  })

  it('clamps to the plausibility bounds, not the slider bounds', () => {
    render(<Harness />)
    type('50000000000000')
    expect(committed()).toBe(MAX_PLAUSIBLE_REVENUE_USD)
  })

  it('displays the committed value in shorthand', () => {
    render(<Harness initial={1_200_000_000} />)
    expect(amountInput()).toHaveValue('$1.2B')
  })

  it('fires the interaction callback once the amount is committed', () => {
    const onInteract = vi.fn()
    render(<Harness onInteract={onInteract} />)
    type('300m')
    expect(onInteract).toHaveBeenCalled()
  })

  it('does not fire the interaction callback for input it rejected', () => {
    const onInteract = vi.fn()
    render(<Harness onInteract={onInteract} />)
    type('abc')
    expect(onInteract).not.toHaveBeenCalled()
  })
})

describe('RevenueField — slider and amount stay in sync', () => {
  it('a slider drag updates the displayed amount', () => {
    render(<Harness />)
    fireEvent.change(slider(), { target: { value: '750' } })
    expect(committed()).toBe(350_000_000)
    expect(amountInput()).toHaveValue('$350M')
  })

  it('a typed amount moves the slider', () => {
    render(<Harness initial={120_000} />)
    expect(slider()).toHaveValue('0')
    type('24m')
    // Position 500 on the log track — see liteDerive.test.js.
    expect(Number(slider().value)).toBeGreaterThan(490)
    expect(Number(slider().value)).toBeLessThan(510)
  })

  // The whole point of not clamping the seed any more: a figure beyond
  // the track's ceiling keeps its real size. The track pins; the number
  // the merchant sees, and the number the model uses, do not.
  it('a typed $8B pins the slider at max while the value stays $8B', () => {
    render(<Harness />)
    type('8b')
    expect(committed()).toBe(8_000_000_000)
    expect(committed()).toBeGreaterThan(REVENUE_SLIDER_MAX)
    expect(slider()).toHaveValue(String(REVENUE_SLIDER_STEPS))
    expect(amountInput()).toHaveValue('$8B')
  })

  it('a seeded value above the ceiling renders pinned, never silently reduced', () => {
    render(<Harness initial={8_000_000_000} />)
    expect(slider()).toHaveValue(String(REVENUE_SLIDER_STEPS))
    expect(amountInput()).toHaveValue('$8B')
  })

  it('a slider drag discards a half-typed draft rather than showing two different numbers', () => {
    render(<Harness />)
    fireEvent.change(amountInput(), { target: { value: '99' } })   // not committed
    fireEvent.change(slider(), { target: { value: '750' } })
    expect(amountInput()).toHaveValue('$350M')
    expect(committed()).toBe(350_000_000)
  })
})
