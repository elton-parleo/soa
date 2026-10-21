"""
2L-1 §B2: worker-shared copy reads as sentences (house rule: no semicolons, no
em dashes). The surface descriptions the run dialog and the Create Study modal
show, the tier lines Create Study's rows read (catalog_tiers.expected_nulls),
the grounded-only refusal, and the other user-facing strings in the shared
packages. Every copy of each module stays identical.
"""
import filecmp
import os
from types import SimpleNamespace

import pytest

from soa_shared import catalog_tiers as ct
from soa_shared import surfaces

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
COPIES = ('apps/api/soa_shared', 'apps/pipeline/soa_shared', 'packages/shared/soa_shared')
BANNED = (';', '—')


@pytest.mark.parametrize('module', ['surfaces.py', 'expected_answers.py', 'degraded_dimensions.py',
                                    'scan_dimensions.py', 'catalog_tiers.py'])
def test_every_copy_is_identical(module):
    present = [os.path.join(ROOT, d, module) for d in COPIES if os.path.exists(os.path.join(ROOT, d, module))]
    assert len(present) >= 2, present          # catalog_tiers.py has no packages/shared copy
    for other in present[1:]:
        assert filecmp.cmp(present[0], other, shallow=False), other


def _clean(text):
    return not any(b in text for b in BANNED)


def test_surface_descriptions_are_sentences():
    for s in surfaces.SURFACES + list(surfaces.LEGACY.values()):
        assert _clean(s.fidelity), s.id
        assert _clean(s.never_available or ''), s.id


def test_the_grounded_only_refusal_has_no_semicolon():
    body = surfaces.ungrounded_refusal(['chatgpt_api', 'gemini'])
    assert body['message'] == ("Only grounded surfaces run. 'chatgpt_api' answers without searching. Use chatgpt. "
                               "'gemini' (gemini_api) answers without searching. Use gemini_grounded.")


def _snapshot(**kw):
    base = dict(brand='Pampers', code_count=0, merchant_kind='brand', retailer_list=['walmart.com'], reads={},
                is_external=True, hosting='external', variants=lambda: [])
    return SimpleNamespace(**{**base, **kw})


@pytest.mark.parametrize('tier', ['category_control', 'value_incentives', 'catalog_accuracy', 'brand_direct'])
@pytest.mark.parametrize('reads', [None, {}, {'v': [object()]}])
def test_tier_lines_are_sentences(tier, reads, monkeypatch):
    import soa_shared.catalog_snapshot as cs
    monkeypatch.setattr(cs, 'price_source', lambda snap: 'read' if snap.reads else None)
    monkeypatch.setattr(ct, 'is_external', lambda snap: True)
    for kind in ('brand', 'seller'):
        assert _clean(ct.expected_nulls(_snapshot(reads=reads, merchant_kind=kind), tier))


def test_the_other_shared_strings():
    from soa_shared import degraded_dimensions as dd, scan_dimensions as sd
    assert _clean(dd.DEGRADED_REASON_NO_PRODUCT_PAGES_TEMPLATE)
    for d in sd.DIMENSIONS:
        assert ';' not in d.how_scored, d.code
