/**
 * Full-analysis rail — mirrors ReportRail.jsx's markup/tokens (same
 * score card, pillar dots, nav-row treatment); a sibling rather than a
 * modification for the same reason as FullAnalysisHero.jsx: the shipped
 * rail hardcodes "FREE AGENTIC VALUE AUDIT", a "Run your free audit"
 * CTA, and a fixed lite-only nav id set (buildNavItems/NAV_META) that
 * doesn't include this report's own sections (discovery, matrix,
 * analyst layer, evidence).
 */
import { Wordmark, Glyph, StatusChip, StateChip, BrandLogo } from '../../ds/index.js'
import { pillarEarnedMax, isAgentReady, isPartialRead, buildMeasurableContext, PILLAR_VISIBILITY, PILLAR_ACCESSIBILITY, PILLAR_TRUE_VALUE } from '../../lite/report/reportDerive.js'
import { formatCompactCurrency } from '../../lite/liteDerive.js'

const NAV_ITEMS = [
  { id: 'score', icon: 'chart', label: 'The score' },
  { id: 'continuation', icon: 'refresh', label: 'Vs. your audit' },
  { id: 'discovery', icon: 'search', label: 'Discovery' },
  { id: 'matrix', icon: 'grid', label: 'Platform matrix' },
  { id: 'viz', icon: 'eye', label: 'Visibility' },
  { id: 'transcript', icon: 'doc', label: 'The transcript' },
  { id: 'acc', icon: 'globe', label: 'Accessibility' },
  { id: 'tv', icon: 'tag', label: 'True Value' },
  { id: 'fix', icon: 'check', label: 'Ranked fixes' },
  { id: 'analyst', icon: 'layers', label: 'Analyst layer' },
  { id: 'evidence', icon: 'doc', label: 'Evidence' },
  { id: 'truesync', icon: 'refresh', label: 'TrueSync' },
  { id: 'exp', icon: 'card', label: 'Exposure' },
]

function navScore({ id, pillars, composite, totalQueries, transcript, exposure }) {
  const vis = pillarEarnedMax(pillars.visibility)
  const acc = pillarEarnedMax(pillars.accessibility)
  const tv = pillarEarnedMax(pillars.true_value)
  switch (id) {
    case 'score': return `${Math.round(composite ?? 0)}/100`
    case 'viz': return `${Math.round(vis.earned)}/${Math.round(vis.max)}`
    case 'transcript': return transcript ? `${transcript.query_index}/${transcript.total_queries}` : null
    case 'acc': return `${Math.round(acc.earned)}/${Math.round(acc.max)}`
    case 'tv': return `${Math.round(tv.earned)}/${Math.round(tv.max)}`
    case 'fix': return pillars.fixes ? `+${Math.round(pillars.fixes.visible.reduce((s, f) => s + f.impact, 0))}` : null
    case 'evidence': return totalQueries ? `${totalQueries}` : null
    case 'exp': return exposure == null ? '—' : formatCompactCurrency(exposure)
    default: return null
  }
}

export function FullAnalysisRail({ report, primaryEntityName, exposure, active, hasContinuation, readOnly = false }) {
  const pillars = report.pillars
  const composite = report.composite
  const vis = pillarEarnedMax(pillars.visibility)
  const acc = pillarEarnedMax(pillars.accessibility)
  const tv = pillarEarnedMax(pillars.true_value)
  const readyPct = 60
  // Honesty rail chip (2c): "Fully measured" only when nothing in the
  // payload came back not_measured/partial (isPartialRead/
  // buildMeasurableContext are the same shared source of truth every
  // other surface on this report reads for that) — otherwise states
  // how many points couldn't be read this run, never a silent 100%.
  const partial = isPartialRead(pillars, report.scan?.degraded_reason)
  const unmeasurable = partial ? buildMeasurableContext(pillars).unmeasurable_points : 0

  const items = NAV_ITEMS.filter((item) => item.id !== 'continuation' || hasContinuation)
    .filter((item) => item.id !== 'transcript' || report.transcript)
    // readOnly (public /fa/{token} viewer): FullAnalysisReport.jsx
    // omits <AnalystLayerSection> outright (it fetches the authed
    // /api/cycles/{code}/metrics directly — the one section with no
    // public equivalent), so its nav entry would otherwise jump to an
    // anchor that no longer exists.
    .filter((item) => item.id !== 'analyst' || !readOnly)

  return (
    <div className="fa-report-rail" style={{ borderRight: '1px solid var(--border)', background: 'var(--canvas-dim)' }}>
      <div style={{ position: 'sticky', top: 0, height: '100vh', overflowY: 'auto', overflowX: 'hidden', padding: '22px 18px 20px', display: 'flex', flexDirection: 'column', gap: 18 }}>
        <div>
          <Wordmark size={13} />
          <div className="mono-label" style={{ fontSize: 9.5, color: 'var(--faint)', marginTop: 9 }}>FULL AGENTIC VALUE ANALYSIS</div>
        </div>

        <div style={{ background: 'var(--surface)', borderRadius: 12, boxShadow: 'var(--shadow-card)', padding: '15px 16px 16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
            <BrandLogo name={primaryEntityName} src={report.brand_icon_url} domain={report.store_domain} size={38} />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 16.5, fontWeight: 660, color: 'var(--text-strong)', letterSpacing: '-0.012em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{primaryEntityName}</div>
            </div>
          </div>
          <div style={{ marginTop: 16 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 5 }}>
              <span className="num" style={{ fontSize: 44, fontWeight: 750, letterSpacing: '-0.042em', lineHeight: 0.9, color: 'var(--text-strong)' }}>
                {composite != null ? Math.round(composite) : '—'}
              </span>
              <span className="num" style={{ fontSize: 16, fontWeight: 560, color: 'var(--faint)' }}>/100</span>
            </div>
            <div style={{ marginTop: 16 }}>
              <div style={{ position: 'relative', height: 11, borderRadius: 5.5, background: 'var(--canvas-dim)', boxShadow: 'inset 0 1px 2px rgba(70,69,85,.16),inset 0 0 0 1px rgba(213,209,203,.95)' }}>
                <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${Math.min(100, composite ?? 0)}%`, borderRadius: 5.5, background: 'var(--ink)' }} />
                <span aria-hidden="true" style={{ position: 'absolute', left: `${readyPct}%`, top: -2, bottom: -2, width: 3, transform: 'translateX(-3px)', borderRadius: 2, background: 'var(--blue)' }} />
              </div>
              <div style={{ position: 'relative', height: 14, marginTop: 7 }}>
                <span className="mono-label" style={{ position: 'absolute', left: 0, top: 0, fontSize: 9, color: 'var(--text-strong)', fontWeight: 600 }}>
                  {composite != null ? Math.round(composite) : '—'} EARNED
                </span>
                <span className="mono-label" style={{ position: 'absolute', left: `${readyPct}%`, top: 0, transform: 'translateX(-50%)', fontSize: 9, color: 'var(--muted)', whiteSpace: 'nowrap' }}>READY 60</span>
                <span className="mono-label" style={{ position: 'absolute', right: 0, top: 0, fontSize: 9, color: 'var(--faint)' }}>100</span>
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><i style={{ width: 9, height: 9, borderRadius: 2.5, background: 'var(--ink)', flexShrink: 0 }} /><span style={{ flex: 1, fontSize: 11.5, color: 'var(--muted)' }}>Visibility</span><span className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--text-strong)' }}>{Math.round(vis.earned)}/{Math.round(vis.max)}</span></div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><i style={{ width: 9, height: 9, borderRadius: 2.5, background: 'rgba(30,30,46,.45)', flexShrink: 0 }} /><span style={{ flex: 1, fontSize: 11.5, color: 'var(--muted)' }}>Accessibility</span><span className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--text-strong)' }}>{Math.round(acc.earned)}/{Math.round(acc.max)}</span></div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><i style={{ width: 9, height: 9, borderRadius: 2.5, background: 'var(--blue)', flexShrink: 0 }} /><span style={{ flex: 1, fontSize: 11.5, color: 'var(--blue)', fontWeight: 560 }}>True Value</span><span className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--blue)', fontWeight: 640 }}>{Math.round(tv.earned)}/{Math.round(tv.max)}</span></div>
            </div>
          </div>
          <div style={{ display: 'flex', justifyContent: 'center', marginTop: 14 }}>
            <StatusChip tone={isAgentReady(pillars) ? 'success' : 'risk'} size="sm">{isAgentReady(pillars) ? 'Agent-ready' : 'Not agent-ready'}</StatusChip>
          </div>
          <div style={{ display: 'flex', justifyContent: 'center', marginTop: 10 }}>
            {partial ? (
              <StateChip state="partial" variant="chip" size="sm">{Math.round(unmeasurable)} pts unread this run</StateChip>
            ) : (
              <StateChip state="seen" variant="chip" size="sm">Fully measured</StateChip>
            )}
          </div>
        </div>

        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '0 4px 9px' }}>
            <span className="mono-label" style={{ fontSize: 9.5, color: 'var(--faint)' }}>IN THIS REPORT</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {items.map(({ id, icon, label }) => {
              const on = active === id
              const score = navScore({ id, pillars, composite, totalQueries: report.total_queries, transcript: report.transcript, exposure })
              return (
                <a
                  key={id}
                  href={`#${id}`}
                  style={{
                    display: 'flex', alignItems: 'baseline', gap: 9, padding: '8px 10px', borderRadius: 8,
                    background: on ? 'var(--surface)' : 'transparent', textDecoration: 'none',
                  }}
                >
                  <Glyph name={icon} size={14} color={on ? 'var(--blue)' : 'var(--faint)'} />
                  <span style={{ flex: 1, fontSize: 13.5, fontWeight: on ? 620 : 500, color: on ? 'var(--text-strong)' : 'var(--text)', letterSpacing: '-0.008em' }}>{label}</span>
                  {score != null && <span className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: on ? 'var(--text)' : 'var(--faint)' }}>{score}</span>}
                </a>
              )
            })}
          </div>
        </div>

        <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div className="mono-label" style={{ fontSize: 9, color: 'var(--faint)', lineHeight: 1.8, paddingTop: 12, borderTop: '1px solid var(--hairline)' }}>
            {report.total_queries} QUERIES MEASURED<br />+ FULL SITE CRAWL
          </div>
        </div>
      </div>
    </div>
  )
}
