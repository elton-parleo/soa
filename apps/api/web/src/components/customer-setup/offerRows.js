/**
 * The wizard's offer row editor <-> supply's owned incentives (1B).
 *
 * The mock's row is four plain cells — mechanic, name, value/rule, applies
 * to. Supply's incentive is structured: each mechanic takes exactly the
 * fields that mean something for it (a coupon takes a code and ONE of a
 * percent or an amount; a member price one price for one GTIN). So the
 * "value / rule" cell is read with a small, explicit grammar, and a row it
 * cannot read is an error on that row — never a guess. A rule like "35% off
 * first, 5% ongoing" is two offers, and the row says so.
 *
 *   value        "10%" -> percent · "$5", "5 USD", "5.00" -> amount
 *                "2x" -> points multiplier · "500 points" -> points
 *   applies to   "", "all", "all products" -> all
 *                one or more GTINs -> those GTINs
 *                anything else -> that category
 *
 * Values leave here as decimal STRINGS: supply refuses JSON numbers.
 */
export const MECHANICS = [
  { value: 'loyalty_program', label: 'Loyalty program', valueHint: 'Tier (optional)' },
  { value: 'member_price', label: 'Member price', valueHint: 'Price, e.g. $4.99' },
  { value: 'coupon_code', label: 'Coupon code', valueHint: '10% or $5' },
  { value: 'rebate', label: 'Rebate', valueHint: '10% or $5' },
  { value: 'subscription_discount', label: 'Subscription discount', valueHint: '5% or $2' },
  { value: 'points', label: 'Points', valueHint: '2x or 500 points' },
]

export const MECHANIC_LABEL = Object.fromEntries(MECHANICS.map((m) => [m.value, m.label]))

const DISCOUNTED = new Set(['coupon_code', 'rebate', 'subscription_discount'])
const CURRENCY_SYMBOL = { '$': 'USD', '£': 'GBP', '€': 'EUR' }
const DECIMAL = /^\d+(\.\d{1,2})?$/
const GTIN = /^\d{8}$|^\d{12,14}$/

export function emptyRow(mechanic = 'coupon_code') {
  return { mechanic, name: '', value: '', appliesTo: '' }
}

/** "$4.99" | "4.99 USD" | "4.99" -> { amount, currency } or null. */
function readAmount(text, defaultCurrency) {
  let t = text.replace(/,/g, '').trim()
  let currency = null
  const symbol = t[0]
  if (CURRENCY_SYMBOL[symbol]) {
    currency = CURRENCY_SYMBOL[symbol]
    t = t.slice(1).trim()
  }
  const coded = t.match(/^(\S+)\s+([A-Za-z]{3})$/)
  if (coded) {
    t = coded[1]
    currency = coded[2].toUpperCase()
  }
  if (!DECIMAL.test(t)) return null
  return { amount: t, currency: currency || defaultCurrency }
}

function readScope(text) {
  const t = (text || '').trim()
  if (!t || /^all( products)?$/i.test(t)) return { applies_to: 'all' }
  const parts = t.split(/[\s,;]+/).filter(Boolean)
  if (parts.every((p) => GTIN.test(p))) return { applies_to: 'gtins', applies_to_gtins: parts }
  return { applies_to: 'category', applies_to_category: t }
}

/**
 * One row -> { incentive } or { error }. An entirely blank row is
 * { skip: true }: the editor's spare line, not an offer.
 */
export function toIncentive(row, { currency = 'USD' } = {}) {
  const name = (row.name || '').trim()
  const value = (row.value || '').trim()
  if (!name && !value && !(row.appliesTo || '').trim()) return { skip: true }
  if (!name) return { error: 'needs a name' }

  const incentive = { mechanic: row.mechanic, name, ...readScope(row.appliesTo) }

  if (row.mechanic === 'loyalty_program') {
    if (value) incentive.tier_name = value
    return { incentive }
  }

  if (row.mechanic === 'coupon_code') {
    if (/\s/.test(name)) return { error: 'a coupon\'s name is its code: one word, like SAVE10' }
    incentive.code = name
  }

  if (row.mechanic === 'points') {
    const multiplier = value.match(/^(\d+(\.\d+)?)\s*x$/i)
    const points = value.match(/^(\d+)\s*(points?|pts)?$/i)
    if (multiplier) incentive.points_multiplier = multiplier[1]
    else if (points) incentive.points = Number(points[1])
    else return { error: 'points: write "2x" or "500 points"' }
    return { incentive }
  }

  if (row.mechanic === 'member_price') {
    const read = readAmount(value, currency)
    if (!read) return { error: 'member price: write a price like $4.99' }
    if (incentive.applies_to !== 'gtins' || incentive.applies_to_gtins.length !== 1) {
      return { error: 'a member price applies to exactly one product: put its GTIN in "Applies to"' }
    }
    incentive.member_price = read.amount
    incentive.currency = read.currency
    return { incentive }
  }

  if (DISCOUNTED.has(row.mechanic)) {
    const percent = value.match(/^(\d+(\.\d+)?)\s*%(\s*off)?$/i)
    if (percent) {
      incentive.discount_percent = percent[1]
      return { incentive }
    }
    const read = readAmount(value.replace(/\s*off$/i, ''), currency)
    if (read) {
      incentive.discount_amount = read.amount
      incentive.currency = read.currency
      return { incentive }
    }
    return {
      error: 'one value per offer: a percent like 10% or an amount like $5 '
        + '(a two-part rule is two offers)',
    }
  }

  return { error: `unknown kind of offer: ${row.mechanic}` }
}

/** Every row -> { incentives, errors: {index: message} }. */
export function toIncentives(rows, opts) {
  const incentives = []
  const errors = {}
  rows.forEach((row, index) => {
    const result = toIncentive(row, opts)
    if (result.error) errors[index] = result.error
    else if (result.incentive) incentives.push(result.incentive)
  })
  return { incentives, errors }
}

function formatAmount(amount, currency) {
  const symbol = Object.entries(CURRENCY_SYMBOL).find(([, code]) => code === currency)?.[0]
  return symbol ? `${symbol}${amount}` : `${amount} ${currency || ''}`.trim()
}

/** A stored incentive (supply's view, or a preview row's values) -> an editor row. */
export function fromIncentive(incentive) {
  const i = incentive || {}
  let value = ''
  if (i.discount_percent != null) value = `${Number(i.discount_percent)}%`
  else if (i.discount_amount != null) value = formatAmount(i.discount_amount, i.currency)
  else if (i.member_price != null) value = formatAmount(i.member_price, i.currency)
  else if (i.points_multiplier != null) value = `${Number(i.points_multiplier)}x`
  else if (i.points != null) value = `${i.points} points`
  else if (i.tier_name) value = i.tier_name

  let appliesTo = ''
  if (i.applies_to === 'gtins') appliesTo = (i.applies_to_gtins || []).join(', ')
  else if (i.applies_to === 'category') appliesTo = i.applies_to_category || ''
  else appliesTo = 'all products'

  return {
    mechanic: i.mechanic || 'coupon_code',
    name: i.mechanic === 'coupon_code' ? (i.code || i.name || '') : (i.name || ''),
    value,
    appliesTo,
  }
}

/** "Vital Care Core (loyalty program) · Repeat Delivery (subscription discount)" */
export function describeOffers(rows) {
  const named = rows.filter((r) => (r.name || '').trim())
  if (named.length === 0) return 'none'
  return named
    .map((r) => `${r.name.trim()} (${(MECHANIC_LABEL[r.mechanic] || r.mechanic).toLowerCase()})`)
    .join(' · ')
}
