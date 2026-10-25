"""Grouped and chronological validation of presence/background classifiers."""
import math
import copy
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, balanced_accuracy_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from analysis.features import ENVIRONMENTS, SEASONAL, seasonality
from analysis.imputation import ProximityImputer, ImputationError, eligibility_reason, exclusion, forest
from analysis.requirements import (analysis_requirements, MODEL_REQUIREMENTS as MR,
    SPLIT_REQUIREMENTS as SR, SPATIAL_REQUIREMENTS as GR, CHRONOLOGICAL_REQUIREMENTS as CR)


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
    return len(train) >= SR['min_train'] and len(test) >= SR['min_test'] and all(
        df.iloc[index].presence.value_counts().reindex([0, 1], fill_value=0).min() >= SR['min_each_class']
        for index in (train, test))


def split_groups(df):
    # Degree-cell size varies with latitude; all dates in a cell stay together.
    return (np.floor(df.lat / GR['cell_degrees']).astype(str) + ':' + np.floor(df.lng / GR['cell_degrees']).astype(str)).values


def evidence_eligibility(records=None, stage='not_evaluated', final=True):
    """Keep measured counts separate from final retention when imputation has not finished."""
    counts = {k: None for k in ('aligned_sightings', 'aligned_background', 'usable_sightings',
                                'usable_background', 'usable_total')}
    spatial = {'n_groups': None, 'sighting_groups': None}
    chronological = {'n_dates': None}
    if records is not None:
        rows = list(records)
        counts['aligned_sightings'] = sum(row['presence'] == 1 for row in rows)
        counts['aligned_background'] = sum(row['presence'] == 0 for row in rows)
        if final:
            counts.update(usable_sightings=counts['aligned_sightings'],
                          usable_background=counts['aligned_background'], usable_total=len(rows))
        if rows:
            df = pd.DataFrame(rows)
            groups = split_groups(df)
            spatial = {'n_groups': len(set(groups)), 'sighting_groups': len(set(groups[df.presence == 1]))}
            chronological['n_dates'] = int(df.date.nunique())
        else:
            spatial = {'n_groups': 0, 'sighting_groups': 0}
            chronological['n_dates'] = 0
    return {'stage': stage, 'requirements': analysis_requirements(), 'counts': counts,
            'spatial': spatial, 'chronological': chronological}


def split_counts(df, train, test):
    return {name: {'records': len(index),
                   'sightings': int((df.iloc[index].presence == 1).sum()),
                   'background': int((df.iloc[index].presence == 0).sum())}
            for name, index in (('training', train), ('test', test))}


def split_reason(counts):
    return (f"Training: {counts['training']['records']} records "
            f"({counts['training']['sightings']} sightings, {counts['training']['background']} backgrounds); "
            f"test: {counts['test']['records']} records "
            f"({counts['test']['sightings']} sightings, {counts['test']['background']} backgrounds). "
            f"Need {SR['min_train']} training, {SR['min_test']} test, and {SR['min_each_class']} of each class in each portion.")


def evaluate_split(df, features, method, train, test, environment):
    training, testing = df.iloc[train].copy(), df.iloc[test].copy()
    imputation = None
    if method == 'rf':
        imputer = ProximityImputer(features, environment)
        training = imputer.fit_transform(training)
        testing, test_imputation = imputer.transform(testing)
        imputation = {'training': imputer.metadata, 'test': test_imputation}
    if (len(training) < SR['min_train'] or len(testing) < SR['min_test'] or any(
            part.presence.value_counts().reindex([0, 1], fill_value=0).min() < SR['min_each_class'] for part in (training, testing))):
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
    context = {'eligibility': evidence_eligibility(records, 'aligned', final=method != 'rf'), 'validation': None}
    try:
        return _train_model(records, environment, method, context)
    except ValueError as exc:
        exc.eligibility = copy.deepcopy(context['eligibility'])
        exc.validation = copy.deepcopy(context['validation'])
        raise


def _train_model(records, environment, method, context):
    exclusions = []
    if len(records) > MR['max_records']:
        raise ValueError(f"Insufficient evidence: at most {MR['max_records']:,} training records are supported.")
    if method == 'rf':
        eligible = []
        for record in records:
            reason = eligibility_reason(record, environment)
            if reason:
                exclusions.append(exclusion(record, environment, reason))
            else:
                eligible.append(record)
        records = eligible
        context['eligibility'] = evidence_eligibility(records, 'eligible_before_imputation', final=False)
    df = pd.DataFrame([{**r, **seasonality(int(r['date'][5:7]))} for r in records])
    features = ENVIRONMENTS[environment] + SEASONAL
    if (len(df) < MR['min_records'] or
            (df.presence == 1).sum() < MR['min_sightings'] or
            (df.presence == 0).sum() < MR['min_background']):
        raise ValueError(f"Insufficient evidence: need at least {MR['min_sightings']} usable sightings and {MR['min_background']} background samples, and {MR['min_records']} records overall.")
    df = df.reindex(columns=list(dict.fromkeys([*df.columns, *features])))
    if method != 'rf' and not np.isfinite(df[features].to_numpy(dtype=float)).all():
        context['eligibility'] = evidence_eligibility(records, 'incomplete_predictors', final=False)
        raise ValueError('Insufficient evidence: environmental values must be finite.')
    if all(df[key].nunique() <= 1 for key in ENVIRONMENTS[environment]):
        raise ValueError('Insufficient evidence: environmental predictors are constant.')
    groups = split_groups(df)
    geometry = context['eligibility']
    validation = {'spatial': None, 'chronological': None, 'experimental': True, 'ranking_allowed': False,
                  'unavailable_reasons': {}, 'diagnostics': {
                      'spatial': {**geometry['spatial'], 'attempted_splits': 0, 'candidates': []},
                      'chronological': dict(geometry['chronological'])}}
    context['validation'] = validation
    if len(set(groups)) >= GR['min_groups']:
        splits = GroupShuffleSplit(n_splits=GR['max_splits'], test_size=.25, random_state=42).split(df, groups=groups)
        for train, test in splits:
            counts = split_counts(df, train, test)
            validation['diagnostics']['spatial']['attempted_splits'] += 1
            validation['diagnostics']['spatial']['candidates'].append(counts)
            if usable_split(df, train, test):
                try:
                    validation['spatial'] = evaluate_split(df, features, method, train, test, environment)
                    validation['unavailable_reasons'].pop('spatial', None)
                    break
                except ValueError as exc:
                    validation['unavailable_reasons']['spatial'] = str(exc)
            elif 'spatial' not in validation['unavailable_reasons']:
                validation['unavailable_reasons']['spatial'] = 'No eligible grouped split. ' + split_reason(counts)
    else:
        validation['unavailable_reasons']['spatial'] = (
            f"Occupied cells: {len(set(groups))}; need at least {GR['min_groups']}. "
            f"Cells containing sightings: {geometry['spatial']['sighting_groups']}. More observations in the same cells do not add spatial separation.")
    unique_dates = sorted(df.date.unique())
    if len(unique_dates) >= CR['min_dates']:
        cutoff = unique_dates[max(1, int(len(unique_dates) * .8))]
        train = np.flatnonzero((df.date < cutoff).values)
        test = np.flatnonzero((df.date >= cutoff).values)
        validation['diagnostics']['chronological'].update(cutoff=cutoff, candidate=split_counts(df, train, test))
        if usable_split(df, train, test):
            try:
                validation['chronological'] = {**evaluate_split(df, features, method, train, test, environment), 'cutoff': cutoff}
            except ValueError as exc:
                validation['unavailable_reasons']['chronological'] = str(exc)
        else:
            validation['unavailable_reasons']['chronological'] = 'No eligible chronological split. ' + split_reason(split_counts(df, train, test))
    else:
        validation['unavailable_reasons']['chronological'] = f"Distinct dates: {len(unique_dates)}; need at least {CR['min_dates']}."
    validation['experimental'] = not (validation['spatial'] and validation['chronological'])
    validation['ranking_allowed'] = not validation['experimental'] and all(
        validation[key]['improves_baseline'] for key in ('spatial', 'chronological'))
    imputer = None
    if method == 'rf':
        imputer = ProximityImputer(features, environment)
        try:
            df = imputer.fit_transform(df)
        except ImputationError as exc:
            context['eligibility']['stage'] = 'imputation_failed'
            exc.exclusions = exclusions + exc.exclusions
            raise
        imputer.metadata['exclusions'] = exclusions + imputer.metadata['exclusions']
        initial_counts = context['eligibility']['counts']
        context['eligibility'] = evidence_eligibility(df.to_dict('records'), 'retained_after_imputation')
        for key in ('aligned_sightings', 'aligned_background'):
            context['eligibility']['counts'][key] = initial_counts[key]
        if (len(df) < MR['min_records'] or (df.presence == 1).sum() < MR['min_sightings'] or
                (df.presence == 0).sum() < MR['min_background']):
            raise ImputationError(f"Insufficient evidence after imputation: need {MR['min_records']} records, {MR['min_sightings']} sightings, and {MR['min_background']} backgrounds.", imputer.metadata['exclusions'])
    context['eligibility']['stage'] = 'eligible_for_fit'
    model = estimator(method).fit(df[features], df.presence)
    context['eligibility']['stage'] = 'model_fitted'
    if imputer is not None:
        model.proximity_imputer_ = imputer
    reference = model.predict_proba(df[features])[:, 1]
    importance = {}
    if method == 'rf':
        importance = {k: round(float(v), 5) for k, v in zip(features, model.feature_importances_)}
    metadata = {'model_type': 'Random Forest' if method == 'rf' else 'Regularized logistic regression',
                'features': features, 'variable_importance': importance, 'validation': validation,
                'bounds': {k: [float(df[k].min()), float(df[k].max())] for k in ENVIRONMENTS[environment]},
                'n_records': len(df), 'reference_quartiles': np.quantile(reference, [.25, .75]).tolist(),
                'eligibility': context['eligibility']}
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
