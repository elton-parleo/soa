import React, { useState } from 'react'
import { relativeTime, absoluteTime } from './truesyncDerive.js'
import { text, SurfaceComparisonTable } from './ComparisonTable.jsx'
import RobotsPolicyTable from './RobotsPolicyTable.jsx'

/**
 * The prospect drift report — §2b of docs/verification-semantics.md.
 *
 * Deliberately NOT the sync matrix. Nothing publishes here: a prospect
 * is a brand we have no authorization to publish for, so there is no
 * publish state, no acceptance authority, and no master record. What
 * exists is several surfaces describing the same product, and the only
 * question worth asking is how far they disagree with each other.
 *
 * Every number rendered here comes from the model's pure functions
 * (`aggregateProspectProduct`, `summarizeProspect`); this file counts
 * nothing.
 */

function bytesLabel(bytes) {
  if (bytes == null) return null
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/**
 * One observed surface.
 *
 * The outcome badge is the fetcher's verdict, rendered verbatim — this
 * view never re-classifies. The transport line beside it is the
 * evidence, and it is not decoration: a body size, a status, an attempt
 * count and a final URL are what make the verdict checkable. On live
 * data today that evidence is the only way to see that a surface
 * classified `no_structured_data` in fact redirected to a /blocked
 * path — see the report.
 */
function SurfaceRow({ surface }) {
  const [showRobots, setShowRobots] = useState(false)
  const { transport, meta, robotsPolicy } = surface
  const size = bytesLabel(transport.bytes)

  return (
    <li className={`mcc-surface tone-${meta.tone}`}>
      <div className="mcc-surface-head">
        <span className="mcc-surface-name mono">{text(surface.surface)}</span>
        <span className={`mcc-badge ${meta.tone}`}>{meta.label}</span>

        {/* Size sits next to the outcome on purpose. A 15 KB "page" and
            a 1.3 MB page carry very different stories, and for a
            no-structured-data row the number IS the finding. */}
        {size && (
          <span className={`mcc-surface-bytes${surface.readable ? '' : ' emphasis'}`}>{size}</span>
        )}
        {transport.httpStatus != null && (
          <span className="mcc-surface-meta mono">HTTP {transport.httpStatus}</span>
        )}
        {transport.attempts != null && transport.attempts > 1 && (
          <span className="mcc-surface-meta" title="The fetcher retried — a 429/403/5xx ladder">
            {transport.attempts} attempts
          </span>
        )}
        {robotsPolicy && (
          <button
            type="button"
            className="mcc-surface-robots-toggle"
            aria-expanded={showRobots}
            onClick={() => setShowRobots((v) => !v)}
          >
            {robotsPolicy.closedToAllAgents
              ? `Agent access: closed to all ${robotsPolicy.agentCount}`
              : robotsPolicy.blockedCount > 0
                ? `Agent access: ${robotsPolicy.blockedCount} blocked`
                : 'Agent access'}
          </button>
        )}
      </div>

      <div className="mcc-surface-detail">{meta.detail}</div>

      {surface.error && <div className="mcc-surface-detail error">{text(surface.error)}</div>}

      {/* Where the fetch actually ended. A redirect away from the
          requested product page is worth stating whatever outcome the
          fetcher assigned to it. */}
      {surface.redirected && (
        <div className="mcc-surface-detail redirect">
          Redirected to <span className="mono">{text(transport.finalUrl)}</span>
          {transport.redirectChain.length > 0 && (
            <> — from <span className="mono">{text(transport.redirectChain[0])}</span></>
          )}
        </div>
      )}

      {surface.readable && surface.jsonLdBlocks > 0 && (
        <div className="mcc-surface-detail">
          {surface.jsonLdBlocks} JSON-LD block{surface.jsonLdBlocks === 1 ? '' : 's'} extracted
          {surface.summary.title && <> · <span className="mono">{text(surface.summary.title)}</span></>}
          {surface.summary.price && <> · {text(surface.summary.price)} {text(surface.summary.currency, '')}</>}
          {surface.summary.gtin && <> · GTIN <span className="mono">{text(surface.summary.gtin)}</span></>}
        </div>
      )}

      <div className="mcc-surface-url">
        <a href={surface.url} target="_blank" rel="noreferrer" className="mono">{text(surface.url)}</a>
      </div>

      {showRobots && <RobotsPolicyTable policy={robotsPolicy} />}
    </li>
  )
}

function ProspectProduct({ product }) {
  return (
    <div className="mcc-panel mcc-prospect-product">
      <div className="mcc-panel-head">
        <h3>{text(product.label)}</h3>
        <span className={`mcc-badge ${product.outcomeMeta.tone}`}>{product.outcomeMeta.label}</span>
        {product.gtin
          ? <span className="mcc-prospect-gtin mono">GTIN {text(product.gtin)}</span>
          : <span className="mcc-prospect-gtin missing">no GTIN on any surface</span>}
        <div className="mcc-spacer" />
        {product.observedAt && (
          <span className="hint" title={absoluteTime(product.observedAt) || ''}>
            observed {relativeTime(product.observedAt)}
          </span>
        )}
      </div>

      {!product.observed && (
        <div className="mcc-section">
          <p className="mcc-empty">
            This product is configured but has not been observed yet — nothing has been fetched,
            so nothing is known about it.
          </p>
        </div>
      )}

      {product.observed && (
        <>
          <div className="mcc-section">
            <h4>Surfaces observed ({product.surfacesRead} of {product.surfacesTotal} readable)</h4>
            <ul className="mcc-surfaces">
              {product.surfaces.map((surface, i) => (
                <SurfaceRow key={surface.surface || i} surface={surface} />
              ))}
            </ul>
          </div>

          <div className="mcc-section">
            <h4>Cross-surface comparison</h4>

            {/* insufficient_surfaces carries the weight null carries in
                dimension 2. One surface cannot disagree with itself, so
                an empty findings list under this outcome means nothing
                was measured — never that the surfaces agreed. */}
            {product.insufficient ? (
              <div className="mcc-insufficient">
                <strong>
                  Only {product.surfacesRead} of {product.surfacesTotal} surfaces readable —
                  cross-surface comparison not possible.
                </strong>
                <div className="detail">
                  {product.surfacesRead === 0
                    ? 'No surface returned machine-readable product data, so there is nothing to compare.'
                    : 'A single surface cannot disagree with itself. This is not agreement between surfaces; it is the absence of a measurement.'}
                </div>
              </div>
            ) : product.findingCount === 0 ? (
              <div className="mcc-empty">
                All readable surfaces agree on every compared field.
              </div>
            ) : (
              <SurfaceComparisonTable findings={product.findings} />
            )}
          </div>
        </>
      )}
    </div>
  )
}

export default function ProspectView({ prospect, products, totals }) {
  return (
    <>
      {/* Stated once, at the top, and unmissable: this mode observes
          other people's public pages and writes to none of them. */}
      <div className="mcc-banner prospect" role="status">
        <span>
          <strong>Prospect mode</strong> — read-only observation of public surfaces;
          nothing is published.
        </span>
      </div>

      <div className="mcc-stats" style={{ marginTop: 14 }}>
        <div className="mcc-stat">
          <div className="label">Products observed</div>
          <div className="value">{totals.observed}<small> / {totals.products}</small></div>
          <div className="sub">
            {totals.lastObservedAt
              ? `last observed ${relativeTime(totals.lastObservedAt)}`
              : 'never observed'}
          </div>
        </div>

        <div className="mcc-stat">
          <div className="label">Surfaces readable</div>
          <div
            className="value"
            style={{ color: totals.surfacesReadable === 0 ? 'var(--fail)' : undefined }}
          >
            {totals.surfacesReadable}<small> / {totals.surfaces}</small>
          </div>
          <div className="sub">
            {Object.entries(totals.outcomeCounts)
              .map(([outcome, n]) => `${n} ${outcome}`)
              .join(' · ') || 'none observed'}
          </div>
        </div>

        <div className="mcc-stat drifting">
          <div className="label">Cross-surface findings</div>
          <div className="value">{totals.findingsTotal}</div>
          <div className="sub">
            {totals.notComparable > 0
              ? `${totals.notComparable} product${totals.notComparable === 1 ? '' : 's'} not comparable`
              : `${totals.comparable} comparable`}
          </div>
        </div>

        <div className="mcc-stat">
          <div className="label">Closed to agents</div>
          <div
            className="value"
            style={{ color: totals.agentBlockedDomains.length > 0 ? 'var(--fail)' : undefined }}
          >
            {totals.agentBlockedDomains.length}
          </div>
          <div className="sub">
            {totals.agentBlockedDomains.length > 0
              ? totals.agentBlockedDomains.join(', ')
              : 'no domain blocks every agent'}
          </div>
        </div>
      </div>

      {products.length === 0 && (
        <div className="mcc-panel" style={{ padding: '60px 20px', textAlign: 'center' }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>No products configured</div>
          <div className="mcc-empty">
            This prospect has no products to observe yet.
          </div>
        </div>
      )}

      <div className="mcc-prospect-products">
        {products.map((product) => (
          <ProspectProduct key={product.key} product={product} />
        ))}
      </div>

      <p className="mcc-prospect-foot">
        Surfaces are other people's public pages, fetched by a declared crawler that honours
        robots.txt. <strong>Blocked</strong>, <strong>no structured data</strong> and{' '}
        <strong>disallowed by robots</strong> are three different facts — about their edge,
        their markup, and their policy — and are never reported as one.
      </p>
    </>
  )
}
