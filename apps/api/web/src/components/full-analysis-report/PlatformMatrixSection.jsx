/**
 * Platform matrix — new (no lite equivalent; lite only ever measures
 * one platform, so a per-platform breakdown is meaningless there).
 * Reuses ReportSection for the card chrome and StateChip for the
 * envelope-driven cells, matching the rest of the report's honesty
 * convention: a not_measured/na envelope renders a state chip, never a
 * zero (2c).
 */
import { StateChip } from '../../ds/index.js'
import { ReportSection } from '../../lite/report/ReportSection.jsx'
import { envelopeChipState, envelopeLabel } from './fullAnalysisDerive.js'

const AGENT_ACCESS_LABEL = { allowed: 'Admitted', blocked: 'Blocked', partial: 'Partial', unknown: 'Unknown' }
const AGENT_ACCESS_STATE = { allowed: 'seen', blocked: 'invisible', partial: 'partial', unknown: 'unmeasured' }
const MEMBER_VALUE_LABEL = { cited_with_price: 'Cited, with price', cited_no_price: 'Cited, no price', never_cited: 'Never cited' }
const MEMBER_VALUE_STATE = { cited_with_price: 'seen', cited_no_price: 'partial', never_cited: 'unmeasured' }

function EnvelopeCell({ envelope }) {
  const state = envelopeChipState(envelope)
  // Only override StateChip's own default label ("Unmeasured") with a
  // real number when there is one — na/not_measured must never render
  // envelopeLabel's '—' fallback in place of the honest state word.
  return <StateChip state={state} variant="chip" size="sm">{state === 'unmeasured' ? undefined : envelopeLabel(envelope)}</StateChip>
}

export function PlatformMatrixSection({ matrix, open, onToggle }) {
  if (!matrix || matrix.length === 0) return null

  return (
    <ReportSection
      id="matrix" eyebrow={`${matrix.length} PLATFORM${matrix.length === 1 ? '' : 'S'} × EVERY PILLAR DIMENSION`}
      title="Where the score comes from, agent by agent"
      open={open} onToggle={onToggle}
    >
      <div style={{ overflowX: 'auto', marginTop: 20 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left', padding: '8px 12px', fontFamily: 'var(--font-mono)', fontSize: 9.5, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--faint)', fontWeight: 500, borderBottom: '2px solid var(--border-strong)' }}>Platform</th>
              {['Share of mentions', 'Rec strength', 'Agent access', 'Price truth · said', 'Deal citability', 'Member value'].map((h) => (
                <th key={h} style={{ textAlign: 'left', padding: '8px 12px', fontFamily: 'var(--font-mono)', fontSize: 9.5, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--faint)', fontWeight: 500, borderBottom: '2px solid var(--border-strong)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.map((row) => (
              <tr key={row.platform}>
                <td style={{ padding: '12px', borderTop: '1px solid var(--hairline)', fontWeight: 600, color: 'var(--text-strong)' }}>{row.platform_name}</td>
                <td style={{ padding: '12px', borderTop: '1px solid var(--hairline)' }}><EnvelopeCell envelope={row.share_of_mentions} /></td>
                <td style={{ padding: '12px', borderTop: '1px solid var(--hairline)', fontSize: 12.5, color: 'var(--text)' }}>{row.recommendation_strength_band}</td>
                <td style={{ padding: '12px', borderTop: '1px solid var(--hairline)' }}>
                  <StateChip state={AGENT_ACCESS_STATE[row.agent_access] || 'unmeasured'} variant="chip" size="sm">{AGENT_ACCESS_LABEL[row.agent_access] || 'Unknown'}</StateChip>
                </td>
                <td style={{ padding: '12px', borderTop: '1px solid var(--hairline)' }}><EnvelopeCell envelope={row.price_truth_said} /></td>
                <td style={{ padding: '12px', borderTop: '1px solid var(--hairline)' }}><EnvelopeCell envelope={row.deal_citability} /></td>
                <td style={{ padding: '12px', borderTop: '1px solid var(--hairline)' }}>
                  <StateChip state={MEMBER_VALUE_STATE[row.member_value] || 'unmeasured'} variant="chip" size="sm">{MEMBER_VALUE_LABEL[row.member_value] || row.member_value}</StateChip>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ReportSection>
  )
}
