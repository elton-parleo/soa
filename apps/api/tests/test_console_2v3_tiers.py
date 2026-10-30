"""
2V-3 Q7: an incentive's tier is on the record and on True Value.

FL17's record read "Incentive · Petco Perks · on all · loyalty program · no
end date" three times, one per tier with the tier not rendered, and True
Value's programs block the same. Each now reads its tier ("Petco Perks ·
Premier") when it shares its name with another; a name that is alone, or already says its tier ("Perks Premier", recorded from
supply on the Petco fixture) is not given it twice.
"""
import json
import os

from app.services import console_parity as parity
from app.services import console_read_models as rm

OWNED = os.path.join(os.path.dirname(__file__), 'fixtures', 'console', 'supply_2v2', 'incentives-owned.json')

TIERS = [{'name': 'Petco Perks', 'tier_name': t, 'mechanic': 'loyalty_program', 'valid_until': None}
         for t in ('Member', 'Premier', 'Vital Care')]


def _recorded():
    with open(OWNED) as fh:
        body = json.load(fh)['body']
    return body if isinstance(body, list) else body.get('incentives') or body.get('rows') or []


def test_the_name_carries_the_tier_once():
    assert rm.incentive_name(TIERS[1], siblings=TIERS) == 'Petco Perks · Premier'
    # alone, the name is as before (Wiggle & Snug's "Member Rewards" with its Member+ tier)
    assert rm.incentive_name({'name': 'Member Rewards', 'tier_name': 'Member+'}) == 'Member Rewards'
    perks = {'name': 'Perks Premier', 'tier_name': 'Premier'}
    assert rm.incentive_name(perks, siblings=[perks, dict(perks)]) == 'Perks Premier'
    assert rm.incentive_name({'name': 'Petco Autoship'}) == 'Petco Autoship'
    assert rm.incentive_name({'tier_name': 'Premier'}) == 'Premier'
    assert rm.incentive_name({}, 'Incentive') == 'Incentive'


def test_the_record_shows_three_tiers_as_three_names():
    fields = parity.offer_fields({'fields': []}, owned=TIERS, reference_rows=[], verifications=[], listing={})
    assert [f['k'] for f in fields if f['k'].startswith('Incentive')] == [
        'Incentive · Petco Perks · Member', 'Incentive · Petco Perks · Premier', 'Incentive · Petco Perks · Vital Care']


def test_true_value_s_programs_name_each_tier():
    names = [p['name'] for p in rm.build_programs(TIERS, [])]
    assert names == ['Petco Perks · Member', 'Petco Perks · Premier', 'Petco Perks · Vital Care']


def test_the_recorded_petco_incentives():
    recorded = _recorded()
    names = [rm.incentive_name(i, siblings=recorded) for i in recorded]
    assert names[0] == 'Petco Perks'          # one Petco Perks in the recording: as before
    assert 'Perks Premier' in names and 'Perks Premier · Premier' not in names
