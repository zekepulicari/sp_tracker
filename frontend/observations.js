import {safeUrl} from './state.js';

const REQUEST_TIMEOUT = 12000;
const CACHE_TTL = 3600000;
const GRID_PANE = 'observations-grid';
const contains = (outer, inner) => outer.nelat >= inner.nelat && outer.nelng >= inner.nelng && outer.swlat <= inner.swlat && outer.swlng <= inner.swlng;
const within = (record, bounds) => {
    const [lng, lat] = record.geojson.coordinates;
    return lat >= bounds.swlat && lat <= bounds.nelat && lng >= bounds.swlng && lng <= bounds.nelng;
};

async function fetchJson(url, controller) {
    const timer = setTimeout(() => controller.abort('timeout'), REQUEST_TIMEOUT);
    try {
        const response = await fetch(url, {signal:controller.signal});
        const data = await response.json();
        if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Observation data unavailable. Please retry.');
        return data;
    } catch (error) {
        if (controller.signal.reason === 'timeout') throw Error('Observations took too long to load. Please retry.');
        throw error;
    } finally { clearTimeout(timer); }
}

/** Map-only requests: small records first, photo details only after opening a popup. */
export class ObservationMap {
    constructor(map, {panel, text, spinner, retry}) {
        this.map = map;
        this.ui = {panel, text, spinner, retry};
        // Base-layer autoZIndex must never cover sightings; tools/markers stay above them.
        const gridPane = map.getPane(GRID_PANE) || map.createPane(GRID_PANE);
        gridPane.style.zIndex = '350';
        gridPane.style.pointerEvents = 'none';
        this.markers = L.layerGroup();
        this.cache = [];
        this.photos = new Map();
        this.generation = 0;
        const attribution = map.getContainer().querySelector('.leaflet-control-attribution');
        if (attribution) {
            this.attributionObserver = new ResizeObserver(() => {
                panel.parentElement.style.setProperty('--attribution-height', `${attribution.getBoundingClientRect().height}px`);
            });
            this.attributionObserver.observe(attribution);
        }
        retry.addEventListener('click', () => this.update());
        map.on('autopanstart', () => { this.popupPanning = true; });
        map.on('movestart', () => {
            if (this.popupPanning) return;
            this.cancel();
            if (this.species && map.getZoom() > 6) this.loading();
        });
        map.on('moveend', () => {
            // Popup layout pans are not a new browsing request; rerendering would close the popup.
            if (this.popupPanning) { this.popupPanning = false; return; }
            clearTimeout(this.timer);
            if (!this.species || map.getZoom() <= 6) { this.update(); return; }
            this.loading();
            this.timer = setTimeout(() => this.update(), 200);
        });
    }

    state(message, loading=false, retry=false) {
        this.ui.text.textContent = message;
        this.ui.spinner.hidden = !loading;
        this.ui.retry.hidden = !retry;
        this.ui.panel.dataset.loading = String(loading);
    }

    loading() {
        this.state(this.markers.getLayers().length ? 'Updating observations… Existing points remain visible.' : 'Loading observations…', true);
    }

    cancel() {
        clearTimeout(this.timer);
        this.controller?.abort();
        this.generation++;
    }

    select(species) {
        this.cancel();
        if (this.grid) this.map.removeLayer(this.grid);
        this.grid = null;
        this.markers.clearLayers();
        this.species = species;
        if (species) {
            this.grid = L.tileLayer(`https://api.inaturalist.org/v1/grid/{z}/{x}/{y}.png?taxon_id=${species.id}&color=%23e76f00`,
                {pane:GRID_PANE, opacity:.8, attribution:'© <a href="https://www.inaturalist.org">iNaturalist</a>'});
            this.grid.on('tileerror', () => {
                if (this.map.getZoom() <= 6) this.state('Some sightings tiles are unavailable. Try zooming in for observations.');
            });
        }
        this.update();
    }

    bounds() {
        const bounds = this.map.getBounds();
        return {nelat:Math.min(90,bounds.getNorth()), nelng:Math.min(180,bounds.getEast()),
            swlat:Math.max(-90,bounds.getSouth()), swlng:Math.max(-180,bounds.getWest())};
    }

    cached(bounds) {
        this.cache = this.cache.filter(item => item.expires > Date.now());
        for (const item of this.cache) {
            if (item.taxon !== this.species.id) continue;
            const same = Object.keys(bounds).every(key => bounds[key] === item.bounds[key]);
            if (same) return item.data;
            if (item.data.complete && contains(item.bounds, bounds)) {
                const results = item.data.results.filter(record => within(record, bounds));
                return {...item.data, results, total_results:results.length};
            }
        }
        return null;
    }

    async update() {
        this.cancel();
        if (!this.species) {
            this.map.removeLayer(this.markers);
            this.state('Choose a species to see recorded observations.');
            return;
        }
        if (this.map.getZoom() <= 6) {
            this.map.removeLayer(this.markers);
            if (this.grid && !this.map.hasLayer(this.grid)) this.grid.addTo(this.map);
            this.state('Grid tiles show recorded sightings. Zoom in for a capped sample of observations.');
            return;
        }
        if (!this.markers.getLayers().length && this.grid && !this.map.hasLayer(this.grid)) this.grid.addTo(this.map);
        this.markers.addTo(this.map);
        const bounds = this.bounds();
        const cached = this.cached(bounds);
        if (cached) { this.render(cached); return; }
        this.loading();
        const generation = this.generation;
        const controller = new AbortController();
        this.controller = controller;
        const taxon = this.species.id;
        try {
            const data = await fetchJson(`/api/observations?${new URLSearchParams({taxon_id:taxon, ...bounds})}`, controller);
            if (controller.signal.aborted || generation !== this.generation) return;
            this.cache.unshift({taxon, bounds, data, expires:Date.now()+CACHE_TTL});
            this.cache.length = Math.min(20, this.cache.length);
            this.render(data);
        } catch (error) {
            if (generation !== this.generation || error.name === 'AbortError') return;
            const retained = this.markers.getLayers().length ? ' Existing points are from the previous view.' : ' Grid tiles remain visible.';
            this.state(error.message + retained, false, true);
        }
    }

    render(data) {
        if (this.grid) this.map.removeLayer(this.grid);
        this.markers.clearLayers();
        for (const obs of data.results || []) {
            const coords = obs.geojson?.coordinates;
            if (!coords || !Number.isFinite(coords[0]) || !Number.isFinite(coords[1])) continue;
            const marker = L.circleMarker([coords[1],coords[0]],
                {radius:7, color:'#ffffff', weight:2, fillColor:'#e76f00', fillOpacity:.95});
            marker.bindPopup('Loading observation…').addTo(this.markers);
            marker.on('popupopen', () => marker.setPopupContent(this.popup(obs, marker)));
        }
        const count = this.markers.getLayers().length;
        if (!count && data.total_results === 0) this.state('No recorded observations found in this view.');
        else this.state(`${count} observations shown${data.complete ? '.' : ` from a capped sample of ${data.sample_cap}. These are not complete counts.`}`);
    }

    popup(obs, marker) {
        const container = document.createElement('div');
        container.className = 'popup-content';
        for (const text of [obs.taxon?.name || 'Unresolved animal', `Observed: ${obs.observed_on || 'Date unavailable'}`,
            `Observer: ${obs.user?.login || 'Unknown'}`, `Location: ${obs.place_guess || 'Not supplied'}`]) {
            const p = document.createElement('p'); p.textContent = text; container.append(p);
        }
        const details = document.createElement('div');
        details.setAttribute('role', 'status');
        const retry = document.createElement('button');
        retry.type = 'button'; retry.textContent = 'Retry photo'; retry.hidden = true;
        container.append(details, retry);
        if (Number.isSafeInteger(obs.id)) {
            const link = document.createElement('a'); link.href = `https://www.inaturalist.org/observations/${obs.id}`;
            link.textContent = 'Source observation'; link.target = '_blank'; link.rel = 'noopener noreferrer'; container.append(link);
        }
        let controller, closed = false;
        marker.once('popupclose', () => { closed = true; controller?.abort(); });
        const showPhoto = data => {
            details.replaceChildren();
            const photo = data.photos?.[0];
            if (photo && safeUrl(photo.url)) {
                const img = document.createElement('img'); img.src = safeUrl(photo.url.replace('square','medium'));
                img.alt = 'Observation photograph'; details.append(img);
                img.addEventListener('load', () => marker.getPopup()?.update());
                img.addEventListener('error', () => {
                    img.remove(); const message = document.createElement('p'); message.textContent = 'Photo could not be loaded.';
                    details.prepend(message); retry.hidden = false; marker.getPopup()?.update();
                });
                const credit = document.createElement('p');
                credit.textContent = `${photo.attribution || 'Contributor attribution not supplied'} · License: ${photo.license_code || 'not supplied'}`;
                details.append(credit);
            } else details.textContent = 'No photograph available.';
            marker.getPopup()?.update();
        };
        const load = async () => {
            retry.hidden = true; details.textContent = 'Loading photo details…';
            controller = new AbortController();
            try {
                let cached = this.photos.get(obs.id);
                if (!cached || cached.expires <= Date.now()) {
                    const data = await fetchJson(`/api/observations/${obs.id}`, controller);
                    cached = {data, expires:Date.now()+CACHE_TTL};
                    this.photos.set(obs.id, cached);
                    if (this.photos.size > 100) this.photos.delete(this.photos.keys().next().value);
                }
                if (!closed) showPhoto(cached.data);
            } catch (error) {
                if (closed || error.name === 'AbortError') return;
                details.textContent = error.message; retry.hidden = false; marker.getPopup()?.update();
            }
        };
        retry.addEventListener('click', load);
        // Called by popupopen, never while constructing the markers.
        load();
        return container;
    }
}
