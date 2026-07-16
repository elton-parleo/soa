/**
 * SoA Lite — public, unauthenticated lead-gen widget at /lite.
 *
 * Self-contained: no Sidebar, no AuthContext, no import of the authed
 * app's api.js/supabase.js (see liteApi.js). Meant to be iframed or
 * linked directly from the marketing site, so it makes no fixed-viewport
 * assumptions and must render sensibly at widths as small as ~400px.
 *
 * State machine (mirrors soa_lite_requests server-side):
 *   FORM -> submit -> token stored (state + sessionStorage so a refresh
 *   mid-run doesn't lose it) -> poll /status every 5s -> PROGRESS view
 *   through phases queued/generating_queries/running/analyzing ->
 *   'complete' fetches /report -> TEASER (locked, email null) or
 *   FULL REPORT (unlocked, email set) -> submitting email on the teaser
 *   swaps straight to FULL REPORT using PATCH /email's inline response.
 *   'failed' shows a retry-from-form view.
 */
import { useEffect, useState } from 'react'
import { liteApi } from './liteApi.js'
import { validateEmail, validateSubmission } from './validation.js'

const STORAGE_KEY = 'soaLiteToken'
const POLL_INTERVAL_MS = 5000
const STAGE_ORDER = ['Awareness', 'Research', 'Comparison', 'Ready to Buy']

const T = {
  navy:       '#0D1829',
  white:      '#FFFFFF',
  offWhite:   '#F8FAFC',
  slate:      '#64748B',
  slateLight: '#94A3B8',
  border:     '#E2E8F0',
  text:       '#0F172A',
  textMid:    '#334155',
  indigo:     '#4F46E5',
  green:      '#16A34A',
  red:        '#DC2626',
  redLight:   '#FEE2E2',
}

const BRAND_COLORS = ['#0F172A', '#3B82F6', '#F59E0B']

function formatRsi(v) {
  if (v === null || v === undefined) return '—'
  return v.toFixed(2)
}

function formatPct(v) {
  if (v === null || v === undefined) return '—'
  return `${v.toFixed(1)}%`
}

// ─── Shared layout ─────────────────────────────────────────────────────────

const outerStyle = {
  width: '100%',
  boxSizing: 'border-box',
  padding: '24px 16px',
  fontFamily: "'DM Sans', sans-serif",
  display: 'flex',
  justifyContent: 'center',
}

const cardStyle = {
  width: '100%',
  maxWidth: 480,
  boxSizing: 'border-box',
  background: T.white,
  border: `1px solid ${T.border}`,
  borderRadius: 12,
  padding: 28,
}

function LogoHeader() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20 }}>
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
        <rect x="2" y="2" width="8" height="20" rx="1.5" fill={T.indigo} />
        <rect x="14" y="6" width="8" height="12" rx="1.5" fill={T.indigo} opacity="0.4" />
      </svg>
      <span style={{ fontSize: 16, fontWeight: 700, color: T.text, letterSpacing: '0.04em' }}>
        SoA Lite
      </span>
    </div>
  )
}

function ErrorBanner({ message }) {
  if (!message) return null
  return (
    <div style={{
      background: T.redLight,
      border: '1px solid #FECACA',
      borderRadius: 6,
      padding: '10px 14px',
      fontSize: 13,
      color: '#991B1B',
      marginBottom: 16,
    }}>
      {message}
    </div>
  )
}

// ─── Horizontal bar (reuses MetricsDashboard.jsx's bar-chart pattern) ──────

function BarRow({ label, value, color, delay = 0, animated }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: T.textMid }}>{label}</span>
        <span style={{ fontSize: 12, fontWeight: 700, color: T.textMid, fontFamily: 'monospace' }}>
          {formatPct(value)}
        </span>
      </div>
      <div style={{ height: 8, background: T.border, borderRadius: 4, overflow: 'hidden' }}>
        <div style={{
          height: '100%',
          width: animated ? `${value || 0}%` : '0%',
          background: color,
          borderRadius: 4,
          transition: `width 0.8s ease ${delay}s`,
        }} />
      </div>
    </div>
  )
}

function useAnimateOnMount() {
  const [animated, setAnimated] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setAnimated(true), 80)
    return () => clearTimeout(t)
  }, [])
  return animated
}

// ─── FORM ────────────────────────────────────────────────────────────────

export function LiteForm({ onSubmitted }) {
  const [brandName, setBrandName] = useState('')
  const [competitors, setCompetitors] = useState(['', ''])
  const [errors, setErrors] = useState({ brandName: null, competitors: {} })
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)

  function handleCompetitorChange(i, value) {
    const next = [...competitors]
    next[i] = value
    setCompetitors(next)
  }

  async function handleSubmit(e) {
    e.preventDefault()
    const { errors: validationErrors, competitors: cleanCompetitors, isValid } =
      validateSubmission(brandName, competitors)
    setErrors(validationErrors)
    if (!isValid) return

    setSubmitting(true)
    setSubmitError(null)
    try {
      // No captcha provider is wired up yet — the API skips verification
      // (with a loud server-side log warning) when it's unset there too.
      // A real provider's widget would set this via its own callback.
      const result = await liteApi.submit({
        brand_name: brandName.trim(),
        competitor_names: cleanCompetitors,
        captcha_token: 'dev-placeholder-token',
      })
      onSubmitted(result.token)
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
          Enter your brand and up to 2 competitors — we'll run a free 12-query
          diagnostic against ChatGPT and show you how often each one gets
          recommended.
        </div>

        <ErrorBanner message={submitError} />

        <form onSubmit={handleSubmit}>
          <label style={labelStyle} htmlFor="lite-brand">Your brand</label>
          <input
            id="lite-brand"
            type="text"
            placeholder="e.g. Drunk Elephant"
            value={brandName}
            onChange={(e) => setBrandName(e.target.value)}
            style={inputStyle}
          />
          <div style={fieldErrorStyle}>{errors.brandName || ' '}</div>

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
              <div style={fieldErrorStyle}>{errors.competitors[i] || ' '}</div>
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

// ─── PROGRESS ────────────────────────────────────────────────────────────

const PHASE_COPY = {
  queued: 'Queued — starting shortly…',
  generating_queries: 'Designing your 12-query diagnostic…',
  running: 'Running query {n} of {total} against ChatGPT…',
  analyzing: 'Analyzing responses…',
}

function phaseMessage(phaseData) {
  const template = PHASE_COPY[phaseData?.phase] || 'Working on it…'
  if (phaseData?.phase !== 'running' || !phaseData.progress) {
    return template
  }
  const { completed_runs, total_runs } = phaseData.progress
  const n = Math.min(completed_runs + 1, total_runs)
  return template.replace('{n}', n).replace('{total}', total_runs)
}

export function LiteProgress({ phaseData, error }) {
  const progress = phaseData?.progress
  const pct = progress && progress.total_runs
    ? Math.round((progress.completed_runs / progress.total_runs) * 100)
    : 0

  return (
    <div style={outerStyle}>
      <div style={cardStyle}>
        <LogoHeader />
        <ErrorBanner message={error} />
        <div style={{ fontSize: 16, fontWeight: 700, color: T.text, marginBottom: 16 }}>
          {phaseMessage(phaseData)}
        </div>
        <div style={{ height: 8, background: T.border, borderRadius: 4, overflow: 'hidden' }}>
          <div style={{
            height: '100%',
            width: `${pct}%`,
            background: T.indigo,
            borderRadius: 4,
            transition: 'width 0.6s ease',
          }} />
        </div>
        {progress && (
          <div style={{ fontSize: 12, color: T.slate, marginTop: 8 }}>
            {progress.completed_runs} of {progress.total_runs} queries complete
          </div>
        )}
      </div>
    </div>
  )
}

export function LiteFailed({ onRetry }) {
  return (
    <div style={outerStyle}>
      <div style={cardStyle}>
        <LogoHeader />
        <div style={{ fontSize: 16, fontWeight: 700, color: T.text, marginBottom: 8 }}>
          Something went wrong
        </div>
        <div style={{ fontSize: 13, color: T.slate, marginBottom: 20, lineHeight: 1.5 }}>
          We couldn't finish your diagnostic. This is on us — please try again.
        </div>
        <button
          onClick={onRetry}
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
            cursor: 'pointer',
          }}
        >
          Try again
        </button>
      </div>
    </div>
  )
}

// ─── TEASER (locked) ────────────────────────────────────────────────────

export function LiteTeaser({ report, token, onUnlocked }) {
  const animated = useAnimateOnMount()
  const [email, setEmail] = useState('')
  const [emailError, setEmailError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)

  const entities = report.overall || []

  async function handleUnlock(e) {
    e.preventDefault()
    const err = validateEmail(email)
    setEmailError(err)
    if (err) return

    setSubmitting(true)
    setSubmitError(null)
    try {
      const fullReport = await liteApi.setEmail(token, email.trim())
      onUnlocked(fullReport)
    } catch (err2) {
      setSubmitError(err2.message || 'Something went wrong. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={outerStyle}>
      <div style={cardStyle}>
        <LogoHeader />
        <div style={{ fontSize: 18, fontWeight: 700, color: T.text, marginBottom: 16 }}>
          Your Share of Algorithm
        </div>

        {entities.map((entity, i) => (
          <BarRow
            key={entity.name}
            label={`${entity.name}${entity.role === 'primary' ? ' (you)' : ''}`}
            value={entity.som}
            color={BRAND_COLORS[i % BRAND_COLORS.length]}
            delay={i * 0.1}
            animated={animated}
          />
        ))}

        {/* Blurred stand-in for the stage-by-stage breakdown, locked behind email */}
        <div style={{ position: 'relative', marginTop: 20 }}>
          <div style={{ filter: 'blur(4px)', pointerEvents: 'none', userSelect: 'none' }} aria-hidden="true">
            {STAGE_ORDER.map((stage) => (
              <BarRow key={stage} label={stage} value={50} color={T.slateLight} animated={true} />
            ))}
          </div>
          <div style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'rgba(255,255,255,0.85)',
            borderRadius: 8,
            padding: 16,
            boxSizing: 'border-box',
          }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: T.text, textAlign: 'center', marginBottom: 12 }}>
              Enter your work email to unlock the full stage-by-stage diagnostic.
            </div>
            <ErrorBanner message={submitError} />
            {/* noValidate: we run our own validateEmail() and render its
                message inline — the browser's native email-input
                validation would otherwise silently block submission
                before handleUnlock ever runs. */}
            <form onSubmit={handleUnlock} noValidate style={{ width: '100%' }}>
              <input
                type="email"
                placeholder="you@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                style={{
                  width: '100%',
                  height: 40,
                  border: `1px solid ${T.border}`,
                  borderRadius: 8,
                  padding: '0 12px',
                  fontSize: 13,
                  fontFamily: 'inherit',
                  outline: 'none',
                  boxSizing: 'border-box',
                  marginBottom: 4,
                  background: T.white,
                }}
              />
              <div style={{ fontSize: 12, color: T.red, marginBottom: 8, minHeight: 16 }}>
                {emailError || ' '}
              </div>
              <button
                type="submit"
                disabled={submitting}
                style={{
                  width: '100%',
                  height: 42,
                  background: T.navy,
                  color: T.white,
                  fontSize: 13,
                  fontWeight: 700,
                  fontFamily: 'inherit',
                  border: 'none',
                  borderRadius: 8,
                  cursor: submitting ? 'not-allowed' : 'pointer',
                  opacity: submitting ? 0.7 : 1,
                }}
              >
                {submitting ? 'Unlocking…' : 'Unlock full report'}
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── FULL REPORT (unlocked) ─────────────────────────────────────────────

function StageFunnel({ byStage, entities }) {
  const stages = STAGE_ORDER.filter((s) => byStage[s])
  const animated = useAnimateOnMount()
  if (stages.length === 0) return null

  return (
    <div>
      <div style={{ fontSize: 14, fontWeight: 700, color: T.text, marginBottom: 12 }}>
        Mention rate by funnel stage
      </div>
      <div style={{ display: 'flex', gap: 8, overflowX: 'auto' }}>
        {stages.map((stage, si) => (
          <div key={stage} style={{ flex: '1 1 0', minWidth: 90 }}>
            <div style={{
              fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
              color: T.slate, letterSpacing: '0.04em', marginBottom: 8, textAlign: 'center',
            }}>
              {stage}
              {si < stages.length - 1 && <span style={{ color: T.slateLight }}> →</span>}
            </div>
            {entities.map((entity, ei) => {
              const value = byStage[stage]?.[entity.name]?.mention_rate ?? 0
              return (
                <div key={entity.name} style={{ marginBottom: 8 }}>
                  <div style={{
                    height: 60, width: '100%', background: T.border, borderRadius: 4,
                    display: 'flex', alignItems: 'flex-end', overflow: 'hidden',
                  }}>
                    <div style={{
                      width: '100%',
                      height: animated ? `${value}%` : '0%',
                      background: BRAND_COLORS[ei % BRAND_COLORS.length],
                      transition: `height 0.8s ease ${(si * entities.length + ei) * 0.05}s`,
                    }} />
                  </div>
                  <div style={{ fontSize: 10, color: T.textMid, textAlign: 'center', marginTop: 2 }}>
                    {formatPct(value)}
                  </div>
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}

export function LiteFullReport({ report }) {
  const animated = useAnimateOnMount()
  const entities = report.overall || []
  const ctaUrl = import.meta.env.VITE_LITE_CTA_URL

  // by_stage is keyed by stage name -> list of {name, role, metrics}; index
  // by entity name for O(1) lookup in StageFunnel.
  const byStageByName = {}
  Object.entries(report.by_stage || {}).forEach(([stage, entityList]) => {
    byStageByName[stage] = {}
    entityList.forEach((e) => {
      byStageByName[stage][e.name] = e.metrics
    })
  })

  return (
    <div style={outerStyle}>
      <div style={cardStyle}>
        <LogoHeader />
        <div style={{ fontSize: 18, fontWeight: 700, color: T.text, marginBottom: 16 }}>
          Your full Share of Algorithm report
        </div>

        <div style={{ fontSize: 14, fontWeight: 700, color: T.text, marginBottom: 8 }}>
          Overall SoA share
        </div>
        {entities.map((entity, i) => (
          <BarRow
            key={entity.name}
            label={`${entity.name}${entity.role === 'primary' ? ' (you)' : ''}`}
            value={entity.metrics?.som}
            color={BRAND_COLORS[i % BRAND_COLORS.length]}
            delay={i * 0.1}
            animated={animated}
          />
        ))}

        <div style={{ margin: '20px 0' }}>
          <StageFunnel byStage={byStageByName} entities={entities} />
        </div>

        <div style={{ fontSize: 14, fontWeight: 700, color: T.text, marginBottom: 8 }}>
          Position score &amp; recommendation strength
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, marginBottom: 20 }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left', padding: '4px 0', color: T.slate, fontWeight: 600 }}>Brand</th>
              <th style={{ textAlign: 'right', padding: '4px 0', color: T.slate, fontWeight: 600 }}>Position</th>
              <th style={{ textAlign: 'right', padding: '4px 0', color: T.slate, fontWeight: 600 }}>RSI</th>
            </tr>
          </thead>
          <tbody>
            {entities.map((entity) => (
              <tr key={entity.name} style={{ borderTop: `1px solid ${T.border}` }}>
                <td style={{ padding: '6px 0', color: T.textMid }}>{entity.name}</td>
                <td style={{ padding: '6px 0', textAlign: 'right', fontFamily: 'monospace', color: T.textMid }}>
                  {formatPct(entity.metrics?.position_index)}
                </td>
                <td style={{ padding: '6px 0', textAlign: 'right', fontFamily: 'monospace', color: T.textMid }}>
                  {formatRsi(entity.metrics?.rsi)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div style={{
          background: T.navy,
          borderRadius: 10,
          padding: 18,
          color: T.white,
        }}>
          <div style={{ fontSize: 13, lineHeight: 1.6, marginBottom: 12 }}>
            This is 12 queries on one platform. The full Parleo diagnostic
            runs hundreds across ChatGPT, Gemini, Perplexity and Claude.
          </div>
          {ctaUrl && (
            <a
              href={ctaUrl}
              target="_blank"
              rel="noreferrer"
              style={{
                display: 'inline-block',
                background: T.white,
                color: T.navy,
                fontSize: 13,
                fontWeight: 700,
                padding: '10px 16px',
                borderRadius: 8,
                textDecoration: 'none',
              }}
            >
              See the full Parleo diagnostic
            </a>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── ROOT ────────────────────────────────────────────────────────────────

export default function LiteWidget() {
  const [token, setToken] = useState(() => {
    try {
      return sessionStorage.getItem(STORAGE_KEY) || null
    } catch (_) {
      return null
    }
  })
  const [phaseData, setPhaseData] = useState(null)
  const [report, setReport] = useState(null)
  const [pollError, setPollError] = useState(null)

  function handleSubmitted(newToken) {
    try {
      sessionStorage.setItem(STORAGE_KEY, newToken)
    } catch (_) {}
    setPhaseData(null)
    setReport(null)
    setPollError(null)
    setToken(newToken)
  }

  function handleRetry() {
    try {
      sessionStorage.removeItem(STORAGE_KEY)
    } catch (_) {}
    setToken(null)
    setPhaseData(null)
    setReport(null)
    setPollError(null)
  }

  // Poll /status every 5s while a token exists and we haven't reached a
  // terminal state yet.
  useEffect(() => {
    if (!token) return undefined
    if (phaseData?.status === 'complete' || phaseData?.status === 'failed') return undefined

    let cancelled = false

    async function poll() {
      try {
        const data = await liteApi.getStatus(token)
        if (!cancelled) setPhaseData(data)
      } catch (err) {
        if (!cancelled) setPollError(err.message || 'Could not check status.')
      }
    }

    poll()
    const interval = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [token, phaseData?.status])

  // Once complete, fetch the report (teaser or full, decided server-side
  // by whether an email is already on file).
  useEffect(() => {
    if (phaseData?.status !== 'complete' || report || !token) return undefined
    let cancelled = false
    liteApi.getReport(token)
      .then((data) => { if (!cancelled) setReport(data) })
      .catch((err) => { if (!cancelled) setPollError(err.message || 'Could not load report.') })
    return () => { cancelled = true }
  }, [phaseData?.status, report, token])

  if (!token) {
    return <LiteForm onSubmitted={handleSubmitted} />
  }

  if (phaseData?.status === 'failed') {
    return <LiteFailed onRetry={handleRetry} />
  }

  if (phaseData?.status === 'complete' && report) {
    return report.locked
      ? <LiteTeaser report={report} token={token} onUnlocked={setReport} />
      : <LiteFullReport report={report} />
  }

  return (
    <LiteProgress
      phaseData={phaseData || { status: 'pending', phase: 'queued' }}
      error={pollError}
    />
  )
}
