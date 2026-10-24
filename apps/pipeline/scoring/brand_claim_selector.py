"""
2O-4: the brand-direct claims, selected by rule. No model call.

2O-3 made the verdict a lookup, and the claim spans still came from the
model: two calls extracted and labelled the answer, and the sentences they
called asserted claims about the brand were the ones judged. On FL14 two
consecutive re-scores under scorer 13 still moved 51 of 258 brand-direct
answers, because the model picked different sentences between runs: the
same answer was `echoed` in one run (it picked the restating sentence) and
`fabricated` in the next (it picked the factual one).

So the sentences are chosen here, from the answer text, by rule:

  units      the answer cut by the pipeline's segmenter (parser/
             span_segmenter.units): lines, then sentences, then clause
             breaks, each with the sentence it was cut from and, for a list
             item, the line that introduced the list.
  about the  a unit is about the brand when it names the brand or one of
  brand      its lines (Vocabulary: the brand's name, the study's terms,
             soa_shared/unprompted.brand_terms, the vocabulary Visibility
             counts with, and the line names in the catalog's and the
             study's product titles), or is a clause of a sentence that
             does, or a list item under a line that does. A unit naming a
             rival and not the brand is the rival's, whatever its sentence
             names; a lead-in naming both hands down neither.
  claim      a unit about the brand that is not hedged (pp.is_hedged, a
             hedge the list's lead-in hands down, or HEDGE_PHRASES: "some
             parents say") and not a cannot-find statement, and carries at
             least one checkable fact (brand_fact_index.facts_in: a price,
             unit price, count, size, weight, hours, retailer, attribute
             word, or a product or line name beyond the one that qualifies
             it). A unit about the brand with no checkable fact that
             restates the question (brand_claim_verdict.ECHO_THRESHOLD) is a
             claim too, and is judged `echoed`; one that does neither
             ("Pampers is a great choice") is not a claim.

Every claim is judged by the 2O-3 verdict (brand_claim_verdict.judge_span,
the facts the question states set aside) and the answer's verdict is the
worst over its claims (misattributed > fabricated > grounded > echoed),
2O-3's order with acknowledged_unknown where it was. Every judged sentence,
its facts and how it qualified are stored (extraction.brand_claim), so the
Answers drawer lists them.

The record this writes is the brand-direct extraction (coder version 4):
the units, the units about the brand labelled by rule (span_labels: claim
or not, hedged or not, for claim_kinds), the rivals named, the stores a
unit sends the reader to (retailer_mentions, for the fabricated-availability
flag), and the selection. The same answer and vocabulary give the same
record, byte for byte: nothing here is sampled.
"""
import hashlib
import json
import re
from typing import Iterable, List, Optional

from parser import extraction_postprocess as pp
from parser import span_segmenter
from scoring import brand_claim_verdict as bcv
from scoring import brand_fact_index as bfi
from soa_shared import expected_answers as ea
from soa_shared import unprompted
from soa_shared.retailers import retailer_name, retailers_named

#: How the answer's own words attribute a claim to someone else, which the
#: hedge lexicon (parser/extraction_postprocess.HEDGE_MARKERS) does not
#: carry: "Some parents say Swaddlers run small" states no fact of the
#: brand's. Matched as whole words, case aside.
HEDGE_PHRASES = (
    'some parents', 'many parents', 'some moms', 'some users', 'some reviewers', 'some customers',
    'some families', 'some people', 'reviewers say', 'reviews say', 'reportedly', 'according to some',
    'in my experience', 'anecdotally',
)
_HEDGE_PHRASES = [re.compile(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", re.I) for p in HEDGE_PHRASES]

#: A title word that ends a line name: a size or pack marker ("Swaddlers S1 96", "Size 1, 96 Count").
_SIZE_WORD = re.compile(r"^(?:s\d{1,2}|nb|size|sizes|newborn|preemie|\d+ct|\d+pk)$", re.I)
_COUNT_WORD = {'ct', 'count', 'pack', 'pk', 'diapers', 'wipes', 'pants'}
_TITLE_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’+-]*")


def hedged(unit: dict) -> bool:
    text = unit.get('text') or ''
    return bool(unit.get('inherits_hedge')) or pp.is_hedged(text) or any(rx.search(text) for rx in _HEDGE_PHRASES)


# ─── The vocabulary ────────────────────────────────────────────────────────

def line_name(title, brand) -> Optional[str]:
    """
    The line a product title names: the words after the brand's, up to a
    size or pack marker, a GENERIC word or a trailing number ("Pampers
    Swaddlers Diapers Size 1, 96 Count" -> Swaddlers; "Pampers Cruisers 360
    S4 104" -> Cruisers 360). A GENERIC first word followed by a word that
    is not is kept ("Pampers Baby Dry S3 136" -> Baby Dry).
    """
    words = [w.rstrip("'’") for w in _TITLE_WORD.findall(str(title or '').replace('®', '').replace('™', ''))]
    brand_tokens = [bfi.stem(t) for t in bfi.tokens(brand)]
    lowered = [bfi.stem(w.lower().replace('’', "'").removesuffix("'s")) for w in words]
    n = len(brand_tokens)
    start = next((i + n for i in range(len(words) - n + 1) if n and lowered[i:i + n] == brand_tokens), 0)
    rest = words[start:]
    out = []
    for i, word in enumerate(rest):
        low = word.lower()
        nxt = rest[i + 1].lower() if i + 1 < len(rest) else None
        if _SIZE_WORD.match(low):
            break
        if low in bfi.GENERIC and not (i == 0 and nxt and nxt not in bfi.GENERIC and not _SIZE_WORD.match(nxt)):
            break
        if word.isdigit() and (nxt is None or nxt in _COUNT_WORD):
            break
        out.append(word)
    return ' '.join(out) or None


class Vocabulary:
    """What names the merchant's brand, and its rivals. See the module docstring."""

    def __init__(self, brand: Optional[str], terms: Iterable[str] = (), titles: Iterable[str] = (),
                 rivals: Iterable[str] = ()) -> None:
        self.brand = brand
        self.terms = unprompted.brand_terms(brand, list(terms or []))
        self.titles = [t for t in dict.fromkeys(t for t in titles or [] if isinstance(t, str) and t.strip())]
        self.lines = []
        for title in self.titles:
            line = line_name(title, brand)
            if line and line not in self.lines:
                self.lines.append(line)
        own = {ea.normalize_brand_text(t) for t in self.terms}
        self.rivals = [r for r in unprompted.brand_terms(None, list(rivals or []))
                       if ea.normalize_brand_text(r) not in own]
        self._line_rx = [(line, _line_pattern(line)) for line in sorted(self.lines, key=lambda s: -len(s))]

    def stamp(self) -> dict:
        body = {'brand': self.brand, 'terms': self.terms, 'lines': self.lines, 'rivals': self.rivals}
        return {**body, 'digest': hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]}

    def names_brand(self, text) -> List[str]:
        """The brand's terms and lines the text names, terms first."""
        out = [t for t in unprompted.names_any(text, self.terms)]
        for line, rx in self._line_rx:
            if any(_line_at(text, m, line) for m in rx.finditer(str(text or ''))) and line not in out:
                out.append(line)
        return out

    def names_rival(self, text) -> List[str]:
        return unprompted.names_any(text, self.rivals)


def _line_pattern(line: str) -> re.Pattern:
    body = r"[\s\-]+".join(re.escape(w) for w in line.split())
    return re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])", re.I)


def _line_at(text: str, match: re.Match, line: str) -> bool:
    """A line written alone counts when it is capitalised as a name; a
    one-word line ("Ultra", "Pure") also not as its sentence's first word,
    where any word is capitalised."""
    written = match.group(0)
    if not written[:1].isupper() and not written[:1].isdigit():
        return False
    if ' ' not in line and not text[:match.start()].strip(' *_"“#-•\t'):
        return False
    return True


def vocabulary(brand, *, facts: Optional[dict] = None, study: Optional[dict] = None) -> Vocabulary:
    """The cycle's vocabulary: `facts` is BrandFactsCache.for_merchant()'s
    dict (the catalog snapshot's titles), `study` BrandTermsCache's
    {terms, product_names, rivals} (soa_shared/unprompted.brand_terms over
    the primary entity's name and aliases, tier_config.merchant.
    product_names, and the cycle's competitor entities)."""
    facts, study = facts or {}, study or {}
    titles = list(facts.get('product_titles') or []) + \
        [v.get('title') for v in facts.get('variants') or [] if isinstance(v, dict) and v.get('title')] + \
        list(study.get('product_names') or [])
    return Vocabulary(brand or facts.get('brand'), study.get('terms') or [], titles, study.get('rivals') or [])


# ─── Selection ─────────────────────────────────────────────────────────────

def _standalone_lines(text, vocab: Vocabulary, named: List[str]) -> List[dict]:
    """The brand's lines a unit writes without the brand before them, as
    name facts ("Swaddlers fit 8-14 lbs")."""
    out = []
    brand_tokens = {bfi.stem(t) for t in bfi.tokens(vocab.brand)}
    for line in named:
        if line not in vocab.lines:
            continue
        value = [t for t in bfi.tokens(line) if bfi.stem(t) not in brand_tokens and t not in bfi.GENERIC] \
            or bfi.tokens(line)
        out.append({'type': 'name', 'text': line, 'value': value})
    return out


def checkable(text, vocab: Vocabulary, *, own_domains=()) -> tuple:
    """(facts, qualifier, beyond): every checkable fact the unit states (the
    brand's lines it writes alone among them), the first product or line
    name it writes as the brand's (the one that qualifies it), and the facts
    beyond that name. A unit is a claim on `beyond`; it is judged on
    `facts`, so a line the brand never made is looked up even when it is
    the one that qualifies ("Pampers Little Snugglers fit up to 14 lbs")."""
    facts = bfi.facts_in(text, vocab.brand, own_domains=own_domains)
    names_written = [f for f in facts if f['type'] == 'name']
    for extra in _standalone_lines(text, vocab, vocab.names_brand(text)):
        covered = any({bfi.stem(t) for t in extra['value']} <= {bfi.stem(t) for t in f['value']}
                      for f in names_written)
        if not covered:
            facts.append(extra)
            names_written.append(extra)
    qualifier = names_written[0] if names_written else None
    return facts, (qualifier['text'] if qualifier else None), [f for f in facts if f is not qualifier]


def _rival_lines(answer, vocab: Vocabulary) -> List[str]:
    """The rivals the answer names, each with the names it writes as theirs
    ("Huggies Little Snugglers"), for the misattribution check."""
    out = []
    for rival in vocab.names_rival(answer):
        out.append(rival)
        for f in bfi.brand_names(answer, rival):
            name = f"{rival} {f['text']}"
            if name not in out:
                out.append(name)
    return out


def select(answer, *, question, vocab: Vocabulary, own_domains=()) -> dict:
    """The brand-direct record for one answer (coder version 4). See the module docstring."""
    units = span_segmenter.units(answer)
    claims, labels, hedges, no_fact, stores = [], [], 0, 0, []
    for unit in units:
        text = unit['text']
        named, via = vocab.names_brand(text), 'named'
        rival = bool(vocab.names_rival(text))
        if not named and not rival:
            if vocab.names_brand(unit['sentence']):
                named, via = vocab.names_brand(unit['sentence']), 'sentence'
            elif unit.get('lead_in') and vocab.names_brand(unit['lead_in']) and not vocab.names_rival(unit['lead_in']):
                named, via = vocab.names_brand(unit['lead_in']), 'lead_in'
        for domain in retailers_named(text):
            if domain not in {ea.normalize_domain(d) for d in own_domains} and bcv._BUY.search(text) \
                    and domain not in stores:
                stores.append(domain)
        if not named:
            continue
        is_hedged = hedged(unit)
        facts, qualifier, beyond = checkable(text, vocab, own_domains=own_domains)
        claim = None
        if not is_hedged and not pp.looks_unknown(text):
            if beyond:
                claim = 'fact'
            elif via == 'named' and bcv.overlap(text, question or '', vocab.brand,
                                                [bfi.tokens(n) for n in named]) >= bcv.ECHO_THRESHOLD:
                claim = 'restates'
        labels.append({'span_id': unit['id'], 'text': text, 'kind': 'assertion' if claim else 'none',
                       'modality': 'hedged' if is_hedged else 'asserted'})
        if claim:
            # 2O-5: the brand's lines the unit (or the sentence or lead-in it was
            # chosen by) names, for the slot its facts are checked in
            claims.append({'span_id': unit['id'], 'text': text, 'via': via, 'qualifier': qualifier,
                           'facts': facts, 'selected_for': claim,
                           'lines': [n for n in named if n in vocab.lines]})
        elif is_hedged:
            hedges += 1
        else:
            no_fact += 1
    return {
        'coder': {'version': ea.BRAND_CODER_VERSION, 'question': question, 'calls': []},
        'extraction_confident': True, 'extraction_note': None,
        'brand_mentioned': bool(vocab.names_brand(answer)),
        'spans': [{'id': u['id'], 'text': u['text'], 'inherits_hedge': u['inherits_hedge']} for u in units],
        'span_labels': labels,
        'brand_claims': [],
        'other_brands_named': [{'name': name, 'relation': 'comparison'} for name in _rival_lines(answer, vocab)],
        'retailer_mentions': [{'name': retailer_name(d), 'role': 'recommendation'} for d in stores],
        'recommended_retailers': [retailer_name(d) for d in stores],
        'sources_cited': [],
        'selector': {'vocabulary': vocab.stamp(), 'units': len(units), 'about_brand': len(labels),
                     'hedged': hedges, 'no_fact': no_fact, 'claims': claims,
                     'question_lines': [n for n in vocab.names_brand(question or '') if n in vocab.lines]},
    }


def claim_set(extraction) -> Optional[List[str]]:
    """The claim sentences a stored brand-direct row was decided on: a
    version-4 row's selection, a version-3 row's settling call's spans,
    None for a row with neither (an older coder, an unsettled call)."""
    x = extraction if isinstance(extraction, dict) else {}
    coder = x.get('coder') if isinstance(x.get('coder'), dict) else {}
    version = coder.get('version') or 0
    if version >= 4:
        return [c.get('text') for c in (x.get('selector') or {}).get('claims') or []]
    if version == 3 and coder.get('pair'):
        return bcv.claim_spans(coder['calls'][coder['pair'][0]])
    return None


# ─── The verdict ───────────────────────────────────────────────────────────

def decide(record, expectation, *, index: 'bfi.FactIndex', own_domains=()) -> dict:
    """{outcome, reason, reason_code, brand_claim} for a version-4 record:
    every selected claim judged against the index, the worst decides."""
    record = record or {}
    brand = (expectation or {}).get('brand') or index.brand or 'the brand'
    question = ((record.get('coder') or {}).get('question')) or ''
    others = bcv.other_brand_names(record)
    claims = (record.get('selector') or {}).get('claims') or []
    spans = []
    for claim in claims:
        judged = bcv.judge_span(claim['text'], question=question, brand=brand, index=index, others=others,
                                own_domains=own_domains, facts=claim.get('facts') or [],
                                line=claim.get('qualifier'), lines=claim.get('lines') or (),
                                question_lines=(record.get('selector') or {}).get('question_lines') or ())
        judged.update(via=claim.get('via'), qualifier=claim.get('qualifier'))
        spans.append(judged)
    decided = bcv.decide(record, expectation, question=question, index=index, own_domains=own_domains, spans=spans)
    selector = record.get('selector') or {}
    decided['brand_claim'].update(selector={k: selector.get(k) for k in ('units', 'about_brand', 'hedged', 'no_fact')},
                                  vocabulary=(selector.get('vocabulary') or {}).get('digest'))
    return decided
