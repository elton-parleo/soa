import { StateChip } from '../../ds/index.js'
import { ReportSection } from './ReportSection.jsx'
import { dimByCode, pillarEarnedMax } from './reportDerive.js'
import { DIMENSIONS_BY_CODE } from '../landing/scanDimensionsRegistry.js'
import { toChipState } from './checkState.js'

function ChecksTile({ dim, registryDim }) {
  const label = registryDim.name
  const scoreLabel = dim && !dim.na && !dim.blocked ? `${Math.round(dim.earned)}/${registryDim.weight}` : dim?.blocked ? 'unmeasured' : `0/${registryDim.weight}`
  return (
    <div style={{ background: 'var(--surface-warm)', border: '1px solid var(--hairline)', borderRadius: 12, padding: '16px 17px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontSize: 13.5, fontWeight: 640, color: 'var(--text-strong)' }}>{label}</span>
        <span className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--muted)' }}>{scoreLabel}</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5, marginTop: 12 }}>
        {(dim?.checks || []).map((c) => (
          <StateChip key={c.code} state={toChipState(c.state)} variant="chip" size="sm">{c.label}</StateChip>
        ))}
        {!dim?.checks && <span style={{ fontSize: 12, color: 'var(--faint)' }}>Not measurable this run.</span>}
      </div>
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

  return (
    <ReportSection
      id="acc" eyebrow="PILLAR 02 · ACCESSIBILITY"
      title="Agents can knock, but can't read much"
      score={`${Math.round(acc.earned)}/${Math.round(acc.max)}`}
      open={open} onToggle={onToggle}
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 14, marginTop: 20 }}>
        <ChecksTile dim={agentAccess} registryDim={DIMENSIONS_BY_CODE.agent_access} />
        <ChecksTile dim={catalog} registryDim={DIMENSIONS_BY_CODE.catalog_context} />
        <ChecksTile dim={protocol} registryDim={DIMENSIONS_BY_CODE.protocol_feed} />
      </div>
    </ReportSection>
  )
}
