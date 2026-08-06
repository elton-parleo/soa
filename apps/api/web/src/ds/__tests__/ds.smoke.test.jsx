/**
 * D2: smoke coverage for every ported component — renders without
 * throwing, across its documented variants where applicable. Glyph
 * covers all 19 names in use; StateChip covers all four states.
 */
import React from 'react'
import { render } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import {
  Button, BrandLogo, Glyph, SoAIndex, MonoTag, ProvenanceLine, SectionHeading,
  LeakageEstimator, MetricRow, StateChip, StatusChip, OfferFeed, Wordmark,
  BrowserChrome, Container, DarkPanel, LogoMarquee,
} from '../index.js'

const GLYPH_NAMES_IN_USE = [
  'agent', 'arrowRight', 'arrowUpRight', 'card', 'chart', 'check', 'chevronDown',
  'clock', 'doc', 'eye', 'filter', 'globe', 'layers', 'refresh', 'search',
  'spark', 'tag', 'viewport', 'x',
]

describe('Button', () => {
  it.each(['ink', 'blue', 'outline', 'ghost', 'light'])('renders variant=%s', (variant) => {
    const { container } = render(<Button variant={variant}>Go</Button>)
    expect(container.querySelector('button')).toBeInTheDocument()
  })
  it.each(['sm', 'md', 'lg'])('renders size=%s with arrow', (size) => {
    const { container } = render(<Button size={size} arrow>Go</Button>)
    expect(container.querySelector('.btn-arrow')).toBeInTheDocument()
  })
  it('renders disabled', () => {
    const { container } = render(<Button disabled>Go</Button>)
    expect(container.querySelector('button')).toBeDisabled()
  })
})

describe('Glyph', () => {
  it('exposes all 19 names in use', () => {
    GLYPH_NAMES_IN_USE.forEach((name) => expect(Glyph.names).toContain(name))
  })
  it.each(GLYPH_NAMES_IN_USE)('renders name=%s without throwing', (name) => {
    const { container } = render(<Glyph name={name} />)
    expect(container.querySelector('svg')).toBeInTheDocument()
  })
  it('renders with notch=false', () => {
    const { container } = render(<Glyph name="eye" notch={false} />)
    expect(container.querySelector('mask')).not.toBeInTheDocument()
  })
})

describe('StateChip', () => {
  it.each(['seen', 'partial', 'invisible', 'unmeasured'])('renders chip variant, state=%s', (state) => {
    const { getByText } = render(<StateChip state={state} variant="chip" size="sm">label</StateChip>)
    expect(getByText('label')).toBeInTheDocument()
  })
  it.each(['seen', 'partial', 'invisible', 'unmeasured'])('renders value variant, state=%s', (state) => {
    const { getByText } = render(<StateChip state={state} variant="value">42</StateChip>)
    expect(getByText('42')).toBeInTheDocument()
  })
  it.each(['seen', 'partial', 'invisible', 'unmeasured'])('renders dot variant, state=%s', (state) => {
    const { container } = render(<StateChip state={state} variant="dot" />)
    expect(container.querySelector('span')).toBeInTheDocument()
  })
  it('unmeasured is visually distinct from invisible (chip bg)', () => {
    const inv = render(<StateChip state="invisible" variant="chip">x</StateChip>).container.querySelector('span')
    const unm = render(<StateChip state="unmeasured" variant="chip">x</StateChip>).container.querySelector('span')
    expect(inv.style.background).not.toBe(unm.style.background)
  })
})

describe('MonoTag', () => {
  it.each(['pill', 'plain', 'blue', 'dark'])('renders tone=%s', (tone) => {
    const { getByText } = render(<MonoTag tone={tone}>LABEL</MonoTag>)
    expect(getByText('LABEL')).toBeInTheDocument()
  })
})

describe('StatusChip', () => {
  it.each(['live', 'success', 'warning', 'risk', 'info', 'neutral'])('renders tone=%s', (tone) => {
    const { getByText } = render(<StatusChip tone={tone}>Status</StatusChip>)
    expect(getByText('Status')).toBeInTheDocument()
  })
})

describe('SectionHeading', () => {
  it('renders with accent + body', () => {
    const { getByText } = render(<SectionHeading accent="accent phrase" body="body copy">Lead phrase</SectionHeading>)
    expect(getByText('Lead phrase', { exact: false })).toBeInTheDocument()
    expect(getByText('body copy')).toBeInTheDocument()
  })
  it('renders size=sm dark', () => {
    const { container } = render(<SectionHeading size="sm" dark>Lead</SectionHeading>)
    expect(container.querySelector('h2.section-heading.sm.on-dark')).toBeInTheDocument()
  })
})

describe('BrandLogo', () => {
  it('renders an img for a known name', () => {
    const { container } = render(<BrandLogo name="ChatGPT" />)
    expect(container.querySelector('img')).toBeInTheDocument()
  })
  it('renders a fallback label for an unknown name', () => {
    const { getByText } = render(<BrandLogo name="Not A Real Brand" label />)
    expect(getByText('Not A Real Brand')).toBeInTheDocument()
  })
})

describe('Wordmark', () => {
  it('renders the lockup', () => {
    const { getByText } = render(<Wordmark />)
    expect(getByText('PARLEO')).toBeInTheDocument()
  })
  it('renders glyphOnly', () => {
    const { queryByText, container } = render(<Wordmark glyphOnly />)
    expect(queryByText('PARLEO')).not.toBeInTheDocument()
    expect(container.querySelector('svg')).toBeInTheDocument()
  })
})

describe('ProvenanceLine', () => {
  it('renders parts + confidence', () => {
    const { getByText } = render(<ProvenanceLine parts={['a', 'b']} confidence="modeled" />)
    expect(getByText('a, b')).toBeInTheDocument()
    expect(getByText('modeled')).toBeInTheDocument()
  })
})

describe('Container / DarkPanel / LogoMarquee / BrowserChrome', () => {
  it('Container renders children + label', () => {
    const { getByText } = render(<Container label="LABEL">child</Container>)
    expect(getByText('child')).toBeInTheDocument()
    expect(getByText('LABEL')).toBeInTheDocument()
  })
  it('DarkPanel renders without image', () => {
    const { getByText } = render(<DarkPanel>content</DarkPanel>)
    expect(getByText('content')).toBeInTheDocument()
  })
  it('DarkPanel renders with image', () => {
    const { container } = render(<DarkPanel image="https://example.com/x.jpg">content</DarkPanel>)
    expect(container.querySelector('img')).toHaveAttribute('src', 'https://example.com/x.jpg')
  })
  it('LogoMarquee renders duplicated chip rail', () => {
    const { container } = render(<LogoMarquee items={['ChatGPT', 'Gemini']} />)
    expect(container.querySelectorAll('.animate-marquee > *').length).toBe(4)
  })
  it('BrowserChrome renders browser variant with url', () => {
    const { getByText } = render(<BrowserChrome url="audit.parleo.io">body</BrowserChrome>)
    expect(getByText('audit.parleo.io')).toBeInTheDocument()
  })
  it('BrowserChrome renders app variant with title', () => {
    const { getByText } = render(<BrowserChrome variant="app" title="My App">body</BrowserChrome>)
    expect(getByText('My App')).toBeInTheDocument()
  })
})

describe('MetricRow / LeakageEstimator / OfferFeed / SoAIndex', () => {
  it('MetricRow renders each item', () => {
    const { getByText } = render(<MetricRow items={[{ value: 25, suffix: '/40', label: 'Visibility' }]} />)
    expect(getByText('Visibility')).toBeInTheDocument()
  })
  it('LeakageEstimator renders total + causes', () => {
    const { getByText } = render(
      <LeakageEstimator total="775" prefix="$" suffix="K" causes={[{ label: 'Cause A', value: 345, display: '$345K' }]} />,
    )
    expect(getByText('Cause A')).toBeInTheDocument()
  })
  it.each(['seen', 'partial', 'invisible', 'unmeasured'])('OfferFeed renders readable=%s', (readable) => {
    const { getByText } = render(<OfferFeed offers={[{ name: 'List price', value: '$1', channel: 'schema.org', readable }]} />)
    expect(getByText('List price')).toBeInTheDocument()
  })
  it('SoAIndex renders rows + projected label', () => {
    const { getByText } = render(<SoAIndex rows={[{ name: 'Allbirds', share: 35, projected: 52 }]} you="Allbirds" projected="Projected with True Value shipped" />)
    expect(getByText('Allbirds')).toBeInTheDocument()
    expect(getByText('Projected with True Value shipped')).toBeInTheDocument()
  })
  it('SoAIndex omits the projected label when not provided', () => {
    const { queryByText } = render(<SoAIndex rows={[{ name: 'Allbirds', share: 35 }]} you="Allbirds" />)
    expect(queryByText(/Projected/)).not.toBeInTheDocument()
  })
})
