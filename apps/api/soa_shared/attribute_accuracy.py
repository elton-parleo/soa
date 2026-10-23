"""
2M-1: attribute accuracy, the weight range for the size asked (the demo's
Accuracy set). Sync copies in apps/api/soa_shared/ and apps/pipeline/soa_shared/.

`attribute = "weight range for the size asked"`. One brand truth per
variant: supply's (parleo-supply-app truesync/fullloop/weight.py), the feed's
weight_min_lb / weight_max_lb, else what the brand's own page states for the
size, never its markup. The truth is written on the question when it is
generated (source_ref.weight_truth, catalog_tiers.build_intent_questions), so
a cycle is scored against the truth it asked about.

  coder    weight_from_answer(): the first weight range in the answer that
           sits within SIZE_REACH characters of the asked size's token
           ("Size 4 is for babies 22-37 lb", "for 15 to 34 pounds (Size 4)"),
           in the forms "X to Y lb", "X–Y lbs", "X-Y pounds", "under N lb",
           "N+ lb", "up to N lb". Stored on the run's extraction as
           `weight_range` / `weight_evidence`; None when the answer states
           none for the size. No model.
  verdict  verdict(): match (each bound within TOLERANCE_LB, an open bound
           only against an open bound, as supply's), mismatch, or absent.

Ranges are {"min": float|None, "max": float|None} in pounds: max None is
"and up", min None is "under".
"""
import html as html_lib
import re
from typing import List, Optional, Tuple

ATTRIBUTE_INTENT = 'attribute'
#: Bounds within this many pounds agree (supply's weight.TOLERANCE_LB).
TOLERANCE_LB = 1.0
#: A range belongs to the size when it sits within this many characters of the size's token.
SIZE_REACH = 80
VERDICTS = ('match', 'mismatch', 'absent')

_UNIT = r"(?:lbs?|pounds?)\b\.?"
_NUM = r"(\d{1,3}(?:\.\d)?)"
_BETWEEN = re.compile(rf"(?<![\d.]){_NUM}\s*(?:{_UNIT})?\s*(?:-|to)\s*{_NUM}\s*{_UNIT}", re.I)
_PLUS = re.compile(rf"(?<![\d.]){_NUM}\s*(?:\+\s*{_UNIT}|{_UNIT}\s*(?:\+|and up\b|or more\b|and over\b))", re.I)
_OVER = re.compile(rf"\b(?:over|more than)\s*{_NUM}\s*{_UNIT}", re.I)
_UNDER = re.compile(rf"(?:\b(?:under|up to|less than|below)\s*|<\s*){_NUM}\s*{_UNIT}", re.I)
_SIZE = re.compile(r"\bsize\s*[:#]?\s*(newborn|preemie|nb|n|p|\d{1,2})\b|\b(newborn|preemie)\b", re.I)
_SIZE_ALIASES = {'newborn': '0', 'nb': '0', 'n': '0', 'preemie': 'p'}


def normalize(text: Optional[str]) -> str:
    """Entities unescaped, dashes made one, markdown emphasis dropped, spaces squashed."""
    text = html_lib.unescape(text or '')
    text = re.sub(r"[‐-―−]", '-', text)
    text = re.sub(r"[*_`]+", '', text)
    return re.sub(r"\s+", ' ', text.replace('\xa0', ' ')).strip()


def _num(text):
    return None if text is None else float(text)


def parse_ranges(text: Optional[str]) -> List[Tuple[dict, int, int]]:
    """Every weight range in the (normalized) text, as ({min, max}, start, end), in order."""
    text = normalize(text)
    found, taken = [], []

    def add(rng, m):
        if any(s < m.end() and m.start() < e for s, e in taken):
            return
        taken.append((m.start(), m.end()))
        found.append((rng, m.start(), m.end()))

    for m in _BETWEEN.finditer(text):
        low, high = _num(m.group(1)), _num(m.group(2))
        if low <= high:
            add({'min': low, 'max': high}, m)
    for m in _PLUS.finditer(text):
        add({'min': _num(m.group(1)), 'max': None}, m)
    for m in _OVER.finditer(text):
        add({'min': _num(m.group(1)), 'max': None}, m)
    for m in _UNDER.finditer(text):
        add({'min': None, 'max': _num(m.group(1))}, m)
    return sorted(found, key=lambda f: f[1])


def size_of(text: Optional[str]) -> Optional[str]:
    """The diaper size a string names, normalised ("Size Newborn" and "Size 0" are one size), or None."""
    m = _SIZE.search(text or '')
    if not m:
        return None
    value = (m.group(1) or m.group(2)).lower()
    return _SIZE_ALIASES.get(value, value)


#: Any size token, for deciding which size a range belongs to.
_ANY_SIZE = re.compile(r"\bsize\s*-?\s*(newborn|preemie|nb|n|p|\d{1,2})(?!\d|\.\d)|\b(newborn|preemie)\b", re.I)


def weight_from_answer(answer: Optional[str], size: Optional[str]) -> Tuple[Optional[dict], Optional[str]]:
    """
    (range, evidence) the answer states for `size`: the first range, in
    answer order, that belongs to a token of the size within SIZE_REACH
    characters. A range belongs to the nearest size token before it ("Size
    3 (16-28 lbs) ... Size 4 (22-37 lbs)": 22-37 is Size 4's), else the
    nearest after it ("for 15 to 34 pounds (Size 4)"). Evidence is the
    answer's text from the token to the range. (None, None) when it states
    none for the size.
    """
    want = size_of(size) or size_of(f"size {size}" if size else None)
    text = normalize(answer)
    if want is None or not text:
        return None, None
    tokens = [(m.start(), m.end(), _SIZE_ALIASES.get((m.group(1) or m.group(2)).lower(),
                                                      (m.group(1) or m.group(2)).lower()))
              for m in _ANY_SIZE.finditer(text)]
    for rng, start, end in parse_ranges(text):
        before = [t for t in tokens if t[1] <= start and start - t[1] <= SIZE_REACH]
        after = [t for t in tokens if t[0] >= end and t[0] - end <= SIZE_REACH]
        owner = before[-1] if before else (after[0] if after else None)
        if owner is not None and owner[2] == want:
            lo, hi = min(start, owner[0]), max(end, owner[1])
            return rng, text[lo:hi]
    return None, None


def same(a: Optional[dict], b: Optional[dict], tolerance: float = TOLERANCE_LB) -> bool:
    if a is None or b is None:
        return False
    for key in ('min', 'max'):
        x, y = a.get(key), b.get(key)
        if (x is None) != (y is None):
            return False
        if x is not None and abs(float(x) - float(y)) > tolerance:
            return False
    return True


def verdict(stated: Optional[dict], truth: Optional[dict]) -> Optional[str]:
    """match | mismatch | absent; None when there is no truth to check against."""
    if truth is None:
        return None
    if stated is None:
        return 'absent'
    return 'match' if same(stated, truth) else 'mismatch'


def phrase(rng: Optional[dict]) -> Optional[str]:
    """{min, max} for people: "15 to 34 lb", "27+ lb", "under 10 lb"."""
    if not rng:
        return None
    fmt = lambda v: format(float(v), 'g')  # noqa: E731
    low, high = rng.get('min'), rng.get('max')
    if low is not None and high is not None:
        return f"{fmt(low)} to {fmt(high)} lb"
    if low is not None:
        return f"{fmt(low)}+ lb"
    if high is not None:
        return f"under {fmt(high)} lb"
    return None


def one_liner(stated: Optional[dict], truth: Optional[dict], brand_site: str = 'the brand site') -> Optional[str]:
    """The /answers row line: "stated 22 to 37 lb; pampers.com says 15 to 34"."""
    if truth is None:
        return f"stated {phrase(stated)}; no brand truth on record" if stated else None
    said = phrase(truth).removesuffix(' lb')
    if stated is None:
        return f"stated no weight range; {brand_site} says {said}"
    if verdict(stated, truth) == 'match':
        return f"stated {phrase(stated)}, as {brand_site} says"
    return f"stated {phrase(stated)}; {brand_site} says {said}"


def answer_attribute(source_ref: Optional[dict], extraction: Optional[dict], answer: Optional[str] = None,
                     brand_site: Optional[str] = None) -> Optional[dict]:
    """
    An attribute question's answer, judged: {size, stated, evidence, truth,
    truth_source, verdict, line} (line is one_liner's). None for any other
    question. The stated range is the stored coding (the extraction's
    weight_range / weight_evidence, expectation_scorer.code_attribute), else
    coded here from the answer text (an outcome stored before the coder).
    """
    ref = source_ref or {}
    if ref.get('intent') != ATTRIBUTE_INTENT:
        return None
    x = extraction or {}
    if 'weight_range' in x:
        stated, evidence = x.get('weight_range'), x.get('weight_evidence')
    else:
        stated, evidence = weight_from_answer(answer, ref.get('size'))
    truth = ref.get('weight_truth')
    site = brand_site or ref.get('own_domain') or ref.get('domain') or 'the brand site'
    return {'size': ref.get('size'), 'count': ref.get('count'), 'stated': stated, 'evidence': evidence,
            'truth': truth, 'truth_source': ref.get('weight_truth_source'),
            'verdict': verdict(stated, truth), 'line': one_liner(stated, truth, site)}


def size_label(text: Optional[str]) -> Optional[str]:
    """The size as a label ("Size 4", "Newborn") from a variant label ("Size 4, 120 ct"), or None."""
    norm = size_of(text)
    if norm is None:
        return None
    return {'0': 'Newborn', 'p': 'Preemie'}.get(norm, f"Size {norm}")
