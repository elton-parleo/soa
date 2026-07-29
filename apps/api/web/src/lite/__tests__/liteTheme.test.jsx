import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import { FullDiagnosticGate, FULL_DIAGNOSTIC_CTA_LABEL } from '../liteTheme.jsx'

describe('FullDiagnosticGate (Part 1, M1)', () => {
  it('renders the default CTA label wired to ctaUrl', () => {
    render(<FullDiagnosticGate message="See more" ctaUrl="https://parleo.io/demo" />)
    const link = screen.getByText('Contact us for a free custom Full Diagnostic').closest('a')
    expect(link).toHaveAttribute('href', 'https://parleo.io/demo')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer')
    expect(FULL_DIAGNOSTIC_CTA_LABEL).toBe('Contact us for a free custom Full Diagnostic')
  })

  it('accepts a custom cta label override', () => {
    render(<FullDiagnosticGate message="See more" cta="Custom label" ctaUrl="https://parleo.io/demo" />)
    expect(screen.getByText('Custom label')).toBeInTheDocument()
    expect(screen.queryByText('Contact us for a free custom Full Diagnostic')).not.toBeInTheDocument()
  })

  it('omits the CTA link entirely when ctaUrl is not provided', () => {
    render(<FullDiagnosticGate message="See more" />)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('renders the main message and an optional mono sub-message', () => {
    render(<FullDiagnosticGate message="Main message" subMessage="4 more fixes identified" ctaUrl="https://x.example.com" />)
    expect(screen.getByText('Main message')).toBeInTheDocument()
    expect(screen.getByText('4 more fixes identified')).toBeInTheDocument()
  })

  it('renders the amber "Full analysis" tag', () => {
    render(<FullDiagnosticGate message="See more" ctaUrl="https://x.example.com" />)
    expect(screen.getByText('Full analysis')).toBeInTheDocument()
  })

  it('wraps decorative children in an aria-hidden container — never real gated data behind a blur', () => {
    const { container } = render(
      <FullDiagnosticGate message="See more" ctaUrl="https://x.example.com">
        <div data-testid="decorative-content">fixed illustrative content</div>
      </FullDiagnosticGate>,
    )
    const decorative = screen.getByTestId('decorative-content')
    expect(decorative.closest('[aria-hidden="true"]')).not.toBeNull()
    // The blurred wrapper carries pointer-events:none — genuinely inert,
    // not just visually blurred.
    expect(decorative.closest('[aria-hidden="true"]')).toHaveStyle({ pointerEvents: 'none' })
  })

  it('never renders email-gate language — paid-tier vocabulary only', () => {
    const { container } = render(
      <FullDiagnosticGate
        message="Two fixes get you started. The full ranked list comes with a custom Full Diagnostic."
        subMessage="4 more fixes identified"
        ctaUrl="https://x.example.com"
      >
        <div>decorative</div>
      </FullDiagnosticGate>,
    )
    expect(container.textContent.toLowerCase()).not.toMatch(/email|unlock with your|sign up/)
  })
})
