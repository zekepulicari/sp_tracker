import {escapeHtml as e} from './state.js';

const number = (value, fallback='Not evaluated') => typeof value === 'number' && Number.isFinite(value) ? e(value) : fallback;
const score = value => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(3) : 'Not recorded';
const definitions = '<p class="help">Sightings are recorded observations. Background samples are generated comparison locations/dates, not confirmed absences. Usable records are retained sightings and backgrounds combined.</p>';

export function requirementsHtml(method, requirements) {
    const description = method === 'rustic'
        ? 'Historical Profile counts when local sightings were recorded. It does not fit an environmental model or estimate a successful visit.'
        : method === 'rf'
        ? 'Key Factors uses Random Forest to identify variables that help distinguish sightings from backgrounds. Eligible missing historical values may be estimated; importance is not causation or a forecast.'
        : 'Environmental Outlook uses logistic regression and complete historical predictors to compare the selected day’s conditions. Complete environmental coverage and observations spread across places and dates are required; a large sighting count alone is insufficient.';
    let html = `<p id="analysis-method-description">${e(description)}</p>`;
    if (method !== 'rustic') {
        if (!requirements) html += '<p class="help">Requirements could not yet be loaded. The server will still enforce them when an analysis runs.</p>';
        else {
            const {model:m, split:s, spatial:g, chronological:c, rf} = requirements;
            html += `<p><strong>Model fitting:</strong> at least ${number(m.min_sightings)} usable sightings, ${number(m.min_background)} usable backgrounds, and ${number(m.min_records)} usable records overall.</p>`;
            if (method === 'rf') html += `<p class="help">Each predictor needs ${number(rf.min_donors)} observed training donors, ${number(rf.min_distinct_values)} distinct observed values, and at most ${number(rf.max_missing_fraction*100)}% missingness. Imputation cannot create unsupported coverage.</p>`;
            html += `<details><summary>Independent validation requirements</summary><p>Spatial validation needs at least ${number(g.min_groups)} occupied ${number(g.cell_degrees)}° cells overall and a valid grouped split. Cells containing sightings matter too; repeatedly recording one colony does not create independent places.</p><p>Each holdout needs at least ${number(s.min_train)} training records, ${number(s.min_test)} test records, and ${number(s.min_each_class)} of each class in each portion. Chronological validation needs at least ${number(c.min_dates)} distinct dates.</p><p>These are validation requirements, not extra observations required just to fit a model. Favorability requires both holdouts to outperform the seasonal baseline, plus supported forecasts inside the training range.</p></details>`;
        }
    }
    return html + definitions;
}

export function evidenceHtml(result, run, config=null) {
    const v = result.evidence;
    if (!v) return '';
    const eligibility = v.eligibility, counts = eligibility?.counts;
    const req = eligibility?.requirements || config;
    const unknown = eligibility ? 'Not evaluated' : 'Not recorded';
    const environmental = run?.payload.method !== 'rustic';
    const usableSightings = counts ? counts.usable_sightings : v.usable_sightings;
    const usableBackground = counts ? counts.usable_background : v.usable_background;
    const total = counts ? counts.usable_total : (typeof usableSightings === 'number' && typeof usableBackground === 'number' ? usableSightings+usableBackground : null);
    const rows = [
        ['Retrieved sightings',v.sightings,null], ['Generated backgrounds',v.background_samples,null],
        ['Usable sightings',usableSightings,req?.model.min_sightings],
        ['Usable backgrounds',usableBackground,req?.model.min_background],
        ['Total usable records',total,req?.model.min_records],
        ['Excluded records',v.excluded_records?.length,null]
    ];
    let html = `<section class="card"><h3>Evidence checklist</h3><table><caption>${environmental ? 'Actual evidence and minimum counts to fit an environmental model' : 'Historical evidence; environmental fitting was not requested'}</caption><thead><tr><th>Record stage</th><th>Count</th><th>Minimum to fit</th></tr></thead><tbody>${rows.map(([label,value,min])=>`<tr><th scope="row">${e(label)}</th><td>${number(value,unknown)}</td><td>${!environmental || min === null ? 'Not applicable' : typeof min === 'number' ? `${number(min)}${typeof value === 'number' ? value < min ? ' · below minimum' : ' · met' : ''}` : 'Not recorded'}</td></tr>`).join('')}</tbody></table>${definitions}`;
    if (counts?.usable_total === null && counts.aligned_sightings !== null) html += `<p class="notice">After data alignment: ${number(counts.aligned_sightings)} sightings and ${number(counts.aligned_background)} backgrounds. Final usable retention has not been evaluated${run?.payload.method === 'rf' ? ' because proximity imputation has not completed' : ''}.</p>`;
    if (v.imputed_records !== undefined) html += `<p>${number(v.complete_records)} complete records · ${number(v.imputed_records)} retained through imputation<br>${number(v.observed_cells)} observed environmental values · ${number(v.imputed_cells)} estimated values.</p>`;
    html += `<p class="help">${number(v.radius_km)} km study radius · ${e(v.date_start || 'No dates')} to ${e(v.date_end || 'No dates')}. Meeting count minimums does not guarantee environmental coverage or independent validation.</p>`;
    const reasons = new Map();
    for (const row of v.excluded_records || []) reasons.set(row.reason || 'Reason not supplied',(reasons.get(row.reason || 'Reason not supplied') || 0)+1);
    if (reasons.size) html += `<h4>Why records were excluded</h4><ul>${[...reasons].sort((a,b)=>b[1]-a[1]).map(([reason,count])=>`<li>${number(count)}: ${e(reason)}</li>`).join('')}</ul>`;
    return html + '</section>';
}

export function validationHtml(result, run) {
    if (run?.path === '/api/discovery/run' || run?.payload.method === 'rustic') return '';
    const validation = result.model?.validation || result.evidence?.validation;
    if (!validation) return result.model
        ? '<section class="card"><h3>Validation not recorded</h3><p>A model was fitted, but this result did not record independent validation details. No holdout metrics are available to display.</p></section>'
        : '<section class="card"><h3>Validation not computed</h3><p>No environmental model was fitted for this request. No holdout AUC or balanced accuracy was calculated.</p></section>';
    const fitStatus = result.model ? 'Model fitted.' : validation.spatial || validation.chronological ? 'Final model unavailable; these holdout metrics were calculated before the final fit stopped.' : 'Final model unavailable. No holdout metrics were calculated.';
    let html = `<section class="card"><h3>Validation overview</h3><p>${fitStatus} ${validation.ranking_allowed ? 'Both independent holdouts outperformed the seasonal baseline.' : 'Favorability assessments and day rankings are unsupported: independent validation is incomplete or has not outperformed the seasonal baseline.'}</p><p class="help">AUC measures ranking of sightings versus backgrounds; 0.500 is chance-level ranking for this task. Balanced accuracy averages the two class recall rates. Both range from 0 to 1 and are not encounter probabilities. Passing requires strictly higher AUC and balanced accuracy at least as high as the baseline, in each holdout. Displayed values use three decimals; the verdict uses the recorded precision. No significance test was performed.</p></section>`;
    for (const [key,name] of [['spatial','Spatial validation'],['chronological','Chronological validation']]) {
        const item = validation[key];
        const d = validation.diagnostics?.[key] || result.evidence?.eligibility?.[key];
        html += `<section class="card validation-card"><h3>${name}</h3>`;
        if (key === 'spatial') html += `<p class="help">Occupied cells: ${number(d?.n_groups,'Not recorded')} · Cells containing sightings: ${number(d?.sighting_groups,'Not recorded')} · Grouped splits attempted: ${number(d?.attempted_splits,'Not recorded')}</p>`;
        else html += `<p class="help">Distinct observation dates: ${number(d?.n_dates,'Not recorded')}${item?.cutoff ? ` · Chronological cutoff: ${e(item.cutoff)}` : ''}</p>`;
        if (item) {
            html += `<p>${item.improves_baseline ? 'Baseline comparison passed.' : 'Did not outperform the seasonal baseline under the required AUC and balanced-accuracy rule.'}</p><p>Training: ${number(item.n_train,'Not recorded')} records · Test: ${number(item.n_test,'Not recorded')} records</p><table><caption>${name}: environmental model versus seasonality only</caption><thead><tr><th>Metric</th><th>Model</th><th>Seasonal baseline</th></tr></thead><tbody><tr><th scope="row">AUC</th><td>${score(item.model?.auc)}</td><td>${score(item.seasonal_baseline?.auc)}</td></tr><tr><th scope="row">Balanced accuracy</th><td>${score(item.model?.balanced_accuracy)}</td><td>${score(item.seasonal_baseline?.balanced_accuracy)}</td></tr></tbody></table>`;
        } else html += `<p><strong>Not computed.</strong> ${e(validation.unavailable_reasons?.[key] || 'Reason not recorded for this result.')}</p>`;
        html += '</section>';
    }
    return html;
}
