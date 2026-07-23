/**
 * Full (unlocked) report. Section order is the product — see the Stage 4
 * spec — and must not be reshuffled: executive tiles, visibility by
 * purchase stage, evidence gallery, why-section (all 8 scan dimensions),
 * ranked fixes, exposure calculator, locked panels grid, footer.
 *
 * Adaptive by report.scan.status: 'skipped' (or no scan row at all) means
 * no store_url was ever submitted — the why-section becomes a prompt to
 * add one, since there is no API to attach a URL after the fact and no
 * per-dimension data to show either way. 'blocked'/'failed' show an
 * honest, static explanation (Stage 3 returns an empty dimensions array
 * for any non-'complete' scan, so this can't be data-driven). 'complete'
 * renders the full 8-dimension breakdown.
 */
import { useState } from 'react'
import {
  accessibilityBadgeText, computeExposure, formatCurrency, formatDateStamp,
  groupDimensionsByFamily, rankDimensionsByGap,
} from './liteDerive.js'
import {
  T, BRAND_COLORS, STAGE_ORDER, outerStyle, wideCardStyle, LogoHeader, InfoBadge,
  ScoreDial, useAnimateOnMount, formatPct, formatScore,
} from './liteTheme.jsx'

const DEFAULT_REVENUE = 1_000_000
const DEFAULT_AI_SHARE_PCT = 20

// ─── Section heading ────────────────────────────────────────────────────

function SectionHeading({ children }) {
  return (
    <div style={{
      fontSize: 15, fontWeight: 700, color: T.text,
      margin: '28px 0 12px', paddingTop: 20, borderTop: `1px solid ${T.border}`,
    }}>
      {children}
    </div>
  )
}

// ─── Executive tiles ────────────────────────────────────────────────────

function ExecutiveTiles({ report, exposure }) {
  const accessBadge = accessibilityBadgeText(report.scan_status)
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 20, justifyContent: 'center' }}>
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 32, fontWeight: 700, color: T.text, fontFamily: 'monospace' }}>
          {report.composite === null || report.composite === undefined ? '—' : Math.round(report.composite)}
        </div>
        <div style={{ fontSize: 12, color: T.slate, fontWeight: 600 }}>Composite score</div>
      </div>
      <ScoreDial label="Visibility" value={report.visibility} color={T.indigo} />
      <ScoreDial
        label="Accessibility" value={report.accessibility} color={T.green}
        dimmed={!!accessBadge} badge={accessBadge}
      />
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 20, fontWeight: 700, color: T.text, fontFamily: 'monospace' }}>
          {formatCurrency(exposure)}
        </div>
        <div style={{ fontSize: 12, color: T.slate, fontWeight: 600 }}>Modeled exposure/mo</div>
      </div>
    </div>
  )
}

// ─── Visibility by purchase stage (4-stage you-vs-rival grid) ──────────

function VisibilityByStage({ byStage, entities }) {
  const stages = STAGE_ORDER.filter((s) => byStage[s])
  const animated = useAnimateOnMount()
  if (stages.length === 0) return null

  return (
    <div>
      <div style={{ display: 'flex', gap: 14, marginBottom: 10, flexWrap: 'wrap' }}>
        {entities.map((entity, ei) => (
          <div key={entity.name} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: T.textMid }}>
            <span style={{
              width: 8, height: 8, borderRadius: 2, display: 'inline-block',
              background: BRAND_COLORS[ei % BRAND_COLORS.length],
            }} />
            {entity.name}{entity.role === 'primary' ? ' (you)' : ''}
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 8, overflowX: 'auto' }}>
        {stages.map((stage, si) => (
          <div key={stage} style={{ flex: '1 1 0', minWidth: 90 }}>
            <div style={{
              fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
              color: T.slate, letterSpacing: '0.04em', marginBottom: 8, textAlign: 'center',
            }}>
              {stage}
              {si < stages.length - 1 && <span style={{ color: T.slateLight }}> →</span>}
            </div>
            {entities.map((entity, ei) => {
              const value = byStage[stage]?.[entity.name]?.mention_rate ?? 0
              return (
                <div key={entity.name} style={{ marginBottom: 8 }}>
                  <div style={{
                    height: 60, width: '100%', background: T.border, borderRadius: 4,
                    display: 'flex', alignItems: 'flex-end', overflow: 'hidden',
                  }}>
                    <div style={{
                      width: '100%',
                      height: animated ? `${value}%` : '0%',
                      background: BRAND_COLORS[ei % BRAND_COLORS.length],
                      transition: `height 0.8s ease ${(si * entities.length + ei) * 0.05}s`,
                    }} />
                  </div>
                  <div style={{ fontSize: 10, color: T.textMid, textAlign: 'center', marginTop: 2 }}>
                    {formatPct(value)}
                  </div>
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Evidence gallery (speculative field, hidden when absent) ──────────

function Chip({ label, muted }) {
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 999,
      background: muted ? T.offWhite : T.amberLight,
      color: muted ? T.slate : '#92400E',
      border: `1px solid ${muted ? T.border : '#FDE68A'}`,
    }}>
      {label}
    </span>
  )
}

function EvidenceGallery({ examples }) {
  if (!examples || examples.length === 0) return null
  return (
    <div>
      <div style={{ fontSize: 13, fontWeight: 700, color: T.text, marginBottom: 10 }}>
        Evidence
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {examples.map((ex, i) => (
          <div key={i} style={{ border: `1px solid ${T.border}`, borderRadius: 8, padding: 12 }}>
            {ex.excerpt && (
              <div style={{ fontSize: 12, color: T.textMid, fontStyle: 'italic', marginBottom: 6 }}>
                "{ex.excerpt}"
              </div>
            )}
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {ex.annotation && <Chip label={ex.annotation} />}
              {ex.platform && <Chip label={ex.platform} muted />}
              {ex.stage && <Chip label={ex.stage} muted />}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Why section: all 8 scan dimensions, grouped Foundation/Value ──────

function AddStoreUrlPrompt({ onAddStoreUrl }) {
  return (
    <div style={{
      background: T.offWhite, border: `1px dashed ${T.border}`, borderRadius: 8,
      padding: 20, textAlign: 'center',
    }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: T.text, marginBottom: 8 }}>
        Add your store URL to see why
      </div>
      <div style={{ fontSize: 12, color: T.slate, marginBottom: 14, lineHeight: 1.5 }}>
        We can only score how an AI shopping agent reads your storefront with
        a URL to read. Run a fresh diagnostic with your store URL included to
        unlock the full breakdown.
      </div>
      {onAddStoreUrl && (
        <button
          onClick={onAddStoreUrl}
          style={{
            background: T.navy, color: T.white, fontSize: 13, fontWeight: 700,
            fontFamily: 'inherit', border: 'none', borderRadius: 8,
            padding: '10px 18px', cursor: 'pointer',
          }}
        >
          Add store URL
        </button>
      )}
    </div>
  )
}

function ScanDegradedExplanation({ status }) {
  const message = status === 'blocked'
    ? "Your store blocked our reader — that's itself a finding. Many AI shopping agents will hit the same wall."
    : "We couldn't finish reading your store this time. We'll try again on your next diagnostic."
  return (
    <div>
      <InfoBadge message={message} />
      <div style={{ fontSize: 12, color: T.textMid, lineHeight: 1.6, marginTop: 12 }}>
        This affects <strong>Agent Access (F1)</strong>, one of the 8 dimensions
        we score: whether an AI shopping agent can even reach your product
        pages at all — robots.txt rules, bot-detection, and sitemap
        availability all factor in. A store that's unreachable scores 0 here
        regardless of how good everything else is.
      </div>
    </div>
  )
}

function DimensionRow({ dimension }) {
  const pct = dimension.max ? (dimension.score / dimension.max) * 100 : 0
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: T.textMid }}>{dimension.name}</span>
        <span style={{ fontSize: 12, fontWeight: 700, fontFamily: 'monospace', color: T.textMid }}>
          {formatScore(dimension.score)}/{dimension.max}
        </span>
      </div>
      <div style={{ height: 6, background: T.border, borderRadius: 3, overflow: 'hidden', marginBottom: 6 }}>
        <div style={{ height: '100%', width: `${pct}%`, background: T.indigo, borderRadius: 3 }} />
      </div>
      {dimension.linked && <Chip label={`Linked: ${dimension.linked.reason}`} />}
    </div>
  )
}

function DimensionFamily({ title, subtotal, max, dimensions }) {
  if (dimensions.length === 0) return null
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: T.text, marginBottom: 10 }}>
        {title} ({formatScore(subtotal)}/{max})
      </div>
      {dimensions.map((d) => <DimensionRow key={d.code} dimension={d} />)}
    </div>
  )
}

function WhySection({ report, onAddStoreUrl }) {
  const scan = report.scan
  const status = scan?.status

  if (!status || status === 'skipped') {
    return <AddStoreUrlPrompt onAddStoreUrl={onAddStoreUrl} />
  }
  if (status === 'blocked' || status === 'failed') {
    return <ScanDegradedExplanation status={status} />
  }

  const { foundation, value } = groupDimensionsByFamily(scan.dimensions)
  return (
    <div>
      {scan.integrity_capped && (
        <div style={{ marginBottom: 16 }}>
          <InfoBadge message="Dishonest pricing signals (a fake 'was' price) capped this store's total score at 59 — see Offer Integrity (V5) below." />
        </div>
      )}
      <DimensionFamily title="Foundation" subtotal={scan.foundation?.subtotal} max={scan.foundation?.max ?? 35} dimensions={foundation} />
      <DimensionFamily title="Value" subtotal={scan.value?.subtotal} max={scan.value?.max ?? 65} dimensions={value} />
    </div>
  )
}

// ─── Ranked fixes ────────────────────────────────────────────────────────

function FixRow({ dimension }) {
  return (
    <div style={{ marginBottom: 14, paddingBottom: 14, borderBottom: `1px solid ${T.border}` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: T.text }}>{dimension.name}</span>
        {dimension.locked ? (
          <span style={{ fontSize: 11, color: T.slate }}>🔒 Full diagnostic</span>
        ) : (
          <span style={{ fontSize: 11, color: T.green, fontWeight: 700 }}>Free fix</span>
        )}
      </div>
      {dimension.locked ? (
        <div style={{ fontSize: 12, color: T.slateLight, fontStyle: 'italic' }}>
          Unlock the full Parleo diagnostic to see exactly what to change.
        </div>
      ) : dimension.fix ? (
        <pre style={{
          background: T.navy, color: '#E2E8F0', fontSize: 11, borderRadius: 6,
          padding: '10px 12px', overflowX: 'auto', margin: 0,
          fontFamily: 'monospace', lineHeight: 1.5, whiteSpace: 'pre-wrap',
        }}>{dimension.fix}</pre>
      ) : (
        <div style={{ fontSize: 12, color: T.slateLight }}>No issue found here.</div>
      )}
    </div>
  )
}

function FixList({ scan }) {
  if (!scan || scan.status !== 'complete') return null
  const ranked = rankDimensionsByGap(scan.dimensions)
  return (
    <div>
      {ranked.map((d) => <FixRow key={d.code} dimension={d} />)}
    </div>
  )
}

// ─── Exposure calculator ────────────────────────────────────────────────

function ExposureCalculator({ revenue, onRevenueChange, aiSharePct, onAiShareChange, exposure }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: T.slateLight, marginBottom: 14 }}>
        Modeled, not measured — a rough estimate, not an audited figure.
      </div>

      <label style={{ fontSize: 12, fontWeight: 600, color: T.textMid, display: 'block', marginBottom: 4 }}>
        Monthly revenue: {formatCurrency(revenue)}
      </label>
      <input
        type="range" min={10000} max={10000000} step={10000} value={revenue}
        onChange={(e) => onRevenueChange(Number(e.target.value))}
        style={{ width: '100%', marginBottom: 16 }}
        aria-label="Monthly revenue"
      />

      <label style={{ fontSize: 12, fontWeight: 600, color: T.textMid, display: 'block', marginBottom: 4 }}>
        AI-assisted share of purchases: {aiSharePct}%
      </label>
      <input
        type="range" min={0} max={100} step={1} value={aiSharePct}
        onChange={(e) => onAiShareChange(Number(e.target.value))}
        style={{ width: '100%', marginBottom: 16 }}
        aria-label="AI-assisted share of purchases"
      />

      <div style={{ background: T.offWhite, borderRadius: 8, padding: 14, textAlign: 'center' }}>
        <div style={{ fontSize: 11, color: T.slate, marginBottom: 4 }}>Modeled monthly exposure</div>
        <div style={{ fontSize: 24, fontWeight: 700, color: T.text, fontFamily: 'monospace' }}>
          {formatCurrency(exposure)}
        </div>
      </div>
    </div>
  )
}

// ─── Locked panels + CTA ────────────────────────────────────────────────

const LOCKED_PANELS = [
  '3 more AI platforms (Gemini, Perplexity, Claude)',
  'Full category run (hundreds of queries)',
  'Net price accuracy vs. your live catalog',
  'Persona-level breakdowns',
  'Trend over time',
  'Retail shelf comparison',
]

function LockedPanelsGrid({ ctaUrl }) {
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10, marginBottom: 16 }}>
        {LOCKED_PANELS.map((label) => (
          <div key={label} style={{
            border: `1px dashed ${T.border}`, borderRadius: 8, padding: 12,
            fontSize: 11, color: T.slate, textAlign: 'center', lineHeight: 1.4,
          }}>
            🔒 {label}
          </div>
        ))}
      </div>
      <div style={{ background: T.navy, borderRadius: 10, padding: 18, color: T.white }}>
        <div style={{ fontSize: 13, lineHeight: 1.6, marginBottom: 12 }}>
          This is 12 queries on one platform. The full Parleo diagnostic runs
          hundreds across ChatGPT, Gemini, Perplexity and Claude — and reads
          your whole catalog, not one page.
        </div>
        {ctaUrl && (
          <a
            href={ctaUrl}
            target="_blank"
            rel="noreferrer"
            style={{
              display: 'inline-block',
              background: T.white,
              color: T.navy,
              fontSize: 13,
              fontWeight: 700,
              padding: '10px 16px',
              borderRadius: 8,
              textDecoration: 'none',
            }}
          >
            Book a working session
          </a>
        )}
      </div>
    </div>
  )
}

// ─── Footer ──────────────────────────────────────────────────────────────

function Footer() {
  return (
    <div style={{
      marginTop: 24, paddingTop: 16, borderTop: `1px solid ${T.border}`,
      fontSize: 11, color: T.slateLight, lineHeight: 1.6,
    }}>
      <div>We'll re-run this diagnostic monthly if you keep your report link.</div>
      <div style={{ marginTop: 4 }}>
        12 queries · 1 platform · 1 run each · {formatDateStamp()} · sample, not a category study.
      </div>
    </div>
  )
}

// ─── Root ────────────────────────────────────────────────────────────────

export function LiteFullReport({ report, onAddStoreUrl }) {
  const entities = report.overall || []
  const ctaUrl = import.meta.env.VITE_LITE_CTA_URL

  const [revenue, setRevenue] = useState(DEFAULT_REVENUE)
  const [aiSharePct, setAiSharePct] = useState(DEFAULT_AI_SHARE_PCT)
  const exposure = computeExposure({ revenue, aiSharePct, visibility: report.visibility })

  // by_stage is keyed by stage name -> list of {name, role, metrics}; index
  // by entity name for O(1) lookup in VisibilityByStage.
  const byStageByName = {}
  Object.entries(report.by_stage || {}).forEach(([stage, entityList]) => {
    byStageByName[stage] = {}
    entityList.forEach((e) => {
      byStageByName[stage][e.name] = e.metrics
    })
  })

  return (
    <div style={outerStyle}>
      <div style={wideCardStyle}>
        <LogoHeader />
        <div style={{ fontSize: 18, fontWeight: 700, color: T.text, marginBottom: 16 }}>
          Your full Share of Algorithm report
        </div>

        <ExecutiveTiles report={report} exposure={exposure} />

        <SectionHeading>Visibility by purchase stage</SectionHeading>
        <VisibilityByStage byStage={byStageByName} entities={entities} />

        <EvidenceGallery examples={report.evidence_examples} />

        <SectionHeading>Why</SectionHeading>
        <WhySection report={report} onAddStoreUrl={onAddStoreUrl} />

        <SectionHeading>Ranked fixes</SectionHeading>
        <FixList scan={report.scan} />

        <SectionHeading>Exposure calculator</SectionHeading>
        <ExposureCalculator
          revenue={revenue} onRevenueChange={setRevenue}
          aiSharePct={aiSharePct} onAiShareChange={setAiSharePct}
          exposure={exposure}
        />

        <SectionHeading>Go deeper</SectionHeading>
        <LockedPanelsGrid ctaUrl={ctaUrl} />

        <Footer />
      </div>
    </div>
  )
}
