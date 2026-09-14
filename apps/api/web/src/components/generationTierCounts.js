/**
 * What a syndicated study actually contains, tier by tier.
 *
 * The generation report used to answer "how many questions is this?"
 * with provenance.rows_generated, which is the count the general
 * generator returned — the stage questions and nothing else. For an
 * ungrounded study those are the same number. For the first real
 * brand-mode study they were 50 and 87, and the report said 50: the
 * catalog tiers are built after that number is recorded, by code that
 * never touches it.
 *
 * The fix is not to redefine rows_generated. It means what it says, and
 * the stage/tier split is exactly what a reader of this report needs to
 * see anyway — 25 template questions over a published catalog and 50
 * model-written ones are different things, and a single total hides the
 * difference. So: read the tier config, and state all three.
 */

// Ordered as the study is: the questions the brief asked for, then the
// tier a model wrote, then the tiers read off the record.
const CATALOG_TIERS = ['catalog_accuracy', 'value_incentives']

export const TIER_LABELS = {
  brand_direct:     'brand-direct',
  catalog_accuracy: 'catalog accuracy',
  value_incentives: 'value & incentives',
  category_control: 'category control',
}

function entry(config, tier) {
  const e = config?.[tier]
  return e && typeof e === 'object' ? e : null
}

function count(config, tier) {
  const e = entry(config, tier)
  if (!e || !e.enabled) return 0
  return Number(e.count) || 0
}

/**
 * null when there is no tier config at all — an ungrounded study, where
 * the stage counts already are the whole study and a breakdown of one
 * number into one number is noise.
 */
export function tierCounts(config) {
  if (!config || typeof config !== 'object') return null
  const enabled = ['brand_direct', ...CATALOG_TIERS].filter(t => entry(config, t)?.enabled)
  if (!enabled.length) return null

  const stage = Number(config.category_control?.stage_total) || 0
  const brandDirect = count(config, 'brand_direct')
  const fromCatalog = CATALOG_TIERS.reduce((n, t) => n + count(config, t), 0)

  return {
    stage,
    brandDirect,
    fromCatalog,
    byTier: CATALOG_TIERS
      .filter(t => entry(config, t)?.enabled)
      .map(t => ({ tier: t, count: count(config, t) })),
    total: stage + brandDirect + fromCatalog,
    shortfalls: shortfalls(config),
  }
}

/**
 * A tier that asked for more than it produced, or could not be built at
 * all. Both are the same fact to a reader — this study has fewer
 * questions of this kind than it was supposed to — and both read as the
 * plan if the report does not say so.
 */
export function shortfalls(config) {
  const out = []
  for (const tier of ['brand_direct', ...CATALOG_TIERS]) {
    const e = entry(config, tier)
    if (!e || !e.enabled) continue
    if (e.unavailable) {
      out.push({ tier, reason: e.unavailable })
      continue
    }
    const short = Number(e.shortfall) || 0
    if (short > 0) {
      out.push({
        tier,
        short,
        requested: Number(e.requested) || (Number(e.count) || 0) + short,
        delivered: Number(e.count) || 0,
      })
    }
  }
  return out
}

/**
 * "50 stage + 12 brand-direct + 25 from the catalog = 87".
 *
 * Parts with a zero count are omitted rather than printed as '+ 0': a
 * study with no brand-direct tier did not fail to write twelve, it was
 * never asked to.
 */
export function tierCountsText(counts) {
  if (!counts) return null
  const parts = []
  if (counts.stage) parts.push(`${counts.stage} stage`)
  if (counts.brandDirect) parts.push(`${counts.brandDirect} brand-direct`)
  if (counts.fromCatalog) parts.push(`${counts.fromCatalog} from the catalog`)
  if (!parts.length) return null
  return `${parts.join(' + ')} = ${counts.total}`
}
