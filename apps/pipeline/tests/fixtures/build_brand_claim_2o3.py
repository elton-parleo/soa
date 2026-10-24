"""2O-3 (B2): builds the brand-claim verdict's fixtures in tests/fixtures/brand_claim/.
No model call, and nothing read from production. No OPEN_AI_API_KEY was present
in the session that wrote 2O-3, so nothing here is a recording: every record is
built with the pipeline's own segmenter and labels (parser/extraction_postprocess.
apply_labels), as a labelling call leaves it.

  fl13_record_pages.json  the brand's fact index inputs, FL13-shaped: the 10
          variants of the FL13-shaped console fixture (apps/api/tests/
          console_fixture_2j2.py: Pampers at Walmart and Amazon), as the record
          (titles, sizes, counts, list prices, weight ranges, retailer list) and
          as the cycle's cached retailer-prices rows (each retailer's price) plus
          one own-page read per line (title, bullets, JSON-LD, size chart). The
          page text and the size chart are the FIXTURE'S, hand-written, not
          pampers.com's: the FL13 fixture's own pages were never read ("not read
          yet"), and supply's rows in this repo's fixtures carry no bullets or
          JSON-LD at all.
  fl14_shaped_runs.json   FL14-pampers-20261023's brand-direct tier, 258 answers
          (PAM_207..PAM_249 x six agents), with two "recordings" each (run 1,
          run 2). The 66 answers the Oct 24 printout (fl14-coder-run2.txt) moved
          between run 1 and run 2 carry that printout's categories, verbatim; the
          192 others carry the same category twice, placed so each run's counts
          are the printout's "before" (run 1) and "after" (run 2). Each record
          classifies under the version-2 rule exactly as its category says
          (the test checks it), so the 66 moves are reproduced.

          HOW A MOVE IS BUILT, and this is an assumption, not a recording: the
          two runs differ in one sentence the labeller called an asserted claim
          in one run and `none` in the other (W), plus the cited source a
          version-2 category needs. That is the mechanism 2O-1 named (labelling
          wobble). W cycles through BANK, whose share of recommendation-only
          sentences (7 of 16) is FL12's 2K-1 hand-check (7 of 16 brand-direct
          answers recommendation-only, docs/console-read-models.md); 6 of the 7
          state no checkable fact, the seventh names a line. If
          FL14's moves were source wobble rather than span wobble, the new
          verdict would move fewer; if more of the wobbling sentences carried a
          fact, more. The figure the test reports is this fixture's, not a
          prediction of FL14's: the two rescores Elton runs measure that.

    cd apps/pipeline && python3 tests/fixtures/build_brand_claim_2o3.py
"""
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from parser import extraction_postprocess as pp  # noqa: E402
from scoring import brand_direct_classifier as bdc  # noqa: E402

OUT = os.path.join(HERE, 'brand_claim')
BRAND, DOMAIN = 'Pampers', 'pampers.com'
RETAILERS = ['walmart.com', 'amazon.com']

#: console_fixture_2j2.VARIANTS: (label, sku, gtin or None, Walmart price); Amazon reads $3.00 above
VARIANTS = (
    ('Swaddlers NB 84', 'PAM-SW-NB-84', '00037000863434', '24.97'),
    ('Swaddlers S1 96', 'PAM-SW-1-96', '00037000863441', '27.97'),
    ('Swaddlers S2 84', 'PAM-SW-2-84', '00037000863458', '27.97'),
    ('Baby Dry S3 136', 'PAM-BD-3-136', '00037000863465', '29.97'),
    ('Cruisers 360 S4 104', 'PAM-CR360-4-104', '00037000863472', '39.97'),
    ('Easy Ups S5 66', 'PAM-EU-5-66', '00037000863489', '34.97'),
    ('Ultra', 'PAM-ULTRA-120', None, '22.97'),
    ('Pure', 'PAM-PURE-2-74', None, '31.97'),
    ('AMORE', 'PAM-AMORE-3-60', None, '26.97'),
    ('Cruisers S5', 'PAM-CR-5-92', None, '37.97'),
)
#: the FIXTURE'S size chart, lb (hand-written; not read from pampers.com)
CHART = [('newborn', None, 10), ('1', 8, 14), ('2', 12, 18), ('3', 16, 28), ('4', 22, 37), ('5', 27, None),
         ('6', 35, None)]
#: the FIXTURE'S own-page text per line (hand-written; not read from pampers.com)
PAGES = {
    'Swaddlers': ('Pampers Swaddlers Diapers', ['Wetness indicator that changes color', 'Umbilical cord notch',
                                                 'Hypoallergenic and free of parabens and latex']),
    'Baby Dry': ('Pampers Baby Dry Diapers', ['Up to 12 hours of overnight protection', 'LeakGuard barriers']),
    'Cruisers 360': ('Pampers Cruisers 360 Diapers', ['Stretchy waistband for 360 fit', 'Up to 100% leakproof']),
    'Easy Ups': ('Pampers Easy Ups Training Underwear', ['Tear-away sides', 'Pull-on training pants']),
    'Pure': ('Pampers Pure Protection Diapers', ['Fragrance free', 'Hypoallergenic', 'Plant-based liner']),
    'AMORE': ('Pampers AMORE Diapers', ['Hypoallergenic', 'Cotton-enhanced liner']),
}
#: fl14-coder-run2.txt, the 66 brand-direct moves between run 1 and run 2, verbatim: (code, agent, run 1, run 2, run id)
MOVES = [
    ('PAM_207', 'perplexity', 'fabricated', 'echoed', 14955),
    ('PAM_208', 'perplexity', 'fabricated', 'grounded', 14958),
    ('PAM_210', 'perplexity', 'grounded', 'fabricated', 14959),
    ('PAM_211', 'perplexity', 'fabricated', 'grounded', 14965),
    ('PAM_214', 'perplexity', 'echoed', 'fabricated', 14969),
    ('PAM_213', 'perplexity', 'fabricated', 'grounded', 14971),
    ('PAM_218', 'perplexity', 'fabricated', 'grounded', 14977),
    ('PAM_223', 'perplexity', 'fabricated', 'grounded', 14989),
    ('PAM_224', 'perplexity', 'fabricated', 'echoed', 14991),
    ('PAM_225', 'perplexity', 'echoed', 'fabricated', 14992),
    ('PAM_222', 'perplexity', 'acknowledged_unknown', 'echoed', 14994),
    ('PAM_226', 'perplexity', 'fabricated', 'echoed', 14996),
    ('PAM_230', 'perplexity', 'fabricated', 'echoed', 15008),
    ('PAM_241', 'perplexity', 'fabricated', 'echoed', 15023),
    ('PAM_242', 'perplexity', 'echoed', 'grounded', 15024),
    ('PAM_239', 'perplexity', 'echoed', 'grounded', 15025),
    ('PAM_243', 'perplexity', 'fabricated', 'echoed', 15028),
    ('PAM_248', 'perplexity', 'fabricated', 'grounded', 15035),
    ('PAM_247', 'perplexity', 'fabricated', 'grounded', 15041),
    ('PAM_211', 'gemini_grounded', 'fabricated', 'grounded', 15047),
    ('PAM_218', 'gemini_grounded', 'echoed', 'fabricated', 15074),
    ('PAM_237', 'gemini_grounded', 'echoed', 'fabricated', 15120),
    ('PAM_238', 'gemini_grounded', 'echoed', 'fabricated', 15121),
    ('PAM_213', 'aimode', 'echoed', 'fabricated', 15181),
    ('PAM_210', 'chatgpt', 'acknowledged_unknown', 'grounded', 15210),
    ('PAM_231', 'aimode', 'fabricated', 'echoed', 15221),
    ('PAM_208', 'copilot', 'echoed', 'grounded', 15237),
    ('PAM_217', 'chatgpt', 'acknowledged_unknown', 'grounded', 15239),
    ('PAM_209', 'copilot', 'fabricated', 'grounded', 15241),
    ('PAM_219', 'chatgpt', 'misattributed', 'grounded', 15244),
    ('PAM_210', 'copilot', 'fabricated', 'acknowledged_unknown', 15245),
    ('PAM_239', 'aimode', 'fabricated', 'echoed', 15255),
    ('PAM_243', 'aimode', 'grounded', 'echoed', 15263),
    ('PAM_215', 'copilot', 'fabricated', 'grounded', 15266),
    ('PAM_229', 'chatgpt', 'grounded', 'unscoreable', 15269),
    ('PAM_246', 'aimode', 'fabricated', 'echoed', 15274),
    ('PAM_220', 'copilot', 'echoed', 'grounded', 15283),
    ('PAM_221', 'copilot', 'grounded', 'acknowledged_unknown', 15287),
    ('PAM_225', 'copilot', 'fabricated', 'grounded', 15303),
    ('PAM_229', 'copilot', 'fabricated', 'echoed', 15314),
    ('PAM_231', 'copilot', 'fabricated', 'acknowledged_unknown', 15324),
    ('PAM_244', 'chatgpt', 'echoed', 'grounded', 15327),
    ('PAM_245', 'chatgpt', 'grounded', 'echoed', 15332),
    ('PAM_233', 'copilot', 'echoed', 'acknowledged_unknown', 15334),
    ('PAM_239', 'chatgpt', 'grounded', 'echoed', 15337),
    ('PAM_235', 'copilot', 'grounded', 'fabricated', 15342),
    ('PAM_236', 'copilot', 'grounded', 'fabricated', 15350),
    ('PAM_238', 'copilot', 'grounded', 'fabricated', 15361),
    ('PAM_240', 'copilot', 'grounded', 'echoed', 15365),
    ('PAM_242', 'copilot', 'fabricated', 'grounded', 15368),
    ('PAM_243', 'copilot', 'fabricated', 'echoed', 15369),
    ('PAM_245', 'copilot', 'grounded', 'echoed', 15377),
    ('PAM_247', 'copilot', 'fabricated', 'grounded', 15382),
    ('PAM_246', 'copilot', 'fabricated', 'echoed', 15384),
    ('PAM_249', 'copilot', 'fabricated', 'echoed', 15389),
    ('PAM_209', 'claude', 'unscoreable', 'fabricated', 15404),
    ('PAM_212', 'claude', 'unscoreable', 'fabricated', 15414),
    ('PAM_225', 'claude', 'grounded', 'fabricated', 15436),
    ('PAM_231', 'claude', 'echoed', 'fabricated', 15442),
    ('PAM_232', 'claude', 'misattributed', 'echoed', 15443),
    ('PAM_234', 'claude', 'misattributed', 'fabricated', 15445),
    ('PAM_238', 'claude', 'misattributed', 'fabricated', 15449),
    ('PAM_240', 'claude', 'fabricated', 'echoed', 15451),
    ('PAM_243', 'claude', 'echoed', 'fabricated', 15454),
    ('PAM_245', 'claude', 'fabricated', 'echoed', 15456),
    ('PAM_249', 'claude', 'echoed', 'fabricated', 15460),
]
#: each run's counts, the printout's "before" (run 1) and "after" (run 2)
RUN1 = {'absent': 6, 'acknowledged_unknown': 5, 'echoed': 54, 'fabricated': 124, 'grounded': 61, 'misattributed': 4,
        'unscoreable': 4}
RUN2 = {'absent': 6, 'acknowledged_unknown': 6, 'echoed': 61, 'fabricated': 112, 'grounded': 70, 'unscoreable': 3}
AGENTS = ('perplexity', 'gemini_grounded', 'aimode', 'chatgpt', 'copilot', 'claude')
CODES = [f'PAM_{n}' for n in range(207, 250)]

#: the sentence a run asserts (and a move wobbles on): 7 of 16 recommendation-only, 6 of them with no checkable fact
BANK = [
    "Pampers Swaddlers are widely considered the gold standard for newborns.",               # name only
    "Pampers is a trusted choice that many parents love.",                                  # no fact
    "Pampers Swaddlers Size 1 fit babies 8-14 lbs.",                                        # on the index
    "Pampers Baby Dry offers up to 12 hours of overnight protection.",                      # on the index
    "Most parents find Pampers comfortable and reliable.",                                  # no fact
    "Pampers Swaddlers Size 1 fit babies 6-12 lbs.",                                        # not on it
    "Pampers Pure Protection is fragrance free and hypoallergenic.",                        # on the index
    "Honestly, Pampers is the best overall pick for most families.",                        # no fact
    "Pampers Cruisers 360 come in a 120 count box.",                                        # not on it
    "You can buy Pampers Swaddlers at Walmart or Amazon.",                                  # on the index
    "It is a dependable everyday option that works well overnight.",                        # no fact
    "Pampers Swaddlers are sold at Target and Kroger.",                                      # not on it
    "Parents rave about how soft Pampers feel.",                                            # no fact
    "Pampers AMORE has a cotton-enhanced liner.",                                           # on the index
    "Pampers is a great brand to start with.",                                              # no fact
    "Pampers Swaddlers Overnights cost about $45 at Walmart.",                              # not on it
]
NO_FACT = (1, 4, 7, 10, 12, 14)
UNKNOWN = "I couldn't find current details for that exact product."
OTHER = "Pampers Little Snugglers fit babies up to 14 lbs."
OTHER_BRAND = 'Huggies Little Snugglers'
QUESTIONS = [
    "Are Pampers Swaddlers good for newborns?", "What sizes do Pampers diapers come in?",
    "Is Pampers Pure Protection fragrance free?", "Where can I buy Pampers Swaddlers?",
    "How long do Pampers Baby Dry last overnight?", "What weight do Pampers Swaddlers Size 1 fit?",
    "Are Pampers Cruisers 360 good for active babies?", "Is Pampers a good diaper brand?",
]

BASE = {'prices': [], 'codes': [], 'pack_counts': [], 'sizes': [], 'gtins': [], 'member_prices': [], 'points': [],
        'brand_unknown_statement': None, 'other_brands_named': [], 'loyalty_tiers_named': [], 'brand_claims': [],
        'sources_cited': [], 'recommended_retailers': [], 'postprocess': [], 'extraction_confident': True,
        'extraction_note': None}


def record(answer, asserted, category):
    """One run's record for `answer`: the sentences in `asserted` labelled
    asserted assertions, the cannot-find sentence labelled so, the rest none;
    the cited source and other brand the version-2 category needs."""
    fields = {'brand_mentioned': category != 'absent'}
    if category == 'grounded':
        fields['sources_cited'] = [DOMAIN]
    elif category in ('echoed', 'acknowledged_unknown') and asserted:
        fields['sources_cited'] = ['babycenter.com']   # sourced: not fabricated, and not the brand's own
    if category == 'misattributed':
        fields['other_brands_named'] = [{'name': OTHER_BRAND, 'presented_as': 'closest_match'}]
    if category == 'unscoreable':
        fields.update(extraction_confident=False, extraction_note='the answer could not be read')
    spans = pp.segment(answer)
    labels = {'spans': [{'span_id': s['id'],
                         'kind': ('assertion' if s['text'] in asserted else
                                  'unknown_statement' if s['text'] == UNKNOWN and category == 'acknowledged_unknown'
                                  else 'none'),
                         'modality': 'asserted'} for s in spans],
              'other_brands': [{'name': OTHER_BRAND, 'relation': 'closest_match_described'}]
              if category == 'misattributed' else [],
              'retailers': []}
    rec = pp.apply_labels({**BASE, **fields}, labels, answer_text=answer, brand=BRAND)
    rec['brand_mentioned'] = fields['brand_mentioned']
    return rec


def answer_for(i, cats, moved):
    """The answer text and each run's record. A moved answer wobbles on W:
    asserted in a fabricated run, `none` in the others."""
    w = BANK[i % len(BANK)]
    sentences = [w]
    if 'acknowledged_unknown' in cats:
        sentences.insert(0, UNKNOWN)
    if 'misattributed' in cats:
        sentences.append(OTHER)
    text = ' '.join(sentences)
    if 'absent' in cats:
        text = "Most parents find disposable diapers comfortable and reliable."
    records = []
    for c in cats:
        if c == 'misattributed':
            asserted = [OTHER]
        elif moved:
            asserted = [w] if c == 'fabricated' else []
        else:
            asserted = [] if c in ('absent', 'unscoreable') else [w]
        records.append(record(text, asserted, c))
    return text, records


def fl13_record_pages() -> dict:
    variants, prices = [], []
    titles = []
    for n, (label, sku, gtin, walmart) in enumerate(VARIANTS):
        line = next((k for k in sorted(PAGES, key=len, reverse=True) if label.startswith(k)), label.split()[0])
        size = next((p[1:] for p in label.split() if p[:1] == 'S' and p[1:].isdigit()), 'newborn' if ' NB ' in f' {label} ' else None)
        count = int(label.split()[-1]) if label.split()[-1].isdigit() and len(label.split()) > 1 else None
        title = f"Pampers {label}"
        titles.append(title)
        chart = next(({'min': lo, 'max': hi} for s, lo, hi in CHART if s == size), None)
        variants.append({'title': title, 'size': size, 'count': count, 'list_price': None, 'member_price': None,
                         'weight_range': chart, 'attributes': {}})
        for retailer in RETAILERS:
            price = walmart if retailer == 'walmart.com' else f"{float(walmart) + 3.0:.2f}"
            prices.append({'variant_ref': f'feed_sku:{900 + n}', 'gtin': gtin, 'sku': sku, 'variant_label': label,
                           'retailer_domain': retailer, 'role': 'retailer', 'price': price, 'currency': 'USD',
                           'method': 'json_ld', 'read_status': 'ok', 'verifiable': True})
    for line, (title, bullets) in PAGES.items():
        prices.append({'variant_ref': None, 'retailer_domain': DOMAIN, 'role': 'own', 'price': None,
                       'verifiable': False, 'method': 'none_by_design', 'page_title': title, 'bullets': bullets,
                       'json_ld': {'@type': 'Product', 'name': title, 'brand': 'Pampers'},
                       'size_chart': [{'size': s, 'min': lo, 'max': hi} for s, lo, hi in CHART]})
    return {
        '_note': ("FL13-SHAPED, HAND-BUILT. The record and retailer rows are console_fixture_2j2's 10 variants; the "
                  "own-page titles, bullets, JSON-LD and size chart are the fixture's, not pampers.com's. Built by "
                  "tests/fixtures/build_brand_claim_2o3.py. Nothing was read from production."),
        'facts': {'brand': BRAND, 'domain': DOMAIN, 'own_domains': [DOMAIN], 'retailer_list': RETAILERS,
                  'tier_names': [], 'program_name': None, 'product_titles': titles, 'variants': variants,
                  'features': [], 'descriptions': []},
        'reference': {'merchant': 'pampers', 'kind': 'brand', 'as_of': '2026-10-19T14:00:00+00:00', 'prices': prices},
    }


def fl14_shaped_runs() -> dict:
    moved = {(m[0], m[1]): m for m in MOVES}
    rest1 = Counter(RUN1) - Counter(m[2] for m in MOVES)
    assert Counter(RUN2) - Counter(m[3] for m in MOVES) == rest1
    stable = [c for c in sorted(rest1) for _ in range(rest1[c])]
    answers, i, k = [], 0, 0
    for code_n, code in enumerate(CODES):
        for agent in AGENTS:
            m = moved.get((code, agent))
            cats = [m[2], m[3]] if m else [stable[k]] * 2
            if not m:
                k += 1
            text, records = answer_for(i, cats, bool(m))
            i += 1
            answers.append({'query_code': code, 'agent': agent, 'run_id': m[4] if m else None,
                            'question': QUESTIONS[code_n % len(QUESTIONS)], 'answer': text,
                            'v2': cats, 'runs': records})
    assert len(answers) == 258 and k == len(stable)
    expect = {'brand': BRAND, 'domain': DOMAIN, 'type': 'brand_mention'}
    for a in answers:
        for c, r in zip(a['v2'], a['runs']):
            got = bdc.classify(r, expect, brand_facts={'domain': DOMAIN, 'own_domains': [DOMAIN]})[0]
            assert got == c, (a['query_code'], a['agent'], c, got)
    return {
        '_note': ("FL14-SHAPED, NOT RECORDED. Built by tests/fixtures/build_brand_claim_2o3.py from the Oct 24 "
                  "printout (fl14-coder-run2.txt: 258 brand-direct answers, 66 moved between run 1 and run 2). Each "
                  "move is built as one sentence asserted in one run and not the other (see the builder's "
                  "docstring: an assumption). Nothing was read from production."),
        'cycle_code': 'FL14-pampers-20261023', 'run1': RUN1, 'run2': RUN2, 'answers': answers,
    }


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for name, build in (('fl13_record_pages.json', fl13_record_pages), ('fl14_shaped_runs.json', fl14_shaped_runs)):
        with open(os.path.join(OUT, name), 'w') as fh:
            json.dump(build(), fh, indent=1)
            fh.write('\n')
        print(f"wrote {os.path.join(OUT, name)}")
