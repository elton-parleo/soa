/**
 * Real logos as proof, never text labels. Favicon service, small +
 * aligned. Ported from the exported design-system bundle
 * (components/foundation/BrandLogo.jsx) — same render tree, restored to JSX.
 */
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

export function BrandLogo({ name, domain, size = 16, grayscale = false, label = false, labelSize, style }) {
  const d = domain || domainMap[name]
  if (!d) {
    return label ? (
      <span style={{ fontSize: labelSize || 13, fontWeight: 520, color: 'var(--text-strong)', ...style }}>{name}</span>
    ) : null
  }
  const img = (
    <img
      src={`https://www.google.com/s2/favicons?domain=${d}&sz=${size > 20 ? 64 : 32}`}
      alt={`${name} logo`}
      width={size}
      height={size}
      style={{
        flexShrink: 0,
        borderRadius: Math.max(2, size * 0.14),
        opacity: grayscale ? 0.7 : 1,
        filter: grayscale ? 'grayscale(30%)' : undefined,
        ...(label ? {} : style),
      }}
      loading="lazy"
      onError={(e) => { e.target.style.display = 'none' }}
    />
  )
  if (!label) return img
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: size * 0.45, ...style }}>
      {img}
      <span style={{ fontSize: labelSize || 13, fontWeight: 520, color: 'inherit', letterSpacing: '-0.005em' }}>{name}</span>
    </span>
  )
}

BrandLogo.domains = domainMap
