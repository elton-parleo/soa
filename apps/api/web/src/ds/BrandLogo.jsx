/**
 * Real logos as proof, never text labels. Ported from the exported
 * design-system bundle (components/foundation/BrandLogo.jsx) — same
 * render tree, restored to JSX.
 *
 * Logo feature, Part 3a: a wrong logo is worse than no logo, so every
 * tier fails toward the monogram, never toward a guess. Render chain,
 * each tier advancing on absence (no src/no resolvable domain) or an
 * image onError: (1) `src` — a crawled icon, used for the target only;
 * (2) the logoProvider (domain-keyed third-party API, skipped when
 * unconfigured or no domain); (3) the Google favicon endpoint, a silent
 * low-res fallback; (4) the monogram — the only tier that can never fail.
 */
import { useEffect, useState } from 'react'
import { logoProviderUrl } from './logoProvider.js'

const domainMap = {
  Anthropic: 'anthropic.com',
  MCP: 'anthropic.com',
  Claude: 'anthropic.com',
  Stripe: 'stripe.com',
  ACP: 'stripe.com',
  OpenAI: 'openai.com',
  OpenAPI: 'openai.com',
  ChatGPT: 'openai.com',
  Google: 'google.com',
  UCP: 'google.com',
  AP2: 'google.com',
  Gemini: 'google.com',
  Perplexity: 'perplexity.ai',
  Copilot: 'microsoft.com',
  Microsoft: 'microsoft.com',
  Visa: 'visa.com',
  'Visa TAP': 'visa.com',
  Mastercard: 'mastercard.com',
  Amex: 'americanexpress.com',
  Chase: 'chase.com',
  Shopify: 'shopify.com',
  Oracle: 'oracle.com',
  Salesforce: 'salesforce.com',
  Klarna: 'klarna.com',
  Sephora: 'sephora.com',
  Ulta: 'ulta.com',
  Target: 'target.com',
  Nordstrom: 'nordstrom.com',
  Nike: 'nike.com',
  REI: 'rei.com',
  Backcountry: 'backcountry.com',
  'Best Buy': 'bestbuy.com',
  Amazon: 'amazon.com',
  Sony: 'sony.com',
  "Kohl's": 'kohls.com',
  'Home Depot': 'homedepot.com',
  "Macy's": 'macys.com',
  Lululemon: 'lululemon.com',
  Apple: 'apple.com',
  Dyson: 'dyson.com',
  Patagonia: 'patagonia.com',
  Adidas: 'adidas.com',
  "Bloomingdale's": 'bloomingdales.com',
  Saks: 'saksfifthavenue.com',
  'Neiman Marcus': 'neimanmarcus.com',
  'SK-II': 'sk-ii.com',
  Costco: 'costco.com',
  Walmart: 'walmart.com',
  Rakuten: 'rakuten.com',
  Groupon: 'groupon.com',
}

function monogramInitial(name) {
  const trimmed = (name || '').trim()
  return trimmed ? trimmed[0].toUpperCase() : '?'
}

export function BrandLogo({ name, src, domain, size = 16, grayscale = false, label = false, labelSize, style }) {
  const resolvedDomain = domain || domainMap[name]

  const tiers = []
  if (src) tiers.push(src)
  if (resolvedDomain) {
    const providerUrl = logoProviderUrl(resolvedDomain, size)
    if (providerUrl) tiers.push(providerUrl)
    tiers.push(`https://www.google.com/s2/favicons?domain=${resolvedDomain}&sz=64`)
  }

  const [tierIndex, setTierIndex] = useState(0)
  // A new identity (different row reusing this component instance) must
  // restart at tier 0 — otherwise a prior row's failed tier count would
  // wrongly carry over and skip tiers this identity hasn't tried yet.
  useEffect(() => { setTierIndex(0) }, [src, resolvedDomain])

  const currentSrc = tiers[tierIndex]

  const mark = currentSrc ? (
    <img
      src={currentSrc}
      alt={`${name} logo`}
      width={size}
      height={size}
      loading="lazy"
      referrerPolicy="no-referrer"
      style={{
        flexShrink: 0,
        display: 'block',
        width: size,
        height: size,
        objectFit: 'contain',
        borderRadius: Math.max(2, size * 0.14),
        opacity: grayscale ? 0.7 : 1,
        filter: grayscale ? 'grayscale(30%)' : undefined,
        ...(label ? {} : style),
      }}
      onError={() => setTierIndex((i) => i + 1)}
    />
  ) : (
    <span
      role="img"
      aria-label={`${name} logo`}
      style={{
        flexShrink: 0,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: size,
        height: size,
        boxSizing: 'border-box',
        borderRadius: Math.max(2, size * 0.14),
        background: 'var(--canvas-dim)',
        color: 'var(--muted)',
        fontSize: size * 0.5,
        fontWeight: 640,
        ...(label ? {} : style),
      }}
    >
      {monogramInitial(name)}
    </span>
  )

  if (!label) return mark
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: size * 0.45, ...style }}>
      {mark}
      <span style={{ fontSize: labelSize || 13, fontWeight: 520, color: 'inherit', letterSpacing: '-0.005em' }}>{name}</span>
    </span>
  )
}

BrandLogo.domains = domainMap
