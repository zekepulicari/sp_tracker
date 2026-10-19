"""Grouped and chronological validation of presence/background classifiers."""
import math
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, balanced_accuracy_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from analysis.features import ENVIRONMENTS, SEASONAL, seasonality
from analysis.imputation import ProximityImputer, ImputationError, eligibility_reason, exclusion, forest


def estimator(method):
    if method == 'rf':
        return forest()
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


def evaluate_split(df, features, method, train, test, environment):
    training, testing = df.iloc[train].copy(), df.iloc[test].copy()
    imputation = None
    if method == 'rf':
        imputer = ProximityImputer(features, environment)
        training = imputer.fit_transform(training)
        testing, test_imputation = imputer.transform(testing)
        imputation = {'training': imputer.metadata, 'test': test_imputation}
    if (len(training) < 20 or len(testing) < 10 or any(
            part.presence.value_counts().reindex([0, 1], fill_value=0).min() < 3 for part in (training, testing))):
        raise ValueError('Insufficient retained records or classes after split-specific imputation.')
    trained = estimator(method).fit(training[features], training.presence)
    # Use exactly the retained records, but never the imputed environmental columns.
    baseline = estimator('glm').fit(training[SEASONAL], training.presence)
    actual = metrics(testing.presence, trained.predict_proba(testing[features])[:, 1])
    seasonal = metrics(testing.presence, baseline.predict_proba(testing[SEASONAL])[:, 1])
    return {'model': actual, 'seasonal_baseline': seasonal,
            'improves_baseline': actual['auc'] > seasonal['auc'] and actual['balanced_accuracy'] >= seasonal['balanced_accuracy'],
            'n_train': len(training), 'n_test': len(testing), 'imputation': imputation}


def train_model(records, environment, method):
    exclusions = []
    if len(records) > 1000:
        raise ValueError('Insufficient evidence: at most 1,000 training records are supported.')
    if method == 'rf':
        eligible = []
        for record in records:
            reason = eligibility_reason(record, environment)
            if reason:
                exclusions.append(exclusion(record, environment, reason))
            else:
                eligible.append(record)
        records = eligible
    df = pd.DataFrame([{**r, **seasonality(int(r['date'][5:7]))} for r in records])
    features = ENVIRONMENTS[environment] + SEASONAL
    if len(df) < 40 or df.presence.value_counts().reindex([0, 1], fill_value=0).min() < 15:
        raise ValueError('Insufficient evidence: need at least 15 usable sightings and 15 background samples, and 40 records overall.')
    df = df.reindex(columns=list(dict.fromkeys([*df.columns, *features])))
    if method != 'rf' and not np.isfinite(df[features].to_numpy(dtype=float)).all():
        raise ValueError('Insufficient evidence: environmental values must be finite.')
    if all(df[key].nunique() <= 1 for key in ENVIRONMENTS[environment]):
        raise ValueError('Insufficient evidence: environmental predictors are constant.')
    groups = split_groups(df)
    validation = {'spatial': None, 'chronological': None, 'experimental': True, 'ranking_allowed': False,
                  'unavailable_reasons': {}}
    if len(set(groups)) >= 4:
        splits = GroupShuffleSplit(n_splits=8, test_size=.25, random_state=42).split(df, groups=groups)
        for train, test in splits:
            if usable_split(df, train, test):
                try:
                    validation['spatial'] = evaluate_split(df, features, method, train, test, environment)
                    validation['unavailable_reasons'].pop('spatial', None)
                    break
                except ValueError as exc:
                    validation['unavailable_reasons']['spatial'] = str(exc)
    unique_dates = sorted(df.date.unique())
    if len(unique_dates) >= 10:
        cutoff = unique_dates[max(1, int(len(unique_dates) * .8))]
        train = np.flatnonzero((df.date < cutoff).values)
        test = np.flatnonzero((df.date >= cutoff).values)
        if usable_split(df, train, test):
            try:
                validation['chronological'] = {**evaluate_split(df, features, method, train, test, environment), 'cutoff': cutoff}
            except ValueError as exc:
                validation['unavailable_reasons']['chronological'] = str(exc)
    validation['experimental'] = not (validation['spatial'] and validation['chronological'])
    validation['ranking_allowed'] = not validation['experimental'] and all(
        validation[key]['improves_baseline'] for key in ('spatial', 'chronological'))
    imputer = None
    if method == 'rf':
        imputer = ProximityImputer(features, environment)
        try:
            df = imputer.fit_transform(df)
        except ImputationError as exc:
            exc.exclusions = exclusions + exc.exclusions
            raise
        imputer.metadata['exclusions'] = exclusions + imputer.metadata['exclusions']
        if len(df) < 40 or df.presence.value_counts().reindex([0, 1], fill_value=0).min() < 15:
            raise ImputationError('Insufficient evidence after imputation: need 40 records and 15 of each class.', imputer.metadata['exclusions'])
    model = estimator(method).fit(df[features], df.presence)
    if imputer is not None:
        model.proximity_imputer_ = imputer
    reference = model.predict_proba(df[features])[:, 1]
    importance = {}
    if method == 'rf':
        importance = {k: round(float(v), 5) for k, v in zip(features, model.feature_importances_)}
    metadata = {'model_type': 'Random Forest' if method == 'rf' else 'Regularized logistic regression',
                'features': features, 'variable_importance': importance, 'validation': validation,
                'bounds': {k: [float(df[k].min()), float(df[k].max())] for k in ENVIRONMENTS[environment]},
                'n_records': len(df), 'reference_quartiles': np.quantile(reference, [.25, .75]).tolist()}
    if imputer is not None:
        metadata['imputation'] = imputer.metadata
        metadata['training_records'] = [{'id': r['id'], 'date': r['date'], 'presence': int(r['presence'])}
                                         for r in df.to_dict('records')]
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
