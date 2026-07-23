/**
 * Locked teaser: composite score, visibility + accessibility dials
 * (accessibility dims with an honest badge until the scan completes),
 * a rival share-of-voice bar (the pre-Stage-4 teaser content, reused
 * as-is), and one verbatim worst-answer excerpt when the API provides
 * one. worst_mention_excerpt is a forward-looking, optional field — no
 * backend stage emits it yet, so it's read defensively and simply
 * omitted when absent, same as every other additive field here.
 * Everything below the fold stays blurred behind the existing email
 * gate (PATCH /email) — that mechanic is unchanged.
 */
import { useState } from 'react'
import { liteApi } from './liteApi.js'
import { validateEmail } from './validation.js'
import { accessibilityBadgeText } from './liteDerive.js'
import {
  T, BRAND_COLORS, STAGE_ORDER, outerStyle, cardStyle, LogoHeader, ErrorBanner,
  BarRow, ScoreDial, useAnimateOnMount,
} from './liteTheme.jsx'

function WorstAnswer({ excerpt }) {
  if (!excerpt || !excerpt.text) return null
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: T.slate, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 8 }}>
        A real agent answer
      </div>
      <div style={{
        background: T.offWhite, border: `1px solid ${T.border}`, borderRadius: 8,
        padding: '12px 14px', fontSize: 13, color: T.textMid, lineHeight: 1.6, fontStyle: 'italic',
      }}>
        "{excerpt.text}"
      </div>
      {(excerpt.platform || excerpt.stage) && (
        <div style={{ fontSize: 11, color: T.slateLight, marginTop: 6 }}>
          {[excerpt.platform, excerpt.stage].filter(Boolean).join(' · ')}
        </div>
      )}
    </div>
  )
}

export function LiteTeaser({ report, token, onUnlocked }) {
  const animated = useAnimateOnMount()
  const [email, setEmail] = useState('')
  const [emailError, setEmailError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)

  const entities = report.overall || []
  const accessBadge = accessibilityBadgeText(report.scan_status)

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
        <div style={{ fontSize: 18, fontWeight: 700, color: T.text, marginBottom: 4 }}>
          Your Share of Algorithm
        </div>
        <div style={{ fontSize: 12, color: T.slate, marginBottom: 20 }}>
          Composite score
          <span style={{ fontSize: 28, fontWeight: 700, color: T.text, marginLeft: 8, fontFamily: 'monospace' }}>
            {report.composite === null || report.composite === undefined ? '—' : Math.round(report.composite)}
          </span>
        </div>

        <div style={{ display: 'flex', justifyContent: 'center', gap: 28, marginBottom: 24 }}>
          <ScoreDial label="Visibility" value={report.visibility} color={T.indigo} />
          <ScoreDial
            label="Accessibility"
            value={report.accessibility}
            color={T.green}
            dimmed={!!accessBadge}
            badge={accessBadge}
          />
        </div>

        <WorstAnswer excerpt={report.worst_mention_excerpt} />

        <div style={{ fontSize: 13, fontWeight: 700, color: T.text, marginBottom: 8 }}>
          Rival share of voice
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
                {emailError || ' '}
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
