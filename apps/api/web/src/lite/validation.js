/**
 * Client-side mirror of the validation rules enforced server-side in
 * apps/api/app/schemas.py (PublicLiteSubmitRequest/PublicLiteEmailRequest).
 * This is a UX convenience only — the API is the source of truth and
 * re-validates everything; keep these patterns in sync if the API's
 * change.
 */
const URL_PATTERN = /(https?:\/\/|www\.)|([a-z0-9-]+\.[a-z]{2,}(\/|\s|$))/i
const EMAIL_PATTERN = /[^\s@]+@[^\s@]+\.[^\s@]+/
const ALLOWED_NAME_PATTERN = /^[A-Za-zÀ-ÿ0-9' &.,-]+$/

export function validateName(rawValue, fieldLabel) {
  const v = (rawValue || '').trim()
  if (v.length < 2 || v.length > 80) {
    return `${fieldLabel} must be 2-80 characters`
  }
  if (EMAIL_PATTERN.test(v)) {
    return `${fieldLabel} must not be an email address`
  }
  if (URL_PATTERN.test(v)) {
    return `${fieldLabel} must not be a URL or web address`
  }
  if (!ALLOWED_NAME_PATTERN.test(v)) {
    return `${fieldLabel} contains disallowed characters`
  }
  return null
}

export function validateEmail(rawValue) {
  const v = (rawValue || '').trim()
  if (!EMAIL_PATTERN.test(v)) {
    return 'Enter a valid email address'
  }
  return null
}

/**
 * Validates the whole submission. Returns { brandName, competitors }
 * error maps (competitors keyed by index) — both empty when valid.
 * competitors[] here is the trimmed, non-empty subset of the two raw
 * input fields (an empty competitor input is allowed and simply
 * omitted, not an error).
 */
export function validateSubmission(brandNameRaw, competitorNamesRaw) {
  const errors = { brandName: null, competitors: {} }

  const brandError = validateName(brandNameRaw, 'Brand name')
  if (brandError) errors.brandName = brandError

  const competitors = competitorNamesRaw
    .map((c) => (c || '').trim())
    .filter((c) => c.length > 0)

  if (competitors.length > 2) {
    errors.competitors[2] = 'Only 2 competitors are allowed'
  }

  competitorNamesRaw.forEach((raw, i) => {
    const v = (raw || '').trim()
    if (!v) return
    const err = validateName(v, 'Competitor name')
    if (err) errors.competitors[i] = err
  })

  const brandKey = (brandNameRaw || '').trim().toLowerCase()
  const seen = new Set([brandKey])
  competitorNamesRaw.forEach((raw, i) => {
    const v = (raw || '').trim()
    if (!v || errors.competitors[i]) return
    const key = v.toLowerCase()
    if (seen.has(key)) {
      errors.competitors[i] = 'Must be different from the brand and other competitors'
    }
    seen.add(key)
  })

  const isValid = !errors.brandName && Object.keys(errors.competitors).length === 0
  return { errors, competitors, isValid }
}
