"""
2P-1 (B1): --refresh-reference writes when any served field changed, not
only a price cell (2O-7).

After supply #31 and the brand-page backfill, FL14's refresh printed
"reference cells that differ: 0 ... nothing to write" though supply now
served the brand page on the own rows, the attribute truth, the deals,
the page titles and the brand's line list; the brand-direct rescores that
followed read the cached rows and printed the old index. Held here, on the
2J-4 FL12 cycle with its cached copy already corrected (no price cell
moves): every served field counts, each named on its own line beside the
price-cell count; an own row cached without the brand page while supply
serves it is changed; a payload with nothing new still writes nothing;
--restore round-trips the whole payload.
"""
import copy
import json

import pytest
from sqlalchemy import text

from scripts import rescore_cycle as rc
from tests.test_refresh_reference_2j4 import AFTER, AS_OF, CYCLE, Supply, _raw, _refresh, fl12, scorer  # noqa: F401

BRAND_PAGE = {'json_ld': {'name': 'Pampers Swaddlers Diapers', 'hasVariant': [{'size': 'Newborn'}]},
              'size_chart': [{'size': 'Newborn', 'min': None, 'max': 10, 'unit': 'lb'}],
              'bullets': ['Up to 100% leakproof skin protection'], 'final_url': 'https://www.pampers.com/swaddlers'}


@pytest.fixture
def corrected(fl12):
    """FL12 with its cached copy already AFTER: the prices supply serves now."""
    with fl12.begin() as c:
        c.execute(text("UPDATE soa_cycles SET reference_prices = :p WHERE id = 12"), {'p': json.dumps(AFTER)})
    rc.classify_only(CYCLE, scorer=scorer())
    return fl12


def served(**changes):
    """AFTER with supply #31's fields: per-row changes keyed by domain, and
    payload-level ones under `payload`."""
    out = copy.deepcopy(AFTER)
    for row in out['prices']:
        row.update(changes.get(row['retailer_domain'], {}))
    out.update(changes.get('payload', {}))
    return out


SUPPLY_31 = dict(**{
    'pampers.com': {**BRAND_PAGE, 'attribute': {'truth': {'min': None, 'max': 10, 'unit': 'lb'}, 'source': 'brand_page'},
                    'page_title': 'Pampers Swaddlers Newborn Diapers'},
    'amazon.com': {'deals': [{'kind': 'coupon', 'text': 'Save 20% with Subscribe & Save'}],
                   'page_title': 'Pampers Swaddlers Diapers Size Newborn, 84 Count'},
    'payload': {'brand_lines': ['Pampers Swaddlers', 'Pampers Cruisers 360'], 'brand_lines_complete': False},
})


def test_no_price_cell_moved_but_the_served_rows_did_writes(corrected, tmp_path, capsys):
    before = _raw(corrected, CYCLE)
    result = _refresh(backup=str(tmp_path / 'b.json'), supply=Supply(served(**SUPPLY_31)))
    out = capsys.readouterr().out
    assert result['diff'] == []
    assert 'reference cells that differ: 0' in out
    assert 'rows with new or changed fields: 2 (attribute, brand_page, deals, page_title)' in out
    assert 'payload fields that differ: brand_lines, brand_lines_complete' in out
    assert 'nothing to write' not in out
    assert result['written'] is True
    stored = json.loads(_raw(corrected, CYCLE))
    own = next(r for r in stored['prices'] if r['role'] == 'own')
    assert own['json_ld'] == BRAND_PAGE['json_ld'] and own['size_chart'] == BRAND_PAGE['size_chart']
    assert stored['brand_lines'] == ['Pampers Swaddlers', 'Pampers Cruisers 360']
    assert stored['brand_lines_complete'] is False
    assert stored['previous_sha256'] == rc._sha256(before)


@pytest.mark.parametrize('domain,field,value', [
    ('pampers.com', 'attribute', {'truth': {'max': 10, 'unit': 'lb'}, 'source': 'brand_page'}),
    ('amazon.com', 'deals', [{'kind': 'coupon', 'text': '$3 off'}]),
    ('target.com', 'page_title', 'Pampers Swaddlers Newborn 84 ct'),
    ('pampers.com', 'json_ld', {'name': 'Pampers Swaddlers'}),
    ('pampers.com', 'size_chart', [{'size': 'Newborn', 'max': 10}]),
    ('pampers.com', 'bullets', ['Wetness indicator']),
])
def test_each_served_row_field_alone_is_a_change(corrected, capsys, domain, field, value):
    result = _refresh(write=False, supply=Supply(served(**{domain: {field: value}})))
    named = 'brand_page' if field in rc.BRAND_PAGE_FIELDS else field
    assert result['served']['rows'] == [(r, domain, named) for r in
                                        [('Swaddlers NB 84 (own)' if domain == 'pampers.com' else 'Swaddlers NB 84')]]
    out = capsys.readouterr().out
    assert f'rows with new or changed fields: 1 ({named})' in out and 'dry run' in out


@pytest.mark.parametrize('key,value', [('brand_lines', ['Pampers Swaddlers']), ('brand_lines_complete', True)])
def test_each_payload_field_alone_is_a_change(corrected, capsys, key, value):
    result = _refresh(write=False, supply=Supply(served(payload={key: value})))
    assert result['served'] == {'rows': [], 'payload': [key]}
    assert f'payload fields that differ: {key}' in capsys.readouterr().out


def test_an_own_row_cached_without_the_brand_page_while_supply_serves_it_is_changed(corrected):
    # the cached row has no json_ld key at all; supply serves one, even an empty chart
    result = _refresh(write=False, supply=Supply(served(**{'pampers.com': {'json_ld': None, 'size_chart': []}})))
    assert result['served']['rows'] == [('Swaddlers NB 84 (own)', 'pampers.com', 'brand_page')]


def test_nothing_new_still_writes_nothing(corrected, tmp_path, capsys):
    raw = _raw(corrected, CYCLE)
    result = _refresh(backup=str(tmp_path / 'b.json'), supply=Supply(served()))
    out = capsys.readouterr().out
    assert result['written'] is False and result['served'] == {'rows': [], 'payload': []}
    assert 'rows with new or changed fields: 0' in out and 'no served field differs: nothing to write.' in out
    assert _raw(corrected, CYCLE) == raw and not (tmp_path / 'b.json').exists()


def test_the_envelope_is_not_a_served_difference(corrected):
    """A second refresh reads its own envelope back; refreshed_at is not supply's."""
    payload = served(**SUPPLY_31)
    assert rc.served_diff({**payload, 'refreshed_at': 'x', 'previous_sha256': 'y'}, payload) == {'rows': [], 'payload': []}


def test_restore_round_trips_the_whole_payload(corrected, tmp_path):
    backup = str(tmp_path / 'b.json')
    raw = _raw(corrected, CYCLE)
    _refresh(backup=backup, supply=Supply(served(**SUPPLY_31)))
    refreshed = json.loads(_raw(corrected, CYCLE))
    assert refreshed['brand_lines'] and any('json_ld' in r for r in refreshed['prices'])
    result = rc.restore_reference(CYCLE, backup, scorer_factory=scorer)
    assert result['written'] is True
    # the restore's own diff names the served fields it takes away
    assert ('Swaddlers NB 84 (own)', 'pampers.com', 'brand_page') in result['served']['rows']
    assert result['served']['payload'] == ['brand_lines', 'brand_lines_complete']
    assert _raw(corrected, CYCLE) == raw
    assert json.loads(raw)['as_of'] == AS_OF
