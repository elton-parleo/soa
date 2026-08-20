/**
 * submitDemoRequest — posts to Formspree, not our own API. FormData,
 * not JSON; Accept: application/json is the only header we set
 * ourselves (no Content-Type — the browser sets the multipart
 * boundary for a FormData body).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { submitDemoRequest } from '../demoRequestApi.js'
import { FORMSPREE_DEMO_ENDPOINT } from '../publicUrls.js'

function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }
}

beforeEach(() => {
  vi.spyOn(global, 'fetch')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('submitDemoRequest', () => {
  it('POSTs FormData to FORMSPREE_DEMO_ENDPOINT with Accept: application/json, no Content-Type', async () => {
    global.fetch.mockResolvedValue(jsonResponse(200, { ok: true }))

    await submitDemoRequest({
      name: 'Jane Smith', email: 'jane@company.com', company: 'Acme Corp', message: 'hi',
      source: 'truesync', subject: 'Demo request — TrueSync',
      page_url: 'https://audit.parleo.io/r/tok123', brand_name: 'Allbirds', report_token: 'tok123',
    })

    expect(global.fetch).toHaveBeenCalledTimes(1)
    const [url, init] = global.fetch.mock.calls[0]
    expect(url).toBe(FORMSPREE_DEMO_ENDPOINT)
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({ Accept: 'application/json' })
    expect(init.body).toBeInstanceOf(FormData)
  })

  it('carries every visible field plus the hidden context fields, _subject, and _gotcha', async () => {
    global.fetch.mockResolvedValue(jsonResponse(200, { ok: true }))

    await submitDemoRequest({
      name: 'Jane Smith', email: 'jane@company.com', company: 'Acme Corp', message: 'hi',
      source: 'truesync', subject: 'Demo request — TrueSync',
      page_url: 'https://audit.parleo.io/r/tok123', brand_name: 'Allbirds', report_token: 'tok123',
    })

    const formData = global.fetch.mock.calls[0][1].body
    expect(formData.get('name')).toBe('Jane Smith')
    expect(formData.get('email')).toBe('jane@company.com')
    expect(formData.get('company')).toBe('Acme Corp')
    expect(formData.get('message')).toBe('hi')
    expect(formData.get('source')).toBe('truesync')
    expect(formData.get('page_url')).toBe('https://audit.parleo.io/r/tok123')
    expect(formData.get('brand_name')).toBe('Allbirds')
    expect(formData.get('report_token')).toBe('tok123')
    expect(formData.get('_subject')).toBe('Demo request — TrueSync')
    expect(formData.get('_gotcha')).toBe('')
  })

  it('omits brand_name/report_token when not opened from a report (landing)', async () => {
    global.fetch.mockResolvedValue(jsonResponse(200, { ok: true }))

    await submitDemoRequest({
      name: 'Jane', email: 'jane@company.com', company: 'Acme', message: '',
      source: 'landing_truesync', subject: 'Demo request — TrueSync',
      page_url: 'https://audit.parleo.io/', brand_name: undefined, report_token: undefined,
    })

    const formData = global.fetch.mock.calls[0][1].body
    expect(formData.get('brand_name')).toBeNull()
    expect(formData.get('report_token')).toBeNull()
  })

  it('falls back to a generic _subject when the CTA carries none', async () => {
    global.fetch.mockResolvedValue(jsonResponse(200, { ok: true }))

    await submitDemoRequest({ name: 'Jane', email: 'jane@company.com', company: 'Acme', message: '' })

    const formData = global.fetch.mock.calls[0][1].body
    expect(formData.get('_subject')).toBe('Demo request')
  })

  it('resolves { ok: true, status } on a 200', async () => {
    global.fetch.mockResolvedValue(jsonResponse(200, { ok: true }))
    const result = await submitDemoRequest({ name: 'Jane', email: 'jane@company.com', company: 'Acme', message: '' })
    expect(result).toEqual({ ok: true, status: 200, body: { ok: true } })
  })

  it('resolves { ok: false, status, body } on a non-2xx, without throwing', async () => {
    global.fetch.mockResolvedValue(jsonResponse(422, { error: 'The email field is invalid.' }))
    const result = await submitDemoRequest({ name: 'Jane', email: 'bad', company: 'Acme', message: '' })
    expect(result).toEqual({ ok: false, status: 422, body: { error: 'The email field is invalid.' } })
  })

  it('resolves { ok: false, status: 0, networkError: true } when fetch throws', async () => {
    global.fetch.mockRejectedValue(new Error('offline'))
    const result = await submitDemoRequest({ name: 'Jane', email: 'jane@company.com', company: 'Acme', message: '' })
    expect(result).toEqual({ ok: false, status: 0, body: null, networkError: true })
  })

  it('never throws even if the response body is not valid JSON', async () => {
    global.fetch.mockResolvedValue({ ok: true, status: 200, json: async () => { throw new Error('not json') } })
    const result = await submitDemoRequest({ name: 'Jane', email: 'jane@company.com', company: 'Acme', message: '' })
    expect(result).toEqual({ ok: true, status: 200, body: null })
  })
})
