import sys
sys.path.insert(0, '/home/kihonlinux/Documents/sp_tracker/backend')

import pandas as pd
import numpy as np
from analysis.correlation import compute_correlations, compute_vif
from analysis.probability_model import fit_glm, fit_random_forest, fit_cca

# Minimal test dataset (presence + pseudo-absences)
df = pd.DataFrame({
    'presence': [1,1,0,0,1,0,1,0,1,0,1,1,0,0,1],
    'sst': [15,14,10,11,16,9,17,12,15,10,14,13,9,11,16],
    'wind_speed': [5,4,8,9,3,10,2,7,4,9,3,5,11,8,2],
    'wave_height': [0.5,0.4,1.2,1.3,0.3,1.5,0.2,1.0,0.6,1.1,0.3,0.5,1.4,1.2,0.2],
    'month': [6,7,1,2,8,12,9,3,6,1,7,8,11,2,9],
    'wind_direction': [180,200,45,30,210,60,220,90,175,40,195,185,50,35,225],
    'ocean_current_velocity': [1.2,1.0,0.3,0.4,1.3,0.2,1.5,0.5,1.1,0.3,1.1,1.0,0.2,0.4,1.4],
})

print("Testing correlations...")
corr = compute_correlations(df)
assert 'pearson' in corr
assert 'spearman' in corr
print(f"  OK: pearson keys = {list(corr['pearson']['with_presence'].keys())}")

print("Testing VIF...")
vif = compute_vif(df)
assert 'scores' in vif
print(f"  OK: VIF has_collinearity = {vif['has_collinearity']}")

print("Testing GLM...")
glm = fit_glm(df)
assert 0 <= glm['accuracy'] <= 1
assert 'coefficients' in glm
print(f"  OK: GLM accuracy = {glm['accuracy']:.3f}, prob = {glm['mean_encounter_probability']:.3f}")

print("Testing Random Forest...")
rf = fit_random_forest(df)
assert 0 <= rf['accuracy'] <= 1
assert 'variable_importance' in rf
print(f"  OK: RF accuracy = {rf['accuracy']:.3f}, oob = {rf['oob_score']:.3f}")

print("Testing CCA...")
cca = fit_cca(df)
assert 'eigenvalue' in cca
print(f"  OK: CCA eigenvalue = {cca['eigenvalue']:.4f}, explained = {cca['explained_variance_pct']}%")

print()
print("ALL TESTS PASSED ✅")
