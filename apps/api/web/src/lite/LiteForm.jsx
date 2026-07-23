/**
 * SoA Lite's entry form — a single field accepting either a brand name
 * or a store URL, auto-detected ("contains a dot + no spaces" per the
 * product spec). URL mode shows an editable, auto-derived brand-name
 * confirmation field; the visitor's edit (if any) always wins over
 * further auto-derivation, tracked via brandManuallyEdited.
 *
 * No screenshot in design-refs/ shows an input form (the reference
 * captures are all completed reports) — this applies the same tokens
 * (paper background, card shape, pill button, mono micro-copy) for
 * visual consistency with the rest of the widget.
 */
import { useEffect, useState } from 'react'
import { liteApi } from './liteApi.js'
import { validateSubmission } from './validation.js'
import { looksLikeUrl, deriveBrandFromUrl } from './liteDerive.js'
import { LogoHeader, ErrorBanner, LightCard } from './liteTheme.jsx'

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

  const fieldErrorStyle = { fontSize: 12, color: 'var(--bad-ink)', marginBottom: 10, minHeight: 16 }
  const labelStyle = { fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 6, display: 'block' }

  return (
    <div className="lite-root">
      <div className="lite-shell" style={{ maxWidth: 480 }}>
        <LightCard>
          <LogoHeader />
          <div className="lite-headline" style={{ fontSize: 20, marginBottom: 6 }}>
            See your brand's Share of Algorithm
          </div>
          <div className="lite-body lite-muted" style={{ marginBottom: 20 }}>
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
              className="lite-input"
              placeholder="e.g. Drunk Elephant or drunkelephant.com"
              value={primaryInput}
              onChange={(e) => handlePrimaryChange(e.target.value)}
              style={{ marginBottom: 4 }}
            />
            {isUrlMode ? (
              <div className="lite-muted" style={{ fontSize: 12, marginBottom: 10 }}>
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
                  className="lite-input"
                  placeholder="e.g. Drunk Elephant"
                  value={confirmedBrand}
                  onChange={(e) => handleConfirmedBrandChange(e.target.value)}
                  style={{ marginBottom: 4 }}
                />
                <div style={fieldErrorStyle}>{errors.brandName || ' '}</div>
              </div>
            )}

            {[0, 1].map((i) => (
              <div key={i}>
                <label style={labelStyle} htmlFor={`lite-competitor-${i}`}>
                  Competitor {i + 1} <span className="lite-muted" style={{ fontWeight: 400 }}>(optional)</span>
                </label>
                <input
                  id={`lite-competitor-${i}`}
                  type="text"
                  className="lite-input"
                  placeholder="e.g. Glossier"
                  value={competitors[i]}
                  onChange={(e) => handleCompetitorChange(i, e.target.value)}
                  style={{ marginBottom: 4 }}
                />
                <div style={fieldErrorStyle}>{errors.competitors[i] || ' '}</div>
              </div>
            ))}

            <div className="lite-label" style={{
              marginBottom: 16, padding: '8px 10px', background: 'var(--paper)', borderRadius: 6,
              textTransform: 'none', letterSpacing: 'normal', fontSize: 11,
            }}>
              Protected against automated submissions.
            </div>

            <button type="submit" disabled={submitting} className="lite-pill lite-pill--solid" style={{ width: '100%', height: 46, fontSize: 14 }}>
              {submitting ? 'Starting…' : 'Run my free diagnostic'}
            </button>
          </form>
        </LightCard>
      </div>
    </div>
  )
}
