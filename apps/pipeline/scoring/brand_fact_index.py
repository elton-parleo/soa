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

2O-5: "fabricated" means contradicted by what the brand publishes, and the
index covers the line, not the pilot. Version 1 held the pilot's facts (10
SKUs, the pages read for them), so any claim naming a size, count, line or
store beyond the pilot was `missing`, and missing was fabricated: on FL14 170
of 258, "by the fact missing: price 60, retailer 48, name 48, size 26, count
21, attribute 58". Version 2 adds SLOTS, each with the value the brand states:

  lines      the brand's lines, complete only when the payload serves the
             brand's own line list (`brand_lines`); the pilot's titles are
             never all of them
  sizes      per line, the sizes it comes in: complete from a brand page's
             JSON-LD (`hasVariant` sizes, the "Size Range" property) or its
             size chart; the feed's variants are a sample, never complete
  counts     per line, the pack counts: complete from the page's hasVariant
             counts or its "Pack Count" property (pampers.com states counts
             per line, not per size)
  ranges     per (line, size), every weight range the brand states for it:
             the feed's variant range, the page's chart, the hasVariant
             variant's own description, and a retailer row's brand truth
             (`attribute.truth`, the chart 2M-1 reads). Never the line's
             "Baby Weight" property, a list aligned with "Size Range" by
             position, which 2M-1 found disagrees with the chart
  status     per line, current or retired: the feed's variant status (a line
             whose variants are all retired is retired, its successor the
             feed's), and a brand page that redirected (`url` != `final_url`)
             to another line's page
  attributes per line, the attribute words the line's own page (bullets,
             description, JSON-LD) or its feed variants state, negations
             included: "free of parabens and latex" puts paraben free and
             latex free on it, and OPPOSITES says a claim of "scented"
             about the line contradicts its fragrance free

check() looks a fact up against them: found, contradicted (the slot holds a
value and the claim's differs), or unverified (absent, nothing contradicts
it). A price or unit price is always unverified here (the price tier judges
prices); a store off the merchant's list is unverified (coverage judges it).
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
INDEX_VERSION = 2

FACT_TYPES = ('price', 'unit_price', 'count', 'size', 'weight', 'name', 'retailer', 'attribute', 'status')

#: Checkable attribute words: what a brand's page states and a reader could
#: check against it. Closed and written out; a word not here is not a fact
#: the verdict looks up (it is no evidence either way). Matched as phrases,
#: a space or hyphen between words either way. A word ordinary prose uses
#: for something else stays out ("overnight": "works well overnight" is no
#: claim about overnight protection; "blowout" alone, "soft").
ATTRIBUTE_TERMS = (
    'fragrance free', 'unscented', 'scented', 'fragrance', 'perfume free',
    'hypoallergenic', 'latex free', 'chlorine free', 'elemental chlorine free', 'paraben free',
    'phthalate free', 'lotion free', 'lotion', 'aloe', 'shea butter', 'petrolatum', 'vitamin e',
    'plant based', 'organic', 'cotton', 'bamboo', 'dermatologist tested', 'dermatologist approved',
    'dermatologist recommended', 'pediatrician recommended', 'hospital', 'hospitals',
    'wetness indicator', 'umbilical cord notch', 'cord notch', 'breathable', 'stretchy sides',
    'stretchy waistband', 'tear away sides', 'tear-away sides', 'refastenable', 'leak guard',
    'leakguard', 'blowout barrier', 'overnight protection', 'extra absorb channels',
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

#: 2O-5: an attribute word and the words a page states for its opposite.
#: A claim of the key is contradicted when the index holds one of its
#: opposites and not the key itself ("lightly scented" against a page that
#: says fragrance free).
OPPOSITES = {
    'scented': ('fragrance free', 'unscented', 'perfume free'),
    'fragrance': ('fragrance free', 'unscented', 'perfume free'),
    'fragrance free': ('scented',), 'unscented': ('scented',), 'perfume free': ('scented',),
    'lotion': ('lotion free',), 'lotion free': ('lotion',),
}
#: A word a page or a claim says is absent ("free of parabens", "no lotion",
#: "without fragrance") and the ATTRIBUTE_TERMS term that says so.
_NEGATED = re.compile(r"\b(?:free\s+(?:of|from)|no|without|zero|0%)\s+"
                      r"((?:[a-z]+(?:\s*,\s*|\s+(?:and|or|nor)\s+)?){1,6})", re.I)
#: 2O-5: a line's status, as a claim states it.
_RETIRED = re.compile(r"\b(?:(?<!not )(?<!not been )(?<!n't been )(?<!never been )discontinued|"
                      r"no longer (?:made|sold|available|produced|manufactured|in production)|phased out|retired)\b",
                      re.I)
_CURRENT = re.compile(r"\b(?:still (?:available|sold|made|produced|in production|on (?:the )?shelves)|currently "
                      r"(?:available|sold|made)|(?:not|not been|n't been|never been) discontinued)\b", re.I)
#: words a page title or JSON-LD name carries after the line's ("Cruisers 360 Pull-on")
LINE_NOISE = {'pull', 'on', 'pull-on', 'taped', 'pampers'}


def negated_terms(text) -> List[str]:
    """The `<word> free` ATTRIBUTE_TERMS a text states by negating the word:
    "free of parabens and latex" -> paraben free, latex free."""
    out = []
    for m in _NEGATED.finditer(aa.normalize(str(text or '')).lower()):
        for word in re.split(r"[\s,]+", m.group(1)):
            word = stem(word)
            if word in ('and', 'or', 'nor', ''):
                continue
            term = f"{word} free"
            if term in ATTRIBUTE_TERMS and term not in out:
                out.append(term)
    return out


def line_key(name, brand=None, *, title=True) -> Optional[str]:
    """A line's key, the same however a title, a page or a claim writes it:
    the line line_name() reads, its words stemmed, LINE_NOISE and GENERIC
    words out ("Pampers® Cruisers 360° Pull-on Diapers | Pampers" ->
    "cruiser 360", "Swaddlers" -> "swaddler")."""
    from scoring.brand_claim_selector import line_name   # late: the selector imports this module
    text = str(name or '').split('|')[0]
    brand_tokens = {stem(t) for t in tokens(brand)}
    # a title or a page's name is read for its line; a name a claim or the
    # served line list writes is the line already ("Cruisers 360": a title's
    # trailing number is its pack count)
    line = line_name(text, brand) if brand and title else text
    words = [stem(t) for t in tokens(line or text)
             if t not in GENERIC and t not in LINE_NOISE and stem(t) not in brand_tokens]
    return ' '.join(words) or None


def line_label(name, brand=None) -> Optional[str]:
    """A line's name for people: the line line_name() reads, LINE_NOISE out ("Cruisers 360")."""
    from scoring.brand_claim_selector import line_name
    line = line_name(str(name or '').split('|')[0], brand) if brand else str(name or '')
    return ' '.join(w for w in str(line or '').split() if w.lower() not in LINE_NOISE) or None


def _size_of(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in _SIZE_ALIAS or text.isdigit():
        return _size(text)
    m = next(_TITLE_SIZE.finditer(text if text.lower().startswith('size') else f"size {text}"), None)
    return _size(m.group(1) or m.group(2) or m.group(3)) if m else None


def _first_range(text) -> Optional[dict]:
    found = aa.parse_ranges(text)
    return found[0][0] if found else None


def _split_list(value) -> List[str]:
    return [p.strip() for p in str(value or '').split(',') if p.strip()]


class Line:
    """2O-5: what the brand states about one of its lines. See the module docstring."""

    def __init__(self, key: str, name: str) -> None:
        self.key, self.name = key, name
        self.sizes: set = set()
        self.sizes_complete = False
        self.counts: set = set()
        self.counts_complete = False
        self.ranges: dict = {}               # size -> [range, ...]
        self.range_sources: dict = {}        # size -> {'chart', 'page', 'feed'}
        self.status: Optional[str] = None    # current | retired
        self.successor: Optional[str] = None
        self.gtins: set = set()
        self.attributes: set = set()         # the ATTRIBUTE_TERMS this line's own pages or variants state
        self.sources: set = set()

    def add_text(self, text) -> None:
        self.attributes.update(attribute_terms(text))
        self.attributes.update(negated_terms(text))

    def add_range(self, size, rng, source='chart') -> None:
        rng = _range(rng)
        if size and rng:
            if rng not in self.ranges.setdefault(size, []):
                self.ranges[size].append(rng)
            self.range_sources.setdefault(size, set()).add(source)

    def facts(self) -> int:
        return (len(self.sizes) + len(self.counts) + sum(len(r) for r in self.ranges.values())
                + len(self.attributes) + (1 if self.status else 0))

    def as_dict(self) -> dict:
        return {'name': self.name, 'sizes': sorted(self.sizes), 'sizes_complete': self.sizes_complete,
                'counts': sorted(self.counts, key=int), 'counts_complete': self.counts_complete,
                'ranges': {k: sorted(v, key=lambda r: (r['min'] or 0, r['max'] or 0))
                           for k, v in sorted(self.ranges.items())},
                'range_sources': {k: sorted(v) for k, v in sorted(self.range_sources.items())},
                'status': self.status, 'successor': self.successor, 'gtins': sorted(self.gtins),
                'attributes': sorted(self.attributes)}


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
        #: 2O-5: the slots (module docstring): per line, and the brand's line list when served
        self.lines: dict = {}                # line_key -> Line
        self.brand_lines: Optional[List[str]] = None
        #: 2O-4: the facts each source put on the index first (build's three passes)
        self.by_source = {'record': 0, 'catalog': 0, 'brand_pages': 0}

    # ── what was read ──
    def types_read(self) -> List[str]:
        read = {'price': bool(self.prices), 'unit_price': bool(self.unit_prices), 'count': bool(self.counts),
                'size': bool(self.sizes), 'weight': bool(self.weights), 'name': bool(self.titles),
                'retailer': bool(self.retailers), 'attribute': self.page_text,
                'status': any(l.status for l in self.lines.values())}
        return [t for t in FACT_TYPES if read[t]]

    def size(self) -> int:
        return (len(self.prices) + len(self.unit_prices) + len(self.counts) + len(self.sizes) + len(self.weights)
                + len(self.titles) + len(self.retailers) + len(self.attributes)
                + sum(l.facts() for l in self.lines.values()) + len(self.brand_lines or []))

    def slots(self) -> dict:
        """2O-5: the slots filled, for the printout: lines (and how many have a
        status), and per line its sizes, counts and ranges (by size)."""
        lines = sorted(self.lines.values(), key=lambda l: l.key)
        return {'lines': len(lines), 'brand_lines': len(self.brand_lines) if self.brand_lines is not None else None,
                'status': sum(1 for l in lines if l.status),
                'retired': sorted(l.name for l in lines if l.status == 'retired'),
                'sizes': {l.name: len(l.sizes) for l in lines if l.sizes},
                'sizes_complete': sorted(l.name for l in lines if l.sizes_complete),
                'counts': {l.name: len(l.counts) for l in lines if l.counts},
                'counts_complete': sorted(l.name for l in lines if l.counts_complete),
                'ranges': {l.name: len(l.ranges) for l in lines if l.ranges},
                'ranges_per_size': {size_label(k): sum(1 for l in lines if l.ranges.get(k))
                                    for k in _size_order({k for l in lines for k in l.ranges})},
                'attributes': {l.name: len(l.attributes) for l in lines if l.attributes}}

    def as_dict(self) -> dict:
        return {'prices': sorted(self.prices), 'unit_prices': sorted(self.unit_prices),
                'counts': sorted(self.counts, key=int), 'sizes': sorted(self.sizes),
                'weights': sorted(self.weights, key=lambda r: (r['min'] or 0, r['max'] or 0)),
                'titles': sorted(self.titles), 'retailers': sorted(self.retailers),
                'attributes': sorted(self.attributes), 'page_text': self.page_text,
                'lines': {k: self.lines[k].as_dict() for k in sorted(self.lines)},
                'brand_lines': sorted(self.brand_lines) if self.brand_lines is not None else None}

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.as_dict(), sort_keys=True).encode()).hexdigest()[:12]

    def stamp(self) -> dict:
        """What an outcome stores about the index it was judged against."""
        return {'version': INDEX_VERSION, 'digest': self.digest(), 'size': self.size(),
                'types_read': self.types_read(), 'by_source': dict(self.by_source), 'slots': self.slots()}

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
        self.attributes.update(negated_terms(text))
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

    # ── 2O-5: the slots ──
    def line(self, name, *, create=True, title=True) -> Optional[Line]:
        """The index's Line for a name, made when `create` and not there yet.
        A title is read for its line, and a number after the line's words can
        be its count ("Cruisers 360 Diapers"): the longest line already known
        that extends what was read, its words in the title in order, wins."""
        key = line_key(name, self.brand, title=title)
        if key and title:
            written = ' '.join(stem(t) for t in tokens(str(name).split('|')[0]))
            longer = [k for k in self.lines if k != key and k.startswith(key + ' ')
                      and re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", written)]
            if longer:
                key = max(longer, key=len)
        if key and key not in self.lines and create:
            self.lines[key] = Line(key, (line_label(name, self.brand) if title else str(name).strip()) or key)
        return self.lines.get(key) if key else None

    def find_line(self, name) -> Optional[Line]:
        """The index's line a claim's name means: the same key, else the one
        line whose words hold every word of the name with fewest left over
        ("Cruisers 360" -> "cruiser 360 ..."); None when that is two lines."""
        key = line_key(name, self.brand, title=False)
        if not key:
            return None
        if key in self.lines:
            return self.lines[key]
        want = set(key.split())
        holds = sorted(((len(set(k.split()) - want), k) for k in self.lines if want <= set(k.split())))
        if not holds or (len(holds) > 1 and holds[0][0] == holds[1][0]):
            return None
        return self.lines[holds[0][1]]

    def add_page(self, row: dict, *, line_hint=None) -> None:
        """A brand page's JSON-LD (the ProductGroup: hasVariant, additionalProperty),
        its size chart and its redirect, into the line it is the page of."""
        nodes = [n for n in _product_nodes(row.get('json_ld'))]
        group = next((n for n in nodes if n.get('hasVariant')), nodes[0] if nodes else None)
        name = (group or {}).get('name') or row.get('page_title') or line_hint
        line = self.line(name) if name else None
        if line is None:
            return
        line.sources.add('page')
        for prop in (group or {}).get('additionalProperty') or []:
            if not isinstance(prop, dict):
                continue
            label = str(prop.get('name') or '').strip().lower()
            if label == 'size range':
                sizes = [_size_of(s) for s in _split_list(prop.get('value'))]
                line.sizes.update(s for s in sizes if s)
                line.sizes_complete = True
            elif label in ('pack count', 'pack counts', 'count'):
                for c in _split_list(prop.get('value')):
                    if c.isdigit():
                        line.counts.add(str(int(c)))
                        line.counts_complete = True
        for variant in (group or {}).get('hasVariant') or []:
            if not isinstance(variant, dict):
                continue
            size = _size_of(variant.get('size')) or _size_of(variant.get('name'))
            if size:
                line.sizes.add(size)
                line.sizes_complete = True
                line.add_range(size, _first_range(variant.get('description')), 'page')
            for key in ('gtin13', 'gtin14', 'gtin12', 'gtin8', 'gtin'):
                if variant.get(key):
                    line.gtins.add(str(variant[key]))
            count = next((m.group(1) or m.group(2) for m in _TITLE_COUNT.finditer(str(variant.get('name') or ''))),
                         None)
            if count:
                line.counts.add(str(int(count)))
        for chart in row.get('size_chart') or []:
            if isinstance(chart, dict) and chart.get('size'):
                size = _size_of(chart['size'])
                if size:
                    line.sizes.add(size)
                    line.sizes_complete = True
                    line.add_range(size, chart)
        for text in list(row.get('bullets') or []) + [row.get('description')] + _json_ld_texts(group):
            if text:
                line.add_text(text)
        url, final = row.get('url'), row.get('final_url')
        if url and final and url.rstrip('/') != final.rstrip('/') and line_hint:
            asked = self.line(line_hint)
            if asked is not None and asked is not line:
                asked.status, asked.successor = 'retired', line.name
                asked.sources.add('redirect')
        if line.status is None and (group or row.get('size_chart')):
            line.status = 'current'


def _product_nodes(value) -> List[dict]:
    out = []
    items = value if isinstance(value, list) else [value]
    for item in items:
        if isinstance(item, dict):
            if isinstance(item.get('@graph'), list):
                out.extend(_product_nodes(item['@graph']))
            kind = item.get('@type')
            kinds = kind if isinstance(kind, list) else [kind]
            if any(k in ('Product', 'ProductGroup') for k in kinds) or item.get('hasVariant'):
                out.append(item)
    return out


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


def _variant_line(v: dict, brand) -> Optional[str]:
    """The line a record variant belongs to: its product's title (2O-5's
    `line`, BrandFactsCache), else its own title ("Pampers Swaddlers NB 84")."""
    return v.get('line') or v.get('title')


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
    # 2O-4: read in three passes, each fact counted for the first that put it
    # on the index (by_source): the merchant record, the catalog, the pages
    for name in [facts.get('program_name')] + list(facts.get('tier_names') or []):
        if name:
            index.add_text(name, page=False)
    for d in list(facts.get('own_domains') or []) + list(facts.get('tenant_own_domains') or []) \
            + [facts.get('domain')] + list(facts.get('retailer_list') or []):
        if ea.normalize_domain(d):
            index.retailers.add(ea.normalize_domain(d))
    index.by_source['record'] = index.size()
    for title in facts.get('product_titles') or []:
        index.add_title(title)
    statuses = {}
    for v in facts.get('variants') or []:
        if not isinstance(v, dict):
            continue
        index.add_variant(v.get('title'), v.get('size'), v.get('count'),
                          (v.get('list_price'), v.get('member_price')), v.get('weight_range'), v.get('attributes'))
        # 2O-5: the feed's (line, size) range, and its status, per line
        line = index.line(_variant_line(v, index.brand))
        if line is None:
            continue
        line.sources.add('feed')
        size = _size_of(v.get('size')) or next((_size(m.group(1) or m.group(2) or m.group(3))
                                                for m in _TITLE_SIZE.finditer(str(v.get('title') or ''))), None)
        line.add_range(size, v.get('weight_range'), 'feed')
        for key, value in (v.get('attributes') or {}).items():
            for item in (value if isinstance(value, list) else [value]):
                if item is True:
                    line.add_text(str(key).replace('_', ' '))
                elif isinstance(item, str) and item.strip():
                    line.add_text(f"{str(key).replace('_', ' ')} {item}")
        if v.get('status'):
            statuses.setdefault(line.key, []).append((v['status'], v.get('successor')))
    for key, seen in sorted(statuses.items()):
        line = index.lines[key]
        if all(status == 'retired' for status, _s in seen):
            line.status = 'retired'
            successor = next((s for _st, s in seen if s), None)
            line.successor = (successor.get('product_name') or successor.get('title')) \
                if isinstance(successor, dict) else successor
        else:
            line.status = 'current'
    for text in list(facts.get('features') or []) + list(facts.get('descriptions') or []):
        index.add_text(text)
    index.sizes.discard(None)
    index.by_source['catalog'] = index.size() - index.by_source['record']

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
        # 2O-5: a row's brand truth (the brand page's chart, 2M-1) is its variant's (line, size) range
        label = row.get('variant_label')
        truth = (row.get('attribute') or {}).get('truth') or (row.get('weight_range') if row.get('role') == 'own'
                                                              else None)
        if label and truth:
            line = index.line(f"{index.brand or ''} {label}")
            size = next((_size(m.group(1) or m.group(2) or m.group(3)) for m in _TITLE_SIZE.finditer(str(label))),
                        None)
            if line is not None:
                line.add_range(size, truth)
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
        if row.get('role') == 'own' and (row.get('json_ld') or row.get('size_chart')):
            index.add_page(row, line_hint=f"{index.brand or ''} {label}" if label else None)
    served = (reference or {}).get('brand_lines')
    if isinstance(served, list):
        index.brand_lines = []
        for name in served:
            if isinstance(name, str) and name.strip() and name not in index.brand_lines:
                index.brand_lines.append(name)
                index.line(name, title=False)
    index.sizes.discard(None)
    index.by_source['brand_pages'] = index.size() - index.by_source['record'] - index.by_source['catalog']
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
    # a negation rewrites a word that is a fact ("free of fragrance" is fragrance
    # free); it adds none ("free of latex" was no fact before 2O-5 and is none now)
    negated = [t for t in negated_terms(text) if t[:-len(' free')] in ATTRIBUTE_TERMS]
    for term in attribute_terms(text):
        written = term_pattern(term).search(text.lower())
        # 2O-5: "free of fragrance" states fragrance free, not fragrance
        if f"{stem(term)} free" in negated:
            continue
        out.append(_fact('attribute', text[written.start():written.end()] if written else term, term))
    for term in negated:
        m = _NEGATED.search(text)
        out.append(_fact('attribute', m.group(0).strip() if m else term, term))
    # 2O-5: a line's status ("Pampers Pure Protection was discontinued")
    for rx, value in ((_CURRENT, 'current'), (_RETIRED, 'retired')):
        m = rx.search(text)
        if m:
            out.append(_fact('status', m.group(0).strip(), value))
            break
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


# ─── 2O-5: contradicted, not merely absent ─────────────────────────────────

CONTRADICTED, UNVERIFIED = 'contradicted', 'unverified'
#: what a contradicted slot is called in the drawer line, by fact type
SLOT_SOURCE = {'weight': 'chart', 'size': 'size list', 'count': 'pack counts', 'status': 'line status',
               'attribute': 'page', 'name': 'line list'}


def size_label(size) -> str:
    return {'0': 'Newborn', 'p': 'Preemie'}.get(str(size), f"Size {size}")


def _size_order(sizes) -> list:
    return sorted(sizes, key=lambda v: (0 if v == 'p' else 1 if v == '0' else 2, int(v) if str(v).isdigit() else 0))


def _published(fact_type, values) -> str:
    if fact_type == 'weight':
        return ' or '.join(aa.phrase(r) or '?' for r in values)
    if fact_type == 'size':
        return ', '.join(size_label(v) for v in _size_order(values))
    if fact_type == 'count':
        return ', '.join(sorted(values, key=int))
    return ', '.join(str(v) for v in values)


def _weight_status(claim: dict, published: List[dict]) -> str:
    """found | contradicted for a claimed range against the ranges the brand
    states for its (line, size). A one-bound claim ("up to 14 lbs") is
    checked on that bound only: found within tolerance, contradicted when a
    stated range has the bound and none agrees, else unverified."""
    if claim.get('min') is not None and claim.get('max') is not None or \
            claim.get('min') is None and claim.get('max') is None:
        return FOUND if any(aa.same(claim, r) for r in published) else CONTRADICTED
    if any(aa.same(claim, r) for r in published):
        return FOUND
    bound = 'max' if claim.get('max') is not None else 'min'
    with_bound = [r for r in published if r.get(bound) is not None]
    if any(abs(r[bound] - claim[bound]) <= aa.TOLERANCE_LB for r in with_bound):
        return FOUND
    return CONTRADICTED if with_bound else UNVERIFIED


def check(fact: dict, index: FactIndex, *, line: Optional[str] = None, size: Optional[str] = None) -> dict:
    """
    2O-5: one fact against the index's slots. {status, slot, claimed,
    published, line, size}: status found | contradicted | unverified.
    `line` is the line the claim is about (its name as written), `size` the
    size a weight or count is for, when the sentence (or the question) binds
    one; a slot is consulted only when both are bound and the index holds a
    value for it. See the module docstring.
    """
    kind, value = fact['type'], fact.get('value')
    out = {'status': UNVERIFIED, 'slot': None, 'claimed': fact.get('text'), 'published': None,
           'line': None, 'size': size}
    bound = index.find_line(line) if line else None
    if bound is not None:
        out['line'] = bound.name

    def contradicted(slot, published, source=None):
        out.update(status=CONTRADICTED, slot=slot, published=published)
        if source:
            out['source'] = source
        return out

    if kind in ('price', 'unit_price'):
        out['slot'] = 'price'          # the price tier judges prices
        return out
    if line and bound is None and kind in ('size', 'count', 'weight', 'status', 'attribute'):
        # about a line the index does not hold ("Ninjamas come in Size 6"):
        # a size another line comes in grounds nothing about this one
        return out
    if kind == 'retailer':
        out.update(slot='retailers', status=FOUND if value in index.retailers else UNVERIFIED)
        return out
    if kind == 'name':
        if _found(fact, index) or index.find_line(fact.get('text')) is not None:
            out['status'] = FOUND
        elif index.brand_lines is not None:
            return contradicted('lines', _published('name', index.brand_lines))
        return out
    if kind == 'status':
        if bound is not None and bound.status:
            if bound.status == value:
                out['status'] = FOUND
            else:
                published = bound.status + (f", succeeded by {bound.successor}" if bound.successor else '')
                return contradicted('status', published)
        return out
    if kind == 'size':
        if bound is not None and bound.sizes_complete:
            missing = [v for v in value or [] if v not in bound.sizes]
            if not missing:
                out['status'] = FOUND
                return out
            return contradicted('sizes', _published('size', bound.sizes))
        out['status'] = FOUND if _found(fact, index) else UNVERIFIED
        return out
    if kind == 'count':
        if bound is not None and bound.counts_complete:
            if value in bound.counts:
                out['status'] = FOUND
                return out
            return contradicted('counts', _published('count', bound.counts))
        out['status'] = FOUND if _found(fact, index) else UNVERIFIED
        return out
    if kind == 'weight':
        if bound is not None and size and bound.ranges.get(size):
            status = _weight_status(value, bound.ranges[size])
            if status == CONTRADICTED:
                return contradicted('ranges', _published('weight', bound.ranges[size]),
                                    'record' if bound.range_sources.get(size) == {'feed'} else None)
            if status == FOUND:
                out['status'] = FOUND
                return out
        elif bound is not None and not size and bound.sizes_complete and bound.ranges:
            # a range for the line, no size named: contradicted when it is no
            # size's range on the line's complete chart ("Swaddlers fit 2-9 lbs")
            every = [r for k in sorted(bound.ranges) for r in bound.ranges[k]]
            if any(aa.same(value, r) for r in every):
                out['status'] = FOUND
                return out
            if _weight_status(value, every) == CONTRADICTED:
                return contradicted('ranges', '; '.join(
                    f"{size_label(k)} {_published('weight', bound.ranges[k])}" for k in _size_order(bound.ranges)))
        out['status'] = FOUND if _found(fact, index) else UNVERIFIED
        return out
    if kind == 'attribute':
        # a word with an opposite is found only as itself: "fragrance" is in
        # "fragrance free" as text, and is its opposite
        if (value in index.attributes) if value in OPPOSITES else _found(fact, index):
            out['status'] = FOUND
            return out
        # the opposite on the line's own pages or variants: another line's
        # "fragrance free" says nothing about this one
        opposite = [o for o in OPPOSITES.get(value, ()) if bound is not None and o in bound.attributes
                    and value not in bound.attributes]
        if opposite:
            return contradicted('attribute', opposite[0])
        return out
    return out
