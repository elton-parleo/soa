/**
 * Logo feature, Part 3c: logo.dev's free tier requires attribution — the
 * "Logos by Logo.dev" line renders iff the provider tier is actually
 * configured (a token present), since an unconfigured build never calls
 * logo.dev at all and has nothing to attribute.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render } from '@testing-library/react'
import '@testing-library/jest-dom'

async function freshImportFooter() {
  vi.resetModules()
  const { ReportFooter } = await import('../ReportFooter.jsx')
  return ReportFooter
}

describe('ReportFooter logo.dev attribution', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('renders the attribution line linking to logo.dev when the provider is configured', async () => {
    vi.stubEnv('VITE_LOGO_DEV_TOKEN', 'pk_test_123')
    const ReportFooter = await freshImportFooter()
    const { getByText } = render(<ReportFooter auditUrl="https://audit.parleo.io" />)
    const link = getByText('Logo.dev')
    expect(link.closest('a')).toHaveAttribute('href', 'https://logo.dev')
  })

  it('omits the attribution line entirely when the provider is unconfigured', async () => {
    vi.stubEnv('VITE_LOGO_DEV_TOKEN', '')
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const ReportFooter = await freshImportFooter()
    const { queryByText } = render(<ReportFooter auditUrl="https://audit.parleo.io" />)
    expect(queryByText('Logo.dev')).not.toBeInTheDocument()
  })
})
