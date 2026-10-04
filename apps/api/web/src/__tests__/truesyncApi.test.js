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
import {
  NOT_AUTHORIZED,
  TRUESYNC_API_BASE,
  TrueSyncError,
  fetchAllVerifications,
  truesyncApi,
} from '../truesyncApi.js'

const SESSION = 'supabase-session-jwt'

function okJson(body) {
  return { ok: true, status: 200, json: async () => body }
}

function status(code, body = { detail: 'nope' }) {
  return { ok: false, status: code, json: async () => body }
}

let fetchMock

beforeEach(() => {
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
}

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
      .toEqual([...Object.keys(SCOPED), ...Object.keys(PUBLIC)].sort())
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

describe('fetchAllVerifications', () => {
  it('still reads an ordinary failure as "not yet verified"', async () => {
    fetchMock.mockResolvedValue(status(500))

    const out = await fetchAllVerifications([90], ['acp'])

    expect(out).toEqual({ '90:acp': [] })
  })

  it('does not hide a refusal behind a matrix of ○', async () => {
    fetchMock.mockResolvedValue(status(403))

    await expect(fetchAllVerifications([90, 91], ['acp', 'schema_org']))
      .rejects.toMatchObject({ notAuthorized: true, message: NOT_AUTHORIZED })
  })
})
