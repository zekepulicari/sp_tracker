"""Train-only, inductive forest proximity imputation of historical predictors."""
from datetime import date, timedelta
import math
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from analysis.features import ENVIRONMENTS

VERSION = 'proximity-1'
PARAMETERS = {'iterations': 5, 'n_estimators': 200, 'max_depth': 8,
              'min_samples_leaf': 3, 'seed': 42, 'min_donors': 15,
              'max_missing_fraction': .5, 'max_records': 1000, 'max_restarts': 5}


class ImputationError(ValueError):
    def __init__(self, message, exclusions=()):
        super().__init__(message)
        self.exclusions = list(exclusions)


def forest():
    return RandomForestClassifier(n_estimators=PARAMETERS['n_estimators'], max_depth=PARAMETERS['max_depth'],
                                  min_samples_leaf=PARAMETERS['min_samples_leaf'],
                                  random_state=PARAMETERS['seed'], n_jobs=1)


def missing_features(record, environment):
    return [key for key in ENVIRONMENTS[environment]
            if record.get(key) is None or not math.isfinite(float(record[key]))]


def eligibility_reason(record, environment):
    try:
        day = date.fromisoformat(str(record['date']))
        if not (-90 <= float(record['lat']) <= 90 and -180 <= float(record['lng']) <= 180):
            return 'Invalid geographic coordinates.'
    except (ValueError, TypeError, KeyError):
        return 'Invalid location or date.'
    if day > date.today() - timedelta(days=5) or (environment == 'marine' and day < date(2022, 1, 1)):
        return 'Outside supported historical environmental dates.'
    missing = missing_features(record, environment)
    if environment == 'marine' and all(k in missing for k in ('sst', 'wave_height', 'ocean_current_velocity')):
        return 'No observed marine predictor; marine coverage is unsupported.'
    if len(missing) > len(ENVIRONMENTS[environment]) * PARAMETERS['max_missing_fraction']:
        return 'More than half of environmental predictors are missing.'
    return None


def exclusion(record, environment, reason):
    return {'id': record['id'], 'date': str(record['date']),
            'missing': missing_features(record, environment), 'reason': reason}


def proximity(fitted, queries, donors):
    """At most a 1000×1000 float matrix plus one tree's boolean comparison."""
    result = np.zeros((len(queries), len(donors)), dtype=np.float32)
    for tree in fitted.estimators_:
        result += tree.apply(queries)[:, None] == tree.apply(donors)[None, :]
    return result / len(fitted.estimators_)


def weighted_update(filled, original, missing, weights, environmental_count):
    updated = filled.copy()
    unresolved = np.zeros(len(filled), dtype=bool)
    for column in range(environmental_count):
        targets = np.flatnonzero(missing[:, column])
        donors = np.flatnonzero(np.isfinite(original[:, column]))
        if not len(targets):
            continue
        selected = weights[np.ix_(targets, donors)]
        totals = selected.sum(axis=1, dtype=np.float64)
        supported = totals > 0
        unresolved[targets[~supported]] = True
        updated[targets[supported], column] = (
            selected[supported] @ original[donors, column]) / totals[supported]
    return updated, unresolved


class ProximityImputer:
    def __init__(self, features, environment):
        self.features = list(features)
        self.environment = environment
        self.environmental_count = len(ENVIRONMENTS[environment])

    def _matrix(self, frame):
        values = frame[self.features].to_numpy(dtype=float, copy=True)
        values[:, :self.environmental_count][~np.isfinite(values[:, :self.environmental_count])] = np.nan
        if not np.isfinite(values[:, self.environmental_count:]).all():
            raise ValueError('Insufficient evidence: seasonality must be finite.')
        return values

    def _initialize(self, original):
        missing = ~np.isfinite(original)
        filled = np.where(missing, self.medians, original)
        return filled, missing

    def fit_transform(self, frame):
        if len(frame) > PARAMETERS['max_records']:
            raise ValueError('Insufficient evidence: proximity imputation supports at most 1,000 records.')
        current = frame.copy()
        exclusions = []
        for restart in range(PARAMETERS['max_restarts'] + 1):
            if not len(current):
                raise ImputationError('Insufficient evidence: no supported proximity donors remain.', exclusions)
            original = self._matrix(current)
            for column, key in enumerate(ENVIRONMENTS[self.environment]):
                observed = original[np.isfinite(original[:, column]), column]
                if (len(observed) < PARAMETERS['min_donors']
                        or 1 - len(observed) / len(current) > PARAMETERS['max_missing_fraction']
                        or len(np.unique(observed)) < 2):
                    raise ImputationError(f'Insufficient evidence: {key} needs 15 observed donors, two distinct values, and at most 50% missingness in training.', exclusions)
            self.medians = np.nanmedian(original, axis=0)
            filled, missing = self._initialize(original)
            unresolved = np.zeros(len(current), dtype=bool)
            iterations = 0
            if missing.any():
                for _ in range(PARAMETERS['iterations']):
                    fitted = forest().fit(filled, current.presence.to_numpy())
                    filled, unresolved = weighted_update(filled, original, missing,
                        proximity(fitted, filled, filled), self.environmental_count)
                    iterations += 1
                    if unresolved.any():
                        break
            if unresolved.any():
                exclusions.extend(exclusion(row, self.environment, 'No observed donor has positive forest proximity.')
                                  for row in current.iloc[np.flatnonzero(unresolved)].to_dict('records'))
                current = current.iloc[np.flatnonzero(~unresolved)].copy()
                # Refit from original values so rejected rows cannot remain donors.
                continue
            self.original = original
            self.reference = filled
            self.forest = forest().fit(filled, current.presence.to_numpy())
            self.donor_counts = {key: int(np.isfinite(original[:, i]).sum())
                                 for i, key in enumerate(ENVIRONMENTS[self.environment])}
            completed = current.copy()
            completed[self.features] = filled
            self.metadata = self.describe(current, completed, missing, exclusions)
            self.metadata.update(parameters=dict(PARAMETERS), donor_counts=self.donor_counts,
                                 iterations_performed=iterations, restarts=restart)
            return completed
        raise ImputationError('Insufficient evidence: proximity donors could not stabilize after exclusions.', exclusions)

    def transform(self, frame):
        """No labels or other query rows participate in a query's transformation."""
        if len(frame) > PARAMETERS['max_records']:
            raise ValueError('Proximity transformation supports at most 1,000 records.')
        if not len(frame):
            return frame.copy(), self.describe(frame, frame, np.zeros((0, len(self.features)), bool), [])
        original = self._matrix(frame)
        filled, missing = self._initialize(original)
        unresolved = np.zeros(len(frame), dtype=bool)
        for _ in range(PARAMETERS['iterations'] if missing.any() else 0):
            filled, failed = weighted_update(filled, self.original, missing,
                proximity(self.forest, filled, self.reference), self.environmental_count)
            unresolved |= failed
        exclusions = [exclusion(row, self.environment, 'No observed training donor has positive forest proximity.')
                      for row in frame.iloc[np.flatnonzero(unresolved)].to_dict('records')]
        positions = np.flatnonzero(~unresolved)
        completed = frame.iloc[positions].copy()
        completed[self.features] = filled[positions]
        return completed, self.describe(frame.iloc[positions], completed, missing[positions], exclusions)

    def describe(self, original, completed, missing, exclusions):
        masks = missing[:, :self.environmental_count]
        records = []
        for position, row in enumerate(original.to_dict('records')):
            keys = [key for i, key in enumerate(ENVIRONMENTS[self.environment]) if masks[position, i]]
            records.append({'id': row['id'], 'date': str(row['date']),
                            'missing': keys, 'estimated_values': {key: float(completed.iloc[position][key]) for key in keys}})
        imputed = int(masks.any(axis=1).sum())
        return {'method': 'forest_proximity', 'version': VERSION,
                'complete_records': len(original) - imputed, 'imputed_records': imputed,
                'observed_cells': int(masks.size - masks.sum()), 'imputed_cells': int(masks.sum()),
                'records': records, 'exclusions': exclusions}
