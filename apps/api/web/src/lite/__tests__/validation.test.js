import { describe, it, expect } from 'vitest'
import { validateEmail, validateName, validateSubmission } from '../validation.js'

describe('validateName', () => {
  it('accepts a normal brand name', () => {
    expect(validateName('Drunk Elephant', 'Brand name')).toBeNull()
  })

  it('accepts ampersands, apostrophes, and accents', () => {
    expect(validateName("L'Oréal", 'Brand name')).toBeNull()
    expect(validateName('Procter & Gamble', 'Brand name')).toBeNull()
  })

  it('rejects names shorter than 2 characters', () => {
    expect(validateName('A', 'Brand name')).toMatch(/2-80 characters/)
  })

  it('rejects names longer than 80 characters', () => {
    expect(validateName('A'.repeat(81), 'Brand name')).toMatch(/2-80 characters/)
  })

  it('rejects email-shaped input', () => {
    expect(validateName('someone@example.com', 'Brand name')).toMatch(/email/)
  })

  it.each([
    'rival.com',
    'https://rival.com',
    'www.rival.com',
  ])('rejects URL-shaped input: %s', (bad) => {
    expect(validateName(bad, 'Brand name')).toMatch(/URL/)
  })

  it.each([
    '<script>alert(1)</script>',
    "'; DROP TABLE users; --",
    'brand`whoami`',
  ])('rejects injection-shaped input: %s', (bad) => {
    expect(validateName(bad, 'Brand name')).toMatch(/disallowed characters/)
  })
})

describe('validateEmail', () => {
  it('accepts a valid email', () => {
    expect(validateEmail('visitor@example.com')).toBeNull()
  })

  it.each(['not-an-email', 'missing@tld', '@nodomain.com', ''])(
    'rejects invalid email: %s',
    (bad) => {
      expect(validateEmail(bad)).not.toBeNull()
    }
  )
})

describe('validateSubmission', () => {
  it('is valid for a brand with two distinct competitors', () => {
    const { isValid, errors, competitors } = validateSubmission('Acme Co', ['Rival Co', 'Other Co'])
    expect(isValid).toBe(true)
    expect(errors.brandName).toBeNull()
    expect(competitors).toEqual(['Rival Co', 'Other Co'])
  })

  it('is valid with zero competitors', () => {
    const { isValid, competitors } = validateSubmission('Acme Co', ['', ''])
    expect(isValid).toBe(true)
    expect(competitors).toEqual([])
  })

  it('is invalid when brand name is too short', () => {
    const { isValid, errors } = validateSubmission('A', ['', ''])
    expect(isValid).toBe(false)
    expect(errors.brandName).not.toBeNull()
  })

  it('flags a competitor matching the brand, case-insensitive', () => {
    const { isValid, errors } = validateSubmission('Acme Co', ['ACME CO', ''])
    expect(isValid).toBe(false)
    expect(errors.competitors[0]).toMatch(/different/)
  })

  it('flags duplicate competitors, case-insensitive', () => {
    const { isValid, errors } = validateSubmission('Acme Co', ['Rival Co', 'rival co'])
    expect(isValid).toBe(false)
    expect(errors.competitors[1]).toMatch(/different/)
  })

  it('flags an individually invalid competitor name', () => {
    const { isValid, errors } = validateSubmission('Acme Co', ['http://evil.com', ''])
    expect(isValid).toBe(false)
    expect(errors.competitors[0]).toMatch(/URL/)
  })
})
