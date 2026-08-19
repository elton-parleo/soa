/**
 * WordmarkLink — the shared "PARLEO lockup as a link to parleo.io"
 * wrapper used at every chrome placement (LandingNav, LandingFooter,
 * ReportRail, ReportFooter, FullAnalysisRail, FullAnalysisFooter).
 * Per-placement coverage that the wrapper is actually used lives in
 * each surface's own test file; this file covers the wrapper's own
 * contract directly.
 */
import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import { WordmarkLink } from '../WordmarkLink.jsx'
import { PARLEO_HOME_URL } from '../publicUrls.js'

describe('WordmarkLink', () => {
  it('renders an anchor to PARLEO_HOME_URL, opening in a new tab, with the home aria-label', () => {
    render(<WordmarkLink size={15} />)
    const link = screen.getByRole('link', { name: 'Parleo home' })
    expect(link).toHaveAttribute('href', PARLEO_HOME_URL)
    expect(PARLEO_HOME_URL).toBe('https://parleo.io')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('keeps the lockup rendering untouched inside the link — glyph + PARLEO text', () => {
    render(<WordmarkLink size={15} />)
    const link = screen.getByRole('link', { name: 'Parleo home' })
    expect(link.querySelector('svg')).toBeInTheDocument()
    expect(link).toHaveTextContent('PARLEO')
  })

  it('link styling is text-decoration:none, color:inherit', () => {
    render(<WordmarkLink size={15} />)
    const link = screen.getByRole('link', { name: 'Parleo home' })
    expect(link.style.textDecoration).toBe('none')
    expect(link.style.color).toBe('inherit')
  })

  it('glyphOnly still renders the anchor, sized to a 44px hit area', () => {
    render(<WordmarkLink size={16} glyphOnly />)
    const link = screen.getByRole('link', { name: 'Parleo home' })
    expect(link.querySelector('svg')).toBeInTheDocument()
    expect(link).not.toHaveTextContent('PARLEO')
    expect(link).toHaveStyle({ minWidth: '44px', minHeight: '44px' })
  })

  it('non-glyphOnly does not force the 44px hit area (it already reads wider than that)', () => {
    render(<WordmarkLink size={15} />)
    const link = screen.getByRole('link', { name: 'Parleo home' })
    expect(link.style.minWidth).toBe('')
  })
})
