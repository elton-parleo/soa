import React, { useEffect, useState } from 'react'
import { getCompetitors, saveCompetitors } from '../../customersApi.js'
import CompetitorsSection, { competitorProblems, emptyCompetitor, filledCompetitors } from './CompetitorsSection.jsx'
import './customerSetup.css'

/**
 * 2I-6: an existing customer's competitors, from the Command Center. The
 * list is read back from TrueSync (supply's comparison_domains) joined to
 * soa's entity names, so what is shown is what every cycle will read; a
 * domain with no entity says "no entity yet". Save replaces the list:
 * supply first, then soa's entities. Removing a row removes the domain
 * from TrueSync; the entity stays (entities are global), and a cycle that
 * already tracks it keeps it in its set.
 */
export default function CompetitorsPanel({ open, onClose, onSaved, orgId, merchant }) {
  const [view, setView] = useState(null)
  const [rows, setRows] = useState([emptyCompetitor()])
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(null)

  useEffect(() => {
    if (!open || !merchant) return
    setView(null); setError(null); setBusy('Reading the list from TrueSync…')
    getCompetitors(orgId, merchant.slug)
      .then((v) => {
        setView(v)
        const listed = v.competitors.map((c) => ({ name: c.name || '', domain: c.domain }))
        setRows(listed.length ? listed : [emptyCompetitor()])
      })
      .catch((err) => setError(err.message))
      .finally(() => setBusy(null))
  }, [open, orgId, merchant?.slug]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!open || !merchant) return null
  const own = view?.own_domains || []
  const retailers = view?.retailer_domains || []
  const problems = competitorProblems(rows, { own, retailers })
  const canSave = !!view && !busy && Object.keys(problems).length === 0

  async function save() {
    setError(null); setBusy('Saving to TrueSync, then the entities…')
    try {
      const v = await saveCompetitors(orgId, merchant.slug, filledCompetitors(rows))
      setView(v)
      onSaved?.(v)
    } catch (err) {
      const code = err.details?.code
      setError(code === 'entities_failed'
        ? `${err.message}. TrueSync has the list; the names are not in soa yet.`
        : err.message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="csw-backdrop" role="presentation">
      <div className="csw" role="dialog" aria-modal="true" aria-label={`Competitors — ${merchant.name}`}>
        <div className="modal">
          <div className="modal-head">
            <h1>Competitors — {merchant.name}</h1>
            <button className="x" aria-label="Close" onClick={onClose}>×</button>
          </div>
          <div className="modal-body">
            <CompetitorsSection rows={rows} onChange={setRows} own={own} retailers={retailers}
              disabled={!view || !!busy} saved={view ? view.competitors : null} />
            {busy && <div className="busy" role="status">{busy}</div>}
            {error && <div className="error" role="alert">{error}</div>}
          </div>
          <div className="modal-foot">
            <button type="button" className="btn btn-ghost" onClick={onClose}>Close</button>
            <div className="right">
              <button type="button" className="btn btn-primary" disabled={!canSave} onClick={save}>Save competitors</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
