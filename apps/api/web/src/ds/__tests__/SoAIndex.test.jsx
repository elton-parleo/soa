/**
 * Logo feature, Part 4: SoAIndex rows carry a BrandLogo avatar per
 * competitor, keyed off the row's own `domain` — present for a
 * generator-confident competitor (or the target's own crawled domain on
 * the primary row), null when the model wasn't confident. Null domains
 * must render a clean monogram, never a broken frame, and every avatar
 * — img or monogram — occupies the same fixed box so a row with no logo
 * doesn't shift layout relative to a row that has one (asserted at the
 * mobile card width, 360px, where the row grid is narrowest).
 */
import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import '@testing-library/jest-dom'

vi.mock('../logoProvider.js', () => ({
  logoProviderUrl: vi.fn(() => null),
  LOGO_PROVIDER_CONFIGURED: false,
}))

import { SoAIndex } from '../SoAIndex.jsx'

const ROWS = [
  { name: 'Allbirds', share: 42, domain: 'allbirds.com' },
  { name: 'Rivalco', share: 30, domain: null },
  { name: 'Thirdco', share: 28 }, // domain key absent entirely — same as null
]

describe('SoAIndex avatars', () => {
  it('renders an img avatar for a row with a resolvable domain', () => {
    const { container } = render(<SoAIndex rows={ROWS} you="Allbirds" style={{ width: 360 }} />)
    const rowSpans = container.querySelectorAll('div > span')
    const allbirdsImg = rowSpans[0].querySelector('img')
    expect(allbirdsImg).toBeInTheDocument()
    expect(allbirdsImg).toHaveAttribute('width', '15')
    expect(allbirdsImg).toHaveAttribute('height', '15')
  })

  it('renders a clean monogram, never a broken frame, for rows with a null or missing domain', () => {
    const { getByRole } = render(<SoAIndex rows={ROWS} you="Allbirds" style={{ width: 360 }} />)
    const rivalMonogram = getByRole('img', { name: 'Rivalco logo' })
    const thirdMonogram = getByRole('img', { name: 'Thirdco logo' })
    expect(rivalMonogram.tagName).toBe('SPAN')
    expect(thirdMonogram.tagName).toBe('SPAN')
  })

  it('gives every avatar — img or monogram — the same fixed 15x15 box so no row shifts layout relative to another', () => {
    const { container, getByRole } = render(<SoAIndex rows={ROWS} you="Allbirds" style={{ width: 360 }} />)
    const allbirdsImg = container.querySelectorAll('div > span')[0].querySelector('img')
    expect(allbirdsImg.getAttribute('width')).toBe('15')
    expect(allbirdsImg.getAttribute('height')).toBe('15')

    const rivalMonogram = getByRole('img', { name: 'Rivalco logo' })
    expect(rivalMonogram.style.width).toBe('15px')
    expect(rivalMonogram.style.height).toBe('15px')
  })
})
