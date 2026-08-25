/**
 * Discovery section — positive framing ("this time, everything opened"),
 * distinct from lite's DiscoveryFinding.jsx which only ever renders the
 * FAILURE framing for a partial/degraded lite crawl (it's gated on
 * isPartialRead and never fires for a successful run at all). Reuses
 * ReportSection's shared card chrome and the same step-card markup/
 * tokens DiscoveryFinding.jsx uses, fed from buildDiscoverySteps
 * (fullAnalysisDerive.js) over the SAME scan.discovery_trace/
 * pages_fetched shape build_scan_payload always writes.
 */
import { Glyph } from '../../ds/index.js'
import { ReportSection } from '../../lite/report/ReportSection.jsx'
import { buildDiscoverySteps } from './fullAnalysisDerive.js'
import { NAV_IDS } from './fullAnalysisNav.js'

export function DiscoverySection({ scan, open, onToggle }) {
  const steps = buildDiscoverySteps(scan)
  if (steps.length === 0) return null
  const allGood = steps.every((s) => s.good)

  return (
    <ReportSection
      id={NAV_IDS.DISCOVERY} eyebrow="FINDING 00 · DISCOVERY · MEASURED"
      title={allGood ? 'This time, everything opened' : 'What this run could reach'}
      open={open} onToggle={onToggle} accentColor={allGood ? 'var(--green)' : 'var(--amber)'}
    >
      <div className="fa-discovery-steps" style={{ display: 'grid', gridTemplateColumns: `repeat(${steps.length},1fr)`, gap: 14, marginTop: 20 }}>
        {steps.map((s) => (
          <div key={s.key} style={{ background: 'var(--surface-warm)', border: `1px solid ${s.good ? '#CDE4D6' : 'var(--hairline)'}`, borderRadius: 12, padding: '14px 15px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <Glyph name={s.good ? 'check' : 'x'} size={13} color={s.good ? 'var(--green)' : 'var(--red-deep)'} />
              <span className="mono-label" style={{ fontSize: 9, color: 'var(--faint)' }}>{s.n} · {s.label}</span>
            </div>
            <div style={{ fontSize: 12.5, color: 'var(--text)', marginTop: 8, lineHeight: 1.5 }}>{s.fact}</div>
          </div>
        ))}
      </div>
      {allGood && (
        <div style={{ marginTop: 22, padding: '15px 17px', background: 'var(--surface-warm)', border: '1px solid var(--hairline)', borderRadius: 12, fontSize: 13.5, color: 'var(--muted)', lineHeight: 1.6 }}>
          Every scored claim below rests on pages this run actually parsed and answers it actually coded.
        </div>
      )}
    </ReportSection>
  )
}
