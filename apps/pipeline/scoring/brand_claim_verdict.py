"""
2O-3: the brand-claim verdict, decided by code from the claim's facts.

The coder's calls (2O-1: two, a third on a disagreement) still transcribe
and label the answer, exactly as before: the same prompts, the same
settings, the same record. What the model no longer decides, even
indirectly, is the category. Version 2 computed it from the labelled record
with brand_direct_classifier.classify, whose rule "an asserted claim with no
source is fabricated" turned every labelling wobble into a category move:
a sentence the labeller called an asserted claim on one call and `none` on
the next took the answer from echoed to fabricated, a cited domain one call
found and the next did not took it from grounded to fabricated. Two
re-scores of FL14 moved 66 of 258 answers that way.

Now the record gives only spans, and the verdict is a lookup:

  claim spans  the answer's own sentences the labeller marked asserted
               claims about the brand (extraction_postprocess.asserted_
               claims), and the sentences naming a store it sends the reader
               to (retailer_mentions role recommendation). Each is the
               segmenter's verbatim cut of the answer; the 2A-5 evidence
               rule is checked anyway (evidence(): a span not in the answer
               text refuses the call). Each carries a `kind` tag, decided
               here from its words (span_kind): price, availability,
               attribute, where_to_buy, recommendation, general.
  agreement    two calls agree when neither was refused and their span sets
               agree: both empty, or every span of each overlaps a span of
               the other (brand_direct_classifier.spans_overlap). A
               disagreement makes the third call, as in 2O-1.
  verdict      per span, from its facts (brand_fact_index.facts_in) against
               the cycle's index, the facts the question already states
               set aside:
                 misattributed  a name written as the brand's that is one
                                of another brand's the answer named
                 echoed         no fact beyond the question's, and its
                                words mostly the question's (ECHO_THRESHOLD)
                 fabricated     a fact not on the index
                 grounded       facts, every one on the index
                 not read       facts, none on the index, all of a type the
                                cycle read nothing of (unchecked)
                 no fact        none of the above
               per answer, worst first: unscoreable (unread), absent,
               misattributed, fabricated, grounded, acknowledged_unknown (a
               sentence of the answer says it could not find the brand,
               extraction_postprocess.looks_unknown, the phrase list the
               transcription's cannot-find check already uses), echoed, then
               unscoreable: fact_type_not_read, else no_checkable_fact.

`unscoreable` / no_checkable_fact is outside every count, as unscoreable
always is: "Pampers is a great choice" states nothing a brand could have
published or not.

What decided it is stored (extraction.brand_claim, written from
Verdict.brand_claim): every span, its kind, its facts found, missing and
unchecked, the span that decided, and the index's version and digest; the
reason quotes the deciding span and names the fact ("'Swaddlers fit 2-9
lbs.' — '2-9 lbs' is not on pampers.com's Swaddlers page").
"""
import re
from typing import List, Optional

from parser import extraction_postprocess as pp
from scoring import brand_fact_index as bfi
from scoring.brand_direct_classifier import spans_overlap
from soa_shared import expected_answers as ea
from soa_shared.retailers import retailer_name, retailers_named

GROUNDED, ECHOED, MISATTRIBUTED, FABRICATED = 'grounded', 'echoed', 'misattributed', 'fabricated'
ACKNOWLEDGED_UNKNOWN, ABSENT, UNSCOREABLE = 'acknowledged_unknown', 'absent', 'unscoreable'
#: a span's own verdicts that are not answer outcomes
NO_FACT, NOT_READ = 'no_fact', 'not_read'

#: A span echoes the question when at least this share of its words (stop
#: words, numbers and names aside) are the question's, and it states no
#: fact the question does not. Tuned on the demo's question/answer pairs
#: (tests/fixtures/brand_claim/echo_pairs.json): the restatements sit at or
#: above 0.6, the answers that say something new well below it.
ECHO_THRESHOLD = 0.6

SPAN_KINDS = ('price', 'availability', 'attribute', 'where_to_buy', 'recommendation', 'general')

#: Reason codes (scripts/rescore_cycle.RULES names each)
CODE_FACT_MISSING = 'fact_not_published'
CODE_FACTS_FOUND = 'facts_published'
CODE_NO_CHECKABLE_FACT = ea.NO_CHECKABLE_FACT
CODE_NOT_READ = ea.FACT_TYPE_NOT_READ
CODE_REFUSED = 'span_not_in_answer'

_STOP = frozenset(
    'a an and are as at be been being but by can do does for from has have how i if in into is it its just me my '
    'of on or our should so than that the their them then there these they this to too was we were what when which '
    'who why will with would you your yes no not also very really more most much many some any all one'.split())
_BUY = re.compile(r"\b(?:buy|purchase|order|shop|find|get|pick up|available|sold|sells?|carr(?:y|ies)|stock(?:s|ed)?|"
                  r"check)\b", re.I)
_AVAILABILITY = re.compile(r"\b(?:available|availability|in stock|out of stock|discontinued|sold out|launch\w*|"
                           r"no longer|exclusive\w*)\b", re.I)
_RECOMMEND = re.compile(r"\b(?:recommend\w*|best|great|good|top|ideal|go with|should (?:buy|try|use|get)|"
                        r"choice|pick|favorite|favourite|popular|love)\b", re.I)


def span_kind(text, facts: List[dict]) -> str:
    """The span's kind, from its words and the facts in it. Deterministic."""
    types = {f['type'] for f in facts}
    if 'retailer' in types and _BUY.search(text or ''):
        return 'where_to_buy'
    if types & {'price', 'unit_price'}:
        return 'price'
    if _AVAILABILITY.search(text or ''):
        return 'availability'
    if types & {'count', 'size', 'weight', 'attribute', 'name'}:
        return 'attribute'
    if _RECOMMEND.search(text or ''):
        return 'recommendation'
    return 'general'


# ─── What a call extracted ─────────────────────────────────────────────────

def claim_spans(record) -> List[str]:
    """The claim spans one call's record gives, in answer order, each once."""
    record = record or {}
    out: List[str] = []

    def add(text):
        text = str(text or '').strip()
        if text and text not in out:
            out.append(text)

    for claim in pp.asserted_claims(record):
        add(claim.get('claim'))
    mentions = record.get('retailer_mentions')
    if mentions is not None:
        sent = [m.get('name') for m in mentions if isinstance(m, dict) and m.get('role') == 'recommendation']
    else:
        sent = list(record.get('recommended_retailers') or [])
    stores = {d for name in sent if name for d in (retailers_named(name) or [])}
    if stores:
        for span in record.get('spans') or []:
            text = (span or {}).get('text') if isinstance(span, dict) else None
            if text and stores & set(retailers_named(text)):
                add(text)
    order = [s.get('text') for s in record.get('spans') or [] if isinstance(s, dict)]
    return sorted(out, key=lambda t: order.index(t) if t in order else len(order))


def _flat(text) -> str:
    return ' '.join(str(text or '').replace('’', "'").replace('“', '"').replace('”', '"').split())


def evidence(record, answer_text) -> dict:
    """2A-5's rule: every claim span is in the answer text (whitespace and
    curly quotes aside), or the call is refused. {'ok', 'missing'}."""
    answer = _flat(answer_text)
    missing = [s for s in claim_spans(record) if _flat(s) not in answer]
    return {'ok': not missing, 'missing': missing}


def refused(record) -> bool:
    return (record or {}).get('evidence', {}).get('ok') is False


def spans_agree(a: List[str], b: List[str]) -> bool:
    """Two calls' span sets agree: the same set, or every span of each
    overlapping a span of the other. Both empty agree."""
    if [_flat(s) for s in a] == [_flat(s) for s in b]:
        return True
    if not a or not b:
        return False
    return all(any(spans_overlap(x, y) for y in b) for x in a) and \
        all(any(spans_overlap(y, x) for x in a) for y in b)


def calls_agree(a: dict, b: dict) -> bool:
    if refused(a) or refused(b):
        return False
    return spans_agree(claim_spans(a), claim_spans(b))


def settle(calls) -> Optional[tuple]:
    """The first pair of calls that agree, as (i, j), or None."""
    for i in range(len(calls)):
        for j in range(i + 1, len(calls)):
            if calls_agree(calls[i], calls[j]):
                return i, j
    return None


# ─── The verdict ───────────────────────────────────────────────────────────

def _content(text, drop: set) -> List[str]:
    return [bfi.stem(t) for t in bfi.tokens(text)
            if t not in _STOP and not any(ch.isdigit() for ch in t) and bfi.stem(t) not in drop]


def overlap(span, question, brand=None, names=()) -> float:
    """The share of the span's words that are the question's: stop words,
    numbers, the brand and every name aside. A span left with no words is
    all question (1.0)."""
    drop = {bfi.stem(t) for t in bfi.tokens(brand)} | {bfi.stem(t) for n in names for t in n}
    words = _content(span, drop)
    if not words:
        return 1.0
    asked = set(_content(question, drop))
    return sum(1 for w in words if w in asked) / len(words)


def _in_question(fact: dict, question_facts: List[dict], question_words: set) -> bool:
    if fact['type'] == 'name':
        return {bfi.stem(t) for t in fact.get('value') or []} <= question_words
    return any(q['type'] == fact['type'] and q.get('value') == fact.get('value') for q in question_facts)


def other_brand_names(record) -> List[List[str]]:
    """The other brands the answer named, as words, each with its own brand
    word dropped ("Huggies Little Snugglers" -> little, snugglers): what a
    line written as this brand's is compared with."""
    out = []
    for entry in (record or {}).get('other_brands_named') or []:
        name = entry.get('name') if isinstance(entry, dict) else None
        if not name or (isinstance(entry, dict) and entry.get('relation') == 'not_a_brand'):
            continue
        words = [t for t in bfi.tokens(name) if t not in bfi.GENERIC]
        out.append(words)
        if len(words) > 1:
            out.append(words[1:])
    return [w for w in out if w]


def judge_span(text, *, question, brand, index, others=(), own_domains=()) -> dict:
    facts = bfi.facts_in(text, brand, own_domains=own_domains)
    q_facts = bfi.facts_in(question, brand, own_domains=own_domains)
    q_words = {bfi.stem(t) for t in bfi.tokens(question)}
    out = {'text': text, 'kind': span_kind(text, facts)}
    names = [f for f in facts if f['type'] == 'name']
    # the brand's own line the span names, for the reason ("pampers.com's Swaddlers page")
    out['line'] = next((f['text'] for f in names if bfi.lookup(f, index) == bfi.FOUND), None)
    for f in names:
        if bfi.lookup(f, index) == bfi.FOUND:
            continue
        want = {bfi.stem(t) for t in f['value']}
        other = next((o for o in others if want <= {bfi.stem(t) for t in o}), None)
        if other:
            out.update(verdict=MISATTRIBUTED, other=' '.join(other), facts_found=[], facts_unchecked=[],
                       facts_missing=[{'type': 'name', 'text': f['text']}])
            return out
    added = [f for f in facts if not _in_question(f, q_facts, q_words)]
    found, missing, unchecked = [], [], []
    for f in added:
        status = bfi.lookup(f, index)
        (found if status == bfi.FOUND else missing if status == bfi.MISSING else unchecked).append(
            {'type': f['type'], 'text': f['text']})
    out.update(facts_found=found, facts_missing=missing, facts_unchecked=unchecked)
    if not added:
        out['overlap'] = round(overlap(text, question, brand, [f['value'] for f in names]), 3)
        out['verdict'] = ECHOED if out['overlap'] >= ECHO_THRESHOLD else NO_FACT
    elif missing:
        out['verdict'] = FABRICATED
    elif found:
        out['verdict'] = GROUNDED
    else:
        out['verdict'] = NOT_READ
    return out


def possessive(name) -> str:
    return f"{name}'" if str(name).endswith('s') else f"{name}'s"


def _where(fact: dict, span: dict, index, brand) -> str:
    domain = index.domain or 'the brand site'
    if fact['type'] == 'retailer':
        return f"{retailer_name(fact['text']) or fact['text']} is not on {possessive(brand)} retailer list"
    line = span.get('line')
    place = f"{domain}'s {line} page" if line else f"{possessive(brand)} record or the {domain} pages read this cycle"
    return f"{fact['text']!r} is not on {place}"


def unknown_sentence(record) -> Optional[str]:
    """The answer's first sentence saying it could not find the brand (the
    phrase list), from the segmenter's spans; the transcription's own
    statement for a record with none."""
    for span in (record or {}).get('spans') or []:
        text = span.get('text') if isinstance(span, dict) else None
        if text and pp.looks_unknown(text):
            return text
    statement = (record or {}).get('brand_unknown_statement')
    return statement if statement and pp.looks_unknown(statement) else None


def decide(record, expectation, *, question, index: 'bfi.FactIndex', own_domains=()) -> dict:
    """{outcome, reason, reason_code, brand_claim} for one call's record."""
    record = record or {}
    brand = (expectation or {}).get('brand') or index.brand or 'the brand'
    claim = {'version': ea.BRAND_CODER_VERSION, 'index': index.stamp(), 'echo_threshold': ECHO_THRESHOLD,
             'spans': [], 'decided_by': None}

    def done(outcome, reason, code=None, at=None):
        claim['decided_by'] = at
        return {'outcome': outcome, 'reason': reason, 'reason_code': code, 'brand_claim': claim}

    if not record.get('extraction_confident', True):
        return done(UNSCOREABLE, record.get('extraction_note') or 'the answer could not be read')
    if not record.get('brand_mentioned'):
        return done(ABSENT, f"the answer did not name {brand}")

    others = other_brand_names(record)
    spans = [judge_span(t, question=question or '', brand=brand, index=index, others=others,
                        own_domains=own_domains) for t in claim_spans(record)]
    claim['spans'] = spans

    def first(verdict):
        return next(((i, s) for i, s in enumerate(spans) if s['verdict'] == verdict), (None, None))

    i, span = first(MISATTRIBUTED)
    if span:
        return done(MISATTRIBUTED, f"named {brand} but described {span['other']}: {span['text']!r}", at=i)
    i, span = first(FABRICATED)
    if span:
        return done(FABRICATED, f"{span['text']!r} — {_where(span['facts_missing'][0], span, index, brand)}",
                    CODE_FACT_MISSING, i)
    i, span = first(GROUNDED)
    if span:
        facts = ', '.join(repr(f['text']) for f in span['facts_found'])
        return done(GROUNDED, f"{span['text']!r} — on {possessive(brand)} record or pages: {facts}",
                    CODE_FACTS_FOUND, i)
    unknown = unknown_sentence(record)
    if unknown:
        return done(ACKNOWLEDGED_UNKNOWN, f"said it could not find {brand}: {unknown!r}")
    i, span = first(ECHOED)
    if span:
        return done(ECHOED, f"{span['text']!r} — restates the question and adds no fact", at=i)
    i, span = first(NOT_READ)
    if span:
        types = sorted({f['type'] for f in span['facts_unchecked']})
        return done(UNSCOREABLE, f"{span['text']!r} — states {', '.join(types)} facts, and the cycle read no "
                                 f"{' or '.join(types)} for {brand}", CODE_NOT_READ, i)
    return done(UNSCOREABLE, ea.NO_CHECKABLE_FACT_NOTE, CODE_NO_CHECKABLE_FACT)
