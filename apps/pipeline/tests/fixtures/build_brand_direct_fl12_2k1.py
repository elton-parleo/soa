"""2K-1 §3: builds packages/testing/fixtures/brand_direct_fl12_2k1.json, the FL12-shaped brand-direct fixture for 2K-1 §3 with the pipeline's
own segmenter (parser/extraction_postprocess.apply_labels) and checks each row
with the frozen classifier. Every span is labelled an asserted assertion, as the
labeller labels a plain declarative sentence. No model call.

    cd apps/pipeline && python3 tests/fixtures/build_brand_direct_fl12_2k1.py \
        ../../packages/testing/fixtures/brand_direct_fl12_2k1.json
"""
import json, sys
sys.path.insert(0, '.')
from parser import extraction_postprocess as pp
from scoring import brand_direct_classifier as bdc

# (answer text, structured values the transcription fills, a reader's label, note)
ROWS = [
    ("For a newborn, you should buy Pampers Swaddlers. They are widely considered the gold standard.", {},
     'recommendation_only', "the brief's example: a recommendation, nothing checkable"),
    ("Pampers Swaddlers are the most popular newborn diaper in US hospitals.", {},
     'attribute', "a checkable claim (hospital use) outside the brief's list: the rule misses it"),
    ("Pampers Pure Protection is a great pick for sensitive skin. Parents love how soft it feels.", {},
     'recommendation_only', 'praise'),
    ("Pampers Swaddlers cost about $0.30 per diaper.", {'prices': [{'amount': '0.30', 'currency': 'USD', 'attributed_product': 'Pampers Swaddlers'}]},
     'attribute', 'a price'),
    ("Pampers Pure is made with premium cotton and is free of chlorine bleaching.", {},
     'attribute', 'material and ingredient'),
    ("Pampers is sold exclusively at Target in the US.", {'recommended_retailers': ['Target']},
     'attribute', 'a retailer, availability'),
    ("Size 1 Pampers Swaddlers fit babies from 8 to 14 lb.", {},
     'attribute', 'size and weight'),
    ("Pampers Club members earn rewards points on every pack.", {},
     'attribute', 'a program'),
    ("Pampers Cruisers 360 come in a 132-count box.", {'pack_counts': [{'value': 132, 'attributed_product': 'Pampers Cruisers 360'}]},
     'attribute', 'a count and pack'),
    ("Pampers Baby-Dry has been discontinued.", {},
     'attribute', 'availability'),
    ("Pampers Swaddlers have a wetness indicator that turns blue.", {},
     'attribute', "a product feature outside the brief's list: the rule misses it"),
    ("I'd go with Pampers Cruisers 360 for an active crawler. Many parents swear by them.", {},
     'recommendation_only', 'a recommendation'),
    ("Pampers is owned by Procter & Gamble.", {},
     'attribute', 'ownership'),
    ("Honestly, Pampers Swaddlers are the best overall choice for most newborns.", {},
     'recommendation_only', 'a recommendation'),
    ("Pampers Swaddlers are hypoallergenic and dermatologist-approved.", {},
     'attribute', 'an ingredient claim'),
    ("Pampers Baby-Dry is a reliable everyday option that most families find works well overnight.", {},
     'recommendation_only', 'a recommendation'),
]
BASE = {'prices': [], 'codes': [], 'pack_counts': [], 'gtins': [], 'member_prices': [], 'points': [],
        'brand_mentioned': True, 'sources_cited': [], 'extraction_confident': True, 'extraction_note': None,
        'other_brands_named': [], 'loyalty_tiers_named': [], 'brand_unknown_statement': None}
EXPECT = {'type': 'brand_mention', 'brand': 'Pampers', 'domain': 'pampers.com'}
FACTS = {'domain': 'pampers.com', 'own_domains': ['pampers.com']}

out = []
for i, (text, fields, label, note) in enumerate(ROWS, start=1):
    spans = pp.segment(text)
    labels = {'spans': [{'span_id': s['id'], 'kind': 'assertion', 'modality': 'asserted'} for s in spans]}
    record = pp.apply_labels({**BASE, **fields}, labels, answer_text=text)
    outcome, reason = bdc.classify(record, EXPECT, brand_facts=FACTS)
    assert outcome == 'fabricated', (text, outcome, reason)
    out.append({'id': f'fl12-bd-{i:02d}', 'answer': text, 'outcome': outcome, 'outcome_reason': reason,
                'reader_label': label, 'note': note, 'extraction': record})
json.dump({'_note': ("FL12-SHAPED, NOT RECORDED. FL12's brand-direct answers are not in this repository and were not "
                     "read from production. Row 1 is the answer the 2K-1 brief quotes; the other 15 are written here in "
                     "the shape of brand-direct answers about Pampers. `extraction` is what the pipeline's own segmenter "
                     "(parser/extraction_postprocess.apply_labels) makes of the text with every span labelled an asserted "
                     "assertion, plus the structured values the transcription would fill; `outcome` is the frozen "
                     "classifier's verdict on it (every row is `fabricated`: asserted, no source). `reader_label` is a "
                     "reader's call: does the answer state a checkable fact about the brand? Built by a one-off script, "
                     "not a test: apps/pipeline/tests/fixtures/build_brand_direct_fl12_2k1.py."),
           'rows': out}, open(sys.argv[1], 'w'), indent=1)
print(len(out), 'rows')
