import {escapeHtml as e, safeUrl, readStorage, writeStorage} from './state.js';
const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const labels = {air_temp:'Air temperature',wind_speed:'Wind speed',precipitation:'Rainfall',sst:'Sea surface temperature',wave_height:'Wave height',ocean_current_velocity:'Ocean current',season_sin:'Season (sine)',season_cos:'Season (cosine)'};
const units = {air_temp:'°C',wind_speed:'km/h',precipitation:'mm/day',sst:'°C',wave_height:'m',ocean_current_velocity:'km/h'};
function conditionRows(conditions) {
    return Object.entries(conditions || {}).map(([key,value]) => `<tr><th scope="row">${e(labels[key] || key)}</th><td>${value === null || !Number.isFinite(value) ? 'Unavailable' : `${e(value.toFixed(2))} ${e(units[key] || '')}`}</td></tr>`).join('');
}
function profileHtml(profile) {
    const max = Math.max(1,...profile.map(row=>row.count));
    return `<section class="card"><h2>Historical sightings by month</h2><p class="help">Counts describe the retrieved sample, not successful visits.</p><table><caption>Recorded sightings and years represented</caption><thead><tr><th>Month</th><th>Sightings</th><th>Years</th></tr></thead><tbody>${profile.map(row=>`<tr><th scope="row">${e(months[row.month-1])}</th><td>${e(row.count)}<span class="bar" aria-hidden="true" style="width:${Math.max(1,row.count/max*100)}%"></span></td><td>${e(row.years.join(', ') || '—')}</td></tr>`).join('')}</tbody></table></section>`;
}
export function resultHtml(result) {
    let html = `<section class="card"><h2>${e(result.title || result.species?.name || 'Analysis evidence')}</h2><p>${e(result.summary)}</p>${(result.warnings || []).map(w=>`<p class="notice">${e(w)}</p>`).join('')}</section>`;
    if (result.type === 'seasonal_discovery') {
        html += `<section class="card"><h3>Area and evidence</h3><p>${e(result.area_km2)} km² · ${e(result.records_inside)} eligible sightings inside the boundary</p><p class="help">${e(result.evidence_window.start)} to ${e(result.evidence_window.end)} · ${e(months[result.month-1])} in each year · complete query</p></section>`;
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
    if (result.profile) html += profileHtml(result.profile);
    html += `<details class="card"><summary>Technical evidence, validation, and relative scores</summary><p class="help">Classifier scores distinguish sightings from background samples. They are not encounter probabilities.</p><pre>${e(JSON.stringify({model:result.model,features:result.features,evidence:result.evidence,days:result.days?.map(d=>({date:d.date,relative_score:d.relative_score,available:d.available}))},null,2))}</pre></details>`;
    return html;
}

export function setupAnalysis(context) {
    const $ = id=>document.getElementById(id);
    const results = $('analysis-results'), progress = $('analysis-progress');
    let session;
    try { session = window.sessionStorage; } catch { session = null; }
    let active = false, generation = 0, lastPayload = null;
    const buttons = ['btn-run-analysis','btn-discover','btn-compare-days'];
    function busy(value) {
        active = value; buttons.forEach(id=>$(id).disabled=value);
        results.setAttribute('aria-busy',String(value));
    }
    function fail(message) {
        results.innerHTML = `<section class="card error"><h2>Unable to complete this request</h2><p>${e(message)}</p></section>`;
        progress.textContent = ''; busy(false);
    }
    function workflow(name) {
        context.tools.cancel();
        $('species-controls').hidden = name !== 'species'; $('discovery-controls').hidden = name !== 'discovery';
        $('workflow-species').setAttribute('aria-pressed',String(name==='species'));
        $('workflow-discovery').setAttribute('aria-pressed',String(name==='discovery'));
    }
    $('workflow-species').addEventListener('click',()=>workflow('species'));
    $('workflow-discovery').addEventListener('click',()=>workflow('discovery'));
    $('analysis-limit').addEventListener('input',()=> $('limit-value').textContent=$('analysis-limit').value);
    function display(result) {
        results.innerHTML = resultHtml(result);
        $('btn-compare-days').hidden = !(result.model && lastPayload?.method === 'glm' &&
            lastPayload.taxon_id === context.selection.species?.id &&
            lastPayload.environment === context.selection.environment &&
            lastPayload.target_lat === context.tools.target?.lat && lastPayload.target_lng === context.tools.target?.lng &&
            result.type !== 'day_comparison');
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
    }
    function clearTask() { writeStorage(session,'sp-tracker:task',null); }
    async function poll(taskId, token) {
        if (token !== generation) return;
        try {
            const response = await fetch(`/api/analysis/status/${encodeURIComponent(taskId)}`);
            const data = await response.json();
            if (!response.ok) throw Error(typeof data.detail==='string' ? data.detail : 'Task unavailable. Run it again.');
            progress.textContent = data.progress;
            if (data.status === 'complete') {
                const response = await fetch(`/api/analysis/results/${encodeURIComponent(taskId)}`);
                const result = await response.json();
                if (!response.ok) throw Error(result.detail || 'Results unavailable.');
                if (token !== generation) return;
                display(result); clearTask(); busy(false); progress.textContent = 'Evidence ready.';
            } else if (data.status === 'failed' || data.status === 'expired') {
                clearTask(); fail(data.error || 'Task expired. Run it again.');
            } else setTimeout(()=>poll(taskId,token),2000);
        } catch (error) { clearTask(); fail(error.message); }
    }
    async function start(path,payload) {
        if (active) return;
        busy(true); progress.textContent = 'Submitting request…';
        const token = ++generation;
        try {
            const headers = {'Content-Type':'application/json', ...(path === '/api/analysis/run' ? context.apiHeaders?.() : {})};
            const response = await fetch(path,{method:'POST',headers,body:JSON.stringify(payload)});
            const data = await response.json();
            if (!response.ok) throw Error(typeof data.detail==='string' ? data.detail : 'Check the selected date, coordinates, and area.');
            lastPayload = path.includes('discovery') ? null : payload;
            writeStorage(session,'sp-tracker:task',{id:data.task_id,path,payload,selectedSpecies:context.selection.species});
            poll(data.task_id,token);
        } catch (error) { fail(error.message); }
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
    $('btn-run-analysis').addEventListener('click',()=>{try {start('/api/analysis/run',analysisPayload('single_day'));} catch(error){fail(error.message);}});
    $('btn-compare-days').addEventListener('click',()=>{
        if (!lastPayload) return;
        start('/api/analysis/run',{...lastPayload,operation:'compare_days',method:'glm'});
    });
    $('btn-discover').addEventListener('click',()=>{
        if (!context.tools.polygon) {fail('Draw and finish an area before finding animals.');return;}
        if (!$('discovery-date').value || !$('discovery-date').checkValidity()) {fail('Choose a valid visit date.');return;}
        start('/api/discovery/run',{polygon:context.tools.polygon,target_date:$('discovery-date').value,animal_group:$('animal-group').value});
    });
    const saved = readStorage(session,'sp-tracker:task',null);
    if (saved?.id && saved.payload) {
        try {
            if (saved.path === '/api/discovery/run') {
                context.tools.setPolygon(saved.payload.polygon); workflow('discovery');
                $('discovery-date').value=saved.payload.target_date; $('animal-group').value=saved.payload.animal_group;
            } else {
                lastPayload=saved.payload;
                context.choose(saved.selectedSpecies?.id === saved.payload.taxon_id ? saved.selectedSpecies : {id:saved.payload.taxon_id,name:saved.payload.species});
                context.selection.setEnvironment(saved.payload.environment); $('analysis-environment').value=saved.payload.environment;
                context.tools.setTarget(saved.payload.target_lat,saved.payload.target_lng);
                context.map.setView?.([saved.payload.target_lat,saved.payload.target_lng],8);
                $('prediction-date').value=saved.payload.target_date; $('analysis-method').value=saved.payload.method;
                $('analysis-limit').value=saved.payload.limit; $('limit-value').textContent=saved.payload.limit;
            }
            busy(true); progress.textContent='Resuming the previous task…'; poll(saved.id,++generation);
        } catch { clearTask(); fail('The previous task could not be restored. Run it again.'); }
    }
    return {
        isBusy: () => active,
        rerunLast() {
            if (active || !lastPayload) return false;
            start('/api/analysis/run', {...lastPayload});
            return true;
        },
    };
}
