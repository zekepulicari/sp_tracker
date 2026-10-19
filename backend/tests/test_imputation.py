import asyncio
import copy
from datetime import date, timedelta
from unittest.mock import AsyncMock
import numpy as np
import pandas as pd
import pytest
from analysis.features import ENVIRONMENTS, SEASONAL, seasonality
from analysis.imputation import ProximityImputer, eligibility_reason, proximity, weighted_update
from analysis.data_ingestion import align_history, env_cache
from analysis.probability_model import train_model
from test_analysis import model_records


def frame(environment='terrestrial', size=100):
    return pd.DataFrame([{**r, **seasonality(int(r['date'][5:7]))} for r in model_records(environment)[:size]])


def test_proximity_is_fraction_of_shared_leaves():
    class Tree:
        def __init__(self, shift): self.shift = shift
        def apply(self, values): return (np.asarray(values)[:, 0] + self.shift).astype(int) // 2
    class Forest:
        estimators_ = [Tree(0), Tree(1)]
    result = proximity(Forest(), np.array([[0], [1]]), np.array([[0], [1], [2]]))
    np.testing.assert_equal(result, [[1, .5, 0], [.5, 1, .5]])


def test_weighted_mean_uses_only_original_observations_and_reports_zero_support():
    original = np.array([[2., 10], [6, 20], [np.nan, 30], [np.nan, 40]])
    missing = ~np.isfinite(original)
    filled = np.nan_to_num(original, nan=4)
    weights = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [.25, .75, 999, 999], [0, 0, 1, 1.]])
    updated, unresolved = weighted_update(filled, original, missing, weights, 1)
    assert updated[2, 0] == 5
    assert unresolved.tolist() == [False, False, False, True]
    np.testing.assert_equal(updated[~missing], original[~missing])


@pytest.mark.parametrize('environment', ['terrestrial', 'marine'])
def test_imputation_repeats_preserves_measurements_and_has_inductive_transform(environment):
    data = frame(environment)
    environmental = ENVIRONMENTS[environment]
    features = environmental + SEASONAL
    data.loc[::7, environmental[0]] = np.nan
    first = ProximityImputer(features, environment)
    completed = first.fit_transform(data)
    second = ProximityImputer(features, environment)
    pd.testing.assert_frame_equal(completed, second.fit_transform(data))
    observed = data[features].notna().to_numpy()
    np.testing.assert_equal(completed[features].to_numpy()[observed], data[features].to_numpy()[observed])
    assert first.metadata['imputed_records'] == 15 and first.metadata['imputed_cells'] == 15
    assert first.metadata['observed_cells'] + first.metadata['imputed_cells'] == len(data) * len(environmental)
    assert first.metadata['iterations_performed'] == 5
    assert first.metadata['donor_counts'][environmental[0]] == 85
    assert all(row['missing'] == [environmental[0]] for row in first.metadata['records'] if row['missing'])
    before = copy.deepcopy(first.metadata)
    query = data.iloc[[0]].copy()
    alone, _ = first.transform(query)
    query['presence'] = 1 - query.presence
    flipped, _ = first.transform(query)
    other = data.iloc[[1]].copy()
    other.loc[:, environmental] = 10000
    together, _ = first.transform(pd.concat([query, other]))
    np.testing.assert_allclose(alone[features], flipped[features], rtol=0, atol=0)
    np.testing.assert_allclose(alone[features], together.iloc[[0]][features], rtol=0, atol=1e-12)
    assert first.metadata == before


@pytest.mark.parametrize('case', ['few_donors', 'majority_missing', 'constant', 'all_missing'])
def test_training_donor_limits_fail_explicitly(case):
    data = frame(size=40)
    if case == 'few_donors': data.loc[14:, 'air_temp'] = np.nan
    if case == 'majority_missing': data.loc[19:, 'air_temp'] = np.nan
    if case == 'constant': data['air_temp'] = 5
    if case == 'all_missing': data['air_temp'] = np.nan
    with pytest.raises(ValueError, match='observed donors'):
        ProximityImputer(ENVIRONMENTS['terrestrial'] + SEASONAL, 'terrestrial').fit_transform(data)


def test_no_positive_donors_excludes_record_and_rebuilds_without_it(monkeypatch):
    data = frame(size=60)
    data.loc[0, 'air_temp'] = np.nan
    monkeypatch.setattr('analysis.imputation.proximity', lambda fitted, queries, donors: np.zeros((len(queries), len(donors))))
    imputer = ProximityImputer(ENVIRONMENTS['terrestrial'] + SEASONAL, 'terrestrial')
    completed = imputer.fit_transform(data)
    assert len(completed) == 59 and 0 not in completed.index
    assert imputer.metadata['restarts'] == 1
    assert imputer.metadata['exclusions'][0]['id'] == 0
    assert 'positive' in imputer.metadata['exclusions'][0]['reason']
    assert imputer.metadata['imputed_cells'] == 0
    heldout, report = imputer.transform(data.iloc[[0]])
    assert heldout.empty and len(report['exclusions']) == 1


def test_hard_eligibility_and_record_bound():
    row = model_records('marine')[0]
    assert eligibility_reason({**row, 'date': '2021-12-31'}, 'marine')
    assert eligibility_reason({**row, 'date': str(date.today() - timedelta(days=2))}, 'marine')
    assert eligibility_reason({**row, 'lat': 91}, 'marine')
    assert eligibility_reason({**row, 'date': 'not-a-date'}, 'marine')
    assert 'marine' in eligibility_reason({**row, 'sst': None, 'wave_height': None, 'ocean_current_velocity': None}, 'marine')
    land = model_records()[0]
    assert eligibility_reason({**land, 'air_temp': None, 'precipitation': None}, 'terrestrial')
    assert eligibility_reason({**land, 'air_temp': None}, 'terrestrial') is None
    with pytest.raises(ValueError, match='1,000'):
        ProximityImputer(ENVIRONMENTS['terrestrial'] + SEASONAL, 'terrestrial').fit_transform(pd.concat([frame()] * 11))


@pytest.mark.parametrize('environment', ['terrestrial', 'marine'])
def test_ingestion_retains_partial_only_for_rf_and_blocks_unsupported_dates(monkeypatch, environment):
    env_cache.clear()
    row = model_records(environment)[0]
    values = {key: row[key] for key in ENVIRONMENTS[environment]}
    values[ENVIRONMENTS[environment][0]] = None
    getter = AsyncMock(return_value=({row['date']: values}, []))
    monkeypatch.setattr('analysis.data_ingestion.environmental_days', getter)
    retained, excluded = asyncio.run(align_history([row], environment, lambda _: None, retain_partial=True))
    assert len(retained) == 1 and not excluded
    assert retained[0]['missing'] == [ENVIRONMENTS[environment][0]]
    strict, excluded = asyncio.run(align_history([row], environment, lambda _: None))
    assert not strict and len(excluded) == 1
    unsupported = {**row, 'date': '2021-01-01' if environment == 'marine' else str(date.today())}
    before = getter.call_count
    retained, excluded = asyncio.run(align_history([unsupported], environment, lambda _: None, retain_partial=True))
    assert not retained and excluded[0]['reason'] and getter.call_count == before


@pytest.mark.parametrize('environment', ['terrestrial', 'marine'])
def test_rf_models_report_imputation_and_validate_same_records(environment):
    rows = model_records(environment)
    for i in range(0, len(rows), 7): rows[i][ENVIRONMENTS[environment][0]] = None
    model, meta = train_model(rows, environment, 'rf')
    assert hasattr(model, 'proximity_imputer_')
    assert meta['imputation']['imputed_records'] == 35
    assert meta['n_records'] == meta['imputation']['complete_records'] + meta['imputation']['imputed_records']
    for name in ('spatial', 'chronological'):
        split = meta['validation'][name]
        assert split
        assert split['n_train'] == sum(split['imputation']['training'][k] for k in ('complete_records', 'imputed_records'))
        assert split['n_test'] == sum(split['imputation']['test'][k] for k in ('complete_records', 'imputed_records'))
        train_ids = {r['id'] for r in split['imputation']['training']['records']}
        assert train_ids.isdisjoint(r['id'] for r in split['imputation']['test']['records'])
    with pytest.raises(ValueError, match='finite'):
        train_model(rows, environment, 'glm')


def test_holdout_labels_cannot_change_training_or_test_imputation():
    from analysis.probability_model import evaluate_split
    data = frame(size=100)
    data.loc[::7, 'air_temp'] = np.nan
    features = ENVIRONMENTS['terrestrial'] + SEASONAL
    train, test = np.arange(80), np.arange(80, 100)
    first = evaluate_split(data, features, 'rf', train, test, 'terrestrial')
    data.loc[test, 'presence'] = 1 - data.loc[test, 'presence']
    flipped = evaluate_split(data, features, 'rf', train, test, 'terrestrial')
    assert first['imputation'] == flipped['imputation']


def test_post_imputation_class_and_sample_minimums_are_enforced(monkeypatch):
    rows = model_records()[:40]
    for row in rows:
        if row['presence'] == 0: row['air_temp'] = None
    monkeypatch.setattr('analysis.imputation.proximity', lambda fitted, queries, donors: np.zeros((len(queries), len(donors))))
    with pytest.raises(ValueError, match='Insufficient evidence after imputation'):
        train_model(rows, 'terrestrial', 'rf')
