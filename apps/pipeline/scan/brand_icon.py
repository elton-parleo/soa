"""
brand_icon.py — Part 1a/1b: the audited brand's own icon, resolved from
documents ALREADY fetched during the crawl — no new fetch. structured_
data.py's extract() (run uniformly, once per sampled page, same as
every other field it captures) already collects apple_touch_icons/
icon_links/organization_logo on every page's ExtractedData; this module
just picks the homepage page specifically and applies the precedence
order.

Precedence: apple-touch-icon (largest declared size) > link rel=icon
(largest declared size) > schema.org Organization.logo. Absolutized
against the homepage's own final URL. Never a third-party or stock
substitute for the primary brand — None when nothing was declared, the
homepage was never reached this run, or the run predates this stage.
"""
from typing import Optional
from urllib.parse import urljoin


def _icon_area(icon: dict) -> int:
    """Best-effort area from a `sizes` attribute like "180x180" or a
    space-separated multi-size list ("32x32 16x16" — take the largest
    token). 0 (lowest priority, never disqualifying) when absent or
    unparseable — "any" is a legitimate, if unranked, sizes value."""
    sizes = icon.get("sizes") or ""
    best = 0
    for token in sizes.split():
        parts = token.lower().split("x")
        if len(parts) == 2:
            try:
                best = max(best, int(parts[0]) * int(parts[1]))
            except ValueError:
                continue
    return best


def _largest(icons: list) -> Optional[dict]:
    if not icons:
        return None
    return max(icons, key=_icon_area)


def extract_brand_icon(pages) -> Optional[str]:
    """None on a blocked/failed run (no homepage reached), or when the
    homepage declared no icon at all — never a fabricated substitute."""
    homepage = next((p for p in pages if p.candidate.kind == "homepage"), None)
    if not homepage or not homepage.extracted:
        return None

    fetch_result = homepage.fetch_result
    base_url = (fetch_result.final_url or fetch_result.url) if fetch_result else None
    if not base_url:
        return None

    extracted = homepage.extracted
    icon = _largest(extracted.apple_touch_icons) or _largest(extracted.icon_links)
    if icon:
        return urljoin(base_url, icon["href"])

    if extracted.organization_logo:
        return urljoin(base_url, extracted.organization_logo)

    return None
