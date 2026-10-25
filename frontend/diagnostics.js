import {escapeHtml as e} from './state.js';

const number = (value, fallback='Not evaluated') => typeof value === 'number' && Number.isFinite(value) ? e(value) : fallback;
const score = value => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(3) : 'Not recorded';
const definitions = '<p class="help">Sightings are recorded observations. Background samples are generated comparison locations/dates, not confirmed absences. Usable records are retained sightings and backgrounds combined.</p>';

export function requirementsHtml(method, requirements) {
    const description = method === 'rustic'
        ? 'Historical Profile counts when local sightings were recorded. It does not fit an environmental model or estimate a successful visit.'
        : method === 'rf'
        ? 'Key Factors is an advanced analysis using Random Forest to identify variables that help distinguish sightings from backgrounds. It needs usable environmental measurements, not just sightings. Eligible missing historical values may be estimated; importance is not causation or a forecast.'
        : 'Environmental Outlook uses logistic regression and complete historical predictors to compare the selected day’s conditions. Complete environmental coverage and observations spread across places and dates are required; a large sighting count alone is insufficient.';
    let html = `<p id="analysis-method-description">${e(description)}</p>`;
    if (method !== 'rustic') {
        if (!requirements) html += '<p class="help">Requirements could not yet be loaded. The server will still enforce them when an analysis runs.</p>';
        else {
            const {model:m, split:s, spatial:g, chronological:c, rf} = requirements;
            html += `<p><strong>Model fitting:</strong> at least ${number(m.min_sightings)} usable sightings, ${number(m.min_background)} usable backgrounds, and ${number(m.min_records)} usable records overall.</p>`;
            if (method === 'rf') html += `<p class="help">Each predictor needs ${number(rf.min_donors)} observed training donors, ${number(rf.min_distinct_values)} distinct observed values, and at most ${number(rf.max_missing_fraction*100)}% missingness. Records missing more than half their environmental predictors are excluded; marine records need at least one observed marine predictor. Imputation cannot create unsupported coverage.</p>`;
            html += `<details><summary>Independent validation requirements</summary><p>Spatial validation needs at least ${number(g.min_groups)} occupied ${number(g.cell_degrees)}° cells overall and a valid grouped split. Cells containing sightings matter too; repeatedly recording one colony does not create independent places.</p><p>Each holdout needs at least ${number(s.min_train)} training records, ${number(s.min_test)} test records, and ${number(s.min_each_class)} of each class in each portion. Chronological validation needs at least ${number(c.min_dates)} distinct dates.</p><p>These are validation requirements, not extra observations required just to fit a model. Key Factors can show descriptive importance even when validation is limited. Outlook favorability requires both holdouts to outperform the seasonal baseline, plus supported forecasts inside the training range.</p></details>`;
        }
    }
    return html + definitions;
}

export function outcomeHtml(result, run) {
    const method = run?.payload.method;
    if (run?.path !== '/api/analysis/run' || method === 'rustic') return '';
    const label = method === 'rf' ? 'Key Factors' : 'Environmental Outlook';
    const validation = result.model?.validation;
    let title, message;
    if (!result.model) {
        const evaluated = result.evidence?.eligibility?.stage !== 'not_evaluated' && result.evidence?.eligibility;
        title = evaluated ? 'Insufficient usable environmental evidence' : `${label} unavailable`;
        message = evaluated
            ? `No ${label} model could be fitted. Recorded sightings alone are not enough: the retained environmental measurements must meet the fitting requirements. See the reason above and the counts and exclusions below. Any monthly chart is supporting historical evidence.`
            : `${result.summary} Any monthly chart is supporting historical evidence, not the requested environmental result.`;
    } else if (method === 'rf') {
        if (!Object.keys(result.model.variable_importance || {}).length) {
            title = 'Feature importance unavailable';
            message = 'A model was fitted but no usable importance values were returned. See the technical evidence.';
        } else if (!validation?.ranking_allowed) {
            title = 'Key Factors available · predictive validation limited';
            message = 'The model fitted successfully. Its importance bars are shown immediately below. Independent validation does not support predictive use; this does not hide the descriptive associations or mean that the sighting count was too low.';
        } else return '';
    } else {
        const days = result.days || [];
        if (!days.some(day => day.available)) {
            title = 'Forecast data unavailable';
            message = 'The historical model fitted, but required forecast measurements are missing. A selected-day assessment cannot be shown. See the forecast details below.';
        } else if (run.payload.operation === 'compare_days' && !days.some(day => day.rank)) {
            title = 'Day ranking unavailable';
            message = result.summary;
        } else if (!validation?.ranking_allowed) {
            title = 'Conditions available · favorability unavailable';
            const unavailable = ['spatial','chronological'].filter(key => !validation?.[key]);
            const failed = ['spatial','chronological'].filter(key => validation?.[key] && !validation[key].improves_baseline);
            message = `The model fitted successfully; this is not a failure of the count requirements. ${unavailable.length ? `Independent validation unavailable: ${unavailable.join(' and ')}. ` : ''}${failed.length ? `The model did not outperform the seasonal baseline in ${failed.join(' and ')} validation. ` : ''}Forecast conditions are shown below, but a reliable favorability assessment is withheld.`;
        } else if (days.some(day => day.extrapolated_variables?.length)) {
            title = 'Forecast outside the supported training range';
            message = 'The model fitted and validation passed, but some forecast conditions extend beyond the historical evidence. Conditions are shown; an assessment for those days is withheld.';
        } else return '';
    }
    return `<section class="card analysis-warning" role="status"><h3>${e(title)}</h3><p>${e(message)}</p></section>`;
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
    ].filter(([label]) => environmental || ['Retrieved sightings','Excluded records'].includes(label));
    let html = `<section class="card"><h3>Evidence checklist</h3>${environmental ? '<p class="help">Only usable sightings, usable backgrounds, and total usable records have count minimums. Retrieved and excluded counts are accounting information. Meeting the three minimums is necessary for fitting; environmental eligibility must also pass. Independent validation is assessed separately below.</p>' : ''}<table><caption>${environmental ? 'Actual evidence and minimum counts to fit an environmental model' : 'Historical evidence; environmental fitting was not requested'}</caption><thead><tr><th>Record stage</th><th>Count</th><th>Minimum to fit</th></tr></thead><tbody>${rows.map(([label,value,min])=>`<tr><th scope="row">${e(label)}</th><td>${number(value,unknown)}</td><td>${!environmental || min === null ? 'Not applicable' : typeof min === 'number' ? `${number(min)}${typeof value === 'number' ? value < min ? ' · below minimum' : ' · met' : ''}` : 'Not recorded'}</td></tr>`).join('')}</tbody></table>${definitions}`;
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
    const verdict = validation.ranking_allowed ? 'Both independent holdouts outperformed the seasonal baseline.'
        : run?.payload.method === 'rf' && result.model
        ? 'The importance bars remain available as descriptive associations. Independent validation is incomplete or has not outperformed the seasonal baseline, so predictive skill is not established.'
        : 'Favorability assessments and day rankings are unsupported: independent validation is incomplete or has not outperformed the seasonal baseline.';
    let html = `<section class="card"><h3>Validation overview</h3><p>${fitStatus} ${verdict}</p><details><summary>How to read these metrics</summary><p class="help">AUC measures ranking of sightings versus backgrounds; 0.500 is chance-level ranking for this task. Balanced accuracy averages the two class recall rates. Both range from 0 to 1 and are not encounter probabilities. Passing requires strictly higher AUC and balanced accuracy at least as high as the baseline, in each holdout. Displayed values use three decimals; the verdict uses the recorded precision. No significance test was performed.</p></details></section>`;
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
