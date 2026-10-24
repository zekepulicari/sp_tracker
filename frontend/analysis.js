import {escapeHtml as e, safeUrl, readStorage, writeStorage} from './state.js';
const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const labels = {air_temp:'Air temperature',wind_speed:'Wind speed',precipitation:'Rainfall',sst:'Sea surface temperature',wave_height:'Wave height',ocean_current_velocity:'Ocean current',season_sin:'Season (sine)',season_cos:'Season (cosine)'};
const units = {air_temp:'°C',wind_speed:'km/h',precipitation:'mm/day',sst:'°C',wave_height:'m',ocean_current_velocity:'km/h'};
const methodNames = {rustic:'Historical Profile', glm:'Environmental Outlook', rf:'Key Factors'};
function runName(run) {
    if (run?.path === '/api/discovery/run') return 'Animals nearby';
    if (run?.payload.operation === 'compare_days') return 'Seven-day comparison';
    return methodNames[run?.payload.method] || 'Analysis';
}
function contextHtml(run) {
    if (!run) return '';
    const p = run.payload;
    if (run.path === '/api/discovery/run') return `<p class="help">Selected date: ${e(p.target_date)} · Animal group: ${e(p.animal_group || 'all')} · Drawn area</p>`;
    return `<p>${e(p.species)}</p><p class="help">${e(p.environment === 'marine' ? 'Marine' : 'Terrestrial')} · ${p.operation === 'compare_days' ? 'Next seven supported days' : `Selected date: ${e(p.target_date)}`}<br>Study point: ${e(p.target_lat)}, ${e(p.target_lng)} · Up to ${e(p.limit)} sightings</p>`;
}
function unavailable(result, run) {
    if (!run || run.path !== '/api/analysis/run' || run.payload.method === 'rustic') return false;
    if (!result.model || result.type === 'historical_profile') return true;
    if (run.payload.operation === 'compare_days') return !result.days?.some(day => day.rank);
    if (run.payload.method === 'rf') return !Object.keys(result.model.variable_importance || {}).length;
    return !result.days?.some(day => day.available);
}
function freeze(value) {
    if (value && typeof value === 'object') {
        Object.values(value).forEach(freeze);
        Object.freeze(value);
    }
    return value;
}
function snapshot(path, payload, selectedSpecies) {
    return freeze(structuredClone({path, payload, selectedSpecies}));
}
function conditionRows(conditions) {
    return Object.entries(conditions || {}).map(([key,value]) => `<tr><th scope="row">${e(labels[key] || key)}</th><td>${value === null || !Number.isFinite(value) ? 'Unavailable' : `${e(value.toFixed(2))} ${e(units[key] || '')}`}</td></tr>`).join('');
}
function profileHtml(profile, supporting=false) {
    const max = Math.max(1,...profile.map(row=>row.count));
    return `<section class="card"><h2>${supporting ? 'Supporting historical sightings by month' : 'Historical sightings by month'}</h2><p class="help">Counts describe the retrieved sample, not successful visits.</p><table><caption>Recorded sightings and years represented</caption><thead><tr><th>Month</th><th>Sightings</th><th>Years</th></tr></thead><tbody>${profile.map(row=>`<tr><th scope="row">${e(months[row.month-1])}</th><td>${e(row.count)}<span class="bar" aria-hidden="true" style="width:${Math.max(1,row.count/max*100)}%"></span></td><td>${e(row.years.join(', ') || '—')}</td></tr>`).join('')}</tbody></table></section>`;
}
export function resultHtml(result, run=null) {
    const limited = unavailable(result, run);
    const heading = run ? `${runName(run)}${limited ? ' unavailable' : ''}` : result.title || result.species?.name || 'Analysis evidence';
    const fallbackNotice = run?.payload.operation === 'compare_days' ? 'The requested day ranking is unavailable. Supporting evidence is shown below.' : 'The requested analysis could not be produced. Historical sightings below are supporting evidence, not its result.';
    let html = `<section class="card${limited ? ' unavailable-result' : ''}"><h2>${e(heading)}</h2>${contextHtml(run)}<p>${e(result.summary)}</p>${limited ? `<p class="notice">${fallbackNotice}</p>` : ''}${(result.warnings || []).map(w=>`<p class="notice">${e(w)}</p>`).join('')}</section>`;
    if (limited && result.evidence) {
        const evidence = result.evidence, reasons = new Map();
        for (const row of evidence.excluded_records || []) reasons.set(row.reason || 'Reason not supplied', (reasons.get(row.reason || 'Reason not supplied') || 0) + 1);
        html += `<section class="card"><h3>Environmental evidence limits</h3><p>${e(evidence.usable_sightings ?? 'Not available')} usable sightings · ${e(evidence.usable_background ?? 'Not available')} usable background samples</p>${reasons.size ? `<p>Excluded records:</p><ul>${[...reasons].sort((a,b)=>b[1]-a[1]).map(([reason,count])=>`<li>${e(count)}: ${e(reason)}</li>`).join('')}</ul>` : '<p class="help">See the explanation above and technical evidence for data availability.</p>'}</section>`;
    }
    if (result.type === 'seasonal_discovery') {
        html += `<section class="card"><h2>${e(result.title || 'Most recorded animals here in this season')}</h2><h3>Area and evidence</h3><p>${e(result.area_km2)} km² · ${e(result.records_inside)} eligible sightings inside the boundary</p><p class="help">${e(result.evidence_window.start)} to ${e(result.evidence_window.end)} · ${e(months[result.month-1])} in each year · complete query</p></section>`;
        for (const animal of result.species) {
            html += `<section class="card species-card"><span class="rank">${e(animal.rank)}</span><div><h3>${e(animal.common_name || animal.name)}</h3><em>${e(animal.name)}</em><p>${e(animal.evidence_label)} across ${e(animal.distinct_dates)} dates.</p><p class="help">Years: ${e(animal.years.join(', '))}<br>Latest recorded sighting: ${e(animal.latest_sighting)}</p><a href="${e(safeUrl(animal.source_url))}" target="_blank" rel="noopener noreferrer">Species source</a><button class="secondary analyze-animal" data-taxon="${e(animal.taxon_id)}">Examine this animal</button></div></section>`;
        }
        html += `<section class="card"><h3>Selected day's weather · separate context</h3>${result.weather.conditions ? `<table>${conditionRows(result.weather.conditions)}</table>` : ''}<p class="help">${e(result.weather.reason || 'Weather unavailable.')}</p></section>`;
        html += `<details class="card"><summary>Source timestamp and query completeness</summary><pre>${e(JSON.stringify({fetched_at:result.fetched_at,bbox_records:result.bbox_records,complete:result.complete,month:result.month,animal_group:result.animal_group},null,2))}</pre></details>`;
        return html;
    }
    if (result.interpretation) html += `<section class="card"><h3>Evidence explanation</h3><p style="white-space:pre-line">${e(result.interpretation.text)}</p><p class="help">${e(result.interpretation.notice)}</p></section>`;
    if (result.evidence) {
        const v = result.evidence;
        html += `<section class="card"><h3>Evidence used</h3><p>${e(v.sightings)} recorded sightings · ${e(v.radius_km)} km study radius</p><p class="help">${e(v.date_start || 'No dates')} to ${e(v.date_end || 'No dates')}<br>${e(v.background_samples)} generated background samples${v.usable_sightings !== undefined ? `<br>${e(v.usable_sightings)} usable sightings · ${e(v.usable_background)} usable background samples` : ''}${v.imputed_records !== undefined ? `<br>${e(v.complete_records)} complete records · ${e(v.imputed_records)} retained through proximity imputation<br>${e(v.observed_cells)} observed environmental values · ${e(v.imputed_cells)} estimated values` : ''}<br>${e(v.excluded_records.length)} records excluded; reasons are listed in technical evidence.</p></section>`;
    }
    if (result.model?.variable_importance && Object.keys(result.model.variable_importance).length) {
        if (result.model.imputation?.imputed_records) html += `<p class="notice">These importance bars depend partly on estimated environmental values. See imputation details in technical evidence; estimated values are not observed measurements.</p>`;
        const entries = Object.entries(result.model.variable_importance).sort((a,b)=>b[1]-a[1]);
        html += `<section class="card"><h2>Modeled variable associations</h2><p class="help">Relative feature importance; these values do not establish ecological causes or encounter chances.</p><table><thead><tr><th>Variable</th><th>Importance</th></tr></thead><tbody>${entries.map(([key,value])=>`<tr><th>${e(labels[key] || key)}</th><td>${e((value*100).toFixed(1))}%<span class="bar" aria-hidden="true" style="width:${Math.max(1,value*100)}%"></span></td></tr>`).join('')}</tbody></table></section>`;
    }
    if (result.weather && !result.weather.available) html += `<p class="notice">${e(result.weather.reason)}</p>`;
    if (result.days) {
        const days = [...result.days].sort((a,b)=>(a.rank || 999)-(b.rank || 999) || a.date.localeCompare(b.date));
        for (const day of days) html += `<section class="card"><h3>${day.rank ? `#${e(day.rank)} · ` : ''}${e(day.date)}</h3><span class="tag">Forecast · daily UTC measures</span><table>${conditionRows(day.conditions)}</table>${!day.available ? `<p class="notice">${e(day.reason)}</p>` : ''}${day.extrapolated_variables?.length ? `<p class="notice">Outside training range: ${e(day.extrapolated_variables.map(k=>labels[k] || k).join(', '))}. This day is not ranked.</p>` : ''}</section>`;
    }
    if (result.profile) html += profileHtml(result.profile, limited);
    html += `<details class="card"><summary>Technical evidence, validation, and relative scores</summary><p class="help">Classifier scores distinguish sightings from background samples. They are not encounter probabilities.</p><pre>${e(JSON.stringify({model:result.model,features:result.features,evidence:result.evidence,days:result.days?.map(d=>({date:d.date,relative_score:d.relative_score,available:d.available}))},null,2))}</pre></details>`;
    return html;
}

export function setupAnalysis(context) {
    const $ = id=>document.getElementById(id);
    const results = $('analysis-results'), progress = $('analysis-progress');
    let session;
    try { session = window.sessionStorage; } catch { session = null; }
    let active = false, generation = 0, currentRun = null, lastRun = null, completed = null;
    let pollTimer = null, controller = null;
    const buttons = ['btn-run-analysis','btn-discover','btn-compare-days'];
    const isCurrent = token => active && token === generation;
    function busy(value) {
        active = value; buttons.forEach(id=>$(id).disabled=value);
        results.setAttribute('aria-busy',String(value));
        if (value) $('btn-compare-days').hidden = true;
    }
    function stopPolling() {
        clearTimeout(pollTimer); pollTimer = null;
        controller?.abort(); controller = null;
    }
    function clearTask() { writeStorage(session,'sp-tracker:task',null); }
    function finish() { stopPolling(); clearTask(); busy(false); }
    function reveal() { results.firstElementChild?.scrollIntoView({block:'nearest', behavior:'auto'}); }
    function fail(message, run=currentRun, token=null) {
        if (token !== null && !isCurrent(token)) return;
        completed = null;
        results.innerHTML = `<section class="card error"><h2>${e(run ? runName(run) : 'Analysis')} could not be completed</h2>${contextHtml(run)}<p>${e(message)}</p></section>`;
        finish(); $('btn-compare-days').hidden = true;
        progress.textContent = 'Request failed. Check the message and run it again.';
        reveal();
    }
    function begin(run, resuming=false) {
        stopPolling(); currentRun = run; completed = null;
        controller = new AbortController();
        const token = ++generation;
        busy(true);
        results.innerHTML = `<section class="card analysis-loading"><h2>${resuming ? 'Resuming' : 'Running'} ${e(runName(run))}</h2>${contextHtml(run)}<p>Gathering evidence for this request…</p></section>`;
        progress.textContent = resuming ? 'Resuming the previous task…' : 'Submitting request…';
        reveal();
        return token;
    }
    function comparisonMatches() {
        if (active || !completed || $('species-controls').hidden) return false;
        if (!$('target-lat').value.trim() || !$('target-lng').value.trim()) return false;
        const {run, result} = completed, p = run.payload;
        if (run.path !== '/api/analysis/run' || p.method !== 'glm' || p.operation !== 'single_day' ||
            result.type !== 'environmental_outlook' || unavailable(result, run)) return false;
        try {
            const input = analysisPayload('single_day');
            return ['taxon_id','method','environment','target_lat','target_lng','target_date','limit','radius_km']
                .every(key=>p[key] === input[key]) &&
                [Number(p.target_lat.toFixed(5)), p.target_lat].includes(Number($('target-lat').value)) &&
                [Number(p.target_lng.toFixed(5)), p.target_lng].includes(Number($('target-lng').value));
        } catch { return false; }
    }
    function inputsChanged() { $('btn-compare-days').hidden = !comparisonMatches(); }
    function workflow(name) {
        context.tools.cancel();
        $('species-controls').hidden = name !== 'species'; $('discovery-controls').hidden = name !== 'discovery';
        $('workflow-species').setAttribute('aria-pressed',String(name==='species'));
        $('workflow-discovery').setAttribute('aria-pressed',String(name==='discovery'));
        inputsChanged();
    }
    $('workflow-species').addEventListener('click',()=>workflow('species'));
    $('workflow-discovery').addEventListener('click',()=>workflow('discovery'));
    $('analysis-limit').addEventListener('input',()=> $('limit-value').textContent=$('analysis-limit').value);
    for (const id of ['analysis-method','analysis-limit','prediction-date','target-lat','target-lng']) {
        $(id).addEventListener('input', inputsChanged);
        $(id).addEventListener('change', inputsChanged);
    }
    function display(result, run) {
        results.innerHTML = resultHtml(result, run);
        completed = {run, result};
        for (const button of results.querySelectorAll('.analyze-animal')) button.addEventListener('click',()=>{
            const animal = result.species.find(row=>String(row.taxon_id)===button.dataset.taxon);
            context.choose({id:animal.taxon_id,name:animal.name,common_name:animal.common_name});
            const point = result.analysis_location;
            context.tools.setTarget(point.lat,point.lng);
            context.map.fitBounds(context.tools.areaLayer.getBounds());
            $('prediction-date').value = result.target_date;
            workflow('species'); $('analysis-species').focus();
            progress.textContent = 'Animal selected. Detailed analysis uses a study circle around a point inside your drawn area. Choose Terrestrial or Marine before running.';
        });
        reveal();
    }
    async function poll(taskId, token, run) {
        if (!isCurrent(token)) return;
        try {
            const response = await fetch(`/api/analysis/status/${encodeURIComponent(taskId)}`, {signal:controller.signal});
            if (!isCurrent(token)) return;
            const data = await response.json();
            if (!isCurrent(token)) return;
            if (!response.ok) throw Error(typeof data.detail==='string' ? data.detail : 'Task unavailable. Run it again.');
            progress.textContent = `${runName(run)}: ${data.progress}`;
            if (data.status === 'complete') {
                const response = await fetch(`/api/analysis/results/${encodeURIComponent(taskId)}`, {signal:controller.signal});
                if (!isCurrent(token)) return;
                const result = await response.json();
                if (!isCurrent(token)) return;
                if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'Results unavailable.');
                display(result, run); finish(); inputsChanged();
                progress.textContent = `${runName(run)} ${unavailable(result, run) ? 'unavailable; supporting evidence is shown.' : 'ready.'}`;
            } else if (data.status === 'failed' || data.status === 'expired') {
                fail(data.error || 'Task expired. Run it again.', run, token);
            } else if (data.status === 'queued' || data.status === 'running') {
                pollTimer = setTimeout(()=>poll(taskId,token,run),2000);
            } else throw Error('The server returned an unknown task state. Run it again.');
        } catch (error) {
            if (isCurrent(token)) fail(error.message, run, token);
        }
    }
    async function start(path,payload) {
        if (active) return;
        const run = snapshot(path, payload, context.selection.species);
        const token = begin(run);
        try {
            const headers = {'Content-Type':'application/json', ...(path === '/api/analysis/run' ? context.apiHeaders?.() : {})};
            const response = await fetch(path,{method:'POST',headers,body:JSON.stringify(run.payload),signal:controller.signal});
            if (!isCurrent(token)) return;
            const data = await response.json();
            if (!isCurrent(token)) return;
            if (!response.ok) throw Error(typeof data.detail==='string' ? data.detail : 'Check the selected date, coordinates, and area.');
            if (typeof data.task_id !== 'string' || !data.task_id) throw Error('The server did not return a task ID. Run it again.');
            lastRun = path === '/api/analysis/run' ? run : null;
            writeStorage(session,'sp-tracker:task',{id:data.task_id,...run});
            poll(data.task_id,token,run);
        } catch (error) {
            if (isCurrent(token)) fail(error.message, run, token);
        }
    }
    function analysisPayload(operation) {
        const species = context.selection.species, target = context.tools.target;
        if (!species) throw Error('Choose an animal from the search results before analysis.');
        if (!target) throw Error('Select a study location on the map or enter coordinates.');
        const targetDate = $('prediction-date').value;
        if (!targetDate || !$('prediction-date').checkValidity()) throw Error('Select a valid target date.');
        return {species:species.name,taxon_id:species.id,environment:context.selection.environment,
            operation,method:operation==='compare_days'?'glm':$('analysis-method').value,
            limit:Number($('analysis-limit').value),target_lat:target.lat,target_lng:target.lng,target_date:targetDate,radius_km:5};
    }
    $('btn-run-analysis').addEventListener('click',()=>{
        if (active) return;
        try { start('/api/analysis/run',analysisPayload('single_day')); }
        catch(error) { fail(error.message, null); }
    });
    $('btn-compare-days').addEventListener('click',()=>{
        if (comparisonMatches()) start('/api/analysis/run',{...completed.run.payload,operation:'compare_days',method:'glm'});
    });
    $('btn-discover').addEventListener('click',()=>{
        if (active) return;
        const payload = {polygon:context.tools.polygon,target_date:$('discovery-date').value,animal_group:$('animal-group').value};
        const run = snapshot('/api/discovery/run',payload,null);
        if (!payload.polygon) {fail('Draw and finish an area before finding animals.',run);return;}
        if (!payload.target_date || !$('discovery-date').checkValidity()) {fail('Choose a valid visit date.',run);return;}
        start('/api/discovery/run',payload);
    });
    const saved = readStorage(session,'sp-tracker:task',null);
    if (saved?.id && saved.payload) {
        try {
            const run = snapshot(saved.path,saved.payload,saved.selectedSpecies);
            const p = run.payload;
            if (run.path === '/api/discovery/run') {
                context.tools.setPolygon(p.polygon); workflow('discovery');
                $('discovery-date').value=p.target_date; $('animal-group').value=p.animal_group;
            } else {
                lastRun=run;
                context.choose(run.selectedSpecies?.id === p.taxon_id ? run.selectedSpecies : {id:p.taxon_id,name:p.species});
                context.selection.setEnvironment(p.environment); $('analysis-environment').value=p.environment;
                context.tools.setTarget(p.target_lat,p.target_lng);
                context.map.setView?.([p.target_lat,p.target_lng],8);
                $('prediction-date').value=p.target_date; $('analysis-method').value=p.method;
                $('analysis-limit').value=p.limit; $('limit-value').textContent=p.limit;
            }
            poll(saved.id,begin(run,true),run);
        } catch { fail('The previous task could not be restored. Run it again.'); }
    }
    return {
        isBusy: () => active,
        inputsChanged,
        rerunLast() {
            if (active || !lastRun) return false;
            start(lastRun.path, lastRun.payload);
            return true;
        },
    };
}
