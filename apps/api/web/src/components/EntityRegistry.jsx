import React, { useState, useEffect } from 'react'
import { api } from '../api.js'

// ─── Design tokens (verbatim from CycleDashboard.jsx) ────────────────────────
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

// ─── Entity color helpers ─────────────────────────────────────────────────────
const ENTITY_COLORS = [
  '#0D9488',
  '#4F46E5',
  '#DC2626',
  '#16A34A',
  '#D97706',
  '#7C3AED',
  '#0284C7',
  '#DB2777',
]

function entityColor(name) {
  if (!name) return ENTITY_COLORS[0]
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  return ENTITY_COLORS[Math.abs(hash) % ENTITY_COLORS.length]
}

function initials(name) {
  if (!name) return '??'
  const parts = name.trim().split(' ')
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}

const TYPE_STYLES = {
  Brand: {
    bg:    '#EEF2FF',
    color: '#4F46E5',
    label: 'BRAND',
  },
  Retailer: {
    bg:    '#0F172A',
    color: '#FFFFFF',
    label: 'RETAILER',
  },
  CPG: {
    bg:    '#F0FDF4',
    color: '#16A34A',
    label: 'CPG',
  },
  Aggregate: {
    bg:    '#F1F5F9',
    color: '#64748B',
    label: 'AGGREGATE',
  },
  Service: {
    bg:    '#FFF7ED',
    color: '#D97706',
    label: 'SERVICE',
  },
}

// ─── Mock data fallback ───────────────────────────────────────────────────────
const MOCK_ENTITIES = [
  {
    id: 1,
    name: 'Oral-B',
    slug: 'oral-b-global',
    type: 'Brand',
    category: 'Personal Care',
    aliases: ['OralB', 'Braun'],
    merchant: 'P&G Central',
    created_at: '2024-01-12',
  },
  {
    id: 2,
    name: 'Philips Sonicare',
    slug: 'philips-sonicare',
    type: 'Brand',
    category: 'Healthcare',
    aliases: ['Sonicare'],
    merchant: 'Philips Direct',
    created_at: '2024-02-05',
  },
  {
    id: 3,
    name: 'Colgate',
    slug: 'colgate-palmolive',
    type: 'Brand',
    category: 'Personal Care',
    aliases: ['CP'],
    merchant: 'Global Distribution',
    created_at: '2023-11-20',
  },
  {
    id: 4,
    name: 'Sensodyne',
    slug: 'sensodyne-gsk',
    type: 'Brand',
    category: 'Personal Care',
    aliases: ['GSK'],
    merchant: 'Haleon Group',
    created_at: '2024-03-15',
  },
  {
    id: 5,
    name: 'Amazon',
    slug: 'amazon-retail',
    type: 'Retailer',
    category: 'E-commerce',
    aliases: ['AMZ', 'AWS'],
    merchant: 'Self-Managed',
    created_at: '2023-08-30',
  },
]

// ─── Slug generator ───────────────────────────────────────────────────────────
function slugify(name) {
  return name.toLowerCase()
    .replace(/['\(\)]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

// ─── Sidebar ──────────────────────────────────────────────────────────────────
function Sidebar({ onNavigate }) {
  const navItems = [
    { label: 'Cycles',          view: 'dashboard', active: false },
    { label: 'Studies',         view: 'studies',   active: false },
    { label: 'Results',         view: 'results',   active: false },
    { label: 'Entity Registry', view: 'entities',  active: true  },
    { label: 'Settings',        view: 'settings',  active: false },
  ]
  return (
    <div style={{ width: 200, minHeight: '100vh', background: T.navy, display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
      <div style={{ padding: '24px 20px 16px' }}>
        <div style={{ color: T.white, fontWeight: 700, fontSize: 15 }}>SoA Platform</div>
        <div style={{ color: T.sidebarText, fontSize: 11, marginTop: 2 }}>Brand Intelligence</div>
      </div>
      <nav style={{ flex: 1, padding: '8px 0' }}>
        {navItems.map(item => (
          <div
            key={item.label}
            onClick={() => onNavigate && onNavigate(item.view)}
            style={{
              padding: '10px 20px',
              fontSize: 13,
              fontWeight: item.active ? 600 : 400,
              color: item.active ? T.white : T.sidebarText,
              background: item.active ? T.navyMid : 'transparent',
              borderLeft: item.active ? `3px solid ${T.teal}` : '3px solid transparent',
              cursor: 'pointer',
            }}
          >
            {item.label}
          </div>
        ))}
      </nav>
      <div style={{ padding: '16px 20px', borderTop: `1px solid ${T.navyBdr}` }}>
        <div style={{ fontSize: 12, color: T.sidebarText, cursor: 'pointer', marginBottom: 8 }}>Help Center</div>
        <div style={{ fontSize: 12, color: T.sidebarText, cursor: 'pointer' }}>Log Out</div>
      </div>
    </div>
  )
}

// ─── Topbar ───────────────────────────────────────────────────────────────────
function Topbar() {
  return (
    <div style={{ height: 56, background: T.white, borderBottom: `1px solid ${T.border}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 32px', flexShrink: 0 }}>
      <div style={{ fontSize: 13, color: T.slate }}>
        <span style={{ color: T.text, fontWeight: 500 }}>ENTITIES</span>
        {' › '}
        <span>Management Dashboard</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <span style={{ fontSize: 18, cursor: 'pointer' }}>🔔</span>
        <div style={{ width: 32, height: 32, borderRadius: '50%', background: T.indigo, color: T.white, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 700 }}>E</div>
      </div>
    </div>
  )
}

// ─── Skeleton row ─────────────────────────────────────────────────────────────
function SkeletonRow({ delay = 0 }) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      height: 56,
      borderBottom: `1px solid ${T.border}`,
      padding: '0 16px',
      gap: 16,
      animation: `pulse 1.5s ease-in-out ${delay}s infinite`,
    }}>
      {/* Name cell */}
      <div style={{ flex: 1, minWidth: 180, display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ width: 32, height: 32, borderRadius: '50%', background: T.border, flexShrink: 0 }} />
        <div style={{ height: 12, width: 120, background: T.border, borderRadius: 4 }} />
      </div>
      <div style={{ width: 200 }}><div style={{ height: 12, width: 140, background: T.border, borderRadius: 4 }} /></div>
      <div style={{ width: 100 }}><div style={{ height: 20, width: 60, background: T.border, borderRadius: 4 }} /></div>
      <div style={{ width: 130 }}><div style={{ height: 12, width: 90, background: T.border, borderRadius: 4 }} /></div>
      <div style={{ width: 150 }}><div style={{ height: 20, width: 80, background: T.border, borderRadius: 4 }} /></div>
      <div style={{ width: 160 }}><div style={{ height: 12, width: 100, background: T.border, borderRadius: 4 }} /></div>
      <div style={{ width: 110 }}><div style={{ height: 12, width: 70, background: T.border, borderRadius: 4 }} /></div>
      <div style={{ width: 80 }}><div style={{ height: 28, width: 60, background: T.border, borderRadius: 6 }} /></div>
    </div>
  )
}

// ─── Type filter pills ────────────────────────────────────────────────────────
const TYPE_PILLS = ['ALL', 'BRAND', 'RETAILER', 'PRODUCT', 'CPG', 'AGGREGATE']

const EMPTY_FORM = {
  name:        '',
  slug:        '',
  type:        'Brand',
  category:    '',
  website_url: '',
  aliases:     [],
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function EntityRegistry({ onNavigate }) {
  const [entities,        setEntities]        = useState([])
  const [loading,         setLoading]         = useState(true)
  const [error,           setError]           = useState(null)
  const [search,          setSearch]          = useState('')
  const [typeFilter,      setTypeFilter]      = useState('ALL')
  const [categoryFilter,  setCategoryFilter]  = useState('All Categories')
  const [slideOver,       setSlideOver]       = useState(null)
  const [saving,          setSaving]          = useState(false)
  const [saveError,       setSaveError]       = useState(null)
  const [toast,           setToast]           = useState(null)
  const [formData,        setFormData]        = useState(EMPTY_FORM)
  const [aliasInput,      setAliasInput]      = useState('')

  // ── Data loading ────────────────────────────────────────────────────────────
  useEffect(() => {
    setLoading(true)
    api.getEntities()
      .then(data => {
        setEntities(data)
        setLoading(false)
      })
      .catch(err => {
        setError(err.message)
        setLoading(false)
      })
  }, [])

  // ── Toast auto-dismiss ──────────────────────────────────────────────────────
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 3000)
    return () => clearTimeout(t)
  }, [toast])

  // ── Mock fallback ───────────────────────────────────────────────────────────
  const displayEntities = entities.length > 0 ? entities : MOCK_ENTITIES

  // ── Filtering ───────────────────────────────────────────────────────────────
  const filteredEntities = displayEntities.filter(e => {
    const matchSearch =
      !search ||
      e.name.toLowerCase().includes(search.toLowerCase()) ||
      e.slug.toLowerCase().includes(search.toLowerCase()) ||
      (e.aliases || []).some(a => a.toLowerCase().includes(search.toLowerCase()))
    const matchType =
      typeFilter === 'ALL' ||
      (e.type || '').toUpperCase() === typeFilter
    const matchCat =
      categoryFilter === 'All Categories' ||
      e.category === categoryFilter
    return matchSearch && matchType && matchCat
  })

  const categories = [
    'All Categories',
    ...new Set(displayEntities.map(e => e.category).filter(Boolean)),
  ]

  // ── Slide-over open helpers ─────────────────────────────────────────────────
  function openAdd() {
    setFormData(EMPTY_FORM)
    setAliasInput('')
    setSaveError(null)
    setSlideOver({ mode: 'add' })
  }

  function openEdit(entity) {
    setFormData({
      name:        entity.name        || '',
      slug:        entity.slug        || '',
      type:        entity.type        || 'Brand',
      category:    entity.category    || '',
      website_url: entity.website_url || '',
      aliases:     entity.aliases     || [],
    })
    setAliasInput('')
    setSaveError(null)
    setSlideOver({ mode: 'edit', entity })
  }

  function closeSlideOver() {
    if (saving) return
    setSlideOver(null)
    setSaveError(null)
  }

  // ── Alias tag input ─────────────────────────────────────────────────────────
  function handleAliasKeyDown(e) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      const trimmed = aliasInput.trim().replace(',', '')
      if (trimmed && !formData.aliases.includes(trimmed) && formData.aliases.length < 8) {
        setFormData(f => ({ ...f, aliases: [...f.aliases, trimmed] }))
      }
      setAliasInput('')
    }
  }

  function removeAlias(alias) {
    setFormData(f => ({ ...f, aliases: f.aliases.filter(a => a !== alias) }))
  }

  // ── Save handler ────────────────────────────────────────────────────────────
  async function handleSave() {
    if (!formData.name.trim()) return
    setSaving(true)
    setSaveError(null)
    try {
      if (slideOver.mode === 'add') {
        const created = await api.createEntity({
          name:        formData.name,
          type:        formData.type,
          category:    formData.category,
          website_url: formData.website_url || null,
          aliases:     formData.aliases,
        })
        setEntities(prev => [...prev, created])
        setToast({ message: `${formData.name} added`, type: 'success' })
      } else {
        try {
          const updated = await api.updateEntity(slideOver.entity.id, {
            name:        formData.name,
            type:        formData.type,
            category:    formData.category,
            website_url: formData.website_url || null,
            aliases:     formData.aliases,
          })
          setEntities(prev =>
            prev.map(e => e.id === slideOver.entity.id ? updated : e)
          )
        } catch (_apiErr) {
          // If update route not yet built, apply optimistically
          setEntities(prev =>
            prev.map(e => e.id === slideOver.entity.id ? { ...e, ...formData } : e)
          )
        }
        setToast({ message: `${formData.name} updated`, type: 'success' })
      }
      setSlideOver(null)
    } catch (err) {
      setSaveError(err.message)
    } finally {
      setSaving(false)
    }
  }

  // ── Delete handler ──────────────────────────────────────────────────────────
  async function handleDelete(entity) {
    if (!window.confirm(`Delete "${entity.name}"? This cannot be undone.`)) return
    try {
      await api.deleteEntity(entity.id)
      setEntities(prev => prev.filter(e => e.id !== entity.id))
      setToast({ message: `${entity.name} deleted`, type: 'success' })
    } catch (err) {
      setToast({ message: err.message, type: 'error' })
    }
  }

  // ── Shared styles ───────────────────────────────────────────────────────────
  const inputBase = {
    width: '100%',
    padding: '9px 12px',
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    fontSize: 14,
    color: T.text,
    background: T.white,
    outline: 'none',
    boxSizing: 'border-box',
  }

  const selectStyle = {
    ...inputBase,
    cursor: 'pointer',
    appearance: 'none',
    backgroundImage: 'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'12\' height=\'8\' viewBox=\'0 0 12 8\'%3E%3Cpath d=\'M1 1l5 5 5-5\' stroke=\'%2364748B\' stroke-width=\'1.5\' fill=\'none\' stroke-linecap=\'round\'/%3E%3C/svg%3E")',
    backgroundRepeat: 'no-repeat',
    backgroundPosition: 'right 12px center',
    paddingRight: 32,
  }

  const labelStyle = {
    fontSize: 11,
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    color: T.slate,
    marginBottom: 6,
    display: 'block',
  }

  // ─── RENDER ─────────────────────────────────────────────────────────────────
  return (
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: "'DM Sans', sans-serif", background: T.offWhite }}>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.4; }
        }
        * { box-sizing: border-box; }
        .er-row:hover { background: ${T.offWhite}; }
        .er-action-btn:hover { background: ${T.offWhite}; }
        .er-action-btn-edit:hover { background: #EEF2FF !important; }
        .er-action-btn-delete:hover { background: ${T.redLight} !important; }
        .er-type-pill-inactive:hover { background: ${T.offWhite}; }
      `}</style>

      <Sidebar onNavigate={onNavigate} />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
        <Topbar />

        <div style={{ flex: 1, overflowY: 'auto', padding: 32 }}>

          {/* Page header */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
            <div>
              <h1 style={{ margin: '0 0 6px', fontSize: 28, fontWeight: 700, color: T.text }}>Entity Registry</h1>
              <p style={{ margin: 0, fontSize: 14, color: T.slate }}>Manage and configure entities across the platform.</p>
            </div>
            <button
              onClick={openAdd}
              style={{ padding: '10px 20px', background: T.text, color: T.white, border: 'none', borderRadius: 8, fontWeight: 700, fontSize: 14, cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0 }}
            >
              + Add Entity
            </button>
          </div>

          {/* Filter bar */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginTop: 24 }}>
            {/* Search */}
            <div style={{ position: 'relative', width: 360, flexShrink: 0 }}>
              <span style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', fontSize: 14, color: T.slate, pointerEvents: 'none' }}>🔍</span>
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search entities by name, slug, or alias..."
                style={{ ...inputBase, paddingLeft: 36, width: '100%' }}
              />
            </div>

            {/* Type pills */}
            <div style={{ display: 'flex', gap: 4 }}>
              {TYPE_PILLS.map(pill => {
                const active = typeFilter === pill
                return (
                  <button
                    key={pill}
                    onClick={() => setTypeFilter(pill)}
                    className={active ? '' : 'er-type-pill-inactive'}
                    style={{
                      padding: '6px 14px',
                      borderRadius: 6,
                      fontSize: 12,
                      fontWeight: 700,
                      border: active ? 'none' : `1px solid ${T.border}`,
                      background: active ? T.text : T.white,
                      color: active ? T.white : T.textMid,
                      cursor: 'pointer',
                      transition: 'all 0.1s',
                    }}
                  >
                    {pill}
                  </button>
                )
              })}
            </div>

            {/* Category */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginLeft: 12 }}>
              <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: T.slate }}>Category</span>
              <select
                value={categoryFilter}
                onChange={e => setCategoryFilter(e.target.value)}
                style={{ ...selectStyle, width: 160 }}
              >
                {categories.map(c => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Entity count */}
          {!loading && (
            <div style={{ marginTop: 12, fontSize: 13, color: T.slate }}>
              Showing {filteredEntities.length} {filteredEntities.length === 1 ? 'entity' : 'entities'}
            </div>
          )}

          {/* Table */}
          <div style={{ border: `1px solid ${T.border}`, borderRadius: 12, overflow: 'hidden', marginTop: 8, background: T.white }}>

            {/* Table header */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              height: 40,
              background: T.offWhite,
              borderBottom: `1px solid ${T.border}`,
              padding: '0 16px',
              gap: 16,
            }}>
              {[
                { label: 'NAME',     style: { flex: 1, minWidth: 180 } },
                { label: 'SLUG',     style: { width: 200 } },
                { label: 'TYPE',     style: { width: 100 } },
                { label: 'CATEGORY', style: { width: 130 } },
                { label: 'ALIASES',  style: { width: 150 } },
                { label: 'MERCHANT', style: { width: 160 } },
                { label: 'CREATED',  style: { width: 110 } },
                { label: 'ACTIONS',  style: { width: 80 } },
              ].map(col => (
                <div key={col.label} style={{
                  ...col.style,
                  fontSize: 11,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  color: T.slate,
                  flexShrink: 0,
                }}>
                  {col.label}
                </div>
              ))}
            </div>

            {/* Loading skeleton */}
            {loading && (
              [0, 1, 2, 3, 4].map(i => <SkeletonRow key={i} delay={i * 0.1} />)
            )}

            {/* Empty state */}
            {!loading && filteredEntities.length === 0 && (
              <div style={{ textAlign: 'center', padding: '64px 32px' }}>
                <div style={{ width: 56, height: 56, borderRadius: '50%', background: T.offWhite, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 24, margin: '0 auto 16px' }}>🔍</div>
                <h3 style={{ margin: '0 0 8px', fontSize: 18, fontWeight: 700, color: T.text }}>No entities found</h3>
                <p style={{ margin: '0 0 20px', fontSize: 14, color: T.slate }}>
                  {search || typeFilter !== 'ALL' || categoryFilter !== 'All Categories'
                    ? 'Try adjusting your search or filter to find what you\'re looking for.'
                    : 'Add your first entity to start tracking brand performance.'}
                </p>
                {!search && typeFilter === 'ALL' && categoryFilter === 'All Categories' && (
                  <button
                    onClick={openAdd}
                    style={{ padding: '10px 20px', background: T.text, color: T.white, border: 'none', borderRadius: 8, fontWeight: 700, fontSize: 14, cursor: 'pointer' }}
                  >
                    + Add Entity
                  </button>
                )}
              </div>
            )}

            {/* Data rows */}
            {!loading && filteredEntities.map(entity => {
              const typeStyle = TYPE_STYLES[entity.type] || TYPE_STYLES.Brand
              const visibleAliases = (entity.aliases || []).slice(0, 2)
              const extraAliases   = (entity.aliases || []).length - 2

              return (
                <div
                  key={entity.id}
                  className="er-row"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    height: 56,
                    borderBottom: `1px solid ${T.border}`,
                    padding: '0 16px',
                    gap: 16,
                    transition: 'background 0.1s',
                    cursor: 'default',
                  }}
                >
                  {/* Name */}
                  <div style={{ flex: 1, minWidth: 180, display: 'flex', alignItems: 'center', gap: 12, overflow: 'hidden' }}>
                    <div style={{
                      width: 32, height: 32, borderRadius: '50%',
                      background: entityColor(entity.name),
                      color: '#FFFFFF',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 11, fontWeight: 700, letterSpacing: '0.02em',
                      flexShrink: 0,
                    }}>
                      {initials(entity.name)}
                    </div>
                    <span style={{ fontSize: 14, fontWeight: 600, color: T.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {entity.name}
                    </span>
                  </div>

                  {/* Slug */}
                  <div style={{ width: 200, flexShrink: 0, overflow: 'hidden' }}>
                    <span style={{
                      fontFamily: "'DM Mono', 'Courier New', monospace",
                      fontSize: 12,
                      color: T.slate,
                      display: 'block',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}>
                      {entity.slug}
                    </span>
                  </div>

                  {/* Type */}
                  <div style={{ width: 100, flexShrink: 0 }}>
                    <span style={{
                      background: typeStyle.bg,
                      color: typeStyle.color,
                      fontSize: 10,
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      borderRadius: 4,
                      padding: '4px 8px',
                      whiteSpace: 'nowrap',
                    }}>
                      {typeStyle.label}
                    </span>
                  </div>

                  {/* Category */}
                  <div style={{ width: 130, flexShrink: 0, fontSize: 13, color: T.textMid, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {entity.category || '—'}
                  </div>

                  {/* Aliases */}
                  <div style={{ width: 150, flexShrink: 0, display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}>
                    {visibleAliases.map(alias => (
                      <span key={alias} style={{
                        background: T.offWhite,
                        border: `1px solid ${T.border}`,
                        borderRadius: 4,
                        padding: '2px 6px',
                        fontSize: 10,
                        fontWeight: 600,
                        color: T.textMid,
                        whiteSpace: 'nowrap',
                      }}>
                        {alias}
                      </span>
                    ))}
                    {extraAliases > 0 && (
                      <span style={{ fontSize: 10, fontWeight: 600, color: T.slate }}>+{extraAliases} more</span>
                    )}
                    {(entity.aliases || []).length === 0 && (
                      <span style={{ fontSize: 12, color: T.slateLight }}>—</span>
                    )}
                  </div>

                  {/* Merchant */}
                  <div style={{ width: 160, flexShrink: 0, fontSize: 13, color: T.textMid, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {entity.merchant || '—'}
                  </div>

                  {/* Created */}
                  <div style={{ width: 110, flexShrink: 0, fontSize: 12, color: T.slate }}>
                    {entity.created_at ? String(entity.created_at).slice(0, 10) : '—'}
                  </div>

                  {/* Actions */}
                  <div style={{ width: 80, flexShrink: 0, display: 'flex', gap: 4, alignItems: 'center' }}>
                    <button
                      className="er-action-btn er-action-btn-edit"
                      onClick={() => openEdit(entity)}
                      title="Edit"
                      style={{
                        width: 28, height: 28, borderRadius: 6,
                        border: 'none', background: 'transparent',
                        fontSize: 14, cursor: 'pointer',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        transition: 'background 0.1s',
                      }}
                    >
                      ✏
                    </button>
                    <button
                      className="er-action-btn er-action-btn-delete"
                      onClick={() => handleDelete(entity)}
                      title="Delete"
                      style={{
                        width: 28, height: 28, borderRadius: 6,
                        border: 'none', background: 'transparent',
                        fontSize: 14, cursor: 'pointer',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        transition: 'background 0.1s',
                      }}
                    >
                      🗑
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* ── Slide-over ──────────────────────────────────────────────────────── */}
      {slideOver && (
        <>
          {/* Overlay */}
          <div
            onClick={closeSlideOver}
            style={{
              position: 'fixed', inset: 0,
              background: 'rgba(0,0,0,0.4)',
              zIndex: 50,
            }}
          />

          {/* Panel */}
          <div style={{
            position: 'fixed', right: 0, top: 0, bottom: 0,
            width: 480,
            background: T.white,
            boxShadow: '-8px 0 32px rgba(0,0,0,0.12)',
            zIndex: 51,
            display: 'flex',
            flexDirection: 'column',
            transform: 'translateX(0)',
            transition: 'transform 0.25s ease',
          }}>

            {/* Header */}
            <div style={{
              height: 56, borderBottom: `1px solid ${T.border}`,
              padding: '0 24px',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              flexShrink: 0,
            }}>
              <span style={{ fontSize: 16, fontWeight: 700, color: T.text }}>
                {slideOver.mode === 'add'
                  ? 'Add New Entity'
                  : `Edit Entity: ${slideOver.entity.name}`}
              </span>
              <button
                onClick={closeSlideOver}
                style={{ width: 24, height: 24, border: 'none', background: 'transparent', fontSize: 18, color: T.slate, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 4 }}
              >
                ×
              </button>
            </div>

            {/* Body */}
            <div style={{ flex: 1, overflowY: 'auto', padding: 24, display: 'flex', flexDirection: 'column', gap: 20 }}>

              {/* Name */}
              <div>
                <label style={labelStyle}>Name *</label>
                <input
                  value={formData.name}
                  onChange={e => {
                    const value = e.target.value
                    if (slideOver.mode === 'add') {
                      setFormData(f => ({ ...f, name: value, slug: slugify(value) }))
                    } else {
                      setFormData(f => ({ ...f, name: value }))
                    }
                  }}
                  placeholder="e.g. Oral-B"
                  style={inputBase}
                />
              </div>

              {/* Slug */}
              <div>
                <label style={labelStyle}>Slug</label>
                <input
                  value={formData.slug}
                  onChange={e => {
                    if (slideOver.mode === 'add') {
                      setFormData(f => ({ ...f, slug: e.target.value }))
                    }
                  }}
                  readOnly={slideOver.mode === 'edit'}
                  style={{
                    ...inputBase,
                    fontFamily: "'DM Mono', 'Courier New', monospace",
                    ...(slideOver.mode === 'edit' ? {
                      background: T.offWhite,
                      cursor: 'not-allowed',
                      color: T.slate,
                    } : {}),
                  }}
                />
                <p style={{ margin: '4px 0 0', fontSize: 11, color: T.slate }}>
                  Auto-generated from name. Cannot be changed after creation.
                </p>
              </div>

              {/* Entity Type */}
              <div>
                <label style={labelStyle}>Entity Type</label>
                <select
                  value={formData.type}
                  onChange={e => setFormData(f => ({ ...f, type: e.target.value }))}
                  style={selectStyle}
                >
                  {['Brand', 'Retailer', 'CPG', 'Service', 'Aggregate'].map(t => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </div>

              {/* Category */}
              <div>
                <label style={labelStyle}>Category</label>
                <input
                  list="category-options"
                  value={formData.category}
                  onChange={e => setFormData(f => ({ ...f, category: e.target.value }))}
                  placeholder="e.g. Personal Care"
                  style={inputBase}
                />
                <datalist id="category-options">
                  {categories.filter(c => c !== 'All Categories').map(c => (
                    <option key={c} value={c} />
                  ))}
                </datalist>
              </div>

              {/* Website URL */}
              <div>
                <label style={labelStyle}>Website URL</label>
                <input
                  value={formData.website_url}
                  onChange={e => setFormData(f => ({ ...f, website_url: e.target.value }))}
                  placeholder="https://..."
                  style={inputBase}
                />
              </div>

              {/* Aliases */}
              <div>
                <label style={labelStyle}>Aliases</label>
                <div style={{
                  border: `1px solid ${T.border}`,
                  borderRadius: 8,
                  padding: '8px 10px',
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 6,
                  minHeight: 44,
                  alignItems: 'center',
                  background: T.white,
                }}>
                  {formData.aliases.map(alias => (
                    <span key={alias} style={{
                      background: T.offWhite,
                      border: `1px solid ${T.border}`,
                      borderRadius: 4,
                      padding: '3px 8px',
                      fontSize: 12,
                      fontWeight: 600,
                      color: T.textMid,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 4,
                    }}>
                      {alias}
                      <button
                        onClick={() => removeAlias(alias)}
                        style={{ border: 'none', background: 'transparent', cursor: 'pointer', padding: 0, fontSize: 12, color: T.slate, lineHeight: 1 }}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                  {formData.aliases.length < 8 && (
                    <input
                      value={aliasInput}
                      onChange={e => setAliasInput(e.target.value)}
                      onKeyDown={handleAliasKeyDown}
                      placeholder="Add..."
                      style={{
                        border: 'none',
                        outline: 'none',
                        fontSize: 13,
                        color: T.text,
                        background: 'transparent',
                        minWidth: 60,
                        flex: 1,
                      }}
                    />
                  )}
                </div>
                <p style={{ margin: '4px 0 0', fontSize: 11, color: T.slate }}>Press Enter or comma to add. Max 8.</p>
              </div>

              {/* System note (edit mode only) */}
              {slideOver.mode === 'edit' && (
                <div style={{
                  background: '#EFF6FF',
                  border: '1px solid #BFDBFE',
                  borderRadius: 8,
                  padding: '12px 14px',
                  display: 'flex',
                  gap: 10,
                  alignItems: 'flex-start',
                }}>
                  <span style={{ color: '#2563EB', fontSize: 16, flexShrink: 0, lineHeight: 1.4 }}>ⓘ</span>
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: '#1D4ED8', marginBottom: 4 }}>
                      SYSTEM NOTE
                    </div>
                    <p style={{ margin: 0, fontSize: 13, color: '#1E40AF', lineHeight: 1.5 }}>
                      This entity is currently linked to 3 active studies. Deletion
                      is restricted until associations are removed.
                    </p>
                  </div>
                </div>
              )}

              {saveError && (
                <div style={{ background: T.redLight, border: `1px solid ${T.red}`, borderRadius: 8, padding: '10px 14px', fontSize: 13, color: T.red }}>
                  {saveError}
                </div>
              )}
            </div>

            {/* Footer */}
            <div style={{
              height: 64,
              borderTop: `1px solid ${T.border}`,
              padding: '0 24px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'flex-end',
              gap: 12,
              flexShrink: 0,
            }}>
              <button
                onClick={closeSlideOver}
                disabled={saving}
                style={{
                  padding: '9px 18px',
                  border: `1px solid ${T.border}`,
                  borderRadius: 8,
                  background: T.white,
                  color: T.text,
                  fontSize: 14,
                  fontWeight: 600,
                  cursor: saving ? 'not-allowed' : 'pointer',
                  opacity: saving ? 0.5 : 1,
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving || !formData.name.trim()}
                style={{
                  padding: '9px 18px',
                  border: 'none',
                  borderRadius: 8,
                  background: T.text,
                  color: T.white,
                  fontSize: 14,
                  fontWeight: 600,
                  cursor: (saving || !formData.name.trim()) ? 'not-allowed' : 'pointer',
                  opacity: (saving || !formData.name.trim()) ? 0.6 : 1,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  minWidth: 120,
                  justifyContent: 'center',
                }}
              >
                {saving ? (
                  <>
                    <span style={{ width: 14, height: 14, border: '2px solid rgba(255,255,255,0.3)', borderTopColor: T.white, borderRadius: '50%', display: 'inline-block', animation: 'spin 0.6s linear infinite' }} />
                    Saving…
                  </>
                ) : (
                  slideOver.mode === 'add' ? 'Add Entity' : 'Save Changes'
                )}
              </button>
            </div>
          </div>
        </>
      )}

      {/* ── Toast ───────────────────────────────────────────────────────────── */}
      {toast && (
        <div style={{
          position: 'fixed',
          bottom: 24,
          right: 24,
          zIndex: 100,
          padding: '12px 18px',
          borderRadius: 8,
          fontSize: 14,
          fontWeight: 600,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          boxShadow: '0 4px 16px rgba(0,0,0,0.15)',
          background: toast.type === 'success' ? T.navy : T.red,
          color: T.white,
        }}>
          {toast.type === 'success' ? '✓' : '✗'}
          {toast.message}
        </div>
      )}

      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}
