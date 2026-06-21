import React, { useState, useEffect, useCallback } from 'react'
import { api } from '../api.js'

/**
 * ScopeSkuManager — additive panel for designating specific SKUs (a catalog
 * product at a specific retailer) as the measurement scope for a cycle.
 *
 * Self-contained: takes a cycleId and renders a catalog search box +
 * results list with "Add to scope", a "paste product URL" field, and the
 * current scope SKU list with delete. Does not replace any existing cycle
 * setup UI — intended to be dropped into a cycle's detail view.
 *
 * When the cycle has no scope SKUs, the rest of the pipeline behaves
 * exactly as it did before this component existed — this panel is purely
 * additive authoring UI.
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

export default function ScopeSkuManager({ cycleId }) {
  const [scopeSkus, setScopeSkus] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const [q, setQ] = useState('')
  const [brand, setBrand] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [searching, setSearching] = useState(false)

  const [productUrl, setProductUrl] = useState('')
  const [resolving, setResolving] = useState(false)

  const refresh = useCallback(() => {
    if (!cycleId) return
    api.getScopeSkus(cycleId)
      .then(rows => setScopeSkus(rows))
      .catch(err => setError(err.message))
  }, [cycleId])

  useEffect(() => { refresh() }, [refresh])

  if (!cycleId) {
    return null
  }

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
    try {
      await api.addScopeSku(cycleId, {
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
      })
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
    try {
      await api.addScopeSku(cycleId, {
        product_url: productUrl.trim(),
        role: 'target',
      })
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
      await api.deleteScopeSku(id)
      refresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ border: `1px solid ${T.border}`, borderRadius: 10, padding: 16, marginTop: 16 }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: T.text, marginBottom: 10 }}>
        Scope SKUs <span style={{ color: T.slate, fontWeight: 400 }}>(optional — score against exact products)</span>
      </div>

      {error && (
        <div style={{ color: T.red, fontSize: 12, marginBottom: 8 }}>{error}</div>
      )}

      {/* Current scope SKUs */}
      {scopeSkus.length > 0 && (
        <div style={{ marginBottom: 14 }}>
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
              <button
                onClick={() => handleDelete(sku.id)}
                disabled={loading}
                style={{ border: 'none', background: 'none', color: T.red, cursor: 'pointer', fontSize: 12 }}
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      )}

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
    </div>
  )
}
