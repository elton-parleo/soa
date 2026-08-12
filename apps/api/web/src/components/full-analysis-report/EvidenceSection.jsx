/**
 * Evidence card — new (no lite equivalent). Renders report.evidence
 * (select_evidence_exemplar) verbatim: platform/stage/persona/query,
 * the coded answer excerpt, the price observation vs ground truth, and
 * a "View coding" toggle showing the raw mention/price_observation
 * facts. Absent gracefully (2c) when the cycle has nothing that
 * qualifies (no inaccurate, ground-truth-measured price observation).
 */
import { useState } from 'react'
import { Glyph } from '../../ds/index.js'
import { ReportSection } from '../../lite/report/ReportSection.jsx'

export function EvidenceSection({ evidence, onViewResponse, open, onToggle }) {
  const [coding, setCoding] = useState(false)
  if (!evidence) return null
  const po = evidence.price_observation

  return (
    <ReportSection
      id="evidence" eyebrow="EVIDENCE · EVERY NUMBER RESOLVES TO A CODED ANSWER"
      title="What an agent actually said"
      extra={<span className="mono-label" style={{ fontSize: 9, background: 'var(--red-tint)', color: 'var(--red-deep)', borderRadius: 999, padding: '4px 10px' }}>PRICE INACCURATE · OFFERS UNCITED</span>}
      open={open} onToggle={onToggle}
    >
      <div className="mono-label" style={{ fontSize: 9.5, color: 'var(--faint)', marginTop: 18 }}>
        {(evidence.platform || '').toUpperCase()} · {(evidence.stage || '').toUpperCase()} · {(evidence.persona || '').toUpperCase()}
        {evidence.query_text ? ` · "${evidence.query_text}"` : ''}
      </div>
      <div style={{ background: 'var(--surface-warm)', border: '1px solid var(--hairline)', borderRadius: 16, padding: '20px 24px', fontSize: 14.5, lineHeight: 1.75, color: 'var(--text)', marginTop: 18 }}>
        {evidence.answer_excerpt || 'No excerpt captured for this answer.'}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 14, flexWrap: 'wrap', gap: 10 }}>
        <span style={{ fontSize: 13.5, color: 'var(--red-deep)' }}>
          {po ? `Ground truth: $${po.ground_truth_true_cost}. Agent quoted $${po.stated_price} — off by ${po.delta_pct > 0 ? '+' : ''}${po.delta_pct}%.` : ''}
          {evidence.uncited_eligible_offers > 0 ? ` ${evidence.uncited_eligible_offers} eligible offer${evidence.uncited_eligible_offers === 1 ? '' : 's'} went uncited.` : ''}
        </span>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          {onViewResponse && evidence.run_id && (
            <button type="button" onClick={() => onViewResponse(evidence.run_id)} style={{ background: 'none', border: 'none', color: 'var(--blue)', fontSize: 12.5, fontWeight: 600, cursor: 'pointer', padding: 0 }}>
              View in Response Explorer →
            </button>
          )}
          <button
            type="button" onClick={() => setCoding((v) => !v)}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 8, background: 'var(--surface)', border: '1px solid var(--border-strong)', borderRadius: 10, padding: '7px 13px', cursor: 'pointer', fontSize: 12.5, fontWeight: 580, color: 'var(--text-strong)' }}
          >
            <Glyph name={coding ? 'x' : 'plus'} size={12} color="var(--blue)" />
            {coding ? 'Hide coding' : 'View coding'}
          </button>
        </div>
      </div>
      {coding && (
        <div style={{ marginTop: 14, fontFamily: 'var(--font-mono)', fontSize: 12, color: '#9BA1AC', background: '#12161F', borderRadius: 12, padding: '16px 20px', lineHeight: 1.9 }}>
          <div><b style={{ color: '#7FA6FF', fontWeight: 500 }}>run_id</b>: {evidence.run_id}</div>
          {po && (
            <div>
              <b style={{ color: '#7FA6FF', fontWeight: 500 }}>price_observation</b>: stated ${po.stated_price} · ground truth ${po.ground_truth_true_cost} · Δ {po.delta_pct > 0 ? '+' : ''}{po.delta_pct}% · <span style={{ color: '#E08579' }}>inaccurate</span>
            </div>
          )}
          <div><b style={{ color: '#7FA6FF', fontWeight: 500 }}>uncited_eligible_offers</b>: {evidence.uncited_eligible_offers}</div>
        </div>
      )}
    </ReportSection>
  )
}
