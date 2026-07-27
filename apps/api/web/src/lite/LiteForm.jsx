/**
 * SoA Lite's entry form — a single field accepting either a brand name
 * or a store URL, auto-detected ("contains a dot + no spaces" per the
 * product spec). URL mode shows an editable, auto-derived brand-name
 * confirmation field; the visitor's edit (if any) always wins over
 * further auto-derivation, tracked via brandManuallyEdited.
 *
 * `compact` (Stage 6) renders the identical state machine and submit
 * path as an inline pill input + button — no LogoHeader/card chrome —
 * for embedding in the scan.parleo.io landing page's hero and final-CTA
 * bands. It changes markup only: every hook, validation call, and
 * liteApi.submit call below is shared between both render modes
 * untouched.
 *
 * Stage 13 (W1): the compact form no longer collects competitor names —
 * the worker now auto-generates them (see
 * apps/pipeline/generation/competitor_generator.py) — so its markup
 * shows a one-line note instead of the old disclosure toggle + two
 * inputs. `competitors` state still exists (submitted as [] from this
 * branch) so the shared handleSubmit/validateSubmission path needs no
 * change. The non-compact card (the older /lite embed) is unchanged and
 * still exposes manual competitor entry — that path remains valid as
 * the override input feeding the worker's select_competitors top-up.
 */
import { useEffect, useId, useState } from 'react'
import { liteApi } from './liteApi.js'
import { validateSubmission } from './validation.js'
import { looksLikeUrl, deriveBrandFromUrl } from './liteDerive.js'
import { LogoHeader, ErrorBanner, LightCard } from './liteTheme.jsx'

export function LiteForm({
  onSubmitted,
  initialBrandName = '',
  compact = false,
  inv = false,
  submitLabel = 'Run my free diagnostic',
  placeholder = 'e.g. Allbirds or allbirds.com',
}) {
  const idPrefix = useId()
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

  if (compact) {
    // Dark bands (final-CTA) need inverse text/error colors and the
    // accent (blue) button; the light hero uses the ink (dark) button —
    // see the Stage 6 design language addendum.
    const compactFieldErrorStyle = { ...fieldErrorStyle, color: inv ? 'var(--bad-on-dark)' : 'var(--bad-ink)' }
    return (
      <div>
        <ErrorBanner message={submitError} />
        <form onSubmit={handleSubmit}>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <label className="lite-visually-hidden" htmlFor={`${idPrefix}-primary`}>Your brand or store URL</label>
            <input
              id={`${idPrefix}-primary`}
              type="text"
              className="lite-input lite-input--pill"
              placeholder={placeholder}
              value={primaryInput}
              onChange={(e) => handlePrimaryChange(e.target.value)}
              style={{ flex: '1 1 220px' }}
            />
            <button
              type="submit"
              disabled={submitting}
              className={`lite-pill ${inv ? 'lite-pill--solid' : 'lite-pill--solid-ink'}`}
              style={{ flex: '0 0 auto', height: 44, padding: '0 22px' }}
            >
              {submitting ? 'Starting…' : submitLabel}
            </button>
          </div>
          {!isUrlMode && (
            <div style={compactFieldErrorStyle}>{errors.brandName || ' '}</div>
          )}
          {isUrlMode && (
            <div style={{ marginTop: 10 }}>
              <label className={inv ? 'lite-muted--inv' : 'lite-muted'} style={{ fontSize: 12, marginBottom: 6, display: 'block' }} htmlFor={`${idPrefix}-confirmed-brand`}>
                Confirm your brand name
              </label>
              <input
                id={`${idPrefix}-confirmed-brand`}
                type="text"
                className="lite-input lite-input--pill"
                placeholder="e.g. Allbirds"
                value={confirmedBrand}
                onChange={(e) => handleConfirmedBrandChange(e.target.value)}
              />
              <div style={compactFieldErrorStyle}>{errors.brandName || ' '}</div>
            </div>
          )}

          <div
            className={inv ? 'lite-muted--inv' : 'lite-muted'}
            style={{ fontSize: 12, marginTop: 8 }}
          >
            We'll identify your closest competitors automatically.
          </div>
        </form>
      </div>
    )
  }

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
              placeholder={placeholder}
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
                  placeholder="e.g. Allbirds"
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
              {submitting ? 'Starting…' : submitLabel}
            </button>
          </form>
        </LightCard>
      </div>
    </div>
  )
}
