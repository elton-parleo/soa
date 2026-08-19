#!/usr/bin/env node
/**
 * Regenerates every favicon PNG from public/favicon.svg (the vector
 * source of truth, itself hand-derived from src/ds/Wordmark.jsx's
 * glyph — see that file's own comment). Run this whenever
 * favicon.svg changes; nothing else in the build pipeline does it
 * automatically.
 *
 *   node scripts/generate-favicons.mjs
 *
 * Node + sharp only (sharp bundles librsvg) — no system SVG tooling
 * required, so this runs the same in CI as on a dev machine.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import sharp from 'sharp'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const PUBLIC_DIR = path.join(__dirname, '../public')
const FAVICON_SVG_PATH = path.join(PUBLIC_DIR, 'favicon.svg')
const FAVICON_VIEWBOX_SIZE = 64 // must match favicon.svg's own viewBox

async function renderPng(svgSource, size, outPath) {
  // Rasterize directly at the target resolution (density scaled from
  // the source viewBox) rather than rendering small and upscaling —
  // keeps every size crisp, not just the largest.
  const density = 72 * (size / FAVICON_VIEWBOX_SIZE)
  await sharp(Buffer.from(svgSource), { density })
    .resize(size, size)
    .png()
    .toFile(outPath)
  console.log(`wrote ${path.relative(PUBLIC_DIR, outPath)} (${size}x${size})`)
}

// iOS convention (Part 2a): a white rounded-square background behind
// the glyph, not a transparent one — iOS masks the icon itself, but
// this is what shows in any context that doesn't apply that mask
// (e.g. a bookmark preview). Same glyph geometry as favicon.svg, just
// re-centered at a smaller scale (~60% of the canvas) to leave a
// visible white margin, per common home-screen icon convention.
function buildAppleTouchIconSvg() {
  const size = 180
  const cornerRadius = size * 0.2
  const glyphW = 42
  const glyphH = 40
  const targetW = size * 0.6
  const scale = targetW / glyphW
  const scaledH = glyphH * scale
  const offsetX = (size - targetW) / 2
  const offsetY = (size - scaledH) / 2
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}">
    <rect x="0" y="0" width="${size}" height="${size}" rx="${cornerRadius}" fill="#FFFFFF" />
    <g transform="translate(${offsetX} ${offsetY}) scale(${scale})">
      <rect x="0" y="0" width="19" height="40" rx="6" fill="#0166FF" />
      <rect x="27" y="9" width="15" height="22" rx="5" fill="#7FB0FF" />
    </g>
  </svg>`
}

async function main() {
  const favicon = fs.readFileSync(FAVICON_SVG_PATH, 'utf8')

  await renderPng(favicon, 16, path.join(PUBLIC_DIR, 'favicon-16.png'))
  await renderPng(favicon, 32, path.join(PUBLIC_DIR, 'favicon-32.png'))
  await renderPng(favicon, 192, path.join(PUBLIC_DIR, 'icon-192.png'))
  await renderPng(favicon, 512, path.join(PUBLIC_DIR, 'icon-512.png'))

  const appleTouchSvg = buildAppleTouchIconSvg()
  await sharp(Buffer.from(appleTouchSvg), { density: 72 })
    .resize(180, 180)
    .png()
    .toFile(path.join(PUBLIC_DIR, 'apple-touch-icon.png'))
  console.log('wrote apple-touch-icon.png (180x180)')
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
