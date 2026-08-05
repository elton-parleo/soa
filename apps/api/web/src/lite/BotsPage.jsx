/**
 * /bots — public documentation page for ParleoAuditBot (W4), mirroring
 * the identity constants apps/pipeline/scan/identity.py defines as the
 * single Python-side source. This file can't import Python, so the
 * literal values below (BOT_UA, KEY_DIRECTORY_URL, the fetch-budget
 * number) are copied by hand from that module — kept in sync manually,
 * same as any other cross-language constant in this repo. If either
 * changes, update both.
 *
 * Presentational only, unauthenticated, at /bots — same pre-auth
 * standalone treatment as /lite (see App.jsx). Lives on the marketing
 * host only, not on audit.parleo.io (H1).
 */
import './theme.css'
import { LightCard, SectionHeader } from './liteTheme.jsx'
import { LandingFooter } from './landing/LandingFooter.jsx'

// Copied from apps/pipeline/scan/identity.py — see module docstring above.
const BOT_NAME = 'ParleoAuditBot'
const BOT_UA = 'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ParleoAuditBot/1.0; +https://www.parleo.io/bots'
const KEY_DIRECTORY_URL = 'https://bots.parleo.io/.well-known/http-message-signatures-directory'
// Copied from apps/pipeline/scan/fetcher.py::MAX_PAGE_FETCHES.
const MAX_PAGES_PER_AUDIT = 12
const LAST_UPDATED = 'August 2026'

function BotsNav() {
  return (
    <nav className="lite-landing-nav" aria-label="Parleo">
      <div className="lite-landing-nav-left">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="2" y="2" width="8" height="20" rx="1.5" style={{ fill: 'var(--accent)' }} />
          <rect x="14" y="6" width="8" height="12" rx="1.5" style={{ fill: 'var(--accent)' }} opacity="0.4" />
        </svg>
        <span className="lite-divider-v" style={{ height: 16 }} aria-hidden="true" />
        <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--text)' }}>Parleo Bots</span>
      </div>
      <div className="lite-landing-nav-right">
        <a href="/" className="lite-pill" style={{ cursor: 'pointer', textDecoration: 'none' }}>
          <span className="lite-badge-dot" aria-hidden="true" />
          parleo.io
        </a>
      </div>
    </nav>
  )
}

function CodeBlock({ children }) {
  return (
    <pre
      className="lite-mono"
      style={{
        background: 'var(--ink)', color: '#fff', padding: '14px 16px', borderRadius: 10,
        fontSize: 12.5, lineHeight: 1.6, overflowX: 'auto', whiteSpace: 'pre',
      }}
    >
      {children}
    </pre>
  )
}

function IdentitySection() {
  return (
    <LightCard>
      <SectionHeader label="IDENTITY" headline={BOT_NAME} />
      <div className="lite-body" style={{ lineHeight: 1.7 }}>
        <p>
          <strong>Operator:</strong> Parleo (parleo.io)
          <br />
          <strong>Purpose:</strong> agentic-commerce audits — reading public product pages the
          way AI shopping agents do, to measure and improve agent readiness.
          <br />
          <strong>Last updated:</strong> {LAST_UPDATED}
        </p>
        <p style={{ marginTop: 14 }}>
          <strong>User-Agent string</strong> (sent on every request, unchanged):
        </p>
        <CodeBlock>{BOT_UA}</CodeBlock>
      </div>
    </LightCard>
  )
}

function VerificationSection() {
  return (
    <LightCard>
      <SectionHeader label="VERIFICATION" headline="How to confirm a request is really us" />
      <div className="lite-body" style={{ lineHeight: 1.7 }}>
        <p>
          Every request from {BOT_NAME} is cryptographically signed per{' '}
          <strong>RFC 9421 (HTTP Message Signatures)</strong>, using the emerging{' '}
          <strong>Web Bot Auth</strong> profile — an Ed25519 signature over the request,
          carried in the <code>Signature</code>/<code>Signature-Input</code> headers, plus a{' '}
          <code>Signature-Agent</code> header pointing at our published key directory:
        </p>
        <CodeBlock>{KEY_DIRECTORY_URL}</CodeBlock>
        <p style={{ marginTop: 10 }}>
          We prefer Web Bot Auth verification over IP allowlists — our crawl egress can change,
          and a signature proves identity independent of which address a request came from.
          A request claiming to be {BOT_NAME} that isn't signed, or doesn't verify against the
          key directory above, should not be trusted as us.
        </p>
      </div>
    </LightCard>
  )
}

const PURPOSE_SCOPE = [
  'Public product pages and their metadata',
  'Schema.org structured data (Product, Offer, and related types)',
  'Sitemap and robots.txt signals',
  'Public agent-protocol surfaces — llms.txt, MCP well-known manifests, UCP discovery',
]

const BOUNDARIES = [
  'Never reads authenticated, paywalled, or otherwise private content',
  'Never collects personal shopper data',
  `A bounded per-site fetch budget — about a dozen pages per audit (currently ${MAX_PAGES_PER_AUDIT})`,
  'Honors robots.txt, including Crawl-delay',
  'Not a search-engine indexer — nothing we read is published or resold as a search index',
]

function PurposeSection() {
  return (
    <LightCard>
      <SectionHeader label="PURPOSE" headline="What we read" />
      <ul className="lite-body" style={{ lineHeight: 1.9, paddingLeft: 20, margin: 0 }}>
        {PURPOSE_SCOPE.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </LightCard>
  )
}

function BoundariesSection() {
  return (
    <LightCard>
      <SectionHeader label="BOUNDARIES" headline="What we don't do" />
      <ul className="lite-body" style={{ lineHeight: 1.9, paddingLeft: 20, margin: 0 }}>
        {BOUNDARIES.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </LightCard>
  )
}

function RobotsSection() {
  return (
    <LightCard>
      <SectionHeader label="ROBOTS.TXT" headline="Controlling access" />
      <div className="lite-body" style={{ lineHeight: 1.7 }}>
        <p>Allow every path (the default — no rule needed, but shown explicitly here):</p>
        <CodeBlock>{`User-agent: ${BOT_NAME}\nAllow: /`}</CodeBlock>
        <p style={{ marginTop: 14 }}>Block specific paths, e.g. account and checkout flows:</p>
        <CodeBlock>{`User-agent: ${BOT_NAME}\nDisallow: /account/\nDisallow: /checkout/`}</CodeBlock>
        <p style={{ marginTop: 14 }}>Block us entirely:</p>
        <CodeBlock>{`User-agent: ${BOT_NAME}\nDisallow: /`}</CodeBlock>
      </div>
    </LightCard>
  )
}

function ContactSection() {
  return (
    <LightCard>
      <SectionHeader label="CONTACT" headline="Questions about this bot" />
      <div className="lite-body" style={{ lineHeight: 1.7 }}>
        <a href="mailto:crawler@parleo.io" className="lite-mono" style={{ color: 'var(--accent-ink)', fontWeight: 700 }}>
          crawler@parleo.io
        </a>
      </div>
    </LightCard>
  )
}

export default function BotsPage() {
  return (
    <div className="lite-root" style={{ display: 'block', padding: 0 }}>
      <BotsNav />
      <div style={{ maxWidth: 720, margin: '0 auto', padding: '32px 20px 60px', display: 'flex', flexDirection: 'column', gap: 16 }}>
        <IdentitySection />
        <VerificationSection />
        <PurposeSection />
        <BoundariesSection />
        <RobotsSection />
        <ContactSection />
      </div>
      <LandingFooter />
    </div>
  )
}
