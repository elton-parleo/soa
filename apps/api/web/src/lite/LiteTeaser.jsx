/**
 * Locked teaser: the dark "agent commerce score" hero card (screenshot
 * 1 — composite numeral, band pill, verdict, Score-by-family bars, band
 * scale), a rival share-of-mentions card, and a verbatim worst-answer
 * excerpt when the API provides one (worst_mention_excerpt is a
 * forward-looking, optional field — no backend stage emits it yet, so
 * it's read defensively and simply omitted when absent, same as every
 * other additive field here). Email gate is the dark band from
 * screenshot 6, replacing Stage 4's blur-overlay treatment — same
 * placement (still gates the teaser), same PATCH /email flow, restyled.
 *
 * Stage 13 (W4/W5): RivalShareOfVoice degrades honestly when
 * report.competitor_source is 'none' (solo run — no fake single-bar
 * comparison) and discloses "auto-selected by ChatGPT" when it's
 * 'generated'/'mixed'.
 */
import { useState } from 'react'
import { liteApi } from './liteApi.js'
import { validateEmail } from './validation.js'
import { accessibilityBadgeText, getScoreBand, getVerdictLine } from './liteDerive.js'
import {
  ENTITY_COLORS, LightCard, DarkCard, BandPill, BandScale, FamilyBar, ErrorBanner, Chip,
} from './liteTheme.jsx'

function WorstAnswer({ excerpt }) {
  if (!excerpt || !excerpt.text) return null
  return (
    <div style={{ marginBottom: 24 }}>
      <div className="lite-label" style={{ marginBottom: 10 }}>A real agent answer</div>
      <div style={{ fontSize: 15, lineHeight: 1.6, color: 'var(--text)', marginBottom: 8 }}>
        "{excerpt.text}"
      </div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        {excerpt.annotation && <Chip tone="bad">{excerpt.annotation}</Chip>}
        {(excerpt.platform || excerpt.stage) && (
          <span className="lite-mono lite-muted" style={{ fontSize: 11 }}>
            {[excerpt.platform, excerpt.stage].filter(Boolean).join(' · ').toUpperCase()}
          </span>
        )}
      </div>
    </div>
  )
}

// Stage 13 (W4/W5): competitor_source === 'none' means a solo run — no
// fake single-bar "comparison"; drops straight to the same quiet note
// used in the full report. 'generated'/'mixed' get the provenance line
// since the tool chose who's being publicly compared here.
function RivalShareOfVoice({ entities, competitorSource }) {
  if (competitorSource === 'none') {
    return (
      <div>
        <div className="lite-label" style={{ marginBottom: 12 }}>Rival share of mentions</div>
        <div className="lite-body lite-muted">Competitor comparison unavailable for this run.</div>
      </div>
    )
  }
  const isAutoSelected = competitorSource === 'generated' || competitorSource === 'mixed'
  return (
    <div>
      <div className="lite-label" style={{ marginBottom: 12 }}>Rival share of mentions</div>
      {isAutoSelected && (
        <div className="lite-mono lite-muted" style={{ fontSize: 11, marginBottom: 10 }}>
          Competitors auto-selected by ChatGPT
        </div>
      )}
      {entities.map((entity, i) => (
        <div key={entity.name} style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 12, fontWeight: 600 }}>
            <span>{entity.name}{entity.role === 'primary' ? ' (you)' : ''}</span>
            <span className="lite-mono">{entity.som === null || entity.som === undefined ? '—' : `${entity.som.toFixed(1)}%`}</span>
          </div>
          <div className="lite-bar-track">
            <div className="lite-bar-fill" style={{
              width: `${Math.max(0, Math.min(100, entity.som || 0))}%`,
              background: ENTITY_COLORS[i % ENTITY_COLORS.length],
            }} />
          </div>
        </div>
      ))}
    </div>
  )
}

export function LiteTeaser({ report, token, onUnlocked }) {
  const [email, setEmail] = useState('')
  const [emailError, setEmailError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)

  const entities = report.overall || []
  const accessBadge = accessibilityBadgeText(report.scan_status)
  const band = getScoreBand(report.composite)
  const verdict = getVerdictLine(report)
  // Stage 19 (R6): the teaser has no scan/pillars object to detect this
  // from itself — scorer_version is its only signal. composite/visibility/
  // accessibility are already correct either way (see public_lite.py's
  // version branch); this is purely the same disclosure the full report
  // gives, so a visitor isn't left assuming the current methodology scored
  // an old row.
  const scoredUnderPreviousMethodology = report.scan_status === 'complete' && report.scorer_version !== '3'

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
    <div className="lite-root">
      <div className="lite-shell" style={{ maxWidth: 640 }}>
        <DarkCard>
          <div className="lite-cols-2">
            <div>
              <div className="lite-label lite-label--inv">Agent commerce score</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 6 }}>
                <span className="lite-numeral lite-numeral--inv lite-numeral--hero">
                  {report.composite === null || report.composite === undefined ? '—' : Math.round(report.composite)}
                </span>
                <span className="lite-muted--inv" style={{ fontSize: 18 }}>/100</span>
              </div>
              <div style={{ margin: '10px 0 14px' }}>
                <BandPill band={band} />
              </div>
              <div className="lite-body--inv" style={{ maxWidth: 320 }}>{verdict}</div>
              {scoredUnderPreviousMethodology && (
                <div className="lite-mono lite-muted--inv" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '0.04em', marginTop: 10 }}>
                  SCORED UNDER A PREVIOUS METHODOLOGY
                </div>
              )}
            </div>
            <div>
              <div className="lite-label lite-label--inv" style={{ marginBottom: 16 }}>
                Score by family
              </div>
              <FamilyBar label="Visibility" value={report.visibility} color="var(--accent)" />
              <FamilyBar
                label="Accessibility"
                value={report.accessibility}
                color="var(--foundation-on-dark)"
                badge={accessBadge}
              />
            </div>
          </div>
          <BandScale score={report.composite} />
        </DarkCard>

        <LightCard>
          <WorstAnswer excerpt={report.worst_mention_excerpt} />
          <RivalShareOfVoice entities={entities} competitorSource={report.competitor_source} />
        </LightCard>

        <DarkCard>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24, alignItems: 'flex-start', justifyContent: 'space-between' }}>
            <div style={{ maxWidth: 320 }}>
              <div className="lite-headline lite-headline--inv" style={{ fontSize: 19, marginBottom: 8 }}>
                Want the full report?
              </div>
              <div className="lite-body--inv">
                Get your private report link sent to your inbox, with a monthly re-run included.
              </div>
            </div>
            <div style={{ flex: '1 1 260px', minWidth: 240 }}>
              <ErrorBanner message={submitError} />
              {/* noValidate: we run our own validateEmail() and render its
                  message inline — the browser's native email-input
                  validation would otherwise silently block submission
                  before handleUnlock ever runs. */}
              <form onSubmit={handleUnlock} noValidate>
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                  <input
                    type="email"
                    placeholder="you@company.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="lite-input lite-input--pill lite-input--inv lite-mono"
                    style={{ flex: '1 1 200px' }}
                  />
                  <button type="submit" disabled={submitting} className="lite-pill lite-pill--solid">
                    {submitting ? 'Unlocking…' : 'Unlock the full report'}
                  </button>
                </div>
                <div className="lite-muted--inv" style={{ fontSize: 12, marginTop: 8, minHeight: 16 }}>
                  {emailError || 'One email. No sequence unless you ask for one.'}
                </div>
              </form>
            </div>
          </div>
        </DarkCard>
      </div>
    </div>
  )
}
