"""
site_context.py — one homepage read that tells the competitor prompt
what a brand actually sells.

Competitor auto-suggest used to infer the category from the brand NAME
alone, so an ambiguous or little-known name ("Orbit", "Kindred",
"Bellwether") produced a plausible-looking but wrong rival list — and a
wrong rival list makes the whole audit moot. This module fetches the
store's own homepage once and distills it into the few lines a model
needs to place the brand: what the page calls itself, what it says it
sells, and a handful of product names off its own markup.

read_site_context() never raises, for the same reason generate_
competitors() doesn't (rule 4's never-throw philosophy): grounding is
an enrichment, not a precondition. No URL, a blocked store, a challenge
page, a timeout, garbage HTML — every one of them returns None and the
caller falls back to today's name-only prompt, with the reason logged.

Cost: exactly one homepage GET, through scan/fetcher.py::fetch, so the
SSRF guard, the redirect re-validation, the politeness delay, and the
declared ParleoAuditBot identity all apply unchanged. robot_parser=None
mirrors the scan's own homepage fetch (discovery.py::resolve_canonical_
origin) — the homepage is the URL the visitor handed us, and robots.txt
hasn't been read at that point in the scan either; fetching it here
would double this module's request count for a page we were pointed at
directly.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup

from .engine import _normalize_input
from .fetcher import fetch
from .structured_data import extract

log = logging.getLogger(__name__)

# Every extracted string is a prompt input, not a stored fact: long
# enough to carry a real tagline or description, short enough that a
# keyword-stuffed <title> can't crowd out the selection rules below it.
MAX_FIELD_LENGTH = 200
MAX_PRODUCT_NAMES = 8


def _clean(value: Optional[str]) -> Optional[str]:
    """Collapses whitespace, caps length, and turns an empty result into
    None — so every field on SiteContext is either real text or absent,
    never a stray '' that as_prompt_block would render as a blank label."""
    if not isinstance(value, str):
        return None
    collapsed = " ".join(value.split())
    if not collapsed:
        return None
    return collapsed[:MAX_FIELD_LENGTH]


@dataclass
class SiteContext:
    title: Optional[str] = None
    meta_description: Optional[str] = None
    og_site_name: Optional[str] = None
    h1: Optional[str] = None
    product_names: list = field(default_factory=list)  # list[str], max MAX_PRODUCT_NAMES
    jsonld_brand: Optional[str] = None
    final_url: Optional[str] = None

    def as_prompt_block(self) -> str:
        """Renders the populated fields as short labelled lines.

        final_url is rendered as the block's own first line rather than
        being passed to the prompt builder separately: the builder takes
        a plain string precisely so the apps/api copy needs no import of
        this dataclass (see competitor_generator.py's module docstring),
        and the model should still see which page these lines came from.
        """
        lines = []
        if self.final_url:
            lines.append(f"Homepage: {self.final_url}")
        if self.title:
            lines.append(f"Page title: {self.title}")
        if self.og_site_name:
            lines.append(f"Site name: {self.og_site_name}")
        if self.meta_description:
            lines.append(f"Site description: {self.meta_description}")
        if self.h1:
            lines.append(f"Main heading: {self.h1}")
        if self.jsonld_brand:
            lines.append(f"Brand named in its product markup: {self.jsonld_brand}")
        if self.product_names:
            lines.append(f"Products listed on the page: {', '.join(self.product_names)}")
        return "\n".join(lines)


def _meta_content(soup, attr: str, name: str) -> Optional[str]:
    """Case-insensitive meta lookup — `<meta NAME="Description">` is
    valid HTML and appears in the wild often enough to matter."""
    tag = soup.find("meta", attrs={attr: re.compile(rf"^{re.escape(name)}$", re.I)})
    if tag is None:
        return None
    return _clean(tag.get("content"))


def _product_facts(html: str) -> tuple:
    """Product names and the brand its own markup declares, read through
    structured_data.py::extract — the scan's single JSON-LD parser, so a
    markup shape that module learns to see (nested variants, ProductGroup)
    is visible here too, and no second JSON-LD reader can drift from it."""
    extracted = extract(html)

    names = []
    brand = None
    for product in extracted.products:
        if brand is None:
            brand = _clean(product.brand)
        name = _clean(product.name)
        if name and name not in names:
            names.append(name)
        if len(names) >= MAX_PRODUCT_NAMES:
            break
    return names, brand


def read_site_context(store_url: Optional[str]) -> Optional[SiteContext]:
    """
    Fetches store_url's homepage once and distills what the site says
    about itself. Returns None — never raises — when there is no URL,
    when the fetch came back anything other than 'fetched' (blocked,
    challenge page, 404, timeout), when the page had no HTML, or when
    nothing usable survived parsing. Every one of those is a caller's
    cue to fall back to the name-only prompt, not an error to handle.
    """
    if not store_url:
        return None

    try:
        origin = _normalize_input(store_url)
        if origin is None:
            log.warning(f"[site-context] could not parse a usable URL from {store_url!r}")
            return None

        result = fetch(origin, robot_parser=None, check_short_body=True)
        if result.status != "fetched" or not result.html:
            log.warning(
                f"[site-context] no usable homepage for {origin}: "
                f"status={result.status} error={result.error!r}"
            )
            return None

        soup = BeautifulSoup(result.html, "html.parser")

        h1_tag = soup.find("h1")
        product_names, jsonld_brand = _product_facts(result.html)

        context = SiteContext(
            title=_clean(soup.title.get_text() if soup.title else None),
            meta_description=(
                _meta_content(soup, "name", "description")
                or _meta_content(soup, "property", "og:description")
            ),
            og_site_name=_meta_content(soup, "property", "og:site_name"),
            h1=_clean(h1_tag.get_text() if h1_tag else None),
            product_names=product_names,
            jsonld_brand=jsonld_brand,
            final_url=result.final_url or result.url,
        )

        # final_url is deliberately not part of this check: it's always
        # populated on a successful fetch, so counting it would mean
        # never returning None for a page we learned nothing from.
        if not any((
            context.title, context.meta_description, context.og_site_name,
            context.h1, context.product_names, context.jsonld_brand,
        )):
            log.warning(f"[site-context] homepage at {origin} yielded no usable fields")
            return None

        return context
    except Exception:
        log.warning(f"[site-context] failed to read site context for {store_url!r}", exc_info=True)
        return None
