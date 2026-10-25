import {Selection, label, localDate} from './state.js';
import {MapTools} from './tools.js';
import {ObservationMap} from './observations.js?v=2.5';
import {setupAnalysis} from './analysis.js?v=2.8';
import {setupApiSettings} from './settings.js?v=2.2';

const $ = id => document.getElementById(id);
let storage;
try { storage = window.localStorage; } catch { storage = null; }
const selection = new Selection(storage);
let analysis;
const input = $('analysis-species');
input.value = label(selection.species);
$('analysis-environment').value = selection.environment;
$('prediction-date').value = $('discovery-date').value = localDate();

function showPage(page) {
    document.querySelectorAll('.page').forEach(node => node.hidden = node.id !== `page-${page}`);
    document.querySelectorAll('[data-page]').forEach(button => {
        if (button.dataset.page === page) button.setAttribute('aria-current','page');
        else button.removeAttribute('aria-current');
    });
    if (page === 'home') setTimeout(() => map.invalidateSize(), 0);
}
document.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click', () => showPage(button.dataset.page)));
$('nav-brand').addEventListener('click', event => { event.preventDefault(); showPage('home'); });
$('panel-toggle').addEventListener('click', () => {
    const body = $('panel-body'); body.hidden = !body.hidden;
    $('panel-toggle').setAttribute('aria-expanded', String(!body.hidden));
    $('panel-toggle').textContent = body.hidden ? 'Expand' : 'Collapse';
});

const light = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom:19, attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'});
const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {maxZoom:19, attribution:'Tiles © Esri'});
const map = L.map('map', {center:[20,0], zoom:2, layers:[light], worldCopyJump:true});
L.control.layers({'Light map':light, 'Satellite':satellite}).addTo(map);
const status = message => { $('map-status').textContent = message; $('map-status').hidden = !message; };
const observations = new ObservationMap(map, {
    panel:$('observation-status'), text:$('observation-status-text'), spinner:$('observation-spinner'), retry:$('observation-retry')
});
function refreshSpecies() {
    observations.select(selection.species);
    $('species-hint').textContent = selection.species ? `Selected: ${selection.species.name}` : 'Choose a search result before running an analysis.';
}

const tools = new MapTools(map, {
    message:status,
    point:point => {
        $('target-lat').value = point.lat.toFixed(5); $('target-lng').value = point.lng.toFixed(5);
        $('prediction-location-display').textContent = `Study location: ${point.lat.toFixed(4)}, ${point.lng.toFixed(4)}. Radius starts at 5 km.`;
        analysis?.inputsChanged();
    },
    polygon:polygon => {
        $('polygon-status').textContent = polygon ? `Area selected with ${polygon.coordinates[0].length-1} vertices. Submit to validate the boundary and count seasonal records.` : 'No area selected. Draw an area first.';
    },
    modeChanged:() => $('btn-pick-location').setAttribute('aria-pressed','false')
});
$('tool-ruler').addEventListener('click', () => tools.activate('ruler'));
$('tool-area').addEventListener('click', () => tools.activate('area'));
$('clear-area').addEventListener('click', () => tools.clearPolygon());
$('btn-pick-location').addEventListener('click', () => {
    if (tools.mode === 'point') tools.cancel();
    else { tools.activate('point'); $('btn-pick-location').setAttribute('aria-pressed','true'); }
});
$('btn-use-coordinates').addEventListener('click', () => {
    if (!$('target-lat').value || !$('target-lng').value) { status('Enter both latitude and longitude.'); return; }
    try { tools.cancel(); tools.setTarget(Number($('target-lat').value), Number($('target-lng').value)); map.setView([tools.target.lat,tools.target.lng],8); }
    catch (error) { status(error.message); }
});
$('analysis-environment').addEventListener('change', event => {
    selection.setEnvironment(event.target.value);
    analysis?.inputsChanged();
});

let searchTimer, searchController, options = [], active = -1;
const list = $('species-autocomplete-list');
function hideOptions() { list.hidden = true; input.setAttribute('aria-expanded','false'); input.removeAttribute('aria-activedescendant'); active = -1; }
function choose(species) {
    selection.select({id:species.id, name:species.name, common_name:species.preferred_common_name || species.common_name || ''});
    input.value = label(selection.species); hideOptions(); refreshSpecies();
    analysis?.inputsChanged();
}
function highlight(index) {
    active = index;
    [...list.children].forEach((li,i) => li.setAttribute('aria-selected',String(i===active)));
    if (active >= 0) { input.setAttribute('aria-activedescendant',`species-option-${active}`); list.children[active]?.scrollIntoView({block:'nearest'}); }
}
input.addEventListener('input', () => {
    selection.invalidate(); refreshSpecies(); analysis?.inputsChanged(); hideOptions(); clearTimeout(searchTimer); searchController?.abort();
    const query = input.value.trim();
    if (query.length < 3) return;
    searchTimer = setTimeout(async () => {
        const controller = new AbortController(); searchController = controller;
        try {
            const response = await fetch(`/api/species/search?q=${encodeURIComponent(query)}`, {signal:controller.signal});
            const data = await response.json();
            if (controller.signal.aborted || input.value.trim() !== query) return;
            if (!response.ok) throw Error('Species search unavailable. Please retry.');
            options = data.results || []; list.replaceChildren();
            options.forEach((species,i) => {
                const li = document.createElement('li'); li.id = `species-option-${i}`; li.role = 'option'; li.setAttribute('aria-selected','false');
                li.textContent = species.name;
                const common = document.createElement('small'); common.textContent = species.preferred_common_name || ''; li.append(common);
                li.addEventListener('click', () => choose(species)); list.append(li);
            });
            list.hidden = options.length === 0; input.setAttribute('aria-expanded',String(options.length>0));
            if (!options.length) $('species-hint').textContent = 'No matching animal species. Try another name.';
        } catch (error) { if (error.name !== 'AbortError') $('species-hint').textContent = error.message; }
    },300);
});
input.addEventListener('keydown', event => {
    if (list.hidden) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault(); highlight((active + (event.key==='ArrowDown'?1:-1) + options.length) % options.length);
    } else if (event.key === 'Enter' && active >= 0) { event.preventDefault(); choose(options[active]); }
    else if (event.key === 'Escape') hideOptions();
});
document.addEventListener('click', event => { if (!list.contains(event.target) && event.target !== input) hideOptions(); });
const credentials = setupApiSettings({
    rerun: () => analysis.rerunLast(),
    isBusy: () => analysis.isBusy(),
    explore: () => showPage('home'),
});
analysis = setupAnalysis({selection, tools, choose, map, apiHeaders:credentials.headers});
refreshSpecies();
