// FullAnalysisReport — Full Analysis coexistence, Phase 4: the paid
// report a cycle renders once it has an attached, current-scorer-
// version crawl (see the render-gate in FullAnalysisReportGate.jsx,
// which decides between this and the classic MetricsDashboard.jsx —
// untouched — for any given cycle). Built on the ds/ design-system
// components ported from the audit/lite report's own design refs.
import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { MetricRow, StateChip, SectionHeading, Delta } from '../ds/index.js'

const FIX_OWNER_LABELS = { ENG: 'Engineering', TRUESYNC: 'Parleo TrueSync' }

const PILLAR_LABELS = {
  visibility: 'Visibility',
  accessibility: 'Accessibility',
  true_value: 'True Value',
}

function envelopeState(envelope) {
  if (!envelope) return null
  if (envelope.state === 'na') return 'unmeasured'
  if (envelope.state === 'not_measured') return 'unmeasured'
  return envelope.value >= 50 ? 'seen' : envelope.value > 0 ? 'partial' : 'invisible'
}

function PillarBar({ pillarKey, pillar }) {
  const pct = pillar.max ? Math.round((pillar.score / 100) * 100) : 0
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6 }}>
        <span style={{ fontWeight: 600, color: 'var(--text-strong)' }}>{PILLAR_LABELS[pillarKey] || pillarKey}</span>
        <span className="num" style={{ color: 'var(--faint)' }}>{Math.round(pillar.score)}/100</span>
      </div>
      <div style={{ height: 8, borderRadius: 999, background: 'var(--canvas-dim)', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: 'var(--blue)', borderRadius: 999 }} />
      </div>
    </div>
  )
}

function ContinuationBanner({ continuation, composite }) {
  if (!continuation) return null
  const hasAuditScore = continuation.audit_composite != null
  return (
    <div style={{ padding: 20, borderRadius: 12, background: 'var(--canvas-dim)', border: '1px solid var(--border)', marginBottom: 28 }}>
      <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 6, color: 'var(--text-strong)' }}>
        {hasAuditScore
          ? `Your audit scored ${continuation.audit_composite} on ${continuation.audit_date || 'a recent date'}, ChatGPT only.`
          : 'This cycle continues your audit.'}
      </div>
      <div style={{ fontSize: 13, color: 'var(--faint)', display: 'flex', alignItems: 'center', gap: 10 }}>
        <span>The full analysis covers {continuation.audit_platforms_note}.</span>
        {hasAuditScore && composite != null && (
          <Delta value={composite - continuation.audit_composite} bare size="sm" />
        )}
      </div>
    </div>
  )
}

function DimensionSection({ dim }) {
  const said = dim.said_envelope
  const seen = dim.seen
  return (
    <div style={{ padding: '18px 0', borderBottom: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <div style={{ fontWeight: 650, fontSize: 15, color: 'var(--text-strong)' }}>{dim.name}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {dim.fix_owner && (
            <span className="mono-label" style={{ fontSize: 10.5, color: 'var(--faint)' }}>
              {FIX_OWNER_LABELS[dim.fix_owner] || dim.fix_owner}
            </span>
          )}
          <span className="num" style={{ fontSize: 13, fontWeight: 600 }}>
            {dim.na ? '—' : `${Math.round(dim.earned)}/${Math.round(dim.max)}`}
          </span>
        </div>
      </div>
      {dim.na ? (
        <StateChip state="unmeasured">Not applicable this cycle</StateChip>
      ) : (
        <div style={{ display: 'flex', gap: 24 }}>
          {seen && (
            <div>
              <div className="mono-label" style={{ fontSize: 10.5, color: 'var(--faint)', marginBottom: 4 }}>SEEN</div>
              <StateChip state={seen.na ? 'unmeasured' : seen.earned >= seen.max ? 'seen' : seen.earned > 0 ? 'partial' : 'invisible'}>
                {seen.na ? 'Unmeasured' : `${Math.round(seen.earned)}/${Math.round(seen.max)}`}
              </StateChip>
            </div>
          )}
          {said && (
            <div>
              <div className="mono-label" style={{ fontSize: 10.5, color: 'var(--faint)', marginBottom: 4 }}>SAID</div>
              <StateChip state={envelopeState(said)}>
                {said.state === 'na' ? 'Too few mentions'
                  : said.state === 'not_measured' ? 'Not yet coded'
                  : `${said.value}%`}
              </StateChip>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function AnalystLayer({ cycleCode }) {
  const [metrics, setMetrics] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.getMetrics(cycleCode)
      .then(data => {
        const primary = data.entities.find(e => e.role === 'primary')
        setMetrics(primary ? data.slices?.overall?.[primary.code] : null)
      })
      .catch(err => setError(err.message))
  }, [cycleCode])

  if (error) return null
  if (!metrics) return <div style={{ color: 'var(--faint)', fontSize: 13 }}>Loading analyst metrics…</div>

  return (
    <MetricRow items={[
      { value: metrics.mention_rate, suffix: '%', label: 'Mention Rate' },
      { value: metrics.som, suffix: '%', label: 'Share of Mentions' },
      { value: metrics.rsi, label: 'Recommendation Strength' },
      { value: metrics.position_index, suffix: '%', label: 'Position Index' },
      { value: metrics.pdi, suffix: '%', label: 'Platform Distribution' },
      { value: metrics.deal_citation_rate, suffix: '%', label: 'Incentive Citation Rate' },
    ]} size={32} />
  )
}

export default function FullAnalysisReport({ cycleCode, report, onNavigate }) {
  const { pillars, continuation, scorer_version: scorerVersion, total_queries: totalQueries } = report

  return (
    <div style={{ minHeight: '100vh', background: 'var(--canvas)', padding: '40px 32px', maxWidth: 880, margin: '0 auto' }}>
      <button onClick={() => onNavigate && onNavigate('dashboard')}
        style={{ background: 'none', border: 'none', color: 'var(--faint)', fontSize: 12, cursor: 'pointer', padding: 0, marginBottom: 20 }}>
        ← Back to dashboard
      </button>

      <SectionHeading accent={cycleCode} accentTone="primary" size="sm">
        Full Analysis
      </SectionHeading>

      <div style={{ margin: '20px 0 28px' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 4 }}>
          <span className="num" style={{ fontSize: 44, fontWeight: 700, color: 'var(--text-strong)' }}>
            {Math.round(pillars.composite ?? 0)}
          </span>
          <StateChip state={pillars.verdict === 'AGENT-READY' ? 'seen' : 'invisible'}>
            {pillars.verdict}
          </StateChip>
        </div>
        <div className="mono-label" style={{ fontSize: 11, color: 'var(--faint)' }}>
          scorer v{scorerVersion} · {totalQueries} queries measured
        </div>
      </div>

      <ContinuationBanner continuation={continuation} composite={pillars.composite} />

      {['visibility', 'accessibility', 'true_value'].map(key => (
        <PillarBar key={key} pillarKey={key} pillar={pillars[key]} />
      ))}

      <div style={{ marginTop: 36 }}>
        <SectionHeading size="sm">Dimensions</SectionHeading>
        <div style={{ marginTop: 16 }}>
          {['visibility', 'accessibility', 'true_value'].flatMap(key =>
            pillars[key].dimensions.map(dim => <DimensionSection key={dim.code} dim={dim} />)
          )}
        </div>
      </div>

      <div style={{ marginTop: 36 }}>
        <SectionHeading size="sm">Analyst metrics</SectionHeading>
        <div style={{ marginTop: 16 }}>
          <AnalystLayer cycleCode={cycleCode} />
        </div>
      </div>
    </div>
  )
}
