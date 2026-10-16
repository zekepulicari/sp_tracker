/** Map tools share one interaction mode; completed areas survive cancellation. */
export class MapTools {
    constructor(map, callbacks) {
        this.map = map;
        this.callbacks = callbacks;
        this.mode = null;
        this.vertices = [];
        this.draft = L.layerGroup().addTo(map);
        this.polygon = null;
        this.areaLayer = null;
        this.target = null;
        this.pointMarker = null;
        this.rulerPoints = [];
        this.rulerLayer = null;
        map.on('click', event => this.click(event.latlng));
        document.addEventListener('keydown', event => {
            const editing = ['INPUT','SELECT','TEXTAREA'].includes(event.target.tagName);
            if (event.key === 'Escape') this.cancel();
            if (!editing && event.key === 'Enter' && this.mode === 'area') {
                event.preventDefault(); this.finish();
            }
        });
    }
    activate(mode) {
        this.cancel();
        this.mode = mode;
        this.map.getContainer().style.cursor = 'crosshair';
        this.callbacks.message(mode === 'area' ? 'Add vertices. Click the first point or press Enter to close. Escape cancels drawing.' : mode === 'point' ? 'Click the map to choose a study location. Escape cancels.' : 'Click two points to measure approximate map distance.');
    }
    cancel() {
        this.mode = null;
        this.vertices = [];
        this.rulerPoints = [];
        this.draft.clearLayers();
        this.map.getContainer().style.cursor = '';
        this.callbacks.modeChanged?.();
    }
    click(latlng) {
        if (this.mode === 'point') { this.setTarget(latlng.lat, latlng.lng); this.cancel(); }
        else if (this.mode === 'area') {
            if (this.vertices.length >= 3 && this.map.latLngToContainerPoint(latlng).distanceTo(this.map.latLngToContainerPoint(this.vertices[0])) < 14) {
                this.finish(); return;
            }
            if (this.vertices.length >= 100) { this.callbacks.message('Use at most 100 vertices. Press Enter to finish.'); return; }
            this.vertices.push(latlng);
            this.draft.clearLayers();
            this.vertices.forEach(pt => L.circleMarker(pt, {radius:4, color:'#344e41', fillColor:'#dad7cd', fillOpacity:1, interactive:false}).addTo(this.draft));
            if (this.vertices.length > 1) L.polyline(this.vertices, {color:'#344e41', dashArray:'5 5', interactive:false}).addTo(this.draft);
            this.callbacks.message(`${this.vertices.length} vertices. Click the first point or press Enter to finish.`);
        } else if (this.mode === 'ruler') {
            this.rulerPoints.push(latlng);
            if (this.rulerPoints.length === 2) {
                if (this.rulerLayer) this.map.removeLayer(this.rulerLayer);
                this.rulerLayer = L.polyline(this.rulerPoints, {color:'#b8563c'}).addTo(this.map);
                const km = this.map.distance(...this.rulerPoints) / 1000;
                this.callbacks.message(`Approximate map distance: ${km.toFixed(2)} km.`);
                this.cancel();
            }
        }
    }
    finish() {
        if (this.vertices.length < 3) { this.callbacks.message('Add at least three vertices.'); return; }
        const ring = this.vertices.map(pt => [pt.lng, pt.lat]);
        ring.push([...ring[0]]);
        this.setPolygon({type:'Polygon', coordinates:[ring]});
        this.cancel();
        this.callbacks.message('Area selected. Choose a date and find seasonal animals.');
    }
    setPolygon(polygon) {
        if (this.areaLayer) this.map.removeLayer(this.areaLayer);
        this.polygon = polygon;
        this.areaLayer = L.polygon(polygon.coordinates[0].map(([lng,lat]) => [lat,lng]), {color:'#344e41', fillColor:'#588157', fillOpacity:.2}).addTo(this.map);
        this.callbacks.polygon(polygon);
    }
    clearPolygon() {
        this.cancel();
        if (this.areaLayer) this.map.removeLayer(this.areaLayer);
        this.areaLayer = null;
        this.polygon = null;
        this.callbacks.polygon(null);
    }
    setTarget(lat, lng) {
        if (!Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat)>90 || Math.abs(lng)>180) throw Error('Use valid WGS84 coordinates.');
        this.target = {lat,lng};
        if (this.pointMarker) this.pointMarker.setLatLng([lat,lng]);
        else this.pointMarker = L.marker([lat,lng]).addTo(this.map).bindPopup('Study location');
        this.callbacks.point(this.target);
    }
}
