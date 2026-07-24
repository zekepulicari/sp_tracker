document.addEventListener('DOMContentLoaded', async () => {

    // =========================================================
    // Tab Navigation
    // =========================================================
    const tabs = document.querySelectorAll('.nav-tab');
    const pages = document.querySelectorAll('.tab-page');
    const brand = document.getElementById('nav-brand');
    let mapInitialized = false;
    window.currentTaxonId = 41521; // Default to Orcinus orca

    /**
     * Switch to a named view.
     *  - 'home' is the map (no tab highlighted).
     *  - 'purpose', 'resources', 'whoami' highlight the matching tab.
     */
    function switchTab(tabName) {
        // Update active tab — clear all, then set the matching one
        tabs.forEach(t => t.classList.remove('active'));
        if (tabName !== 'home') {
            const activeTab = document.querySelector(`.nav-tab[data-tab="${tabName}"]`);
            if (activeTab) activeTab.classList.add('active');
        }

        // Show / hide pages
        pages.forEach(page => {
            const pageId = page.id.replace('page-', '');
            if (pageId === tabName) {
                page.style.display = (pageId === 'home') ? 'flex' : 'flex';
                page.classList.add('tab-enter');
                page.addEventListener('animationend', () => {
                    page.classList.remove('tab-enter');
                }, { once: true });
            } else {
                page.style.display = 'none';
                page.classList.remove('tab-enter');
            }
        });

        // Initialize the map only when the home view is first shown
        if (tabName === 'home' && !mapInitialized) {
            initMap();
            mapInitialized = true;
        }

        // Leaflet needs invalidateSize when its container re-appears
        if (tabName === 'home' && mapInitialized && window._spMap) {
            setTimeout(() => window._spMap.invalidateSize(), 50);
        }
    }

    // Tab button clicks
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            switchTab(tab.dataset.tab);
        });
    });

    // Brand logo click → go back to map
    brand.addEventListener('click', (e) => {
        e.preventDefault();
        switchTab('home');
    });

    // =========================================================
    // Map Initialization (deferred until home view is active)
    // =========================================================
    function initMap() {
        // Base maps
        const lightMap = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
            subdomains: 'abcd',
            maxZoom: 20
        });

        const satelliteMap = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
            attribution: 'Tiles &copy; Esri &mdash; Source: Esri',
            maxZoom: 20
        });

        // Initialize map centered roughly on the equator
        const map = L.map('map', {
            center: [20, 0],
            zoom: 2,
            layers: [lightMap]
        });

        // Expose map globally so we can call invalidateSize on tab switch
        window._spMap = map;

        // Add layer control
        const baseMaps = {
            "Light Map": lightMap,
            "Satellite": satelliteMap
        };
        L.control.layers(baseMaps).addTo(map);

        // Fetch config from backend
        let config = { DEFAULT_ZOOM_THRESHOLD: 6 };
        (async () => {
            try {
                const response = await fetch('/api/config');
                if (response.ok) {
                    config = await response.json();
                }
            } catch (e) {
                console.warn("Could not fetch config, using defaults", e);
            }
        })();

        window.mapInstance = map;

        // Add iNaturalist Grid layer
        let gridLayer = L.tileLayer(`https://api.inaturalist.org/v1/grid/{z}/{x}/{y}.png?taxon_id=${window.currentTaxonId}&color=%23dc2f02`, {
            attribution: '&copy; <a href="https://www.inaturalist.org">iNaturalist</a>',
            opacity: 0.8,
            zIndex: 10
        });

        window.updateGridLayer = function(newTaxonId) {
            if (map.hasLayer(gridLayer)) {
                map.removeLayer(gridLayer);
            }
            gridLayer = L.tileLayer(`https://api.inaturalist.org/v1/grid/{z}/{x}/{y}.png?taxon_id=${newTaxonId}&color=%23dc2f02`, {
                attribution: '&copy; <a href="https://www.inaturalist.org">iNaturalist</a>',
                opacity: 0.8,
                zIndex: 10
            });
            if (map.getZoom() <= config.DEFAULT_ZOOM_THRESHOLD) {
                gridLayer.addTo(map);
            }
        };

        // Layer Group for individual markers
        const markersLayer = L.layerGroup();
        // Expose for access by tools.js (point-in-polygon on visible observations)
        window._spMarkersLayer = markersLayer;

        let activeObsController = null;

        async function updateMapState() {
            const currentZoom = map.getZoom();

            if (currentZoom > config.DEFAULT_ZOOM_THRESHOLD) {
                // High zoom: Show individual markers, hide grid
                if (map.hasLayer(gridLayer)) {
                    map.removeLayer(gridLayer);
                }
                if (!map.hasLayer(markersLayer)) {
                    markersLayer.addTo(map);
                }
                await fetchObservations();
            } else {
                // Low zoom: Show grid layer, hide markers
                if (!map.hasLayer(gridLayer)) {
                    gridLayer.addTo(map);
                }
                if (map.hasLayer(markersLayer)) {
                    map.removeLayer(markersLayer);
                }
            }
        }

        async function fetchObservations() {
            // Cancel any in-flight request before starting a new one
            if (activeObsController) {
                activeObsController.abort();
            }
            activeObsController = new AbortController();
            const signal = activeObsController.signal;

            try {
                const bounds = map.getBounds();
                const nelat = bounds.getNorthEast().lat;
                const nelng = bounds.getNorthEast().lng;
                const swlat = bounds.getSouthWest().lat;
                const swlng = bounds.getSouthWest().lng;

                // Call iNaturalist directly — skips the backend proxy hop for speed
                const url = `https://api.inaturalist.org/v1/observations` +
                    `?taxon_id=${window.currentTaxonId}&per_page=100&has_geo=true` +
                    `&nelat=${nelat}&nelng=${nelng}&swlat=${swlat}&swlng=${swlng}`;

                const response = await fetch(url, { signal });

                // Don't update layers if this request was superseded
                if (signal.aborted) return;

                if (!response.ok) {
                    console.warn(`iNaturalist fetch failed (${response.status}). Keeping existing markers.`);
                    return;
                }

                const data = await response.json();

                markersLayer.clearLayers();

                if (data.results) {
                    data.results.forEach(obs => {
                        if (!obs.geojson || !obs.geojson.coordinates) return;

                        const lat = obs.geojson.coordinates[1];
                        const lng = obs.geojson.coordinates[0];

                        const photoHtml = obs.photos && obs.photos.length > 0
                            ? `<img src="${obs.photos[0].url.replace('square', 'medium')}" alt="Observation photo">`
                            : '<p><em>No photo available</em></p>';

                        const date = obs.observed_on_details ? obs.observed_on_details.date : 'Unknown date';
                        const observer = obs.user ? obs.user.login : 'Unknown observer';
                        const location = obs.place_guess || 'Unknown location';

                        const popupContent = `
                            <div class="popup-content">
                                ${photoHtml}
                                <p><strong>Date:</strong> ${date}</p>
                                <p><strong>Observer:</strong> ${observer}</p>
                                <p><strong>Location:</strong> ${location}</p>
                            </div>
                        `;

                        const marker = L.circleMarker([lat, lng], {
                            radius: 6,
                            fillColor: "#588157",
                            color: "#344E41",
                            weight: 1,
                            opacity: 1,
                            fillOpacity: 0.8
                        });

                        marker.bindPopup(popupContent);
                        markersLayer.addLayer(marker);
                    });
                }
            } catch (e) {
                if (e.name === 'AbortError') return; // Stale request cancelled — expected
                console.error("Failed to fetch observations", e);
            }
        }

        // Attach event listeners
        map.on('zoomend', updateMapState);
        map.on('moveend', () => {
            if (map.getZoom() > config.DEFAULT_ZOOM_THRESHOLD) {
                fetchObservations();
            }
        });

        // Initial state setup
        updateMapState();
    }

    // =========================================================
    // Autocomplete Logic
    // =========================================================
    const speciesInput = document.getElementById('analysis-species');
    const autocompleteList = document.getElementById('species-autocomplete-list');
    let debounceTimer;

    if (speciesInput && autocompleteList) {
        speciesInput.addEventListener('input', (e) => {
            const query = e.target.value.trim();
            clearTimeout(debounceTimer);
            
            if (query.length < 3) {
                autocompleteList.classList.remove('active');
                return;
            }

            debounceTimer = setTimeout(async () => {
                try {
                    const res = await fetch(`/api/species/search?q=${encodeURIComponent(query)}`);
                    const data = await res.json();
                    
                    if (data.results && data.results.length > 0) {
                        renderAutocomplete(data.results);
                    } else {
                        autocompleteList.classList.remove('active');
                    }
                } catch (err) {
                    console.error("Autocomplete error:", err);
                }
            }, 300); // 300ms debounce
        });

        // Hide dropdown on click outside
        document.addEventListener('click', (e) => {
            if (!speciesInput.contains(e.target) && !autocompleteList.contains(e.target)) {
                autocompleteList.classList.remove('active');
            }
        });
    }

    function renderAutocomplete(results) {
        autocompleteList.innerHTML = '';
        results.slice(0, 8).forEach(item => {
            const li = document.createElement('li');
            li.className = 'autocomplete-item';
            
            const imgUrl = item.default_photo && item.default_photo.square_url 
                ? item.default_photo.square_url 
                : '/resources/images/default_species.png'; // fallback if no photo
                
            li.innerHTML = `
                <img src="${imgUrl}" class="autocomplete-img" onerror="this.style.display='none'">
                <div class="autocomplete-info">
                    <span class="autocomplete-name">${item.name}</span>
                    <span class="autocomplete-common">${item.preferred_common_name || ''}</span>
                </div>
            `;
            
            li.addEventListener('click', () => {
                const displayName = item.preferred_common_name 
                    ? `${item.name} (${item.preferred_common_name})` 
                    : item.name;
                speciesInput.value = displayName;
                window.currentTaxonId = item.id;
                autocompleteList.classList.remove('active');
                
                // Immediately update map if initialized
                if (window.updateGridLayer) {
                    window.updateGridLayer(item.id);
                }
                if (window.mapInstance) {
                    window.mapInstance.fire('moveend');
                }
            });
            
            autocompleteList.appendChild(li);
        });
        autocompleteList.classList.add('active');
    }

    // =========================================================
    // Boot: start on the home (map) view
    // =========================================================
    switchTab('home');
});
