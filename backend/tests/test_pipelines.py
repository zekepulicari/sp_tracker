"""Pipeline acceptance tests use fixtures rather than live networks or AI tokens."""
import asyncio
import copy
from datetime import date, timedelta
from unittest.mock import AsyncMock
import pytest
from main import AnalysisRequest
from analysis.prediction import run_analysis, model_cache
from analysis.features import ENVIRONMENTS
from analysis.interpretation import generate_interpretation
from test_analysis import model_records


def run(coro):return asyncio.run(coro)

def request(environment='terrestrial',operation='single_day',method='glm',day=None):
    return AnalysisRequest(species='Example animal',taxon_id=42,environment=environment,operation=operation,
        method=method,target_lat=0,target_lng=0,target_date=day or date.today(),limit=100)

def arrange(monkeypatch,environment,missing=False):
    model_cache.clear()
    records=[{**r,'month':int(r['date'][5:7])} for r in model_records(environment) if r['presence']==1]
    monkeypatch.setattr('analysis.prediction.local_occurrences',AsyncMock(return_value=(records,{'complete':True})))
    monkeypatch.setattr('analysis.prediction.align_history',AsyncMock(return_value=(model_records(environment),[])))
    def explain(species,evidence,fallback,api_key=None):return {'text':fallback,'source':'evidence','notice':'fixture'}
    monkeypatch.setattr('analysis.prediction.generate_interpretation',explain)
    async def weather(lat,lng,start,end,env,forecast=False):
        values={k:None if missing else 15.0 for k in ENVIRONMENTS[env]}
        return {str(start+timedelta(days=i)):values for i in range((end-start).days+1)},[]
    monkeypatch.setattr('analysis.prediction.environmental_days',weather)

@pytest.mark.parametrize('environment',['terrestrial','marine'])
def test_full_outlook_then_comparison_reuses_training(monkeypatch,environment):
    arrange(monkeypatch,environment)
    result=run(run_analysis(request(environment),lambda _:None))
    assert result['type']=='environmental_outlook'
    assert result['days'][0]['available'] and result['evidence']['usable_sightings']>0
    original=copy.deepcopy(result)
    # Cached training must not carry the previous target, summary, or days into the next operation.
    comparison=run(run_analysis(request(environment,'compare_days'),lambda _:None))
    assert comparison['type']=='day_comparison' and len(comparison['days'])==7
    from analysis.prediction import align_history
    assert align_history.call_count==1
    assert result==original


def test_out_of_window_does_not_fetch_environmental_history(monkeypatch):
    arrange(monkeypatch,'terrestrial')
    result=run(run_analysis(request(day=date.today()+timedelta(days=90)),lambda _:None))
    assert result['type']=='historical_profile' and not result['weather']['available']
    from analysis.prediction import align_history
    assert align_history.call_count==0


def test_missing_forecast_keeps_profile_and_withholds_scores(monkeypatch):
    arrange(monkeypatch,'terrestrial',True)
    result=run(run_analysis(request(),lambda _:None))
    assert not result['days'][0]['available']
    assert 'relative_score' not in result['days'][0]
    assert result['profile'] and 'missing' in result['summary']


def test_key_factors_retains_importance(monkeypatch):
    arrange(monkeypatch,'terrestrial')
    result=run(run_analysis(request(method='rf'),lambda _:None))
    assert result['model']['variable_importance'] and 'days' not in result
    assert set(result['model']['variable_importance'])==set(result['model']['features'])


def test_ai_missing_or_exception_preserves_evidence(monkeypatch):
    monkeypatch.setattr('analysis.interpretation.GEMINI_KEY','')
    assert generate_interpretation('Animal',{},'Evidence')['text']=='Evidence'
    monkeypatch.setattr('analysis.interpretation.GEMINI_KEY','test-only-key')
    from google import genai
    monkeypatch.setattr(genai,'Client',lambda **kwargs:(_ for _ in ()).throw(ValueError('private SDK details')))
    result=generate_interpretation('Animal',{},'Evidence')
    assert result['text']=='Evidence' and 'private' not in str(result)


def test_personal_key_overrides_default_without_mutating_it(monkeypatch):
    from google import genai
    from types import SimpleNamespace
    from analysis import interpretation
    received = []
    class Client:
        def __init__(self, **kwargs):
            received.append(kwargs['api_key'])
            self.models = SimpleNamespace(generate_content=lambda **kwargs: SimpleNamespace(text='Summary'))
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(interpretation, 'GEMINI_KEY', 'server-default-key')
    monkeypatch.setattr(genai, 'Client', Client)
    assert generate_interpretation('Animal', {}, 'Evidence', 'personal-key')['source'] == 'ai'
    assert generate_interpretation('Animal', {}, 'Evidence')['source'] == 'ai'
    assert received == ['personal-key', 'server-default-key']
    assert interpretation.GEMINI_KEY == 'server-default-key'


def test_cached_model_uses_current_request_key(monkeypatch):
    arrange(monkeypatch, 'terrestrial')
    seen = []
    def explain(species, evidence, fallback, api_key=None):
        seen.append(api_key)
        return {'text': fallback, 'source': 'evidence', 'notice': 'fixture'}
    monkeypatch.setattr('analysis.prediction.generate_interpretation', explain)
    first = run(run_analysis(request(), lambda _: None, 'first-personal-key'))
    second = run(run_analysis(request(), lambda _: None, 'second-personal-key'))
    assert seen == ['first-personal-key', 'second-personal-key']
    assert 'personal-key' not in str(first) + str(second) + str(model_cache)
    from analysis.prediction import align_history
    assert align_history.call_count == 1


@pytest.mark.parametrize('environment', ['terrestrial', 'marine'])
def test_key_factors_reports_estimates_without_sending_source_ids_to_ai(monkeypatch, environment):
    arrange(monkeypatch, environment)
    rows = model_records(environment)
    for i in range(0, len(rows), 7):
        rows[i][ENVIRONMENTS[environment][0]] = None
        rows[i]['id'] = f'private-record-{i}'
    monkeypatch.setattr('analysis.prediction.align_history', AsyncMock(return_value=(rows, [])))
    captured = []
    def explain(species, evidence, fallback, api_key=None):
        captured.append(evidence)
        return {'text': fallback, 'source': 'evidence', 'notice': 'fixture'}
    monkeypatch.setattr('analysis.prediction.generate_interpretation', explain)
    result = run(run_analysis(request(environment, method='rf'), lambda _: None))
    evidence = result['evidence']
    assert evidence['complete_records'] + evidence['imputed_records'] == result['model']['n_records']
    assert evidence['imputed_records'] == 35 and evidence['imputed_cells'] == 35
    assert evidence['usable_sightings'] + evidence['usable_background'] == result['model']['n_records']
    assert any('estimated' in warning for warning in result['warnings'])
    assert 'private-record-' not in str(captured)
    assert captured[0]['model']['imputation']['imputed_cells'] == 35
    for _, cached in model_cache.values():
        assert 'target_date' not in cached and 'days' not in cached


def test_imputation_failure_preserves_exclusion_reasons_without_claiming_a_fit(monkeypatch):
    import numpy as np
    arrange(monkeypatch, 'terrestrial')
    rows = model_records()[:40]
    for row in rows:
        if row['presence'] == 0: row['air_temp'] = None
    monkeypatch.setattr('analysis.prediction.align_history', AsyncMock(return_value=(rows, [])))
    monkeypatch.setattr('analysis.imputation.proximity', lambda fitted, queries, donors: np.zeros((len(queries), len(donors))))
    result = run(run_analysis(request(method='rf'), lambda _: None))
    assert result['type'] == 'historical_profile' and 'model' not in result
    assert 'Insufficient evidence' in result['summary']
    assert len(result['evidence']['excluded_records']) == 20
    assert all('positive' in row['reason'] for row in result['evidence']['excluded_records'])
    assert 'usable_sightings' not in result['evidence']
    assert 'training_records' not in result['evidence']
