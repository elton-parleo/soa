import { useState } from 'react'
import { api } from '../api.js'

// ─── Design tokens (verbatim from StudyDetail.jsx) ───────────────────────────
const T = {
  white:       '#FFFFFF',
  offWhite:    '#F8FAFC',
  slate:       '#64748B',
  slateLight:  '#94A3B8',
  border:      '#E2E8F0',
  text:        '#0F172A',
  textMid:     '#334155',
  teal:        '#0D9488',
  tealLight:   '#CCFBF1',
  indigo:      '#4F46E5',
  green:       '#16A34A',
  greenLight:  '#DCFCE7',
  amber:       '#D97706',
  amberLight:  '#FEF3C7',
  amberLine:   '#FCD34D',
  amberInk:    '#78350F',
  red:         '#DC2626',
  redLight:    '#FEE2E2',
  redInk:      '#991B1B',
  greenInk:    '#14532D',
}

// Finding ids are derived from position in the provenance record rather
// than stored on it. Provenance is written once by the worker, and a
// reviewer decision has to be addressable without rewriting what the
// worker wrote — so the id is a function of where the finding sits.
export const dupId = (i) => `dup:${i}`
export const cohId = (verdict, i) => `coh:${verdict}:${i}`

/**
 * Reads the advisory findings out of a provenance record and lets a
 * reviewer act on them.
 *
 * Non-blocking, and it could not be a gate even if that were wanted:
 * rows never reach the client before the worker persists them, so there
 * is no approve-before-save moment to insert. It is also the right shape
 * on its own merits — these are model judgments that will sometimes be
 * wrong, and a fallible reviewer should not be a hard gate.
 *
 * The three sections are visually separated because the separation is
 * load-bearing. Section one is provenance: things already removed during
 * generation, with no actions, because presenting them next to the
 * advisory findings would make the advisory ones read as work already
 * done — which is exactly the impression that stops anyone acting on
 * them. Sections two and three changed nothing; every query they name is
 * still in the table below.
 */
export default function StudyReviewPanel({ studyType, provenance, queries, onResolved }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const [sections, setSections] = useState({ handled: false, dupes: true, problems: true })
  // Which member of a duplicate group the reviewer wants to keep, when it
  // is not the one the model picked. The model's pick is a default, not a
  // decision.
  const [keepOverride, setKeepOverride] = useState({})

  if (!provenance) return null

  const groups = provenance.semantic_duplicate_groups || []
  const byOutcome = provenance.coherence_findings_by_outcome || {}
  const outOfScope = byOutcome.out_of_scope || []
  const labelMismatches = byOutcome.label_mismatch || []
  const resolutions = provenance.review_resolutions || {}

  // Findings carry the query TEXT the worker saw, not a query_code — it
  // did not have one yet, the rows were not inserted at that point. The
  // join back to the live row happens here, by text, which also means a
  // study generated before any of this existed still reviews correctly.
  const byText = new Map((queries || []).map(q => [q.query_text, q]))
  const lookup = (text) => byText.get(text) || null

  const dupFindings = groups.map((g, i) => ({ id: dupId(i), group: g }))
  const scopeFindings = outOfScope.map((f, i) => ({ id: cohId('out_of_scope', i), finding: f }))
  const labelFindings = labelMismatches.map((f, i) => ({ id: cohId('label_mismatch', i), finding: f }))

  const all = [...dupFindings, ...scopeFindings, ...labelFindings]
  const unresolved = all.filter(f => !resolutions[f.id])
  const allResolved = all.length > 0 && unresolved.length === 0

  async function resolve(body) {
    setBusy(body.finding_id)
    setError(null)
    try {
      const result = await api.resolveReviewFinding(studyType, body)
      onResolved(result.provenance)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(null)
    }
  }

  // ─── banner ───────────────────────────────────────────────────────────
  //
  // Persists in a resolved state rather than disappearing once everything
  // is handled. Reviewed-and-cleared is different information from
  // never-had-findings, and a banner that vanishes reports them
  // identically.
  const done = all.length === 0 || allResolved
  const bannerText = all.length === 0
    ? 'Reviewed — this study generated with no findings to look at.'
    : allResolved
      ? `Reviewed — all ${all.length} finding${all.length === 1 ? '' : 's'} resolved.`
      : `${unresolved.length} finding${unresolved.length === 1 ? '' : 's'} to review`

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{
        border: `1px solid ${done ? '#BBF7D0' : T.amberLine}`,
        background: done ? T.greenLight : T.amberLight,
        borderRadius: 12, padding: '14px 18px',
        display: 'flex', alignItems: 'center', gap: 14,
      }}>
        <div style={{
          flex: 1, fontSize: 14, lineHeight: 1.5,
          color: done ? T.greenInk : T.amberInk,
        }}>
          <b style={{ fontWeight: 700 }}>{bannerText}</b>
          {!done && (
            <span> — this study generated cleanly, but a few queries may be redundant or off-brief.</span>
          )}
        </div>
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen(o => !o)}
          style={{
            padding: '8px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600,
            fontFamily: 'inherit', cursor: 'pointer', whiteSpace: 'nowrap',
            background: T.textMid, border: `1px solid ${T.textMid}`, color: T.white,
          }}
        >{open ? 'Hide' : 'Review'}</button>
      </div>

      {open && (
        <div style={{
          background: T.white, border: `1px solid ${T.border}`,
          borderRadius: 12, overflow: 'hidden', marginTop: 12,
        }}>
          {error && (
            <div style={{
              padding: '10px 18px', background: T.redLight,
              borderBottom: `1px solid #FECACA`, fontSize: 13, color: T.redInk,
            }}>{error}</div>
          )}

          <Section
            id="handled"
            title="Already handled"
            count={(provenance.exact_duplicates_dropped || []).length
              + (provenance.category_drops || []).length}
            subtitle="Removed automatically during generation. Nothing to do."
            open={sections.handled}
            onToggle={() => setSections(s => ({ ...s, handled: !s.handled }))}
          >
            <Provenance label="Questions generated" value={provenance.rows_generated ?? 0} />
            <Provenance
              label="Exact duplicates removed"
              value={(provenance.exact_duplicates_dropped || []).length}
            />
            <Provenance
              label="Outside allowed categories, removed"
              value={(provenance.category_drops || []).length}
            />
            <Provenance label="Replacement rounds run" value={provenance.replacement_rounds ?? 0} />
            <Provenance label="Final query count" value={(queries || []).length} />
          </Section>

          <Section
            id="dupes"
            title="Possible duplicates"
            count={dupFindings.filter(f => !resolutions[f.id]).length}
            active
            subtitle="Different wording, same question. Exact matching can't catch these."
            open={sections.dupes}
            onToggle={() => setSections(s => ({ ...s, dupes: !s.dupes }))}
          >
            {dupFindings.length === 0 && <Empty>No redundant groups were found.</Empty>}
            {dupFindings.map(({ id, group }) => (
              <DuplicateGroup
                key={id}
                id={id}
                group={group}
                lookup={lookup}
                resolution={resolutions[id]}
                busy={busy === id}
                keepOverride={keepOverride[id]}
                onKeepOverride={(text) => setKeepOverride(k => ({ ...k, [id]: text }))}
                onResolve={resolve}
              />
            ))}
          </Section>

          <Section
            id="problems"
            title="Possible problems"
            count={[...scopeFindings, ...labelFindings].filter(f => !resolutions[f.id]).length}
            active
            subtitle="Query text that may not match its labels, or may be off-brief entirely."
            open={sections.problems}
            onToggle={() => setSections(s => ({ ...s, problems: !s.problems }))}
          >
            {scopeFindings.length + labelFindings.length === 0 && (
              <Empty>Nothing looked off-brief or mislabelled.</Empty>
            )}
            {scopeFindings.map(({ id, finding }) => (
              <CoherenceFinding
                key={id} id={id} finding={finding} lookup={lookup}
                resolution={resolutions[id]} busy={busy === id} onResolve={resolve}
              />
            ))}
            {labelFindings.map(({ id, finding }) => (
              <CoherenceFinding
                key={id} id={id} finding={finding} lookup={lookup}
                resolution={resolutions[id]} busy={busy === id} onResolve={resolve}
              />
            ))}
          </Section>

          <div style={{
            padding: '13px 18px', borderTop: `1px solid ${T.border}`,
            background: T.offWhite, fontSize: 12, color: T.slate, lineHeight: 1.5,
          }}>
            Deactivating sets a query to Paused rather than deleting it — cycles only run Active
            queries, so it stays visible here and can be restored. Dismissing records that someone
            looked and disagreed.
          </div>
        </div>
      )}
    </div>
  )
}

// ─── duplicate group ─────────────────────────────────────────────────────────

function DuplicateGroup({ id, group, lookup, resolution, busy, keepOverride, onKeepOverride, onResolve }) {
  const texts = group.member_texts || []
  const rows = texts.map(lookup)
  const modelKeepText = group.keep_text ?? texts[0]
  const keepText = keepOverride ?? modelKeepText

  const keepRow = lookup(keepText)
  const otherCodes = rows
    .filter(r => r && r.query_text !== keepText)
    .map(r => r.query_code)

  // A group this large should now be impossible — the generator discards
  // anything over MAX_DUPLICATE_GROUP_SIZE before it reaches provenance.
  // This stays as the last line of defence if that cap ever regresses,
  // and because the panel also renders records written before the cap
  // existed. The failure it exists for rendered a single button reading
  // "Deactivate PRE_080, PRE_083, PRE_086, PRE_089, PRE_092, PRE_095,
  // PRE_098, PRE_099, PRE_100, PRE_101" — ten queries destroyed in one
  // click, the ids overflowing the control.
  const oversized = texts.length > 3
  const [selected, setSelected] = useState([])

  // Deactivating ten must never be a shorter path than deactivating one.
  // Above the threshold the bulk action is withdrawn entirely and each
  // row has to be picked deliberately.
  const dropCodes = oversized
    ? otherCodes.filter(code => selected.includes(code))
    : otherCodes

  const toggle = (code) => setSelected(prev => (
    prev.includes(code) ? prev.filter(c => c !== code) : [...prev, code]
  ))

  return (
    <Finding
      tag="Duplicate group"
      tagStyle={{ background: '#EFF6FF', color: T.indigo }}
      reason={group.reason}
      resolution={resolution}
      busy={busy}
      id={id}
      onResolve={onResolve}
      actions={
        <>
          <GhostButton
            disabled={busy}
            onClick={() => onResolve({ finding_id: id, action: 'dismiss' })}
          >Dismiss — not duplicates</GhostButton>
          <span style={{ flex: 1 }} />
          <SolidButton
            disabled={busy || dropCodes.length === 0}
            onClick={() => onResolve({
              finding_id: id,
              action: 'deactivate',
              query_codes: dropCodes,
              keep_query_code: keepRow ? keepRow.query_code : null,
            })}
          >
            {/* A count, never an id list, once the group is large enough
                for the list to stop being readable. */}
            {oversized
              ? (dropCodes.length
                ? `Deactivate ${dropCodes.length} selected`
                : 'Select queries to deactivate')
              : (dropCodes.length
                ? `Deactivate ${dropCodes.join(', ')}`
                : 'Deactivate the others')}
          </SolidButton>
        </>
      }
    >
      {oversized && !resolution && (
        <div style={{
          padding: '9px 14px', background: T.amberLight,
          borderBottom: `1px solid ${T.border}`, fontSize: 12, color: T.amberInk,
        }}>
          {texts.length} queries in this group — too many to be duplicates of one
          another. Pick individually, or dismiss it.
        </div>
      )}

      {texts.map((text, i) => {
        const row = rows[i]
        const isKeep = text === keepText
        const code = row ? row.query_code : null
        return (
          <QueryLine key={i} row={row} text={text}>
            {resolution ? (
              isKeep ? <KeepChip>Kept</KeepChip> : null
            ) : oversized ? (
              isKeep ? <KeepChip>Keep</KeepChip> : (
                <label style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6,
                  fontSize: 12, color: T.textMid, cursor: code ? 'pointer' : 'not-allowed',
                }}>
                  <input
                    type="checkbox"
                    aria-label={`Deactivate ${code || 'this query'}`}
                    disabled={!code || busy}
                    checked={!!code && selected.includes(code)}
                    onChange={() => code && toggle(code)}
                  />
                  Deactivate
                </label>
              )
            ) : isKeep ? (
              <KeepChip>Keep</KeepChip>
            ) : (
              <LinkButton onClick={() => onKeepOverride(text)}>Keep this</LinkButton>
            )}
          </QueryLine>
        )
      })}
    </Finding>
  )
}

// ─── coherence finding ───────────────────────────────────────────────────────

function CoherenceFinding({ id, finding, lookup, resolution, busy, onResolve }) {
  const row = lookup(finding.query_text)
  const isScope = finding.verdict === 'out_of_scope'

  return (
    <Finding
      tag={isScope ? 'Off-brief' : 'Wrong label'}
      tagStyle={isScope
        ? { background: T.redLight, color: T.redInk }
        : { background: T.amberLight, color: T.amberInk }}
      reason={finding.reason}
      resolution={resolution}
      busy={busy}
      id={id}
      onResolve={onResolve}
      fix={!isScope && finding.field ? (
        <>
          Change <Code>{finding.field}</Code> from{' '}
          {/* Once applied, the live row already holds the proposed value,
              so reading "from" off it would render "from Fragrance to
              Fragrance". The resolution recorded what was actually
              overwritten — that is the honest thing to show afterwards. */}
          <Code>{resolution?.prior_value
            ?? (row ? row[finding.field] : finding.category)}</Code> to{' '}
          <Code>{finding.proposed_value}</Code>
        </>
      ) : null}
      actions={
        <>
          <GhostButton
            disabled={busy}
            onClick={() => onResolve({ finding_id: id, action: 'dismiss' })}
          >{isScope ? 'Dismiss — it belongs' : 'Dismiss — the label is right'}</GhostButton>
          <span style={{ flex: 1 }} />
          {isScope ? (
            <SolidButton
              disabled={busy || !row}
              onClick={() => onResolve({
                finding_id: id, action: 'deactivate',
                query_codes: row ? [row.query_code] : [],
              })}
            >Deactivate {row ? row.query_code : ''}</SolidButton>
          ) : (
            <SolidButton
              disabled={busy || !row || !finding.field}
              onClick={() => onResolve({
                finding_id: id, action: 'apply_label',
                query_code: row ? row.query_code : null,
                field: finding.field,
                proposed_value: finding.proposed_value,
              })}
            >Apply correction</SolidButton>
          )}
        </>
      }
    >
      <QueryLine row={row} text={finding.query_text} />
    </Finding>
  )
}

// ─── shared pieces ───────────────────────────────────────────────────────────

function Finding({ tag, tagStyle, reason, children, fix, actions, resolution, busy, id, onResolve }) {
  return (
    <div style={{
      border: `1px solid ${T.border}`, borderRadius: 10, marginTop: 12,
      overflow: 'hidden', opacity: resolution ? 0.62 : 1,
    }}>
      {/* The reason leads, not the verdict. The reviewer has to be able to
          disagree with the reasoning, which means reading it before the
          action rather than after deciding. */}
      <div style={{
        padding: '10px 14px', background: T.offWhite,
        borderBottom: `1px solid ${T.border}`,
        display: 'flex', alignItems: 'center', gap: 9,
      }}>
        <span style={{
          fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
          letterSpacing: '0.04em', padding: '3px 7px', borderRadius: 4,
          whiteSpace: 'nowrap', ...tagStyle,
        }}>{tag}</span>
        <span style={{ flex: 1, fontSize: 12, color: T.slate, lineHeight: 1.45 }}>
          {reason || 'No reason given.'}
        </span>
      </div>

      {children}

      {fix && (
        <div style={{
          padding: '11px 14px', background: '#EFF6FF', fontSize: 13,
          color: T.textMid, borderBottom: `1px solid ${T.border}`,
        }}>{fix}</div>
      )}

      <div style={{ padding: '10px 14px', display: 'flex', gap: 8, alignItems: 'center' }}>
        {resolution ? (
          <>
            <span style={{ fontSize: 12, color: T.greenInk, fontWeight: 600 }}>
              {describeResolution(resolution)}
            </span>
            <span style={{ flex: 1 }} />
            <LinkButton
              disabled={busy}
              onClick={() => onResolve({ finding_id: id, action: 'undo' })}
            >Undo</LinkButton>
          </>
        ) : actions}
      </div>
    </div>
  )
}

export function describeResolution(resolution) {
  if (!resolution) return ''
  if (resolution.action === 'dismissed') return 'Dismissed — reviewed and disagreed'
  if (resolution.action === 'deactivated') {
    const codes = (resolution.queries || []).map(q => q.query_code).join(', ')
    return codes ? `${codes} deactivated` : 'Deactivated'
  }
  if (resolution.action === 'label_applied') {
    return `Applied — ${resolution.field} set to ${resolution.applied_value}`
  }
  return 'Resolved'
}

function QueryLine({ row, text, children }) {
  return (
    <div style={{
      padding: '11px 14px', borderBottom: `1px solid ${T.border}`,
      display: 'flex', gap: 12, alignItems: 'flex-start',
    }}>
      <span style={{
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
        fontSize: 11, color: T.slate, minWidth: 62, paddingTop: 2,
      }}>{row ? row.query_code : '—'}</span>
      <span style={{ flex: 1, fontSize: 13, color: T.text, lineHeight: 1.5 }}>
        {text}
        {row && (
          <div style={{ fontSize: 11, color: T.slate, marginTop: 4 }}>
            {[row.category, row.stage, row.specificity, row.persona]
              .filter(Boolean).join(' · ')}
            {row.status && row.status !== 'Active' && (
              <span style={{ color: T.amber, fontWeight: 600 }}> · {row.status}</span>
            )}
          </div>
        )}
      </span>
      <span style={{ minWidth: 74, textAlign: 'right', paddingTop: 1 }}>{children}</span>
    </div>
  )
}

function Section({ title, count, subtitle, active, open, onToggle, children }) {
  return (
    <div style={{ borderTop: `1px solid ${T.border}` }}>
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        style={{
          width: '100%', padding: '14px 18px', display: 'flex', alignItems: 'center',
          gap: 10, cursor: 'pointer', background: T.offWhite, border: 'none',
          fontFamily: 'inherit', textAlign: 'left',
        }}
      >
        <span style={{ fontSize: 13, margin: 0, fontWeight: 700, color: T.text }}>{title}</span>
        <span style={{
          fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 999,
          background: active && count > 0 ? T.amberLight : T.white,
          border: `1px solid ${active && count > 0 ? T.amberLine : T.border}`,
          color: active && count > 0 ? T.amberInk : T.slate,
        }}>{count}</span>
        <span style={{ flex: 1, fontSize: 12, color: T.slate }}>{subtitle}</span>
        <span style={{ color: T.slateLight, fontSize: 11 }}>{open ? '▾' : '▸'}</span>
      </button>
      {open && <div style={{ padding: '4px 18px 16px' }}>{children}</div>}
    </div>
  )
}

function Provenance({ label, value }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', padding: '9px 0',
      borderBottom: `1px solid ${T.border}`, fontSize: 13,
    }}>
      <span style={{ color: T.textMid }}>{label}</span>
      <span style={{ color: T.slate, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </div>
  )
}

function Empty({ children }) {
  return <div style={{ fontSize: 12, color: T.slate, paddingTop: 10 }}>{children}</div>
}

function Code({ children }) {
  return (
    <code style={{
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12,
      background: T.white, border: '1px solid #DBEAFE', borderRadius: 4, padding: '1px 5px',
    }}>{children}</code>
  )
}

function KeepChip({ children }) {
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em',
      padding: '3px 7px', borderRadius: 4, background: T.greenLight, color: T.greenInk,
    }}>{children}</span>
  )
}

function LinkButton({ children, onClick, disabled }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        border: 0, background: 'none', padding: 0, fontFamily: 'inherit',
        fontSize: 12, color: T.indigo, cursor: disabled ? 'not-allowed' : 'pointer',
        textDecoration: 'underline', opacity: disabled ? 0.5 : 1,
      }}
    >{children}</button>
  )
}

function GhostButton({ children, onClick, disabled }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: '6px 11px', borderRadius: 8, fontSize: 12, fontWeight: 600,
        fontFamily: 'inherit', cursor: disabled ? 'not-allowed' : 'pointer',
        background: T.white, border: `1px solid ${T.border}`, color: T.textMid,
        opacity: disabled ? 0.5 : 1, whiteSpace: 'nowrap',
      }}
    >{children}</button>
  )
}

function SolidButton({ children, onClick, disabled }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: '6px 11px', borderRadius: 8, fontSize: 12, fontWeight: 600,
        fontFamily: 'inherit', cursor: disabled ? 'not-allowed' : 'pointer',
        background: T.textMid, border: `1px solid ${T.textMid}`, color: T.white,
        opacity: disabled ? 0.5 : 1, whiteSpace: 'nowrap',
      }}
    >{children}</button>
  )
}
