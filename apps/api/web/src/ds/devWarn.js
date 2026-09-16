/**
 * Part 2c: one narrow, single-purpose module so RequestFormModal.jsx's
 * own submit path — the gate checks and the fetch it eventually
 * triggers — stays free of any import.meta.env/VITE_ reference
 * (grep-tested in noOrphanedReferences.test.js): this is a diagnostic
 * console line only, it can never affect whether a request is sent.
 * Mirrors analytics.js's own IS_DEV pattern, kept separate rather than
 * imported from lite/ since ds/ never depends on lite/ (see
 * RequestFormModal.jsx's own docstring on that boundary).
 */
const IS_DEV = !!import.meta.env.DEV

export function logAntiSpamGateTripped(reason) {
  if (IS_DEV) {
    console.warn(`demo form: anti-spam gate tripped — no request sent; reason: ${reason}`)
  }
}
