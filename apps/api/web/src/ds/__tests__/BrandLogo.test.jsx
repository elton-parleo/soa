/**
 * Logo feature, Part 3a: BrandLogo's fallback chain. A wrong logo is
 * worse than no logo, so every tier must fail toward the monogram, never
 * toward a guess — these tests drive each tier's onError explicitly and
 * assert the next tier (or the monogram, at the end) takes over.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'

vi.mock('../logoProvider.js', () => ({
  logoProviderUrl: vi.fn(),
  LOGO_PROVIDER_CONFIGURED: true,
}))

import { logoProviderUrl } from '../logoProvider.js'
import { BrandLogo } from '../BrandLogo.jsx'

describe('BrandLogo fallback chain', () => {
  it('renders the src tier first when provided', () => {
    logoProviderUrl.mockReturnValue('https://img.logo.dev/acme.com?token=t&size=32')
    const { container } = render(<BrandLogo name="Acme" src="https://acme.com/icon.png" domain="acme.com" size={32} />)
    expect(container.querySelector('img').src).toBe('https://acme.com/icon.png')
  })

  it('advances from src to the provider tier on error', () => {
    logoProviderUrl.mockReturnValue('https://img.logo.dev/acme.com?token=t&size=32')
    const { container } = render(<BrandLogo name="Acme" src="https://acme.com/icon.png" domain="acme.com" size={32} />)
    fireEvent.error(container.querySelector('img'))
    expect(container.querySelector('img').src).toBe('https://img.logo.dev/acme.com?token=t&size=32')
  })

  it('skips the provider tier straight to favicon when the provider is unconfigured', () => {
    logoProviderUrl.mockReturnValue(null)
    const { container } = render(<BrandLogo name="Acme" src="https://acme.com/icon.png" domain="acme.com" size={32} />)
    fireEvent.error(container.querySelector('img'))
    expect(container.querySelector('img').src).toBe('https://www.google.com/s2/favicons?domain=acme.com&sz=64')
  })

  it('advances from favicon to the monogram on a final error', () => {
    logoProviderUrl.mockReturnValue(null)
    const { container, getByRole } = render(<BrandLogo name="Acme" domain="acme.com" size={32} />)
    fireEvent.error(container.querySelector('img'))
    expect(container.querySelector('img')).not.toBeInTheDocument()
    expect(getByRole('img', { name: 'Acme logo' })).toBeInTheDocument()
  })

  it('falls all the way to the monogram after every tier fails', () => {
    logoProviderUrl.mockReturnValue('https://img.logo.dev/acme.com?token=t&size=32')
    const { container, getByRole } = render(<BrandLogo name="Acme" src="https://acme.com/icon.png" domain="acme.com" size={32} />)
    fireEvent.error(container.querySelector('img')) // src -> provider
    fireEvent.error(container.querySelector('img')) // provider -> favicon
    fireEvent.error(container.querySelector('img')) // favicon -> monogram
    expect(container.querySelector('img')).not.toBeInTheDocument()
    expect(getByRole('img', { name: 'Acme logo' })).toBeInTheDocument()
  })

  it('goes straight to the monogram when there is no src and no resolvable domain', () => {
    logoProviderUrl.mockReturnValue(null)
    const { container, getByRole } = render(<BrandLogo name="Zzyzx Not A Real Brand" size={20} />)
    expect(container.querySelector('img')).not.toBeInTheDocument()
    expect(getByRole('img', { name: 'Zzyzx Not A Real Brand logo' })).toBeInTheDocument()
  })

  it('gives the monogram an accessible label and initial built from the brand name', () => {
    logoProviderUrl.mockReturnValue(null)
    const { getByRole } = render(<BrandLogo name="Vuori" size={20} />)
    const mark = getByRole('img', { name: 'Vuori logo' })
    expect(mark.textContent).toBe('V')
  })

  it('every img tier is lazy, no-referrer, and object-fit contain', () => {
    logoProviderUrl.mockReturnValue(null)
    const { container } = render(<BrandLogo name="Acme" src="https://acme.com/icon.png" size={32} />)
    const img = container.querySelector('img')
    expect(img.getAttribute('loading')).toBe('lazy')
    expect(img.getAttribute('referrerpolicy')).toBe('no-referrer')
    expect(img.style.objectFit).toBe('contain')
  })

  it('resolves a domain from the built-in ecosystem map when no explicit domain is given', () => {
    logoProviderUrl.mockReturnValue(null)
    const { container } = render(<BrandLogo name="ChatGPT" size={16} />)
    expect(container.querySelector('img').src).toBe('https://www.google.com/s2/favicons?domain=openai.com&sz=64')
  })
})
