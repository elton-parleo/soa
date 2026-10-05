import fixture from '../../../pipeline/tests/fixtures/wiggle_and_snug_catalog.json'
import channels from '../src/components/merchant-command-center/__fixtures__/channels.json'
import publications from '../src/components/merchant-command-center/__fixtures__/publications.json'
import spine from '../src/components/merchant-command-center/__fixtures__/merchant-schema-org.json'
import listings from '../src/components/merchant-command-center/__fixtures__/listings.json'
import preview from '../src/components/customer-setup/__fixtures__/feed-preview-acme-pets.json'

export const NOT_AUTHORIZED = 'Not authorized for this customer'
export const withMutationTimeout = (p) => p
export async function fetchAllVerifications() { return {} }

// Acme's feed-served catalog: the fixture preview's committable rows,
// grouped as supply's catalog route groups them (brand + product name).
function acmeCatalog() {
  const groups = new Map()
  for (const row of preview.rows.filter((r) => r.status !== 'error')) {
    const key = `${row.brand_name}|${row.product_name}`
    if (!groups.has(key)) groups.set(key, { listing_id: 500 + groups.size, title: row.product_name,
      brand: row.brand_name, product_url: row.retailers[0]?.url, published_at: '2026-10-04T12:00:00Z',
      spec_version: 'sku-feed', variants: [] })
    groups.get(key).variants.push({ variant_id: row.gtin, gtin: row.gtin, list_price: row.price, currency: row.currency })
  }
  return { merchant: 'acme-pets', listings: [...groups.values()] }
}

export const truesyncApi = {
  getMerchants: async () => fixture.merchants,
  getMerchantCatalog: async (slug) => (slug === 'acme-pets' ? acmeCatalog() : fixture.catalog),
  getMerchantIncentives: async () => fixture.incentives,
  getChannels: async () => channels,
  getPublications: async () => publications,
  getMerchantSchemaOrg: async () => spine,
  getListing: async (id) => listings[String(id)],
  getProspects: async () => ({ prospects: [{ slug: 'pampers', prospect: 'Pampers',
    products_observed: 3, products_configured: 3, observations_total: 9, placeholders: 0,
    last_observed_at: '2026-10-03T09:00:00Z' }] }),
  getProspectDrift: async () => ({ products: [] }),
  validateFeed: async () => preview,
  commitFeed: async () => ({ version_number: 1 }),
  putOwnedIncentives: async () => ({ incentives: [] }),
  getOwnedIncentives: async () => ({ incentives: [] }),
  getProvenance: async () => ({ merchant_source: 'scrape', deals: { scrape: 14, published: 2 },
    listings: { scrape: 3, published: 9 }, journal: [{ action: 'claim', at: '2026-10-05T09:00:00Z' }] }),
  downloadTemplate: async () => new Blob(['gtin,product_name\n']),
}
