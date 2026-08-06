import { Glyph, SoAIndex } from '../../ds/index.js'
import { ReportSection } from './ReportSection.jsx'
import { HowItsScoredButton, HowItsScoredPanel } from './HowItsScored.jsx'
import { useCollapsible } from './Collapsible.jsx'
import { dimByCode, pillarEarnedMax, pillarHeadline, PILLAR_VISIBILITY } from './reportDerive.js'
import { DIMENSIONS_BY_CODE, LITE_QUERY_COUNT } from '../landing/scanDimensionsRegistry.js'
import { buildSoaIndexRows } from '../soaIndexDerive.js'

export function VisibilitySection({ report, open, onToggle, shareOfMentionsRank }) {
  const pillars = report.pillars
  const dims = pillars.visibility?.dimensions || []
  const som = dimByCode(dims, 'share_of_mentions')
  const rs = dimByCode(dims, 'recommendation_strength')
  const somDim = DIMENSIONS_BY_CODE.share_of_mentions
  const rsDim = DIMENSIONS_BY_CODE.recommendation_strength
  const [somOpen, toggleSom] = useCollapsible()
  const [rsOpen, toggleRs] = useCollapsible()

  const vis = pillarEarnedMax(pillars.visibility)
  const shareOfMentions = report.visibility_breakdown?.share_of_mentions || []
  const primaryShare = shareOfMentions.find((e) => e.is_primary)
  const somPct = primaryShare ? primaryShare.share_pct : (som ? Math.round((som.earned / somDim.weight) * 50) : 0)
  const { rows: soaRows, you, projectedLabel } = buildSoaIndexRows(shareOfMentions)

  return (
    <ReportSection
      id="viz" eyebrow={`PILLAR 01 · VISIBILITY · ${LITE_QUERY_COUNT} QUERIES`}
      title={pillarHeadline(report, PILLAR_VISIBILITY)}
      score={som && rs ? `${Math.round(vis.earned)}/${Math.round(vis.max)}` : null}
      open={open} onToggle={onToggle}
    >
      <div style={{ marginTop: 22, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
        <div style={{ background: 'var(--surface-warm)', border: '1px solid var(--hairline)', borderRadius: 13, padding: '17px 18px 18px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
            <Glyph name="eye" size={15} color="var(--blue)" />
            <span style={{ fontSize: 14.5, fontWeight: 640, color: 'var(--text-strong)', letterSpacing: '-0.01em' }}>{somDim.name}</span>
            {som && (
              <span className="num" style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 680, color: 'var(--text-strong)' }}>
                {Math.round(som.earned)}<span style={{ color: 'var(--faint)', fontWeight: 500 }}>/{somDim.weight}</span>
              </span>
            )}
          </div>
          <div style={{ fontSize: 13.5, color: 'var(--muted)', marginTop: 9, lineHeight: 1.55 }}>
            {somPct}% of all brand mentions were you. 50% share earns all {somDim.weight} points.
          </div>
          <div style={{ marginTop: 18 }}>
            <div style={{ position: 'relative', height: 9, borderRadius: 5, background: 'var(--canvas-dim)', overflow: 'hidden' }}>
              <i style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${Math.min(100, (somPct / 50) * 100)}%`, background: 'var(--ink)', borderRadius: 5 }} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, marginTop: 9 }}>
              <span className="mono-label" style={{ fontSize: 9.5, color: 'var(--text-strong)' }}>YOU · {somPct}%</span>
              <span className="mono-label" style={{ fontSize: 9.5, color: 'var(--faint)' }}>50% EARNS ALL {somDim.weight}</span>
            </div>
          </div>
          <div style={{ marginTop: 16 }}>
            <HowItsScoredButton open={somOpen} onToggle={toggleSom} />
          </div>
          {somOpen && (
            <HowItsScoredPanel>
              {LITE_QUERY_COUNT} shopper questions, every brand counted, your share of the total. Bigger share, more points. <b style={{ color: 'var(--text-strong)' }}>50% share = all {somDim.weight}.</b> You're at {somPct}%.
            </HowItsScoredPanel>
          )}
        </div>

        <div style={{ background: 'var(--surface-warm)', border: '1px solid var(--hairline)', borderRadius: 13, padding: '17px 18px 18px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
            <Glyph name="spark" size={15} color="var(--blue)" />
            <span style={{ fontSize: 14.5, fontWeight: 640, color: 'var(--text-strong)', letterSpacing: '-0.01em' }}>{rsDim.name}</span>
            {rs && (
              <span className="num" style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 680, color: 'var(--text-strong)' }}>
                {Math.round(rs.earned)}<span style={{ color: 'var(--faint)', fontWeight: 500 }}>/{rsDim.weight}</span>
              </span>
            )}
          </div>
          <div style={{ fontSize: 13.5, color: 'var(--muted)', marginTop: 9, lineHeight: 1.55 }}>Where you land when agents do mention you.</div>
          <div style={{ marginTop: 16 }}>
            <HowItsScoredButton open={rsOpen} onToggle={toggleRs} />
          </div>
          {rsOpen && (
            <HowItsScoredPanel>
              Where you appear in each answer and how strongly you're recommended. First and endorsed earns all {rsDim.weight}. Listed in passing earns partial credit.
            </HowItsScoredPanel>
          )}
        </div>
      </div>

      <div style={{ borderTop: '1px solid var(--hairline)', marginTop: 22, paddingTop: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 13 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
            <Glyph name="layers" size={14} color="var(--faint)" />
            <span className="mono-label" style={{ fontSize: 9.5, color: 'var(--faint)' }}>YOUR AUTO-SELECTED COMPETITOR SET</span>
          </div>
          {shareOfMentionsRank && <span className="mono-label" style={{ fontSize: 9.5, color: 'var(--text-strong)' }}>{shareOfMentionsRank}</span>}
        </div>
        {soaRows.length > 0 ? (
          <SoAIndex rows={soaRows} you={you} projected={projectedLabel} />
        ) : (
          <div style={{ fontSize: 13, color: 'var(--faint)' }}>No competitor share data for this run.</div>
        )}
      </div>
    </ReportSection>
  )
}
