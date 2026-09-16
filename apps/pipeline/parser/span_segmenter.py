"""
Cutting an answer into the spans a label can be attached to.

Round four's failure class, and the last one that was still the model's
to get wrong. Three rounds moved judgements out of the transcriber; what
stayed behind was the transcriber choosing where a sentence starts and
stops, and it chose badly in four distinguishable ways:

  * it merged two sentences and the first one's hedge suppressed the
    second's claim. "It seems there might be a slight misunderstanding.
    **Wiggle & Snug is a private label brand sold exclusively at
    Kohl's.**" came back as one span, marked hedged. The second sentence
    is not hedged; it is the false claim the tier exists to catch.
  * it ran a span past a clause break. "I couldn't verify a product
    specifically branded 'Wiggle & Snug Cloud Wipes', but the 3-pack
    'Cloud Moist' wipes are listed as hypoallergenic..." was filed whole
    as a cannot-find statement, taking a product claim with it.
  * same again with a leading subordinate clause: "While I don't find a
    product specifically named 'Wiggle & Snug Bum Balm,' the Wiggle &
    Giggle ... is a very popular and similarly named product."
  * and it simply left sentences out. "It appears that Wiggle & Snug Bum
    Balm 4 oz has been discontinued" — the headline claim of the whole
    answer — reached neither the claims nor the unknown statement, and
    nothing recorded that it had gone missing.

So the answer is cut up HERE, deterministically, and the labeller is
handed a numbered list it can only label. It cannot merge two spans,
extend one, or re-quote the text: the text is ours and the only thing
coming back is an id and two enum values. That also makes the coverage
check possible — every span naming the brand has to come back labelled,
and one that does not is a finding rather than an absence.

Verbatim is the contract. Every span returned is a substring of the
answer, so a reader checking a label can find the words in the stored
answer and nothing has been paraphrased on the way.
"""
import re

# A period that ends a sentence is followed by whitespace and then
# something that starts one. Markdown is everywhere in these answers, so
# an opening bold marker or a quote counts as a start.
_SENTENCE_END = re.compile(r'(?<=[.!?])["”’*]*\s+(?=["“*_#\-•]*[A-Z0-9])')

# Periods that do not end anything. Decimals are handled by the pattern
# above — "15.79" has no space after the dot — but these do have one.
#
# Units are deliberately NOT here. "4 oz." ends a sentence as often as it
# sits inside one, and the lookahead already protects the mid-sentence
# case: "a 4 oz. jar" does not split, because "jar" is lowercase. Listing
# oz. as an abbreviation cost a whole sentence — the one saying no
# product page for this brand could be found — which then reached neither
# the claims nor the unknown statement and was recorded nowhere.
_ABBREVIATIONS = (
    'e.g.', 'i.e.', 'etc.', 'vs.', 'approx.', 'no.',
    'mr.', 'mrs.', 'ms.', 'dr.', 'st.', 'inc.', 'co.', 'u.s.',
)

# Clause breaks. A contrast is a new claim: the half after "but" is
# routinely a different kind of statement from the half before it, which
# is exactly how a cannot-find swallowed a product claim.
_CLAUSE = re.compile(
    r'(?<=[,;])\s+(?=but\b|however\b|although\b|though\b|while\b|whereas\b)'
    r'|(?<=;)\s+'
    r'|(?<=—)\s+(?=but\b|however\b)',
    re.I,
)

# A leading subordinate clause: "While I don't find X, the Y is ...". The
# comma that closes it is a boundary, and the pattern is anchored at the
# start so a mid-sentence "while" does not split on its own comma.
_LEADING_CLAUSE = re.compile(
    r'^(\s*[*_"“]*(?:while|although|though|whereas)\b.{5,240}?,["”’*]*)\s+(?=\S)',
    re.I | re.S,
)

MIN_SPAN_CHARS = 3


def _ends_with_abbreviation(text: str) -> bool:
    lowered = text.lower().rstrip('"”’*)')
    return any(lowered.endswith(a) for a in _ABBREVIATIONS)


def _split_sentences(line: str):
    out, start = [], 0
    for match in _SENTENCE_END.finditer(line):
        piece = line[start:match.start()]
        if _ends_with_abbreviation(piece):
            continue
        out.append(piece)
        start = match.end()
    out.append(line[start:])
    return [p for p in out if p.strip()]


def _split_clauses(sentence: str):
    leading = _LEADING_CLAUSE.match(sentence)
    if leading:
        head = leading.group(1)
        rest = sentence[leading.end():]
        return [head] + _split_clauses(rest) if rest.strip() else [head]
    parts = _CLAUSE.split(sentence)
    return [p for p in parts if p.strip()]


def segment(answer_text) -> list:
    """
    [{'id': 1, 'text': '...'}, ...] — every span a verbatim substring of
    the answer, in order, ids from 1.

    Lines come first because these answers are half bullet list: a
    newline ends a span whatever punctuation is or is not there, and a
    list item is its own claim.
    """
    text = str(answer_text or '')
    spans = []
    for line in text.split('\n'):
        if not line.strip():
            continue
        for sentence in _split_sentences(line):
            for clause in _split_clauses(sentence):
                stripped = clause.strip()
                if len(stripped) >= MIN_SPAN_CHARS:
                    spans.append(stripped)

    return [{'id': i, 'text': span} for i, span in enumerate(spans, start=1)]


def covers(answer_text, spans) -> bool:
    """Whether every span is verbatim in the answer. The contract, as an
    assertion — a paraphrased span is a label attached to words nobody
    said."""
    text = str(answer_text or '')
    return all(span['text'] in text for span in spans)
