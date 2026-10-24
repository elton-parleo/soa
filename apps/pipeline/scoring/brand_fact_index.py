"""
2O-3: what the brand published, as an index a claim's facts are looked up in.

The brand-claim verdict used to be the classifier's reading of a model's
labels: an asserted sentence with no source was `fabricated`, whatever it
said. On FL14 two consecutive re-scores moved 66 of 258 brand-direct answers
between grounded, fabricated and echoed, because which sentences the
labeller called asserted claims, and whether the transcription found a
cited domain, moved from call to call. The price check never had that
problem: the model transcribes a number and the verdict is a comparison.

This is the comparison for brand claims. Built once per cycle from what the
cycle read, normalised, and never from a model:

  record      supply's merchant record and catalog snapshot
              (expectation_scorer.BrandFactsCache): product and variant
              titles, sizes, counts, list and member prices, the feed's
              weight ranges, variant attributes (a true flag is its key, a
              text value is itself), a listing's features / bullets /
              description when supply serves them, the loyalty programme
              and its tier names, the own domains and the retailer list.
  page reads  the cycle's cached retailer-prices rows (soa_cycles.
              reference_prices, read once per cycle): each page's title,
              price, member price and list price, the size chart's weight
              range (`weight_range`, `attribute.truth`), and, when a row
              carries them, its `bullets`, `description`, `json_ld` (name,
              description, size, additionalProperty) and `size_chart`.

A fact is one of seven types, each with its own lookup:

  price      a money amount: on the index when a read or record price is
             within half a cent, or the claim is whole-dollar within fifty
             cents of one (the catalog tier's rule 1)
  unit_price a per-diaper / per-count amount: within two cents of a page's
             price over its count
  count      a pack count: a variant's count, or a count a title states
  size       a size (Size 3, Newborn): a variant's size, or a title's
  weight     a weight range or bound: within a pound of a range the record
             or a size chart states (attribute_accuracy's tolerance)
  name       a product or line name written as the brand's ("Pampers Pure
             Protection"): every word of it in one title the cycle read
  retailer   a store: on the retailer list, or one of the brand's own sites
  attribute  a word from ATTRIBUTE_TERMS: in the record's or the pages' text

A type the cycle read nothing of (no page text at all, so no attribute word
could be on it) is `unchecked`, never `missing`: an index that holds no
bullets cannot say a bullet was invented. The verdict reports it apart
(brand_claim_verdict, reason fact_type_not_read).

No model, no network: the record and the payload are handed in.
"""
import hashlib
import json
import re
from typing import Iterable, List, Optional

from soa_shared import attribute_accuracy as aa
from soa_shared import expected_answers as ea
from soa_shared.retailers import retailers_named

#: The index's own version. Bumped when what goes into it, or how a fact is
#: looked up, changes; stored on every outcome beside the index's digest.
INDEX_VERSION = 1

FACT_TYPES = ('price', 'unit_price', 'count', 'size', 'weight', 'name', 'retailer', 'attribute')

#: Checkable attribute words: what a brand's page states and a reader could
#: check against it. Closed and written out; a word not here is not a fact
#: the verdict looks up (it is no evidence either way). Matched as phrases,
#: a space or hyphen between words either way.
ATTRIBUTE_TERMS = (
    'fragrance free', 'unscented', 'scented', 'fragrance', 'perfume free',
    'hypoallergenic', 'latex free', 'chlorine free', 'elemental chlorine free', 'paraben free',
    'phthalate free', 'lotion free', 'lotion', 'aloe', 'shea butter', 'petrolatum', 'vitamin e',
    'plant based', 'organic', 'cotton', 'bamboo', 'dermatologist tested', 'dermatologist approved',
    'dermatologist recommended', 'pediatrician recommended', 'hospital', 'hospitals',
    'wetness indicator', 'umbilical cord notch', 'cord notch', 'breathable', 'stretchy sides',
    'stretchy waistband', 'tear away sides', 'tear-away sides', 'refastenable', 'leak guard',
    'leakguard', 'blowout', 'blowout barrier', 'overnight', 'overnight protection', 'extra absorb channels',
    'absorb away liner', 'air channels', 'heart quilts', 'pocketed back waistband', 'sleep and play',
    'swim', 'tsa', 'eu ecolabel', 'number one', '#1', 'best selling', 'award winning',
)
_SMALL = {'a', 'an', 'and', 'the', 'of', 'for', 'with', 'to', 'in', 'on', 'at', 'by', 'or', 'is', 'are'}
#: words a product title carries that name no line ("Pampers Swaddlers Diapers Size 1, 96 Count")
GENERIC = {'diaper', 'diapers', 'nappy', 'nappies', 'pants', 'pant', 'wipes', 'wipe', 'baby', 'babies', 'size',
           'sizes', 'count', 'ct', 'pack', 'packs', 'box', 'case', 'month', 'supply', 'super', 'giant', 'mega',
           'enormous', 'jumbo', 'one', 'value', 'disposable', 'premium', 'new', 'newborn', 'preemie', 'nb',
           'line', 'brand', 'range'}

_WORD = re.compile(r"[a-z0-9#]+(?:'[a-z]+)?")
_MONEY = re.compile(r"\$\s?(\d{1,4}(?:,\d{3})*(?:\.\d{1,2})?)")
_UNIT = re.compile(r"\$\s?(\d{1,2}(?:\.\d{1,2})?)\s*(?:/|per|a|an|each)\s*(?:diaper|wipe|count|unit|pant)s?\b"
                   r"|\b(\d{1,2}(?:\.\d)?)\s*(?:¢|cents?)\s*(?:/|per|a|an|each)\s*(?:diaper|wipe|count|unit|pant)s?\b",
                   re.I)
_COUNT = re.compile(r"\b(\d{2,4})\s*(?:-\s*)?(?:ct|count|pack|pk|diapers|wipes|pants|pieces|pcs)\b", re.I)
_PACK_OF = re.compile(r"\bpacks?\s+of\s+(\d{2,4})\b", re.I)
_SIZE_RANGE = re.compile(r"\bsizes?\s*(newborn|preemie|nb|p|\d{1,2})\s*(?:-|–|to|through|thru)\s*(?:size\s*)?(\d{1,2})\b",
                         re.I)
_SIZE_ONE = re.compile(r"\bsize\s*[:#]?\s*(newborn|preemie|nb|p|\d{1,2})\b|\b(newborn|preemie)\s+size\b", re.I)
_TITLE_SIZE = re.compile(r"\b(?:s(\d{1,2})|size\s*(\d{1,2}|newborn|nb|preemie|p)|(nb))\b", re.I)
_TITLE_COUNT = re.compile(r"\b(?:s\d{1,2}|nb|size\s*\w+)\s*,?\s+(\d{2,4})\b|\b(\d{2,4})\s*(?:ct|count|pack)\b", re.I)
_HOURS = re.compile(r"\b(?:up\s+to\s+)?(\d{1,2})\s*(?:-\s*)?hours?\b", re.I)
_SIZE_ALIAS = {'newborn': '0', 'nb': '0', 'n': '0', 'preemie': 'p', 'p': 'p'}


def norm(text) -> str:
    """Lower-case words joined by single spaces; hyphens and slashes are spaces, & is and."""
    text = aa.normalize(str(text or '')).lower().replace('&', ' and ').replace('’', "'")
    text = re.sub(r"[-/_]", ' ', text)
    return ' '.join(_WORD.findall(text))


def tokens(text) -> List[str]:
    return [t[:-2] if t.endswith("'s") else t for t in norm(text).split()]


def stem(token: str) -> str:
    return token[:-1] if len(token) > 3 and token.endswith('s') and not token.endswith('ss') else token


def _size(value) -> Optional[str]:
    value = str(value or '').strip().lower()
    return _SIZE_ALIAS.get(value, value) if value else None


def _money(value) -> Optional[str]:
    return ea.normalize_money(value)


def _range(value) -> Optional[dict]:
    if isinstance(value, dict) and (value.get('min') is not None or value.get('max') is not None):
        def f(v):
            try:
                return None if v is None else float(v)
            except (TypeError, ValueError):
                return None
        return {'min': f(value.get('min')), 'max': f(value.get('max'))}
    return None


def term_pattern(term: str) -> re.Pattern:
    body = r"[\s\-]*".join(re.escape(t) for t in re.split(r"[\s\-]+", term) if t)
    head = r"(?<![a-z0-9])" if term[:1].isalnum() else ''
    return re.compile(head + body + r"(?![a-z0-9])", re.I)


_TERMS = [(t, term_pattern(t)) for t in sorted(ATTRIBUTE_TERMS, key=lambda t: -len(t))]


def attribute_terms(text) -> List[str]:
    """The ATTRIBUTE_TERMS a text states, longest first, a shorter term inside a longer one left out
    ("fragrance" in "fragrance free")."""
    flat = aa.normalize(str(text or '')).lower()
    found, taken = [], []
    for term, rx in _TERMS:
        for m in rx.finditer(flat):
            if any(s <= m.start() and m.end() <= e for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            if term not in found:
                found.append(term)
    return found


# ─── The index ─────────────────────────────────────────────────────────────

def _json_ld_texts(value) -> List[str]:
    out = []
    items = value if isinstance(value, list) else [value]
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in ('name', 'description', 'size', 'material', 'color'):
            if isinstance(item.get(key), str):
                out.append(item[key])
        for prop in item.get('additionalProperty') or []:
            if isinstance(prop, dict):
                out.append(f"{prop.get('name') or ''} {prop.get('value') or ''}")
    return out


class FactIndex:
    """What the brand published, normalised. See the module docstring."""

    def __init__(self) -> None:
        self.brand: Optional[str] = None
        self.domain: Optional[str] = None
        self.prices: set = set()
        self.unit_prices: set = set()
        self.counts: set = set()
        self.sizes: set = set()
        self.weights: List[dict] = []
        self.titles: List[str] = []          # normalised, each once
        self.retailers: set = set()
        self.text: List[str] = []            # page and record text, normalised
        self.attributes: set = set()         # ATTRIBUTE_TERMS the text states
        self.page_text = False               # any text beyond titles was read

    # ── what was read ──
    def types_read(self) -> List[str]:
        read = {'price': bool(self.prices), 'unit_price': bool(self.unit_prices), 'count': bool(self.counts),
                'size': bool(self.sizes), 'weight': bool(self.weights), 'name': bool(self.titles),
                'retailer': bool(self.retailers), 'attribute': self.page_text}
        return [t for t in FACT_TYPES if read[t]]

    def size(self) -> int:
        return (len(self.prices) + len(self.unit_prices) + len(self.counts) + len(self.sizes) + len(self.weights)
                + len(self.titles) + len(self.retailers) + len(self.attributes))

    def as_dict(self) -> dict:
        return {'prices': sorted(self.prices), 'unit_prices': sorted(self.unit_prices),
                'counts': sorted(self.counts, key=int), 'sizes': sorted(self.sizes),
                'weights': sorted(self.weights, key=lambda r: (r['min'] or 0, r['max'] or 0)),
                'titles': sorted(self.titles), 'retailers': sorted(self.retailers),
                'attributes': sorted(self.attributes), 'page_text': self.page_text}

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.as_dict(), sort_keys=True).encode()).hexdigest()[:12]

    def stamp(self) -> dict:
        """What an outcome stores about the index it was judged against."""
        return {'version': INDEX_VERSION, 'digest': self.digest(), 'size': self.size(),
                'types_read': self.types_read()}

    # ── building ──
    def add_title(self, title) -> None:
        if not title:
            return
        t = norm(title)
        if t and t not in self.titles:
            self.titles.append(t)
            self.add_text(title, page=False)
        for m in _TITLE_SIZE.finditer(str(title)):
            self.sizes.add(_size(m.group(1) or m.group(2) or m.group(3)))
        for m in _TITLE_COUNT.finditer(str(title)):
            self.counts.add(str(int(m.group(1) or m.group(2))))

    def add_text(self, text, *, page=True) -> None:
        if not text or not str(text).strip():
            return
        self.text.append(norm(text))
        self.attributes.update(attribute_terms(text))
        for rng, _s, _e in aa.parse_ranges(text):
            if rng not in self.weights:
                self.weights.append(rng)
        if page:
            self.page_text = True

    def add_weight(self, value) -> None:
        rng = _range(value)
        if rng and rng not in self.weights:
            self.weights.append(rng)

    def add_variant(self, title=None, size=None, count=None, prices=(), weight=None, attributes=None) -> None:
        self.add_title(title)
        if size:
            for m in _TITLE_SIZE.finditer(f"size {size}"):
                self.sizes.add(_size(m.group(1) or m.group(2) or m.group(3)))
        if count:
            try:
                self.counts.add(str(int(count)))
            except (TypeError, ValueError):
                pass
        for p in prices:
            if _money(p):
                self.prices.add(_money(p))
        self.add_weight(weight)
        for key, value in (attributes or {}).items():
            values = value if isinstance(value, list) else [value]
            for item in values:
                if item is True:
                    self.add_text(str(key).replace('_', ' '))
                elif isinstance(item, str) and item.strip():
                    self.add_text(f"{str(key).replace('_', ' ')} {item}")

    def add_unit_price(self, price, count) -> None:
        try:
            amount, n = float(_money(price)), int(count)
        except (TypeError, ValueError):
            return
        if n > 0:
            self.unit_prices.add(f"{amount / n:.2f}")


def build(facts: Optional[dict], reference: Optional[dict] = None) -> FactIndex:
    """
    The cycle's index: `facts` is BrandFactsCache.for_merchant()'s dict (the
    record and catalog snapshot, plus tenant_own_domains when the scorer
    read it); `reference` the cycle's cached retailer-prices payload (rows
    under `prices`), or None. Deterministic: the same inputs give the same
    index, and the same digest.
    """
    facts = facts or {}
    index = FactIndex()
    index.brand = facts.get('brand')
    index.domain = ea.normalize_domain(facts.get('domain')) or None
    for title in facts.get('product_titles') or []:
        index.add_title(title)
    for v in facts.get('variants') or []:
        if not isinstance(v, dict):
            continue
        index.add_variant(v.get('title'), v.get('size'), v.get('count'),
                          (v.get('list_price'), v.get('member_price')), v.get('weight_range'), v.get('attributes'))
    for text in list(facts.get('features') or []) + list(facts.get('descriptions') or []):
        index.add_text(text)
    for name in [facts.get('program_name')] + list(facts.get('tier_names') or []):
        if name:
            index.add_text(name, page=False)
    for d in list(facts.get('own_domains') or []) + list(facts.get('tenant_own_domains') or []) \
            + [facts.get('domain')] + list(facts.get('retailer_list') or []):
        if ea.normalize_domain(d):
            index.retailers.add(ea.normalize_domain(d))

    rows = [r for r in ((reference or {}).get('prices') or (reference or {}).get('rows') or []) if isinstance(r, dict)]
    for row in rows:
        if row.get('role') == 'comparison':
            continue   # another brand's page, read for context (2A-4), is never this brand's record
        domain = ea.normalize_domain(row.get('retailer_domain'))
        if domain and row.get('role') in (None, 'retailer', 'own'):
            index.retailers.add(domain)
        for key in ('page_title', 'title', 'name'):
            index.add_title(row.get(key))
        index.add_title(row.get('variant_label'))
        prices = [row.get(k) for k in ('price', 'member_price', 'list_price')]
        for p in prices:
            if _money(p):
                index.prices.add(_money(p))
        count = next((m.group(1) or m.group(2) for t in (row.get('page_title'), row.get('title'), row.get('variant_label'))
                      for m in _TITLE_COUNT.finditer(str(t or ''))), None)
        if count and _money(row.get('price')):
            index.add_unit_price(row['price'], count)
        index.add_weight(row.get('weight_range'))
        index.add_weight((row.get('attribute') or {}).get('truth'))
        for chart in row.get('size_chart') or []:
            if isinstance(chart, dict):
                index.add_weight(chart)
                if chart.get('size'):
                    index.sizes.add(_size(chart['size']) if str(chart['size']).isalpha() else
                                    next((_size(m.group(1) or m.group(2) or m.group(3))
                                          for m in _TITLE_SIZE.finditer(f"size {chart['size']}")), None))
        for bullet in row.get('bullets') or []:
            index.add_text(bullet)
        index.add_text(row.get('description'))
        for text in _json_ld_texts(row.get('json_ld')):
            index.add_text(text)
    index.sizes.discard(None)
    return index


# ─── The facts a span states ───────────────────────────────────────────────

def _fact(kind, text, value=None) -> dict:
    out = {'type': kind, 'text': text}
    if value is not None:
        out['value'] = value
    return out


def brand_names(text, brand) -> List[dict]:
    """
    Product or line names the text writes as the brand's: the words that
    follow the brand's name ("Pampers Pure Protection", "Pampers' Swaddlers
    Overnights") while each is capitalised or a number, stopping at a GENERIC
    word or punctuation. [{'type': 'name', 'text': 'Pure Protection',
    'value': ['pure', 'protection']}].
    """
    brand_tokens = tokens(brand)
    if not brand_tokens:
        return []
    out = []
    raw = aa.normalize(str(text or ''))
    words = list(re.finditer(r"[A-Za-z0-9®™&'’+-]+|[^\sA-Za-z0-9]", raw))
    plain = [re.sub(r"[®™]|['’]s?$", '', w.group(0)) for w in words]
    lowered = [p.lower() for p in plain]
    n = len(brand_tokens)
    for i in range(len(words) - n + 1):
        if [stem(t) for t in lowered[i:i + n]] != [stem(t) for t in brand_tokens]:
            continue
        name, j = [], i + n
        while j < len(words):
            word = plain[j]
            if not word or not (word[:1].isupper() or word[:1].isdigit()) or word.lower() in GENERIC:
                break
            if word.lower() in _SMALL:
                break
            name.append(word)
            j += 1
        if name:
            label = ' '.join(name)
            value = [t for t in tokens(label) if t not in GENERIC]
            if value and not any(f['text'] == label for f in out):
                out.append(_fact('name', label, value))
    return out


def facts_in(text, brand=None, *, own_domains: Iterable[str] = ()) -> List[dict]:
    """Every checkable fact a span states, in FACT_TYPES order. Deterministic."""
    text = aa.normalize(str(text or ''))
    out = []
    unit_spans = []
    for m in _UNIT.finditer(text):
        unit_spans.append((m.start(), m.end()))
        value = m.group(1) or (f"{float(m.group(2)) / 100:.2f}" if m.group(2) else None)
        out.append(_fact('unit_price', m.group(0).strip(), _money(value)))
    for m in _MONEY.finditer(text):
        if any(s <= m.start() < e for s, e in unit_spans):
            continue
        out.append(_fact('price', m.group(0).strip(), _money(m.group(1).replace(',', ''))))
    for m in list(_COUNT.finditer(text)) + list(_PACK_OF.finditer(text)):
        out.append(_fact('count', m.group(0).strip(), str(int(m.group(1)))))
    sized = []
    for m in _SIZE_RANGE.finditer(text):
        sized.append((m.start(), m.end()))
        out.append(_fact('size', m.group(0).strip(), [_size(m.group(1)), _size(m.group(2))]))
    for m in _SIZE_ONE.finditer(text):
        if any(s <= m.start() < e for s, e in sized):
            continue
        out.append(_fact('size', m.group(0).strip(), [_size(m.group(1) or m.group(2))]))
    for rng, start, end in aa.parse_ranges(text):
        out.append(_fact('weight', text[start:end].strip().rstrip('.'), rng))
    out.extend(brand_names(text, brand))
    own = {ea.normalize_domain(d) for d in own_domains if d}
    for domain in retailers_named(text):
        if domain not in own:
            out.append(_fact('retailer', domain, domain))
    for m in _HOURS.finditer(text):
        out.append(_fact('attribute', m.group(0).strip(), f"{int(m.group(1))} hour"))
    for term in attribute_terms(text):
        written = term_pattern(term).search(text.lower())
        out.append(_fact('attribute', text[written.start():written.end()] if written else term, term))
    seen, unique = set(), []
    for f in out:
        key = (f['type'], json.dumps(f.get('value'), sort_keys=True))
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


# ─── Looking a fact up ─────────────────────────────────────────────────────

FOUND, MISSING, UNCHECKED = 'found', 'missing', 'unchecked'


def _price_on(value, prices) -> bool:
    from scoring import variant_rules as vr
    return any(vr.same_money(value, p) or vr.rounds_to(value, p) for p in prices)


def _found(fact: dict, index: FactIndex) -> bool:
    kind, value = fact['type'], fact.get('value')
    if kind == 'price':
        return bool(value) and _price_on(value, index.prices)
    if kind == 'unit_price':
        return bool(value) and any(abs(float(value) - float(u)) <= 0.02 for u in index.unit_prices)
    if kind == 'count':
        return value in index.counts
    if kind == 'size':
        return all(v in index.sizes for v in value or [])
    if kind == 'weight':
        if value.get('min') is not None and value.get('max') is not None:
            return any(aa.same(value, r) for r in index.weights)
        bound = 'max' if value.get('max') is not None else 'min'
        return any(r.get(bound) is not None and abs(r[bound] - value[bound]) <= aa.TOLERANCE_LB
                   for r in index.weights)
    if kind == 'name':
        want = {stem(t) for t in value or []}
        return any(want <= {stem(t) for t in title.split()} for title in index.titles)
    if kind == 'retailer':
        return value in index.retailers
    if kind == 'attribute':
        if value.endswith(' hour'):
            rx = re.compile(r"(?<![a-z0-9])" + re.escape(value.split()[0]) + r"\s*hours?(?![a-z0-9])")
            return any(rx.search(t) for t in index.text)
        return value in index.attributes or any(term_pattern(value).search(t) for t in index.text)
    return False


def lookup(fact: dict, index: FactIndex) -> str:
    """found | missing | unchecked: not on the index, and the cycle read
    nothing of the fact's type (no page text, so no attribute word could be
    on it; no title stated a count), which is no evidence it was invented."""
    if _found(fact, index):
        return FOUND
    return MISSING if fact['type'] in index.types_read() else UNCHECKED
