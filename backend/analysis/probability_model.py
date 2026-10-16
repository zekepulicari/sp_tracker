"""Grouped and chronological validation of presence/background classifiers."""
import math
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, balanced_accuracy_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from analysis.features import ENVIRONMENTS, SEASONAL, seasonality


def estimator(method):
    if method == 'rf':
        return RandomForestClassifier(n_estimators=200, min_samples_leaf=3, max_depth=8, random_state=42, n_jobs=1)
    return make_pipeline(StandardScaler(), LogisticRegression(C=1, max_iter=1000, random_state=42))


def metrics(y, scores):
    if len(set(y)) < 2 or not np.isfinite(scores).all():
        raise ValueError('Insufficient evidence to validate both classes.')
    return {'auc': round(float(roc_auc_score(y, scores)), 4),
            'balanced_accuracy': round(float(balanced_accuracy_score(y, scores >= .5)), 4)}


def usable_split(df, train, test):
    return len(train) >= 20 and len(test) >= 10 and all(
        df.iloc[index].presence.value_counts().reindex([0, 1], fill_value=0).min() >= 3
        for index in (train, test))


def split_groups(df):
    # Approximately 10 km cells, kept intact along with all dates at that cell.
    return (np.floor(df.lat / .1).astype(str) + ':' + np.floor(df.lng / .1).astype(str)).values


def evaluate_split(df, features, method, train, test):
    trained = estimator(method).fit(df.iloc[train][features], df.iloc[train].presence)
    baseline = estimator('glm').fit(df.iloc[train][SEASONAL], df.iloc[train].presence)
    actual = metrics(df.iloc[test].presence, trained.predict_proba(df.iloc[test][features])[:, 1])
    seasonal = metrics(df.iloc[test].presence, baseline.predict_proba(df.iloc[test][SEASONAL])[:, 1])
    return {'model': actual, 'seasonal_baseline': seasonal,
            'improves_baseline': actual['auc'] > seasonal['auc'] and actual['balanced_accuracy'] >= seasonal['balanced_accuracy'],
            'n_train': len(train), 'n_test': len(test)}


def train_model(records, environment, method):
    df = pd.DataFrame([{**r, **seasonality(int(r['date'][5:7]))} for r in records])
    features = ENVIRONMENTS[environment] + SEASONAL
    if len(df) < 40 or df.presence.value_counts().reindex([0, 1], fill_value=0).min() < 15:
        raise ValueError('Insufficient evidence: need at least 15 usable sightings and 15 background samples, and 40 records overall.')
    if not np.isfinite(df[features].to_numpy()).all():
        raise ValueError('Insufficient evidence: environmental values must be finite.')
    if all(df[key].nunique() <= 1 for key in ENVIRONMENTS[environment]):
        raise ValueError('Insufficient evidence: environmental predictors are constant.')
    groups = split_groups(df)
    validation = {'spatial': None, 'chronological': None, 'experimental': True, 'ranking_allowed': False}
    if len(set(groups)) >= 4:
        splits = GroupShuffleSplit(n_splits=8, test_size=.25, random_state=42).split(df, groups=groups)
        for train, test in splits:
            if usable_split(df, train, test):
                validation['spatial'] = evaluate_split(df, features, method, train, test)
                break
    unique_dates = sorted(df.date.unique())
    if len(unique_dates) >= 10:
        cutoff = unique_dates[max(1, int(len(unique_dates) * .8))]
        train = np.flatnonzero((df.date < cutoff).values)
        test = np.flatnonzero((df.date >= cutoff).values)
        if usable_split(df, train, test):
            validation['chronological'] = {**evaluate_split(df, features, method, train, test), 'cutoff': cutoff}
    validation['experimental'] = not (validation['spatial'] and validation['chronological'])
    validation['ranking_allowed'] = not validation['experimental'] and all(
        validation[key]['improves_baseline'] for key in ('spatial', 'chronological'))
    model = estimator(method).fit(df[features], df.presence)
    reference = model.predict_proba(df[features])[:, 1]
    importance = {}
    if method == 'rf':
        importance = {k: round(float(v), 5) for k, v in zip(features, model.feature_importances_)}
    metadata = {'model_type': 'Random Forest' if method == 'rf' else 'Regularized logistic regression',
                'features': features, 'variable_importance': importance, 'validation': validation,
                'bounds': {k: [float(df[k].min()), float(df[k].max())] for k in ENVIRONMENTS[environment]},
                'n_records': len(df), 'reference_quartiles': np.quantile(reference, [.25, .75]).tolist()}
    return model, metadata


def predict(model, metadata, conditions, day):
    missing = [k for k in metadata['bounds'] if conditions.get(k) is None]
    if missing:
        return {'available': False, 'missing': missing, 'reason': 'Required environmental data is unavailable.'}
    outside = [k for k, bounds in metadata['bounds'].items() if not bounds[0] <= conditions[k] <= bounds[1]]
    row = {**conditions, **seasonality(int(str(day)[5:7]))}
    score = float(model.predict_proba(pd.DataFrame([row])[metadata['features']])[0, 1])
    if not math.isfinite(score):
        return {'available': False, 'reason': 'The model returned a non-finite result.'}
    return {'available': True, 'relative_score': round(score, 6), 'extrapolated_variables': outside}
