/**
 * truesyncApi.js's transport: which reads go where, and what they carry.
 *
 * Since supply's tenancy step, scoped TrueSync reads are refused without
 * the tenant token, and the token is server-side only. So the scoped
 * reads must go same-origin, through this app's authed proxy, carrying
 * this app's session — and never a TrueSync credential. The public reads
 * still go straight to TRUESYNC_API_BASE, carrying nothing.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setApiToken } from '../api.js'
import { CUSTOMER_HEADER, clearSelection, setSelection } from '../customerSelection.js'
import {
  NOT_AUTHORIZED,
  TRUESYNC_API_BASE,
  TrueSyncError,
  fetchAllVerifications,
  truesyncApi,
  unwrapVerifications,
} from '../truesyncApi.js'
import gmcEnvelope from '../components/merchant-command-center/__fixtures__/verifications-gmc.json'
import probeEnvelope from '../components/merchant-command-center/__fixtures__/verifications-fetch-probe.json'

const SESSION = 'supabase-session-jwt'

function okJson(body) {
  return { ok: true, status: 200, json: async () => body }
}

function status(code, body = { detail: 'nope' }) {
  return { ok: false, status: code, json: async () => body }
}

let fetchMock

beforeEach(() => {
  clearSelection()
  setApiToken(SESSION)
  fetchMock = vi.fn(async () => okJson([]))
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
  setApiToken(null)
})

const SCOPED = {
  getChannels: [() => truesyncApi.getChannels(), '/api/truesync/channels'],
  getPublications: [() => truesyncApi.getPublications(), '/api/truesync/publications?limit=500'],
  getMerchants: [() => truesyncApi.getMerchants(), '/api/truesync/merchants'],
  getMerchantCatalog: [() => truesyncApi.getMerchantCatalog('w&s'), '/api/truesync/merchants/w%26s/catalog'],
  getMerchantIncentives: [() => truesyncApi.getMerchantIncentives('ws'), '/api/truesync/merchants/ws/incentives'],
  getProspects: [() => truesyncApi.getProspects(), '/api/truesync/prospects'],
  getProspectDrift: [() => truesyncApi.getProspectDrift('pampers'), '/api/truesync/prospects/pampers/drift'],
  getVerifications: [
    () => truesyncApi.getVerifications(90, 'acp'),
    '/api/truesync/listings/90/verifications?channel=acp&limit=100',
  ],
  // Step 1C
  getMerchantVerifications: [
    () => truesyncApi.getMerchantVerifications('ws', 'acp'),
    '/api/truesync/merchants/ws/verifications?channel=acp&limit=100',
  ],
  getTenant: [() => truesyncApi.getTenant(), '/api/truesync/tenant'],
  getRetailers: [() => truesyncApi.getRetailers('petco'), '/api/truesync/merchants/petco/retailers'],
  getFeed: [() => truesyncApi.getFeed('petco'), '/api/truesync/merchants/petco/feed'],
  getFeedHistory: [() => truesyncApi.getFeedHistory('petco'), '/api/truesync/merchants/petco/feed/history'],
  getOwnedIncentives: [
    () => truesyncApi.getOwnedIncentives('petco'), '/api/truesync/merchants/petco/incentives/owned'],
  // Step 2A-0
  getProvenance: [() => truesyncApi.getProvenance('petco'), '/api/truesync/merchants/petco/provenance'],
}

//: The wizard's writes (Step 1C) — the same proxy, the same rules.
const WRITES = {
  putRetailers: [() => truesyncApi.putRetailers('petco', ['petco.com']),
    'PUT', '/api/truesync/merchants/petco/retailers'],
  validateFeed: [() => truesyncApi.validateFeed('petco', [new File(['gtin'], 'f.csv')]),
    'POST', '/api/truesync/merchants/petco/feed/validate?skip_reachability=false'],
  commitFeed: [() => truesyncApi.commitFeed('petco', 'u1', 'require_clean'),
    'POST', '/api/truesync/merchants/petco/feed/commit'],
  putOwnedIncentives: [() => truesyncApi.putOwnedIncentives('petco', []),
    'PUT', '/api/truesync/merchants/petco/incentives/owned'],
}

//: Public upstream, carried by the proxy with only this app's session.
const TEMPLATE = ['downloadTemplate']

const PUBLIC = {
  getActiveBrand: [() => truesyncApi.getActiveBrand(), '/api/truesync/demo/active-brand'],
  getMerchantSchemaOrg: [() => truesyncApi.getMerchantSchemaOrg('ws'), '/api/truesync/merchants/ws/schema-org'],
  getListing: [() => truesyncApi.getListing(90), '/api/truesync/listings/90'],
}

describe('scoped reads go through this app\'s proxy', () => {
  it('covers every read method the client exposes', () => {
    // A read added to truesyncApi without a row in one of these tables
    // has not been decided: public, or scoped behind the proxy.
    expect(Object.keys(truesyncApi).sort())
      .toEqual([...Object.keys(SCOPED), ...Object.keys(PUBLIC), ...Object.keys(WRITES), ...TEMPLATE].sort())
  })

  it.each(Object.entries(SCOPED))('%s is same-origin, with the session, without a TrueSync key', async (_name, [call, path]) => {
    await call()

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(path)
    expect(url.startsWith(TRUESYNC_API_BASE)).toBe(false)
    expect(init.headers.Authorization).toBe(`Bearer ${SESSION}`)
    expect(Object.keys(init.headers).map((h) => h.toLowerCase())).not.toContain('x-truesync-key')
  })

  it.each(Object.entries(SCOPED))('%s turns a 403 into "not authorized for this customer"', async (_name, [call]) => {
    fetchMock.mockResolvedValue(status(403, { detail: 'whatever the proxy said' }))

    const err = await call().catch((e) => e)

    expect(err).toBeInstanceOf(TrueSyncError)
    expect(err.notAuthorized).toBe(true)
    expect(err.status).toBe(403)
    expect(err.message).toBe(NOT_AUTHORIZED)
  })
})

describe('public reads go straight to TrueSync', () => {
  it.each(Object.entries(PUBLIC))('%s carries no credential at all', async (_name, [call, path]) => {
    await call()

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${TRUESYNC_API_BASE}${path}`)
    expect(init.headers).toEqual({})
  })
})

describe('the selected customer rides on every proxied call', () => {
  it.each(Object.entries(SCOPED))('%s names the selected org', async (_name, [call]) => {
    setSelection({ orgId: 7, merchantSlug: 'ws', prospectSlug: null })
    await call()
    expect(fetchMock.mock.calls[0][1].headers[CUSTOMER_HEADER]).toBe('7')
  })

  it('a caller can read under another org without changing the selection', async () => {
    setSelection({ orgId: 7, merchantSlug: 'ws', prospectSlug: null })
    await truesyncApi.getMerchantCatalog('brandco', { customer: 20 })
    expect(fetchMock.mock.calls[0][1].headers[CUSTOMER_HEADER]).toBe('20')
  })

  it('with nothing selected it sends no customer, and the server picks the user\'s own', async () => {
    await truesyncApi.getChannels()
    expect(Object.keys(fetchMock.mock.calls[0][1].headers)).not.toContain(CUSTOMER_HEADER)
  })
})

describe('the wizard\'s writes go through the proxy too', () => {
  it.each(Object.entries(WRITES))('%s: same-origin, session, customer, no TrueSync key', async (_name, [call, method, path]) => {
    setSelection({ orgId: 9, merchantSlug: 'petco', prospectSlug: null })
    fetchMock.mockResolvedValue(okJson({}))

    await call()

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(path)
    expect(init.method).toBe(method)
    expect(init.headers.Authorization).toBe(`Bearer ${SESSION}`)
    expect(init.headers[CUSTOMER_HEADER]).toBe('9')
    expect(Object.keys(init.headers).map((h) => h.toLowerCase())).not.toContain('x-truesync-key')
  })

  it.each(Object.entries(WRITES))('%s: a 403 is "not authorized for this customer"', async (_name, [call]) => {
    fetchMock.mockResolvedValue(status(403, { detail: 'refused' }))
    const err = await call().catch((e) => e)
    expect(err.notAuthorized).toBe(true)
    expect(err.message.startsWith(NOT_AUTHORIZED)).toBe(true)
  })

  it('the feed goes up as multipart, the file under "files"', async () => {
    fetchMock.mockResolvedValue(okJson({}))
    const file = new File(['gtin,product_name'], 'petco.csv', { type: 'text/csv' })
    await truesyncApi.validateFeed('petco', [file], { skipReachability: true })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('skip_reachability=true')
    expect(init.body).toBeInstanceOf(FormData)
    expect(init.body.get('files').name).toBe('petco.csv')
  })

  it('an upstream detail reaches the caller verbatim', async () => {
    fetchMock.mockResolvedValue(status(409, { detail: "merchant 'w' is hosted on Parleo" }))
    const err = await truesyncApi.commitFeed('w', 'u', 'require_clean').catch((e) => e)
    expect(err.message).toBe("merchant 'w' is hosted on Parleo")
    expect(err.status).toBe(409)
  })
})

describe('fetchAllVerifications — the bulk route', () => {
  function bulkByChannel(byChannel) {
    // The bulk route's answer for one channel: {merchant, listings: [...]}.
    fetchMock.mockImplementation(async (url) => {
      const channel = new URL(url, 'http://x').searchParams.get('channel')
      return okJson({ merchant: 'ws', listings: byChannel[channel] || [] })
    })
  }

  it('makes one request per channel, not one per cell', async () => {
    bulkByChannel({})
    await fetchAllVerifications('ws', [90, 91, 92, 93, 94], ['schema_org', 'acp', 'merchant_center'])

    expect(fetchMock).toHaveBeenCalledTimes(3)
    for (const [url] of fetchMock.mock.calls) {
      expect(url).toMatch(/^\/api\/truesync\/merchants\/ws\/verifications\?channel=\w+&limit=100$/)
    }
  })

  it('hands each cell exactly what the per-listing route would have', async () => {
    // Parity: the per-listing route answers one envelope per listing; the
    // bulk route answers the same envelopes in a list. Each cell must hold
    // what unwrapVerifications made of the per-listing answer.
    bulkByChannel({
      merchant_center: [gmcEnvelope],
      schema_org: [probeEnvelope],
    })
    const out = await fetchAllVerifications('ws', [gmcEnvelope.listing_id, 999], ['merchant_center', 'schema_org'])

    expect(out[`${gmcEnvelope.listing_id}:merchant_center`]).toEqual(unwrapVerifications(gmcEnvelope))
    expect(out[`${probeEnvelope.listing_id}:schema_org`]).toEqual(unwrapVerifications(probeEnvelope))
    expect(out['999:merchant_center']).toEqual([])
    expect(out['999:schema_org']).toEqual([])
  })

  it('still reads an ordinary failure as "not yet verified"', async () => {
    fetchMock.mockResolvedValue(status(500))

    const out = await fetchAllVerifications('ws', [90], ['acp'])

    expect(out).toEqual({ '90:acp': [] })
  })

  it('does not hide a refusal behind a matrix of ○', async () => {
    fetchMock.mockResolvedValue(status(403))

    await expect(fetchAllVerifications('ws', [90, 91], ['acp', 'schema_org']))
      .rejects.toMatchObject({ notAuthorized: true, message: NOT_AUTHORIZED })
  })
})
