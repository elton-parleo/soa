/**
 * Exposure-model fix regression guard.
 *
 * computeExposure's input was renamed from `visibility` to
 * `trueValueScore` because the two are different pillars and the wrong
 * one was driving the dollar figure. The rename is deliberately NOT
 * backed by a deprecated `visibility` alias: an alias would have let a
 * missed call site keep compiling while silently feeding the wrong
 * pillar in, which is exactly the class of bug this session existed to
 * kill. Without an alias a stale caller instead yields `trueValueScore:
 * undefined` — maximum gap — which is also silent, just in the other
 * direction. So the guard is static: no source file may pass a
 * `visibility` key into computeExposure, ever again.
 *
 * Scoped to the whole web src tree (not just lite/) because
 * components/FullAnalysisReport.jsx is a caller too, and to production
 * code only — this file and the rest of __tests__/ are excluded.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const SRC_DIR = path.join(__dirname, '../..')

// computeExposure({ ... }) with a `visibility` key anywhere in the
// argument object — across newlines, in any key order.
const STALE_INPUT_PATTERN = /computeExposure\s*\(\s*\{[^}]*\bvisibility\s*:/s

function collectSourceFiles(dir) {
  const out = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === '__tests__' || entry.name === 'node_modules') continue
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) out.push(...collectSourceFiles(full))
    else if (/\.(jsx|js)$/.test(entry.name)) out.push(full)
  }
  return out
}

describe('no call site feeds Visibility into the exposure model', () => {
  const files = collectSourceFiles(SRC_DIR)

  it('sweeps a non-trivial number of source files', () => {
    expect(files.length).toBeGreaterThan(20)
  })

  it('finds no computeExposure({ ..., visibility: ... }) anywhere in production code', () => {
    const offenders = files.filter((file) => (
      STALE_INPUT_PATTERN.test(fs.readFileSync(file, 'utf8'))
    ))
    expect(offenders.map((f) => path.relative(SRC_DIR, f))).toEqual([])
  })

  it('every computeExposure call site passes trueValueScore', () => {
    const callSites = []
    for (const file of files) {
      const source = fs.readFileSync(file, 'utf8')
      // Skip the module that defines it — only call sites are checked.
      if (file.endsWith(path.join('lite', 'liteDerive.js'))) continue
      for (const match of source.matchAll(/computeExposure\s*\(\s*\{[^}]*\}/gs)) {
        callSites.push({ file: path.relative(SRC_DIR, file), text: match[0] })
      }
    }
    // The four real callers: the V4 report, the legacy report template,
    // the Full Analysis report, and the landing estimator.
    expect(callSites.length).toBe(4)
    for (const site of callSites) {
      expect(site.text, site.file).toMatch(/trueValueScore\s*:/)
    }
  })
})
