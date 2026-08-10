/**
 * Restores the pre-V4 "Copy link" behavior (Stage 9 U3) as
 * ShareReportButton. vi.useFakeTimers() is scoped to individual tests
 * (not a global beforeEach) since it conflicts with @testing-library's
 * own findBy/waitFor polling — this file never uses findBy/waitFor
 * under fake timers, only fireEvent + manual microtask flushes + a
 * synchronous getByText/queryByText read, matching the pattern
 * established in RequestFormModal.test.jsx.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, fireEvent, act } from '@testing-library/react'
import '@testing-library/jest-dom'

import { ShareReportButton } from '../ShareReportButton.jsx'
import { PUBLIC_AUDIT_BASE_URL } from '../../publicUrls.js'

const TOKEN = 'tok-abc123'
const CANONICAL_URL = `${PUBLIC_AUDIT_BASE_URL}/r/${TOKEN}`

async function flushMicrotasks() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

function mockClipboard(writeText) {
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText },
    configurable: true,
  })
}

function removeClipboard() {
  Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
}

afterEach(() => {
  vi.useRealTimers()
  removeClipboard()
  delete document.execCommand
})

describe('ShareReportButton — copies the canonical URL', () => {
  it('writes PUBLIC_AUDIT_BASE_URL/r/{token} exactly, no query string or hash', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    mockClipboard(writeText)

    const { getByRole } = render(<ShareReportButton token={TOKEN} />)
    fireEvent.click(getByRole('button', { name: 'Share report' }))
    await flushMicrotasks()

    expect(writeText).toHaveBeenCalledWith(CANONICAL_URL)
    expect(writeText.mock.calls[0][0]).not.toMatch(/[?#]/)
  })

  it('never window.location.href — different token than the current page still copies the token it was given', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    mockClipboard(writeText)
    window.history.pushState(null, '', '/r/some-other-token?utm_source=test#frag')

    const { getByRole } = render(<ShareReportButton token={TOKEN} />)
    fireEvent.click(getByRole('button', { name: 'Share report' }))
    await flushMicrotasks()

    expect(writeText).toHaveBeenCalledWith(CANONICAL_URL)
    window.history.pushState(null, '', '/')
  })
})

describe('ShareReportButton — copied-state confirmation', () => {
  it('shows Copied immediately after copying, and reverts to Share report after ~2s', async () => {
    vi.useFakeTimers()
    const writeText = vi.fn().mockResolvedValue(undefined)
    mockClipboard(writeText)

    const { getByRole, queryByText } = render(<ShareReportButton token={TOKEN} />)
    fireEvent.click(getByRole('button', { name: /Share report/ }))
    await flushMicrotasks()

    expect(queryByText('Copied')).toBeInTheDocument()
    expect(queryByText('Share report')).not.toBeInTheDocument()

    act(() => { vi.advanceTimersByTime(2000) })

    expect(queryByText('Share report')).toBeInTheDocument()
    expect(queryByText('Copied')).not.toBeInTheDocument()
  })

  it('re-clicking while already in the copied state re-copies harmlessly and resets the timer', async () => {
    vi.useFakeTimers()
    const writeText = vi.fn().mockResolvedValue(undefined)
    mockClipboard(writeText)

    const { getByRole, queryByText } = render(<ShareReportButton token={TOKEN} />)
    const btn = getByRole('button', { name: /Share report/ })

    fireEvent.click(btn)
    await flushMicrotasks()
    expect(queryByText('Copied')).toBeInTheDocument()

    act(() => { vi.advanceTimersByTime(1500) })
    fireEvent.click(btn)
    await flushMicrotasks()
    expect(writeText).toHaveBeenCalledTimes(2)

    // 3000ms since the first click, but only 1500ms since the reset —
    // still copied because the timer restarted on the second click.
    act(() => { vi.advanceTimersByTime(1500) })
    expect(queryByText('Copied')).toBeInTheDocument()

    act(() => { vi.advanceTimersByTime(600) })
    expect(queryByText('Share report')).toBeInTheDocument()
  })

  it('announces "Link copied" via the aria-live region', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    mockClipboard(writeText)

    const { getByRole, container } = render(<ShareReportButton token={TOKEN} />)
    fireEvent.click(getByRole('button', { name: 'Share report' }))
    await flushMicrotasks()
    // The announce text is set one macrotask later (see the component's
    // own comment on why — a repeat click needs the region's content to
    // actually change to re-announce).
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })

    const live = container.querySelector('[aria-live="polite"]')
    expect(live).toBeInTheDocument()
    expect(live.textContent).toBe('Link copied')
  })

  it('focus stays on the button after copying', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    mockClipboard(writeText)

    const { getByRole } = render(<ShareReportButton token={TOKEN} />)
    const btn = getByRole('button', { name: 'Share report' })
    fireEvent.click(btn)
    await flushMicrotasks()

    expect(document.activeElement).toBe(btn)
  })
})

describe('ShareReportButton — clipboard fallbacks', () => {
  it('falls back to document.execCommand("copy") when navigator.clipboard is unavailable', async () => {
    removeClipboard()
    const execCommand = vi.fn(() => true)
    document.execCommand = execCommand

    const { getByRole, queryByText } = render(<ShareReportButton token={TOKEN} />)
    fireEvent.click(getByRole('button', { name: 'Share report' }))
    await flushMicrotasks()

    expect(execCommand).toHaveBeenCalledWith('copy')
    expect(queryByText('Copied')).toBeInTheDocument()
  })

  it('shows a read-only input with the URL, selected, plus a Copy button when both methods fail — never a dead button', async () => {
    removeClipboard()
    document.execCommand = vi.fn(() => false)

    const { getByRole, getByDisplayValue, queryByText } = render(<ShareReportButton token={TOKEN} />)
    fireEvent.click(getByRole('button', { name: 'Share report' }))
    await flushMicrotasks()

    expect(queryByText('Copied')).not.toBeInTheDocument()
    const input = getByDisplayValue(CANONICAL_URL)
    expect(input).toHaveAttribute('readonly')
    expect(document.activeElement).toBe(input)
    expect(getByRole('button', { name: 'Copy' })).toBeInTheDocument()
  })

  it('never throws even if clipboard.writeText rejects and execCommand also throws', async () => {
    mockClipboard(vi.fn().mockRejectedValue(new Error('denied')))
    document.execCommand = vi.fn(() => { throw new Error('nope') })

    const { getByRole } = render(<ShareReportButton token={TOKEN} />)
    expect(() => fireEvent.click(getByRole('button', { name: 'Share report' }))).not.toThrow()
    await flushMicrotasks()
  })
})

describe('ShareReportButton — compact variant', () => {
  it('renders icon-only with an accessible name, and swaps to a "Link copied" label + tooltip once copied', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    mockClipboard(writeText)

    const { getByRole, queryByText } = render(<ShareReportButton token={TOKEN} compact />)
    expect(getByRole('button', { name: 'Share report' })).toBeInTheDocument()

    fireEvent.click(getByRole('button', { name: 'Share report' }))
    await flushMicrotasks()

    expect(getByRole('button', { name: 'Link copied' })).toBeInTheDocument()
    expect(queryByText('Copied')).toBeInTheDocument()
  })

  it('meets the 44px hit area via the same className the sticky bar\'s Sections button uses', () => {
    const { container } = render(<ShareReportButton token={TOKEN} compact />)
    expect(container.querySelector('button').className).toContain('lite-report-mobile-sections-btn')
  })
})
