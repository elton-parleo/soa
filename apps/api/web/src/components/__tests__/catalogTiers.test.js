/**
 * The mirror check.
 *
 * catalogTiers.js is a deliberate reimplementation of
 * apps/pipeline/generation/catalog_tiers.py, because the modal has to
 * show the user what the generator will produce, before it produces it,
 * from data the browser already holds.
 *
 * What keeps the two honest is this file and its Python twin
 * (apps/pipeline/tests/test_catalog_tiers.py) asserting the SAME literal
 * question strings against the SAME fixture — which is imported from the
 * pipeline's test directory rather than copied here, so there is one
 * fixture and not two that can disagree.
 *
 * If you change a template on one side and not the other, one of these
 * two suites goes red. If you change both, it was deliberate.
 */
import { describe, it, expect } from 'vitest'

import fixture from '../../../../../pipeline/tests/fixtures/wiggle_and_snug_catalog.json'
import {
  DEFAULT_VARIANT_CAP,
  brandDirectExample,
  buildCatalogAccuracy,
  buildSnapshot,
  buildValueIncentives,
  catalogCounts,
  catalogReadback,
  normalizeMoney,
  sampleVariants,
  subjectOf,
  tally,
  tallyText,
  tierPreview,
  variantDisplay,
} from '../catalogTiers.js'

function snapshot(overrides = {}) {
  return buildSnapshot(overrides.catalog || fixture.catalog, {
    merchants: fixture.merchants,
    incentives: 'incentives' in overrides ? overrides.incentives : fixture.incentives,
  })
}

const texts = questions => questions.map(q => q.text)

// ── the read-back line the modal renders ─────────────────────────────────

describe('the catalog read-back', () => {
  it('counts the catalog the design mock describes, from the record', () => {
    expect(catalogCounts(snapshot())).toMatchObject({
      products: 5, variants: 19, gtins: 6, codes: 2, tiers: 2,
      programName: 'Member Rewards',
    })
  })

  it('renders as one line', () => {
    expect(catalogReadback(snapshot())).toBe(
      '5 products, 19 variants, 6 GTINs, 2 live codes, Member Rewards (2 tiers)',
    )
  })

  it('reads the brand off the published records, not the merchant row', () => {
    expect(snapshot().brand).toBe('Wiggle & Snug')
    expect(snapshot().domain).toBe('trueshopstore.com')
  })
})

// ── money stays a string ─────────────────────────────────────────────────

describe('money', () => {
  it.each([
    ['22.99', '22.99'],
    ['$22.99', '22.99'],
    ['18.9', '18.90'],
    ['1,234.50', '1234.50'],
  ])('normalises %s to %s', (raw, expected) => {
    expect(normalizeMoney(raw)).toBe(expected)
  })

  it.each([null, undefined, '', 'free', 'call for pricing'])(
    'returns null for %s rather than a number', raw => {
      expect(normalizeMoney(raw)).toBeNull()
    },
  )
})

// ── naming ───────────────────────────────────────────────────────────────

describe('variant display', () => {
  it('names what distinguishes a variant from its siblings', () => {
    const product = snapshot().products[0]
    const variant = product.variants.find(v => v.variantId === 'snug-fit-diapers-s3-small')
    expect(variantDisplay(product, variant)).toBe('Size 3 small pack (84 ct)')
  })

  it('drops the count when the question must not state its own answer', () => {
    const product = snapshot().products[0]
    const variant = product.variants.find(v => v.variantId === 'snug-fit-diapers-s3-small')
    expect(variantDisplay(product, variant, { withCount: false })).toBe('Size 3 small pack')
  })

  it('is empty for a single-variant product, which has nothing to distinguish', () => {
    const product = snapshot().products.find(p => p.title === 'Cloud Wipes 3-Pack')
    expect(variantDisplay(product, product.variants[0])).toBe('')
    expect(subjectOf('Wiggle & Snug', product, product.variants[0]))
      .toBe('Wiggle & Snug Cloud Wipes 3-Pack')
  })
})

// ── catalog accuracy: the same strings the Python asserts ────────────────

describe('catalog accuracy', () => {
  it('asks one price question per variant', () => {
    const { questions } = buildCatalogAccuracy(snapshot())
    const prices = questions.filter(q => q.text.endsWith('cost?'))
    expect(prices).toHaveLength(19)
  })

  it('uses the frozen price template', () => {
    const { questions } = buildCatalogAccuracy(snapshot())
    expect(texts(questions)).toContain(
      'What does the Wiggle & Snug Snug-Fit Diapers Size 3 small pack (84 ct) cost?',
    )
  })

  it('uses the frozen pack-count template', () => {
    const { questions } = buildCatalogAccuracy(snapshot())
    expect(texts(questions)).toContain(
      'How many come in the Wiggle & Snug Snug-Fit Diapers Size 3 small pack?',
    )
  })

  it('asks a single-variant product by name alone', () => {
    const { questions } = buildCatalogAccuracy(snapshot())
    expect(texts(questions)).toContain(
      'What does the Wiggle & Snug Cloud Wipes 3-Pack cost?',
    )
  })

  it('shows the published price to the cent, with the GTIN riding along', () => {
    const { questions } = buildCatalogAccuracy(snapshot())
    const q = questions.find(x => x.text.endsWith('Size 3 small pack (84 ct) cost?'))
    expect(q.expected).toEqual(['Expected: $22.99', 'GTIN 884400137609'])
  })

  it('never asks for a GTIN', () => {
    const { questions } = buildCatalogAccuracy(snapshot())
    expect(texts(questions).some(t => t.toUpperCase().includes('GTIN'))).toBe(false)
  })

  it('never states the pack count inside the pack-count question', () => {
    const { questions } = buildCatalogAccuracy(snapshot())
    const counts = questions.filter(q => q.text.startsWith('How many come in'))
    expect(counts.length).toBeGreaterThan(0)
    for (const q of counts) expect(q.text).not.toContain(' ct)')
  })

  it('emits 19 price plus 16 pack-count questions for this catalog', () => {
    expect(buildCatalogAccuracy(snapshot()).count).toBe(35)
  })
})

// ── the sampling rule ────────────────────────────────────────────────────

describe('sampling at 40 variants', () => {
  const forty = {
    merchant: 'wiggle-and-snug',
    listings: Array.from({ length: 4 }, (_, p) => ({
      listing_id: 500 + p,
      title: `Product ${p}`,
      brand: 'Wiggle & Snug',
      published_at: '2026-09-01T00:00:00+00:00',
      variants: Array.from({ length: 10 }, (_, v) => ({
        variant_id: `p${p}-v${v}`,
        title: `Product ${p} variant ${v}`,
        size: `Size ${v}`,
        count: 10 + v,
        attributes: {},
        list_price: `${p * 10 + v + 1}.00`,
        currency: 'USD',
        gtin: null,
      })),
    })),
  }

  it('caps at twenty variants', () => {
    const s = snapshot({ catalog: forty, incentives: null })
    expect(sampleVariants(s, DEFAULT_VARIANT_CAP)).toHaveLength(20)
  })

  it('covers every product at least once', () => {
    const s = snapshot({ catalog: forty, incentives: null })
    const products = new Set(
      sampleVariants(s).map(({ variant }) => variant.variantId.split('-')[0]),
    )
    expect([...products].sort()).toEqual(['p0', 'p1', 'p2', 'p3'])
  })

  it('spreads across price points rather than taking the cheapest', () => {
    const s = snapshot({ catalog: forty, incentives: null })
    const picked = new Set(sampleVariants(s).map(({ variant }) => variant.variantId))
    for (let p = 0; p < 4; p += 1) {
      expect(picked.has(`p${p}-v0`)).toBe(true)   // cheapest of this product
      expect(picked.has(`p${p}-v9`)).toBe(true)   // dearest of this product
    }
  })
})

// ── value & incentives ───────────────────────────────────────────────────

describe('value and incentives', () => {
  it('asks one question per mechanic the record has', () => {
    expect(buildValueIncentives(snapshot()).mechanics).toEqual({
      code: 2, member_price: 3, points: 1,
    })
  })

  it('gives the two codes two questions a shopper would type differently', () => {
    const { questions } = buildValueIncentives(snapshot())
    const codes = questions.filter(q => q.text.includes('promo code'))
    expect(new Set(texts(codes))).toEqual(new Set([
      'Is there a first-order promo code for Wiggle & Snug, and what does it take off?',
      'Are there any promo codes for Wiggle & Snug Snug-Fit Diapers right now, and what do they take off?',
    ]))
  })

  it('shows what a code is worth, not only that it exists', () => {
    const { questions } = buildValueIncentives(snapshot())
    const snug3 = questions.find(q => q.expected[0].includes('SNUG3'))
    expect(snug3.expected).toEqual(['Expected: SNUG3, $3.00 off'])
  })

  it('uses the frozen member-price template and names the tier', () => {
    const { questions } = buildValueIncentives(snapshot())
    expect(texts(questions)).toContain(
      'What do Member+ members pay for the Wiggle & Snug Cloud Wipes 3-Pack?',
    )
  })

  it('asks about points once, not once per variant', () => {
    const { questions } = buildValueIncentives(snapshot())
    const points = questions.filter(q => q.text.includes('points'))
    expect(texts(points)).toEqual([
      'How many Member Rewards points do you earn per dollar on Wiggle & Snug products?',
    ])
  })

  it('builds nothing at all when the incentives read failed', () => {
    expect(buildValueIncentives(snapshot({ incentives: null })).count).toBe(0)
  })
})

// ── brand-direct is illustrative, and says so ────────────────────────────

describe('brand-direct', () => {
  it('is marked illustrative, because AI writes the wording', () => {
    const example = brandDirectExample(snapshot())
    expect(example.illustrative).toBe(true)
    expect(example.expected).toEqual([
      'Expected: brand named, trueshopstore.com cited',
    ])
  })
})

// ── the tally ────────────────────────────────────────────────────────────

describe('the tally', () => {
  const enabled = {
    brand_direct: true, catalog_accuracy: true,
    value_incentives: true, category_control: false,
  }

  it('splits by who wrote the question', () => {
    const preview = tierPreview(snapshot(), { enabled, stageTotal: 50 })
    expect(tally(preview, 50)).toEqual({
      aiWritten: 62,     // 50 stage + 12 brand-direct
      fromCatalog: 41,   // 35 accuracy + 6 value
      total: 103,
    })
  })

  it('counts the control tier as a tag, adding nothing', () => {
    const preview = tierPreview(snapshot(), {
      enabled: { category_control: true }, stageTotal: 50,
    })
    expect(preview.category_control.count).toBe(50)
    expect(preview.category_control.additive).toBe(false)
    expect(tally(preview, 50)).toEqual({
      aiWritten: 50, fromCatalog: 0, total: 50,
    })
  })

  it('reads as today\'s line when no tier is on', () => {
    const preview = tierPreview(snapshot(), { enabled: {}, stageTotal: 50 })
    expect(tallyText(preview, 50, 100)).toEqual({
      tone: 'ok', text: '50 questions total — within the 100 limit',
    })
  })

  it('names both halves once the catalog contributes', () => {
    const preview = tierPreview(snapshot(), {
      enabled: { catalog_accuracy: true, value_incentives: true }, stageTotal: 50,
    })
    expect(tallyText(preview, 50, 100).text).toBe(
      '50 AI-written + 41 from the catalog = 91 questions — within the 100 limit',
    )
  })

  it('says what to do when the shared 100 cap is exceeded', () => {
    const preview = tierPreview(snapshot(), { enabled, stageTotal: 50 })
    expect(tallyText(preview, 50, 100)).toEqual({
      tone: 'off',
      text: '62 AI-written + 41 from the catalog = 103 questions — '
        + 'over the 100 limit, reduce a stage or untick a tier',
    })
  })

  it('the cap is shared: catalog questions count against the same 100', () => {
    const preview = tierPreview(snapshot(), {
      enabled: { catalog_accuracy: true }, stageTotal: 70,
    })
    expect(tally(preview, 70).total).toBe(105)
    expect(tallyText(preview, 70, 100).tone).toBe('off')
  })

  it('is empty rather than misleading when nothing is allocated', () => {
    const preview = tierPreview(snapshot(), { enabled: {}, stageTotal: 0 })
    expect(tallyText(preview, 0, 100)).toEqual({
      tone: 'off', text: 'No questions allocated yet',
    })
  })
})

// ── per-tier examples ────────────────────────────────────────────────────

describe('tier previews', () => {
  it('gives each enabled tier one true example from this brand\'s catalog', () => {
    const preview = tierPreview(snapshot(), {
      enabled: {
        brand_direct: true, catalog_accuracy: true, value_incentives: true,
      },
      stageTotal: 50,
    })
    expect(preview.catalog_accuracy.example.text).toContain('Wiggle & Snug')
    expect(preview.value_incentives.example.text).toContain('Wiggle & Snug')
    expect(preview.brand_direct.example.text).toContain('Wiggle & Snug')
  })

  it('gives a disabled tier no example and no count', () => {
    const preview = tierPreview(snapshot(), { enabled: {}, stageTotal: 50 })
    for (const tier of ['brand_direct', 'catalog_accuracy', 'value_incentives']) {
      expect(preview[tier].count).toBe(0)
      expect(preview[tier].example).toBeNull()
    }
  })
})
