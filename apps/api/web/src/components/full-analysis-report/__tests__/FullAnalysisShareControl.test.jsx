/**
 * 2e: FullAnalysisShareControl — the owner Share/Revoke control.
 * Confirms the actually load-bearing behaviors: no link exists until
 * the button's first click (never eager), the link is create-or-return
 * (never a surprise second token), and a revoke really does invalidate
 * the button's own cached URL rather than leaving it copying a stale
 * one (the key={shareToken || 'none'} remount this depends on).
 */
import React from 'react'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import { FullAnalysisShareControl } from '../FullAnalysisShareControl.jsx'
import { api } from '../../../api.js'
import { PUBLIC_APP_BASE_URL } from '../../../publicFullAnalysisUrls.js'

vi.mock('../../../api.js', () => ({
  api: {
    getShareLink: vi.fn(),
    createShareLink: vi.fn(),
    revokeShareLink: vi.fn(),
  },
}))

function mockClipboard(writeText) {
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
}

async function flushMicrotasks() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
})

describe('FullAnalysisShareControl — no link until the first click', () => {
  it('shows "Share report", not "Revoke link", when getShareLink resolves null', async () => {
    api.getShareLink.mockResolvedValue(null)
    render(<FullAnalysisShareControl cycleCode="c-1" />)

    await waitFor(() => expect(screen.getByRole('button', { name: 'Share report' })).toBeInTheDocument())
    expect(screen.queryByText('Revoke link')).not.toBeInTheDocument()
    expect(api.createShareLink).not.toHaveBeenCalled()
  })

  it('shows "Revoke link" immediately when getShareLink already returns an active token', async () => {
    api.getShareLink.mockResolvedValue({ token: 'existing-tok', created_at: '2026-08-18', expires_at: null })
    render(<FullAnalysisShareControl cycleCode="c-1" />)

    await waitFor(() => expect(screen.getByText('Revoke link')).toBeInTheDocument())
    expect(api.createShareLink).not.toHaveBeenCalled()
  })
})

describe('FullAnalysisShareControl — create on first click', () => {
  it('creates the link and copies the /fa/{token} URL on the first click', async () => {
    api.getShareLink.mockResolvedValue(null)
    api.createShareLink.mockResolvedValue({ token: 'new-tok', created_at: '2026-08-18', expires_at: null })
    const writeText = vi.fn().mockResolvedValue(undefined)
    mockClipboard(writeText)

    render(<FullAnalysisShareControl cycleCode="c-1" />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Share report' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Share report' }))
    await waitFor(() => expect(api.createShareLink).toHaveBeenCalledWith('c-1'))
    await flushMicrotasks()

    expect(writeText).toHaveBeenCalledWith(`${PUBLIC_APP_BASE_URL}/fa/new-tok`)
    await waitFor(() => expect(screen.getByText('Revoke link')).toBeInTheDocument())
  })

  it('a second click never creates a second link', async () => {
    api.getShareLink.mockResolvedValue(null)
    api.createShareLink.mockResolvedValue({ token: 'new-tok', created_at: '2026-08-18', expires_at: null })
    mockClipboard(vi.fn().mockResolvedValue(undefined))

    render(<FullAnalysisShareControl cycleCode="c-1" />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Share report' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /Share report|Copied/ }))
    await waitFor(() => expect(api.createShareLink).toHaveBeenCalledTimes(1))
    await flushMicrotasks()

    fireEvent.click(screen.getByRole('button', { name: /Copied|Share report/ }))
    await flushMicrotasks()

    expect(api.createShareLink).toHaveBeenCalledTimes(1)
  })
})

describe('FullAnalysisShareControl — revoke', () => {
  it('revoking calls the API, removes "Revoke link", and reverts to "Share report"', async () => {
    api.getShareLink.mockResolvedValue({ token: 'existing-tok', created_at: '2026-08-18', expires_at: null })
    api.revokeShareLink.mockResolvedValue({ revoked: true })

    render(<FullAnalysisShareControl cycleCode="c-1" />)
    await waitFor(() => expect(screen.getByText('Revoke link')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Revoke link'))
    await waitFor(() => expect(api.revokeShareLink).toHaveBeenCalledWith('c-1'))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Share report' })).toBeInTheDocument())
    expect(screen.queryByText('Revoke link')).not.toBeInTheDocument()
  })

  it('a share after a revoke copies a genuinely new URL, not the stale revoked one', async () => {
    api.getShareLink.mockResolvedValue({ token: 'old-tok', created_at: '2026-08-18', expires_at: null })
    api.revokeShareLink.mockResolvedValue({ revoked: true })
    api.createShareLink.mockResolvedValue({ token: 'fresh-tok', created_at: '2026-08-18', expires_at: null })
    const writeText = vi.fn().mockResolvedValue(undefined)
    mockClipboard(writeText)

    render(<FullAnalysisShareControl cycleCode="c-1" />)
    await waitFor(() => expect(screen.getByText('Revoke link')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Revoke link'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Share report' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Share report' }))
    await waitFor(() => expect(api.createShareLink).toHaveBeenCalledWith('c-1'))
    await flushMicrotasks()

    expect(writeText).toHaveBeenCalledWith(`${PUBLIC_APP_BASE_URL}/fa/fresh-tok`)
    expect(writeText).not.toHaveBeenCalledWith(expect.stringContaining('old-tok'))
  })
})
