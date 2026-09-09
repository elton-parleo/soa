/**
 * "Regenerate from the catalog" — the choice the study page offers when a
 * study is grounded in a syndicated brand.
 *
 * One decision, and the modal exists to make it an informed one: the
 * catalog-built questions are ALWAYS rebuilt (carrying the currently
 * published answer is what they are for, so a republished price makes
 * them wrong, not stale), while rebuilding the AI-written tier produces
 * different question wording and breaks run-over-run comparability with
 * every cycle before it.
 *
 * The study's own stage-count questions are never rebuilt by this, and
 * the copy says so. Rewriting those is creating a different study, not
 * refreshing this one against a record.
 */
import { useState } from 'react'
import { api } from '../api.js'

const T = {
  white: '#FFFFFF', border: '#E2E8F0', text: '#0F172A', textMid: '#334155',
  slate: '#64748B', amberLight: '#FEF3C7', redLight: '#FEE2E2',
}

export default function RegenerateStudyModal({ open, studyType, merchant, onClose, onStarted }) {
  const [regenerateAi, setRegenerateAi] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  if (!open) return null

  async function handleSubmit() {
    setSubmitting(true)
    setError(null)
    try {
      const result = await api.regenerateStudy(studyType, regenerateAi)
      if (onStarted) onStarted(result)
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      onClick={() => { if (!submitting) onClose() }}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', zIndex: 100,
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Regenerate from the catalog"
        style={{
          background: T.white, borderRadius: 12, width: 520, maxWidth: '100%',
          fontFamily: "'DM Sans', sans-serif", boxShadow: '0 8px 32px rgba(0,0,0,0.16)',
        }}
      >
        <div style={{ padding: '24px 24px 16px', borderBottom: `1px solid ${T.border}` }}>
          <span style={{ fontSize: 18, fontWeight: 700, color: T.text }}>
            Regenerate from the catalog
          </span>
        </div>

        <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 18 }}>
          <div style={{ fontSize: 13, color: T.textMid, lineHeight: 1.6 }}>
            The catalog-built questions{merchant ? ` for ${merchant}` : ''} will be
            rebuilt from the record as it is published <strong>now</strong> —
            prices, pack counts, codes and member prices. They carry the published
            answer, so a republished catalog makes them wrong rather than out of
            date, and refreshing them is what regenerating means.
          </div>

          <label style={{ display: 'flex', gap: 10, alignItems: 'flex-start', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={regenerateAi}
              onChange={(e) => setRegenerateAi(e.target.checked)}
              style={{ marginTop: 2 }}
            />
            <span>
              <span style={{ fontSize: 13, fontWeight: 600, color: T.text, display: 'block' }}>
                Also rewrite the AI-written brand questions
              </span>
              <span style={{ fontSize: 12, color: T.slate, lineHeight: 1.5, display: 'block', marginTop: 3 }}>
                Their wording is written by a model, so rewriting them produces
                different questions — and a study whose questions changed cannot
                be compared run-over-run with the cycles before it. Leave this
                off unless the catalog has changed enough that the old questions
                ask about products the brand no longer sells.
              </span>
            </span>
          </label>

          <div style={{
            background: T.amberLight, border: '1px solid #FDE68A', borderRadius: 8,
            padding: '10px 13px', fontSize: 12, color: '#78350F', lineHeight: 1.55,
          }}>
            Questions from past cycles keep their measurements. The runs and
            outcomes already recorded are evidence of what was true then and are
            never deleted — only the questions themselves are replaced.
          </div>

          {error && (
            <div style={{
              background: T.redLight, border: '1px solid #FECACA', borderRadius: 8,
              padding: '10px 14px', fontSize: 13, color: '#991B1B',
            }}>{error}</div>
          )}
        </div>

        <div style={{
          padding: '16px 24px', borderTop: `1px solid ${T.border}`,
          display: 'flex', justifyContent: 'flex-end', gap: 12,
        }}>
          <button
            onClick={() => { if (!submitting) onClose() }}
            disabled={submitting}
            style={{
              padding: '9px 18px', background: T.white, color: T.text,
              border: `1px solid ${T.border}`, borderRadius: 8, fontWeight: 600,
              fontSize: 13, fontFamily: 'inherit', cursor: submitting ? 'not-allowed' : 'pointer',
            }}
          >Cancel</button>
          <button
            onClick={handleSubmit}
            disabled={submitting}
            style={{
              padding: '9px 18px', background: T.text, color: T.white, border: 'none',
              borderRadius: 8, fontWeight: 700, fontSize: 13, fontFamily: 'inherit',
              cursor: submitting ? 'not-allowed' : 'pointer', opacity: submitting ? 0.6 : 1,
            }}
          >{submitting ? 'Starting…' : 'Regenerate'}</button>
        </div>
      </div>
    </div>
  )
}
