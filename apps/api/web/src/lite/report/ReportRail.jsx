import { Wordmark, Glyph, StatusChip, Button, BrandLogo } from '../../ds/index.js'
import { NAV_IDS } from './useReportSections.js'
import { pillarEarnedMax, isAgentReady } from './reportDerive.js'
import { LITE_QUERY_COUNT } from '../landing/scanDimensionsRegistry.js'

const NAV_META = {
  score: { icon: 'chart', label: 'Score' },
  viz: { icon: 'eye', label: 'Visibility' },
  acc: { icon: 'globe', label: 'Accessibility' },
  tv: { icon: 'tag', label: 'True Value' },
  fix: { icon: 'check', label: 'Ranked fixes' },
  truesync: { icon: 'refresh', label: 'The fix' },
  exp: { icon: 'card', label: 'Exposure' },
}

function kLabel(n) {
  if (n == null) return '—'
  return n >= 1e6 ? `$${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M` : `$${Math.round(n / 1e3)}K`
}

export function ReportRail({ report, primaryEntityName, exposure, active, focus, allLabel, onToggleAll }) {
  const pillars = report.pillars
  const composite = report.composite
  const vis = pillarEarnedMax(pillars.visibility)
  const acc = pillarEarnedMax(pillars.accessibility)
  const tv = pillarEarnedMax(pillars.true_value)
  const readyPct = 60

  const navItems = NAV_IDS.filter((id) => id !== 'fun').map((id) => {
    if (!(id in NAV_META)) return null
    const on = active === id
    const meta = NAV_META[id]
    let score = null
    if (id === 'score') score = `${Math.round(composite ?? 0)}/100`
    else if (id === 'viz') score = `${Math.round(vis.earned)}/${Math.round(vis.max)}`
    else if (id === 'acc') score = `${Math.round(acc.earned)}/${Math.round(acc.max)}`
    else if (id === 'tv') score = `${Math.round(tv.earned)}/${Math.round(tv.max)}`
    else if (id === 'fix') score = `+${Math.round(vis.max - vis.earned + acc.max - acc.earned + tv.max - tv.earned > 0 ? Math.min(20, vis.max - vis.earned + acc.max - acc.earned + tv.max - tv.earned) : 0)}`
    else if (id === 'truesync') score = 'TrueSync'
    else if (id === 'exp') score = kLabel(exposure)
    return { id, on, meta, score }
  }).filter(Boolean)

  return (
    <div style={{ borderRight: '1px solid var(--border)', background: 'var(--canvas-dim)' }}>
      <div style={{ position: 'sticky', top: 0, height: '100vh', overflowY: 'auto', overflowX: 'hidden', padding: '22px 18px 20px', display: 'flex', flexDirection: 'column', gap: 18 }}>
        <div>
          <Wordmark size={13} />
          <div className="mono-label" style={{ fontSize: 9.5, color: 'var(--faint)', marginTop: 9 }}>FREE AGENTIC VALUE AUDIT</div>
        </div>

        <div style={{ background: 'var(--surface)', borderRadius: 12, boxShadow: 'var(--shadow-card)', padding: '15px 16px 16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
            <BrandLogo name={primaryEntityName} size={38} />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 16.5, fontWeight: 660, color: 'var(--text-strong)', letterSpacing: '-0.012em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{primaryEntityName}</div>
            </div>
          </div>
          <div style={{ marginTop: 16 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 5 }}>
              <span className="num" style={{ fontSize: 44, fontWeight: 750, letterSpacing: '-0.042em', lineHeight: 0.9, color: 'var(--text-strong)' }}>{composite != null ? Math.round(composite) : '—'}</span>
              <span className="num" style={{ fontSize: 16, fontWeight: 560, color: 'var(--faint)' }}>/100</span>
            </div>
            <div style={{ marginTop: 16 }}>
              <div style={{ position: 'relative', height: 11, borderRadius: 5.5, background: 'var(--canvas-dim)', boxShadow: 'inset 0 1px 2px rgba(70,69,85,.16),inset 0 0 0 1px rgba(213,209,203,.95)' }}>
                <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${Math.min(100, composite ?? 0)}%`, borderRadius: 5.5, background: 'var(--ink)' }} />
                <span aria-hidden="true" style={{ position: 'absolute', left: `${readyPct}%`, top: -2, bottom: -2, width: 3, transform: 'translateX(-3px)', borderRadius: 2, background: 'var(--blue)' }} />
              </div>
              <div style={{ position: 'relative', height: 14, marginTop: 7 }}>
                <span className="mono-label" style={{ position: 'absolute', left: 0, top: 0, fontSize: 9, color: 'var(--text-strong)', fontWeight: 600 }}>{composite != null ? Math.round(composite) : '—'} EARNED</span>
                <span className="mono-label" style={{ position: 'absolute', left: `${readyPct}%`, top: 0, transform: 'translateX(-50%)', fontSize: 9, color: 'var(--muted)', whiteSpace: 'nowrap' }}>READY {readyPct}</span>
                <span className="mono-label" style={{ position: 'absolute', right: 0, top: 0, fontSize: 9, color: 'var(--faint)' }}>100</span>
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><i style={{ width: 9, height: 9, borderRadius: 2.5, background: 'var(--ink)', flexShrink: 0 }} /><span style={{ flex: 1, fontSize: 11.5, color: 'var(--muted)' }}>Visibility</span><span className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--text-strong)' }}>{Math.round(vis.earned)}/{Math.round(vis.max)}</span></div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><i style={{ width: 9, height: 9, borderRadius: 2.5, background: 'rgba(30,30,46,.45)', flexShrink: 0 }} /><span style={{ flex: 1, fontSize: 11.5, color: 'var(--muted)' }}>Accessibility</span><span className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--text-strong)' }}>{Math.round(acc.earned)}/{Math.round(acc.max)}</span></div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><i style={{ width: 9, height: 9, borderRadius: 2.5, background: 'var(--blue)', flexShrink: 0 }} /><span style={{ flex: 1, fontSize: 11.5, color: 'var(--blue)', fontWeight: 560 }}>True Value</span><span className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--blue)', fontWeight: 640 }}>{Math.round(tv.earned)}/{Math.round(tv.max)}</span></div>
            </div>
          </div>
          {pillars.state === 'scored' && (
            <div style={{ display: 'flex', justifyContent: 'center', marginTop: 14 }}>
              <StatusChip tone={isAgentReady(pillars) ? 'success' : 'risk'} size="sm">{isAgentReady(pillars) ? 'Agent-ready' : 'Not agent-ready'}</StatusChip>
            </div>
          )}
        </div>

        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '0 4px 9px' }}>
            <span className="mono-label" style={{ fontSize: 9.5, color: 'var(--faint)' }}>IN THIS REPORT</span>
            <button
              type="button"
              onClick={onToggleAll}
              style={{ marginLeft: 'auto', background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: 8.5, letterSpacing: '.06em', fontWeight: 640, color: 'var(--blue)', textTransform: 'uppercase', whiteSpace: 'nowrap' }}
            >
              {allLabel}
            </button>
          </div>
          {focus && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, margin: '0 4px 10px', background: 'var(--blue-tint)', border: '1px solid rgba(1,102,255,.2)', borderRadius: 8, padding: '7px 9px' }}>
              <Glyph name="eye" size={12} color="var(--blue)" />
              <span className="mono-label" style={{ fontSize: 8, color: 'var(--blue)', lineHeight: 1.5 }}>FOCUS MODE · SECTIONS OPEN AS YOU SCROLL</span>
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {navItems.map(({ id, on, meta, score }) => (
              <a
                key={id}
                href={`#${id}`}
                style={{
                  display: 'flex', alignItems: 'baseline', gap: 9, padding: '8px 10px', borderRadius: 8,
                  background: on ? 'var(--surface)' : 'transparent', textDecoration: 'none',
                }}
              >
                <Glyph name={meta.icon} size={14} color={on ? 'var(--blue)' : 'var(--faint)'} />
                <span style={{ flex: 1, fontSize: 13.5, fontWeight: on ? 620 : 500, color: on ? 'var(--text-strong)' : 'var(--text)', letterSpacing: '-0.008em' }}>{meta.label}</span>
                <span className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: on ? 'var(--text)' : 'var(--faint)' }}>{score}</span>
              </a>
            ))}
          </div>
        </div>

        <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <a href="#run" style={{ textDecoration: 'none' }}>
            <Button variant="blue" size="sm" arrow style={{ width: '100%', justifyContent: 'center' }}>Run your free audit</Button>
          </a>
          <div className="mono-label" style={{ fontSize: 9, color: 'var(--faint)', lineHeight: 1.8, paddingTop: 12, borderTop: '1px solid var(--hairline)' }}>
            {LITE_QUERY_COUNT} LIVE CHATGPT QUERIES<br />+ FULL SITE CRAWL
          </div>
        </div>
      </div>
    </div>
  )
}
