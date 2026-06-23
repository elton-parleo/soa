import React, { useState, useEffect, useCallback } from 'react'
import { api } from '../api.js'

/**
 * ScopeSkuManager — panel for designating specific SKUs (a catalog product
 * at a specific retailer) as measured scope.
 *
 * Two contexts, via props:
 *   <ScopeSkuManager entityId={entity.id} />
 *     Full edit of the brand's living template (entity_id set, cycle_id
 *     NULL). Always editable.
 *   <ScopeSkuManager cycleId={cycle.id} readOnly={bool} />
 *     A cycle's effective scope (soa_shared.scope_resolution). Editable
 *     only while the cycle is Planned and not yet frozen/forced read-only
 *     by the caller — once scope_frozen_at is set, the API reports
 *     is_editable=false and this renders the list without add/remove
 *     controls regardless of the readOnly prop.
 *
 * Same search/URL/add/remove UI in both contexts; read-only mode hides
 * the mutating controls and shows the list plus a short explanatory note.
 */

const T = {
  border: '#E2E8F0',
  text: '#0F172A',
  textMid: '#334155',
  slate: '#64748B',
  teal: '#0D9488',
  tealLight: '#CCFBF1',
  red: '#DC2626',
  offWhite: '#F8FAFC',
}

const inputStyle = {
  padding: '6px 10px',
  border: `1px solid ${T.border}`,
  borderRadius: 6,
  fontSize: 13,
  flex: 1,
  minWidth: 0,
}

const buttonStyle = {
  padding: '6px 12px',
  borderRadius: 6,
  border: 'none',
  background: T.teal,
  color: '#fff',
  fontSize: 13,
  fontWeight: 600,
  cursor: 'pointer',
  whiteSpace: 'nowrap',
}

const SOURCE_LABEL = {
  frozen: 'Frozen with this cycle’s run',
  custom: 'Customized for this cycle',
  inherited: 'Inherited live from the brand template',
  materialized: 'Snapshot captured at cycle creation',
}

export default function ScopeSkuManager({ entityId, cycleId, readOnly = false }) {
  const mode = entityId != null ? 'entity' : cycleId != null ? 'cycle' : null

  const [scopeSkus, setScopeSkus] = useState([])
  const [source, setSource] = useState(null)
  const [isEditable, setIsEditable] = useState(mode === 'entity')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const [q, setQ] = useState('')
  const [brand, setBrand] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [searching, setSearching] = useState(false)

  const [productUrl, setProductUrl] = useState('')
  const [resolving, setResolving] = useState(false)

  const refresh = useCallback(() => {
    if (mode === 'entity') {
      api.getEntityScopeSkus(entityId)
        .then(rows => setScopeSkus(rows))
        .catch(err => setError(err.message))
    } else if (mode === 'cycle') {
      api.getScopeSkus(cycleId)
        .then(result => {
          setScopeSkus(result.skus || [])
          setSource(result.source)
          setIsEditable(!!result.is_editable)
        })
        .catch(err => setError(err.message))
    }
  }, [mode, entityId, cycleId])

  useEffect(() => { refresh() }, [refresh])

  if (mode === null) {
    return null
  }

  const canEdit = mode === 'entity' ? true : (isEditable && !readOnly)

  async function handleSearch() {
    setSearching(true)
    setError(null)
    try {
      const result = await api.searchScopeCatalog({ q, brand })
      setSearchResults(result.listings || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setSearching(false)
    }
  }

  async function handleAddListing(listing) {
    setLoading(true)
    setError(null)
    const payload = {
      listing_id: listing.listing_id,
      catalog_product_id: listing.catalog_product_id,
      merchant_slug: listing.merchant_slug,
      merchant_sku: listing.merchant_sku,
      brand: listing.brand,
      category: listing.category,
      product_url: listing.product_url,
      listed_price: listing.listed_price,
      currency: listing.currency,
      display_name: listing.name,
      role: 'target',
    }
    try {
      if (mode === 'entity') {
        await api.addEntityScopeSku(entityId, payload)
      } else {
        await api.addScopeSku(cycleId, payload)
      }
      refresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleAddFromUrl() {
    if (!productUrl.trim()) return
    setResolving(true)
    setError(null)
    const payload = { product_url: productUrl.trim(), role: 'target' }
    try {
      if (mode === 'entity') {
        await api.addEntityScopeSku(entityId, payload)
      } else {
        await api.addScopeSku(cycleId, payload)
      }
      setProductUrl('')
      refresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setResolving(false)
    }
  }

  async function handleDelete(id) {
    setLoading(true)
    setError(null)
    try {
      if (mode === 'entity') {
        await api.deleteScopeSku(id)
      } else {
        await api.deleteCycleScopeSku(cycleId, id)
      }
      refresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ border: `1px solid ${T.border}`, borderRadius: 10, padding: 16, marginTop: 16 }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: T.text, marginBottom: 4 }}>
        {mode === 'entity' ? 'Measured SKUs' : 'Scope SKUs'}{' '}
        <span style={{ color: T.slate, fontWeight: 400 }}>
          {mode === 'entity'
            ? '(this brand’s living, editable measured-SKU set)'
            : '(optional — score against exact products)'}
        </span>
      </div>

      {mode === 'cycle' && source && (
        <div style={{ fontSize: 12, color: T.slate, marginBottom: 10 }}>
          {SOURCE_LABEL[source] || source}
          {!canEdit && source === 'frozen' && (
            <span> — to change scope, clone into a new cycle.</span>
          )}
        </div>
      )}

      {error && (
        <div style={{ color: T.red, fontSize: 12, marginBottom: 8 }}>{error}</div>
      )}

      {/* Current scope SKUs */}
      {scopeSkus.length > 0 && (
        <div style={{ marginBottom: canEdit ? 14 : 0 }}>
          {scopeSkus.map(sku => (
            <div
              key={sku.id}
              style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '6px 10px', background: T.offWhite, borderRadius: 6, marginBottom: 4,
              }}
            >
              <span style={{ fontSize: 13, color: T.textMid }}>
                {sku.display_name || sku.merchant_sku || `Listing #${sku.dealengine_listing_id}`}
                {sku.merchant_slug ? ` — ${sku.merchant_slug}` : ''}
                {sku.role === 'competitor' ? ' (competitor)' : ''}
              </span>
              {canEdit && (
                <button
                  onClick={() => handleDelete(sku.id)}
                  disabled={loading}
                  style={{ border: 'none', background: 'none', color: T.red, cursor: 'pointer', fontSize: 12 }}
                >
                  Remove
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {!canEdit && scopeSkus.length === 0 && (
        <div style={{ fontSize: 13, color: T.slate }}>No SKUs in scope.</div>
      )}

      {canEdit && (
        <>
          {/* Catalog search */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
            <input
              style={inputStyle}
              placeholder="Search catalog (e.g. product name)"
              value={q}
              onChange={e => setQ(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
            />
            <input
              style={{ ...inputStyle, flex: 0.6 }}
              placeholder="Brand"
              value={brand}
              onChange={e => setBrand(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
            />
            <button style={buttonStyle} onClick={handleSearch} disabled={searching}>
              {searching ? 'Searching…' : 'Search'}
            </button>
          </div>

          {searchResults.length > 0 && (
            <div style={{ marginBottom: 14, maxHeight: 220, overflowY: 'auto' }}>
              {searchResults.map(listing => (
                <div
                  key={listing.listing_id}
                  style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '6px 10px', borderBottom: `1px solid ${T.border}`,
                  }}
                >
                  <span style={{ fontSize: 13, color: T.textMid }}>
                    {listing.name} — {listing.merchant_slug}
                    {listing.listed_price != null ? ` ($${listing.listed_price})` : ''}
                  </span>
                  <button style={buttonStyle} onClick={() => handleAddListing(listing)} disabled={loading}>
                    Add to scope
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Paste product URL */}
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              style={inputStyle}
              placeholder="Paste a product URL instead…"
              value={productUrl}
              onChange={e => setProductUrl(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleAddFromUrl()}
            />
            <button style={buttonStyle} onClick={handleAddFromUrl} disabled={resolving}>
              {resolving ? 'Resolving…' : 'Add from URL'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
