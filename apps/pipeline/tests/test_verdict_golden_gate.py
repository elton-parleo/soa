"""The 2B verdict golden set is a gate, like the extraction golden set."""
from scripts import eval_verdict_golden as evg


def test_every_verdict_golden_row_reproduces(capsys):
    assert evg.main(['--gate']) == 0


def test_at_least_ten_rows_and_every_rule_is_exercised():
    rows = evg.load_rows()
    assert len(rows) >= 10
    rules = ' '.join(r['rule'] for r in rows)
    for rule in ('§3 rule 1', '§3 rule 2', '§3 rule 3', '§3 rule 4', '§2 retailer_price'):
        assert rule in rules
    for engine_case in ('pack number', 'model/size number', 'variant marker'):
        assert engine_case in rules


def test_every_row_awaits_the_hand_check():
    assert {r['attribution'] for r in evg.load_rows()} == {'claude-reviewed, elton-pending'}
