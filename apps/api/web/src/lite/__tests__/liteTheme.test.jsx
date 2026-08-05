import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import { FullDiagnosticGate, FullAnalysisPill, FULL_DIAGNOSTIC_CTA_LABEL, LogoHeader, ReportHeaderBar } from '../liteTheme.jsx'

describe('FullDiagnosticGate (Part 1, M1; variants restyled Report redesign Part 6, G1)', () => {
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

  it('renders the FULL ANALYSIS pill (default inline variant)', () => {
    render(<FullDiagnosticGate message="See more" ctaUrl="https://x.example.com" />)
    expect(screen.getByText('FULL ANALYSIS')).toBeInTheDocument()
  })

  it('never renders email-gate language — paid-tier vocabulary only', () => {
    const { container } = render(
      <FullDiagnosticGate
        message="Two fixes get you started. The full ranked list comes with a custom Full Diagnostic."
        subMessage="4 MORE FIXES IDENTIFIED"
        ctaUrl="https://x.example.com"
      />,
    )
    expect(container.textContent.toLowerCase()).not.toMatch(/email|unlock with your|sign up/)
  })

  it('inline variant renders message/CTA in a single slim bar, ignoring any children prop (blur is the caller\'s job now)', () => {
    render(
      <FullDiagnosticGate variant="inline" message="See more" ctaUrl="https://x.example.com">
        <div data-testid="should-not-render">nope</div>
      </FullDiagnosticGate>,
    )
    expect(screen.queryByTestId('should-not-render')).not.toBeInTheDocument()
  })

  it('block variant renders a heading and its children as real, unblurred content, followed by the CTA', () => {
    render(
      <FullDiagnosticGate variant="block" heading="A bigger picture" ctaUrl="https://x.example.com">
        <div data-testid="block-content">real content, not decorative</div>
      </FullDiagnosticGate>,
    )
    expect(screen.getByText('A bigger picture')).toBeInTheDocument()
    const content = screen.getByTestId('block-content')
    expect(content.closest('[aria-hidden="true"]')).toBeNull()
    expect(screen.getByText(FULL_DIAGNOSTIC_CTA_LABEL).closest('a')).toHaveAttribute('href', 'https://x.example.com')
  })
})

describe('FullAnalysisPill (Report redesign, Part 6, G1)', () => {
  it('renders identical computed style regardless of its mounting ancestor — no ancestor rule can restyle it', () => {
    const { container: c1 } = render(<div style={{ color: 'red', fontFamily: 'serif' }}><FullAnalysisPill /></div>)
    const { container: c2 } = render(<div className="lite-card-dark"><FullAnalysisPill /></div>)
    const { container: c3 } = render(
      <div style={{ background: 'var(--accent)', color: '#fff' }} className="lite-v4-tv"><FullAnalysisPill /></div>,
    )
    const pills = [c1, c2, c3].map((c) => c.querySelector('span'))
    const styles = pills.map((p) => getComputedStyle(p))
    const props = ['color', 'fontSize', 'fontWeight', 'letterSpacing', 'borderRadius', 'padding']
    for (const prop of props) {
      expect(styles[1][prop]).toBe(styles[0][prop])
      expect(styles[2][prop]).toBe(styles[0][prop])
    }
  })
})

describe('R1: scan→audit rendered-copy rename', () => {
  it('LogoHeader reads "Parleo Audit", not "Parleo Scan"', () => {
    render(<LogoHeader />)
    expect(screen.getByText('Parleo Audit')).toBeInTheDocument()
    expect(screen.queryByText('Parleo Scan')).not.toBeInTheDocument()
  })

  it('ReportHeaderBar status copy says Audit, not Scan', () => {
    render(<ReportHeaderBar brandOrDomain="Acme Co" scanStatus="complete" />)
    expect(screen.getByText('Audit complete')).toBeInTheDocument()

    const { unmount } = render(<ReportHeaderBar brandOrDomain="Acme Co" scanStatus="failed" />)
    expect(screen.getByText('Audit failed')).toBeInTheDocument()
    unmount()
  })
})
