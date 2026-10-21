"""
2L-2: a brand's retired product lines and their successors.

Supply's feed may say a SKU is retired and name the SKU that replaced it
(parleo-supply-app docs/truesync/sku-feed.md, "Retired lines"); its catalog
serves both on every variant as `status` and `successor`. A LINE is a
catalog product (one listing: the SKUs sharing brand and product name), and
it is retired when every one of its variants is. Agents keep naming a
retired line long after the brand stopped making it, which is the finding:
Pure named in 10 category answers, AMORE, its successor, in none.

What this module decides, once, for the generator and the read model:

  line      the product name with the brand's name taken off the front:
            "Pampers Pure Protection" -> "Pure Protection"
  label     the line's first word, which is what people call it: "Pure",
            "AMORE". Display only.
  terms     what an answer must contain to have NAMED the line, matched on
            whole words after normalize_brand_text: the product name, the
            line, and the brand with the label ("Pampers Pure"). Never the
            label alone when the line has more than one word: "pure" on its
            own is an adjective ("pure cotton"), not Pampers Pure.

Deterministic: no model reads here, and the same record gives the same lines.
The generator stores retired_lines() in tier_config.merchant.retired, so the
read model counts against the record the questions were written from.
"""
from typing import List, Optional

from soa_shared.expected_answers import normalize_brand_text


def line_name(product_name: Optional[str], brand: Optional[str]) -> str:
    """The product name without the brand in front of it."""
    name = (product_name or '').strip()
    words, prefix = name.split(), (brand or '').split()
    if prefix and len(words) > len(prefix) and \
            [normalize_brand_text(w) for w in words[:len(prefix)]] == [normalize_brand_text(w) for w in prefix]:
        return ' '.join(words[len(prefix):])
    return name


def label(product_name: Optional[str], brand: Optional[str]) -> str:
    line = line_name(product_name, brand)
    return line.split()[0] if line else ''


def terms(product_name: Optional[str], brand: Optional[str]) -> List[str]:
    """The phrases that name the line, most specific first, de-duplicated."""
    line = line_name(product_name, brand)
    out = [product_name or '', line]
    if line and len(line.split()) > 1 and brand:
        out.append(f"{brand} {label(product_name, brand)}")
    seen, kept = set(), []
    for term in out:
        key = normalize_brand_text(term)
        if key and key not in seen:
            seen.add(key)
            kept.append(term.strip())
    return kept


def names(text: Optional[str], line_terms: List[str]) -> bool:
    """Whether `text` names the line: any term as whole words."""
    hay = f" {normalize_brand_text(text or '')} "
    return any(f" {normalize_brand_text(t)} " in hay for t in line_terms if normalize_brand_text(t))


def _line(product_name: Optional[str], brand: Optional[str], **extra) -> dict:
    return {**extra, 'product_name': product_name, 'line': line_name(product_name, brand),
            'label': label(product_name, brand), 'terms': terms(product_name, brand)}


def retired_lines(snapshot) -> List[dict]:
    """
    One entry per retired line, in catalog order:

      {listing_id, variant_ids, product_name, line, label, terms,
       successor: {variant_id, sku, product_name, line, label, terms} | None}

    The successor is the first one a variant of the line names; a line whose
    variants name none is the last of its kind, and still a retired line.
    """
    if snapshot is None or not getattr(snapshot, 'available', False):
        return []
    brand = getattr(snapshot, 'study_brand', None) or snapshot.brand
    out = []
    for product in snapshot.products:
        variants = list(product.variants)
        if not variants or any((v.status or 'active') != 'retired' for v in variants):
            continue
        successor = next((v.successor for v in variants if v.successor), None)
        out.append(_line(
            product.title, brand, listing_id=product.listing_id,
            variant_ids=[v.variant_id for v in variants],
            successor=_line(successor.get('product_name') or successor.get('title'), brand,
                            variant_id=successor.get('variant_id'), sku=successor.get('sku'))
            if successor else None,
        ))
    return out


def question_text(line: dict, brand: Optional[str] = None) -> str:
    """The brand-direct question the generator asks about a retired line. It
    names the brand, as every brand-direct question must: the product name
    when that starts with it ("Pampers Pure Protection"), else the brand in
    front ("Wiggle & Snug Snug-Fit Overnight Diapers")."""
    name = line['product_name']
    if brand and line.get('line') == name:
        name = f"{brand} {name}"
    if line.get('successor'):
        return f"Is {name} still sold, and what replaced it?"
    return f"Is {name} still sold?"
