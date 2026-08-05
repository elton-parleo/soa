/**
 * Idempotent <head> tag helpers (S2). Once static HTML can already
 * contain a tag an effect wants to manage (S1's baked-in title/
 * canonical/OG/noindex), a naive "always create, always remove on
 * unmount" effect produces a duplicate the moment it mounts on top of
 * that static tag. upsert* finds an existing tag by its identifying
 * attribute and updates it in place instead of creating a second one;
 * restoreOrRemove reverses that on unmount — restoring the prior value
 * if the tag pre-existed, or removing it if the effect created it.
 */
export function upsertMeta(attr, key, content) {
  let el = document.querySelector(`meta[${attr}="${key}"]`)
  const existed = !!el
  const prevValue = existed ? el.getAttribute('content') : undefined
  if (!el) {
    el = document.createElement('meta')
    el.setAttribute(attr, key)
    document.head.appendChild(el)
  }
  el.setAttribute('content', content)
  return { el, existed, prevValue }
}

export function upsertLink(rel, href) {
  let el = document.querySelector(`link[rel="${rel}"]`)
  const existed = !!el
  const prevValue = existed ? el.getAttribute('href') : undefined
  if (!el) {
    el = document.createElement('link')
    el.setAttribute('rel', rel)
    document.head.appendChild(el)
  }
  el.setAttribute('href', href)
  return { el, existed, prevValue }
}

export function restoreOrRemove(handle) {
  if (!handle) return
  const { el, existed, prevValue } = handle
  if (!existed) {
    el.remove()
    return
  }
  if (el.tagName === 'LINK') {
    el.setAttribute('href', prevValue)
  } else {
    el.setAttribute('content', prevValue)
  }
}
