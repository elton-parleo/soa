/**
 * The catalog tiers, as the modal needs them: the read-back line, the
 * per-tier counts, and one true example question per tier.
 *
 * THIS IS A DELIBERATE MIRROR of apps/pipeline/generation/catalog_tiers.py.
 * Every template string, every count rule and the sampling rule are the
 * same on both sides, because the modal promises the user what the
 * generator will produce, and a promise computed by different code than
 * the thing it promises is a promise waiting to be broken.
 *
 * Why mirror rather than ask the server. The examples have to be live —
 * "true for the selected brand", before anything is generated — and the
 * catalog reads already go straight from the browser to TrueSync (see
 * truesyncApi.js on why reads do not take a proxy hop). Adding a
 * server round-trip so the server could compute what the browser already
 * has the data for would buy a shared implementation at the cost of a
 * request per keystroke on the brand select.
 *
 * What stops the two drifting is a test on each side asserting the SAME
 * literal question strings against the SAME Wiggle & Snug fixture:
 * apps/pipeline/tests/test_catalog_tiers.py and
 * src/components/__tests__/catalogTiers.test.js. Change one template
 * without the other and a test fails; change both and it was deliberate.
 */

// Counted in VARIANTS sampled, not questions emitted. See the Python
// module's comment for the reading of "cap the tier at 20 questions".
export const DEFAULT_VARIANT_CAP = 20

export const DEFAULT_BRAND_DIRECT_COUNT = 12

export const TIERS = [
  'brand_direct', 'catalog_accuracy', 'value_incentives', 'category_control',
]

// ─── Money ───────────────────────────────────────────────────────────────
//
// Strings all the way through, never floats. Published records spell
// prices as decimal strings and the scorer compares them for equality; a
// round trip through binary floating point is a silent way to make two
// identical published prices differ.

export function normalizeMoney(value) {
  if (value === null || value === undefined || typeof value === 'boolean') return null
  let text = String(value).trim()
  if (!text) return null
  for (const token of ['$', '£', '€', 'USD', 'usd', 'CAD', 'GBP', 'EUR']) {
    text = text.split(token).join('')
  }
  text = text.split(',').join('').trim()
  if (!text || !/^-?\d*\.?\d+$/.test(text)) return null
  const amount = Number(text)
  if (!Number.isFinite(amount)) return null
  return amount.toFixed(2)
}

// ─── Building a snapshot from the three payloads ─────────────────────────

export function buildSnapshot(catalog, { merchants = [], incentives = null } = {}) {
  const slug = catalog?.merchant || null

  const products = (catalog?.listings || []).map(listing => ({
    listingId: listing.listing_id,
    productId: listing.product_id,
    title: listing.title,
    brand: listing.brand,
    publishedAt: listing.published_at,
    variants: (listing.variants || [])
      .filter(v => v.variant_id)
      .map(v => ({
        variantId: v.variant_id,
        title: v.title,
        size: v.size,
        count: v.count === null || v.count === undefined ? null : Number(v.count),
        attributes: v.attributes || {},
        listPrice: v.list_price,
        currency: v.currency,
        gtin: v.gtin,
        memberPrice: null,
        memberTierName: null,
        pointsRules: [],
      })),
  }))

  const snapshot = {
    available: true,
    merchantSlug: slug,
    displayName: null,
    domain: null,
    // The brand name comes off the published records, not the merchant
    // row: it is what the payload says, which is what an assistant
    // reading the surface would have seen.
    brand: products.find(p => p.brand)?.brand || null,
    products,
    incentives: [],
    programName: null,
    tiers: [],
  }

  const merchant = (merchants || []).find(m => m.slug === slug)
  if (merchant) {
    snapshot.displayName = merchant.display_name
    snapshot.domain = merchant.domain
  }

  if (incentives) mergeIncentives(snapshot, incentives)
  return snapshot
}

function mergeIncentives(snapshot, payload) {
  snapshot.programName = payload.program_name || null
  snapshot.tiers = payload.tiers || []

  const byOfferId = new Map()
  const byVariant = new Map()

  for (const listing of payload.listings || []) {
    for (const incentive of listing.incentives || []) {
      // An offer scoped to nineteen variants is ONE offer: the same
      // WELCOME10 on every variant is one code a shopper types.
      const key = incentive.offer_id || JSON.stringify(incentive)
      if (!byOfferId.has(key)) {
        byOfferId.set(key, { ...incentive, listing_id: listing.listing_id })
      }
    }
    for (const variant of listing.variants || []) {
      if (variant.variant_id) byVariant.set(variant.variant_id, variant)
    }
  }

  snapshot.incentives = [...byOfferId.values()]

  for (const product of snapshot.products) {
    for (const variant of product.variants) {
      const merged = byVariant.get(variant.variantId)
      if (!merged) continue
      variant.memberPrice = merged.entitled_member_price || null
      variant.memberTierName = merged.entitled_tier_name || null
      variant.pointsRules = merged.points || []
    }
  }
}

// ─── Read-back ───────────────────────────────────────────────────────────

export function catalogCounts(snapshot) {
  if (!snapshot?.available) {
    return { products: 0, variants: 0, gtins: 0, codes: 0, tiers: 0 }
  }
  const variants = snapshot.products.flatMap(p => p.variants)
  return {
    products: snapshot.products.length,
    variants: variants.length,
    gtins: variants.filter(v => v.gtin).length,
    // Distinct codes, not offers carrying one.
    codes: new Set(
      snapshot.incentives.map(i => i.promo_code).filter(Boolean),
    ).size,
    tiers: (snapshot.tiers || []).length,
    programName: snapshot.programName,
  }
}

/** "5 products, 19 variants, 6 GTINs, 2 live codes, Member Rewards (2 tiers)" */
export function catalogReadback(snapshot) {
  const counts = catalogCounts(snapshot)
  const parts = [
    `${counts.products} product${counts.products === 1 ? '' : 's'}`,
    `${counts.variants} variant${counts.variants === 1 ? '' : 's'}`,
    `${counts.gtins} GTIN${counts.gtins === 1 ? '' : 's'}`,
    `${counts.codes} live code${counts.codes === 1 ? '' : 's'}`,
  ]
  if (counts.programName && counts.tiers) {
    parts.push(`${counts.programName} (${counts.tiers} tier${counts.tiers === 1 ? '' : 's'})`)
  }
  return parts.join(', ')
}

// ─── Naming — mirrors catalog_tiers.variant_display ──────────────────────

export function variantDisplay(product, variant, { withCount = true } = {}) {
  // A variant display exists to distinguish variants; with one variant
  // there is nothing to distinguish.
  if (product.variants.length <= 1) return ''

  const parts = []
  if (variant.size) parts.push(String(variant.size).trim())

  const pack = variant.attributes?.pack
  if (pack) parts.push(String(pack).trim().toLowerCase())

  if (withCount && variant.count && variant.count > 1) {
    parts.push(`(${variant.count} ct)`)
  }
  return parts.join(' ')
}

export function subjectOf(brand, product, variant, { withCount = true } = {}) {
  const words = [brand, product.title].filter(Boolean)
  const display = variantDisplay(product, variant, { withCount })
  if (display) words.push(display)
  return words.join(' ')
}

// ─── Sampling — mirrors catalog_tiers.sample_variants ────────────────────

export function priceSpreadOrder(variants) {
  const priced = []
  const unpriced = []
  for (const variant of variants) {
    const amount = normalizeMoney(variant.listPrice)
    if (amount === null) unpriced.push(variant)
    else priced.push([Number(amount), variant])
  }
  priced.sort((a, b) => a[0] - b[0])

  const ordered = []
  let low = 0
  let high = priced.length - 1
  while (low <= high) {
    ordered.push(priced[low][1])
    if (low !== high) ordered.push(priced[high][1])
    low += 1
    high -= 1
  }
  return [...ordered, ...unpriced]
}

export function sampleVariants(snapshot, cap = DEFAULT_VARIANT_CAP) {
  const queues = snapshot.products.map(p => priceSpreadOrder(p.variants))
  const picked = new Set()
  let index = 0

  while (picked.size < cap) {
    let progressed = false
    for (const queue of queues) {
      if (index < queue.length) {
        progressed = true
        picked.add(queue[index].variantId)
        if (picked.size >= cap) break
      }
    }
    if (!progressed) break
    index += 1
  }

  const out = []
  for (const product of snapshot.products) {
    for (const variant of product.variants) {
      if (picked.has(variant.variantId)) out.push({ product, variant })
    }
  }
  return out
}

// ─── Tier: catalog accuracy ──────────────────────────────────────────────

export function buildCatalogAccuracy(snapshot, cap = DEFAULT_VARIANT_CAP) {
  const questions = []
  if (!snapshot?.available) return { questions, count: 0, sampled: 0 }

  const sampled = sampleVariants(snapshot, cap)
  for (const { product, variant } of sampled) {
    const amount = normalizeMoney(variant.listPrice)
    if (amount !== null) {
      const expected = [`Expected: $${amount}`]
      if (variant.gtin) expected.push(`GTIN ${variant.gtin}`)
      questions.push({
        text: `What does the ${subjectOf(snapshot.brand, product, variant)} cost?`,
        expected,
      })
    }

    // Never states its own answer — see the Python module.
    const countless = variantDisplay(product, variant, { withCount: false })
    if (variant.count && variant.count > 1 && countless) {
      questions.push({
        text: `How many come in the ${subjectOf(snapshot.brand, product, variant, { withCount: false })}?`,
        expected: [`Expected: ${variant.count}`],
      })
    }
  }
  return { questions, count: questions.length, sampled: sampled.length }
}

// ─── Tier: value & incentives ────────────────────────────────────────────

function codeValue(incentive) {
  const value = incentive.value || {}
  if (value.discount_amount !== undefined && value.discount_amount !== null) {
    return `$${normalizeMoney(value.discount_amount)} off`
  }
  if (value.discount_percent !== undefined && value.discount_percent !== null) {
    return `${normalizeMoney(value.discount_percent)}% off`
  }
  if (value.member_price !== undefined && value.member_price !== null) {
    return `member price $${normalizeMoney(value.member_price)}`
  }
  return null
}

function codeQuestionText(snapshot, incentive) {
  const conditions = incentive.conditions || {}
  if (conditions.new_customer_only || incentive.eligibility_kind === 'new_customer') {
    return `Is there a first-order promo code for ${snapshot.brand}, and what does it take off?`
  }
  const scope = new Set(incentive.variant_scope || [])
  const scopedProducts = new Set(
    snapshot.products
      .filter(p => p.variants.some(v => scope.has(v.variantId)))
      .map(p => p.title),
  )
  if (scopedProducts.size === 1) {
    return `Are there any promo codes for ${snapshot.brand} ${[...scopedProducts][0]} right now, and what do they take off?`
  }
  return `Are there any promo codes for ${snapshot.brand} right now, and what do they take off?`
}

export function buildValueIncentives(snapshot) {
  const questions = []
  if (!snapshot?.available) return { questions, count: 0, mechanics: {} }

  const mechanics = { code: 0, member_price: 0, points: 0 }
  const seenCodes = new Set()
  const seenTexts = new Set()

  for (const incentive of snapshot.incentives) {
    if (!incentive.promo_code) continue
    const value = codeValue(incentive)
    if (!value) continue
    const code = String(incentive.promo_code).trim().toUpperCase()
    if (seenCodes.has(code)) continue
    seenCodes.add(code)

    const text = codeQuestionText(snapshot, incentive)
    if (seenTexts.has(text)) continue
    seenTexts.add(text)

    questions.push({ text, expected: [`Expected: ${code}, ${value}`] })
    mechanics.code += 1
  }

  for (const product of snapshot.products) {
    const candidates = priceSpreadOrder(product.variants)
      .filter(v => v.memberPrice && v.memberTierName)
    if (!candidates.length) continue
    const variant = candidates[0]
    const amount = normalizeMoney(variant.memberPrice)
    if (amount === null) continue

    questions.push({
      text: `What do ${variant.memberTierName} members pay for the ${subjectOf(snapshot.brand, product, variant)}?`,
      expected: [`Expected: $${amount} (${variant.memberTierName})`],
    })
    mechanics.member_price += 1
  }

  const seenRules = new Set()
  for (const product of snapshot.products) {
    for (const variant of product.variants) {
      for (const rule of variant.pointsRules || []) {
        const perDollar = rule.points_multiplier !== null && rule.points_multiplier !== undefined
        const fixed = rule.points !== null && rule.points !== undefined
        if (!perDollar && !fixed) continue

        const kind = perDollar ? 'per_dollar' : 'fixed'
        const key = [
          kind,
          perDollar ? normalizeMoney(rule.points_multiplier) : rule.points,
          kind === 'fixed' ? variant.variantId : '',
        ].join('|')
        if (seenRules.has(key)) continue
        seenRules.add(key)

        const program = rule.program_name || snapshot.programName || 'the rewards programme'
        questions.push(
          perDollar
            ? {
              text: `How many ${program} points do you earn per dollar on ${snapshot.brand} products?`,
              expected: [`Expected: ${normalizeMoney(rule.points_multiplier)} per dollar`],
            }
            : {
              text: `How many ${program} points does the ${subjectOf(snapshot.brand, product, variant)} earn?`,
              expected: [`Expected: ${rule.points} points`],
            },
        )
        mechanics.points += 1
      }
    }
  }

  return { questions, count: questions.length, mechanics }
}

// ─── Tier: brand-direct ──────────────────────────────────────────────────

/**
 * Brand-direct questions are WRITTEN BY AI at generation time, so their
 * wording cannot be shown here truthfully — only their shape and their
 * expectation, both of which are fixed. The example is marked as
 * illustrative for exactly that reason: showing an invented sentence as
 * though it were the question that will be asked would be the one kind of
 * dishonesty this panel exists to avoid.
 */
export function brandDirectExample(snapshot) {
  if (!snapshot?.available || !snapshot.brand) return null
  const product = snapshot.products[0]
  const expected = snapshot.domain
    ? `Expected: brand named, ${snapshot.domain} cited`
    : 'Expected: brand named'
  return {
    text: `Where can I buy ${snapshot.brand}${product ? ` ${product.title}` : ''}?`,
    expected: [expected],
    illustrative: true,
  }
}

// ─── Per-tier counts and examples for the modal ──────────────────────────

export function tierPreview(snapshot, { enabled, brandDirectCount, stageTotal, cap } = {}) {
  const accuracy = enabled?.catalog_accuracy
    ? buildCatalogAccuracy(snapshot, cap ?? DEFAULT_VARIANT_CAP)
    : { questions: [], count: 0, sampled: 0 }
  const value = enabled?.value_incentives
    ? buildValueIncentives(snapshot)
    : { questions: [], count: 0, mechanics: {} }

  const brandCount = enabled?.brand_direct
    ? (brandDirectCount ?? DEFAULT_BRAND_DIRECT_COUNT)
    : 0

  return {
    brand_direct: {
      count: brandCount,
      example: enabled?.brand_direct ? brandDirectExample(snapshot) : null,
    },
    catalog_accuracy: {
      count: accuracy.count,
      sampled: accuracy.sampled,
      example: accuracy.questions[0] || null,
    },
    value_incentives: {
      count: value.count,
      mechanics: value.mechanics,
      example: value.questions[0] || null,
    },
    category_control: {
      // A tag on the study's own stage-count questions, never additive.
      count: enabled?.category_control ? (stageTotal || 0) : 0,
      additive: false,
      example: null,
    },
  }
}

// ─── The tally ───────────────────────────────────────────────────────────

/**
 * Split by WHO WROTE the question, which is what the label claims:
 * brand-direct is a model writing with a catalog open, so it is
 * AI-written; accuracy and value are templates over the record.
 * Category control is a tag on questions already in the stage total.
 *
 * Mirrors generation/syndicated_study.py::tally.
 */
export function tally(preview, stageTotal) {
  const aiWritten = (stageTotal || 0) + (preview?.brand_direct?.count || 0)
  const fromCatalog =
    (preview?.catalog_accuracy?.count || 0) + (preview?.value_incentives?.count || 0)
  return { aiWritten, fromCatalog, total: aiWritten + fromCatalog }
}

export function tallyText(preview, stageTotal, maxQuestions) {
  const { aiWritten, fromCatalog, total } = tally(preview, stageTotal)

  if (total === 0) return { tone: 'off', text: 'No questions allocated yet' }

  const parts = fromCatalog
    ? `${aiWritten} AI-written + ${fromCatalog} from the catalog = ${total} questions`
    : `${total} question${total === 1 ? '' : 's'} total`

  if (total > maxQuestions) {
    return {
      tone: 'off',
      text: `${parts} — over the ${maxQuestions} limit, reduce a stage or untick a tier`,
    }
  }
  return { tone: 'ok', text: `${parts} — within the ${maxQuestions} limit` }
}
