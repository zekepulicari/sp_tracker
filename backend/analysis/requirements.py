"""One source for enforced analytical requirements and their public descriptions."""
from copy import deepcopy

MODEL_REQUIREMENTS = {'min_sightings': 15, 'min_background': 15, 'min_records': 40, 'max_records': 1000}
SPLIT_REQUIREMENTS = {'min_train': 20, 'min_test': 10, 'min_each_class': 3}
SPATIAL_REQUIREMENTS = {'min_groups': 4, 'cell_degrees': .1, 'max_splits': 8}
CHRONOLOGICAL_REQUIREMENTS = {'min_dates': 10}
RF_REQUIREMENTS = {'min_donors': 15, 'min_distinct_values': 2, 'max_missing_fraction': .5}


def analysis_requirements():
    return deepcopy({'model': MODEL_REQUIREMENTS, 'split': SPLIT_REQUIREMENTS,
                     'spatial': SPATIAL_REQUIREMENTS, 'chronological': CHRONOLOGICAL_REQUIREMENTS,
                     'rf': RF_REQUIREMENTS})
