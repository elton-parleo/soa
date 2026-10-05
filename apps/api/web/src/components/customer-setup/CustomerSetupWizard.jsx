import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createCustomer } from '../../customersApi.js'
import { truesyncApi } from '../../truesyncApi.js'
import {
  MECHANICS, emptyRow, toIncentives, fromIncentive, describeOffers,
} from './offerRows.js'
import './customerSetup.css'

/**
 * The customer setup wizard (Step 1C) — design-refs/customer-setup-mock.html,
 * the two operator screens as one modal. Operators only; the page that
 * opens it checks, and the API refuses anyone else regardless.
 *
 * What each step WRITES, and when:
 *
 *   1  Account & customer   on Continue: POST /api/customers — the org (and,
 *                           if new, its TrueSync tenant and sealed token),
 *                           the merchant with kind + hosting, its retailer
 *                           list. Must happen here: validating a feed needs
 *                           the merchant and its retailer list to exist.
 *   2  Product feed         on file drop: feed/validate (writes no record,
 *                           stages the preview). Skipped for hosting=parleo:
 *                           a Parleo-hosted merchant's record is its brand
 *                           config, and supply refuses its feed (409).
 *   3  Customer-owned offers  nothing until Create.
 *   4  Review               Create: feed/commit in the mode the gate chose
 *                           (require_clean, or all_valid_rows after "continue
 *                           with the valid rows"), then PUT incentives/owned.
 *
 * Re-entry from the Command Center uses the same screens on an existing
 * customer: mode "feed" (upload a new version, then review) and mode
 * "offers" (edit, then review). Nothing about the account changes there.
 */

const KIND_HELP = {
  seller: "Prices will be checked against this customer's own pages. Its loyalty and offer programs count as its own.",
  brand: "This customer doesn't set shelf prices. AI-quoted prices will be checked against the retailer page they're attributed to; only the brand's own coupons, rebates and rewards count as its offers.",
}
const HOSTING_HELP = {
  external: 'We can observe and verify their pages but not publish to them until they integrate. Syndication columns will show "not connected".',
  parleo: 'We serve their pages and hold their accounts, so publishing and verification run end to end.',
}
const RETAILER_LABEL = {
  seller: 'Where the products are sold',
  brand: 'Retailers that carry these products',
}
const RETAILER_HELP = {
  seller: "For a store, this is usually just its own site (plus marketplaces if any). This list is the only place we'll look for listings — nothing is guessed.",
  brand: "Each product's page URL on these sites goes in the feed. Any retailer an AI assistant names that isn't on this list is reported as a fabricated claim.",
}

const STEP_TITLES = {
  account: 'Account & customer',
  feed: 'Product feed',
  offers: 'Customer-owned offers',
  review: 'Review',
}

export function stepsFor(mode, hosting) {
  if (mode === 'feed') return ['feed', 'review']
  if (mode === 'offers') return ['offers', 'review']
  return hosting === 'parleo'
    ? ['account', 'offers', 'review']
    : ['account', 'feed', 'offers', 'review']
}

function bareDomain(text) {
  return (text || '').trim().toLowerCase()
    .replace(/^https?:\/\//, '').replace(/^www\./, '').replace(/\/.*$/, '')
}

function money(price, currency) {
  if (price == null) return '—'
  return currency === 'USD' ? `$${price}` : `${price} ${currency || ''}`.trim()
}

function urlTail(url) {
  try {
    const u = new URL(url)
    const tail = `${u.pathname}${u.search}`
    return tail.length > 44 ? `${tail.slice(0, 43)}…` : tail
  } catch (_) {
    return url
  }
}

const STATUS_CLASS = { ready: 'ok', warning: 'warn', error: 'bad' }

function plural(n, word, many = `${word}s`) {
  return `${n} ${n === 1 ? word : many}`
}

export default function CustomerSetupWizard({
  open, onClose, onDone, customers = [], mode = 'new', existing = null,
}) {
  const [stepIndex, setStepIndex] = useState(0)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(null)

  // Step 1
  const [accountChoice, setAccountChoice] = useState('new')
  const [accountName, setAccountName] = useState('')
  const [merchantName, setMerchantName] = useState('')
  const [domain, setDomain] = useState('')
  const [kind, setKind] = useState('seller')
  const [hosting, setHosting] = useState('external')
  const [retailers, setRetailers] = useState([''])
  // What step 1 created: { orgId, orgName, merchant }. Once set, step 1 is
  // a record of what exists, not a form.
  const [created, setCreated] = useState(null)

  // Step 2
  const [files, setFiles] = useState([])
  const [preview, setPreview] = useState(null)
  const [filter, setFilter] = useState('all')
  const [continueWithValid, setContinueWithValid] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const fileInput = useRef(null)

  // Step 3
  const [offers, setOffers] = useState([emptyRow('loyalty_program')])
  const [offerErrors, setOfferErrors] = useState({})

  // Reset on every open, and seed re-entry from the existing customer.
  useEffect(() => {
    if (!open) return
    setStepIndex(0); setError(null); setBusy(null)
    setAccountChoice('new'); setAccountName(''); setMerchantName(''); setDomain('')
    setKind('seller'); setHosting('external'); setRetailers([''])
    setFiles([]); setPreview(null); setFilter('all'); setContinueWithValid(false)
    setOffers([emptyRow('loyalty_program')]); setOfferErrors({})
    if (existing) {
      setCreated({ orgId: existing.orgId, orgName: existing.orgName, merchant: existing.merchant })
      setKind(existing.merchant.kind)
      setHosting(existing.merchant.hosting)
      if (mode === 'offers') {
        truesyncApi.getOwnedIncentives(existing.merchant.slug, { customer: existing.orgId })
          .then((data) => {
            const rows = (data?.incentives || []).map(fromIncentive)
            setOffers(rows.length ? rows : [emptyRow('loyalty_program')])
          })
          .catch((err) => setError(err.message))
      }
    } else {
      setCreated(null)
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const steps = stepsFor(mode, created?.merchant?.hosting || hosting)
  const step = steps[Math.min(stepIndex, steps.length - 1)]
  const merchant = created?.merchant || null
  const orgId = created?.orgId ?? null

  const existingAccounts = useMemo(
    () => customers.map((c) => ({ id: c.org_id, name: c.name })),
    [customers],
  )

  const rows = preview?.rows || []
  const summary = preview?.summary || null
  const errorRows = rows.filter((r) => r.status === 'error').length
  const warningRows = rows.filter((r) => r.status === 'warning').length
  const validRows = rows.length - errorRows
  const fileErrors = preview?.file_errors || []
  const blocked = errorRows > 0 || fileErrors.length > 0
  const commitMode = blocked ? 'all_valid_rows' : 'require_clean'
  const feedReady = !!preview && validRows > 0 && (!blocked || continueWithValid)

  // The URL column the table shows: the merchant's own site if the feed
  // names it, else the first site any row names.
  const urlDomain = useMemo(() => {
    const own = bareDomain(merchant?.domain)
    const seen = rows.flatMap((r) => (r.retailers || []).map((x) => x.domain))
    return seen.includes(own) ? own : (seen[0] || own || null)
  }, [rows, merchant])

  if (!open) return null

  // ─── Step 1 ─────────────────────────────────────────────────────
  function chooseKind(next) {
    setKind(next)
    // The mock's own nudge: a brand's list is retailers, not its own site.
    if (next === 'brand' && retailers.length === 1 && bareDomain(retailers[0]) === bareDomain(domain)) {
      setRetailers([''])
    }
    if (next === 'seller' && retailers.every((r) => !r.trim()) && domain.trim()) {
      setRetailers([bareDomain(domain)])
    }
  }

  function step1Problem() {
    if (accountChoice === 'new' && !accountName.trim()) return 'Name the account.'
    if (!merchantName.trim()) return 'Name the customer.'
    if (!domain.trim()) return "Give the customer's domain."
    return null
  }

  async function runStep1() {
    const problem = step1Problem()
    if (problem) { setError(problem); return null }
    setBusy('Creating the customer…')
    setError(null)
    try {
      const result = await createCustomer({
        account: accountChoice === 'new'
          ? { name: accountName.trim() }
          : { org_id: Number(accountChoice) },
        merchant: { name: merchantName.trim(), domain: bareDomain(domain), kind, hosting },
        retailers: retailers.map(bareDomain).filter(Boolean),
      })
      const made = { orgId: result.org_id, orgName: result.org_name, merchant: result.merchant }
      setCreated(made)
      return made
    } catch (err) {
      if (typeof err.orgId === 'number') {
        // The account exists now even though the customer does not: retry
        // under it, never by creating a second account.
        setAccountChoice(String(err.orgId))
        setError(`The account was created, but the customer was not: ${err.message} `
          + 'Fix it and continue — the account is now selected.')
      } else {
        setError(err.message)
      }
      return null
    } finally {
      setBusy(null)
    }
  }

  // ─── Step 2 ─────────────────────────────────────────────────────
  async function validate(chosen) {
    const list = Array.from(chosen || [])
    if (list.length === 0 || !merchant) return
    setFiles(list)
    setPreview(null)
    setContinueWithValid(false)
    setFilter('all')
    setError(null)
    setBusy('Checking the feed…')
    try {
      const result = await truesyncApi.validateFeed(merchant.slug, list, { customer: orgId })
      setPreview(result)
      // An incentive sheet in the upload fills step 3 (1B accepts one).
      const sheet = (result.incentives || []).filter((i) => i.values).map((i) => fromIncentive(i.values))
      if (sheet.length) setOffers(sheet)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(null)
    }
  }

  async function downloadTemplate(ext) {
    try {
      const blob = await truesyncApi.downloadTemplate(ext)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `sku-feed-template.${ext}`
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (err) {
      setError(err.message)
    }
  }

  // ─── Step 3 ─────────────────────────────────────────────────────
  function setOffer(index, patch) {
    setOffers((list) => list.map((row, i) => (i === index ? { ...row, ...patch } : row)))
    setOfferErrors((e) => { const next = { ...e }; delete next[index]; return next })
  }

  function checkOffers() {
    const { errors } = toIncentives(offers)
    setOfferErrors(errors)
    return Object.keys(errors).length === 0
  }

  // ─── Navigation ─────────────────────────────────────────────────
  async function next() {
    if (step === 'account' && !created) {
      if (!(await runStep1())) return
    }
    if (step === 'feed' && !feedReady) return
    if (step === 'offers' && !checkOffers()) return
    if (step === 'review') { await finish(); return }
    setError(null)
    setStepIndex((i) => Math.min(i + 1, steps.length - 1))
  }

  function back() {
    setError(null)
    setStepIndex((i) => Math.max(i - 1, 0))
  }

  async function finish() {
    if (!merchant) return
    setError(null)
    try {
      if (steps.includes('feed') && preview) {
        setBusy('Saving the feed…')
        await truesyncApi.commitFeed(merchant.slug, preview.upload_id, commitMode, { customer: orgId })
      }
      if (steps.includes('offers')) {
        setBusy('Saving the offers…')
        const { incentives } = toIncentives(offers)
        await truesyncApi.putOwnedIncentives(merchant.slug, incentives, { customer: orgId })
      }
      onDone({ orgId, merchantSlug: merchant.slug })
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(null)
    }
  }

  // "Save draft": what step 1 made is kept (it already exists); nothing on
  // the later steps is committed. On step 1 itself it creates first.
  async function saveDraft() {
    const made = created || (step === 'account' ? await runStep1() : null)
    if (!made) return
    onDone({ orgId: made.orgId, merchantSlug: made.merchant.slug, draft: true })
  }

  const isLast = step === 'review'
  const continueDisabled = !!busy
    || (step === 'feed' && !feedReady)
  const title = mode === 'feed'
    ? `New product feed — ${existing?.merchant?.name || ''}`
    : mode === 'offers'
      ? `Customer-owned offers — ${existing?.merchant?.name || ''}`
      : 'New customer'
  const primaryLabel = !isLast ? 'Continue'
    : mode === 'new' ? 'Create customer' : 'Save'

  const visibleRows = rows.filter((r) => filter === 'all'
    || (filter === 'bad' && r.status === 'error')
    || (filter === 'warn' && r.status === 'warning'))
  const step1Locked = !!created

  return (
    <div className="csw-backdrop" role="presentation">
      <div className="csw" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal">
          <div className="modal-head">
            <h1>{title}</h1>
            <button className="x" aria-label="Close" onClick={onClose}>×</button>
          </div>

          <div className="steps">
            {steps.map((s, i) => (
              <div
                key={s}
                className={`step${i === stepIndex ? ' on' : ''}${i < stepIndex ? ' done' : ''}`}
                aria-current={i === stepIndex ? 'step' : undefined}
              >
                <b>{i + 1}</b>{STEP_TITLES[s]}
              </div>
            ))}
          </div>

          <div className="modal-body">
            {/* ── 1: Account & customer ─────────────────────────── */}
            {step === 'account' && (
              <div>
                <div className="field">
                  <div className="label">Account</div>
                  <div className="row2">
                    <div>
                      <input
                        type="text"
                        aria-label="Account name"
                        placeholder="Account (tenant) name"
                        value={accountChoice === 'new'
                          ? accountName
                          : (existingAccounts.find((a) => String(a.id) === accountChoice)?.name || '')}
                        disabled={step1Locked || accountChoice !== 'new'}
                        onChange={(e) => setAccountName(e.target.value)}
                      />
                      <div className="help">One account can hold several customers (brands or stores).</div>
                    </div>
                    <div>
                      <select
                        aria-label="Account choice"
                        value={accountChoice}
                        disabled={step1Locked}
                        onChange={(e) => setAccountChoice(e.target.value)}
                      >
                        <option value="new">Create new account</option>
                        {existingAccounts.map((a) => (
                          <option key={a.id} value={String(a.id)}>Add to existing: {a.name}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                </div>

                <div className="field">
                  <div className="label">Customer</div>
                  <div className="row2">
                    <input type="text" aria-label="Customer name" placeholder="Customer name"
                      value={merchantName} disabled={step1Locked}
                      onChange={(e) => setMerchantName(e.target.value)} />
                    <input type="text" aria-label="Domain" placeholder="Domain"
                      value={domain} disabled={step1Locked}
                      onChange={(e) => setDomain(e.target.value)}
                      onBlur={() => {
                        if (kind === 'seller' && retailers.every((r) => !r.trim()) && domain.trim()) {
                          setRetailers([bareDomain(domain)])
                        }
                      }} />
                  </div>
                </div>

                <div className="field">
                  <div className="label">Does this customer sell the products?</div>
                  <div className="seg" role="group" aria-label="Kind">
                    <button type="button" aria-pressed={kind === 'seller'} disabled={step1Locked}
                      onClick={() => chooseKind('seller')}>
                      Yes — sets its own prices and runs its own programs
                    </button>
                    <button type="button" aria-pressed={kind === 'brand'} disabled={step1Locked}
                      onClick={() => chooseKind('brand')}>
                      No — a brand sold through retailers
                    </button>
                  </div>
                  <div className="help">{KIND_HELP[kind]}</div>
                </div>

                <div className="field">
                  <div className="label">Who hosts the store pages?</div>
                  <div className="seg" role="group" aria-label="Hosting">
                    <button type="button" aria-pressed={hosting === 'parleo'} disabled={step1Locked}
                      onClick={() => setHosting('parleo')}>
                      Parleo hosts them
                    </button>
                    <button type="button" aria-pressed={hosting === 'external'} disabled={step1Locked}
                      onClick={() => setHosting('external')}>
                      The customer does
                    </button>
                  </div>
                  <div className="help">{HOSTING_HELP[hosting]}</div>
                </div>

                <div className="field">
                  <div className="label">{RETAILER_LABEL[kind]}</div>
                  {retailers.map((value, i) => (
                    <div className="ent" key={i}>
                      <input type="text" aria-label={`Retailer ${i + 1}`}
                        placeholder="retailer domain, e.g. walmart.com"
                        value={value} disabled={step1Locked}
                        onChange={(e) => setRetailers((list) => list.map((v, j) => (j === i ? e.target.value : v)))} />
                      <button type="button" className="del" aria-label="Remove" disabled={step1Locked}
                        onClick={() => setRetailers((list) => (list.length > 1 ? list.filter((_, j) => j !== i) : ['']))}>
                        ×
                      </button>
                    </div>
                  ))}
                  <button type="button" className="addrow" disabled={step1Locked}
                    onClick={() => setRetailers((list) => [...list, ''])}>
                    + Add a retailer site
                  </button>
                  <div className="help">{RETAILER_HELP[kind]}</div>
                  {step1Locked && (
                    <div className="note">
                      <b>Created.</b> {created.orgName} · {merchant.name} now exists, with its
                      retailer list. Continue to load its products.
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* ── 2: Product feed ─────────────────────────────── */}
            {step === 'feed' && (
              <div className="field">
                <div className="label">Product feed</div>
                {!preview && (
                  <div
                    className={`drop${dragOver ? ' over' : ''}`}
                    onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
                    onDragLeave={() => setDragOver(false)}
                    onDrop={(e) => { e.preventDefault(); setDragOver(false); validate(e.dataTransfer.files) }}
                    data-testid="feed-drop"
                  >
                    <div className="t">Drop a CSV or XLSX here, or choose a file</div>
                    <div className="d">
                      One row per product: barcode (GTIN), product name, variant / pack, size or
                      count, price (optional), and the product page URL on each retailer site.
                      <br />
                      Download the template:{' '}
                      <button type="button" className="linkbtn" onClick={() => downloadTemplate('csv')}>CSV</button>
                      {' · '}
                      <button type="button" className="linkbtn" onClick={() => downloadTemplate('xlsx')}>XLSX</button>
                    </div>
                    <input
                      ref={fileInput}
                      type="file"
                      accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                      multiple
                      hidden
                      aria-label="Feed file"
                      onChange={(e) => validate(e.target.files)}
                    />
                    <button type="button" className="btn btn-ghost" disabled={!!busy}
                      onClick={() => fileInput.current?.click()}>
                      Choose file…
                    </button>
                  </div>
                )}

                {preview && (
                  <div data-testid="feed-preview">
                    <div className="summary">
                      <span className="pill">
                        {files.map((f) => f.name).join(', ')} · {plural(summary.rows, 'row')}
                      </span>
                      <span className="pill ok">{summary.ready} ready</span>
                      <span className="pill warn">{plural(summary.warning, 'warning')}</span>
                      <span className="pill bad">{plural(summary.error, 'error')}</span>
                    </div>

                    {fileErrors.length > 0 && (
                      <ul className="file-errors">
                        {fileErrors.map((m, i) => <li key={i}>{m}</li>)}
                      </ul>
                    )}

                    <div className="filters" role="group" aria-label="Filter rows">
                      {[['all', 'All'], ['bad', 'Errors'], ['warn', 'Warnings']].map(([f, label]) => (
                        <button key={f} type="button" className="chip" aria-pressed={filter === f}
                          onClick={() => setFilter(f)}>
                          {label}
                        </button>
                      ))}
                    </div>

                    <div className="tbl">
                      <table>
                        <thead>
                          <tr>
                            <th>#</th><th>Status</th><th>GTIN</th><th>Product</th>
                            <th>Variant / pack</th><th>Size</th><th>Price</th>
                            <th className="url">{urlDomain ? `${urlDomain} URL` : 'URL'}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {visibleRows.map((r) => {
                            const url = (r.retailers || []).find((x) => x.domain === urlDomain)?.url
                            const cls = STATUS_CLASS[r.status]
                            return (
                              <tr key={`${r.sheet}:${r.row_number}`} className={cls}>
                                <td>{r.row_number}</td>
                                <td><span className={`st ${cls}`}>{r.status === 'ready' ? 'ready' : r.status}</span></td>
                                <td className="mono">{r.gtin_as_given || '—'}</td>
                                <td>{r.product_name || '—'}</td>
                                <td>
                                  {[r.variant_label, r.pack_count ? `${r.pack_count}-pack` : null]
                                    .filter(Boolean).join(' · ') || '—'}
                                </td>
                                <td>{r.size_value ? `${r.size_value} ${r.size_unit || ''}`.trim() : '—'}</td>
                                <td>{money(r.price, r.currency)}</td>
                                <td className="mono url">
                                  {url ? urlTail(url) : '—'}
                                  {(r.messages || []).map((m, i) => (
                                    <span key={i} className="msg">{m.message}</span>
                                  ))}
                                </td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>

                    {blocked && validRows > 0 && !continueWithValid && (
                      <div className="gate off" role="status">
                        {errorRows > 0
                          ? `${plural(errorRows, 'row has', 'rows have')} an error. `
                          : 'The file has problems listed above. '}
                        Fix the file and{' '}
                        <button type="button" className="linkbtn" onClick={() => { setPreview(null); setFiles([]) }}>
                          re-upload
                        </button>
                        , or{' '}
                        <button type="button" className="linkbtn" onClick={() => setContinueWithValid(true)}>
                          continue with the {plural(validRows, 'valid row')}
                        </button>
                        {errorRows > 0 && ` (the error ${errorRows === 1 ? 'row is' : 'rows are'} left out)`}.
                      </div>
                    )}
                    {blocked && validRows === 0 && (
                      <div className="gate bad" role="status">
                        No row can be saved. Fix the file and{' '}
                        <button type="button" className="linkbtn" onClick={() => { setPreview(null); setFiles([]) }}>
                          re-upload
                        </button>.
                      </div>
                    )}
                    {feedReady && (
                      <div className="gate ok" role="status">
                        {plural(validRows, 'product')} will be saved.
                        {errorRows > 0 && ` ${plural(errorRows, 'row')} left out.`}
                        {warningRows > 0 && ` ${plural(warningRows, 'warning')} kept — the access check will report those pages.`}
                        {' '}
                        <button type="button" className="linkbtn" onClick={() => { setPreview(null); setFiles([]) }}>
                          Upload a different file
                        </button>
                      </div>
                    )}

                    <div className="help">
                      Re-uploading later replaces the feed; earlier versions are kept so changes can be
                      traced. Prices are optional — for a store we read the live price from its page; for
                      a brand, retailers set the price.
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ── 3: Customer-owned offers ─────────────────────── */}
            {step === 'offers' && (
              <div className="field">
                <div className="label">Programs and offers this customer owns</div>
                <div className="help" style={{ margin: '0 0 10px' }}>
                  Only what the customer runs itself: a loyalty program, member pricing, its own coupons
                  or rebates. Retailer programs it doesn&apos;t control (e.g. Subscribe &amp; Save) are
                  observed in reports but never expected.
                </div>
                {offers.map((row, i) => {
                  const hint = MECHANICS.find((m) => m.value === row.mechanic)?.valueHint
                  return (
                    <div className="offer" key={i} data-testid="offer-row">
                      <select aria-label={`Offer ${i + 1} kind`} value={row.mechanic}
                        onChange={(e) => setOffer(i, { mechanic: e.target.value })}>
                        {MECHANICS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                      </select>
                      <input type="text" aria-label={`Offer ${i + 1} name`}
                        placeholder={row.mechanic === 'coupon_code' ? 'Code' : 'Name'}
                        value={row.name} onChange={(e) => setOffer(i, { name: e.target.value })} />
                      <input type="text" aria-label={`Offer ${i + 1} value`}
                        placeholder={hint || 'Value / rule'}
                        value={row.value} onChange={(e) => setOffer(i, { value: e.target.value })} />
                      <input type="text" aria-label={`Offer ${i + 1} applies to`}
                        placeholder="Applies to"
                        value={row.appliesTo} onChange={(e) => setOffer(i, { appliesTo: e.target.value })} />
                      <button type="button" className="del" aria-label="Remove"
                        onClick={() => {
                          setOffers((list) => (list.length > 1 ? list.filter((_, j) => j !== i) : [emptyRow()]))
                          setOfferErrors({})
                        }}>
                        ×
                      </button>
                      {offerErrors[i] && <div className="offer-error" role="alert">{offerErrors[i]}</div>}
                    </div>
                  )
                })}
                <button type="button" className="addrow" onClick={() => setOffers((list) => [...list, emptyRow()])}>
                  + Add a program or offer
                </button>
                <div className="note">
                  <b>Why this matters.</b> Reports check whether these survive into AI answers
                  (“value survival”). An offer not listed here can&apos;t be scored as missing — it will be
                  reported as something the assistant volunteered.
                </div>
              </div>
            )}

            {/* ── 4: Review ───────────────────────────────────── */}
            {step === 'review' && (
              <div className="field">
                <div className="rev">
                  <div className="k">Account · customer</div>
                  <div className="v">
                    {created?.orgName} · {merchant?.name}{merchant?.domain ? ` · ${merchant.domain}` : ''}
                  </div>
                </div>
                <div className="rev">
                  <div className="k">Kind · hosting</div>
                  <div className="v">
                    {(merchant?.kind || kind) === 'seller'
                      ? 'Sells its products (own prices, own programs)'
                      : "Brand — doesn't sell; retailers set prices"}
                    {' · '}
                    {(merchant?.hosting || hosting) === 'external'
                      ? 'pages hosted by the customer'
                      : 'pages hosted by Parleo'}
                  </div>
                </div>
                {mode === 'new' && (
                  <div className="rev">
                    <div className="k">Where products are sold</div>
                    <div className="v">{retailers.map(bareDomain).filter(Boolean).join(' · ') || '—'}</div>
                  </div>
                )}
                {steps.includes('feed') && (
                  <div className="rev">
                    <div className="k">Product feed</div>
                    <div className="v">
                      {preview
                        ? [
                            files.map((f) => f.name).join(', '),
                            `${plural(validRows, 'product')} will be saved`,
                            errorRows > 0 ? `${plural(errorRows, 'row')} left out (errors)` : null,
                            warningRows > 0 ? `${plural(warningRows, 'warning')} kept` : null,
                          ].filter(Boolean).join(' · ')
                        : 'No feed uploaded'}
                    </div>
                  </div>
                )}
                {steps.includes('offers') && (
                  <div className="rev">
                    <div className="k">Customer-owned offers</div>
                    <div className="v">{describeOffers(offers)}</div>
                  </div>
                )}
                <div className="rev">
                  <div className="k">What happens next</div>
                  <div className="v">
                    {mode === 'new' ? (
                      <>
                        A record is created under this account, and <b>{merchant?.name}</b> appears in
                        your customer switcher in the Command Center. Select it to see its dashboard and
                        create its first study. You keep your own login — the switcher lists every customer
                        you can access.
                        {(merchant?.hosting || hosting) === 'external' && (
                          <> Syndication columns will show <em>not connected</em> until the customer
                          integrates or grants access.</>
                        )}
                      </>
                    ) : mode === 'feed' ? (
                      'The upload becomes the customer\'s current feed version; the previous one is kept, marked superseded.'
                    ) : (
                      'These replace the customer\'s owned offers. Studies generated from now on expect them.'
                    )}
                  </div>
                </div>
              </div>
            )}

            {busy && <div className="busy" role="status">{busy}</div>}
            {error && <div className="error" role="alert">{error}</div>}
          </div>

          <div className="modal-foot">
            <button type="button" className="btn btn-ghost" disabled={stepIndex === 0 || !!busy} onClick={back}>
              Back
            </button>
            <div className="right">
              {mode === 'new' && (
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={!!busy || (step !== 'account' && !created)}
                  title="Keep the account and customer; the feed and offers are not saved"
                  onClick={saveDraft}
                >
                  Save draft
                </button>
              )}
              <button type="button" className="btn btn-primary" disabled={continueDisabled} onClick={next}>
                {primaryLabel}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
