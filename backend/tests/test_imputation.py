"""Proximity weighting, reproducibility, held-out isolation, and donor eligibility."""
import copy
import numpy as np
import pandas as pd
import pytest
from analysis.features import ENVIRONMENTS, SEASONAL, seasonality
from analysis.imputation import ProximityImputer, weighted_update
from test_analysis import model_records
from analysis.probability_model import train_model

def frame(environment='terrestrial', size=100):
    return pd.DataFrame([{**r, **seasonality(int(r['date'][5:7]))} for r in model_records(environment)[:size]])


def test_failed_imputation_retains_alignment_counts_without_inventing_final_retention():
    rows = model_records()
    for row in rows[20:]: row['wind_speed'] = None
    with pytest.raises(ValueError, match='observed donors') as error:
        train_model(rows, 'terrestrial', 'rf')
    diagnostic = error.value.eligibility
    assert diagnostic['stage'] == 'imputation_failed'
    assert diagnostic['counts']['aligned_sightings'] == 120
    assert diagnostic['counts']['aligned_background'] == 120
    assert diagnostic['counts']['usable_total'] is None
    assert error.value.validation['unavailable_reasons']['spatial']


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
