// NewCycleFlow — Full Analysis coexistence, Phase 2: the 3-step cycle
// creation flow that becomes the paid product's default entry point.
// The classic 6-step NewCycleWizard.jsx is untouched and stays reachable
// as "Advanced setup" (see the link in Step3's footer and App.jsx's
// routing). No design mock exists for this flow (design-refs/ only has
// the audit/lite report's own refs) — built from the written spec,
// reusing NewCycleWizard's design tokens/patterns where they fit.
import React, { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '../api.js'
import { StatusChip } from '../ds/index.js'

// ─── Design tokens — mirrors NewCycleWizard.jsx's T object exactly ────────
const T = {
  navy:        '#0D1829',
  navyMid:     '#162032',
  navyBdr:     '#1E2D42',
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
  green:       '#16A34A',
  greenLight:  '#DCFCE7',
  amber:       '#D97706',
  amberLight:  '#FEF3C7',
  red:         '#DC2626',
  redLight:    '#FEE2E2',
}

const STEP_LABELS = ['Brand & Competitors', 'Study & Queries', 'Review & Launch']

// Depth presets (Phase 2 spec): platforms × runs-per-query behind one
// dial instead of raw controls. Perplexity stays visibly listed but
// marked unavailable on every preset — never silently dropped from the
// launch payload (same discipline NewCycleWizard.jsx already applies by
// disabling it in PLATFORMS).
const PLATFORM_META = [
  { id: 'chatgpt',    name: 'ChatGPT',    available: true },
  { id: 'gemini',     name: 'Gemini',     available: true },
  { id: 'claude',     name: 'Claude',     available: true },
  { id: 'perplexity', name: 'Perplexity', available: false },
]

const DEPTH_PRESETS = [
  {
    id: 'standard', name: 'Standard', description: 'ChatGPT + Gemini, 3 runs per query.',
    platforms: ['chatgpt', 'gemini'], runsPerQuery: 3,
  },
  {
    id: 'deep', name: 'Deep', description: 'ChatGPT + Gemini + Claude, 5 runs per query.',
    platforms: ['chatgpt', 'gemini', 'claude'], runsPerQuery: 5,
  },
]

// Monthly/quarterly are visibly present but disabled — recurring
// execution isn't automated yet (see Step2's own note below), so
// selecting either would persist an intent the product can't act on.
// Kept as real option values (not removed) so turning them on later is
// a one-line change, not a rebuild of this list.
const RECURRENCE_OPTIONS = [
  { id: 'none',      label: 'One-time' },
  { id: 'monthly',   label: 'Monthly',   disabled: true },
  { id: 'quarterly', label: 'Quarterly', disabled: true },
]

// Query generation polls every 3s (same interval as StudyDetail.jsx) —
// capped so a stuck job doesn't poll forever; a timeout renders the
// same honest notice+retry as a genuine failure, never a silent reset.
const GENERATION_POLL_INTERVAL_MS = 3000
const GENERATION_MAX_POLLS = 40 // 40 * 3s = 120s

const INITIAL_STATE = {
  // Step 1
  primaryEntity: null,     // {id, name, category, ...} — from entity catalog or the audit
  storeUrl: '',
  competitors: [],         // [{name, entity_id, domain}]
  // Continuation mode (set once the audit resolves)
  continuation: null,      // full AuditContinuationResponse payload, or null
  sourceLiteRequestId: null,
  priorCycleId: null,
  // Step 2
  studyType: null,         // {id, name, ...}
  depth: 'standard',
  queries: [],
  queriesVisible: false,
  recurrence: 'none',
  // Step 3
  cycleCode: '',
  notes: '',
}

function studySeriesId(existing) {
  // Stamped once, the first time a cycle in a series is created — a
  // continuation's own study_series_id if one already exists (future
  // cycles in the same series share it), otherwise a fresh client id.
  return existing || `series-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

function matchesSearch(entity, query) {
  if (!query) return true
  const q = query.toLowerCase()
  return (
    entity.name?.toLowerCase().includes(q) ||
    entity.category?.toLowerCase().includes(q) ||
    entity.type?.toLowerCase().includes(q)
  )
}

// ─── Entity combobox ────────────────────────────────────────────────────
//
// A real combobox, not a search box glued to an always-open list:
// selecting an option commits it (input shows the name, dropdown
// closes, the entity id is stored via onChange); editing the text
// afterward clears the stored selection until a new option is chosen —
// typed text alone is never treated as a selection. `value` is the
// controlled selection (an entity object or null); the input's own text
// is internal state, synced from `value` whenever it changes externally
// (continuation mode pre-filling it, or a parent-level reset).

function EntityCombobox({ entities, value, onChange, placeholder, onCreate, createLabel }) {
  const [query, setQuery] = useState(value?.name || '')
  const [open, setOpen] = useState(false)
  const [highlighted, setHighlighted] = useState(-1)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState(null)
  const wrapperRef = useRef(null)

  // A value set from OUTSIDE this component (continuation mode's
  // pre-fill) always renders as a committed, closed input — never an
  // open dropdown mid-query. Deliberately does NOT sync on value
  // becoming null: that happens via this component's own onChange(null)
  // in handleInputChange, which already set query/open itself for the
  // edit in progress — re-syncing here would immediately stomp it back
  // to a blank, closed field on every keystroke after a selection.
  useEffect(() => {
    if (!value) return
    setQuery(value.name || '')
    setOpen(false)
    setHighlighted(-1)
  }, [value?.id])

  useEffect(() => {
    if (!open) return
    function handleClickOutside(e) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  const filtered = entities.filter(e => matchesSearch(e, query))
  const trimmedQuery = query.trim()
  // The registry's own create endpoint (api.createEntity, reused as-is
  // below) has no dedup check of its own — every call mints a new row
  // with a uniquified slug, so two entities can share a display name.
  // This combobox is the one place that matters (it's how a duplicate
  // would get created), so the dedup check lives here: an exact,
  // case-insensitive name match is surfaced and selected instead of
  // creating a near-identical row.
  const exactMatch = trimmedQuery
    ? entities.find(e => e.name.toLowerCase() === trimmedQuery.toLowerCase())
    : null
  const showCreateOption = !!onCreate && !!trimmedQuery && !exactMatch

  const selectEntity = (entity) => {
    setQuery(entity.name)
    setOpen(false)
    setHighlighted(-1)
    setCreateError(null)
    onChange(entity)
  }

  const handleCreate = async () => {
    if (!trimmedQuery || creating) return
    // Re-check immediately before creating — entities may have been
    // refreshed since the option rendered, and creating is never worth
    // racing against a dupe that just appeared.
    const nowExisting = entities.find(e => e.name.toLowerCase() === trimmedQuery.toLowerCase())
    if (nowExisting) { selectEntity(nowExisting); return }
    setCreating(true)
    setCreateError(null)
    try {
      const created = await onCreate(trimmedQuery)
      selectEntity(created)
    } catch (err) {
      setCreateError(err.message || 'Could not create this brand.')
    } finally {
      setCreating(false)
    }
  }

  const handleInputChange = (e) => {
    const val = e.target.value
    setQuery(val)
    setOpen(true)
    setHighlighted(-1)
    setCreateError(null)
    // Editing after a selection clears it — the stored selection and
    // the raw text must never silently drift apart.
    if (value) onChange(null)
  }

  // The create row (when shown) is one more selectable option, appended
  // after every filtered match — index filtered.length.
  const lastIndex = filtered.length - (showCreateOption ? 0 : 1)

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') {
      setOpen(false)
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (!open) { setOpen(true); return }
      setHighlighted(h => Math.min(h + 1, lastIndex))
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlighted(h => Math.max(h - 1, 0))
      return
    }
    if (e.key === 'Enter' && open && highlighted >= 0) {
      e.preventDefault()
      if (filtered[highlighted]) {
        selectEntity(filtered[highlighted])
      } else if (showCreateOption && highlighted === filtered.length) {
        handleCreate()
      }
    }
  }

  return (
    <div ref={wrapperRef} style={{ position: 'relative' }}>
      <input
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        placeholder={placeholder}
        value={query}
        onChange={handleInputChange}
        onFocus={() => setOpen(true)}
        onKeyDown={handleKeyDown}
        style={{ width: '100%', padding: '10px 12px', border: `1px solid ${T.border}`, borderRadius: 8, fontSize: 13, outline: 'none', boxSizing: 'border-box' }}
      />
      {open && (
        <div role="listbox" style={{
          position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 10, marginTop: 4,
          maxHeight: 200, overflowY: 'auto', border: `1px solid ${T.border}`, borderRadius: 8,
          background: T.white, boxShadow: '0 4px 12px rgba(15, 23, 42, 0.12)',
        }}>
          {filtered.map((e, i) => (
            <div key={e.id} role="option" aria-selected={value?.id === e.id}
              onMouseDown={ev => { ev.preventDefault(); selectEntity(e) }}
              onMouseEnter={() => setHighlighted(i)}
              style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '9px 14px', cursor: 'pointer',
                borderBottom: `1px solid ${T.border}`,
                background: i === highlighted ? T.tealLight : (value?.id === e.id ? T.offWhite : T.white),
              }}>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{e.name}</div>
              <div style={{ fontSize: 11, color: T.slate }}>{e.category}</div>
              {value?.id === e.id && <span style={{ marginLeft: 'auto', color: T.teal, fontSize: 12 }}>✓ Selected</span>}
            </div>
          ))}
          {showCreateOption && (
            <div role="option" aria-selected={false}
              onMouseDown={ev => { ev.preventDefault(); handleCreate() }}
              onMouseEnter={() => setHighlighted(filtered.length)}
              style={{
                display: 'flex', alignItems: 'center', gap: 8, padding: '9px 14px', cursor: creating ? 'default' : 'pointer',
                color: T.indigo, fontWeight: 600, fontSize: 13,
                background: highlighted === filtered.length ? T.tealLight : T.white,
              }}>
              {creating ? 'Creating…' : `⊕ Create "${trimmedQuery}" as a new ${createLabel || 'brand'}`}
            </div>
          )}
          {filtered.length === 0 && !showCreateOption && (
            <div style={{ padding: 16, textAlign: 'center', color: T.slate, fontSize: 13 }}>No matches — try a different search.</div>
          )}
          {createError && (
            <div style={{ padding: '10px 14px', color: T.red, fontSize: 12, borderTop: `1px solid ${T.border}` }}>{createError}</div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Shared bits ────────────────────────────────────────────────────────

function Badge({ children, color = T.slate, bg = T.offWhite }) {
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 99,
      fontSize: 11, fontWeight: 600, color, background: bg, border: `1px solid ${color}22`,
    }}>
      {children}
    </span>
  )
}

function StepIndicator({ current }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, padding: '20px 32px', background: T.white, borderBottom: `1px solid ${T.border}` }}>
      {STEP_LABELS.map((label, i) => {
        const step = i + 1
        const done = step < current
        const active = step === current
        return (
          <React.Fragment key={step}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
              <div style={{
                width: 32, height: 32, borderRadius: '50%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 13, fontWeight: 700,
                background: done ? T.navy : active ? T.white : T.offWhite,
                color: done ? T.white : active ? T.navy : T.slate,
                border: `2px solid ${done || active ? T.navy : T.border}`,
                flexShrink: 0,
              }}>
                {done ? '✓' : step}
              </div>
              <span style={{ fontSize: 11, fontWeight: active ? 600 : 400, color: active ? T.text : T.slate, whiteSpace: 'nowrap' }}>
                {label}
              </span>
            </div>
            {i < STEP_LABELS.length - 1 && (
              <div style={{ flex: 1, height: 2, background: done ? T.navy : T.border, margin: '0 8px', marginBottom: 22 }} />
            )}
          </React.Fragment>
        )
      })}
    </div>
  )
}

function NavButtons({ onBack, onNext, nextLabel = 'Next →', nextDisabled = false }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 28 }}>
      {onBack ? (
        <button onClick={onBack} style={{ padding: '10px 20px', borderRadius: 8, border: `1px solid ${T.border}`, background: T.white, fontWeight: 600, fontSize: 14, cursor: 'pointer' }}>
          ← Back
        </button>
      ) : <span />}
      <button onClick={onNext} disabled={nextDisabled}
        style={{ padding: '10px 24px', borderRadius: 8, border: 'none', background: nextDisabled ? T.border : T.navy, color: nextDisabled ? T.slate : T.white, fontWeight: 600, fontSize: 14, cursor: nextDisabled ? 'not-allowed' : 'pointer' }}>
        {nextLabel}
      </button>
    </div>
  )
}

// ─── Step 1: Brand & Competitors ───────────────────────────────────────

function ContinuationCard({ continuation, onEdit }) {
  const scored = continuation.composite != null
  return (
    <div style={{ padding: 20, borderRadius: 12, border: `1px solid ${T.teal}`, background: T.tealLight, marginBottom: 24 }}>
      <div style={{ fontWeight: 700, fontSize: 15, color: T.text, marginBottom: 4 }}>
        Continuing from your audit of {continuation.brand_name}
        {scored && `, scored ${continuation.composite} on ${continuation.audited_at || 'a recent date'}`}
      </div>
      <div style={{ fontSize: 13, color: T.textMid, marginBottom: 12 }}>
        {continuation.competitors.length > 0
          ? `Competitors: ${continuation.competitors.map(c => c.name).join(', ')}`
          : 'No competitors were tracked on the audit.'}
        {continuation.category && ` · Category: ${continuation.category}`}
      </div>
      <button onClick={onEdit} style={{ background: 'none', border: 'none', color: T.indigo, fontWeight: 600, fontSize: 13, cursor: 'pointer', padding: 0 }}>
        Edit brand & competitors
      </button>
    </div>
  )
}

function Step1({ state, setState, onNext, auditToken }) {
  const [entities, setEntities] = useState([])
  const [editingContinuation, setEditingContinuation] = useState(false)
  const [continuationLoading, setContinuationLoading] = useState(!!auditToken)
  const [continuationError, setContinuationError] = useState(null)
  const [suggesting, setSuggesting] = useState(false)
  const [suggestDegraded, setSuggestDegraded] = useState(false)
  const [manualCompetitor, setManualCompetitor] = useState('')

  // Continuation mode: pre-resolve brand/competitors/category from the
  // audit the instant a token is present, collapsing step 1 into a
  // confirmation card (Phase 2 spec).
  useEffect(() => {
    if (!auditToken) return
    let cancelled = false
    setContinuationLoading(true)
    api.getAuditContinuation(auditToken)
      .then(res => {
        if (cancelled) return
        setState(s => ({
          ...s,
          continuation: res,
          sourceLiteRequestId: res.lite_request_id,
          priorCycleId: res.cycle_id,
          primaryEntity: res.brand_entity_id
            ? { id: res.brand_entity_id, name: res.brand_name, category: res.category }
            : s.primaryEntity,
          storeUrl: res.store_url || s.storeUrl,
          competitors: res.competitors.length
            ? res.competitors.map(c => ({ name: c.name, entity_id: c.entity_id, domain: null }))
            : s.competitors,
        }))
      })
      .catch(err => { if (!cancelled) setContinuationError(err.message) })
      .finally(() => { if (!cancelled) setContinuationLoading(false) })
    return () => { cancelled = true }
  }, [auditToken])

  useEffect(() => {
    // api.js's request() resolves (never rejects) with `undefined` on a
    // 401 — it signs out and reloads the page instead of throwing, so
    // .catch() below never sees that case. Without this guard,
    // setEntities(undefined) makes the next render's entities.filter(...)
    // throw, which unmounts this whole step with no error boundary above
    // it — on a stale/expired session, the picker never renders at all
    // instead of showing an empty/error state.
    api.getEntities().then(res => setEntities(Array.isArray(res) ? res : [])).catch(() => {})
  }, [])

  // Reuses the registry's own create endpoint and validation (api.
  // createEntity, POST /api/entities) rather than a parallel create
  // path — same request shape EntityRegistry.jsx sends for a brand-new
  // entity, type defaulted to 'Brand' since this step has no type
  // selector of its own. The dedup check itself lives in EntityCombobox
  // (the registry endpoint has none), so by the time this is called the
  // name is already believed to be new; entities is still re-appended
  // to here (not just left to a refetch) so the combobox's own list is
  // immediately consistent if it's reopened.
  const handleCreateEntity = async (name) => {
    const created = await api.createEntity({ name, type: 'Brand', category: '', website_url: null, aliases: [] })
    setEntities(list => [...list, created])
    return created
  }

  const handleSuggest = async () => {
    if (!state.primaryEntity) return
    setSuggesting(true)
    setSuggestDegraded(false)
    try {
      const res = await api.suggestCompetitors({
        brand_name: state.primaryEntity.name,
        store_url: state.storeUrl || null,
        category_hint: state.primaryEntity.category || null,
        manual_names: state.competitors.map(c => c.name),
      })
      setState(s => ({ ...s, competitors: res.competitors.map(c => ({ name: c.name, domain: c.domain, entity_id: null })) }))
      // Backend-reported degradation (e.g. no suggestion API key
      // configured) — an honest notice, never a silent empty result the
      // visitor can't tell apart from "this brand genuinely has no
      // competitors" (res.status === 'ok' with an empty list).
      if (res.status === 'degraded') setSuggestDegraded(true)
    } catch (_) {
      // A request that errors or times out gets the SAME honest notice
      // as a backend-reported degradation — never blocks the flow,
      // manual entry always remains available.
      setSuggestDegraded(true)
    } finally {
      setSuggesting(false)
    }
  }

  const addManualCompetitor = () => {
    const name = manualCompetitor.trim()
    if (!name || state.competitors.some(c => c.name.toLowerCase() === name.toLowerCase())) return
    setState(s => ({ ...s, competitors: [...s.competitors, { name, entity_id: null, domain: null }] }))
    setManualCompetitor('')
  }

  const removeCompetitor = (name) => {
    setState(s => ({ ...s, competitors: s.competitors.filter(c => c.name !== name) }))
  }

  const showContinuationCard = auditToken && state.continuation && !editingContinuation
  const isValid = !!state.primaryEntity

  if (auditToken && continuationLoading) {
    return <div style={{ padding: 32, color: T.slate, fontSize: 14 }}>Loading your audit…</div>
  }

  return (
    <div style={{ padding: 32, maxWidth: 720 }}>
      <h2 style={{ margin: '0 0 4px', fontSize: 20, fontWeight: 700, color: T.text }}>Brand & Competitors</h2>
      <p style={{ margin: '0 0 20px', color: T.slate, fontSize: 14 }}>Pick the brand this analysis measures, then confirm who it competes against.</p>

      {continuationError && (
        <div style={{ padding: 12, borderRadius: 8, background: T.redLight, color: T.red, fontSize: 13, marginBottom: 16 }}>
          Couldn't load the audit ({continuationError}) — continuing without it.
        </div>
      )}

      {showContinuationCard ? (
        <ContinuationCard continuation={state.continuation} onEdit={() => setEditingContinuation(true)} />
      ) : (
        <>
          <div style={{ marginBottom: 20 }}>
            <label style={{ fontWeight: 600, fontSize: 13, display: 'block', marginBottom: 8 }}>Primary brand</label>
            <EntityCombobox
              entities={entities}
              value={state.primaryEntity}
              onChange={entity => setState(s => ({ ...s, primaryEntity: entity }))}
              placeholder="Search entities by name, type, or category…"
              onCreate={handleCreateEntity}
            />
          </div>

          <div style={{ marginBottom: 20 }}>
            <label style={{ fontWeight: 600, fontSize: 13, display: 'block', marginBottom: 8 }}>Storefront URL</label>
            <input
              placeholder="https://example.com"
              value={state.storeUrl}
              onChange={e => setState(s => ({ ...s, storeUrl: e.target.value }))}
              style={{ width: '100%', padding: '10px 12px', border: `1px solid ${T.border}`, borderRadius: 8, fontSize: 13, outline: 'none', boxSizing: 'border-box' }}
            />
            <div style={{ fontSize: 11, color: T.slate, marginTop: 6 }}>Used to crawl accessibility/catalog signal at launch.</div>
          </div>
        </>
      )}

      <div style={{ marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <label style={{ fontWeight: 600, fontSize: 13 }}>Competitors</label>
          <button onClick={handleSuggest} disabled={!state.primaryEntity || suggesting}
            style={{ background: 'none', border: `1px solid ${T.indigo}`, color: T.indigo, borderRadius: 6, padding: '4px 10px', fontSize: 12, fontWeight: 600, cursor: state.primaryEntity ? 'pointer' : 'not-allowed', opacity: state.primaryEntity ? 1 : 0.5 }}>
            {suggesting ? 'Suggesting…' : '✦ Auto-suggest'}
          </button>
        </div>
        {suggestDegraded && (
          <div style={{ marginBottom: 10 }}>
            <StatusChip tone="warning" size="sm">Suggestions are unavailable — add competitors manually.</StatusChip>
          </div>
        )}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
          {state.competitors.map(c => (
            <span key={c.name} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '5px 10px', borderRadius: 99, background: T.offWhite, border: `1px solid ${T.border}`, fontSize: 12, fontWeight: 500 }}>
              {c.name}
              <button onClick={() => removeCompetitor(c.name)} style={{ background: 'none', border: 'none', color: T.slate, cursor: 'pointer', fontSize: 13, lineHeight: 1, padding: 0 }}>✕</button>
            </span>
          ))}
          {state.competitors.length === 0 && <span style={{ fontSize: 12, color: T.slate }}>No competitors yet — suggest or add manually.</span>}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            placeholder="Add a competitor by name"
            value={manualCompetitor}
            onChange={e => setManualCompetitor(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addManualCompetitor() } }}
            style={{ flex: 1, padding: '8px 12px', border: `1px solid ${T.border}`, borderRadius: 8, fontSize: 13, outline: 'none' }}
          />
          <button onClick={addManualCompetitor} style={{ padding: '8px 14px', borderRadius: 8, border: `1px solid ${T.border}`, background: T.white, fontWeight: 600, fontSize: 13, cursor: 'pointer' }}>
            Add
          </button>
        </div>
      </div>

      <NavButtons onNext={onNext} nextDisabled={!isValid} nextLabel="Next: Study & Queries →" />
    </div>
  )
}

// ─── Step 2: Study & Queries ────────────────────────────────────────────

function Step2({ state, setState, onNext, onBack }) {
  const [studies, setStudies] = useState([])
  const [genLoading, setGenLoading] = useState(false)
  const [genError, setGenError] = useState(null)
  const [genStatus, setGenStatus] = useState(null)
  const [lastGenerateArgs, setLastGenerateArgs] = useState(null)
  // Guards api.getQueryRows against out-of-order responses. The
  // "study just selected/generated" effect below fires an initial fetch
  // immediately — for a freshly generated study that's still 0 rows,
  // since the worker hasn't picked the job up yet. Under real network
  // jitter that request can resolve AFTER the generation-complete
  // refetch (issued seconds later, once polling reaches a terminal
  // status) lands its real rows, silently clobbering the count back to
  // 0 with stale data. Every fetch gets a ticket; a response only
  // applies if its ticket is still the most recent one issued, so a
  // late-arriving stale response is discarded instead of winning.
  const queriesReqIdRef = useRef(0)

  const refetchQueries = useCallback((studyTypeId) => {
    const reqId = ++queriesReqIdRef.current
    // api.getQueryRows (GET /studies/{type}/query-rows) returns the
    // actual [{query_code, query_text, ...}] array this step renders.
    // api.getStudyQueries (GET /studies/{type}/queries) is a DIFFERENT
    // endpoint — a {study_type, total, by_pattern} count breakdown, not
    // an array — using it here was the root cause of an earlier reset
    // bug: .map()/.length on that object throws once queriesVisible
    // flips true, and with no error boundary anywhere in this app, an
    // uncaught render error unmounts the whole tree.
    return api.getQueryRows(studyTypeId).then(rows => {
      if (queriesReqIdRef.current !== reqId) return // superseded — discard
      setState(s => ({ ...s, queries: Array.isArray(rows) ? rows : [] }))
    })
  }, [setState])

  useEffect(() => {
    api.getStudies().then(setStudies).catch(() => {})
  }, [])

  useEffect(() => {
    if (!state.studyType?.id) return
    refetchQueries(state.studyType.id).catch(() => {})
  }, [state.studyType?.id])

  // Poll a just-launched generation job — same 3s interval as
  // StudyDetail.jsx, so step 2 never sits on the dead-end empty state
  // the classic wizard leaves generation in. Capped at
  // GENERATION_MAX_POLLS: a stuck job must not poll forever, but a
  // timeout is reported the same honest way as a real failure, never a
  // silent reset.
  useEffect(() => {
    if (!genLoading || !state.studyType?.id) return
    const studyTypeId = state.studyType.id
    let cancelled = false
    let attempts = 0
    const interval = setInterval(async () => {
      attempts += 1
      try {
        const status = await api.getGenerationStatus(studyTypeId)
        if (cancelled) return
        setGenStatus(status)

        if (status.status === 'complete' || status.status === 'failed') {
          clearInterval(interval)
          setGenLoading(false)
          // A job can legitimately reach 'complete' with zero rows
          // (generation returned nothing on both attempts of the very
          // first batch — worker.py's early-break path) — that's not a
          // genuine success, and must not render as an empty-but-normal
          // study. created_count already reflects committed rows (it's
          // updated in the same commit as each batch's inserts), so no
          // new backend field is needed to detect this honestly.
          if (status.status === 'complete' && (status.created_count || 0) > 0) {
            await Promise.all([
              refetchQueries(studyTypeId).catch(() => {}),
              // The new study only appears in /api/studies once it has
              // at least one committed Active query (that endpoint only
              // returns study_types with Active rows) — refetch now so
              // the dropdown's <option> list matches reality.
              api.getStudies().then(list => { if (!cancelled) setStudies(list) }).catch(() => {}),
            ])
            if (!cancelled) setState(s => ({ ...s, queriesVisible: true }))
          } else if (status.status === 'failed') {
            setGenError(status.error_message || 'Query generation failed.')
          } else {
            setGenError('Query generation finished without creating any queries.')
          }
          return
        }

        if (attempts >= GENERATION_MAX_POLLS) {
          clearInterval(interval)
          setGenLoading(false)
          setGenError('Query generation is taking longer than expected.')
        }
      } catch (_) {
        if (!cancelled) {
          clearInterval(interval)
          setGenLoading(false)
          setGenError('Lost connection while checking generation status.')
        }
      }
    }, GENERATION_POLL_INTERVAL_MS)
    return () => { cancelled = true; clearInterval(interval) }
  }, [genLoading, state.studyType?.id])

  const handleGenerate = async (name, description) => {
    setGenError(null)
    setGenLoading(true)
    setGenStatus(null)
    setLastGenerateArgs({ name, description })
    try {
      const result = await api.generateStudy({ study_name: name, description: description || null, target_count: 50 })
      // Synthesize the new study into the local list immediately — a
      // fresh study has zero committed queries, so /api/studies (which
      // only returns study_types with at least one Active query) won't
      // include it yet, and without this the <select> would show an
      // orphan value (no matching <option>) for the whole generation
      // run, silently falling back to its placeholder.
      setStudies(list => (
        list.some(s => s.id === result.study_type)
          ? list
          : [...list, { id: result.study_type, name, category: '', patterns: [], queryCount: 0, lastRun: null }]
      ))
      setState(s => ({ ...s, studyType: { id: result.study_type, name }, queries: [], queriesVisible: false }))
    } catch (err) {
      setGenError(err.message || 'Could not start query generation.')
      setGenLoading(false)
    }
  }

  const handleRetryGenerate = () => {
    if (lastGenerateArgs) handleGenerate(lastGenerateArgs.name, lastGenerateArgs.description)
  }

  const depthPreset = DEPTH_PRESETS.find(d => d.id === state.depth) || DEPTH_PRESETS[0]
  // Next requires a COMMITTED study selection with real, fetched query
  // rows behind it — never just an id in state (a freshly generated
  // study starts with studyType.id set and queries: [] until generation
  // actually finishes) and never while generation is still in flight,
  // mirroring Step1's "validation reads stored state" rule.
  const isValid = !!state.studyType?.id && state.queries.length > 0 && !genLoading

  return (
    <div style={{ padding: 32, maxWidth: 720 }}>
      <h2 style={{ margin: '0 0 4px', fontSize: 20, fontWeight: 700, color: T.text }}>Study & Queries</h2>
      <p style={{ margin: '0 0 20px', color: T.slate, fontSize: 14 }}>Choose what this cycle asks, and how thoroughly.</p>

      <div style={{ marginBottom: 20 }}>
        <label style={{ fontWeight: 600, fontSize: 13, display: 'block', marginBottom: 8 }}>Study type</label>
        <select
          value={state.studyType?.id || ''}
          onChange={e => {
            const st = studies.find(s => s.id === e.target.value)
            // Clear the previous study's queries immediately — without
            // this, switching studies leaves the OLD study's count/rows
            // in state until the refetch resolves, which can both
            // misrepresent the newly selected study and let Next enable
            // on stale data for a split second.
            setState(s => ({ ...s, studyType: st || null, queries: [], queriesVisible: false }))
          }}
          style={{ width: '100%', padding: '10px 12px', border: `1px solid ${T.border}`, borderRadius: 8, fontSize: 13, outline: 'none', boxSizing: 'border-box' }}
        >
          <option value="">Select an existing study…</option>
          {studies.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>

        {!genLoading && (
          <GenerateInline onGenerate={handleGenerate} />
        )}
        {genLoading && (
          <div style={{ marginTop: 10, padding: 12, borderRadius: 8, background: T.offWhite, fontSize: 13, color: T.textMid, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>Generating queries{genStatus ? ` (${genStatus.created_count || 0}/${genStatus.target_count || '…'})` : '…'}</span>
          </div>
        )}
        {genError && (
          <div style={{ marginTop: 8, padding: 10, borderRadius: 8, background: T.redLight, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
            <span style={{ color: T.red, fontSize: 12 }}>{genError}</span>
            {lastGenerateArgs && (
              <button onClick={handleRetryGenerate}
                style={{ background: 'none', border: `1px solid ${T.red}`, color: T.red, borderRadius: 6, padding: '4px 10px', fontSize: 12, fontWeight: 600, cursor: 'pointer', flexShrink: 0 }}>
                Retry
              </button>
            )}
          </div>
        )}
      </div>

      {state.studyType?.id && (
        <div style={{ marginBottom: 24 }}>
          <button onClick={() => setState(s => ({ ...s, queriesVisible: !s.queriesVisible }))}
            style={{ background: 'none', border: 'none', color: T.indigo, fontWeight: 600, fontSize: 13, cursor: 'pointer', padding: 0, marginBottom: 8 }}>
            {state.queriesVisible ? '▾' : '▸'} {state.queries.length} quer{state.queries.length === 1 ? 'y' : 'ies'} in this study
          </button>
          {state.queriesVisible && (
            <div style={{ maxHeight: 220, overflowY: 'auto', border: `1px solid ${T.border}`, borderRadius: 8 }}>
              {state.queries.length === 0 && (
                <div style={{ padding: 16, textAlign: 'center', color: T.slate, fontSize: 13 }}>No queries yet.</div>
              )}
              {state.queries.map((q, i) => (
                <div key={q.query_code || i} style={{ padding: '8px 12px', borderBottom: `1px solid ${T.border}`, fontSize: 12, color: T.textMid }}>
                  {q.query_text}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div style={{ marginBottom: 20 }}>
        <label style={{ fontWeight: 600, fontSize: 13, display: 'block', marginBottom: 10 }}>Depth</label>
        <div style={{ display: 'flex', gap: 10 }}>
          {DEPTH_PRESETS.map(preset => (
            <div key={preset.id} onClick={() => setState(s => ({ ...s, depth: preset.id }))}
              style={{
                flex: 1, padding: 14, borderRadius: 10, cursor: 'pointer',
                border: `2px solid ${state.depth === preset.id ? T.navy : T.border}`,
                background: state.depth === preset.id ? T.offWhite : T.white,
              }}>
              <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 4 }}>{preset.name}</div>
              <div style={{ fontSize: 12, color: T.slate }}>{preset.description}</div>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
          {PLATFORM_META.map(p => {
            const selected = depthPreset.platforms.includes(p.id)
            return (
              <Badge key={p.id} color={p.available ? (selected ? T.teal : T.slate) : T.slateLight} bg={p.available && selected ? T.tealLight : T.offWhite}>
                {p.name}{!p.available ? ' — unavailable' : selected ? '' : ' — not in this preset'}
              </Badge>
            )
          })}
        </div>
      </div>

      <div style={{ marginBottom: 8 }}>
        <label style={{ fontWeight: 600, fontSize: 13, display: 'block', marginBottom: 10 }}>Recurrence</label>
        <div style={{ display: 'flex', gap: 8 }}>
          {RECURRENCE_OPTIONS.map(opt => (
            <button key={opt.id} disabled={opt.disabled}
              onClick={() => { if (!opt.disabled) setState(s => ({ ...s, recurrence: opt.id })) }}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '8px 16px', borderRadius: 8, fontSize: 13, fontWeight: 600,
                cursor: opt.disabled ? 'not-allowed' : 'pointer',
                border: `1px solid ${state.recurrence === opt.id ? T.navy : T.border}`,
                background: state.recurrence === opt.id ? T.navy : T.white,
                color: opt.disabled ? T.slateLight : (state.recurrence === opt.id ? T.white : T.textMid),
                opacity: opt.disabled ? 0.7 : 1,
              }}>
              {opt.label}
              {opt.disabled && (
                <span style={{ fontSize: 10, fontWeight: 600, color: T.slateLight }}>· Coming soon</span>
              )}
            </button>
          ))}
        </div>
        <div style={{ fontSize: 11, color: T.slate, marginTop: 6 }}>
          Persists intent only — recurring execution isn't automated yet.
        </div>
      </div>

      <NavButtons onBack={onBack} onNext={onNext} nextDisabled={!isValid} nextLabel="Next: Review & Launch →" />
    </div>
  )
}

function GenerateInline({ onGenerate }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  if (!open) {
    return (
      <button onClick={() => setOpen(true)}
        style={{ marginTop: 8, background: 'none', border: `1px dashed ${T.border}`, color: T.indigo, borderRadius: 8, padding: '8px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer', width: '100%' }}>
        ⊕ Generate a new study inline
      </button>
    )
  }

  return (
    <div style={{ marginTop: 10, padding: 12, borderRadius: 8, border: `1px solid ${T.border}`, display: 'flex', flexDirection: 'column', gap: 8 }}>
      <input placeholder="Study name" value={name} onChange={e => setName(e.target.value)}
        style={{ padding: '8px 12px', border: `1px solid ${T.border}`, borderRadius: 6, fontSize: 13 }} />
      <input placeholder="Description (optional)" value={description} onChange={e => setDescription(e.target.value)}
        style={{ padding: '8px 12px', border: `1px solid ${T.border}`, borderRadius: 6, fontSize: 13 }} />
      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={() => { if (name.trim()) { onGenerate(name.trim(), description.trim()); setOpen(false) } }}
          disabled={!name.trim()}
          style={{ flex: 1, padding: 8, background: name.trim() ? T.navy : T.border, color: name.trim() ? T.white : T.slate, border: 'none', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: name.trim() ? 'pointer' : 'not-allowed' }}>
          Generate
        </button>
        <button onClick={() => setOpen(false)}
          style={{ padding: '8px 16px', background: T.offWhite, border: `1px solid ${T.border}`, borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>
          Cancel
        </button>
      </div>
    </div>
  )
}

// ─── Step 3: Review & Launch ────────────────────────────────────────────

function Step3({ state, setState, onBack, onLaunched }) {
  const [availability, setAvailability] = useState(null)
  const [launching, setLaunching] = useState(false)
  const [launchError, setLaunchError] = useState(null)
  const debounceRef = useRef(null)

  const depthPreset = DEPTH_PRESETS.find(d => d.id === state.depth) || DEPTH_PRESETS[0]
  const now = new Date()
  const pad2 = n => String(n).padStart(2, '0')
  // Full local timestamp (YYYYMMDD-HHMMSS), not just YYYY-MM — a cycle
  // launched twice in the same month for the same brand used to collide
  // on the auto-generated name every time, silently pushing the visitor
  // into manually resolving TAKEN. No cycle_code length/charset
  // constraint exists on the backend (soa_cycles.cycle_code is a plain
  // unique TEXT column, CreateCycleRequest.cycle_code a bare str) — so
  // there's nothing here to trim; the slug is exactly as long as it needs
  // to be.
  const timestamp = `${now.getFullYear()}${pad2(now.getMonth() + 1)}${pad2(now.getDate())}-${pad2(now.getHours())}${pad2(now.getMinutes())}${pad2(now.getSeconds())}`
  const defaultCode = `${timestamp}-${(state.primaryEntity?.name || 'brand').toLowerCase().replace(/[^a-z0-9]+/g, '-')}-full`

  useEffect(() => {
    if (!state.cycleCode) {
      setState(s => ({ ...s, cycleCode: defaultCode }))
      checkAvailability(defaultCode)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const checkAvailability = useCallback((code) => {
    if (!code) { setAvailability(null); return }
    setAvailability('checking')
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await api.checkCycleCode(code)
        setAvailability(res.available ? 'available' : 'taken')
      } catch {
        setAvailability(null)
      }
    }, 500)
  }, [])

  const handleCodeChange = (val) => {
    const clean = val.toLowerCase().replace(/[^a-z0-9-]/g, '')
    setState(s => ({ ...s, cycleCode: clean }))
    checkAvailability(clean)
  }

  // Defense in depth, not the primary gate: Step2's own Next button
  // already requires a committed study with queries.length > 0 before
  // this step is reachable, but a direct-navigation path arriving here
  // some other way must not be able to launch with a study id and no
  // actual queries behind it.
  const isValid = state.cycleCode && availability === 'available' && !!state.studyType?.id && !!state.primaryEntity && state.queries.length > 0

  const handleLaunch = async () => {
    setLaunchError(null)
    setLaunching(true)
    try {
      const comparisonSet = [
        { entity_id: state.primaryEntity.id, comparison_code: 'M001', role: 'primary' },
        ...state.competitors
          .filter(c => c.entity_id)
          .map((c, i) => ({ entity_id: c.entity_id, comparison_code: `M${String(i + 2).padStart(3, '0')}`, role: 'competitor' })),
      ]

      const seriesId = state.recurrence !== 'none' ? studySeriesId(state.continuation?.study_series_id) : null
      const notesParts = [state.notes || null]
      if (state.recurrence !== 'none') notesParts.push(`Recurrence intent: ${state.recurrence}`)

      const created = await api.createCycle({
        cycle_code: state.cycleCode,
        study_type: state.studyType.id,
        platforms: depthPreset.platforms,
        runs_per_query: depthPreset.runsPerQuery,
        notes: notesParts.filter(Boolean).join(' — ') || null,
        run_mode: 'immediate',
        comparison_set: comparisonSet,
        source_lite_request_id: state.sourceLiteRequestId || null,
        study_series_id: seriesId,
        prior_cycle_id: state.priorCycleId || null,
      })

      // Always a fresh crawl — Phase 2 spec: even in continuation mode,
      // the audit's own crawl is never reused for scoring.
      if (state.storeUrl) {
        try {
          await api.launchCrawl({ cycle_id: created.id, store_url: state.storeUrl })
        } catch (_) {
          // Non-fatal — the cycle itself launched; a missing crawl just
          // means the report renders classic instead of Full Analysis.
        }
      }

      onLaunched(created)
    } catch (err) {
      setLaunchError(err.message)
    } finally {
      setLaunching(false)
    }
  }

  return (
    <div style={{ padding: 32, maxWidth: 720 }}>
      <h2 style={{ margin: '0 0 4px', fontSize: 20, fontWeight: 700, color: T.text }}>Review & Launch</h2>
      <p style={{ margin: '0 0 20px', color: T.slate, fontSize: 14 }}>Confirm everything below, then launch.</p>

      <div style={{ border: `1px solid ${T.border}`, borderRadius: 12, overflow: 'hidden', marginBottom: 20 }}>
        {[
          ['Brand', state.primaryEntity?.name || '—'],
          ['Competitors', state.competitors.length ? state.competitors.map(c => c.name).join(', ') : 'None'],
          ['Study', state.studyType?.name || '—'],
          ['Depth', `${depthPreset.name} (${depthPreset.platforms.join(', ')} · ${depthPreset.runsPerQuery} runs/query)`],
          ['Recurrence', RECURRENCE_OPTIONS.find(r => r.id === state.recurrence)?.label || 'One-time'],
          ['Continuing from audit', state.continuation ? 'Yes' : 'No'],
        ].map(([label, value]) => (
          <div key={label} style={{ display: 'flex', padding: '10px 16px', borderBottom: `1px solid ${T.border}`, fontSize: 13 }}>
            <div style={{ width: 180, color: T.slate, fontWeight: 600 }}>{label}</div>
            <div style={{ color: T.text }}>{value}</div>
          </div>
        ))}
      </div>

      <div style={{ marginBottom: 20 }}>
        <label style={{ fontWeight: 600, fontSize: 13, display: 'block', marginBottom: 8 }}>Cycle name</label>
        <div style={{ position: 'relative' }}>
          <input
            value={state.cycleCode}
            onChange={e => handleCodeChange(e.target.value)}
            style={{
              width: '100%', padding: '10px 140px 10px 12px',
              border: `1px solid ${availability === 'taken' ? T.red : availability === 'available' ? T.green : T.border}`,
              borderRadius: 8, fontSize: 14, fontFamily: 'monospace', outline: 'none', boxSizing: 'border-box',
            }}
          />
          <div style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', fontSize: 12, fontWeight: 600 }}>
            {availability === 'checking' && <span style={{ color: T.slate }}>Checking...</span>}
            {availability === 'available' && <span style={{ color: T.green }}>AVAILABLE ✓</span>}
            {availability === 'taken' && <span style={{ color: T.red }}>TAKEN ✗</span>}
          </div>
        </div>
      </div>

      {launchError && (
        <div style={{ padding: 12, borderRadius: 8, background: T.redLight, color: T.red, fontSize: 13, marginBottom: 16 }}>
          {launchError}
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 28 }}>
        <button onClick={onBack} disabled={launching} style={{ padding: '10px 20px', borderRadius: 8, border: `1px solid ${T.border}`, background: T.white, fontWeight: 600, fontSize: 14, cursor: 'pointer' }}>
          ← Back
        </button>
        <button onClick={handleLaunch} disabled={!isValid || launching}
          style={{ padding: '10px 24px', borderRadius: 8, border: 'none', background: (isValid && !launching) ? T.navy : T.border, color: (isValid && !launching) ? T.white : T.slate, fontWeight: 600, fontSize: 14, cursor: (isValid && !launching) ? 'pointer' : 'not-allowed' }}>
          {launching ? 'Launching…' : 'Launch Full Analysis'}
        </button>
      </div>
    </div>
  )
}

// ─── Post-launch status ─────────────────────────────────────────────────

function PostLaunchStatus({ cycle, onNavigate }) {
  return (
    <div style={{ padding: 48, maxWidth: 560, textAlign: 'center', margin: '0 auto' }}>
      <div style={{ fontSize: 40, marginBottom: 12 }}>🚀</div>
      <h2 style={{ margin: '0 0 8px', fontSize: 20, fontWeight: 700, color: T.text }}>Full Analysis launched</h2>
      <p style={{ margin: '0 0 24px', color: T.slate, fontSize: 14 }}>
        <strong style={{ fontFamily: 'monospace' }}>{cycle.cycle_code}</strong> is queued. The pipeline worker picks it up within 30 seconds — platforms, crawl, and query runs progress from here, same as any cycle.
      </p>
      <button
        onClick={() => onNavigate && onNavigate('metrics', { cycleCode: cycle.cycle_code })}
        style={{ padding: '10px 24px', borderRadius: 8, border: 'none', background: T.navy, color: T.white, fontWeight: 600, fontSize: 14, cursor: 'pointer' }}>
        View report progress →
      </button>
    </div>
  )
}

// ─── Root ───────────────────────────────────────────────────────────────

export default function NewCycleFlow({ auditToken, onComplete, onCancel, onNavigate } = {}) {
  const [step, setStep] = useState(1)
  const [state, setState] = useState(INITIAL_STATE)
  const [launchedCycle, setLaunchedCycle] = useState(null)

  return (
    <div style={{ minHeight: '100vh', background: T.offWhite, fontFamily: "'DM Sans', sans-serif" }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 32px', background: T.navy }}>
        <div style={{ color: T.white, fontWeight: 700, fontSize: 15 }}>New Full Analysis</div>
        {!launchedCycle && (
          <button onClick={() => { if (onCancel) onCancel() }}
            style={{ background: 'none', border: `1px solid ${T.navyBdr}`, color: T.white, borderRadius: 6, padding: '6px 12px', fontSize: 12, cursor: 'pointer' }}>
            Cancel
          </button>
        )}
      </div>

      {launchedCycle ? (
        <PostLaunchStatus cycle={launchedCycle} onNavigate={onNavigate} />
      ) : (
        <>
          <StepIndicator current={step} />

          {step === 1 && (
            <Step1 state={state} setState={setState} onNext={() => setStep(2)} auditToken={auditToken} />
          )}
          {step === 2 && (
            <Step2 state={state} setState={setState} onNext={() => setStep(3)} onBack={() => setStep(1)} />
          )}
          {step === 3 && (
            <Step3
              state={state} setState={setState}
              onBack={() => setStep(2)}
              onLaunched={(cycle) => {
                setLaunchedCycle(cycle)
                if (onComplete) onComplete(cycle)
              }}
            />
          )}

          <div style={{ padding: '0 32px 32px', maxWidth: 720 }}>
            <button onClick={() => onNavigate && onNavigate('wizard')}
              style={{ background: 'none', border: 'none', color: T.slate, fontSize: 12, cursor: 'pointer', padding: 0, textDecoration: 'underline' }}>
              Need more control? Use advanced setup →
            </button>
          </div>
        </>
      )}
    </div>
  )
}
