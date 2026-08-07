import React from 'react'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import BotsPage from '../BotsPage.jsx'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const COMPONENT_SRC = fs.readFileSync(path.join(__dirname, '../BotsPage.jsx'), 'utf-8')

describe('BotsPage — W4: all required sections render', () => {
  it('renders identity: bot name, operator, purpose, last-updated stamp', () => {
    render(<BotsPage />)
    expect(screen.getByText('IDENTITY')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'ParleoAuditBot' })).toBeInTheDocument()
    expect(screen.getByText(/Operator:/)).toBeInTheDocument()
    expect(screen.getByText(/Parleo \(parleo\.io\)/)).toBeInTheDocument()
    expect(screen.getByText(/agentic-commerce audits/)).toBeInTheDocument()
    expect(screen.getByText(/reading public product pages the way AI shopping agents do/)).toBeInTheDocument()
    expect(screen.getByText(/Last updated:/)).toBeInTheDocument()
  })

  it('renders the exact User-Agent string', () => {
    render(<BotsPage />)
    expect(screen.getByText(
      'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ParleoAuditBot/1.0; +https://bots.parleo.io',
    )).toBeInTheDocument()
  })

  it('declares bots.parleo.io canonical: link tag and a visible notice linking there', () => {
    render(<BotsPage />)
    expect(document.querySelector('link[rel="canonical"]')).toHaveAttribute('href', 'https://bots.parleo.io/')
    const notice = screen.getByText(/Canonical documentation:/)
    expect(notice.querySelector('a')).toHaveAttribute('href', 'https://bots.parleo.io/')
  })

  it('renders verification: Web Bot Auth, key directory URL, IP-allowlist preference note', () => {
    render(<BotsPage />)
    expect(screen.getByText('VERIFICATION')).toBeInTheDocument()
    expect(screen.getAllByText(/Web Bot Auth/).length).toBeGreaterThan(0)
    expect(screen.getByText('https://bots.parleo.io/.well-known/http-message-signatures-directory')).toBeInTheDocument()
    expect(screen.getByText(/prefer Web Bot Auth verification over IP allowlists/)).toBeInTheDocument()
    expect(screen.getByText(/crawl egress can change/)).toBeInTheDocument()
  })

  it('renders the purpose scope list', () => {
    render(<BotsPage />)
    expect(screen.getByText('PURPOSE')).toBeInTheDocument()
    expect(screen.getByText(/Public product pages and their metadata/)).toBeInTheDocument()
    expect(screen.getByText(/Schema\.org structured data/)).toBeInTheDocument()
    expect(screen.getByText(/Sitemap and robots\.txt signals/)).toBeInTheDocument()
    expect(screen.getByText(/llms\.txt, MCP well-known manifests, UCP discovery/)).toBeInTheDocument()
  })

  it('renders the boundaries list, including the real per-site fetch budget', () => {
    render(<BotsPage />)
    expect(screen.getByText('BOUNDARIES')).toBeInTheDocument()
    expect(screen.getByText(/Never reads authenticated, paywalled, or otherwise private content/)).toBeInTheDocument()
    expect(screen.getByText(/Never collects personal shopper data/)).toBeInTheDocument()
    expect(screen.getByText(/about a dozen pages per audit \(currently 12\)/)).toBeInTheDocument()
    expect(screen.getByText(/Honors robots\.txt, including Crawl-delay/)).toBeInTheDocument()
    expect(screen.getByText(/Not a search-engine indexer/)).toBeInTheDocument()
  })

  it('renders copy-pasteable robots.txt examples: allow, block-specific-paths, block-entirely', () => {
    const { container } = render(<BotsPage />)
    expect(screen.getByText('ROBOTS.TXT')).toBeInTheDocument()
    const blocks = Array.from(container.querySelectorAll('pre')).map((el) => el.textContent)
    expect(blocks).toContain('User-agent: ParleoAuditBot\nAllow: /')
    expect(blocks).toContain('User-agent: ParleoAuditBot\nDisallow: /account/\nDisallow: /checkout/')
    expect(blocks).toContain('User-agent: ParleoAuditBot\nDisallow: /')
  })

  it('renders the contact section with crawler@parleo.io', () => {
    render(<BotsPage />)
    expect(screen.getByText('CONTACT')).toBeInTheDocument()
    const link = screen.getByText('crawler@parleo.io')
    expect(link).toBeInTheDocument()
    expect(link.closest('a')).toHaveAttribute('href', 'mailto:crawler@parleo.io')
  })

  it('renders the nav and footer', () => {
    render(<BotsPage />)
    expect(screen.getByRole('navigation', { name: 'Parleo' })).toBeInTheDocument()
    expect(screen.getByText('© 2026 Parleo, Inc.')).toBeInTheDocument()
  })
})

describe('BotsPage — grep: identity constants match apps/pipeline/scan/identity.py', () => {
  it('never references the retired bot name', () => {
    const oldName = ['Parleo', 'Scan', 'Bot'].join('')
    expect(COMPONENT_SRC).not.toContain(oldName)
  })

  it('the fetch-budget number is stated as a literal, not left as a placeholder', () => {
    expect(COMPONENT_SRC).toMatch(/MAX_PAGES_PER_AUDIT = 12/)
  })
})
