"""
2B: the existing Full Analysis tier report counts partial and unverifiable
rows instead of dropping them, without changing what a pre-2B cycle renders.
"""
from app.services import tier_accuracy as ta


def test_a_pre_2b_cycle_renders_the_same_count_keys():
    assert set(ta._empty_counts('catalog_accuracy')) == {'exact', 'stale', 'wrong', 'absent', 'unscoreable'}


def test_partial_is_scored_and_never_exact_and_unverifiable_is_outside():
    summary = ta._summarise({'exact': 2, 'wrong': 1, 'partial': 1, 'unverifiable': 3, 'absent': 2})
    assert summary['scored'] == 4
    assert summary['accuracy'] == 0.5
    assert summary['counts']['unverifiable'] == 3


def test_2b_outcomes_are_in_the_value_vocabulary():
    for outcome in ('partial', 'unverifiable'):
        assert outcome in ta._vocabulary('catalog_accuracy')
