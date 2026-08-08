/**
 * Wires RequestFormModal (ds/, presentational-only) to the demo-request
 * API and to a CTA's copy from demoRequestCtas.js. Context ride-along
 * (Part 2c): report_token/brand_name are passed in by the caller (only
 * report surfaces have them); page_url is always read fresh from
 * window.location.href at submit time, not captured at open time, so
 * a visitor who navigates within a long-lived SPA session before
 * submitting still reports the page they were actually on.
 */
import { useCallback, useState } from 'react'
import { DEMO_REQUEST_CTAS } from './demoRequestCtas.js'
import { submitDemoRequest } from './demoRequestApi.js'

export function useDemoRequestModal({ brandName, reportToken } = {}) {
  const [ctaKey, setCtaKey] = useState(null)

  const open = useCallback((key) => setCtaKey(key), [])
  const close = useCallback(() => setCtaKey(null), [])

  const cta = ctaKey ? DEMO_REQUEST_CTAS[ctaKey] : null

  const onSubmit = useCallback(
    (values) =>
      submitDemoRequest({
        ...values,
        source: cta ? cta.source : undefined,
        page_url: typeof window !== 'undefined' ? window.location.href : '',
        brand_name: brandName || undefined,
        report_token: reportToken || undefined,
      }),
    [cta, brandName, reportToken],
  )

  return { isOpen: ctaKey !== null, cta, open, close, onSubmit }
}
