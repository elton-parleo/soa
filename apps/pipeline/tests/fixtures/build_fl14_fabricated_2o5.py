"""
2O-5: FL14's 170 fabricated brand-direct answers, SHAPED FROM THE PRINTOUT'S
BREAKDOWN, not recorded.

    python3 tests/fixtures/build_fl14_fabricated_2o5.py /path/to/a/2o4/checkout/apps/pipeline

fl14-v14-run2.txt (2O-4, the second run, 0 moved): 258 brand-direct answers,
fabricated 170, "fabricated, by the fact missing: price 60, retailer 48,
name 48, size 26, count 21, attribute 58" (261 facts over 170 answers: the
deciding sentence can miss more than one). The printout gives the counts and
nothing of the sentences, so the sentences here are written to the counts:

  * 79 answers miss one fact (price 20, retailer 18, name 20, size 6,
    count 5, attribute 10) and 91 miss two (price+retailer 25, price+
    attribute 15, retailer+attribute 5, name+attribute 18, name+size 10,
    size+count 10, count+attribute 6, attribute+attribute 2): an
    ASSUMPTION, the only one that changes the per-answer split below; the
    per-type totals are the printout's;
  * every value is one the brand publishes or plausibly could: a size,
    count or line from supply's recorded pampers.com pages
    (pampers_brand_pages_2o5.json: Swaddlers Size 7, a 148 count box, Zzz),
    a real store, a real Pampers line not read (Ninjamas, Splashers), an
    attribute word. The printout's own reading ("Swaddlers Size 2 exists;
    Walgreens sells Pampers; pampers.com publishes no price"). None is a
    value the brand states otherwise, so nothing here is contradicted:
    whether FL14's real answers are is what Elton's rescore says.

The pilot index is FL14-SHAPED: the FL13-shaped record and retailer rows
(fl13_record_pages.json) with the hand-built JSON-LD and size charts taken
off its own-page rows, as supply serves them today (page title and bullets,
no hasVariant, no chart). Every answer's 2O-4 verdict is recorded under
`v14` by running the 2O-4 code (the checkout named on the command line,
main at #144) against that index, and the builder refuses to write unless
all 170 are fabricated and the missing facts total the printout's. Nothing
was read from production.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'brand_claim', 'fl14_fabricated_2o5.json')
PRINTOUT = {'price': 60, 'retailer': 48, 'name': 48, 'size': 26, 'count': 21, 'attribute': 58}
ALLOCATION = [
    (('price',), 20), (('retailer',), 18), (('name',), 20), (('size',), 6), (('count',), 5), (('attribute',), 10),
    (('price', 'retailer'), 25), (('price', 'attribute'), 15), (('retailer', 'attribute'), 5),
    (('name', 'attribute'), 18), (('name', 'size'), 10), (('size', 'count'), 10), (('count', 'attribute'), 6),
    (('attribute', 'attribute'), 2),
]
PRICES = ['$38.49', '$41.29', '$52.79', '$33.19', '$47.63']
STORES = ['Walgreens', 'CVS', 'Kroger', 'Costco', "Sam's Club", 'Dollar General']
LINES = ['Zzz', 'Ninjamas', 'Splashers']                     # real lines the pilot never read
SIZES = [('Swaddlers', 'Size 7'), ('Swaddlers', 'Size 8'), ('Swaddlers', 'Preemie size'),
         ('Cruisers 360', 'Size 7'), ('Cruisers 360', 'Size 6')]
COUNTS = [('Swaddlers', '148'), ('Swaddlers', '120'), ('Swaddlers', '186'), ('Cruisers 360', '116'),
          ('Cruisers 360', '88')]
WORDS = ['breathable', 'dermatologist tested', 'pediatrician recommended', 'chlorine free', 'aloe',
         'extra absorb channels', 'blowout barrier', 'heart quilts']
AGENTS = ['chatgpt', 'perplexity', 'gemini_grounded', 'copilot', 'aimode', 'claude']
QUESTIONS = ['Tell me about Pampers diapers.', 'Are Pampers diapers worth it?', 'Is Pampers a good diaper brand?']


def sentence(kinds, i):
    p, store, line = PRICES[i % 5], STORES[i % 6], LINES[i % 3]
    sline, size = SIZES[i % 5]
    cline, count = COUNTS[i % 5]
    w1, w2 = WORDS[i % 8], WORDS[(i + 3) % 8]
    return {
        ('price',): f"Pampers Swaddlers cost {p} a box.",
        ('retailer',): f"You can also buy Pampers Swaddlers at {store}.",
        ('name',): f"Pampers Swaddlers and Pampers {line} are both popular with parents.",
        ('size',): f"Pampers {sline} also come in {size}.",
        ('count',): f"Pampers {cline} come in a {count} count box.",
        ('attribute',): f"Pampers Swaddlers are {w1}.",
        ('price', 'retailer'): f"Pampers Swaddlers cost {p} at {store}.",
        ('price', 'attribute'): f"Pampers Swaddlers are {w1} and cost {p}.",
        ('retailer', 'attribute'): f"{store} carries Pampers Swaddlers, which are {w1}.",
        ('name', 'attribute'): f"Pampers {line} are {w1}.",
        ('name', 'size'): f"Pampers {line} also come in Size 6.",
        ('size', 'count'): f"Pampers Swaddlers {size if sline == 'Swaddlers' else 'Size 7'} come in a 120 count box.",
        ('count', 'attribute'): f"Pampers Swaddlers come in a 148 count box and are {w1}.",
        ('attribute', 'attribute'): f"Pampers Swaddlers are {w1} and {w2}.",
    }[kinds]


def answers():
    out, n = [], 0
    for kinds, k in ALLOCATION:
        for i in range(k):
            n += 1
            out.append({'id': n, 'agent': AGENTS[n % 6], 'question': QUESTIONS[n % 3], 'kinds': list(kinds),
                        'answer': f"Pampers is a well-known diaper brand. {sentence(kinds, i)}"})
    return out


def pilot():
    """The FL14-shaped pilot: fl13_record_pages.json, its own-page rows as supply serves them."""
    fl13 = json.load(open(os.path.join(HERE, 'brand_claim', 'fl13_record_pages.json')))
    rows = [{k: v for k, v in r.items() if not (r.get('role') == 'own' and k in ('json_ld', 'size_chart'))}
            for r in fl13['reference']['prices']]
    return fl13['facts'], {**fl13['reference'], 'prices': rows}


V14 = r'''
import json, sys
from scoring import brand_claim_selector as sel, brand_fact_index as bfi
from soa_shared import expected_answers as ea
body = json.load(sys.stdin)
facts, reference = body['facts'], body['reference']
index = bfi.build(facts, reference)
vocab = sel.vocabulary('Pampers', facts=facts, study={'terms': ['Pampers'], 'product_names': [],
                                                   'rivals': ['Huggies', 'Luvs']})
out = []
for a in body['answers']:
    record = sel.select(a['answer'], question=a['question'], vocab=vocab, own_domains=['pampers.com'])
    d = sel.decide(record, ea.brand_mention('Pampers', 'pampers.com'), index=index, own_domains=['pampers.com'])
    at = d['brand_claim']['decided_by']
    span = d['brand_claim']['spans'][at] if at is not None else {}
    out.append({'outcome': d['outcome'], 'reason_code': d['reason_code'],
                'missing': [f['type'] for f in span.get('facts_missing') or []]})
print(json.dumps({'index': index.stamp(), 'verdicts': out}))
'''


def main(v14_tree):
    facts, reference = pilot()
    rows = answers()
    done = subprocess.run([sys.executable, '-c', V14], cwd=v14_tree, capture_output=True, text=True, check=True,
                          input=json.dumps({'facts': facts, 'reference': reference, 'answers': rows}))
    result = json.loads(done.stdout)
    missing = {}
    wrong = []
    for row, verdict in zip(rows, result['verdicts']):
        row['v14'] = verdict
        for kind in verdict['missing']:
            missing[kind] = missing.get(kind, 0) + 1
        if not (verdict['outcome'] == 'fabricated' and sorted(verdict['missing']) == sorted(row['kinds'])):
            wrong.append((row['answer'], verdict))
    assert not wrong, '\n'.join(map(str, wrong))
    assert missing == PRINTOUT, missing
    body = {'_note': __doc__.strip().split('\n\n')[0], 'printout': {'answers': 258, 'fabricated': 170,
                                                                    'missing': PRINTOUT},
            'v14_index': result['index'], 'answers': rows}
    with open(OUT, 'w') as fh:
        json.dump(body, fh, indent=1, sort_keys=True)
        fh.write('\n')
    print(f"wrote {OUT}: {len(rows)} answers, 2O-4 missing {missing}, 2O-4 index {result['index']['size']} facts")


if __name__ == '__main__':
    main(sys.argv[1])
