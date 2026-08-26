import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import Sidebar from './Sidebar.jsx'
import { api } from '../api.js'
import { truesyncApi, fetchAllVerifications, withMutationTimeout } from '../truesyncApi.js'
import SyncMatrix from './merchant-command-center/SyncMatrix.jsx'
import ListingDrawer from './merchant-command-center/ListingDrawer.jsx'
import SyncRulesTab from './merchant-command-center/SyncRulesTab.jsx'
import DrawerErrorBoundary from './merchant-command-center/DrawerErrorBoundary.jsx'
import CatalogSourceSwitcher from './merchant-command-center/CatalogSourceSwitcher.jsx'
import ProspectView from './merchant-command-center/ProspectView.jsx'
import {
  orderChannels, channelImplementation, isMutedImplementation,
  latestPublicationByCell, buildCatalogRows, relativeTime, absoluteTime,
} from './merchant-command-center/truesyncDerive.js'
import {
  aggregateCell, summarize, aggregateProspectProduct, summarizeProspect, ACCEPTANCE,
  VERIFY_BY_CHANNEL,
} from './merchant-command-center/verificationModel.js'
import './merchant-command-center/commandCenter.css'

const SCHEMA_ORG_SLUG = 'schema_org'
const ACP_SLUG = 'acp'

// Which client call probes which channel. Keyed by the same slugs as
// VERIFY_BY_CHANNEL, which decides whether the button is offered at all —
// the two are asserted to agree in the test suite, so a channel can never
// be offered a button that routes nowhere.
const VERIFIERS = {
  [SCHEMA_ORG_SLUG]: (listingId) => api.verifyListing(listingId),
  [ACP_SLUG]: (listingId) => api.verifyListingAcp(listingId),
}

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

  // Catalog source. null = the live merchant (the sync matrix and the
  // whole cell model); a slug = a prospect, which is a different view
  // entirely because nothing about a prospect publishes.
  const [prospects,      setProspects]      = useState([])
  const [prospectSlug,   setProspectSlug]   = useState(null)
  const [prospectDrift,  setProspectDrift]  = useState(null)
  const [prospectLoading, setProspectLoading] = useState(false)
  const [prospectError,  setProspectError]  = useState(null)

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
    // The prospect list is fetched alongside, and its failure is not
    // allowed to take the page down: prospects are an additional view,
    // not a prerequisite for the live merchant's.
    // Promise.resolve() so that even a synchronous throw here — a
    // stubbed or misconfigured client — cannot take down the live
    // merchant's view, which does not depend on this at all.
    Promise.resolve()
      .then(() => truesyncApi.getProspects({ signal }))
      .then((data) => {
        if (signal?.aborted) return
        setProspects(Array.isArray(data?.prospects) ? data.prospects : [])
      })
      .catch(() => { if (!signal?.aborted) setProspects([]) })

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

  // Prospect drift, loaded on selection rather than up front: it is a
  // per-prospect report and the live merchant's view never needs it.
  useEffect(() => {
    if (prospectSlug == null) {
      setProspectDrift(null)
      setProspectError(null)
      return
    }
    const controller = new AbortController()
    setProspectLoading(true)
    setProspectError(null)
    truesyncApi.getProspectDrift(prospectSlug, { signal: controller.signal })
      .then((data) => { if (!controller.signal.aborted) setProspectDrift(data) })
      .catch((err) => {
        if (controller.signal.aborted) return
        setProspectDrift(null)
        setProspectError(err.message || 'Prospect drift could not be loaded')
      })
      .finally(() => { if (!controller.signal.aborted) setProspectLoading(false) })
    return () => controller.abort()
  }, [prospectSlug])

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

  /**
   * One cell, fully described. Everything the UI shows about a cell
   * comes from here — see docs/verification-semantics.md. Components
   * render these fields and count nothing themselves.
   */
  const cellFor = useCallback((row, channel) => aggregateCell(
    publicationByCell.get(`${row.listingId}:${channel.slug}`),
    verificationsByCell[`${row.listingId}:${channel.slug}`] || [],
    { channelSlug: channel.slug },
  ), [publicationByCell, verificationsByCell])

  const cells = useMemo(() => {
    const out = []
    for (const row of rows) {
      for (const channel of channels) out.push(cellFor(row, channel))
    }
    return out
  }, [rows, channels, cellFor])

  const stats = useMemo(() => summarize(cells), [cells])

  // Prospect data goes through the model's own pure functions and is
  // summarized separately — it contributes nothing to `stats` above,
  // which is the live merchant's and only the live merchant's.
  const prospectProducts = useMemo(
    () => (prospectDrift?.products || []).map(aggregateProspectProduct),
    [prospectDrift],
  )
  const prospectTotals = useMemo(() => summarizeProspect(prospectProducts), [prospectProducts])
  const activeProspect = prospects.find((p) => p.slug === prospectSlug) || null
  const inProspectMode = prospectSlug != null

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

  // Every verify mutation ends the same way: re-read the verification
  // pass so the badges reflect what the run actually recorded. Never an
  // optimistic update — the page renders the server's answer.
  const reloadVerifications = useCallback(async (currentRows, currentChannels) => {
    const listingIds = (currentRows || []).map((r) => r.listingId)
    const channelSlugs = (currentChannels || []).map((c) => c.slug)
    if (listingIds.length === 0 || channelSlugs.length === 0) return
    setVerificationsByCell(await fetchAllVerifications(listingIds, channelSlugs))
  }, [])

  async function handleVerifyListing(row, channelSlug = SCHEMA_ORG_SLUG) {
    // Channel-aware on purpose. Every channel used to route here and get the
    // schema.org probe, so verifying an ACP cell wrote a schema_org row and
    // left the ACP cell unverified — with a success toast on top.
    const verifier = VERIFIERS[channelSlug]
    if (!verifier) {
      pushToast('err', `${channelSlug} has no probe to run`)
      return
    }

    const key = `verify:${row.listingId}:${channelSlug}`
    setBusy(key)
    try {
      const result = await withMutationTimeout(
        verifier(row.listingId), 'Verify')
      await reloadVerifications(rows, channels)

      // Report what came back, including the unhappy outcomes — a probe
      // that could not read the page is not a success.
      const outcome = result?.outcome
      if (result?.error) {
        pushToast('err', `${row.name}: ${result.error}`)
      } else if (outcome && outcome !== 'ok') {
        pushToast('err', `${row.name} · ${channelSlug}: probe outcome "${outcome}"`)
      } else {
        const n = Array.isArray(result?.findings) ? result.findings.length : 0
        const what = `${row.name} · ${channelSlug}`
        pushToast('ok', n > 0
          ? `Verified ${what} — ${n} finding${n === 1 ? '' : 's'}`
          : `Verified ${what} — no drift`)
      }
    } catch (err) {
      pushToast('err', err.message)   // verbatim, per spec
    } finally {
      setBusy(null)
    }
  }

  async function handleVerifyAll() {
    setBusy('verify-all')
    try {
      const result = await withMutationTimeout(api.verifyAll(), 'Verify all')
      await reloadVerifications(rows, channels)

      // The upstream's summary shape is not pinned down, so report a
      // count when it gives one and stay vague when it does not, rather
      // than inventing a number.
      const count = Array.isArray(result)
        ? result.length
        : (typeof result?.verified === 'number' ? result.verified : null)
      pushToast('ok', count != null
        ? `Verified ${count} listing${count === 1 ? '' : 's'}`
        : 'Verification run complete')
    } catch (err) {
      pushToast('err', err.message)
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
      await reloadVerifications(rows, channels)
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

            {prospects.length > 0 && (
              <CatalogSourceSwitcher
                brandName={brand?.site?.display_name}
                prospects={prospects}
                activeSlug={prospectSlug}
                onSelect={(slug) => {
                  setProspectSlug(slug)
                  setSelectedId(null)   // the drawer belongs to the matrix
                }}
              />
            )}

            {/* The live merchant's counts are hidden in prospect mode
                rather than recomputed: they describe cells that this
                view does not show, and prospect data contributes to
                none of them. */}
            {!inProspectMode && (
            <div className="mcc-context-meta">
              {/* Every number here comes from summarize(). The four
                  dimensions are reported separately and never summed
                  together — see docs/verification-semantics.md. */}
              <span>
                <strong>{stats.publishedCells}</strong> published
                <span style={{ color: 'var(--ink-faint)' }}> / {stats.totalCells} cells</span>
              </span>
              <span>·</span>
              <span><strong>{stats.verifiedCells}</strong> verified</span>
              <span>·</span>
              <span><strong>{stats.driftingCells}</strong> drifting</span>

              {stats.issueCount > 0 && (
                <>
                  <span>·</span>
                  <span title="Surface acceptance issues reported by the channel. Counted separately from drift.">
                    <strong>{stats.issueCount}</strong> issue{stats.issueCount === 1 ? '' : 's'}
                  </span>
                </>
              )}

              {stats.notFoundCells > 0 && (
                <>
                  <span>·</span>
                  <span title="Published, but the channel has no record of the item.">
                    <strong>{stats.notFoundCells}</strong> not in feed
                  </span>
                </>
              )}

              {stats.unreadableCount > 0 && (
                <>
                  <span>·</span>
                  <span title="Verification records this page could not read. Not drift, not issues — our own gap.">
                    <strong>{stats.unreadableCount}</strong> unreadable
                  </span>
                </>
              )}

              {stats.staleCount > 0 && (
                <>
                  <span>·</span>
                  <span title="Verification records that pre-date the latest publish. They verified a superseded artifact and count for nothing.">
                    <strong>{stats.staleCount}</strong> stale
                  </span>
                </>
              )}

              <span>·</span>
              <span
                style={{ color: 'var(--ink-faint)' }}
                title={stats.lastVerifiedAt
                  ? absoluteTime(stats.lastVerifiedAt) || ''
                  : 'No fresh verification run has recorded a timestamp'}
              >
                last verified: {stats.lastVerifiedAt ? relativeTime(stats.lastVerifiedAt) : 'n/a'}
              </span>
            </div>
            )}

            {inProspectMode && activeProspect && (
              <div className="mcc-context-meta">
                <span>
                  <strong>{activeProspect.products_observed}</strong> of{' '}
                  {activeProspect.products_configured} products observed
                </span>
                <span>·</span>
                <span><strong>{activeProspect.observations_total}</strong> observations</span>
                {activeProspect.placeholders > 0 && (
                  <>
                    <span>·</span>
                    <span title="Configured products with no real observation behind them yet">
                      <strong>{activeProspect.placeholders}</strong> placeholder
                      {activeProspect.placeholders === 1 ? '' : 's'}
                    </span>
                  </>
                )}
                <span>·</span>
                <span style={{ color: 'var(--ink-faint)' }}>
                  last observed:{' '}
                  {activeProspect.last_observed_at
                    ? relativeTime(activeProspect.last_observed_at)
                    : 'never'}
                </span>
              </div>
            )}

            <div className="mcc-spacer" />

            {!inProspectMode && (
            <>
            <button
              className="mcc-btn"
              onClick={handleVerifyAll}
              disabled={busy === 'verify-all' || loading || rows.length === 0}
              title="Fetch every listing's live PDP and record what it served"
            >
              {busy === 'verify-all'
                ? <><span className="mcc-spinner" /> Verifying…</>
                : 'Verify all'}
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
            </>
            )}
          </div>

          {loadError && (
            <div className="mcc-banner error" role="alert">
              <span>
                <strong>TrueSync could not be reached.</strong> {loadError}
              </span>
              <button className="mcc-btn" onClick={() => load()}>Retry</button>
            </div>
          )}

          {!inProspectMode && (
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
          )}

          <main className="mcc-main">
            {/* ── Prospect mode ──────────────────────────────────── */}
            {inProspectMode && (
              <>
                {prospectLoading && (
                  <div className="mcc-loading">Loading prospect observations…</div>
                )}

                {!prospectLoading && prospectError && (
                  <div className="mcc-banner error" role="alert">
                    <span>
                      <strong>Prospect observations could not be loaded.</strong> {prospectError}
                    </span>
                    <button
                      className="mcc-btn"
                      onClick={() => setProspectSlug((slug) => slug)}
                    >
                      Back to live merchant
                    </button>
                  </div>
                )}

                {!prospectLoading && !prospectError && prospectDrift && (
                  <ProspectView
                    prospect={prospectDrift}
                    products={prospectProducts}
                    totals={prospectTotals}
                  />
                )}
              </>
            )}

            {/* ── Live merchant ──────────────────────────────────── */}
            {!inProspectMode && loading && (
              <div className="mcc-loading">Loading TrueSync catalog…</div>
            )}

            {!inProspectMode && !loading && !loadError && rows.length === 0 && (
              <div className="mcc-panel" style={{ padding: '60px 20px', textAlign: 'center' }}>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>No listings published yet</div>
                <div className="mcc-empty">
                  This merchant has no schema.org publications, so there is nothing to syndicate.
                </div>
              </div>
            )}

            {!inProspectMode && !loading && rows.length > 0 && tab === 'catalog' && (
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

                  {/* Dimension 2 only. A cell with no fresh probe is
                      unknown, not clean — it is in neither number. */}
                  <div className="mcc-stat drifting">
                    <div className="label">Drifting</div>
                    <div className="value">{stats.driftingCells}</div>
                    <div className="sub">
                      {stats.verifiedCells > 0
                        ? `${stats.verifiedCells} verified clean`
                        : 'No fresh verification runs'}
                      {stats.driftFindings > 0 && ` · ${stats.driftFindings} finding${stats.driftFindings === 1 ? '' : 's'}`}
                    </div>
                  </div>

                  {/* Dimension 3 only. */}
                  <div className="mcc-stat">
                    <div className="label">Surface issues</div>
                    <div
                      className="value"
                      style={{ color: stats.disapprovedCells > 0 ? 'var(--fail)' : stats.issueCount > 0 ? 'var(--drift)' : undefined }}
                    >
                      {stats.issueCount}
                    </div>
                    <div className="sub">
                      {stats.pendingCells > 0 && `${stats.pendingCells} pending review`}
                      {stats.pendingCells > 0 && stats.disapprovedCells > 0 && ' · '}
                      {stats.disapprovedCells > 0 && `${stats.disapprovedCells} not approved`}
                      {stats.pendingCells === 0 && stats.disapprovedCells === 0 &&
                        (stats.notFoundCells > 0 ? `${stats.notFoundCells} not in feed` : 'None reported')}
                    </div>
                  </div>

                  <div className="mcc-stat">
                    <div className="label">Last verified</div>
                    {stats.lastVerifiedAt ? (
                      <>
                        <div className="value" style={{ fontSize: '1.15rem', paddingTop: 6 }}>
                          {relativeTime(stats.lastVerifiedAt)}
                        </div>
                        <div className="sub">
                          {absoluteTime(stats.lastVerifiedAt)}
                          {stats.staleCount > 0 && ` · ${stats.staleCount} stale`}
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="value unavailable">n/a</div>
                        <div className="sub">
                          No fresh verification run
                          {stats.staleCount > 0 && ` · ${stats.staleCount} stale`}
                        </div>
                      </>
                    )}
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
                        onVerify={handleVerifyListing}
                        verifyPendingFor={(slug) => busy === `verify:${selectedRow.listingId}:${slug}`}
                      />
                    </DrawerErrorBoundary>
                  </div>
                )}
              </>
            )}

            {!inProspectMode && !loading && rows.length > 0 && tab === 'rules' && (
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
