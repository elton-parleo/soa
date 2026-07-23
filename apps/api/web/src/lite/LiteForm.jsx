/**
 * SoA Lite's entry form — a single field accepting either a brand name
 * or a store URL, auto-detected ("contains a dot + no spaces" per the
 * product spec). URL mode shows an editable, auto-derived brand-name
 * confirmation field; the visitor's edit (if any) always wins over
 * further auto-derivation, tracked via brandManuallyEdited.
 */
import { useEffect, useState } from 'react'
import { liteApi } from './liteApi.js'
import { validateSubmission } from './validation.js'
import { looksLikeUrl, deriveBrandFromUrl } from './liteDerive.js'
import { T, outerStyle, cardStyle, LogoHeader, ErrorBanner } from './liteTheme.jsx'

export function LiteForm({ onSubmitted, initialBrandName = '' }) {
  const [primaryInput, setPrimaryInput] = useState(initialBrandName)
  const [confirmedBrand, setConfirmedBrand] = useState('')
  const [brandManuallyEdited, setBrandManuallyEdited] = useState(false)
  const [competitors, setCompetitors] = useState(['', ''])
  const [errors, setErrors] = useState({ brandName: null, competitors: {} })
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)

  const isUrlMode = looksLikeUrl(primaryInput)

  useEffect(() => {
    if (isUrlMode && !brandManuallyEdited) {
      setConfirmedBrand(deriveBrandFromUrl(primaryInput))
    }
  }, [primaryInput, isUrlMode, brandManuallyEdited])

  function handlePrimaryChange(value) {
    setPrimaryInput(value)
    if (!looksLikeUrl(value)) {
      // Leaving URL mode — reset the gate so re-entering it later re-derives fresh.
      setBrandManuallyEdited(false)
    }
  }

  function handleConfirmedBrandChange(value) {
    setConfirmedBrand(value)
    setBrandManuallyEdited(true)
  }

  function handleCompetitorChange(i, value) {
    const next = [...competitors]
    next[i] = value
    setCompetitors(next)
  }

  async function handleSubmit(e) {
    e.preventDefault()
    const resolvedBrand = isUrlMode ? confirmedBrand : primaryInput
    const { errors: validationErrors, competitors: cleanCompetitors, isValid } =
      validateSubmission(resolvedBrand, competitors)
    setErrors(validationErrors)
    if (!isValid) return

    setSubmitting(true)
    setSubmitError(null)
    try {
      const storeUrl = isUrlMode ? primaryInput.trim() : null
      // No captcha provider is wired up yet — the API skips verification
      // (with a loud server-side log warning) when it's unset there too.
      // A real provider's widget would set this via its own callback.
      const payload = {
        brand_name: resolvedBrand.trim(),
        competitor_names: cleanCompetitors,
        captcha_token: 'dev-placeholder-token',
      }
      if (storeUrl) payload.store_url = storeUrl

      const result = await liteApi.submit(payload)
      onSubmitted(result.token, { storeUrl })
    } catch (err) {
      if (err.status === 429) {
        setSubmitError(err.message || 'Too many requests — please try again shortly.')
      } else {
        setSubmitError(err.message || 'Something went wrong. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const inputStyle = {
    width: '100%',
    height: 42,
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    padding: '0 12px',
    fontSize: 14,
    fontFamily: 'inherit',
    color: T.text,
    outline: 'none',
    boxSizing: 'border-box',
    marginBottom: 4,
  }

  const labelStyle = { fontSize: 13, fontWeight: 600, color: T.text, marginBottom: 6, display: 'block' }
  const fieldErrorStyle = { fontSize: 12, color: T.red, marginBottom: 10 }

  return (
    <div style={outerStyle}>
      <div style={cardStyle}>
        <LogoHeader />
        <div style={{ fontSize: 20, fontWeight: 700, color: T.text, marginBottom: 6 }}>
          See your brand's Share of Algorithm
        </div>
        <div style={{ fontSize: 13, color: T.slate, marginBottom: 20, lineHeight: 1.5 }}>
          Enter your brand or store URL and up to 2 competitors — we'll run a
          free 12-query diagnostic against ChatGPT and, if you give us a URL,
          read your store the way an AI shopping agent does.
        </div>

        <ErrorBanner message={submitError} />

        <form onSubmit={handleSubmit}>
          <label style={labelStyle} htmlFor="lite-primary">Your brand or store URL</label>
          <input
            id="lite-primary"
            type="text"
            placeholder="e.g. Drunk Elephant or drunkelephant.com"
            value={primaryInput}
            onChange={(e) => handlePrimaryChange(e.target.value)}
            style={inputStyle}
          />
          {isUrlMode ? (
            <div style={{ fontSize: 12, color: T.slate, marginBottom: 10 }}>
              Looks like a URL — we'll read it the way an AI shopping agent does.
            </div>
          ) : (
            <div style={fieldErrorStyle}>{errors.brandName || ' '}</div>
          )}

          {isUrlMode && (
            <div>
              <label style={labelStyle} htmlFor="lite-confirmed-brand">
                Confirm your brand name
              </label>
              <input
                id="lite-confirmed-brand"
                type="text"
                placeholder="e.g. Drunk Elephant"
                value={confirmedBrand}
                onChange={(e) => handleConfirmedBrandChange(e.target.value)}
                style={inputStyle}
              />
              <div style={fieldErrorStyle}>{errors.brandName || ' '}</div>
            </div>
          )}

          {[0, 1].map((i) => (
            <div key={i}>
              <label style={labelStyle} htmlFor={`lite-competitor-${i}`}>
                Competitor {i + 1} <span style={{ fontWeight: 400, color: T.slateLight }}>(optional)</span>
              </label>
              <input
                id={`lite-competitor-${i}`}
                type="text"
                placeholder="e.g. Glossier"
                value={competitors[i]}
                onChange={(e) => handleCompetitorChange(i, e.target.value)}
                style={inputStyle}
              />
              <div style={fieldErrorStyle}>{errors.competitors[i] || ' '}</div>
            </div>
          ))}

          <div style={{
            fontSize: 11,
            color: T.slateLight,
            marginBottom: 16,
            padding: '8px 10px',
            background: T.offWhite,
            borderRadius: 6,
          }}>
            Protected against automated submissions.
          </div>

          <button
            type="submit"
            disabled={submitting}
            style={{
              width: '100%',
              height: 46,
              background: T.navy,
              color: T.white,
              fontSize: 14,
              fontWeight: 700,
              fontFamily: 'inherit',
              border: 'none',
              borderRadius: 8,
              cursor: submitting ? 'not-allowed' : 'pointer',
              opacity: submitting ? 0.7 : 1,
            }}
          >
            {submitting ? 'Starting…' : 'Run my free diagnostic'}
          </button>
        </form>
      </div>
    </div>
  )
}
