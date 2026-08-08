/**
 * RequestFormModal — leadgen session. No exported design-system bundle
 * covers this (unlike every other ds/ component, this one is hand-
 * authored to the marketing site's Request-demo modal UX as described
 * in the brief, not ported verbatim from a design-refs source).
 *
 * Deliberately decoupled from the demo-request API: this component
 * only knows how to render a form, validate it client-side, and call
 * the `onSubmit` prop it's given — it has no idea what source/
 * brand_name/report_token/page_url are, or that the endpoint is
 * /api/public/demo-request. That context-gathering lives in lite/
 * (which is allowed to depend on ds/, never the other way around) —
 * see lite/useDemoRequestModal.js.
 *
 * onSubmit(values) must resolve to { ok, status, body } (never throw —
 * demoRequestApi.js's submitDemoRequest already has this shape). A 422
 * with a FastAPI-style {detail: [{loc, msg}]} body renders per-field
 * errors; any other non-ok result shows the generic failure line with
 * the entered values preserved; ok shows the success state.
 */
import { useEffect, useId, useRef, useState } from 'react'
import { Button } from './Button.jsx'
import { Glyph } from './Glyph.jsx'

const EMAIL_SHAPE = /[^\s@]+@[^\s@]+\.[^\s@]+/
const MAX_SHORT_FIELD = 200
const MAX_MESSAGE = 2000

// Anti-spam (Part 1c): a bot that fills every field and submits inside
// this window almost certainly never rendered/read the form. Chosen
// well under normal human fill time (a few seconds minimum) but long
// enough that no real visitor could plausibly trip it. Exported so
// tests can advance fake timers past it explicitly rather than
// guessing a magic number that has to be kept in sync by hand.
export const MIN_ELAPSED_MS = 1500

const FIELD_LABELS = { name: 'Name', email: 'Email', company: 'Company' }

function fieldErrorsFromDetail(detail) {
  const errors = {}
  if (!Array.isArray(detail)) return errors
  for (const item of detail) {
    const loc = item && item.loc
    if (!Array.isArray(loc) || loc.length === 0) continue
    const field = loc[loc.length - 1]
    if (typeof field === 'string' && !errors[field]) {
      errors[field] = item.msg || 'Invalid value'
    }
  }
  return errors
}

function validate(values) {
  const errors = {}
  const name = values.name.trim()
  const email = values.email.trim()
  const company = values.company.trim()

  if (!name) errors.name = 'Name is required'
  else if (name.length > MAX_SHORT_FIELD) errors.name = `Name must be under ${MAX_SHORT_FIELD} characters`

  if (!email) errors.email = 'Email is required'
  else if (!EMAIL_SHAPE.test(email)) errors.email = 'Enter a valid email address'
  else if (email.length > MAX_SHORT_FIELD) errors.email = `Email must be under ${MAX_SHORT_FIELD} characters`

  if (!company) errors.company = 'Company is required'
  else if (company.length > MAX_SHORT_FIELD) errors.company = `Company must be under ${MAX_SHORT_FIELD} characters`

  if (values.message.length > MAX_MESSAGE) errors.message = `Message must be under ${MAX_MESSAGE} characters`

  return errors
}

const EMPTY_VALUES = { name: '', email: '', company: '', message: '' }
const FOCUSABLE_SELECTOR = 'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

function fieldStyle(hasError) {
  return {
    width: '100%',
    boxSizing: 'border-box',
    padding: '11px 13px',
    fontFamily: 'var(--font-sans)',
    fontSize: 14.5,
    color: 'var(--text-strong)',
    background: 'var(--surface)',
    border: `1px solid ${hasError ? 'var(--red)' : 'var(--border)'}`,
    borderRadius: 'var(--r-md)',
    outline: 'none',
    minHeight: 44,
  }
}

function Field({ id, label, required, error, children }) {
  return (
    <div style={{ minWidth: 0 }}>
      <label htmlFor={id} style={{ display: 'block', fontSize: 12.5, fontWeight: 560, color: 'var(--text-strong)', marginBottom: 6 }}>
        {label}{required ? <span style={{ color: 'var(--blue)' }}> *</span> : null}
      </label>
      {children}
      {error ? (
        <div role="alert" style={{ marginTop: 5, fontSize: 12, color: 'var(--red-deep)' }}>{error}</div>
      ) : null}
    </div>
  )
}

export function RequestFormModal({ open, onClose, eyebrow, title, messagePlaceholder, onSubmit }) {
  const uid = useId()
  const cardRef = useRef(null)
  const firstFieldRef = useRef(null)
  const previouslyFocusedRef = useRef(null)
  const openedAtRef = useRef(0)

  const [values, setValues] = useState(EMPTY_VALUES)
  const [honeypot, setHoneypot] = useState('')
  const [errors, setErrors] = useState({})
  const [status, setStatus] = useState('form') // form | submitting | success
  const [submitError, setSubmitError] = useState(null)

  useEffect(() => {
    if (!open) return
    previouslyFocusedRef.current = document.activeElement
    openedAtRef.current = Date.now()
    setValues(EMPTY_VALUES)
    setHoneypot('')
    setErrors({})
    setStatus('form')
    setSubmitError(null)
    const t = setTimeout(() => firstFieldRef.current?.focus(), 0)
    return () => clearTimeout(t)
  }, [open])

  useEffect(() => {
    if (!open) return
    return () => {
      previouslyFocusedRef.current?.focus?.()
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKeyDown(e) {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
        return
      }
      if (e.key !== 'Tab') return
      const node = cardRef.current
      if (!node) return
      const focusable = Array.from(node.querySelectorAll(FOCUSABLE_SELECTOR)).filter((el) => el.offsetParent !== null)
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown, true)
    return () => document.removeEventListener('keydown', onKeyDown, true)
  }, [open, onClose])

  if (!open) return null

  function handleChange(field, value) {
    setValues((v) => ({ ...v, [field]: value }))
    setErrors((e) => (e[field] ? { ...e, [field]: null } : e))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (status === 'submitting') return

    const elapsed = Date.now() - openedAtRef.current
    if (honeypot.trim() !== '' || elapsed < MIN_ELAPSED_MS) {
      // Anti-spam trip (Part 1c): show success without calling the API.
      setStatus('success')
      return
    }

    const clientErrors = validate(values)
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors)
      return
    }

    setStatus('submitting')
    setSubmitError(null)
    const result = await onSubmit({
      name: values.name.trim(),
      email: values.email.trim(),
      company: values.company.trim(),
      message: values.message.trim(),
    })

    if (result && result.ok) {
      setStatus('success')
      return
    }

    if (result && result.status === 422 && result.body) {
      setErrors(fieldErrorsFromDetail(result.body.detail))
      setStatus('form')
      return
    }

    setStatus('form')
    setSubmitError('Something went wrong — email us at elton@parleo.io')
  }

  const submitting = status === 'submitting'

  return (
    <div
      role="presentation"
      className="lite-request-modal-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        background: 'rgba(30,30,46,.55)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 20,
      }}
    >
      <div
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${uid}-title`}
        className="lite-request-modal-card"
        style={{
          position: 'relative',
          width: '100%',
          maxWidth: 480,
          maxHeight: '90vh',
          overflowY: 'auto',
          background: 'var(--surface)',
          borderRadius: 'var(--r-xl)',
          boxShadow: 'var(--shadow-float)',
          padding: '36px 32px 32px',
        }}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          style={{
            position: 'absolute',
            top: 16,
            right: 16,
            width: 44,
            height: 44,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'transparent',
            border: 'none',
            borderRadius: 'var(--r-md)',
            cursor: 'pointer',
            color: 'var(--muted)',
          }}
        >
          <Glyph name="x" size={16} />
        </button>

        {status === 'success' ? (
          <div style={{ textAlign: 'center', padding: '20px 8px 4px' }}>
            <div
              style={{
                width: 56,
                height: 56,
                margin: '0 auto 20px',
                borderRadius: '50%',
                background: 'var(--blue-tint)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Glyph name="check" size={24} color="var(--blue)" strokeWidth={2} />
            </div>
            <div id={`${uid}-title`} style={{ fontSize: 20, fontWeight: 680, color: 'var(--text-strong)', letterSpacing: '-0.01em' }}>Message sent</div>
            <p style={{ marginTop: 8, fontSize: 14, color: 'var(--muted)' }}>We&rsquo;ll get back to you shortly.</p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} noValidate>
            <div className="mono-label" style={{ color: 'var(--blue)', marginBottom: 10 }}>{eyebrow}</div>
            <h2 id={`${uid}-title`} style={{ margin: '0 0 22px', fontSize: 21, fontWeight: 680, color: 'var(--text-strong)', letterSpacing: '-0.012em', lineHeight: 1.25 }}>
              {title}
            </h2>

            {/* Honeypot (Part 1c) — real users never see or fill this;
                any client that does trips the same anti-spam path as a
                too-fast submit, above. Kept off-canvas rather than
                display:none, which some crawlers skip filling. */}
            <div aria-hidden="true" style={{ position: 'absolute', left: -9999, top: 'auto', width: 1, height: 1, overflow: 'hidden' }}>
              <label htmlFor={`${uid}-website`}>Website</label>
              <input
                id={`${uid}-website`}
                name="website"
                type="text"
                tabIndex={-1}
                autoComplete="off"
                value={honeypot}
                onChange={(e) => setHoneypot(e.target.value)}
              />
            </div>

            <div className="lite-cols-2" style={{ marginBottom: 16 }}>
              <Field id={`${uid}-name`} label="Name" required error={errors.name}>
                <input
                  ref={firstFieldRef}
                  id={`${uid}-name`}
                  type="text"
                  placeholder="Jane Smith"
                  value={values.name}
                  onChange={(e) => handleChange('name', e.target.value)}
                  style={fieldStyle(!!errors.name)}
                  aria-invalid={!!errors.name}
                />
              </Field>
              <Field id={`${uid}-email`} label="Email" required error={errors.email}>
                <input
                  id={`${uid}-email`}
                  type="email"
                  placeholder="jane@company.com"
                  value={values.email}
                  onChange={(e) => handleChange('email', e.target.value)}
                  style={fieldStyle(!!errors.email)}
                  aria-invalid={!!errors.email}
                />
              </Field>
            </div>

            <div style={{ marginBottom: 16 }}>
              <Field id={`${uid}-company`} label="Company" required error={errors.company}>
                <input
                  id={`${uid}-company`}
                  type="text"
                  placeholder="Acme Corp"
                  value={values.company}
                  onChange={(e) => handleChange('company', e.target.value)}
                  style={fieldStyle(!!errors.company)}
                  aria-invalid={!!errors.company}
                />
              </Field>
            </div>

            <div style={{ marginBottom: 22 }}>
              <Field id={`${uid}-message`} label="Message" error={errors.message}>
                <textarea
                  id={`${uid}-message`}
                  placeholder={messagePlaceholder}
                  value={values.message}
                  onChange={(e) => handleChange('message', e.target.value)}
                  rows={4}
                  style={{ ...fieldStyle(!!errors.message), resize: 'vertical', fontFamily: 'var(--font-sans)' }}
                />
              </Field>
            </div>

            {submitError ? (
              <div role="alert" style={{ marginBottom: 14, fontSize: 13, color: 'var(--red-deep)' }}>{submitError}</div>
            ) : null}

            {/* Button doesn't take a `type` prop — its underlying <button>
                has no type attribute, so it defaults to type="submit"
                inside a <form> and this still triggers handleSubmit
                (same pattern as LiteForm.jsx). */}
            <Button variant="ink" disabled={submitting} style={{ width: '100%', justifyContent: 'center', minHeight: 44 }}>
              {submitting ? 'Sending…' : 'Send message'}
            </Button>
          </form>
        )}
      </div>
    </div>
  )
}
