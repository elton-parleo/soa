/**
 * Stage-driven competitor graph — extends Pillar 01 per the mock (one
 * graph, re-rendered per selected funnel stage) without touching
 * VisibilitySection.jsx itself (which already renders the OVERALL
 * competitor set via SoAIndex and has no stage-selector slot to extend
 * safely). Rendered as its own section directly after Visibility.
 *
 * Reuses SoAIndex + buildSoaIndexRows exactly as VisibilitySection does
 * — including its existing flat +17pt illustrative "projected" hatch
 * (soaIndexDerive.js's PROJECTED_SHARE_UPLIFT_PCT), shown only on the
 * Ready to Buy stage. This turned out to BE "the illustrative purchase-
 * intent share extension used by the audit's flat what-if" 1h asked
 * for — the same mechanism, not a second one — so this section reuses
 * it directly rather than consuming the separate backend `what_if`
 * field, which duplicates the same idea server-side.
 */
import { useState } from 'react'
import { SoAIndex } from '../../ds/index.js'
import { buildSoaIndexRows } from '../../lite/soaIndexDerive.js'
import { shareOfMentionsRank } from './fullAnalysisDerive.js'

const STAGE_ORDER = ['Awareness', 'Research', 'Comparison', 'Ready to Buy']

export function CompetitorStageSection({ competitorSet }) {
  const stages = ['All stages', ...STAGE_ORDER.filter((s) => competitorSet?.by_stage?.[s])]
  const [stage, setStage] = useState('All stages')

  if (!competitorSet || !competitorSet.overall?.length) return null

  const rows = stage === 'All stages' ? competitorSet.overall : competitorSet.by_stage[stage]
  const { rows: soaRows, you, projectedLabel } = buildSoaIndexRows(rows)
  const rank = shareOfMentionsRank(rows)

  return (
    <div style={{ background: 'var(--surface)', borderRadius: 16, boxShadow: 'var(--shadow-card)', padding: '26px 28px', marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
        <span className="mono-label" style={{ fontSize: 9.5, color: 'var(--faint)' }}>YOUR AUTO-SELECTED COMPETITOR SET, BY STAGE</span>
        {rank && <span className="mono-label" style={{ fontSize: 9.5, color: 'var(--text-strong)' }}>{rank}{stage !== 'All stages' ? ` · ${stage.toUpperCase()}` : ''}</span>}
      </div>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', margin: '6px 0 18px' }}>
        {stages.map((s) => (
          <button
            key={s} type="button" onClick={() => setStage(s)}
            style={{
              fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase',
              padding: '9px 14px', borderRadius: 999, cursor: 'pointer',
              border: `1px solid ${s === stage ? 'var(--ink)' : 'var(--border)'}`,
              background: s === stage ? 'var(--ink)' : 'var(--surface)',
              color: s === stage ? '#fff' : 'var(--muted)',
            }}
          >
            {s}
          </button>
        ))}
      </div>
      {soaRows.length > 0 ? (
        <SoAIndex rows={soaRows} you={you} projected={stage === 'Ready to Buy' ? projectedLabel : null} />
      ) : (
        <div style={{ fontSize: 13, color: 'var(--faint)' }}>No competitor share data for this stage.</div>
      )}
    </div>
  )
}
