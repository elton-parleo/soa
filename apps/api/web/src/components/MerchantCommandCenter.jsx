import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import Sidebar from './Sidebar.jsx'
import { api } from '../api.js'
import { truesyncApi, fetchAllVerifications, withMutationTimeout } from '../truesyncApi.js'
import SyncMatrix from './merchant-command-center/SyncMatrix.jsx'
import ListingDrawer from './merchant-command-center/ListingDrawer.jsx'
import SyncRulesTab from './merchant-command-center/SyncRulesTab.jsx'
import DrawerErrorBoundary from './merchant-command-center/DrawerErrorBoundary.jsx'
import {
  orderChannels, channelImplementation, isMutedImplementation,
  latestPublicationByCell, buildCell, buildCatalogRows, summarize,
  VERIFIED_AT_UNAVAILABLE,
} from './merchant-command-center/truesyncDerive.js'
import './merchant-command-center/commandCenter.css'

/**
 * Merchant Command Center — what is live on every agent-readable
 * surface for the active merchant, and where it has drifted.
 *
 * Follows this app's page conventions: Sidebar + topbar + body, same as
 * ActionsPage.jsx / MetricsDashboard.jsx, mounted as a view in App.jsx.
 * Inside the body it switches to the design language of
 * design-refs/merchant-command-center-mock.html, scoped under .mcc (see
 * merchant-command-center/commandCenter.css).
 *
 * Data flow, and the reason it is split:
 *   reads   browser -> TRUESYNC_API_BASE directly (that API allows any
 *           origin on GET)
 *   writes  browser -> this app's authed proxy -> TrueSync, so
 *           TRUESYNC_ADMIN_KEY never reaches the client
 *
 * Everything on screen is live API output. Nothing falls back to the
 * mock's illustrative values, and no state is inferred: no publication
 * row reads "never published", no verification reads ○.
 */

// Verify actions the API does not offer. Kept as one named constant so
// the two buttons that carry it say exactly the same thing, and so
// deleting it is the single edit needed when the endpoints land.
const VERIFY_WIREUP_PENDING =
  'Wire-up pending — TrueSync exposes no verify endpoint (no POST /verify-all, ' +
  'no POST /listings/{id}/verify) as of 2026-08-22'

function Toasts({ toasts, onDismiss }) {
  if (toasts.length === 0) return null
  return (
    <div className="mcc-toasts" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`mcc-toast ${t.kind}`}>
          <span className="msg">{t.message}</span>
          <button onClick={() => onDismiss(t.id)} aria-label="Dismiss">×</button>
        </div>
      ))}
    </div>
  )
}

export default function MerchantCommandCenter({ onNavigate }) {
  const [brand,        setBrand]        = useState(null)
  const [channels,     setChannels]     = useState([])
  const [rows,         setRows]         = useState([])
  const [publications, setPublications] = useState([])
  const [loading,      setLoading]      = useState(true)
  const [loadError,    setLoadError]    = useState(null)
  const [tab,          setTab]          = useState('catalog')
  const [selectedId,   setSelectedId]   = useState(null)
  const [toasts,       setToasts]       = useState([])
  const [busy,         setBusy]         = useState(null)   // a mutation key, or null
  const [ruleState,    setRuleState]    = useState({})
  // "listingId:channelSlug" -> VerificationResponse[], newest first.
  const [verificationsByCell, setVerificationsByCell] = useState({})
  const drawerRef = useRef(null)

  const pushToast = useCallback((kind, message) => {
    const id = `${Date.now()}-${Math.random()}`
    setToasts((list) => [...list, { id, kind, message }])
    // Errors stay until dismissed — an operator who clicked Publish and
    // walked away should still find out it failed.
    if (kind === 'ok') setTimeout(() => setToasts((l) => l.filter((t) => t.id !== id)), 6000)
  }, [])

  const dismissToast = useCallback((id) => {
    setToasts((list) => list.filter((t) => t.id !== id))
  }, [])

  // ─── Load ──────────────────────────────────────────────────────────
  const load = useCallback((signal) => {
    setLoading(true)
    setLoadError(null)

    // The brand, channel and publication reads are independent; the
    // catalog needs the brand's merchant_slug, and each listing's
    // canonical record needs the catalog. Hence two waves.
    return Promise.all([
      truesyncApi.getActiveBrand({ signal }),
      truesyncApi.getChannels({ signal }),
      truesyncApi.getPublications({ signal }),
    ])
      .then(async ([brandData, channelData, pubData]) => {
        const spine = await truesyncApi.getMerchantSchemaOrg(brandData.merchant_slug, { signal })

        // Per-listing detail: variant counts, GTIN coverage and the
        // catalog_product_id the sync-rule API is keyed by. There is no
        // bulk form of this endpoint upstream. A listing whose detail
        // fetch fails still gets a row (buildCatalogRows fills nulls)
        // rather than disappearing from the matrix.
        const details = await Promise.all(
          spine.map((entry) =>
            truesyncApi.getListing(entry.listing_id, { signal })
              .then((d) => [entry.listing_id, d])
              .catch(() => [entry.listing_id, null]),
          ),
        )
        const detailsById = Object.fromEntries(details.filter(([, d]) => d))

        if (signal?.aborted) return
        const orderedChannels = orderChannels(channelData)
        const catalogRows = buildCatalogRows(spine, detailsById)
        setBrand(brandData)
        setChannels(orderedChannels)
        setPublications(Array.isArray(pubData) ? pubData : [])
        setRows(catalogRows)

        // The matrix is rendered as soon as the catalog is in hand;
        // verification history then fills the badges in behind it.
        // Deliberately not awaited before the first paint — it is
        // listings x channels requests (the endpoint has no bulk form),
        // and a matrix that is visible with ○ badges beats a spinner.
        // ○ is also the correct reading until a run says otherwise.
        setLoading(false)
        const verifications = await fetchAllVerifications(
          catalogRows.map((r) => r.listingId),
          orderedChannels.map((c) => c.slug),
          { signal },
        )
        if (signal?.aborted) return
        setVerificationsByCell(verifications)
      })
      .catch((err) => {
        if (signal?.aborted) return
        setLoadError(err.message || 'TrueSync is unreachable')
      })
      .finally(() => { if (!signal?.aborted) setLoading(false) })
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    load(controller.signal)
    return () => controller.abort()
  }, [load])

  // ─── Derived ───────────────────────────────────────────────────────
  const channelState = useMemo(() => {
    const out = {}
    for (const channel of channels) {
      const implementation = channelImplementation(channel.slug, publications)
      out[channel.slug] = { implementation, muted: isMutedImplementation(implementation) }
    }
    return out
  }, [channels, publications])

  const publicationByCell = useMemo(
    () => latestPublicationByCell(publications), [publications],
  )

  const cellFor = useCallback((row, channel) => buildCell({
    publication: publicationByCell.get(`${row.listingId}:${channel.slug}`),
    // Absent until the verification pass lands (and permanently absent
    // for a cell whose fetch failed) — buildCell reads that as ○, not
    // as a clean ✓.
    verifications: verificationsByCell[`${row.listingId}:${channel.slug}`] || [],
    implementation: channelState[channel.slug]?.implementation,
  }), [publicationByCell, channelState, verificationsByCell])

  const stats = useMemo(
    () => summarize(rows, channels, cellFor), [rows, channels, cellFor],
  )

  const accent = brand?.site?.primary_color || null
  const selectedRow = rows.find((r) => r.listingId === selectedId) || null

  /**
   * Bring the drift inspector into view when a row is selected.
   *
   * This is the fix for the "dead click" — the drawer renders BELOW the
   * matrix, and with five listings on a 900px viewport its top lands
   * ~157px past the fold. Selecting a row worked correctly and threw
   * nothing; it just put the result somewhere the operator could not
   * see, and clicking the row again toggled it shut. Nothing in the
   * console, nothing on screen.
   *
   * 'nearest' rather than 'start': when the drawer is already visible,
   * switching rows should not yank the page around.
   */
  useEffect(() => {
    const node = drawerRef.current
    // scrollIntoView is not implemented in jsdom, and this is a
    // convenience rather than a correctness concern — never let it be
    // the thing that breaks the page.
    if (selectedId == null || !node || typeof node.scrollIntoView !== 'function') return
    const reduceMotion = typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    try {
      node.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'nearest' })
    } catch (_) {
      node.scrollIntoView()
    }
  }, [selectedId])

  // ─── Mutations (all proxied; no optimistic updates) ────────────────
  async function handlePublish(row, channelSlug) {
    const key = `publish:${row.listingId}:${channelSlug || 'all'}`
    setBusy(key)
    try {
      const result = await withMutationTimeout(
        api.publishListing(row.listingId, channelSlug), 'Publish')
      // Render what the server returned, not what we hoped for: fold
      // the returned PublicationRows straight into state.
      if (Array.isArray(result) && result.length > 0) {
        setPublications((prev) => [...result, ...prev])
        const failed = result.filter((r) => r.status === 'failed')
        if (failed.length > 0) {
          pushToast('err', failed.map((r) => `${r.channel_slug}: ${r.error || 'failed'}`).join(' · '))
        } else {
          pushToast('ok', `Published ${row.name} to ${result.map((r) => r.channel_slug).join(', ')}`)
        }
      } else {
        pushToast('ok', `Publish returned no rows for ${row.name}`)
      }
    } catch (err) {
      pushToast('err', err.message)   // verbatim, per spec
    } finally {
      setBusy(null)
    }
  }

  async function handleRefreshDiagnostics() {
    setBusy('gmc')
    try {
      const result = await withMutationTimeout(
        api.refreshGmcDiagnostics(), 'Refresh Google diagnostics')
      pushToast('ok', `Google diagnostics refreshed${
        Array.isArray(result) ? ` — ${result.length} record(s)` : ''
      }`)
      // Diagnostics land as verification rows, so both halves of the
      // matrix have to be re-read — publications for any new publish
      // lineage, verifications for the item issues themselves.
      const pubs = await truesyncApi.getPublications({})
      setPublications(Array.isArray(pubs) ? pubs : [])
      setVerificationsByCell(await fetchAllVerifications(
        rows.map((r) => r.listingId), channels.map((c) => c.slug),
      ))
    } catch (err) {
      pushToast('err', err.message)
    } finally {
      setBusy(null)
    }
  }

  async function handleToggleRule(row, channelSlug, next) {
    if (row.catalogProductId == null) return
    const key = `${row.catalogProductId}:${channelSlug}`
    setBusy(key)
    try {
      const result = await withMutationTimeout(
        api.putSyncRule({
          catalog_product_id: row.catalogProductId,
          channel_slug: channelSlug,
          enabled: next,
        }),
        'Sync-rule update',
      )
      // The echoed `enabled` is the only trustworthy value here, since
      // there is nothing to read the rule back from.
      setRuleState((prev) => ({ ...prev, [key]: !!result?.enabled }))
      pushToast('ok', `${channelSlug} ${result?.enabled ? 'enabled' : 'disabled'} for ${row.name}`)
    } catch (err) {
      pushToast('err', err.message)
    } finally {
      setBusy(null)
    }
  }

  // ─── Render ────────────────────────────────────────────────────────
  return (
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: "'DM Sans', sans-serif", background: '#F5F6F2' }}>
      <Sidebar activeView="command-center" onNavigate={onNavigate} />

      <div style={{ flex: 1, marginLeft: 200, minWidth: 0 }}>
        <div
          className="mcc"
          // The brand's accent from the active-brand API drives every
          // accent on the page (tab underline, primary buttons, brand
          // dot). Never a hardcoded demo-brand colour; falls back to the
          // mock's cobalt only when the brand call itself failed.
          style={accent ? { '--brand-accent': accent } : undefined}
        >
          <div className="mcc-contextbar">
            <div className="mcc-brand">
              <span className="mcc-brand-dot" />
              <div>
                <div className="mcc-brand-name">
                  {brand?.site?.display_name || (loading ? 'Loading…' : 'Brand unavailable')}
                </div>
                <div className="mcc-brand-slug mono">{brand?.merchant_slug || '—'}</div>
              </div>
            </div>

            <div className="mcc-context-meta">
              <span>
                <strong>{stats.publishedCells}</strong> published
                <span style={{ color: 'var(--ink-faint)' }}> / {stats.totalCells} cells</span>
              </span>
              <span>·</span>
              <span><strong>{stats.verifiedCells}</strong> verified</span>
              <span>·</span>
              <span><strong>{stats.driftCells}</strong> with drift</span>
              <span>·</span>
              {/* Stated as unavailable rather than filled with a
                  publish time. VerificationResponse has no timestamp. */}
              <span title={VERIFIED_AT_UNAVAILABLE} style={{ color: 'var(--ink-faint)' }}>
                last verified: n/a
              </span>
            </div>

            <div className="mcc-spacer" />

            <button
              className="mcc-btn"
              disabled
              title={VERIFY_WIREUP_PENDING}
            >
              Verify all
            </button>
            <button
              className="mcc-btn primary"
              onClick={handleRefreshDiagnostics}
              disabled={busy === 'gmc' || loading}
            >
              {busy === 'gmc'
                ? <><span className="mcc-spinner" /> Refreshing…</>
                : 'Refresh Google diagnostics'}
            </button>
          </div>

          {loadError && (
            <div className="mcc-banner error" role="alert">
              <span>
                <strong>TrueSync could not be reached.</strong> {loadError}
              </span>
              <button className="mcc-btn" onClick={() => load()}>Retry</button>
            </div>
          )}

          <nav className="mcc-tabs">
            <button
              className={tab === 'catalog' ? 'active' : ''}
              onClick={() => setTab('catalog')}
            >
              Catalog
            </button>
            <button
              className={tab === 'rules' ? 'active' : ''}
              onClick={() => setTab('rules')}
            >
              Sync rules
            </button>
          </nav>

          <main className="mcc-main">
            {loading && <div className="mcc-loading">Loading TrueSync catalog…</div>}

            {!loading && !loadError && rows.length === 0 && (
              <div className="mcc-panel" style={{ padding: '60px 20px', textAlign: 'center' }}>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>No listings published yet</div>
                <div className="mcc-empty">
                  This merchant has no schema.org publications, so there is nothing to syndicate.
                </div>
              </div>
            )}

            {!loading && rows.length > 0 && tab === 'catalog' && (
              <>
                <div className="mcc-stats">
                  <div className="mcc-stat">
                    <div className="label">Listings</div>
                    <div className="value">{rows.length}</div>
                    <div className="sub">
                      {rows.reduce((n, r) => n + r.variantCount, 0)} variants ·{' '}
                      {rows.reduce((n, r) => n + r.gtinCount, 0)} with GTIN
                    </div>
                  </div>
                  <div className="mcc-stat sync">
                    <div className="label">Surface cells published</div>
                    <div className="value">
                      {stats.publishedCells}<small> / {stats.totalCells}</small>
                    </div>
                    <div className="sub">Across {channels.length} channels</div>
                  </div>
                  <div className="mcc-stat drifting">
                    <div className="label">Drifting</div>
                    <div className="value">{stats.driftCells}</div>
                    <div className="sub">
                      {stats.verifiedCells === 0 && stats.driftCells === 0
                        ? 'No verification runs recorded'
                        : `${stats.verifiedCells} verified clean`}
                    </div>
                  </div>
                  <div className="mcc-stat">
                    <div className="label">Last verified</div>
                    <div className="value unavailable">n/a</div>
                    <div className="sub">{VERIFIED_AT_UNAVAILABLE}</div>
                  </div>
                </div>

                <SyncMatrix
                  rows={rows}
                  channels={channels}
                  channelState={channelState}
                  cellFor={cellFor}
                  selectedListingId={selectedId}
                  onSelectRow={(id) => setSelectedId((cur) => (cur === id ? null : id))}
                />

                {selectedRow && (
                  <div ref={drawerRef}>
                    {/* Anything the inspector throws becomes a visible
                        panel rather than an unmounted subtree — see
                        DrawerErrorBoundary.jsx. A selected row must
                        always put something on screen. */}
                    <DrawerErrorBoundary
                      resetKey={selectedRow.listingId}
                      onClose={() => setSelectedId(null)}
                      context={`listing_id ${selectedRow.listingId} · ${selectedRow.name}`}
                    >
                      <ListingDrawer
                        row={selectedRow}
                        channels={channels}
                        channelState={channelState}
                        cellFor={cellFor}
                        publications={publications}
                        verificationsByCell={verificationsByCell}
                        onClose={() => setSelectedId(null)}
                        onPublish={handlePublish}
                        publishPending={String(busy || '').startsWith(`publish:${selectedRow.listingId}`)}
                      />
                    </DrawerErrorBoundary>
                  </div>
                )}
              </>
            )}

            {!loading && rows.length > 0 && tab === 'rules' && (
              <SyncRulesTab
                rows={rows}
                channels={channels}
                channelState={channelState}
                ruleState={ruleState}
                pendingKey={busy}
                onToggle={handleToggleRule}
              />
            )}
          </main>
        </div>
      </div>

      <Toasts toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}
