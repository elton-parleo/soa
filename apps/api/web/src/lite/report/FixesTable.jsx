/**
 * S6: ranked fixes. Reads report.pillars.fixes (F1's top-2 + remaining
 * count) — the mock's per-fix dollar "EXPOSURE" column is dropped: this
 * report has no real per-action exposure split, only the run's single
 * modeled total (S7's Exposure section), and fabricating one per row
 * would violate the no-fabrication rule. Owner tag comes straight from
 * F3's registry-driven fix_owner, never a literal.
 */
import { Button, ProvenanceLine, StatusChip } from '../../ds/index.js'
import { ReportSection } from './ReportSection.jsx'
import { WALKTHROUGH_URL } from './reportContent.js'

const RANK_LABELS = ['01', '02', '03', '04', '05', '06', '07', '08']

export function FixesTable({ report, open, onToggle }) {
  const fixes = report.pillars.fixes
  if (!fixes) return null
  const visible = fixes.visible || []
  const maxImpact = Math.max(1, ...visible.map((f) => f.impact))

  return (
    <ReportSection
      id="fix" eyebrow="RANKED FIXES · BY MODELED IMPACT"
      title={`${visible.length ? visible.length : 'No'} move${visible.length === 1 ? '' : 's'} recover up to ${Math.round(visible.reduce((s, f) => s + f.impact, 0))} points`}
      extra={<StatusChip tone="info" dot={false} size="sm">Modeled impact</StatusChip>}
      open={open} onToggle={onToggle}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 20 }}>
        {visible.length > 0 && (
          <div className="lite-fixrow-header" style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '0 2px 2px' }}>
            <span className="mono-label" style={{ fontSize: 9, color: 'var(--faint)', flex: 1 }}>THE MOVE</span>
            <span className="mono-label" style={{ fontSize: 9, color: 'var(--faint)', width: 190 }}>POINTS RECOVERED</span>
            <span className="mono-label" style={{ fontSize: 9, color: 'var(--faint)', width: 64, textAlign: 'right' }}>OWNER</span>
          </div>
        )}
        {visible.map((f, i) => {
          const isTrueSync = f.fix_owner === 'TRUESYNC'
          return (
            <div key={f.code} className="lite-fixrow" style={{ display: 'flex', alignItems: 'center', gap: 12, background: 'var(--surface-warm)', border: `1px solid ${isTrueSync ? 'rgba(1,102,255,.32)' : 'var(--hairline)'}`, borderRadius: 12, padding: '14px 16px' }}>
              <span className="num" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 26, height: 26, flexShrink: 0, borderRadius: 9, background: isTrueSync ? 'var(--blue)' : 'var(--canvas-dim)', color: isTrueSync ? '#fff' : 'var(--muted)', fontSize: 11.5, fontWeight: 660 }}>{RANK_LABELS[i] || i + 1}</span>
              <div className="lite-fixrow-title" style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 620, color: 'var(--text-strong)', letterSpacing: '-0.01em' }}>{f.name}</div>
                <div style={{ fontSize: 12.5, color: 'var(--muted)', marginTop: 3, lineHeight: 1.5 }}>{f.fix_human}</div>
              </div>
              <div className="lite-fixrow-points" style={{ width: 190, flexShrink: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{ flex: 1, position: 'relative', height: 10, borderRadius: 5, background: 'var(--canvas-dim)', overflow: 'hidden' }}>
                  <i style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${(f.impact / maxImpact) * 100}%`, background: isTrueSync ? 'var(--blue)' : 'var(--ink)', borderRadius: 5 }} />
                </div>
                <span className="num" style={{ fontSize: 13, fontWeight: 680, color: isTrueSync ? 'var(--blue)' : 'var(--ink)', whiteSpace: 'nowrap' }}>+{f.impact} pts</span>
              </div>
              <span className="mono-label lite-fixrow-owner" style={{ width: 64, flexShrink: 0, textAlign: 'right', fontSize: 9, color: isTrueSync ? 'var(--blue)' : 'var(--faint)' }}>{f.fix_owner}</span>
            </div>
          )
        })}
      </div>

      {fixes.remaining_count > 0 && (
        <div style={{ marginTop: 16, borderRadius: 14, background: 'var(--surface-warm)', border: '1px dashed var(--border-strong)', padding: '18px 20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <span className="mono-label" style={{ fontSize: 9, color: 'var(--faint)' }}>{fixes.remaining_count} MORE FIXES IDENTIFIED, NOT RANKED IN THIS SAMPLE</span>
            <span className="mono-label" style={{ fontSize: 9, letterSpacing: '.18em', fontWeight: 600, color: 'var(--amber-deep)', border: '1.5px solid var(--amber)', borderRadius: 999, padding: '5px 13px 4px', background: 'rgba(255,255,255,.94)', whiteSpace: 'nowrap' }}>RANKED IN THE FULL ANALYSIS</span>
          </div>
          <div style={{ marginTop: 18, display: 'flex', justifyContent: 'space-between', gap: 22, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.6, maxWidth: 430 }}>Ranked across your full catalog instead of a 24-query sample, each with the owner and the effort it takes.</span>
            <a href={WALKTHROUGH_URL} style={{ textDecoration: 'none', flexShrink: 0 }}>
              <Button variant="blue" arrow>Book your walkthrough</Button>
            </a>
          </div>
        </div>
      )}

      <div style={{ marginTop: 16, paddingTop: 14, borderTop: '1px solid var(--hairline)' }}>
        <ProvenanceLine confidence="modeled" parts={['Action-level estimates', 'exposure shares are modeled, not measured']} />
      </div>
    </ReportSection>
  )
}
