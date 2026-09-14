import { useState } from 'react'
import { tierCounts, tierCountsText, TIER_LABELS } from './generationTierCounts.js'

// ─── Design tokens (verbatim from StudyDetail.jsx) ───────────────────────────
const T = {
  white:       '#FFFFFF',
  offWhite:    '#F8FAFC',
  slate:       '#64748B',
  border:      '#E2E8F0',
  text:        '#0F172A',
  textMid:     '#334155',
  indigo:      '#4F46E5',
  green:       '#16A34A',
  amber:       '#D97706',
  amberLight:  '#FEF3C7',
  red:         '#DC2626',
  redLight:    '#FEE2E2',
}

/**
 * Renders the provenance record a generation job wrote to its own row.
 *
 * The organising principle is the split between what was REMOVED and what
 * was merely FLAGGED, and it is why the two live under separate headings
 * with different language rather than in one combined list of "issues".
 *
 * Exact duplicates and out-of-scope categories are already gone by the
 * time anyone opens this page — the study does not contain them, and the
 * record is the only place they still exist. Semantic duplicates and
 * coherence findings changed nothing at all; every row they name is
 * sitting in the table below, exactly as generated. Presenting those two
 * kinds together would make the second look like work already done, which
 * is the one impression that would stop anyone acting on it.
 */
export default function GenerationReport({ provenance, tierConfig }) {
  const [open, setOpen] = useState(false)

  if (!provenance) return null

  // The live tier config when the page has one, the snapshot taken at
  // generation otherwise. They differ after a tier is regenerated, and
  // it is the live one that describes the study now sitting in the
  // table below this report.
  const counts = tierCounts(tierConfig || provenance.tiers)
  const countsText = tierCountsText(counts)

  const shortfall = provenance.shortfall_by_stage || {}
  const duplicates = provenance.exact_duplicates_dropped || []
  const categoryDrops = provenance.category_drops || []
  const semanticGroups = provenance.semantic_duplicate_groups || []
  const byOutcome = provenance.coherence_findings_by_outcome || {}
  const labelMismatches = byOutcome.label_mismatch || []
  const outOfScope = byOutcome.out_of_scope || []

  // The brand-direct tier's own automatic drops. Same standing as an
  // exact duplicate: the question is not in the study, and this report
  // is the only place it still exists.
  const brandTier = tierConfig?.brand_direct || provenance.tiers?.brand_direct || {}
  const brandMissing = brandTier.brand_missing_drops || []
  const intentDupes = brandTier.intent_duplicate_drops || []

  const removedCount = duplicates.length + categoryDrops.length
    + brandMissing.length + intentDupes.length
  const flaggedCount = semanticGroups.length + labelMismatches.length + outOfScope.length
  const shortStages = Object.keys(shortfall)

  const nothingToReport = !removedCount && !flaggedCount && !shortStages.length

  // counts.total covers every tier; rows_generated covers the stage
  // questions alone, and for a grounded study those are different
  // numbers. Saying the smaller one here is what made the report
  // undercount an 87-question study as 50.
  const generated = counts ? counts.total : provenance.rows_generated
  const shortTiers = counts?.shortfalls || []

  const summary = nothingToReport && !shortTiers.length
    ? `${generated} questions generated, nothing removed or flagged.`
    : [
      `${generated} questions generated`,
      shortTiers.length ? `${shortTiers.length} tier short` : null,
      removedCount ? `${removedCount} removed` : null,
      flaggedCount ? `${flaggedCount} flagged for review` : null,
      shortStages.length ? `short on ${shortStages.join(', ')}` : null,
    ].filter(Boolean).join(' · ')

  return (
    <div style={{
      border: `1px solid ${T.border}`, borderRadius: 8,
      marginBottom: 16, background: T.white,
    }}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: 10,
          padding: '12px 16px', background: 'none', border: 'none',
          cursor: 'pointer', fontFamily: 'inherit', textAlign: 'left',
        }}
      >
        <span style={{ fontSize: 12, color: T.slate, flexShrink: 0 }}>{open ? '▾' : '▸'}</span>
        <span style={{
          fontSize: 13, fontWeight: 700, color: T.text,
          flexShrink: 0, whiteSpace: 'nowrap',
        }}>Generation report</span>
        <span style={{ fontSize: 12, color: T.slate }}>{summary}</span>
        {flaggedCount > 0 && (
          <span style={{
            marginLeft: 'auto', flexShrink: 0, padding: '2px 8px', borderRadius: 99,
            fontSize: 11, fontWeight: 700, color: '#92400E', background: T.amberLight,
          }}>{flaggedCount} to review</span>
        )}
      </button>

      {open && (
        <div style={{
          padding: '4px 16px 16px', display: 'flex', flexDirection: 'column', gap: 18,
        }}>

          {counts && (
            <TierCounts counts={counts} text={countsText} />
          )}

          <Distribution provenance={provenance} shortfall={shortfall} />

          {/* ─── Already removed ─── */}
          {removedCount > 0 && (
            <Section
              title="Removed automatically"
              note="These are not in the study. This report is the only record of them."
            >
              {duplicates.length > 0 && (
                <Group label={`${duplicates.length} exact duplicate${duplicates.length === 1 ? '' : 's'}`}>
                  {duplicates.map((d, i) => (
                    <Line key={i} muted={`${d.stage || '—'}`}>{d.query_text}</Line>
                  ))}
                </Group>
              )}
              {categoryDrops.length > 0 && (
                <Group
                  label={`${categoryDrops.length} outside the study's categories`}
                  hint="Dropped rather than relabelled — a rewrite would turn a scope violation into a clean-looking row."
                >
                  {categoryDrops.map((d, i) => (
                    <Line key={i} muted={d.category}>{d.query_text}</Line>
                  ))}
                </Group>
              )}
              {brandMissing.length > 0 && (
                <Group
                  label={`${brandMissing.length} brand-direct question${brandMissing.length === 1 ? '' : 's'} that did not name the brand`}
                  hint="These carry a brand-mention expectation, so a question that never names the brand cannot be answered correctly. Regenerated rather than patched."
                >
                  {brandMissing.map((d, i) => (
                    <Line key={i}>{d.query_text}</Line>
                  ))}
                </Group>
              )}
              {intentDupes.length > 0 && (
                <Group
                  label={`${intentDupes.length} brand-direct question${intentDupes.length === 1 ? '' : 's'} the catalog tier already asks`}
                  hint="Same question, different words — it would measure one published number twice and score the second copy against a brand mention."
                >
                  {intentDupes.map((d, i) => (
                    <Line key={i}>{d.query_text}</Line>
                  ))}
                </Group>
              )}
            </Section>
          )}

          {/* ─── Flagged only ─── */}
          {flaggedCount > 0 && (
            <Section
              title="Flagged for review"
              note="Nothing here was applied. Every question below is still in the study, exactly as generated."
              accent
            >
              {semanticGroups.length > 0 && (
                <Group label={`${semanticGroups.length} possible duplicate group${semanticGroups.length === 1 ? '' : 's'}`}>
                  {semanticGroups.map((g, i) => (
                    <div key={i} style={{ marginBottom: 10 }}>
                      {(g.member_texts || []).map((text, j) => (
                        <Line key={j} muted={g.members?.[j] === g.keep ? 'suggested keep' : null}>
                          {text}
                        </Line>
                      ))}
                      {g.reason && (
                        <div style={{ fontSize: 11, color: T.slate, marginTop: 2 }}>{g.reason}</div>
                      )}
                    </div>
                  ))}
                </Group>
              )}
              {outOfScope.length > 0 && (
                <Group label={`${outOfScope.length} possibly off-brief`}>
                  {outOfScope.map((f, i) => (
                    <div key={i} style={{ marginBottom: 8 }}>
                      <Line muted={f.category}>{f.query_text}</Line>
                      {f.reason && (
                        <div style={{ fontSize: 11, color: T.slate, marginTop: 2 }}>{f.reason}</div>
                      )}
                    </div>
                  ))}
                </Group>
              )}
              {labelMismatches.length > 0 && (
                <Group label={`${labelMismatches.length} possible mislabel${labelMismatches.length === 1 ? '' : 's'}`}>
                  {labelMismatches.map((f, i) => (
                    <div key={i} style={{ marginBottom: 8 }}>
                      <Line muted={f.field ? `${f.field} → ${f.proposed_value}` : null}>
                        {f.query_text}
                      </Line>
                    </div>
                  ))}
                </Group>
              )}
            </Section>
          )}

          {nothingToReport && (
            <div style={{ fontSize: 12, color: T.slate }}>
              Every stage was filled, nothing was removed, and neither review pass
              found anything worth a second look.
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function TierCounts({ counts, text }) {
  const cells = [
    { label: 'stage', value: counts.stage },
    { label: 'brand-direct', value: counts.brandDirect },
    ...counts.byTier.map(t => ({
      label: TIER_LABELS[t.tier] || t.tier, value: t.count, catalog: true,
    })),
  ].filter(c => c.value > 0)

  return (
    <div>
      <SectionTitle>Questions in this study</SectionTitle>
      <div style={{
        fontSize: 13, color: T.text, marginTop: 6, fontWeight: 600,
      }}>{text}</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
        {cells.map(cell => (
          <div
            key={cell.label}
            style={{
              border: `1px solid ${T.border}`, borderRadius: 8,
              padding: '6px 10px', fontSize: 12,
              background: cell.catalog ? T.offWhite : T.white,
            }}
          >
            <strong style={{ color: T.text }}>{cell.value}</strong>{' '}
            <span style={{ color: T.textMid }}>{cell.label}</span>
          </div>
        ))}
      </div>
      {counts.shortfalls.length > 0 && (
        <div style={{ marginTop: 8 }}>
          {counts.shortfalls.map(s => (
            <div
              key={s.tier}
              style={{
                fontSize: 12, color: '#92400E', background: T.amberLight,
                border: '1px solid #FDE68A', borderRadius: 8,
                padding: '6px 10px', marginTop: 4,
              }}
            >
              {s.reason
                ? `${TIER_LABELS[s.tier] || s.tier} could not be built — ${s.reason}`
                : `${TIER_LABELS[s.tier] || s.tier} is ${s.short} short: `
                  + `${s.delivered} of ${s.requested} requested`}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Distribution({ provenance, shortfall }) {
  const requested = provenance.requested_by_stage || {}
  const delivered = provenance.delivered_by_stage || {}
  const stages = Object.keys(requested)
  if (!stages.length) return null

  return (
    <div>
      <SectionTitle>Questions by stage</SectionTitle>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 6 }}>
        {stages.map(stage => {
          const short = shortfall[stage]
          return (
            <div
              key={stage}
              style={{
                border: `1px solid ${short ? '#FDE68A' : T.border}`,
                background: short ? T.amberLight : T.white,
                borderRadius: 8, padding: '6px 10px', fontSize: 12,
              }}
            >
              <span style={{ color: T.textMid }}>{stage}</span>{' '}
              <strong style={{ color: short ? '#92400E' : T.text }}>
                {delivered[stage] ?? 0}/{requested[stage]}
              </strong>
            </div>
          )
        })}
      </div>
      {provenance.replacement_rounds > 0 && (
        <div style={{ fontSize: 11, color: T.slate, marginTop: 6 }}>
          {provenance.replacement_rounds} replacement round
          {provenance.replacement_rounds === 1 ? '' : 's'} run after removing duplicates.
        </div>
      )}
    </div>
  )
}

function SectionTitle({ children }) {
  return (
    <div style={{
      fontSize: 11, fontWeight: 700, color: T.slate,
      textTransform: 'uppercase', letterSpacing: '0.08em',
    }}>{children}</div>
  )
}

function Section({ title, note, accent, children }) {
  return (
    <div style={{
      borderLeft: `3px solid ${accent ? T.amber : T.border}`,
      paddingLeft: 12,
    }}>
      <SectionTitle>{title}</SectionTitle>
      {note && (
        <div style={{ fontSize: 11, color: T.slate, marginTop: 4, marginBottom: 8 }}>{note}</div>
      )}
      {children}
    </div>
  )
}

function Group({ label, hint, children }) {
  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: T.textMid }}>{label}</div>
      {hint && <div style={{ fontSize: 11, color: T.slate, marginTop: 2 }}>{hint}</div>}
      <div style={{ marginTop: 6 }}>{children}</div>
    </div>
  )
}

function Line({ children, muted }) {
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', marginBottom: 3 }}>
      <span style={{ fontSize: 12, color: T.text }}>{children}</span>
      {muted && <span style={{ fontSize: 11, color: T.slate, flexShrink: 0 }}>{muted}</span>}
    </div>
  )
}
