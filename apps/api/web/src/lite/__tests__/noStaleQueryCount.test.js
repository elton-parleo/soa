/**
 * Stage 25 (Part 4, Q4) regression guard: a static sweep over every lite
 * source file (production code only — this file itself and the rest of
 * __tests__/ are excluded) for a literal "12" adjacent to "quer(y|ies)"
 * or "question(s)" — the exact stale-count bug this stage killed
 * (LITE_QUERY_COUNT is now the one source of truth, imported from
 * scanDimensionsRegistry.js wherever a query count is displayed). A
 * future edit that reintroduces a hardcoded "12 questions"/"12 queries"
 * fails here instead of silently drifting from the registry.
 *
 * Numeric "12"s that are NOT a query count (CSS px values, weights,
 * dates, unrelated stage numbers) are extremely common in this codebase
 * and are correctly untouched by the query/quer-adjacency regex below —
 * no allowlist has been needed in practice; one line per offender would
 * be added here if a genuine false positive ever showed up.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const LITE_DIR = path.join(__dirname, '..')

const STALE_QUERY_COUNT_PATTERN = /12[\s-]*(quer|question)|(quer|question)\w*[^.]{0,20}\b12\b/i

function collectSourceFiles(dir) {
  const out = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === '__tests__' || entry.name === 'node_modules') continue
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      out.push(...collectSourceFiles(full))
    } else if (/\.(jsx|js)$/.test(entry.name)) {
      out.push(full)
    }
  }
  return out
}

describe('lite source sweep — no stale hardcoded "12 queries" (Stage 25, Part 4, Q4)', () => {
  it('no production lite source file mentions a literal 12-query count', () => {
    const offenders = []
    for (const file of collectSourceFiles(LITE_DIR)) {
      const text = fs.readFileSync(file, 'utf8')
      if (STALE_QUERY_COUNT_PATTERN.test(text)) {
        offenders.push(path.relative(LITE_DIR, file))
      }
    }
    expect(offenders).toEqual([])
  })
})
