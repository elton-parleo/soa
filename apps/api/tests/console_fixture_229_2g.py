"""
2G: cycle 229's fixture (console_fixture_229.py), shaped further where 2G's
items read it. The base fixture is built from counts and stays as it is (the
2C-3a tests pin it); this layer is applied on top, in 2G's tests only.

  Questions name their variant, as production's do (source_ref.variant_id):
    the 19 catalog questions the 19 W&S record variants in catalog order;
    the three Member+ questions Overnight Size 3, Cloud Wipes 3-Pack and the
    Trial Pack; the code and the two points questions Snug-Fit Diapers.
  The catalog runs that state a price carry it (claim_results, target asked):
    every exact and wrong run and every one answered with another brand's
    price. That is the first 13 questions: 13 variants measured.
  One move: the sixth run of the first catalog question is wrong, not exact.
    In the base fixture that question is exact on all six runs, which would
    make its variant verified; production's 229 has none verified.
  Layer 2 names brands outside the comparison set (other_brands_named, on the
    scored runs in run order): Target on 34, Costco on 17, Hello Bello on 9,
    and 43 entries presented as a source.
"""
import json
import os

from sqlalchemy import text

HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, '..', '..', 'pipeline', 'tests', 'fixtures', 'wiggle_and_snug_catalog.json')) as fh:
    LISTINGS = json.load(fh)['catalog']['listings']
VARIANTS = [(l['listing_id'], v) for l in LISTINGS for v in l['variants']]
BY_ID = {v['variant_id']: (lid, v) for lid, v in VARIANTS}

MEMBER_VARIANTS = ['snug-fit-overnight-s3', 'cloud-wipes-3pack', 'snug-fit-trial-pack']
CODE_VARIANT = 'snug-fit-diapers-s3-small'
POINTS_VARIANTS = ['snug-fit-diapers-s3-small', 'snug-fit-diapers-s3-big']
OTHER_BRANDS = (('Target', 34), ('Costco', 17), ('Hello Bello', 9))
SOURCES = 43


def _ref(vid: str) -> dict:
    lid, v = BY_ID[vid]
    return {'merchant_slug': 'wiggle-and-snug', 'variant_id': vid, 'gtin': v.get('gtin'), 'listing_id': lid}


def apply(engine) -> None:
    with engine.begin() as c:
        def put(table, col, value, id_col, id_):
            c.execute(text(f"UPDATE {table} SET {col} = :v WHERE {id_col} = :i"), {'v': json.dumps(value), 'i': id_})

        questions = c.execute(text(
            "SELECT id, tier, expected_answer FROM soa_queries WHERE study_type = 'wiggle-snug-full' ORDER BY id")).mappings().all()
        catalog = [q['id'] for q in questions if q['tier'] == 'catalog_accuracy']
        value = [q for q in questions if q['tier'] == 'value_incentives']
        for qid, (_, v) in zip(catalog, VARIANTS):
            put('soa_queries', 'source_ref', _ref(v['variant_id']), 'id', qid)
        member = iter(MEMBER_VARIANTS)
        points = iter(POINTS_VARIANTS)
        for q in value:
            kind = (q['expected_answer'] if isinstance(q['expected_answer'], dict) else json.loads(q['expected_answer']))['type']
            vid = next(member) if kind == 'member_price' else CODE_VARIANT if kind == 'code' else next(points)
            put('soa_queries', 'source_ref', _ref(vid), 'id', q['id'])

        runs = c.execute(text("""
            SELECT o.run_id, o.query_id, o.outcome, o.reason_code FROM soa_expectation_outcomes o
            WHERE o.cycle_id = 229 AND o.tier = 'catalog_accuracy' ORDER BY o.run_id""")).mappings().all()
        first = [r for r in runs if r['query_id'] == catalog[0]]
        c.execute(text("UPDATE soa_expectation_outcomes SET outcome = 'wrong' WHERE run_id = :r"), {'r': first[5]['run_id']})
        moved = first[5]['run_id']
        for r in runs:
            outcome = 'wrong' if r['run_id'] == moved else r['outcome']
            if outcome in ('exact', 'wrong') or r['reason_code'] == 'other_brand':
                stated = '12.99' if outcome == 'exact' else '13.49'
                put('soa_expectation_outcomes', 'claim_results',
                    [{'target': 'asked', 'stated': stated, 'outcome': outcome}], 'run_id', r['run_id'])

        scored = [r[0] for r in c.execute(text(
            "SELECT run_id FROM soa_expectation_outcomes WHERE cycle_id = 229 ORDER BY run_id"))]
        named = [name for name, n in OTHER_BRANDS for _ in range(n)]
        for i, run_id in enumerate(scored):
            entries = ([{'name': named[i], 'presented_as': 'recommendation'}] if i < len(named) else [])
            if i < SOURCES:
                entries.append({'name': f'Source {i}', 'presented_as': 'source', 'relation': 'citation_only'})
            if entries:
                put('soa_expectation_outcomes', 'extraction', {'other_brands_named': entries}, 'run_id', run_id)
