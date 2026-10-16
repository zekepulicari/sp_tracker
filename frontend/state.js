/** Pure state and safe-output helpers shared by UI and regression tests. */
export const DEFAULT_SPECIES = { id: 41521, name: 'Orcinus orca', common_name: 'Orca' };
export function validSpecies(value) {
    return value && Number.isSafeInteger(value.id) && value.id > 0 && typeof value.name === 'string' && value.name.trim();
}
export function label(species) {
    return species.common_name ? `${species.name} (${species.common_name})` : species.name;
}
export function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
export function safeUrl(value) {
    try { const url = new URL(value); return url.protocol === 'https:' ? url.href : ''; }
    catch { return ''; }
}
export function readStorage(storage, key, fallback) {
    try { const value = JSON.parse(storage.getItem(key)); return value ?? fallback; } catch { return fallback; }
}
export function writeStorage(storage, key, value) {
    try { storage.setItem(key, JSON.stringify(value)); } catch { /* Storage may be disabled. */ }
}
export class Selection {
    constructor(storage) {
        this.storage = storage;
        const saved = readStorage(storage, 'sp-tracker:last-species', DEFAULT_SPECIES);
        // Migrate the previous { id, name: scientific + common } preference.
        this.species = validSpecies(saved) ? {...saved, name:saved.name.split(' (')[0]} : {...DEFAULT_SPECIES};
        this.environment = readStorage(storage, 'sp-tracker:environment', 'terrestrial');
        if (!['terrestrial','marine'].includes(this.environment)) this.environment = 'terrestrial';
    }
    select(species) {
        if (!validSpecies(species)) throw Error('Choose a resolved species.');
        this.species = {...species};
        writeStorage(this.storage, 'sp-tracker:last-species', this.species);
    }
    invalidate() { this.species = null; }
    setEnvironment(value) {
        if (!['terrestrial','marine'].includes(value)) throw Error('Choose an environmental setting.');
        this.environment = value;
        writeStorage(this.storage, 'sp-tracker:environment', value);
    }
}
export function localDate() {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
}
