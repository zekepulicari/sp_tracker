/** Personal credentials live only in this page's memory, never browser storage. */
export function setupApiSettings({rerun, isBusy, explore}) {
    const $ = id => document.getElementById(id);
    const input = $('gemini-api-key'), status = $('api-key-status');
    let key = '';
    $('api-key-form').addEventListener('submit', event => {
        event.preventDefault();
        if (isBusy()) {
            status.textContent = 'Wait for the current analysis to finish before applying a key.';
            return;
        }
        const candidate = input.value.trim();
        if (!/^[A-Za-z0-9_-]{10,256}$/.test(candidate)) {
            status.textContent = 'Enter a valid Gemini API key. It must contain 10–256 letters, numbers, underscores, or hyphens.';
            return;
        }
        if (window.isSecureContext !== true) {
            status.textContent = 'Personal keys require HTTPS or localhost. Open the app over a secure connection.';
            return;
        }
        key = candidate;
        input.value = '';
        status.textContent = 'Personal key applied for this tab. Google will validate it when generating a summary.';
        if (rerun()) {
            status.textContent += ' Your last species analysis is running again.';
            explore();
        } else {
            status.textContent += ' Choose an animal and location in Explore to run your first analysis.';
        }
    });
    $('clear-api-key').addEventListener('click', () => {
        key = ''; input.value = '';
        status.textContent = 'Personal key removed. Future analyses use the server default, if configured. Already submitted jobs keep the key they started with.';
    });
    return {headers: () => key ? {'X-Gemini-Key': key} : {}};
}
