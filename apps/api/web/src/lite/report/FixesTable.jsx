/**
 * S6: ranked fixes. Reads report.pillars.fixes (F1's top-2 + remaining
 * count) — the mock's per-fix dollar "EXPOSURE" column is dropped: this
 * report has no real per-action exposure split, only the run's single
 * modeled total (S7's Exposure section), and fabricating one per row
 * would violate the no-fabrication rule. Owner tag comes straight from
 * F3's registry-driven fix_owner, never a literal.
 */
import { Button, ProvenanceLine, RequestFormModal, StatusChip } from '../../ds/index.js'
import { ReportSection } from './ReportSection.jsx'
import { FAILURE_POINT_COPY } from './reportContent.js'
import { isPartialRead, buildMeasurableContext, partialReadFailurePoint } from './reportDerive.js'
import { DEMO_REQUEST_CTAS } from '../demoRequestCtas.js'
import { useDemoRequestModal } from '../useDemoRequestModal.js'

const RANK_LABELS = ['01', '02', '03', '04', '05', '06', '07', '08']

// Part 5a: the discovery/access fix — whichever ranked row is about
// getting product pages discoverable at all — moves to rank 1 in a
// partial-read run and carries the run's unmeasurable_points as a
// separate "+N UNLOCKED" badge. The badge is rendering only: it never
// touches impact, maxImpact, or the title's point total, so it can
// never be summed into a real total (test-asserted).
const DISCOVERY_FIX_CODES = ['agent_access', 'catalog_context']

function _withDiscoveryFirst(visible) {
  const idx = visible.findIndex((f) => DISCOVERY_FIX_CODES.includes(f.code))
  if (idx <= 0) return { ordered: visible, discoveryCode: idx === 0 ? visible[0].code : null }
  const ordered = [visible[idx], ...visible.slice(0, idx), ...visible.slice(idx + 1)]
  return { ordered, discoveryCode: visible[idx].code }
}

export function FixesTable({ report, open, onToggle, brandName, reportToken }) {
  const demoModal = useDemoRequestModal({ brandName, reportToken })
  const fixes = report.pillars.fixes
  if (!fixes) return null
  const partialRead = isPartialRead(report.pillars, report.scan?.degraded_reason)
  const failurePoint = partialRead ? partialReadFailurePoint(report.scan?.degraded_reason) : null
  const rawVisible = fixes.visible || []
  const { ordered, discoveryCode } = partialRead ? _withDiscoveryFirst(rawVisible) : { ordered: rawVisible, discoveryCode: null }
  const visible = ordered
  const unlockedPoints = partialRead ? buildMeasurableContext(report.pillars).unmeasurable_points : 0
  const maxImpact = Math.max(1, ...visible.map((f) => f.impact))

  return (
    <>
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
          // Blocked-run copy pass (1c): the discovery fix's description
          // becomes the registry's plain-language action line instead
          // of the backend's generic ENG fix text, for the blocked
          // failure point only — registry-sourced, never inlined here.
          const isDiscoveryRow = f.code === discoveryCode
          const fixHuman = (isDiscoveryRow && failurePoint === 'blocked') ? FAILURE_POINT_COPY.blocked.fixFraming : f.fix_human
          return (
            <div key={f.code} className="lite-fixrow" style={{ display: 'flex', alignItems: 'center', gap: 12, background: 'var(--surface-warm)', border: `1px solid ${isTrueSync ? 'rgba(1,102,255,.32)' : 'var(--hairline)'}`, borderRadius: 12, padding: '14px 16px' }}>
              <span className="num" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 26, height: 26, flexShrink: 0, borderRadius: 9, background: isTrueSync ? 'var(--blue)' : 'var(--canvas-dim)', color: isTrueSync ? '#fff' : 'var(--muted)', fontSize: 11.5, fontWeight: 660 }}>{RANK_LABELS[i] || i + 1}</span>
              <div className="lite-fixrow-title" style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 620, color: 'var(--text-strong)', letterSpacing: '-0.01em' }}>{f.name}</div>
                <div style={{ fontSize: 12.5, color: 'var(--muted)', marginTop: 3, lineHeight: 1.5 }}>{fixHuman}</div>
              </div>
              {isDiscoveryRow && unlockedPoints > 0 ? (
                <div className="lite-fixrow-points" style={{ width: 190, flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
                  <div style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div style={{ flex: 1, position: 'relative', height: 10, borderRadius: 5, background: 'var(--canvas-dim)', overflow: 'hidden' }}>
                      <i style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${(f.impact / maxImpact) * 100}%`, background: isTrueSync ? 'var(--blue)' : 'var(--ink)', borderRadius: 5 }} />
                    </div>
                    <span className="num" style={{ fontSize: 13, fontWeight: 680, color: isTrueSync ? 'var(--blue)' : 'var(--ink)', whiteSpace: 'nowrap' }}>+{f.impact} pts</span>
                  </div>
                  {/* Part 5a: rendering-only badge — never folded into impact,
                      maxImpact, or the title's point total, so it can never
                      appear in a summed total (test-asserted). */}
                  <span className="mono-label lite-fixrow-unlocked" style={{ fontSize: 8.5, color: 'var(--amber-deep)', whiteSpace: 'nowrap' }}>+{Math.round(unlockedPoints)} UNLOCKED</span>
                </div>
              ) : (
                <div className="lite-fixrow-points" style={{ width: 190, flexShrink: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{ flex: 1, position: 'relative', height: 10, borderRadius: 5, background: 'var(--canvas-dim)', overflow: 'hidden' }}>
                    <i style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${(f.impact / maxImpact) * 100}%`, background: isTrueSync ? 'var(--blue)' : 'var(--ink)', borderRadius: 5 }} />
                  </div>
                  <span className="num" style={{ fontSize: 13, fontWeight: 680, color: isTrueSync ? 'var(--blue)' : 'var(--ink)', whiteSpace: 'nowrap' }}>+{f.impact} pts</span>
                </div>
              )}
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
            <Button variant="blue" arrow onClick={() => demoModal.open('full_analysis_walkthrough')} style={{ flexShrink: 0 }}>Book your walkthrough</Button>
          </div>
        </div>
      )}

      <div style={{ marginTop: 16, paddingTop: 14, borderTop: '1px solid var(--hairline)' }}>
        <ProvenanceLine confidence="modeled" parts={['Action-level estimates', 'exposure shares are modeled, not measured']} />
      </div>
    </ReportSection>
    {demoModal.cta && (
      <RequestFormModal
        open={demoModal.isOpen}
        onClose={demoModal.close}
        eyebrow={demoModal.cta.eyebrow}
        title={demoModal.cta.title}
        messagePlaceholder={demoModal.cta.messagePlaceholder}
        onSubmit={demoModal.onSubmit}
      />
    )}
    </>
  )
}
