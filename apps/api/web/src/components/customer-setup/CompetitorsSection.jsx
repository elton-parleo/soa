import React from 'react'

/**
 * 2I-6: "Competitors to track", entered once per merchant as name + domain:
 * in the setup wizard's first step, and on an existing customer in the
 * Command Center (CompetitorsPanel). Saved through
 * PUT /api/customers/{org}/merchants/{slug}/competitors, which writes
 * supply's comparison_domains and then soa's entities.
 *
 * The checks here are supply's own, so a row is refused before it is sent:
 * a bare lowercase hostname (no scheme, path, port or leading www.), not
 * listed twice, and not the merchant's own site or a retailer on its list
 * (supply answers those with a 409).
 */

// supply's truesync/tenancy.py _HOSTNAME_RE
export const HOSTNAME_RE = /^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]$/

export const emptyCompetitor = () => ({ name: '', domain: '' })

/** The rows the operator filled in (a name or a domain), trimmed. */
export function filledCompetitors(rows) {
  return rows.map((r) => ({ name: r.name.trim(), domain: r.domain.trim() })).filter((r) => r.name || r.domain)
}

/** { rowIndex: problem } for the filled rows; {} when the list can be saved. */
export function competitorProblems(rows, { own = [], retailers = [] } = {}) {
  const out = {}
  const domains = rows.map((r) => r.domain.trim())
  rows.forEach((r, i) => {
    const name = r.name.trim()
    const domain = r.domain.trim()
    if (!name && !domain) return
    if (!domain) out[i] = 'Give the competitor\'s site, e.g. pampers.com.'
    else if (domain.startsWith('www.')) out[i] = 'Leave out the leading www.'
    else if (!HOSTNAME_RE.test(domain)) out[i] = 'A bare site name: lowercase, no https://, no path, e.g. pampers.com.'
    else if (own.includes(domain)) out[i] = 'This is the customer\'s own site.'
    else if (retailers.includes(domain)) out[i] = 'This is on the customer\'s retailer list.'
    else if (domains.indexOf(domain) !== i) out[i] = 'Listed twice.'
    else if (!name) out[i] = 'Name the competitor as agents would, e.g. Pampers.'
  })
  return out
}

export default function CompetitorsSection({ rows, onChange, own = [], retailers = [], disabled = false, saved = null }) {
  const problems = competitorProblems(rows, { own, retailers })
  const set = (i, key, value) => onChange(rows.map((r, j) => (j === i ? { ...r, [key]: value } : r)))
  return (
    <div className="field" data-testid="competitors">
      <div className="label">Competitors to track</div>
      {rows.map((row, i) => (
        <div key={i}>
          <div className="ent comp">
            <input type="text" aria-label={`Competitor ${i + 1} name`} placeholder="name, e.g. Pampers"
              value={row.name} disabled={disabled} onChange={(e) => set(i, 'name', e.target.value)} />
            <input type="text" aria-label={`Competitor ${i + 1} domain`} placeholder="site, e.g. pampers.com"
              value={row.domain} disabled={disabled} onChange={(e) => set(i, 'domain', e.target.value)} />
            <button type="button" className="del" aria-label={`Remove competitor ${i + 1}`} disabled={disabled}
              onClick={() => onChange(rows.length > 1 ? rows.filter((_, j) => j !== i) : [emptyCompetitor()])}>
              ×
            </button>
          </div>
          {problems[i] && <div className="row-problem" role="alert">{problems[i]}</div>}
        </div>
      ))}
      <button type="button" className="addrow" disabled={disabled} onClick={() => onChange([...rows, emptyCompetitor()])}>
        + Add a competitor
      </button>
      <div className="help">
        Tracked competitors get full rows on the console, and their pages are read when the feed carries their URLs.
        Other brands agents name appear as “named but not tracked”.
      </div>
      {saved && (
        <div className="saved-list" data-testid="competitors-saved">
          <div className="k">On TrueSync now</div>
          {saved.length === 0 ? <div className="v">No competitor yet.</div> : (
            <ul>
              {saved.map((c) => (
                <li key={c.domain}>
                  <b>{c.name || <span className="muted">no entity yet</span>}</b> · {c.domain}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
