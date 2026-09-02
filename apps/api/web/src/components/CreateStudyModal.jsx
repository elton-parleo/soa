import { useState, useEffect, useMemo, useRef } from 'react'
import { api } from '../api.js'

// ─── Design tokens (verbatim from StudyLibrary.jsx) ──────────────────────────
const T = {
  white:       '#FFFFFF',
  offWhite:    '#F8FAFC',
  slate:       '#64748B',
  slateLight:  '#94A3B8',
  border:      '#E2E8F0',
  borderDark:  '#CBD5E1',
  text:        '#0F172A',
  textMid:     '#334155',
  teal:        '#0D9488',
  tealLight:   '#CCFBF1',
  indigo:      '#4F46E5',
  amber:       '#D97706',
  amberLight:  '#FEF3C7',
  red:         '#DC2626',
  redLight:    '#FEE2E2',
}

// The API validator caps target_count at 100. The modal derives its total
// from the per-stage cells rather than reading a separate total input, so
// the ceiling has to be checked against that derived number.
export const MAX_QUESTIONS = 100

const DEFAULT_TOTAL = 50

export const SPECIFICITY_MODES = [
  { value: 'match_to_stage', label: 'Match to stage',
    hint: 'Broad early in the funnel, narrower toward purchase.' },
  { value: 'even_split', label: 'Even split',
    hint: 'Roughly equal numbers of Broad, Mid and Narrow questions.' },
]

// ─── Stage distribution presets ──────────────────────────────────────────────
//
// Defined by POSITION in the stages array, never by stage name. The stage
// list comes from GET /api/studies/constraints at runtime; a preset that
// named 'Awareness' would silently stop working the day a stage is added,
// which is exactly the coupling the constraints endpoint exists to avoid.
export const PRESETS = [
  {
    value: 'balanced',
    label: 'Balanced',
    hint: 'Equal weight across every funnel stage.',
    weights: (n) => Array(n).fill(1),
  },
  {
    value: 'discovery',
    label: 'Discovery-weighted',
    hint: 'More questions early in the funnel.',
    weights: (n) => Array.from({ length: n }, (_, i) => n - i),
  },
  {
    value: 'decision',
    label: 'Decision-weighted',
    hint: 'More questions close to purchase.',
    weights: (n) => Array.from({ length: n }, (_, i) => i + 1),
  },
  {
    value: 'custom',
    label: 'Custom',
    hint: 'Set each stage yourself.',
    weights: null,
  },
]

/**
 * Splits `total` across `stages` using a preset's positional weights,
 * handing any remainder to the earliest stages so the numbers always sum
 * to exactly `total`.
 */
export function distribute(stages, total, presetValue) {
  const preset = PRESETS.find(p => p.value === presetValue)
  if (!stages.length || !preset || !preset.weights) return {}

  const weights = preset.weights(stages.length)
  const sum = weights.reduce((a, b) => a + b, 0)

  const counts = weights.map(w => Math.floor((total * w) / sum))
  let remainder = total - counts.reduce((a, b) => a + b, 0)
  for (let i = 0; remainder > 0; i = (i + 1) % stages.length) {
    counts[i] += 1
    remainder -= 1
  }

  return Object.fromEntries(stages.map((stage, i) => [stage, counts[i]]))
}

/**
 * Infers categories from the study name and description.
 *
 * Matching is on the category VALUE itself, with whitespace and hyphens
 * stripped from both sides, so "skin care", "Skincare" and "SKINCARE" all
 * reach 'Skincare'. No keyword table: the allowed values come from the
 * constraints endpoint at runtime, and a synonym list maintained here
 * would be one more copy of constants.py to drift out of sync.
 *
 * Returns [] when nothing matches, which the caller renders as its own
 * helper line rather than as an empty selection that looks decided.
 */
export function inferCategories(text, categories) {
  const flat = (text || '').toLowerCase().replace(/[\s\-_/]/g, '')
  if (!flat) return []
  return categories.filter(c => flat.includes(c.toLowerCase().replace(/[\s\-_/]/g, '')))
}

function sameMembers(a, b) {
  return a.length === b.length && a.every((v, i) => v === b[i])
}

// ─── Small shared pieces ─────────────────────────────────────────────────────

const labelStyle = {
  display: 'block', fontSize: 11, fontWeight: 700, color: T.slate,
  textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6,
}

const helperStyle = { fontSize: 11, color: T.slate, marginTop: 6, lineHeight: 1.5 }

const inputStyle = {
  width: '100%', padding: '9px 12px', fontSize: 13, color: T.text,
  background: T.white, border: `1px solid ${T.border}`, borderRadius: 8,
  outline: 'none', fontFamily: "'DM Sans', sans-serif", boxSizing: 'border-box',
}

function Segmented({ options, value, onChange, ariaLabel }) {
  return (
    <div role="radiogroup" aria-label={ariaLabel} style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
      {options.map(opt => {
        const selected = value === opt.value
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(opt.value)}
            style={{
              padding: '7px 12px', fontSize: 12, fontWeight: 600,
              fontFamily: 'inherit', cursor: 'pointer', borderRadius: 8,
              border: `1px solid ${selected ? T.text : T.border}`,
              background: selected ? T.text : T.white,
              color: selected ? T.white : T.textMid,
            }}
          >{opt.label}</button>
        )
      })}
    </div>
  )
}

function Chip({ label, selected, onClick }) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={selected}
      onClick={onClick}
      style={{
        padding: '6px 11px', fontSize: 12, fontWeight: 600, fontFamily: 'inherit',
        cursor: 'pointer', borderRadius: 99,
        border: `1px solid ${selected ? T.teal : T.border}`,
        background: selected ? T.tealLight : T.white,
        color: selected ? '#115E59' : T.textMid,
      }}
    >{label}</button>
  )
}

function Checkbox({ checked, onChange, title, children, disabled = false }) {
  return (
    <label style={{
      display: 'flex', gap: 10, alignItems: 'flex-start',
      cursor: disabled ? 'not-allowed' : 'pointer',
    }}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={e => onChange(e.target.checked)}
        style={{ marginTop: 2, cursor: disabled ? 'not-allowed' : 'pointer' }}
      />
      <span>
        <span style={{ fontSize: 13, fontWeight: 600, color: T.text }}>{title}</span>
        <span style={{ ...helperStyle, marginTop: 3, display: 'block' }}>{children}</span>
      </span>
    </label>
  )
}

// ─── Retailer picker row ─────────────────────────────────────────────────────
//
// Deliberately role-free: no primary, no competitor. These names are
// GENERATION input — they get written into question text. The
// primary-versus-competitor decision belongs to soa_cycle_entities and is
// made at cycle creation, so offering roles here would imply a
// persistence that does not happen.

function RetailerPicker({ entities, value, onChange, onRemove, index }) {
  const [query, setQuery] = useState(value || '')
  const [open, setOpen] = useState(false)
  const wrapperRef = useRef(null)

  useEffect(() => { setQuery(value || '') }, [value])

  useEffect(() => {
    if (!open) return
    function handleClickOutside(e) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  const q = query.trim().toLowerCase()
  const filtered = entities.filter(e => !q || (e.name || '').toLowerCase().includes(q))

  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
      <div ref={wrapperRef} style={{ position: 'relative', flex: 1 }}>
        <input
          role="combobox"
          aria-expanded={open}
          aria-label={`Retailer ${index + 1}`}
          value={query}
          placeholder="Search the entity registry…"
          onChange={e => { setQuery(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)}
          style={inputStyle}
        />
        {open && (
          <div role="listbox" style={{
            position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 10,
            marginTop: 4, maxHeight: 180, overflowY: 'auto',
            border: `1px solid ${T.border}`, borderRadius: 8, background: T.white,
            boxShadow: '0 4px 12px rgba(15, 23, 42, 0.12)',
          }}>
            {filtered.map(e => (
              <div
                key={e.id}
                role="option"
                aria-selected={value === e.name}
                onMouseDown={ev => { ev.preventDefault(); onChange(e.name); setOpen(false) }}
                style={{
                  display: 'flex', gap: 10, alignItems: 'center', padding: '9px 14px',
                  cursor: 'pointer', borderBottom: `1px solid ${T.border}`, fontSize: 13,
                }}
              >
                <span style={{ fontWeight: 600 }}>{e.name}</span>
                <span style={{ fontSize: 11, color: T.slate }}>{e.category}</span>
              </div>
            ))}
            {filtered.length === 0 && (
              <div style={{ padding: 14, fontSize: 12, color: T.slate, textAlign: 'center' }}>
                No matches in the entity registry.
              </div>
            )}
          </div>
        )}
      </div>
      <button
        type="button"
        aria-label={`Remove retailer ${index + 1}`}
        onClick={onRemove}
        style={{
          padding: '9px 12px', background: T.white, color: T.slate,
          border: `1px solid ${T.border}`, borderRadius: 8, cursor: 'pointer',
          fontFamily: 'inherit', fontSize: 13, lineHeight: 1,
        }}
      >×</button>
    </div>
  )
}

// ─── The modal ───────────────────────────────────────────────────────────────

export default function CreateStudyModal({ open, onClose, onCreated }) {
  const [constraints, setConstraints] = useState(null)
  const [entities, setEntities] = useState([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const [studyName, setStudyName] = useState('')
  const [description, setDescription] = useState('')
  const [studyPattern, setStudyPattern] = useState('')
  const [retailers, setRetailers] = useState([''])
  const [rotateFirstNamed, setRotateFirstNamed] = useState(true)
  const [categories, setCategories] = useState([])
  const [preset, setPreset] = useState('balanced')
  const [stageCounts, setStageCounts] = useState({})
  const [namingRule, setNamingRule] = useState(true)
  const [personas, setPersonas] = useState([])
  const [specificityMode, setSpecificityMode] = useState(SPECIFICITY_MODES[0].value)
  const [advancedOpen, setAdvancedOpen] = useState(false)

  // Category inference. `locked` is permanent for the session once the
  // user touches a chip; `resetAvailable` is what the reset control's
  // visibility hangs on.
  //
  // Deliberately NOT an auto/manual mode toggle. An earlier design had
  // one and it was wrong: inference is a derived value, not a rule, so
  // "returning to auto" did nothing at all while the control went on
  // claiming the form was in it. The chips are the truth; inference only
  // ever writes into them.
  const [inferenceLocked, setInferenceLocked] = useState(false)
  const [resetAvailable, setResetAvailable] = useState(false)

  // Memoised on the constraints object, not recomputed per render. A
  // fresh `|| []` every render gives the inference memo below a new
  // dependency identity every render, which makes its effect setState on
  // every render, which re-renders — an infinite loop that only shows up
  // once the component is actually mounted.
  const stages = useMemo(() => constraints?.stage || [], [constraints])
  const allCategories = useMemo(() => constraints?.category || [], [constraints])

  // Everything this form holds, back to its defaults, every time the modal
  // opens.
  //
  // This has to live here rather than in whatever opened it. `open` is a
  // prop and the early return below is AFTER the hooks, so the component
  // stays mounted while closed and keeps every field — a second open would
  // otherwise show the previous study's name, chips and stage counts. The
  // page that renders this used to do the clearing on its way in, which
  // meant a page reaching into form state it did not own, and that seam is
  // exactly what broke: the setters moved in here and the reset was left
  // behind pointing at nothing.
  useEffect(() => {
    if (!open) return

    setStudyName('')
    setDescription('')
    setRetailers([''])
    setRotateFirstNamed(true)
    setCategories([])
    setPreset('balanced')
    setStageCounts({})
    setNamingRule(true)
    setPersonas([])
    setSpecificityMode(SPECIFICITY_MODES[0].value)
    setAdvancedOpen(false)
    setInferenceLocked(false)
    setResetAvailable(false)
    setSubmitting(false)
    setError(null)

    api.getQueryConstraints()
      .then(data => {
        setConstraints(data)
        const stageList = data?.stage || []
        setStageCounts(distribute(stageList, DEFAULT_TOTAL, 'balanced'))
        // Unconditionally, not "only if unset": this is a fresh open, so a
        // pattern picked during the last one is stale, not a value worth
        // preserving.
        if (data?.study_pattern?.length) {
          setStudyPattern(data.study_pattern[0])
        }
      })
      .catch(() => setError('Could not load study options. Please try again.'))
    api.getEntities()
      .then(res => setEntities(Array.isArray(res) ? res : []))
      .catch(() => setEntities([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // Live inference from the name and description as the user types, until
  // the first chip edit locks it.
  const inferred = useMemo(
    () => inferCategories(`${studyName} ${description}`, allCategories),
    [studyName, description, allCategories],
  )

  useEffect(() => {
    if (inferenceLocked) return
    setCategories(prev => (sameMembers(prev, inferred) ? prev : inferred))
  }, [inferred, inferenceLocked])

  const total = Object.values(stageCounts).reduce((a, b) => a + (Number(b) || 0), 0)
  const overCeiling = total > MAX_QUESTIONS

  const namedRetailers = retailers.map(r => (r || '').trim()).filter(Boolean)
  // An empty retailer list IS the unbranded study. It is a valid, and in
  // fact the strictest, share-of-mentions shape: no question names
  // anyone, so every mention in an answer has been earned rather than
  // prompted.
  //
  // Deliberately derived from the list rather than set by a mode control.
  // A toggle claiming "this is unbranded" could disagree with a list that
  // has three retailers in it, and a control that can contradict the
  // state it describes will eventually misreport it — the same reason the
  // categories field has no auto-versus-manual toggle.
  //
  // This used to be a blocking validation error when combined with the
  // naming rule being off. That rule was wrong and is reversed: an empty
  // list is valid whatever the naming rule says, because with no names
  // anywhere the rule has nothing to govern either way.
  const unbranded = namedRetailers.length === 0

  const canSubmit = (
    !!studyName.trim() && total > 0 && !overCeiling && !submitting
  )

  function toggleCategory(category) {
    if (!inferenceLocked) setInferenceLocked(true)
    setResetAvailable(true)
    setCategories(prev => (
      prev.includes(category) ? prev.filter(c => c !== category) : [...prev, category]
    ))
  }

  function resetCategories() {
    // Re-infers from whatever the fields say RIGHT NOW — it is not an
    // undo, and it does not restore an earlier selection.
    setCategories(inferCategories(`${studyName} ${description}`, allCategories))
    setResetAvailable(false)
  }

  function setStageCount(stage, raw) {
    const next = Math.max(0, Number(raw) || 0)
    setStageCounts(prev => ({ ...prev, [stage]: next }))
    setPreset('custom')
  }

  function applyPreset(value) {
    setPreset(value)
    if (value === 'custom') return
    setStageCounts(distribute(stages, total || DEFAULT_TOTAL, value))
  }

  function togglePersona(persona) {
    setPersonas(prev => (
      prev.includes(persona) ? prev.filter(p => p !== persona) : [...prev, persona]
    ))
  }

  async function handleSubmit() {
    if (!canSubmit) return
    setSubmitting(true)
    setError(null)
    try {
      const result = await api.generateStudy({
        study_name:   studyName.trim(),
        description:  description.trim() || null,
        target_count: total,
        study_pattern: studyPattern || null,
        retailer_names: namedRetailers,
        allowed_categories: categories,
        stage_targets: stageCounts,
        rotate_named_retailer: rotateFirstNamed,
        naming_rule_enabled: namingRule,
        personas,
        specificity_mode: specificityMode,
      })
      onCreated(result.study_type)
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (!open) return null

  const presetHint = PRESETS.find(p => p.value === preset)?.hint

  return (
    <div
      onClick={() => { if (!submitting) onClose() }}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', zIndex: 100,
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-label="Create Study with AI"
        style={{
          background: T.white, borderRadius: 12, width: 560, maxWidth: '100%',
          maxHeight: '90vh', display: 'flex', flexDirection: 'column',
          boxShadow: '0 8px 32px rgba(0,0,0,0.16)', fontFamily: "'DM Sans', sans-serif",
        }}
      >
        {/* Header */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '24px 24px 16px', borderBottom: `1px solid ${T.border}`,
        }}>
          <span style={{ fontSize: 18, fontWeight: 700, color: T.text }}>Create Study with AI</span>
          <button
            onClick={() => { if (!submitting) onClose() }}
            disabled={submitting}
            aria-label="Close"
            style={{
              background: 'none', border: 'none', cursor: submitting ? 'not-allowed' : 'pointer',
              fontSize: 18, color: T.slate, lineHeight: 1, padding: 4, fontFamily: 'inherit',
            }}
          >×</button>
        </div>

        {/* Body */}
        <div style={{
          padding: 24, display: 'flex', flexDirection: 'column', gap: 22,
          overflowY: 'auto', flex: 1,
        }}>

          {/* 1. Study name */}
          <div>
            <label style={labelStyle} htmlFor="study-name">Study Name</label>
            <input
              id="study-name"
              type="text"
              value={studyName}
              onChange={e => setStudyName(e.target.value)}
              placeholder="e.g. Prestige Beauty — Retailer Study"
              style={inputStyle}
            />
          </div>

          {/* 2. Study pattern */}
          <div>
            <label style={labelStyle}>Study Pattern</label>
            <Segmented
              ariaLabel="Study Pattern"
              options={(constraints?.study_pattern || []).map(v => ({ value: v, label: v }))}
              value={studyPattern}
              onChange={setStudyPattern}
            />
            <div style={helperStyle}>
              Stamped on every question in this study, so the coding rubric stays the same from row to row.
            </div>
          </div>

          {/* 3. Retailers to name */}
          <div>
            <label style={labelStyle}>Retailers to name in comparison questions</label>

            {/* Informational, never an error or a warning. An unbranded
                study is a deliberate and valid choice — the strictest
                share-of-mentions shape there is — so this states its three
                consequences in the app's informational blue rather than
                the amber or red the form uses for things needing fixing. */}
            {unbranded && (
              <div style={{
                border: '1px solid #BFDBFE', background: '#EFF6FF',
                borderRadius: 8, padding: '13px 15px', marginBottom: 10,
              }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: T.indigo, marginBottom: 5 }}>
                  Unbranded study — no retailers named
                </div>
                <div style={{ fontSize: 12, color: T.textMid, lineHeight: 1.55 }}>
                  Every question describes the need without naming a retailer, so every retailer
                  mention has to be earned. Comparison questions will weigh products and buying
                  criteria rather than one retailer against another. This is the strictest way to
                  measure share of mentions.
                </div>
              </div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {retailers.map((value, i) => (
                <RetailerPicker
                  key={i}
                  index={i}
                  entities={entities}
                  value={value}
                  onChange={name => setRetailers(prev => prev.map((v, j) => (j === i ? name : v)))}
                  onRemove={() => setRetailers(prev => (
                    prev.length === 1 ? [''] : prev.filter((_, j) => j !== i)
                  ))}
                />
              ))}
            </div>
            <button
              type="button"
              onClick={() => setRetailers(prev => [...prev, ''])}
              style={{
                marginTop: 8, padding: '7px 12px', background: T.white, color: T.indigo,
                border: `1px solid ${T.border}`, borderRadius: 8, cursor: 'pointer',
                fontFamily: 'inherit', fontSize: 12, fontWeight: 600,
              }}
            >⊕ Add retailer</button>
            {!unbranded && (
              <div style={helperStyle}>
                These names are written into question text. The primary entity is chosen at cycle
                creation, not here — this list has no roles.
              </div>
            )}

            {/* Rotation is HIDDEN rather than made inert, unlike the naming
                rule below. The difference is whether the control still
                means anything: the naming rule has a subject (where names
                may appear) that survives having no names, so it is worth
                showing greyed with a reason. Spreading head-to-heads over
                an empty list has no subject at all — there is nothing to
                explain, so there is nothing to show. */}
            {!unbranded && (
              <div style={{ marginTop: 12 }}>
                <Checkbox
                  checked={rotateFirstNamed}
                  onChange={setRotateFirstNamed}
                  title="Rotate which retailer is named first"
                >
                  A study that names the same retailer first in ten of eleven head-to-heads cannot be
                  reused with a different primary entity, and reuse across cycles is the point.
                </Checkbox>
              </div>
            )}
          </div>

          {/* 4. Categories */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <label style={labelStyle}>Categories</label>
              {resetAvailable && (
                <button
                  type="button"
                  onClick={resetCategories}
                  style={{
                    background: 'none', border: 'none', padding: 0, cursor: 'pointer',
                    color: T.indigo, fontSize: 11, fontWeight: 600, fontFamily: 'inherit',
                  }}
                >Reset to inferred</button>
              )}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {allCategories.map(c => (
                <Chip
                  key={c}
                  label={c}
                  selected={categories.includes(c)}
                  onClick={() => toggleCategory(c)}
                />
              ))}
            </div>
            <div style={helperStyle}>
              {inferenceLocked
                ? 'Chosen by hand. Reset re-reads the name and description as they are now.'
                : (categories.length === 0
                  ? 'Nothing inferred yet — keep typing the name and description, or pick categories yourself.'
                  : 'Inferred from the study name and description. Picking one takes over.')}
            </div>
          </div>

          {/* 5. Questions by stage */}
          <div>
            <label style={labelStyle}>Questions by stage</label>
            <Segmented
              ariaLabel="Distribution preset"
              options={PRESETS.map(p => ({ value: p.value, label: p.label }))}
              value={preset}
              onChange={applyPreset}
            />
            <div style={{
              display: 'grid', gap: 8, marginTop: 12,
              gridTemplateColumns: `repeat(${Math.min(stages.length || 1, 4)}, 1fr)`,
            }}>
              {stages.map(stage => (
                <div key={stage}>
                  <label
                    htmlFor={`stage-${stage}`}
                    style={{ ...helperStyle, marginTop: 0, marginBottom: 4, display: 'block', fontWeight: 600 }}
                  >{stage}</label>
                  <input
                    id={`stage-${stage}`}
                    type="number"
                    min={0}
                    value={stageCounts[stage] ?? 0}
                    onChange={e => setStageCount(stage, e.target.value)}
                    style={{ ...inputStyle, padding: '8px 10px' }}
                  />
                </div>
              ))}
            </div>
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              marginTop: 10, fontSize: 13,
            }}>
              <span style={{ color: T.slate, fontSize: 11 }}>{presetHint}</span>
              <span style={{ fontWeight: 700, color: overCeiling ? T.red : T.text }}>
                {total} question{total === 1 ? '' : 's'} total
              </span>
            </div>
            {overCeiling && (
              <div style={{
                marginTop: 8, background: T.amberLight, border: `1px solid #FDE68A`,
                borderRadius: 8, padding: '9px 12px', fontSize: 12, color: '#92400E',
              }}>
                That is over the {MAX_QUESTIONS}-question ceiling. Lower one of the stages.
              </div>
            )}
          </div>

          {/* 6. Naming rule — inert, not hidden, when unbranded.
              A control that vanishes leaves the reader wondering where it
              went; one that greys out with a reason teaches how the
              fields relate. The rule governs WHERE names may appear, so
              with no names it has nothing to govern — that is worth
              saying, not worth hiding. */}
          <div>
            {unbranded && (
              <div style={{
                display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8,
              }}>
                <span style={labelStyle}>Naming rule</span>
                <span
                  style={{
                    fontSize: 10, fontWeight: 700, letterSpacing: '0.04em',
                    textTransform: 'uppercase', color: T.slate, background: T.white,
                    border: `1px solid ${T.border}`, borderRadius: 4, padding: '2px 7px',
                    marginBottom: 6,
                  }}
                >Not applicable</span>
              </div>
            )}
            <div style={{ opacity: unbranded ? 0.55 : 1 }}>
              <Checkbox
                checked={namingRule}
                onChange={setNamingRule}
                disabled={unbranded}
                title="Only name entities in Comparison and Ready to Buy questions"
              >
                {unbranded
                  ? 'No retailers are named anywhere in this study, so there is nothing for this rule to restrict.'
                  : 'Awareness and Research questions describe the need without naming a retailer, so a mention there has to be earned rather than prompted.'}
              </Checkbox>
            </div>
          </div>

          {/* 7. What to ask about */}
          <div>
            <label style={labelStyle} htmlFor="study-description">What to ask about</label>
            <textarea
              id="study-description"
              rows={4}
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="e.g. Prestige skincare and fragrance, from a shopper comparing where to buy…"
              style={{ ...inputStyle, resize: 'vertical' }}
            />
            <div style={helperStyle}>
              Subject matter and tone only. Structure — pattern, categories, stage counts, naming —
              is handled by the fields above.
            </div>
          </div>

          {/* 8. Advanced */}
          <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 16 }}>
            <button
              type="button"
              aria-expanded={advancedOpen}
              onClick={() => setAdvancedOpen(o => !o)}
              style={{
                background: 'none', border: 'none', padding: 0, cursor: 'pointer',
                fontFamily: 'inherit', fontSize: 12, fontWeight: 700, color: T.textMid,
              }}
            >{advancedOpen ? '▾' : '▸'} Advanced</button>

            {advancedOpen && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 18, marginTop: 16 }}>
                <div>
                  <label style={labelStyle}>Personas</label>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {(constraints?.persona || []).map(p => (
                      <Chip
                        key={p}
                        label={p}
                        selected={personas.includes(p)}
                        onClick={() => togglePersona(p)}
                      />
                    ))}
                  </div>
                  <div style={helperStyle}>Leave empty to let the generator choose per question.</div>
                </div>

                <div>
                  <label style={labelStyle}>Specificity</label>
                  <Segmented
                    ariaLabel="Specificity"
                    options={SPECIFICITY_MODES}
                    value={specificityMode}
                    onChange={setSpecificityMode}
                  />
                  <div style={helperStyle}>
                    {SPECIFICITY_MODES.find(m => m.value === specificityMode)?.hint}
                  </div>
                </div>
              </div>
            )}
          </div>

          {error && (
            <div style={{
              background: T.redLight, border: '1px solid #FECACA', borderRadius: 8,
              padding: '10px 14px', fontSize: 13, color: '#991B1B',
            }}>{error}</div>
          )}
        </div>

        {/* Footer */}
        <div style={{
          padding: '16px 24px', borderTop: `1px solid ${T.border}`,
          display: 'flex', justifyContent: 'flex-end', gap: 12,
        }}>
          <button
            onClick={() => { if (!submitting) onClose() }}
            disabled={submitting}
            style={{
              padding: '9px 18px', background: T.white, color: T.text,
              border: `1px solid ${T.border}`, borderRadius: 8, fontWeight: 600,
              fontSize: 13, fontFamily: 'inherit',
              cursor: submitting ? 'not-allowed' : 'pointer', opacity: submitting ? 0.6 : 1,
            }}
          >Cancel</button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            style={{
              padding: '9px 18px', background: T.text, color: T.white, border: 'none',
              borderRadius: 8, fontWeight: 700, fontSize: 13, fontFamily: 'inherit',
              cursor: canSubmit ? 'pointer' : 'not-allowed', opacity: canSubmit ? 1 : 0.6,
            }}
          >{submitting ? '⏳ Generating...' : '✨ Generate Questions'}</button>
        </div>
      </div>
    </div>
  )
}
