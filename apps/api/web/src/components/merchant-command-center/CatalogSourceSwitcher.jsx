import React from 'react'
import { relativeTime } from './truesyncDerive.js'

/**
 * The catalog-source switcher from the design mock, restored now that
 * Part A serves prospects.
 *
 * "Live merchant" is the merchant we publish for — the sync matrix, the
 * whole cell model. A prospect is a brand we only observe, so choosing
 * one swaps the entire view rather than filtering this one: there is no
 * publish state to show and nothing to publish.
 *
 * Prospect counts come from the list payload, so the switcher can say
 * what is behind each option before it is chosen.
 */
export default function CatalogSourceSwitcher({ brandName, prospects, activeSlug, onSelect }) {
  return (
    <div className="mcc-source-switch" role="tablist" aria-label="Catalog source">
      <button
        type="button"
        role="tab"
        aria-selected={activeSlug === null}
        className={activeSlug === null ? 'active' : ''}
        onClick={() => onSelect(null)}
      >
        {brandName || 'Live merchant'}
        <span className="tag live">Live</span>
      </button>

      {prospects.map((p) => (
        <button
          key={p.slug}
          type="button"
          role="tab"
          aria-selected={activeSlug === p.slug}
          className={activeSlug === p.slug ? 'active' : ''}
          onClick={() => onSelect(p.slug)}
          title={[
            `${p.products_observed} of ${p.products_configured} products observed`,
            `${p.observations_total} observations`,
            p.last_observed_at ? `last observed ${relativeTime(p.last_observed_at)}` : null,
          ].filter(Boolean).join(' · ')}
        >
          {p.prospect || p.slug}
          <span className="tag prospect">Read-only</span>
          <span className="mcc-source-counts">
            {p.products_observed}/{p.products_configured} products
            {p.last_observed_at && ` · ${relativeTime(p.last_observed_at)}`}
          </span>
        </button>
      ))}
    </div>
  )
}
