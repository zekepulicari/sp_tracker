"""Synthetic held-out reconstruction experiment; no wildlife or network claims."""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from analysis.features import ENVIRONMENTS, SEASONAL, seasonality
from analysis.imputation import ProximityImputer


def experiment(environment):
    rng = np.random.default_rng(42)
    latent = rng.uniform(10, 30, 240)
    values = {
        'air_temp': latent + rng.normal(0, .5, 240),
        'wind_speed': 8 + .4 * latent + rng.normal(0, .3, 240),
        'precipitation': np.maximum(0, .3 * latent - 2 + rng.normal(0, .2, 240)),
        'sst': latent + rng.normal(0, .5, 240),
        'wave_height': .05 * latent + rng.normal(0, .05, 240),
        'ocean_current_velocity': .08 * latent + rng.normal(0, .1, 240),
    }
    keys = ENVIRONMENTS[environment]
    features = keys + SEASONAL
    data = pd.DataFrame([{'id': i, 'date': str(date(2023, 1, 1) + timedelta(days=i)),
                         'lat': .1 * (i % 10), 'lng': .1 * (i // 10),
                         'presence': int(latent[i] > 20), **seasonality((i // 30) % 12 + 1),
                         **{key: float(values[key][i]) for key in keys}} for i in range(240)])
    training, testing = data.iloc[:180].copy(), data.iloc[180:].copy()
    for i in range(0, len(training), 5):
        training.loc[training.index[i], keys[(i // 5) % len(keys)]] = np.nan
    masked = testing.copy()
    for i in range(len(masked)):
        masked.loc[masked.index[i], keys[i % len(keys)]] = np.nan
    imputer = ProximityImputer(features, environment)
    imputer.fit_transform(training)
    estimated, report = imputer.transform(masked.drop(columns='presence'))
    errors = {}
    for column, key in enumerate(keys):
        indexes = estimated.index[masked.loc[estimated.index, key].isna()]
        truth = testing.loc[indexes, key].to_numpy()
        errors[key] = {'masked_cells_reconstructed': len(indexes),
                       'proximity_mae': float(np.mean(np.abs(estimated.loc[indexes, key].to_numpy() - truth))) if len(indexes) else None,
                       'training_median_mae': float(np.mean(np.abs(imputer.medians[column] - truth))) if len(indexes) else None}
    return {'environment': environment, 'seed': 42, 'training_records': len(training),
            'held_out_records': len(testing), 'excluded_queries': len(report['exclusions']),
            'metrics': errors, 'parameters': imputer.metadata['parameters']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Optional JSON artifact; default prints only.')
    args = parser.parse_args()
    result = {'notice': 'Synthetic masked-data experiment, not ecological validation. Lower MAE means better reconstruction in this example; improvement is not guaranteed on other missingness patterns.',
              'model_version': '2.2.0', 'cases': [experiment(env) for env in ENVIRONMENTS]}
    text = json.dumps(result, indent=2, allow_nan=False)
    if args.output:
        args.output.write_text(text + '\n', encoding='utf-8')
    print(text)
