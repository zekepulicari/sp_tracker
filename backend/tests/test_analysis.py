"""Core environmental contracts, unavailable forecasts, and exact discovery ranking."""
import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock
import numpy as np
import pytest
from analysis.features import ENVIRONMENTS
from analysis.geo import validate_polygon
from analysis.discovery import rank_observations, centered_dates
from analysis import discovery
from upstream import UpstreamError
from analysis.data_ingestion import environmental_days
from analysis.probability_model import train_model, predict
from main import AnalysisRequest, DiscoveryRequest
from analysis import prediction as pipeline
from analysis.requirements import analysis_requirements

RING=[[0,0],[1,0],[1,1],[0,1],[0,0]]

def run(coro):
    return asyncio.run(coro)


def model_records(environment='terrestrial'):
    rng=np.random.default_rng(42)
    rows=[]
    for i in range(240):
        presence=i%2
        day=date(2023,1,1)+timedelta(days=i//2)
        row={'id':i,'presence':presence,'date':str(day),'lat':(i//2%12)*.2,'lng':(i//24)*.2}
        for k in ENVIRONMENTS[environment]:row[k]=float(10+presence*8+rng.normal(0,2))
        rows.append(row)
    return rows


@pytest.mark.parametrize('environment',['terrestrial','marine'])
def test_models_validate_and_keep_feature_contract(environment):
    model,metadata=train_model(model_records(environment),environment,'glm')
    assert metadata['validation']['spatial'] and metadata['validation']['chronological']
    assert set(metadata['bounds'])==set(ENVIRONMENTS[environment])
    values={k:15.0 for k in ENVIRONMENTS[environment]}
    prediction=predict(model,metadata,values,'2026-10-16')
    assert prediction['available'] and 0<=prediction['relative_score']<=1
    assert not predict(model,metadata,{},'2026-10-16')['available']
    values[next(iter(values))]=9999
    assert predict(model,metadata,values,'2026-10-16')['extrapolated_variables']


def test_missing_forecast_not_imputed(monkeypatch):
    monkeypatch.setattr('analysis.data_ingestion.gateway.get',AsyncMock(return_value={'hourly':{}}))
    values,_=run(environmental_days(0,0,date.today(),date.today(),'terrestrial',True))
    assert all(v is None for v in values[str(date.today())].values())

def obs(id,taxon=10,day='2024-10-01',coords=None,rank='species'):
    return {'id':id,'observed_on':day,'geojson':{'coordinates':coords or [.5,.5]},'quality_grade':'research','captive':False,
        'taxon':{'id':taxon,'name':f'Species {taxon}','rank':rank,'ancestor_ids':[48460,1], 'iconic_taxon_name':'Aves'}}


def test_ranking_exact_boundary_filters_and_ties():
    rows=[obs(1,20),obs(2,10),obs(3,20,'2023-10-01'),obs(4,10,'2023-10-02'),obs(5,30,coords=[0,0]),obs(6,40,coords=[2,2]),obs(7,50,'2024-09-01')]
    rows += [rows[0],{**obs(8,60),'captive':True},{**obs(9,70),'taxon':{'id':70,'rank':'genus'}}]
    animals,count=run(rank_observations(rows,validate_polygon([RING]),date(2026,10,1)))
    assert [s['taxon_id'] for s in animals]==[10,20,30]
    assert count==5 and animals[2]['evidence_label']=='Single recorded sighting'
    assert animals[0]['years']==[2023,2024]


@pytest.mark.parametrize('center,first,last', [
    ('2026-10-20','10-17','10-23'), ('2026-11-01','10-29','11-04'),
    ('2026-01-01','12-29','01-04'), ('2024-02-29','02-26','03-03'),
    ('2025-03-01','02-26','03-04')])
def test_centered_discovery_includes_boundaries_but_not_other_calendar_dates(center, first, last):
    target = date.fromisoformat(center)
    days = centered_dates(target)
    assert len(days) == 7 and days[3] == target
    assert days[0].isoformat()[5:] == first and days[-1].isoformat()[5:] == last
    rows = [obs(1, day='2024-'+first), obs(2, day='2024-'+last), obs(3, day='2024-'+center[5:]),
            obs(4, day='2024-'+(days[0]-timedelta(days=1)).isoformat()[5:]),
            obs(5, day='2024-'+(days[-1]+timedelta(days=1)).isoformat()[5:]),
            obs(6, day='2010-'+first), obs(7, day='2030-'+last)]
    if center == '2025-03-01': rows.append(obs(8, day='2024-02-29'))
    species,count = run(rank_observations(rows, validate_polygon([RING]), target,
        historical_bounds=(date(2016,1,1),date(2025,12,31))))
    assert count == 3 and species[0]['count'] == 3


def test_discovery_queries_pair_months_and_days_and_share_only_matching_week_cache(monkeypatch):
    discovery.history_cache.clear()
    monkeypatch.setattr(discovery, 'evidence_window', lambda: (date(2016,1,1),date(2025,12,31)))
    monkeypatch.setattr(discovery, 'DISCOVERY_CAP', 4)
    async def fetch(params, cap, **kwargs):
        assert kwargs['require_complete']
        if params['month'] == 12:
            return [obs(1,day='2024-12-29'),obs(2,day='2024-12-31')],2,True
        return [obs(3,day='2024-01-01'),obs(4,day='2024-01-04')],2,True
    get = AsyncMock(side_effect=fetch)
    monkeypatch.setattr(discovery, 'fetch_observations', get)
    def request(day):
        return DiscoveryRequest(polygon={'type':'Polygon','coordinates':[RING]},target_date=day)
    result = run(discovery.run_discovery(request('2027-01-01'), lambda _:None))
    assert result['records_inside'] == 4 and result['bbox_records'] == 4 and result['complete']
    assert result['seasonal_window']['start'] == '2026-12-29' and result['seasonal_window']['end'] == '2027-01-04'
    calls = get.call_args_list
    assert [(c.args[0]['month'],c.args[0]['day'],c.args[1]) for c in calls] == [(12,'29,30,31',4),(1,'1,2,3,4',2)]
    assert not result['weather']['available']
    repeated = run(discovery.run_discovery(request('2028-01-01'), lambda _:None))
    assert get.await_count == 2 and repeated['seasonal_window']['start'] == '2027-12-29'
    next_day = run(discovery.run_discovery(request('2027-01-02'), lambda _:None))
    assert get.await_count == 4 and next_day['records_inside'] == 3
    discovery.history_cache.clear()


def test_discovery_never_caches_partial_or_over_cap_combined_windows(monkeypatch):
    monkeypatch.setattr(discovery, 'DISCOVERY_CAP', 3)
    request = DiscoveryRequest(polygon={'type':'Polygon','coordinates':[RING]},target_date='2027-01-01')
    for failure in ('pagination','incomplete','cap'):
        discovery.history_cache.clear()
        async def fetch(params, cap, **kwargs):
            if params['month'] == 12:
                return [obs(1,day='2024-12-29'),obs(2,day='2024-12-31')],2,True
            assert cap == 1
            if failure == 'pagination': raise UpstreamError('Interrupted pagination.')
            return [obs(3,day='2024-01-01')],2 if failure == 'cap' else 1,failure != 'incomplete'
        monkeypatch.setattr(discovery, 'fetch_observations', fetch)
        with pytest.raises(UpstreamError):
            run(discovery.run_discovery(request, lambda _:None))
        assert not discovery.history_cache


@pytest.mark.parametrize('environment', ['terrestrial', 'marine'])
def test_consecutive_methods_comparison_and_unavailable_evidence(monkeypatch, environment):
    """Method switches must not inherit the previous method's result or cached forecast."""
    rows = model_records(environment)
    sightings = [{**row, 'month': int(row['date'][5:7])} for row in rows if row['presence'] == 1]
    pipeline.model_cache.clear()
    monkeypatch.setattr(pipeline, 'collect_local', AsyncMock(return_value=(sightings, 5, {'complete': True})))
    align = AsyncMock(return_value=(rows, []))
    monkeypatch.setattr(pipeline, 'align_history', align)
    monkeypatch.setattr(pipeline, 'generate_interpretation', lambda species, evidence, fallback, key=None:
                        {'text': fallback, 'source': 'fixture'})
    missing_forecast = False
    async def weather(lat, lng, start, end, env, forecast=False):
        return {str(start + timedelta(days=i)): {key: None if missing_forecast else 14.
                for key in ENVIRONMENTS[env]} for i in range((end-start).days + 1)}, []
    monkeypatch.setattr(pipeline, 'environmental_days', weather)
    def request(method, operation='single_day'):
        return AnalysisRequest(species='Synthetic animal', taxon_id=42, environment=environment,
            method=method, operation=operation, target_lat=0, target_lng=0, target_date=date.today(), limit=100)
    async def scenario():
        for method in ('rustic', 'glm', 'rf', 'glm', 'rustic', 'rf', 'rustic'):
            result = await pipeline.run_analysis(request(method), lambda _: None, '')
            assert result['environment'] == environment
            assert (method == 'rustic') == ('model' not in result)
            assert (method == 'glm') == bool(result.get('days'))
            assert (method == 'rf') == bool(result.get('model', {}).get('variable_importance'))
        comparison = await pipeline.run_analysis(request('glm', 'compare_days'), lambda _: None, '')
        assert comparison['type'] == 'day_comparison' and len(comparison['days']) == 7
    run(scenario())
    missing_forecast = True
    missing = run(pipeline.run_analysis(request('glm'), lambda _: None, ''))
    assert missing['profile'] and not missing['days'][0]['available']
    assert 'relative_score' not in missing['days'][0]
    pipeline.model_cache.clear()
    align.return_value = ([row for row in rows if row['presence'] == 0][:31],
                          [{'id': row['id'], 'date': row['date'], 'reason': 'Incomplete environmental data.'}
                           for row in sightings])
    for method in ('glm', 'rf'):
        fallback = run(pipeline.run_analysis(request(method), lambda _: None, ''))
        assert fallback['type'] == 'historical_profile' and fallback['profile'] and 'model' not in fallback
        assert 'Insufficient evidence' in fallback['summary'] and fallback['evidence']['excluded_records']
        counts = fallback['evidence']['eligibility']['counts']
        assert counts['aligned_sightings'] == 0 and counts['aligned_background'] == 31
        assert counts['usable_total'] == (31 if method == 'glm' else None)
    pipeline.model_cache.clear()


def test_failed_fits_preserve_counts_and_public_fitting_minimum():
    minimum = analysis_requirements()['model']['min_records']
    with pytest.raises(ValueError) as error:
        train_model(model_records()[:minimum-1], 'terrestrial', 'glm')
    assert error.value.eligibility['counts']['usable_total'] == minimum-1
    assert error.value.validation is None
    _, metadata = train_model(model_records()[:minimum], 'terrestrial', 'glm')
    assert metadata['n_records'] == minimum
    incomplete = model_records()[:minimum]
    incomplete[0]['air_temp'] = float('nan')
    with pytest.raises(ValueError, match='finite') as error:
        train_model(incomplete, 'terrestrial', 'glm')
    assert error.value.eligibility['counts']['usable_total'] is None
    assert error.value.eligibility['counts']['aligned_sightings'] == minimum//2


def test_spatial_and_date_limits_keep_other_available_metrics():
    rows = model_records()[:150]
    for row in rows: row.update(lat=.01, lng=.01)
    _, metadata = train_model(rows, 'terrestrial', 'glm')
    v = metadata['validation']
    assert v['spatial'] is None and v['chronological']
    assert v['diagnostics']['spatial']['n_groups'] == 1
    assert v['diagnostics']['spatial']['sighting_groups'] == 1
    assert v['diagnostics']['chronological']['n_dates'] == 75
    assert 'Occupied cells: 1; need at least 4' in v['unavailable_reasons']['spatial']
    assert isinstance(v['chronological']['model']['auc'], float)
    rows = model_records()
    for i, row in enumerate(rows): row['date'] = str(date(2023, 1, 1)+timedelta(days=i%9))
    _, metadata = train_model(rows, 'terrestrial', 'glm')
    assert metadata['validation']['spatial'] and metadata['validation']['chronological'] is None
    assert 'Distinct dates: 9; need at least 10' in metadata['validation']['unavailable_reasons']['chronological']


def test_many_cells_do_not_guarantee_a_class_balanced_spatial_split():
    rows = model_records()
    for row in rows:
        if row['presence']: row.update(lat=.01, lng=.01)
    _, metadata = train_model(rows, 'terrestrial', 'glm')
    v = metadata['validation']
    assert v['spatial'] is None and v['chronological']
    assert v['diagnostics']['spatial']['n_groups'] >= 4
    assert v['diagnostics']['spatial']['sighting_groups'] == 1
    assert v['diagnostics']['spatial']['attempted_splits'] == 8
    assert 'No eligible grouped split' in v['unavailable_reasons']['spatial']


@pytest.mark.parametrize('spatial_pass', [False, True])
def test_readable_baseline_verdict_preserves_individual_holdout_metrics(monkeypatch, spatial_pass):
    from analysis import probability_model as models
    values = iter([
        {'auc': .8 if spatial_pass else .5079, 'balanced_accuracy': .8 if spatial_pass else .4632},
        {'auc': .5289, 'balanced_accuracy': .4789},
        {'auc': .8, 'balanced_accuracy': .8}, {'auc': .5, 'balanced_accuracy': .5}])
    monkeypatch.setattr(models, 'metrics', lambda *_: next(values))
    _, metadata = models.train_model(model_records(), 'terrestrial', 'glm')
    v = metadata['validation']
    assert v['spatial']['improves_baseline'] == spatial_pass
    assert v['chronological']['improves_baseline'] and not v['experimental']
    assert v['ranking_allowed'] == spatial_pass
    assert v['spatial']['model']['auc'] == (.8 if spatial_pass else .5079)


@pytest.mark.parametrize('text,allowed', [
    ('The models are statistically indistinguishable.', False),
    ('The difference is not statistically significant.', False),
    ('There is no significant difference between the models.', False),
    ('Chronological validation did not outperform the seasonal baseline.', True)])
def test_ai_significance_claims_fall_back_to_authoritative_evidence(monkeypatch, text, allowed):
    from types import SimpleNamespace
    from google import genai
    from analysis.interpretation import generate_interpretation
    class Client:
        def __init__(self, **kwargs):
            self.models = SimpleNamespace(generate_content=lambda **kwargs: SimpleNamespace(text=text))
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(genai, 'Client', Client)
    result = generate_interpretation('Synthetic animal', {}, 'Authoritative evidence.', 'dummy-key')
    assert result['source'] == ('ai' if allowed else 'evidence')
    assert result['text'] == (text if allowed else 'Authoritative evidence.')
