/**
 * Logo feature, Part 3b: logoProvider.js owns the third-party logo API
 * URL construction and the "is a provider even configured" flag that
 * BrandLogo's chain and the footer attribution line both read. The env
 * var is read once at module load, so each case re-imports the module
 * fresh under a stubbed env.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

async function freshImport() {
  vi.resetModules()
  return import('../logoProvider.js')
}

describe('logoProvider', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
  })

  it('builds the logo.dev URL from domain, token, and size when a token is configured', async () => {
    vi.stubEnv('VITE_LOGO_DEV_TOKEN', 'pk_test_123')
    const { logoProviderUrl } = await freshImport()
    expect(logoProviderUrl('acme.com', 32)).toBe('https://img.logo.dev/acme.com?token=pk_test_123&size=32')
  })

  it('reports the provider as configured when the token is present', async () => {
    vi.stubEnv('VITE_LOGO_DEV_TOKEN', 'pk_test_123')
    const { LOGO_PROVIDER_CONFIGURED } = await freshImport()
    expect(LOGO_PROVIDER_CONFIGURED).toBe(true)
  })

  it('returns null and reports unconfigured when no token is set', async () => {
    vi.stubEnv('VITE_LOGO_DEV_TOKEN', '')
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { logoProviderUrl, LOGO_PROVIDER_CONFIGURED } = await freshImport()
    expect(logoProviderUrl('acme.com', 32)).toBeNull()
    expect(LOGO_PROVIDER_CONFIGURED).toBe(false)
    expect(warnSpy).toHaveBeenCalledTimes(1)
  })

  it('returns null when there is no domain to key off of, even with a token configured', async () => {
    vi.stubEnv('VITE_LOGO_DEV_TOKEN', 'pk_test_123')
    const { logoProviderUrl } = await freshImport()
    expect(logoProviderUrl(null, 32)).toBeNull()
  })
})
