/**
 * The offer editor's four cells -> supply's structured owned incentives.
 * Every shape the grammar reads, and the refusals it gives instead of a
 * guess. The incentive objects asserted here are what supply's
 * incentives.check accepts (decimal strings, one value per mechanic).
 */
import { describe, expect, it } from 'vitest'
import { toIncentive, toIncentives, fromIncentive, describeOffers } from '../offerRows.js'

const row = (mechanic, name, value = '', appliesTo = '') => ({ mechanic, name, value, appliesTo })

describe('reading a row', () => {
  it('a coupon: its name is its code, a percent off, all products', () => {
    expect(toIncentive(row('coupon_code', 'SAVE10', '10%', 'all products'))).toEqual({
      incentive: {
        mechanic: 'coupon_code', name: 'SAVE10', code: 'SAVE10',
        applies_to: 'all', discount_percent: '10',
      },
    })
  })

  it('an amount off reads its currency from the symbol or the code', () => {
    expect(toIncentive(row('rebate', 'Mail-in', '$5')).incentive)
      .toMatchObject({ discount_amount: '5', currency: 'USD' })
    expect(toIncentive(row('rebate', 'Mail-in', '5.00 EUR off')).incentive)
      .toMatchObject({ discount_amount: '5.00', currency: 'EUR' })
  })

  it('a member price needs exactly one GTIN', () => {
    expect(toIncentive(row('member_price', 'Member', '$4.99', '00012345000021')).incentive).toEqual({
      mechanic: 'member_price', name: 'Member', applies_to: 'gtins',
      applies_to_gtins: ['00012345000021'], member_price: '4.99', currency: 'USD',
    })
    expect(toIncentive(row('member_price', 'Member', '$4.99', 'all')).error)
      .toMatch(/exactly one product/)
  })

  it('points: a multiplier or a count', () => {
    expect(toIncentive(row('points', 'Double', '2x')).incentive).toMatchObject({ points_multiplier: '2' })
    expect(toIncentive(row('points', 'Welcome', '500 points')).incentive).toMatchObject({ points: 500 })
  })

  it('a loyalty program carries an optional tier, and a category scope', () => {
    expect(toIncentive(row('loyalty_program', 'Vital Care', 'Gold', 'food & litter')).incentive).toEqual({
      mechanic: 'loyalty_program', name: 'Vital Care', tier_name: 'Gold',
      applies_to: 'category', applies_to_category: 'food & litter',
    })
  })

  it('refuses a two-part rule instead of picking half of it', () => {
    expect(toIncentive(row('subscription_discount', 'Repeat Delivery', '35% off first, 5% ongoing')).error)
      .toMatch(/two-part rule is two offers/)
  })

  it('refuses a coupon whose code is not one word', () => {
    expect(toIncentive(row('coupon_code', '10% off', '10%')).error).toMatch(/one word/)
  })

  it('skips the blank spare row and reports the others by index', () => {
    const { incentives, errors } = toIncentives([
      row('coupon_code', ''), row('coupon_code', 'OK5', '5%'), row('rebate', 'x', 'lots'),
    ])
    expect(incentives).toHaveLength(1)
    expect(Object.keys(errors)).toEqual(['2'])
  })
})

describe('writing a stored incentive back into a row', () => {
  it('round-trips through the editor', () => {
    for (const r of [
      row('coupon_code', 'SAVE10', '10%', 'all products'),
      row('rebate', 'Mail-in', '$5', 'all products'),
      row('points', 'Double', '2x', 'all products'),
      row('member_price', 'Member', '$4.99', '00012345000021'),
      row('loyalty_program', 'Vital Care', 'Gold', 'food & litter'),
    ]) {
      expect(fromIncentive(toIncentive(r).incentive)).toEqual(r)
    }
  })

  it('describes the list the way the review step restates it', () => {
    expect(describeOffers([
      row('loyalty_program', 'Vital Care Core'), row('subscription_discount', 'Repeat Delivery'),
      row('coupon_code', ''),
    ])).toBe('Vital Care Core (loyalty program) · Repeat Delivery (subscription discount)')
  })
})
