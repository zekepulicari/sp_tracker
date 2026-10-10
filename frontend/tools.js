/**
 * tools.js — Measurement Tools for Species Tracker
 *
 * Provides two map tools via a shared ToolManager:
 *   - RulerTool  : Two-click geodesic distance measurement (km)
 *   - AreaTool   : Multi-click polygon area measurement (km²) with
 *                  iNaturalist observation count inside the selection
 *
 * Dependencies (loaded before this file):
 *   - Leaflet  (window.L)
 *   - Turf.js  (window.turf)
 *   - app.js   exposes window._spMap, window._spMarkersLayer
 */

// Wait for app.js to finish bootstrapping the map
document.addEventListener('DOMContentLoaded', () => {

    // =========================================================
    // Shared style constants
    // =========================================================
    const RULER_COLOR   = '#e63946'; // Red — visible on both basemaps
    const POLYGON_COLOR = '#588157'; // Green — matches design palette
    const VERTEX_RADIUS = 5;

    // =========================================================
    // Utilities
    // =========================================================

    /**
     * Format a distance in km, choosing m or km depending on magnitude.
     * @param {number} km
     * @returns {string}
     */
    function formatDistance(km) {
        if (km < 1) return `${(km * 1000).toFixed(0)} m`;
        return `${km.toFixed(2)} km`;
    }

    /**
     * Format an area in km².
     * @param {number} sqMeters - Area in square metres from turf.area()
     * @returns {string}
     */
    function formatArea(sqMeters) {
        const sqKm = sqMeters / 1_000_000;
        if (sqKm < 0.01) return `${sqMeters.toFixed(0)} m²`;
        return `${sqKm.toFixed(4)} km²`;
    }

    /**
     * Show or hide the #measurement-results panel.
     * @param {boolean} visible
     */
    function setResultsVisible(visible) {
        const el = document.getElementById('measurement-results');
        if (!el) return;
        el.style.display = visible ? 'flex' : 'none';
    }

    /**
     * Replace the content of #measurement-results with provided HTML.
     * @param {string} html
     */
    function renderResults(html) {
        const el = document.getElementById('measurement-results');
        if (!el) return;
        el.innerHTML = html;
        el.style.display = 'flex';
        // Re-trigger animation
        el.classList.remove('results-animate');
        void el.offsetWidth; // reflow
        el.classList.add('results-animate');
    }

    // =========================================================
    // ToolManager — coordinates which tool is active
    // =========================================================
    class ToolManager {
        /**
         * @param {L.Map} map - Leaflet map instance
         */
        constructor(map) {
            this.map = map;
            this.activeTool = null;

            this._rulerTool = new RulerTool(map, this);
            this._areaTool  = new AreaTool(map, this);

            this._bindButtons();
            this._bindGlobalKeys();
        }

        _bindButtons() {
            document.getElementById('tool-ruler')
                ?.addEventListener('click', () => this.toggle('ruler'));
            document.getElementById('tool-area')
                ?.addEventListener('click', () => this.toggle('area'));
        }

        _bindGlobalKeys() {
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') this.deactivate();
            });
        }

        /**
         * Toggle a tool on/off. Activating one deactivates the other.
         * @param {'ruler'|'area'} toolName
         */
        toggle(toolName) {
            if (this.activeTool === toolName) {
                this.deactivate();
            } else {
                this.activate(toolName);
            }
        }

        /**
         * Activate a named tool.
         * @param {'ruler'|'area'} toolName
         */
        activate(toolName) {
            // Deactivate any running tool first
            if (this.activeTool) this._getTool(this.activeTool).deactivate();

            this.activeTool = toolName;
            this._getTool(toolName).activate();

            // Button highlight
            document.querySelectorAll('.map-tool-btn').forEach(b => b.classList.remove('tool-active'));
            const btn = document.getElementById(`tool-${toolName}`);
            if (btn) btn.classList.add('tool-active');

            // Crosshair cursor on map container
            document.getElementById('map')?.classList.add('tool-cursor-active');
        }

        /** Deactivate all tools. */
        deactivate() {
            if (this.activeTool) {
                this._getTool(this.activeTool).deactivate();
                this.activeTool = null;
            }
            document.querySelectorAll('.map-tool-btn').forEach(b => b.classList.remove('tool-active'));
            document.getElementById('map')?.classList.remove('tool-cursor-active');
        }

        /**
         * @param {'ruler'|'area'} name
         * @returns {RulerTool|AreaTool}
         */
        _getTool(name) {
            return name === 'ruler' ? this._rulerTool : this._areaTool;
        }
    }

    // =========================================================
    // RulerTool — two-click geodesic distance measurement
    // =========================================================
    class RulerTool {
        /**
         * @param {L.Map} map
         * @param {ToolManager} manager
         */
        constructor(map, manager) {
            this.map     = map;
            this.manager = manager;
            this._layers = []; // Leaflet layers to clean up
            this._clicks = 0;
            this._startLatLng = null;
            this._onMapClick  = this._onMapClick.bind(this);
        }

        activate() {
            this._reset();
            this.map.on('click', this._onMapClick);
            renderResults(`
                <div class="drawing-hint">
                    <img src="/resources/images/ruler_icon.png" alt="ruler" width="16" height="16" style="vertical-align:middle;"> Click two points on the map to measure distance.<br>
                    <small>Press <kbd>Esc</kbd> to cancel.</small>
                </div>
            `);
        }

        deactivate() {
            this.map.off('click', this._onMapClick);
            this._clearLayers();
            setResultsVisible(false);
        }

        _reset() {
            this._clearLayers();
            this._clicks = 0;
            this._startLatLng = null;
        }

        _clearLayers() {
            this._layers.forEach(l => this.map.removeLayer(l));
            this._layers = [];
        }

        /**
         * Handle map clicks for ruler (first = start, second = end + measure).
         * @param {L.LeafletMouseEvent} e
         */
        _onMapClick(e) {
            if (this._clicks === 0) {
                this._clearLayers();
            }
            this._clicks++;

            if (this._clicks === 1) {
                // Place start marker
                this._startLatLng = e.latlng;
                const dot = L.circleMarker(e.latlng, {
                    radius: VERTEX_RADIUS + 1,
                    color: RULER_COLOR,
                    fillColor: RULER_COLOR,
                    fillOpacity: 1,
                    weight: 2,
                    interactive: false
                }).addTo(this.map);
                this._layers.push(dot);

                renderResults(`
                    <div class="drawing-hint">
                        <img src="/resources/images/ruler_icon.png" alt="ruler" width="16" height="16" style="vertical-align:middle;"> Now click the <strong>second point</strong> to measure.<br>
                        <small>Press <kbd>Esc</kbd> to cancel.</small>
                    </div>
                `);

            } else if (this._clicks === 2) {
                // Place end marker + line + compute distance
                const endLatLng = e.latlng;

                const endDot = L.circleMarker(endLatLng, {
                    radius: VERTEX_RADIUS + 1,
                    color: RULER_COLOR,
                    fillColor: RULER_COLOR,
                    fillOpacity: 1,
                    weight: 2,
                    interactive: false
                }).addTo(this.map);
                this._layers.push(endDot);

                const line = L.polyline(
                    [this._startLatLng, endLatLng],
                    { color: RULER_COLOR, weight: 2.5, dashArray: '8 6', interactive: false }
                ).addTo(this.map);
                this._layers.push(line);

                // Compute geodesic distance using Turf.js
                const from = turf.point([this._startLatLng.lng, this._startLatLng.lat]);
                const to   = turf.point([endLatLng.lng, endLatLng.lat]);
                const distKm = turf.distance(from, to, { units: 'kilometers' });

                // Label at midpoint
                const midLat = (this._startLatLng.lat + endLatLng.lat) / 2;
                const midLng = (this._startLatLng.lng + endLatLng.lng) / 2;
                const label = L.marker([midLat, midLng], {
                    icon: L.divIcon({
                        className: '',
                        html: `<div style="
                            color: #000;
                            font: 600 14px/1.4 Inter, sans-serif;
                            white-space: nowrap;
                            text-shadow: 1px 1px 2px #fff, -1px -1px 2px #fff, 1px -1px 2px #fff, -1px 1px 2px #fff;
                            transform: translate(-50%, -50%);
                        ">${formatDistance(distKm)}</div>`,
                        iconAnchor: [0, 0]
                    }),
                    interactive: false
                }).addTo(this.map);
                this._layers.push(label);

                // Render results panel
                renderResults(`
                    <div class="measurement-card">
                        <div class="measurement-card-header">
                            <span class="measurement-card-icon"><img src="/resources/images/ruler_icon.png" alt="ruler" width="20" height="20"></span>
                            <span class="measurement-card-title">Distance</span>
                        </div>
                        <div class="measurement-value">${formatDistance(distKm)}</div>
                        <div class="measurement-sub">Geodesic distance (WGS-84)</div>
                    </div>
                    <div class="drawing-hint">
                        Click <img src="/resources/images/ruler_icon.png" alt="ruler" width="14" height="14" style="vertical-align:middle;"> again or press <kbd>Esc</kbd> to clear.<br>
                        Click the ruler button to start a new measurement.
                    </div>
                `);

                // Reset click counter so user can start fresh by clicking again
                this._clicks = 0;
            }
        }
    }

    // =========================================================
    // AreaTool — multi-click polygon area + species count
    // =========================================================
    class AreaTool {
        /**
         * @param {L.Map} map
         * @param {ToolManager} manager
         */
        constructor(map, manager) {
            this.map     = map;
            this.manager = manager;
            this._vertices  = []; // Array of {lat, lng}
            this._layers    = []; // Leaflet layers to clean up
            this._previewPolyline = null;
            this._onMapClick      = this._onMapClick.bind(this);
            this._onKeyDown       = this._onKeyDown.bind(this);
        }

        activate() {
            this._reset();
            this.map.on('click', this._onMapClick);
            document.addEventListener('keydown', this._onKeyDown);
            renderResults(`
                <div class="drawing-hint">
                    <img src="/resources/images/area_selector_icon.png" alt="area" width="16" height="16" style="vertical-align:middle;"> Click on the map to add vertices.<br>
                    Click the <strong>first point</strong> or press <kbd>Enter</kbd> to close.<br>
                    <small>Press <kbd>Esc</kbd> to cancel.</small>
                </div>
            `);
        }

        deactivate() {
            this.map.off('click', this._onMapClick);
            document.removeEventListener('keydown', this._onKeyDown);
            this._clearLayers();
            setResultsVisible(false);
        }

        _reset() {
            this._clearLayers();
            this._vertices = [];
            this._previewPolyline = null;
            this._isClosed = false;
        }

        _clearLayers() {
            this._layers.forEach(l => this.map.removeLayer(l));
            this._layers = [];
            this._previewPolyline = null;
        }

        /**
         * @param {KeyboardEvent} e
         */
        _onKeyDown(e) {
            if (e.key === 'Enter' && this._vertices.length >= 3) {
                this._closePolygon();
            }
            // Esc is handled by ToolManager, but deactivate is called which calls our deactivate()
        }

        /**
         * Handle map clicks for polygon drawing.
         * @param {L.LeafletMouseEvent} e
         */
        _onMapClick(e) {
            if (this._isClosed) {
                this._reset();
            }

            const clickedLatLng = e.latlng;

            // Add vertex
            this._vertices.push({ lat: clickedLatLng.lat, lng: clickedLatLng.lng });

            // Draw vertex dot
            const dot = L.circleMarker(clickedLatLng, {
                radius: VERTEX_RADIUS,
                color: POLYGON_COLOR,
                fillColor: POLYGON_COLOR,
                fillOpacity: 0.9,
                weight: 2,
                interactive: false
            }).addTo(this.map);
            this._layers.push(dot);

            // Mark the first vertex differently to hint it's clickable
            if (this._vertices.length === 1) {
                const firstHint = L.circleMarker(clickedLatLng, {
                    radius: VERTEX_RADIUS + 6,
                    color: POLYGON_COLOR,
                    fillColor: POLYGON_COLOR,
                    fillOpacity: 0.2,
                    weight: 2,
                    dashArray: '4 3',
                    interactive: true
                }).addTo(this.map);
                
                firstHint.on('click', (ev) => {
                    L.DomEvent.stopPropagation(ev);
                    if (this._vertices.length >= 3) {
                        this._closePolygon();
                    }
                });
                
                this._layers.push(firstHint);
            }

            // Update/draw the preview polyline
            if (this._previewPolyline) {
                this.map.removeLayer(this._previewPolyline);
                this._layers = this._layers.filter(l => l !== this._previewPolyline);
            }
            if (this._vertices.length >= 2) {
                const coords = this._vertices.map(v => [v.lat, v.lng]);
                this._previewPolyline = L.polyline(coords, {
                    color: POLYGON_COLOR,
                    weight: 2,
                    dashArray: '6 4',
                    interactive: false
                }).addTo(this.map);
                this._layers.push(this._previewPolyline);
            }

            // Update hint
            if (this._vertices.length >= 3) {
                renderResults(`
                    <div class="drawing-hint">
                        <img src="/resources/images/area_selector_icon.png" alt="area" width="16" height="16" style="vertical-align:middle;"> <strong>${this._vertices.length}</strong> points placed.<br>
                        Click the <strong>first point</strong> or press <kbd>Enter</kbd> to finish.<br>
                        <small>Press <kbd>Esc</kbd> to cancel.</small>
                    </div>
                `);
            }
        }

        /** Close the polygon, compute area, count species, render results. */
        async _closePolygon() {
            if (this._vertices.length < 3) return;

            this._isClosed = true;

            // Clear preview polyline and vertex dots — replace with solid filled polygon
            this._clearLayers();

            // Build closed ring for Turf.js: [lng, lat] pairs, first = last
            const ring = this._vertices.map(v => [v.lng, v.lat]);
            ring.push(ring[0]); // close ring

            const turfPolygon = turf.polygon([ring]);
            const areaSqMeters = turf.area(turfPolygon);

            window._spActivePolygon = { type: 'Polygon', coordinates: [ring], areaSqMeters };
            window.dispatchEvent(new CustomEvent('sp:polygon-updated', { detail: window._spActivePolygon }));

            // Draw the solid polygon on the map
            const polygon = L.polygon(
                this._vertices.map(v => [v.lat, v.lng]),
                {
                    color: POLYGON_COLOR,
                    weight: 2.5,
                    fillColor: POLYGON_COLOR,
                    fillOpacity: 0.18,
                    interactive: false
                }
            ).addTo(this.map);
            this._layers.push(polygon);

            // --- Count observations inside the polygon ---
            // Phase 1: point-in-polygon on already-loaded markers (fast, client-side)
            const speciesCounts = {}; // { taxon_name: count }
            let clientTotal = 0;

            const markersLayer = window._spMarkersLayer;
            if (markersLayer) {
                markersLayer.eachLayer(layer => {
                    if (!(layer instanceof L.CircleMarker)) return;
                    const { lat, lng } = layer.getLatLng();
                    const pt = turf.point([lng, lat]);
                    if (turf.booleanPointInPolygon(pt, turfPolygon)) {
                        clientTotal++;
                        // Try to get species name from popup content
                        const popupContent = layer.getPopup()?.getContent() || '';
                        const nameMatch = popupContent.match(/Orcinus orca|<em>([^<]+)<\/em>/i);
                        const name = nameMatch ? (nameMatch[1] || 'Orcinus orca') : 'Orcinus orca';
                        speciesCounts[name] = (speciesCounts[name] || 0) + 1;
                    }
                });
            }

            // Phase 2: fetch from backend for the polygon bbox (may include off-screen obs)
            let backendTotal = clientTotal;
            let backendSpecies = { ...speciesCounts };
            try {
                const resp = await fetch('/api/observations/within', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ polygon: { type: 'Polygon', coordinates: [ring] } })
                });
                if (resp.ok) {
                    const data = await resp.json();
                    if (data.results) {
                        // Filter precisely with Turf
                        backendTotal = 0;
                        backendSpecies = {};
                        data.results.forEach(obs => {
                            if (!obs.geojson?.coordinates) return;
                            const [lng, lat] = obs.geojson.coordinates;
                            const pt = turf.point([lng, lat]);
                            if (turf.booleanPointInPolygon(pt, turfPolygon)) {
                                backendTotal++;
                                const name = obs.taxon?.name || obs.species_guess || 'Unknown species';
                                backendSpecies[name] = (backendSpecies[name] || 0) + 1;
                            }
                        });
                    }
                }
            } catch (err) {
                console.warn('Backend within-query failed, using client-side count only.', err);
            }

            // Use backend results if available (more complete)
            const total    = backendTotal > 0 ? backendTotal : clientTotal;
            const species  = Object.keys(backendSpecies).length > 0 ? backendSpecies : speciesCounts;

            // Build species breakdown HTML
            const speciesRows = Object.entries(species)
                .sort(([, a], [, b]) => b - a) // descending by count
                .map(([name, count]) => `
                    <div class="species-row">
                        <span class="species-name">${name}</span>
                        <span class="species-count-badge">${count}</span>
                    </div>
                `).join('');

            renderResults(`
                <div class="measurement-card">
                    <div class="measurement-card-header">
                        <span class="measurement-card-icon"><img src="/resources/images/area_selector_icon.png" alt="area" width="20" height="20"></span>
                        <span class="measurement-card-title">Selected Area</span>
                    </div>
                    <div class="measurement-value">${formatArea(areaSqMeters)}</div>
                    <div class="measurement-sub">Polygon area (WGS-84 / equal-area approx.)</div>
                </div>
                <div class="measurement-card">
                    <div class="measurement-card-header">
                        <span class="measurement-card-icon">🐋</span>
                        <span class="measurement-card-title">Observations Inside</span>
                    </div>
                    <div class="measurement-value">${total}</div>
                    <div class="measurement-sub">iNaturalist sightings within the selection</div>
                    ${speciesRows ? `<div class="species-breakdown">${speciesRows}</div>` : ''}
                </div>
                <div class="drawing-hint">
                    Click <img src="/resources/images/area_selector_icon.png" alt="area" width="14" height="14" style="vertical-align:middle;"> to draw a new area.<br>
                    <small>Press <kbd>Esc</kbd> to clear.</small>
                </div>
            `);

            // Store layers reference so Esc/next activation can clean them
            this._closedLayers = [...this._layers];
        }
    }

    // =========================================================
    // Bootstrap — wait for map to be ready before wiring tools
    // =========================================================
    function tryInit(attempts = 0) {
        if (window._spMap) {
            new ToolManager(window._spMap);
        } else if (attempts < 30) {
            // Map initializes on first tab switch — poll briefly
            setTimeout(() => tryInit(attempts + 1), 200);
        } else {
            console.error('tools.js: window._spMap not available after 6s. Tools not loaded.');
        }
    }

    tryInit();
});
