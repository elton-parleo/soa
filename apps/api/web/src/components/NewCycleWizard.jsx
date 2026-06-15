import React, { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '../api.js'
import Sidebar from './Sidebar.jsx'

// ─── Design tokens ────────────────────────────────────────────────────────────
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
  sidebarText: '#94A3B8',
}

// ─── Platform metadata ────────────────────────────────────────────────────────
const PLATFORMS = [
  { id: 'chatgpt',    name: 'ChatGPT',    model: 'GPT-5.5',                costMin: 0.04, costMax: 0.06, icon: '🤖', color: '#10B981' },
  { id: 'gemini',     name: 'Gemini',     model: 'Gemini 2.5 Flash',       costMin: 0.02, costMax: 0.03, icon: '✦',  color: '#4F46E5' },
  { id: 'perplexity', name: 'Perplexity', model: 'Llama 3.1 Sonar Large',  costMin: 0.05, costMax: 0.08, icon: '🔍', color: '#0EA5E9', disabled: true },
  { id: 'claude',     name: 'Claude',     model: 'Claude Sonnet 4.6',      costMin: 0.03, costMax: 0.05, icon: '◈',  color: '#F59E0B' },
]

const STEP_LABELS = ['Study Type', 'Comparison Set', 'Platforms & Runs', 'Name & Schedule', 'Review & Launch']

const INITIAL_STATE = {
  studyType:     null,
  comparisonSet: [],
  platforms:     ['chatgpt'],
  runsPerQuery:  5,
  cycleCode:     '',
  notes:         '',
  runMode:       'immediate',
}

// ─── Shared UI primitives ─────────────────────────────────────────────────────

function Badge({ children, color = T.slate, bg = T.offWhite }) {
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 8px',
      borderRadius: 99,
      fontSize: 11,
      fontWeight: 600,
      color,
      background: bg,
      border: `1px solid ${color}22`,
    }}>
      {children}
    </span>
  )
}

function Skeleton({ width = '100%', height = 16, radius = 6 }) {
  return (
    <div style={{
      width, height,
      borderRadius: radius,
      background: 'linear-gradient(90deg, #E2E8F0 25%, #F1F5F9 50%, #E2E8F0 75%)',
      backgroundSize: '200% 100%',
      animation: 'pulse 1.5s ease-in-out infinite',
    }} />
  )
}

// ─── Step Indicator ───────────────────────────────────────────────────────────

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
                width: 32, height: 32,
                borderRadius: '50%',
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

// ─── Top bar ──────────────────────────────────────────────────────────────────

function Topbar({ stepName }) {
  return (
    <div style={{
      height: 56, background: T.white, borderBottom: `1px solid ${T.border}`,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '0 32px', flexShrink: 0,
    }}>
      <div style={{ fontSize: 13, color: T.slate }}>
        <span style={{ color: T.text, fontWeight: 500 }}>Cycles</span>
        {' › '}
        <span style={{ color: T.text, fontWeight: 500 }}>New Cycle</span>
        {' › '}
        <span>{stepName}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <span style={{ fontSize: 18, cursor: 'pointer' }}>🔔</span>
        <div style={{
          width: 32, height: 32, borderRadius: '50%',
          background: T.indigo, color: T.white,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 13, fontWeight: 700,
        }}>E</div>
      </div>
    </div>
  )
}

// ─── Add New Study card ───────────────────────────────────────────────────────

function AddNewStudyCard({ onNavigate }) {
  const [hovered, setHovered] = React.useState(false)
  return (
    <div
      onClick={() => onNavigate && onNavigate('studies')}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background:    hovered ? T.offWhite : T.white,
        border:        `2px dashed ${hovered ? T.text : T.border}`,
        borderRadius:  12,
        padding:       20,
        cursor:        'pointer',
        display:       'flex',
        flexDirection: 'column',
        alignItems:    'center',
        justifyContent:'center',
        transition:    'all 0.15s ease',
      }}
    >
      <div style={{
        width:          44,
        height:         44,
        background:     T.offWhite,
        border:         `1px solid ${T.border}`,
        borderRadius:   '50%',
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'center',
        marginBottom:   14,
      }}>
        <span style={{ fontSize: 22, fontWeight: 300, color: T.slate, lineHeight: 1 }}>+</span>
      </div>
      <div style={{ fontSize: 15, fontWeight: 600, color: T.text, textAlign: 'center', marginBottom: 4 }}>
        Add New Study
      </div>
      <div style={{ fontSize: 12, color: T.slate, textAlign: 'center' }}>
        Create a custom template
      </div>
    </div>
  )
}

// ─── Omni-search helpers ──────────────────────────────────────────────────────

function matchesStudySearch(study, query) {
  if (!query || !query.trim()) return true
  const q = query.trim().toLowerCase()

  const fields = [
    study.name,
    study.study_type || study.id,
    study.category,
  ]

  const patterns = Array.isArray(study.patterns)
    ? study.patterns
    : study.study_pattern
      ? [study.study_pattern]
      : []

  fields.push(...patterns)

  return fields.some(f => f && String(f).toLowerCase().includes(q))
}

function matchesEntitySearch(entity, query) {
  if (!query || !query.trim()) return true
  const q = query.trim().toLowerCase()

  const fields = [
    entity.name,
    entity.slug,
    entity.type || entity.entity_type,
    entity.category,
  ]

  let aliases = entity.aliases || []
  if (typeof aliases === 'string') {
    try { aliases = JSON.parse(aliases) } catch { aliases = [aliases] }
  }
  if (Array.isArray(aliases)) fields.push(...aliases)

  return fields.some(f => f && String(f).toLowerCase().includes(q))
}

// ─── Step 1: Select Study Type ────────────────────────────────────────────────

function Step1({ state, setState, onNext, onNavigate }) {
  const [studies,        setStudies]        = useState([])
  const [studiesLoading, setStudiesLoading] = useState(true)
  const [search,         setSearch]         = useState('')
  const [filterCat,      setFilterCat]      = useState('')
  const [filterPat,      setFilterPat]      = useState('')

  useEffect(() => {
    api.getStudies()
      .then(data => { setStudies(data || []) })
      .catch(() => { setStudies([]) })
      .finally(() => { setStudiesLoading(false) })
  }, [])

  const categories = [...new Set(studies.map(s => s.category))].filter(Boolean)
  const patterns   = [...new Set(studies.flatMap(s => s.patterns))].filter(Boolean)

  const filtered = studies.filter(s => {
    if (!matchesStudySearch(s, search)) return false
    if (filterCat && s.category !== filterCat) return false
    if (filterPat && !s.patterns.includes(filterPat)) return false
    return true
  })

  return (
    <div style={{ padding: 32 }}>
      <h2 style={{ margin: '0 0 4px', fontSize: 22, fontWeight: 700, color: T.text }}>Select Study Type</h2>
      <p style={{ margin: '0 0 24px', color: T.slate, fontSize: 14 }}>Choose the measurement study to run in this cycle.</p>

      {/* Filter bar */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 24 }}>
        <input
          placeholder="Search by name, category, or pattern..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ flex: 1, minWidth: 280, padding: '8px 12px', border: `1px solid ${T.border}`, borderRadius: 8, fontSize: 13, outline: 'none' }}
        />
        <select value={filterCat} onChange={e => setFilterCat(e.target.value)}
          style={{ padding: '8px 12px', border: `1px solid ${T.border}`, borderRadius: 8, fontSize: 13, background: T.white }}>
          <option value="">All Categories</option>
          {categories.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={filterPat} onChange={e => setFilterPat(e.target.value)}
          style={{ padding: '8px 12px', border: `1px solid ${T.border}`, borderRadius: 8, fontSize: 13, background: T.white }}>
          <option value="">All Patterns</option>
          {patterns.map(p => <option key={p} value={p}>{p}</option>)}
        </select>
      </div>

      {/* Study cards grid / empty state */}
      {studiesLoading ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 32 }}>
          {[1,2,3].map(i => (
            <div key={i} style={{ background: T.white, border: `1px solid ${T.border}`, borderRadius: 12, padding: 20 }}>
              <Skeleton height={12} width="60%" />
              <div style={{ marginTop: 12 }}><Skeleton height={18} width="80%" /></div>
              <div style={{ marginTop: 8 }}><Skeleton height={12} width="40%" /></div>
              <div style={{ marginTop: 16 }}><Skeleton height={12} /></div>
              <div style={{ marginTop: 6 }}><Skeleton height={12} width="70%" /></div>
            </div>
          ))}
        </div>
      ) : studies.length === 0 ? (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          background: T.offWhite,
          border: `1px solid ${T.border}`,
          borderRadius: 12,
          padding: '60px 40px',
          minHeight: 280,
          marginBottom: 32,
        }}>
          {/* Flask icon */}
          <div style={{
            width: 56, height: 56,
            background: T.white,
            border: `1px solid ${T.border}`,
            borderRadius: 12,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginBottom: 20,
          }}>
            <svg
              width="24" height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke={T.slate}
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M9 3h6M9 3v8L4.5 17.5a2.121 2.121 0 001.5 3.5h12a2.121 2.121 0 001.5-3.5L15 11V3"/>
              <path d="M6.5 17.5h11"/>
            </svg>
          </div>

          {/* Heading */}
          <div style={{
            fontSize: 18,
            fontWeight: 700,
            color: T.text,
            textAlign: 'center',
            marginBottom: 10,
          }}>
            No studies yet
          </div>

          {/* Body text */}
          <div style={{
            fontSize: 13,
            color: T.slate,
            textAlign: 'center',
            maxWidth: 340,
            lineHeight: 1.6,
            marginBottom: 20,
          }}>
            Launch your first cycle to start measuring how AI agents recommend your brand. You'll need to create or seed a study type first.
          </div>

          {/* Link */}
          <span
            onClick={() => onNavigate && onNavigate('studies')}
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: T.text,
              textDecoration: 'none',
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
            }}
            onMouseEnter={e => { e.currentTarget.style.textDecoration = 'underline' }}
            onMouseLeave={e => { e.currentTarget.style.textDecoration = 'none' }}
          >
            Manage Studies in the Study Library →
          </span>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 32 }}>
          {filtered.map(study => {
            const selected = state.studyType?.id === study.id
            return (
              <div
                key={study.id}
                onClick={() => setState(s => ({ ...s, studyType: study }))}
                style={{
                  background: T.white,
                  border: `2px solid ${selected ? T.navy : T.border}`,
                  borderRadius: 12, padding: 20,
                  cursor: 'pointer',
                  position: 'relative',
                  transition: 'border-color 0.15s',
                }}
              >
                {selected && (
                  <div style={{
                    position: 'absolute', top: 12, right: 12,
                    width: 22, height: 22, borderRadius: '50%',
                    background: T.navy, color: T.white,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 12, fontWeight: 700,
                  }}>✓</div>
                )}
                <div style={{ fontFamily: 'monospace', fontSize: 11, color: T.slate, marginBottom: 6 }}>{study.id}</div>
                <div style={{ fontWeight: 700, fontSize: 15, color: T.text, marginBottom: 6 }}>{study.name}</div>
                <Badge color={T.teal} bg={T.tealLight}>{study.category}</Badge>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 10 }}>
                  {study.patterns.map(p => <Badge key={p} color={T.indigo} bg="#EEF2FF">{p}</Badge>)}
                </div>
                <div style={{ marginTop: 12, display: 'flex', justifyContent: 'space-between', fontSize: 12, color: T.slate }}>
                  <span>{study.queryCount} queries</span>
                  {study.lastRun && <span>Last: {study.lastRun}</span>}
                </div>
              </div>
            )
          })}
          {/* Add New Study card */}
          <AddNewStudyCard onNavigate={onNavigate} />
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <button
          onClick={onNext}
          disabled={!state.studyType}
          style={{
            padding: '10px 24px', borderRadius: 8, border: 'none',
            background: state.studyType ? T.navy : T.border,
            color: state.studyType ? T.white : T.slate,
            fontWeight: 600, fontSize: 14, cursor: state.studyType ? 'pointer' : 'not-allowed',
          }}
        >
          Next: Configure Comparison Set →
        </button>
      </div>
    </div>
  )
}

// ─── Step 2: Comparison Set ────────────────────────────────────────────────────

function Step2({ state, setState, onNext, onBack }) {
  const [entities, setEntities] = useState([])
  const [search, setSearch] = useState('')
  const [showAddForm, setShowAddForm] = useState(false)
  const [newEntity, setNewEntity] = useState({ name: '', type: 'Brand', category: '' })
  const [adding, setAdding] = useState(false)

  useEffect(() => {
    api.getEntities().then(setEntities).catch(() => {})
  }, [])

  const filtered = entities.filter(e => matchesEntitySearch(e, search))

  const addToSet = (entity) => {
    if (state.comparisonSet.find(c => c.entity_id === entity.id)) return
    const idx = state.comparisonSet.length
    const code = `M${String(idx + 1).padStart(3, '0')}`
    const role = idx === 0 ? 'primary' : 'competitor'
    setState(s => ({
      ...s,
      comparisonSet: [...s.comparisonSet, { entity_id: entity.id, entity, code, role }]
    }))
  }

  const removeFromSet = (entityId) => {
    setState(s => {
      const next = s.comparisonSet
        .filter(c => c.entity_id !== entityId)
        .map((c, i) => ({ ...c, code: `M${String(i + 1).padStart(3, '0')}`, role: i === 0 ? 'primary' : c.role }))
      return { ...s, comparisonSet: next }
    })
  }

  const handleAddEntity = async () => {
    if (!newEntity.name || !newEntity.category) return
    setAdding(true)
    try {
      const created = await api.createEntity(newEntity)
      setEntities(es => [...es, created])
      addToSet(created)
      setNewEntity({ name: '', type: 'Brand', category: '' })
      setShowAddForm(false)
    } catch (e) {
      alert(e.message)
    } finally {
      setAdding(false)
    }
  }

  const primaryEntry = state.comparisonSet.find(c => c.role === 'primary')
  const isValid = state.comparisonSet.length >= 2 && state.comparisonSet.filter(c => c.role === 'primary').length === 1

  const typeColors = { Retailer: T.teal, Brand: T.indigo, CPG: T.amber }

  return (
    <div style={{ padding: 32, display: 'flex', gap: 24 }}>
      {/* Left: entity list */}
      <div style={{ flex: 1, background: T.white, border: `1px solid ${T.border}`, borderRadius: 12, overflow: 'hidden' }}>
        <div style={{ padding: '16px 20px', borderBottom: `1px solid ${T.border}` }}>
          <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 12 }}>Available Entities</div>
          <input
            placeholder="Search by name, type, or category..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{ width: '100%', padding: '8px 12px', border: `1px solid ${T.border}`, borderRadius: 8, fontSize: 13, outline: 'none', boxSizing: 'border-box' }}
          />
        </div>
        <div style={{ maxHeight: 380, overflowY: 'auto' }}>
          {filtered.map(e => {
            const inSet = !!state.comparisonSet.find(c => c.entity_id === e.id)
            return (
              <div
                key={e.id}
                onClick={() => addToSet(e)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 12,
                  padding: '10px 20px', cursor: inSet ? 'default' : 'pointer',
                  borderBottom: `1px solid ${T.border}`,
                  opacity: inSet ? 0.45 : 1,
                  background: inSet ? T.offWhite : T.white,
                }}
              >
                <div style={{ width: 32, height: 32, borderRadius: '50%', background: T.offWhite, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 700 }}>
                  {e.name[0]}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 13 }}>{e.name}</div>
                  <div style={{ fontSize: 11, color: T.slate }}>{e.category}</div>
                </div>
                <Badge color={typeColors[e.type] || T.slate}>{e.type}</Badge>
                {inSet && <span style={{ color: T.green, fontSize: 12 }}>✓ Added</span>}
              </div>
            )
          })}
        </div>
        <div style={{ padding: '12px 20px', borderTop: `1px solid ${T.border}` }}>
          {showAddForm ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <input placeholder="Entity name" value={newEntity.name}
                onChange={e => setNewEntity(n => ({ ...n, name: e.target.value }))}
                style={{ padding: '8px 12px', border: `1px solid ${T.border}`, borderRadius: 6, fontSize: 13 }} />
              <div style={{ display: 'flex', gap: 8 }}>
                <select value={newEntity.type}
                  onChange={e => setNewEntity(n => ({ ...n, type: e.target.value }))}
                  style={{ flex: 1, padding: '8px 12px', border: `1px solid ${T.border}`, borderRadius: 6, fontSize: 13 }}>
                  {['Retailer','Brand','CPG','Service','Aggregate'].map(t => <option key={t}>{t}</option>)}
                </select>
                <input placeholder="Category" value={newEntity.category}
                  onChange={e => setNewEntity(n => ({ ...n, category: e.target.value }))}
                  style={{ flex: 1, padding: '8px 12px', border: `1px solid ${T.border}`, borderRadius: 6, fontSize: 13 }} />
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={handleAddEntity} disabled={adding}
                  style={{ flex: 1, padding: '8px', background: T.navy, color: T.white, border: 'none', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
                  {adding ? 'Adding...' : 'Add Entity'}
                </button>
                <button onClick={() => setShowAddForm(false)}
                  style={{ padding: '8px 16px', background: T.offWhite, border: `1px solid ${T.border}`, borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button onClick={() => setShowAddForm(true)}
              style={{ width: '100%', padding: '8px', background: 'transparent', border: `1px dashed ${T.border}`, borderRadius: 6, fontSize: 13, color: T.indigo, cursor: 'pointer', fontWeight: 600 }}>
              ⊕ Add New Entity
            </button>
          )}
        </div>
      </div>

      {/* Right: comparison set */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={{ background: T.white, border: `1px solid ${T.border}`, borderRadius: 12, overflow: 'hidden', flex: 1 }}>
          <div style={{ padding: '16px 20px', borderBottom: `1px solid ${T.border}`, fontWeight: 700, fontSize: 15 }}>
            Comparison Set ({state.comparisonSet.length})
          </div>
          {state.comparisonSet.length === 0 ? (
            <div style={{ padding: 32, textAlign: 'center', color: T.slate, fontSize: 13 }}>
              Click entities on the left to add them.
            </div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ background: T.offWhite }}>
                  {['Entity','Code','Role',''].map(h => (
                    <th key={h} style={{ padding: '8px 16px', textAlign: 'left', fontWeight: 600, color: T.slate, fontSize: 11, borderBottom: `1px solid ${T.border}` }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {state.comparisonSet.map((c, i) => (
                  <tr key={c.entity_id} style={{ borderBottom: `1px solid ${T.border}` }}>
                    <td style={{ padding: '10px 16px', fontWeight: 500 }}>{c.entity.name}</td>
                    <td style={{ padding: '10px 16px', fontFamily: 'monospace', color: T.slate }}>{c.code}</td>
                    <td style={{ padding: '10px 16px' }}>
                      {i === 0 ? (
                        <Badge color={T.teal} bg={T.tealLight}>Primary</Badge>
                      ) : (
                        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 12 }}>
                          <input type="checkbox" checked={c.role === 'competitor'} readOnly />
                          Competitor
                        </label>
                      )}
                    </td>
                    <td style={{ padding: '10px 16px' }}>
                      <button onClick={() => removeFromSet(c.entity_id)}
                        style={{ background: 'none', border: 'none', color: T.red, cursor: 'pointer', fontSize: 16 }}>✕</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {isValid && (
            <div style={{ padding: '12px 20px', borderTop: `1px solid ${T.border}`, display: 'flex', alignItems: 'center', gap: 8, background: T.greenLight }}>
              <span style={{ fontSize: 12, fontWeight: 500, color: T.green }}>
                Primary: {primaryEntry?.entity.name}
              </span>
              <Badge color={T.green} bg={T.greenLight}>Validation Pass</Badge>
            </div>
          )}
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <button onClick={onBack}
            style={{ padding: '10px 20px', borderRadius: 8, border: `1px solid ${T.border}`, background: T.white, fontWeight: 600, fontSize: 14, cursor: 'pointer' }}>
            ← Back
          </button>
          <button onClick={onNext} disabled={!isValid}
            style={{ padding: '10px 24px', borderRadius: 8, border: 'none', background: isValid ? T.navy : T.border, color: isValid ? T.white : T.slate, fontWeight: 600, fontSize: 14, cursor: isValid ? 'pointer' : 'not-allowed' }}>
            Next: Platforms & Runs →
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Step 3: Platforms & Runs ─────────────────────────────────────────────────

function Step3({ state, setState, onNext, onBack, queryCount }) {
  const togglePlatform = (id) => {
    setState(s => ({
      ...s,
      platforms: s.platforms.includes(id)
        ? s.platforms.filter(p => p !== id)
        : [...s.platforms, id],
    }))
  }

  const totalCalls = (queryCount || 0) * state.platforms.length * state.runsPerQuery
  const minCost = state.platforms.reduce((sum, pid) => {
    const p = PLATFORMS.find(x => x.id === pid)
    return sum + (p ? p.costMin * (queryCount || 0) * state.runsPerQuery : 0)
  }, 0)
  const maxCost = state.platforms.reduce((sum, pid) => {
    const p = PLATFORMS.find(x => x.id === pid)
    return sum + (p ? p.costMax * (queryCount || 0) * state.runsPerQuery : 0)
  }, 0)
  const estMins = Math.ceil(totalCalls * 1.5 / 60)

  const isValid = state.platforms.length > 0

  return (
    <div style={{ padding: 32, display: 'flex', gap: 24 }}>
      <div style={{ flex: 1 }}>
        <h2 style={{ margin: '0 0 4px', fontSize: 20, fontWeight: 700, color: T.text }}>Platforms & Runs</h2>
        <p style={{ margin: '0 0 24px', color: T.slate, fontSize: 14 }}>Select which AI platforms to query and how many runs per query.</p>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 32 }}>
          {PLATFORMS.map(p => {
            const sel = state.platforms.includes(p.id)
            const isDisabled = p.disabled === true
            return (
              <div key={p.id}
                onClick={isDisabled ? undefined : () => togglePlatform(p.id)}
                style={{
                  padding: 20, borderRadius: 12,
                  cursor: isDisabled ? 'not-allowed' : 'pointer',
                  border: `2px solid ${sel ? T.navy : T.border}`,
                  background: sel ? '#F0F4FF' : T.white,
                  position: 'relative',
                  transition: 'border-color 0.15s',
                  opacity: isDisabled ? 0.4 : 1,
                  pointerEvents: isDisabled ? 'none' : 'auto',
                }}>
                {sel && (
                  <div style={{
                    position: 'absolute', top: 12, right: 12,
                    width: 20, height: 20, borderRadius: '50%',
                    background: T.navy, color: T.white,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 11, fontWeight: 700,
                  }}>✓</div>
                )}
                <div style={{ fontSize: 24, marginBottom: 8 }}>{p.icon}</div>
                <div style={{ fontWeight: 700, fontSize: 14 }}>{p.name}</div>
                <div style={{ fontSize: 11, color: T.slate, marginTop: 2 }}>{p.model}</div>
                <div style={{ fontSize: 11, color: T.slate, marginTop: 6 }}>~${p.costMin}–${p.costMax}/run</div>
                {isDisabled && (
                  <div style={{
                    display: 'inline-block',
                    marginTop: 8,
                    fontSize: 10,
                    color: '#64748B',
                    background: '#F1F5F9',
                    borderRadius: 4,
                    padding: '2px 6px',
                  }}>Coming soon</div>
                )}
              </div>
            )
          })}
        </div>

        <div style={{ marginBottom: 24 }}>
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 12 }}>Runs per Query</div>
          <div style={{ display: 'flex', gap: 8 }}>
            {[1, 3, 5, 10].map(n => (
              <button key={n} onClick={() => setState(s => ({ ...s, runsPerQuery: n }))}
                style={{
                  padding: '8px 20px', borderRadius: 99, border: `1px solid ${state.runsPerQuery === n ? T.navy : T.border}`,
                  background: state.runsPerQuery === n ? T.navy : T.white,
                  color: state.runsPerQuery === n ? T.white : T.text,
                  fontWeight: 600, fontSize: 14, cursor: 'pointer',
                }}>
                {n}
              </button>
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <button onClick={onBack}
            style={{ padding: '10px 20px', borderRadius: 8, border: `1px solid ${T.border}`, background: T.white, fontWeight: 600, fontSize: 14, cursor: 'pointer' }}>
            ← Back
          </button>
          <button onClick={onNext} disabled={!isValid}
            style={{ padding: '10px 24px', borderRadius: 8, border: 'none', background: isValid ? T.navy : T.border, color: isValid ? T.white : T.slate, fontWeight: 600, fontSize: 14, cursor: isValid ? 'pointer' : 'not-allowed' }}>
            Next: Review & Launch →
          </button>
        </div>
      </div>

      {/* Cost sidebar */}
      <div style={{ width: 260, background: T.navy, borderRadius: 12, padding: 24, color: T.white, alignSelf: 'flex-start' }}>
        <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 20 }}>Estimated Cycle Totals</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div>
            <div style={{ fontSize: 11, color: T.sidebarText, marginBottom: 4 }}>TOTAL API CALLS</div>
            <div style={{ fontSize: 24, fontWeight: 700 }}>{totalCalls.toLocaleString()}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: T.sidebarText, marginBottom: 4 }}>COST PROJECTION</div>
            <div style={{ fontSize: 20, fontWeight: 700 }}>${minCost.toFixed(2)}–${maxCost.toFixed(2)}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: T.sidebarText, marginBottom: 4 }}>EST. DURATION</div>
            <div style={{ fontSize: 20, fontWeight: 700 }}>~{estMins} min</div>
          </div>
        </div>
        <div style={{ marginTop: 20, fontSize: 11, color: T.sidebarText, lineHeight: 1.5, borderTop: `1px solid ${T.navyBdr}`, paddingTop: 16 }}>
          Estimates are indicative. Actual cost and duration vary based on response length and platform availability.
        </div>
      </div>
    </div>
  )
}

// ─── Step 4: Name & Schedule ──────────────────────────────────────────────────

function Step4({ state, setState, onNext, onBack }) {
  const [availability, setAvailability] = useState(null) // null | 'checking' | 'available' | 'taken'
  const debounceRef = useRef(null)

  const today = new Date()
  const defaultCode = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${state.studyType?.id?.replace(/_/g, '-') || 'study'}`

  useEffect(() => {
    if (!state.cycleCode) {
      setState(s => ({ ...s, cycleCode: defaultCode }))
    }
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

  const isValid = state.cycleCode && availability === 'available'

  return (
    <div style={{ padding: 32, maxWidth: 560 }}>
      <h2 style={{ margin: '0 0 4px', fontSize: 20, fontWeight: 700, color: T.text }}>Name & Schedule</h2>
      <p style={{ margin: '0 0 28px', color: T.slate, fontSize: 14 }}>Give this cycle a unique code and set when it should run.</p>

      <div style={{ marginBottom: 24 }}>
        <label style={{ fontWeight: 600, fontSize: 13, display: 'block', marginBottom: 8 }}>Cycle Code</label>
        <div style={{ position: 'relative' }}>
          <input
            value={state.cycleCode}
            onChange={e => handleCodeChange(e.target.value)}
            placeholder={defaultCode}
            style={{
              width: '100%', padding: '10px 140px 10px 12px',
              border: `1px solid ${availability === 'taken' ? T.red : availability === 'available' ? T.green : T.border}`,
              borderRadius: 8, fontSize: 14, fontFamily: 'monospace',
              outline: 'none', boxSizing: 'border-box',
            }}
          />
          <div style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', fontSize: 12, fontWeight: 600 }}>
            {availability === 'checking' && <span style={{ color: T.slate }}>Checking...</span>}
            {availability === 'available' && <span style={{ color: T.green }}>AVAILABLE ✓</span>}
            {availability === 'taken' && <span style={{ color: T.red }}>TAKEN ✗</span>}
          </div>
        </div>
        <div style={{ fontSize: 11, color: T.slate, marginTop: 6 }}>Lowercase letters, numbers, and hyphens only.</div>
      </div>

      <div style={{ marginBottom: 24 }}>
        <label style={{ fontWeight: 600, fontSize: 13, display: 'block', marginBottom: 8 }}>Notes (optional)</label>
        <textarea
          value={state.notes}
          onChange={e => setState(s => ({ ...s, notes: e.target.value }))}
          rows={3}
          placeholder="Any notes about this cycle..."
          style={{ width: '100%', padding: '10px 12px', border: `1px solid ${T.border}`, borderRadius: 8, fontSize: 13, resize: 'vertical', outline: 'none', boxSizing: 'border-box' }}
        />
      </div>

      <div style={{ marginBottom: 32 }}>
        <label style={{ fontWeight: 600, fontSize: 13, display: 'block', marginBottom: 12 }}>Execution Window</label>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', fontSize: 13 }}>
            <input type="radio" checked={state.runMode === 'immediate'} onChange={() => setState(s => ({ ...s, runMode: 'immediate' }))} />
            <span><strong>Start on Launch</strong> — the pipeline worker picks this up within 30 seconds</span>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'not-allowed', fontSize: 13, opacity: 0.5 }}>
            <input type="radio" disabled />
            <span><strong>Set Specific Date</strong> — coming soon</span>
          </label>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
        <button onClick={onBack}
          style={{ padding: '10px 20px', borderRadius: 8, border: `1px solid ${T.border}`, background: T.white, fontWeight: 600, fontSize: 14, cursor: 'pointer' }}>
          ← Back
        </button>
        <button onClick={onNext} disabled={!isValid}
          style={{ padding: '10px 24px', borderRadius: 8, border: 'none', background: isValid ? T.navy : T.border, color: isValid ? T.white : T.slate, fontWeight: 600, fontSize: 14, cursor: isValid ? 'pointer' : 'not-allowed' }}>
          Next: Review & Launch →
        </button>
      </div>
    </div>
  )
}

// ─── Step 5: Review & Launch ──────────────────────────────────────────────────

function Step5({ state, setState, onBack, onGoTo, onSuccess }) {
  const [queryBreakdown, setQueryBreakdown] = useState(null)
  const [showConfirm, setShowConfirm] = useState(false)
  const [launching, setLaunching] = useState(false)
  const [launchError, setLaunchError] = useState(null)
  const [launched, setLaunched] = useState(false)

  useEffect(() => {
    if (state.studyType?.id) {
      api.getStudyQueries(state.studyType.id).then(setQueryBreakdown).catch(() => {})
    }
  }, [state.studyType?.id])

  const totalCalls = (queryBreakdown?.total || 0) * state.platforms.length * state.runsPerQuery
  const platforms  = PLATFORMS.filter(p => state.platforms.includes(p.id))
  const minCost = platforms.reduce((s, p) => s + p.costMin * (queryBreakdown?.total || 0) * state.runsPerQuery, 0)
  const maxCost = platforms.reduce((s, p) => s + p.costMax * (queryBreakdown?.total || 0) * state.runsPerQuery, 0)

  const handleLaunch = async () => {
    setLaunchError(null)
    setLaunching(true)
    try {
      await api.createCycle({
        cycle_code:     state.cycleCode,
        study_type:     state.studyType.id,
        platforms:      state.platforms.filter(p => p !== 'perplexity'),
        runs_per_query: state.runsPerQuery,
        notes:          state.notes || null,
        run_mode:       state.runMode,
        comparison_set: state.comparisonSet.map(c => ({
          entity_id:       c.entity_id,
          comparison_code: c.code,
          role:            c.role,
        })),
      })
      setShowConfirm(false)
      setLaunched(true)
    } catch (e) {
      setLaunchError(e.message)
    } finally {
      setLaunching(false)
    }
  }

  if (launched) {
    return (
      <div style={{ padding: 64, textAlign: 'center' }}>
        <div style={{ fontSize: 64, marginBottom: 16 }}>🚀</div>
        <h2 style={{ fontSize: 28, fontWeight: 700, color: T.text, margin: '0 0 8px' }}>Cycle Launched</h2>
        <div style={{ fontFamily: 'monospace', fontSize: 18, color: T.navy, fontWeight: 700, marginBottom: 16 }}>{state.cycleCode}</div>
        <p style={{ color: T.slate, fontSize: 14, maxWidth: 400, margin: '0 auto 32px' }}>
          The pipeline worker will begin processing this cycle shortly.
        </p>
        <button onClick={onSuccess}
          style={{ padding: '12px 28px', background: T.navy, color: T.white, border: 'none', borderRadius: 8, fontWeight: 600, fontSize: 14, cursor: 'pointer' }}>
          Start New Cycle
        </button>
      </div>
    )
  }

  const SummaryPanel = ({ title, step, children }) => (
    <div style={{ background: T.white, border: `1px solid ${T.border}`, borderRadius: 12, overflow: 'hidden', marginBottom: 16 }}>
      <div style={{ padding: '14px 20px', borderBottom: `1px solid ${T.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontWeight: 700, fontSize: 14 }}>{title}</div>
        <button onClick={() => onGoTo(step)}
          style={{ fontSize: 12, color: T.indigo, fontWeight: 600, background: 'none', border: 'none', cursor: 'pointer' }}>EDIT</button>
      </div>
      <div style={{ padding: '16px 20px' }}>{children}</div>
    </div>
  )

  return (
    <div style={{ padding: 32, maxWidth: 700 }}>
      <h2 style={{ margin: '0 0 4px', fontSize: 20, fontWeight: 700, color: T.text }}>Review & Launch</h2>
      <p style={{ margin: '0 0 24px', color: T.slate, fontSize: 14 }}>Confirm all settings before launching.</p>

      <SummaryPanel title="Study Type & Queries" step={1}>
        <div style={{ fontWeight: 600 }}>{state.studyType?.name}</div>
        <div style={{ fontSize: 12, color: T.slate, marginTop: 4 }}>{state.studyType?.id}</div>
        {queryBreakdown && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 12, color: T.slate, marginBottom: 6 }}>{queryBreakdown.total} active queries</div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {Object.entries(queryBreakdown.by_pattern).map(([pat, cnt]) => (
                <Badge key={pat} color={T.indigo} bg="#EEF2FF">{pat}: {cnt}</Badge>
              ))}
            </div>
          </div>
        )}
      </SummaryPanel>

      <SummaryPanel title="Comparison Set" step={2}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {state.comparisonSet.map(c => (
            <div key={c.entity_id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
              <span style={{ fontFamily: 'monospace', color: T.slate, fontSize: 12 }}>{c.code}</span>
              <span style={{ fontWeight: c.role === 'primary' ? 700 : 400 }}>{c.entity.name}</span>
              <Badge color={c.role === 'primary' ? T.teal : T.slate}>{c.role}</Badge>
            </div>
          ))}
        </div>
      </SummaryPanel>

      <SummaryPanel title="Platforms & Economics" step={3}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
          {platforms.map(p => <Badge key={p.id} color={T.navy}>{p.icon} {p.name}</Badge>)}
        </div>
        <div style={{ fontSize: 13, color: T.textMid }}>
          {state.runsPerQuery} runs/query · {totalCalls} total calls · ~${minCost.toFixed(2)}–${maxCost.toFixed(2)}
        </div>
      </SummaryPanel>

      <div style={{ background: T.navy, borderRadius: 12, padding: '16px 20px', marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ color: T.slateLight, fontSize: 11, marginBottom: 4 }}>CYCLE CODE</div>
          <div style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: 18, color: T.white }}>{state.cycleCode}</div>
          <div style={{ color: T.sidebarText, fontSize: 12, marginTop: 4 }}>Starts immediately on launch</div>
        </div>
        <button onClick={() => onGoTo(4)}
          style={{ fontSize: 12, color: T.tealLight, fontWeight: 600, background: 'none', border: `1px solid ${T.navyBdr}`, borderRadius: 6, padding: '6px 12px', cursor: 'pointer' }}>EDIT</button>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
        <button onClick={onBack}
          style={{ padding: '10px 20px', borderRadius: 8, border: `1px solid ${T.border}`, background: T.white, fontWeight: 600, fontSize: 14, cursor: 'pointer' }}>
          ← Back
        </button>
        <button onClick={() => setShowConfirm(true)}
          style={{ padding: '12px 28px', background: T.navy, color: T.white, border: 'none', borderRadius: 8, fontWeight: 700, fontSize: 15, cursor: 'pointer' }}>
          Launch Cycle 🚀
        </button>
      </div>

      {/* Confirm modal */}
      {showConfirm && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
        }}>
          <div style={{ background: T.white, borderRadius: 16, padding: 32, maxWidth: 440, width: '90%', boxShadow: '0 20px 60px rgba(0,0,0,0.3)' }}>
            <h3 style={{ margin: '0 0 12px', fontSize: 18, fontWeight: 700 }}>Confirm Launch</h3>
            <p style={{ fontSize: 14, color: T.textMid, lineHeight: 1.6, margin: '0 0 16px' }}>
              You are about to launch <strong>{totalCalls.toLocaleString()}</strong> API calls across <strong>{state.platforms.length}</strong> platform{state.platforms.length > 1 ? 's' : ''}.
              Estimated cost <strong>${minCost.toFixed(2)}–${maxCost.toFixed(2)}</strong>. This cannot be undone.
            </p>
            {launchError && (
              <div style={{ background: T.redLight, border: `1px solid ${T.red}22`, borderRadius: 8, padding: '10px 14px', marginBottom: 16, fontSize: 13, color: T.red, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                <span>{launchError}</span>
                <button onClick={() => setLaunchError(null)} style={{ background: 'none', border: 'none', color: T.red, cursor: 'pointer', flexShrink: 0, fontSize: 16 }}>✕</button>
              </div>
            )}
            <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
              <button onClick={() => { setShowConfirm(false); setLaunchError(null) }} disabled={launching}
                style={{ padding: '10px 20px', background: T.offWhite, border: `1px solid ${T.border}`, borderRadius: 8, fontWeight: 600, fontSize: 14, cursor: 'pointer' }}>
                Cancel
              </button>
              <button onClick={handleLaunch} disabled={launching}
                style={{ padding: '10px 24px', background: T.navy, color: T.white, border: 'none', borderRadius: 8, fontWeight: 700, fontSize: 14, cursor: launching ? 'wait' : 'pointer', opacity: launching ? 0.7 : 1 }}>
                {launching ? 'Launching...' : 'Confirm Launch'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Root Wizard ──────────────────────────────────────────────────────────────

export default function NewCycleWizard({ onComplete, onCancel, onNavigate } = {}) {
  const [step, setStep] = useState(1)
  const [state, setState] = useState(INITIAL_STATE)
  const [queryCount, setQueryCount] = useState(0)

  useEffect(() => {
    if (state.studyType?.queryCount) setQueryCount(state.studyType.queryCount)
  }, [state.studyType])

  const reset = () => {
    setStep(1)
    setState(INITIAL_STATE)
  }

  const handleSuccess = () => {
    reset()
    if (onComplete) onComplete()
  }

  return (
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: "'DM Sans', sans-serif", background: T.offWhite }}>
      <style>{`
        @keyframes pulse {
          0%, 100% { background-position: 0% 50%; }
          50% { background-position: 100% 50%; }
        }
        * { box-sizing: border-box; }
      `}</style>

      <Sidebar
        activeView="dashboard"
        onNavigate={(v) => {
          if (onNavigate) {
            onNavigate(v)
          } else if (onCancel) {
            onCancel()
          }
        }}
      />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: '100vh', marginLeft: 200 }}>
        <Topbar stepName={STEP_LABELS[step - 1]} />
        <StepIndicator current={step} />

        {/* Cancel setup link */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '8px 32px 0', borderBottom: `1px solid ${T.border}`, paddingBottom: 8 }}>
          <button
            onClick={() => { if (onCancel) onCancel() }}
            style={{ background: 'none', border: 'none', color: T.slate, fontSize: 13, cursor: 'pointer', padding: '4px 0' }}
          >
            ✕ Cancel Setup
          </button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {step === 1 && (
            <Step1 state={state} setState={setState} onNext={() => setStep(2)} onNavigate={onNavigate} />
          )}
          {step === 2 && (
            <Step2 state={state} setState={setState}
              onNext={() => setStep(3)} onBack={() => setStep(1)} />
          )}
          {step === 3 && (
            <Step3 state={state} setState={setState} queryCount={queryCount}
              onNext={() => setStep(4)} onBack={() => setStep(2)} />
          )}
          {step === 4 && (
            <Step4 state={state} setState={setState}
              onNext={() => setStep(5)} onBack={() => setStep(3)} />
          )}
          {step === 5 && (
            <Step5 state={state} setState={setState}
              onBack={() => setStep(4)}
              onGoTo={setStep}
              onSuccess={handleSuccess} />
          )}
        </div>
      </div>
    </div>
  )
}
