import { StateChip } from '../../ds/index.js'
import { ReportSection } from './ReportSection.jsx'
import { dimByCode, pillarEarnedMax, pillarHeadline, isPartialRead, PILLAR_ACCESSIBILITY } from './reportDerive.js'
import { DIMENSIONS_BY_CODE } from '../landing/scanDimensionsRegistry.js'
import { toChipState } from './checkState.js'

// Part 4c: a tile whose inputs needed product pages keeps its shape —
// same checks grid — but the score corner becomes a "{n} PTS UNREAD"
// chip and a mono line clarifies it's not a zero. Outside a
// partial-read run, a blocked tile keeps today's plain 'unmeasured'
// text unchanged (1b).
function ChecksTile({ dim, registryDim, partialRead }) {
  const label = registryDim.name
  const unread = partialRead && dim?.blocked
  const scoreLabel = dim && !dim.na && !dim.blocked ? `${Math.round(dim.earned)}/${registryDim.weight}` : dim?.blocked ? 'unmeasured' : `0/${registryDim.weight}`
  return (
    <div className={unread ? 'ds-hatch' : undefined} style={{ background: unread ? undefined : 'var(--surface-warm)', border: `1px ${unread ? 'dashed var(--border-strong)' : 'solid var(--hairline)'}`, borderRadius: 12, padding: '16px 17px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontSize: 13.5, fontWeight: 640, color: 'var(--text-strong)' }}>{label}</span>
        {unread ? (
          <span className="mono-label" style={{ fontSize: 9, color: 'var(--faint)', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 999, padding: '3px 8px' }}>
            {registryDim.weight} PTS UNREAD
          </span>
        ) : (
          <span className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--muted)' }}>{scoreLabel}</span>
        )}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5, marginTop: 12 }}>
        {(dim?.checks || []).map((c) => (
          <StateChip key={c.code} state={toChipState(c.state)} variant="chip" size="sm">{c.label}</StateChip>
        ))}
        {!dim?.checks && <span style={{ fontSize: 12, color: 'var(--faint)' }}>Not measurable this run.</span>}
      </div>
      {unread && <div className="mono-label" style={{ fontSize: 8, color: 'var(--faint)', marginTop: 12 }}>NEEDS PRODUCT PAGES · NOT A ZERO</div>}
    </div>
  )
}

export function AccessibilitySection({ report, open, onToggle }) {
  const pillars = report.pillars
  const dims = pillars.accessibility?.dimensions || []
  const acc = pillarEarnedMax(pillars.accessibility)
  const agentAccess = dimByCode(dims, 'agent_access')
  const catalog = dimByCode(dims, 'catalog_context')
  const protocol = dimByCode(dims, 'protocol_feed')
  const partialRead = isPartialRead(pillars, report.scan?.degraded_reason)

  return (
    <ReportSection
      id="acc" eyebrow="PILLAR 02 · ACCESSIBILITY"
      title={pillarHeadline(report, PILLAR_ACCESSIBILITY)}
      score={`${Math.round(acc.earned)}/${Math.round(acc.max)}`}
      open={open} onToggle={onToggle}
    >
      <div className="lite-v4-acc-tiles-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 14, marginTop: 20 }}>
        <ChecksTile dim={agentAccess} registryDim={DIMENSIONS_BY_CODE.agent_access} partialRead={partialRead} />
        <ChecksTile dim={catalog} registryDim={DIMENSIONS_BY_CODE.catalog_context} partialRead={partialRead} />
        <ChecksTile dim={protocol} registryDim={DIMENSIONS_BY_CODE.protocol_feed} partialRead={partialRead} />
      </div>
    </ReportSection>
  )
}
