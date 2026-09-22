/**
 * SoA Lite's entry form — a single field accepting either a brand name
 * or a store URL, auto-detected ("contains a dot + no spaces" per the
 * product spec). URL mode shows an editable, auto-derived brand-name
 * confirmation field; the visitor's edit (if any) always wins over
 * further auto-derivation, tracked via brandManuallyEdited.
 *
 * `compact` (Stage 6, restyled to DS tokens in the V4 redesign) renders
 * the identical state machine and submit path as an inline pill input +
 * button — no LogoHeader/card chrome — for embedding in the audit
 * landing page's hero and final-CTA bands. It changes markup only:
 * every hook, validation call, and liteApi.submit call below is shared
 * between both render modes untouched.
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
import { looksLikeUrl, deriveBrandFromUrl, domainFromStoreUrl } from './liteDerive.js'
import { LogoHeader, ErrorBanner, LightCard } from './liteTheme.jsx'
import { LITE_QUERY_COUNT } from './landing/scanDimensionsRegistry.js'
import { Button } from '../ds/index.js'
import { track, identifyReport, recordOwnedToken, captureSrcParam, getAttribution } from './analytics.js'
import { EVENTS } from './analyticsEvents.js'

// Intake validation (this session): the `code` values
// public_lite.py::_enforce_store_url_admissible returns on a 422. The
// MESSAGE is the API's — one wording, one place — and this set decides
// only that the message belongs under the URL field rather than in the
// generic error slot. An unrecognized code falls through to the
// generic path, so a new server-side code is never swallowed.
const STORE_URL_ERROR_CODES = new Set(['shortener', 'unresolvable', 'reserved_tld'])

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
  // Intake validation (this session): a store URL the API refused —
  // shown UNDER the URL field it's about, not in the generic
  // submit-error slot at the bottom, because it's the URL the visitor
  // needs to change. Cleared the moment they edit that field.
  const [storeUrlError, setStoreUrlError] = useState(null)

  const isUrlMode = looksLikeUrl(primaryInput)

  useEffect(() => {
    if (isUrlMode && !brandManuallyEdited) {
      setConfirmedBrand(deriveBrandFromUrl(primaryInput))
    }
  }, [primaryInput, isUrlMode, brandManuallyEdited])

  function handlePrimaryChange(value) {
    setPrimaryInput(value)
    setStoreUrlError(null)
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
    setStoreUrlError(null)
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
      // The funnel's spine (Q1) — fired once, right on accept, shared by
      // every surface this form renders on (landing hero/final-CTA,
      // the older /lite card). recordOwnedToken is the only signal
      // that later tells report_viewed this browser is the run's
      // owner, not a visitor who opened a shared link — see
      // analytics.js's own doc comment for why sessionStorage's
      // soaLiteToken can't answer that question by itself.
      //
      // identifyReport FIRST, then the event: the run token is the
      // audit's id everywhere (soa_lite_requests.token), and
      // registering it here is what puts report_token on every
      // subsequent event of this session — status_viewed,
      // email_captured, report_viewed — not just this one. The event
      // carries it explicitly as well, so the submission itself joins
      // even if this is the last thing that happens in this tab.
      //
      // The props below are the attribution this session arrived with
      // (analytics.js captured it at init) plus the one fact about the
      // submission that isn't a form value: the store's domain. Never
      // the brand name the visitor typed — that's a form value, and
      // the registry forbids it.
      identifyReport(result.token)
      const attribution = getAttribution()
      track(EVENTS.AUDIT_SUBMITTED, {
        report_token: result.token,
        target_domain: storeUrl ? domainFromStoreUrl(storeUrl) : null,
        oppref: attribution.oppref,
        utm_source: attribution.utm_source,
        src: captureSrcParam(),
      })
      recordOwnedToken(result.token)
      onSubmitted(result.token, { storeUrl })
    } catch (err) {
      if (err.status === 429) {
        setSubmitError(err.message || 'Too many requests — please try again shortly.')
      } else if (STORE_URL_ERROR_CODES.has(err.code)) {
        // Copy comes from the API (one wording, one place) — the form
        // decides only WHERE it goes, which is under the field the
        // visitor has to fix.
        setStoreUrlError(err.message)
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
    // V4 redesign: compact is landing-only (Hero + FinalCta), so its
    // markup can commit fully to DS tokens without touching the
    // non-compact /lite embed below. `inv` (dark band, e.g. the final
    // CTA's ink-photo panel) swaps text/error colors for on-dark
    // legibility; every hook, validation call, and liteApi.submit call
    // stays exactly what the non-compact form uses.
    const pillInputStyle = {
      flex: '1 1 220px',
      minWidth: 0,
      fontFamily: 'var(--font-mono)',
      fontSize: 13.5,
      color: 'var(--text-strong)',
      background: 'var(--surface)',
      border: inv ? '1px solid transparent' : '1px solid var(--border-strong)',
      borderRadius: 999,
      padding: '14px 20px',
      outline: 'none',
      boxShadow: inv ? 'var(--shadow-md)' : 'var(--shadow-sm)',
    }
    const mutedColor = inv ? 'var(--dark-muted)' : 'var(--muted)'
    const errorColor = inv ? '#FFB4B4' : 'var(--red-deep)'
    return (
      <div>
        <ErrorBanner message={submitError} />
        <form onSubmit={handleSubmit}>
          <div className="lite-form-compact-row" style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <label style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0,0,0,0)' }} htmlFor={`${idPrefix}-primary`}>Your brand or store URL</label>
            <input
              id={`${idPrefix}-primary`}
              type="text"
              placeholder={placeholder}
              value={primaryInput}
              onChange={(e) => handlePrimaryChange(e.target.value)}
              style={pillInputStyle}
            />
            {/* Button doesn't take a `type` prop — its underlying <button>
                has none set either, so as a form descendant it defaults
                to type="submit" and this still triggers handleSubmit. */}
            <Button variant="blue" size="lg" arrow disabled={submitting}>
              {submitting ? 'Starting…' : submitLabel}
            </Button>
          </div>
          {storeUrlError && (
            <div style={{ fontSize: 12, color: errorColor, marginTop: 8 }}>{storeUrlError}</div>
          )}
          {!isUrlMode && (
            <div style={{ fontSize: 12, color: errorColor, marginTop: 8, minHeight: 16 }}>{errors.brandName || ' '}</div>
          )}
          {isUrlMode && (
            <div style={{ marginTop: 10 }}>
              <label style={{ fontSize: 12, marginBottom: 6, display: 'block', color: mutedColor }} htmlFor={`${idPrefix}-confirmed-brand`}>
                Confirm your brand name
              </label>
              <input
                id={`${idPrefix}-confirmed-brand`}
                type="text"
                placeholder="e.g. Allbirds"
                value={confirmedBrand}
                onChange={(e) => handleConfirmedBrandChange(e.target.value)}
                style={pillInputStyle}
              />
              <div style={{ fontSize: 12, color: errorColor, marginTop: 8, minHeight: 16 }}>{errors.brandName || ' '}</div>
            </div>
          )}

          <div style={{ fontSize: 12, marginTop: 8, color: mutedColor }}>
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
            free {LITE_QUERY_COUNT}-query diagnostic against ChatGPT and, if you give us a URL,
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
            {storeUrlError && (
              <div style={{ ...fieldErrorStyle, minHeight: undefined }}>{storeUrlError}</div>
            )}
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
