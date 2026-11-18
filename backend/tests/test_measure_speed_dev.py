import importlib.util
from pathlib import Path
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'measure_speed_dev.py'
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location('measure_speed_dev', SCRIPT)
speed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(speed)


def test_prompt_budget_fails_closed():
    assert speed.check_prompt('a', 'b') > 0
    with pytest.raises(ValueError, match='BUDGET_PREFLIGHT'):
        speed.check_prompt('x ' * 50000, '')


def test_exact_prior_token_count_can_validate_large_estimate_without_relaxing_actual_cap():
    assert speed.check_prompt('x ' * 50000, '', known_token_count=7340) > 0
    with pytest.raises(ValueError, match='BUDGET_PREFLIGHT'):
        speed.check_prompt('x ' * 50000, '', known_token_count=8000)


def test_options_are_shared_and_bm25_fusion_off(monkeypatch):
    monkeypatch.setattr(speed, 'configure', lambda: {'MAX_OUTPUT_TOKENS':'700'})
    bm = speed.configure_speed('bm25', 5)
    d3 = speed.configure_speed('d3', 6)
    assert bm['RETRIEVAL_FUSION'] == 'off' and d3['RETRIEVAL_FUSION'] == 'bm25'
    assert all(x['LOCAL_LLM_CONTEXT_TOKENS'] == '8192' and x['MAX_CONTEXT_TOKENS'] == '3000'
               and x['MAX_OUTPUT_TOKENS'] == '700' for x in (bm, d3))


def test_sample_is_independent_and_dev_only():
    rows = [{'id': str(i), 'ma_chuoi': str(i)} for i in range(29)]
    sample = [str(i) for i in range(10)]
    assert len(speed.select_rows(rows, 'sample', sample)) == 10
    assert len(speed.select_rows(rows, 'all', sample)) == 29
    rows[1]['ma_chuoi'] = rows[0]['ma_chuoi']
    with pytest.raises(ValueError, match='independent'):
        speed.select_rows(rows, 'sample', sample)


def test_bm25_never_falls_back(monkeypatch):
    from app.retrieval import candidate_index
    class Pipeline:
        source_store = object()
    pipeline = Pipeline()
    monkeypatch.setattr(candidate_index, 'cached_rank', lambda *a, **kw: None)
    speed.install_bm25(pipeline)
    with pytest.raises(RuntimeError, match='refusing fallback'):
        pipeline._retrieve_candidates('q', None, top_k=5, min_score=0, source_ids=[])


