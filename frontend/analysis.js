/**
 * analysis.js — Ecological Analysis Module for Species Tracker
 *
 * Wires the analysis panel UI (species input, model selector, run button)
 * to the FastAPI backend analysis endpoints:
 *   POST /api/analysis/run
 *   GET  /api/analysis/status/{task_id}
 *   GET  /api/analysis/results/{task_id}
 *
 * Renders progress steps, correlation tables, VIF warnings,
 * variable importance bars, and encounter probability.
 */

document.addEventListener('DOMContentLoaded', () => {

    // =========================================================
    // Element References
    // =========================================================
    const speciesInput    = document.getElementById('analysis-species');
    const limitSlider     = document.getElementById('analysis-limit');
    const limitValue      = document.getElementById('limit-value');
    const methodInput     = document.getElementById('analysis-method');
    const analysisTabs    = document.querySelectorAll('#analysis-tabs .segmented-tab');
    const methodDescText  = document.getElementById('method-explanation-text');
    const methodDocsLink  = document.getElementById('link-method-docs');
    const targetTitle     = document.getElementById('target-section-title');
    const targetSubtitle  = document.getElementById('target-section-subtitle');
    const dateGroup       = document.getElementById('prediction-date-group');
    const dateLabel       = document.getElementById('prediction-date-label');
    const runBtn          = document.getElementById('btn-run-analysis');
    const resultsArea     = document.getElementById('analysis-results');
    const personaStatus   = document.getElementById('persona-status');
    const pickLocBtn      = document.getElementById('btn-pick-location');
    const locDisplay      = document.getElementById('prediction-location-display');
    const dateInput       = document.getElementById('prediction-date');

    let predictionTarget = null; // {lat, lng}

    if (!runBtn || !resultsArea) return; // Guard if panel not present

    // =========================================================
    // Segmented Tabs & Adaptive Controls
    // =========================================================
    const METHOD_CONFIGS = {
        glm: {
            desc: "Predicts sighting probability using forecasted sea and weather conditions.",
            title: "Target Prediction",
            subtitle: "Select a date and location to calculate predictive encounter probabilities based on weather forecasts.",
            showDate: true,
            dateLabel: "Target Date"
        },
        rustic: {
            desc: "Calculates sighting odds based on historical monthly patterns in the selected area.",
            title: "Seasonal Baseline Target",
            subtitle: "Select a location and target date (for month) to evaluate historical seasonal occurrence rates.",
            showDate: true,
            dateLabel: "Target Date (Month of year)"
        },
        rf: {
            desc: "Ranks the environmental variables that most influence species presence.",
            title: "Local Habitat Assessment",
            subtitle: "Select a location on the map to rank which environmental factors matter most for this species.",
            showDate: false,
            dateLabel: ""
        }
    };

    function selectMethod(methodKey) {
        if (!METHOD_CONFIGS[methodKey]) return;
        const cfg = METHOD_CONFIGS[methodKey];

        if (methodInput) methodInput.value = methodKey;

        analysisTabs.forEach(btn => {
            const isMatch = btn.dataset.method === methodKey;
            btn.classList.toggle('active', isMatch);
            btn.setAttribute('aria-selected', isMatch ? 'true' : 'false');
        });

        if (methodDescText) methodDescText.textContent = cfg.desc;
        if (targetTitle) targetTitle.textContent = cfg.title;
        if (targetSubtitle) targetSubtitle.textContent = cfg.subtitle;
        if (dateGroup) dateGroup.style.display = cfg.showDate ? 'block' : 'none';
        if (dateLabel) dateLabel.textContent = cfg.dateLabel;
    }

    analysisTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            selectMethod(tab.dataset.method);
        });
    });

    if (methodDocsLink) {
        methodDocsLink.addEventListener('click', (e) => {
            e.preventDefault();
            const docsTab = document.querySelector('.nav-tab[data-tab="docs"]');
            if (docsTab) {
                docsTab.click();
                setTimeout(() => {
                    const el = document.getElementById('doc-methods');
                    if (el) el.scrollIntoView({ behavior: 'smooth' });
                }, 100);
            }
        });
    }

    let pollInterval = null;

    // =========================================================
    // Slider: live label update
    // =========================================================
    if (limitSlider && limitValue) {
        limitSlider.addEventListener('input', () => {
            limitValue.textContent = limitSlider.value;
        });
    }

    // =========================================================
    // Location Picker
    // =========================================================
    let isPickingLocation = false;
    let predictionMarker = null;

    if (pickLocBtn) {
        pickLocBtn.addEventListener('click', () => {
            if (!window._spMap) {
                alert('Map is not initialized.');
                return;
            }
            if (isPickingLocation) {
                // Cancel picking
                isPickingLocation = false;
                window._spMap.getContainer().style.cursor = '';
                pickLocBtn.innerHTML = '<span class="btn-icon">📍</span> Pick Location on Map';
                pickLocBtn.classList.remove('running');
            } else {
                // Start picking
                isPickingLocation = true;
                window._spMap.getContainer().style.cursor = 'crosshair';
                pickLocBtn.innerHTML = '<span class="btn-icon">❌</span> Cancel Picking';
                pickLocBtn.classList.add('running');
            }
        });

        // Global click listener for map (needs to hook into leafet)
        // Let's hook into window._spMap if available
        const attachMapListener = () => {
            if (window._spMap && !window._spMap._locPickerBound) {
                window._spMap.on('click', (e) => {
                    if (!isPickingLocation) return;
                    
                    isPickingLocation = false;
                    window._spMap.getContainer().style.cursor = '';
                    pickLocBtn.innerHTML = '<span class="btn-icon">📍</span> Pick Location on Map';
                    pickLocBtn.classList.remove('running');

                    predictionTarget = { lat: e.latlng.lat, lng: e.latlng.lng };
                    locDisplay.textContent = `Lat: ${predictionTarget.lat.toFixed(4)}, Lng: ${predictionTarget.lng.toFixed(4)}`;
                    
                    if (predictionMarker) {
                        predictionMarker.setLatLng(e.latlng);
                    } else {
                        predictionMarker = L.marker(e.latlng).addTo(window._spMap);
                        predictionMarker.bindPopup("<b>Prediction Target</b>").openPopup();
                    }
                });
                window._spMap._locPickerBound = true;
            }
        };
        // Retry attaching if map isn't loaded immediately
        setInterval(attachMapListener, 1000);
    }

    // =========================================================
    // Run Button
    // =========================================================
    runBtn.addEventListener('click', async () => {
        if (!predictionTarget) {
            renderError("Please click on the map to select a target location before running the analysis.");
            return;
        }

        const method = methodInput?.value || 'glm';
        let tDate = dateInput?.value || null;

        if (method !== 'rf' && !tDate) {
            renderError("Please select a target date before running the analysis.");
            return;
        }

        // If Key Factors (rf), date is not required; default to today's date for backend pipeline compatibility
        if (method === 'rf' && !tDate) {
            const today = new Date();
            tDate = today.toISOString().split('T')[0];
        }

        const rawSpecies = speciesInput?.value?.trim() || 'Orcinus orca';
        // Extract scientific name if it has parentheses: "Megaptera (Humpback Whale)" -> "Megaptera"
        const species = rawSpecies.split('(')[0].trim();
        
        const limit   = parseInt(limitSlider?.value || '500', 10);

        // Ensure the map and taxon ID are synced with the text input if the user didn't click the autocomplete
        try {
            const resp = await fetch(`/api/species/search?q=${encodeURIComponent(rawSpecies)}`);
            const data = await resp.json();
            if (data.results && data.results.length > 0) {
                window.currentTaxonId = data.results[0].id;
                if (window.updateGridLayer) window.updateGridLayer(window.currentTaxonId);
                if (window.mapInstance) window.mapInstance.fire('moveend');
            }
        } catch (e) {
            console.error("Failed to sync taxon ID", e);
        }

        const taxon_id = window.currentTaxonId;

        await runAnalysis(species, method, limit, predictionTarget, tDate, taxon_id);
    });

    // =========================================================
    // Core: runAnalysis
    // =========================================================
    async function runAnalysis(species, method, limit, targetLoc, targetDate, taxon_id) {
        // UI: disable button, show busy status
        setRunning(true);
        renderProgress('Initializing...', 0);

        let taskId;
        try {
            const payload = { species, method, limit };
            if (taxon_id) {
                payload.taxon_id = taxon_id;
            }
            if (targetLoc && targetDate) {
                payload.target_lat = targetLoc.lat;
                payload.target_lng = targetLoc.lng;
                payload.target_date = targetDate;
                payload.radius_km = 5.0; // Start with 5km and expand up to 50km
            }

            const resp = await fetch('/api/analysis/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${resp.status}`);
            }

            const data = await resp.json();
            taskId = data.task_id;
        } catch (err) {
            renderError(`Failed to start analysis: ${err.message}`);
            setRunning(false);
            return;
        }

        // Start polling for status
        let dots = 0;
        pollInterval = setInterval(async () => {
            dots = (dots + 1) % 4;
            try {
                await pollStatus(taskId);
            } catch (e) {
                clearInterval(pollInterval);
                renderError(`Polling error: ${e.message}`);
                setRunning(false);
            }
        }, 2000);
    }

    // =========================================================
    // pollStatus — check task progress
    // =========================================================
    async function pollStatus(taskId) {
        const resp = await fetch(`/api/analysis/status/${taskId}`);

        if (!resp.ok) throw new Error(`Status check failed: HTTP ${resp.status}`);

        const data = await resp.json();
        const { status, progress, error } = data;

        // Map progress messages to step index for visual tracking
        const progressPct = estimateProgress(progress);
        renderProgress(progress, progressPct);

        if (status === 'complete') {
            clearInterval(pollInterval);
            await fetchAndRenderResults(taskId);
            setRunning(false);
        } else if (status === 'error') {
            clearInterval(pollInterval);
            renderError(error || 'Unknown error');
            setRunning(false);
        }
        // If still "running" or "queued", keep polling
    }

    // =========================================================
    // fetchAndRenderResults
    // =========================================================
    async function fetchAndRenderResults(taskId) {
        const resp = await fetch(`/api/analysis/results/${taskId}`);
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }
        const results = await resp.json();
        renderResults(results);
    }

    // =========================================================
    // UI State Helpers
    // =========================================================
    function setRunning(isRunning) {
        if (!runBtn) return;
        if (isRunning) {
            runBtn.disabled = true;
            runBtn.classList.add('running');
            runBtn.innerHTML = '<span class="btn-icon">⏳</span> Running...';
            if (personaStatus) {
                personaStatus.className = 'persona-status busy';
            }
        } else {
            runBtn.disabled = false;
            runBtn.classList.remove('running');
            runBtn.innerHTML = '<span class="btn-icon">▶</span> Run Analysis';
            if (personaStatus) {
                personaStatus.className = 'persona-status online';
            }
        }
    }

    // =========================================================
    // Render: Progress
    // =========================================================
    const PROGRESS_STEPS = [
        { key: 'Initializing',       label: 'Initializing',                    icon: '⚙️' },
        { key: 'Fetching',           label: 'Fetching OBIS occurrences',        icon: '🌊' },
        { key: 'Retrieved',          label: 'OBIS data retrieved',              icon: '✅' },
        { key: 'Generating',         label: 'Generating pseudo-absences',       icon: '🎲' },
        { key: 'Fetching environ',   label: 'Fetching environmental data',      icon: '🌡️' },
        { key: 'Processing environ', label: 'Processing environmental data',    icon: '📡' },
        { key: 'Building',           label: 'Building aligned dataset',         icon: '🗂️' },
        { key: 'Computing Pearson',  label: 'Computing correlations',           icon: '📊' },
        { key: 'Checking',           label: 'VIF multicollinearity check',      icon: '🔍' },
        { key: 'Fitting',            label: 'Fitting model',                    icon: '🧮' },
        { key: 'Training',           label: 'Training Random Forest',           icon: '🌳' },
        { key: 'Running',            label: 'Running CCA',                      icon: '🔬' },
        { key: 'Generating AI',      label: 'Generating AI Interpretation',     icon: '✨' },
        { key: 'Analysis complete',  label: 'Analysis complete!',               icon: '🎉' },
    ];

    function estimateProgress(message) {
        if (!message) return 5;
        const msg = message.toLowerCase();
        if (msg.includes('complete')) return 100;
        if (msg.includes('generating ai')) return 95;
        if (msg.includes('fitting') || msg.includes('training') || msg.includes('running cca')) return 88;
        if (msg.includes('vif') || msg.includes('multicollinearity')) return 78;
        if (msg.includes('correlation')) return 70;
        if (msg.includes('building') || msg.includes('dataset ready')) return 62;
        if (msg.includes('processing environmental')) return 52;
        if (msg.includes('fetching environmental')) return 40;
        if (msg.includes('generating')) return 28;
        if (msg.includes('retrieved') || msg.includes('obis records')) return 20;
        if (msg.includes('fetching') || msg.includes('obis')) return 12;
        return 5;
    }

    function renderProgress(message, pct) {
        const currentStep = PROGRESS_STEPS.find(s =>
            message && message.toLowerCase().includes(s.key.toLowerCase())
        ) || PROGRESS_STEPS[0];

        const activeIndex = PROGRESS_STEPS.indexOf(currentStep);

        const stepsHtml = PROGRESS_STEPS
            .filter((_, i) => i <= Math.min(activeIndex + 1, PROGRESS_STEPS.length - 1))
            .slice(-5) // Show at most 5 steps
            .map((step, idx, arr) => {
                const globalIdx = activeIndex - (arr.length - 1 - idx);
                const isDone = globalIdx < activeIndex;
                const isActive = globalIdx === activeIndex;
                const cls = isDone ? 'done' : isActive ? 'active' : '';
                const icon = isDone ? '✅' : step.icon;
                return `<div class="progress-step ${cls}">
                    <span class="step-icon">${icon}</span>
                    <span>${isDone ? step.label : message}</span>
                </div>`;
            })
            .join('');

        resultsArea.innerHTML = `
            <div class="analysis-progress">
                ${stepsHtml}
                <div class="progress-bar-track">
                    <div class="progress-bar-fill" style="width: ${pct}%"></div>
                </div>
            </div>
        `;
    }

    // =========================================================
    // Render: Full Results
    // =========================================================
    function renderResults(results) {
        let html = '';
        const { dataset_stats, correlations, vif, model, sst_warnings } = results;

        // --- AI INTERPRETATION CARD (if exists) ---
        if (results.interpretation) {
            html += `
                <div class="result-card interpretation-card">
                    <div class="result-card-header">
                        <div style="display:flex; align-items:center; gap:8px;">
                            <span class="result-card-icon">✨</span>
                            <span class="result-card-title">AI Interpretation</span>
                        </div>
                        <span class="docs-badge" style="margin-bottom:0; background:rgba(88, 129, 87, 0.2); color:var(--color-bg-light); border:1px solid rgba(88, 129, 87, 0.5);">Gemini 3.1 Flash-Lite</span>
                    </div>
                    <div class="result-card-body" style="font-size: 1.05em; line-height: 1.6; color: var(--color-bg-light);">
                        ${results.interpretation.replace(/\n\n/g, '<br><br>')}
                    </div>
                </div>
            `;
        }

        // --- ENCOUNTER PREDICTION CARD (if exists) ---
        if (results.encounter_prediction) {
            const pred = results.encounter_prediction;
            
            // Color code based on probability
            let probColor = 'var(--color-success)'; // green
            if (pred.probability_pct < 30) probColor = 'var(--color-danger)'; // red
            else if (pred.probability_pct < 60) probColor = 'var(--color-warning)'; // yellow

            html += `
                <div class="result-card" style="border-left: 4px solid ${probColor}; margin-bottom: 20px;">
                    <div class="result-card-header" style="justify-content: space-between;">
                        <div style="display:flex; align-items:center; gap:8px;">
                            <span class="result-card-icon">🎯</span>
                            <span class="result-card-title">Encounter Prediction</span>
                        </div>
                        <div style="font-size: 1.4em; font-weight: 800; color: ${probColor};">
                            ${pred.probability_pct.toFixed(1)}%
                        </div>
                    </div>
                    <div style="font-size: 0.85em; opacity: 0.9; margin-bottom: 12px; line-height: 1.4;">
                        Target: <strong>${pred.target_date}</strong><br>
                        Location: ${pred.target_lat.toFixed(4)}, ${pred.target_lng.toFixed(4)}<br>
                        Radius Used: ${pred.radius_km_used.toFixed(1)} km<br>
                        Mode: <em>${pred.mode}</em>
                    </div>
            `;

            if (pred.algorithm_method === "glm") {
                html += `
                    <div style="font-size: 0.78em; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--color-accent-light); opacity: 0.85; margin-bottom: 4px;">
                        Forecasted Conditions
                    </div>
                    <table class="correlation-table" style="font-size: 0.85em;">
                        <tbody>
                            <tr><td>Sea Surface Temp</td><td>${pred.conditions_used.sst !== null && pred.conditions_used.sst !== undefined ? pred.conditions_used.sst.toFixed(1) + ' °C' : 'N/A'}</td></tr>
                            <tr><td>Wind Speed</td><td>${pred.conditions_used.wind_speed !== null && pred.conditions_used.wind_speed !== undefined ? pred.conditions_used.wind_speed.toFixed(1) + ' km/h' : 'N/A'}</td></tr>
                            <tr><td>Air Temp (2m)</td><td>${pred.conditions_used.air_temp !== null && pred.conditions_used.air_temp !== undefined ? pred.conditions_used.air_temp.toFixed(1) + ' °C' : 'N/A'}</td></tr>
                            <tr><td>Wave Height</td><td>${pred.conditions_used.wave_height !== null && pred.conditions_used.wave_height !== undefined ? pred.conditions_used.wave_height.toFixed(1) + ' m' : 'N/A'}</td></tr>
                            <tr><td>Ocean Current</td><td>${pred.conditions_used.ocean_current !== null && pred.conditions_used.ocean_current !== undefined ? pred.conditions_used.ocean_current.toFixed(2) + ' km/h' : 'N/A'}</td></tr>
                        </tbody>
                    </table>
                    <div style="margin-top: 15px; padding: 12px; background-color: rgba(88, 129, 87, 0.1); border-left: 3px solid var(--color-accent-primary); border-radius: 4px; font-size: 0.8em; line-height: 1.5; color: var(--color-text-main);">
                        <strong style="color: var(--color-accent-light); display: block; margin-bottom: 4px;">How is this calculated?</strong>
                        First, the model uses your selected <strong>Location</strong> and <strong>Target Date</strong> to fetch the exact weather forecast from the Open-Meteo API for that specific spot. 
                        Then, this probability is calculated using a Logistic Regression model trained on historical sightings. The model assigns a mathematical weight (coefficient) to each forecasted environmental condition shown above. These values are multiplied by their respective weights and combined to produce the final probability percentage.
                    </div>
                `;
            } else if (pred.algorithm_method === "rustic") {
                html += `
                    <div style="margin-top: 15px; padding: 12px; background-color: rgba(88, 129, 87, 0.1); border-left: 3px solid var(--color-accent-primary); border-radius: 4px; font-size: 0.8em; line-height: 1.5; color: var(--color-text-main);">
                        <strong style="color: var(--color-accent-light); display: block; margin-bottom: 4px;">How is this calculated? (Rustic Baseline)</strong>
                        This probability completely ignores weather forecasts. It is calculated simply by evaluating the historical frequency of sightings for the selected month within the local radius. This serves as a raw baseline to see if the weather actually helps predict the species better than random chance.
                    </div>
                `;
            } else if (pred.algorithm_method === "rf") {
                html += `
                    <div style="margin-top: 15px; padding: 12px; background-color: rgba(88, 129, 87, 0.1); border-left: 3px solid var(--color-accent-primary); border-radius: 4px; font-size: 0.8em; line-height: 1.5; color: var(--color-text-main);">
                        <strong style="color: var(--color-accent-light); display: block; margin-bottom: 4px;">Why is this not a forecast?</strong>
                        Random Forest models are complex and cannot be easily translated into a simple forecast formula via API. The percentage shown here is simply the <em>historical training accuracy</em> for the local area. However, scroll down to see the "Variable Importance" bars which show exactly what environmental factors matter most in this specific location!
                    </div>
                `;
            }

            html += `
                </div>
            `;
        }

        // --- 1. DATASET STATS ---
        if (results.dataset_stats && !results.encounter_prediction) {
            html += `
                <div class="result-card">
                    <div class="result-card-header">
                        <span class="result-card-icon">🗂️</span>
                        <span class="result-card-title">Dataset</span>
                    </div>
                    <table class="correlation-table">
                        <tr><td>Total Records</td><td><strong>${dataset_stats.total_records}</strong></td></tr>
                        <tr><td>Presence Points</td><td><strong>${dataset_stats.presence_count}</strong></td></tr>
                        <tr><td>Pseudo-absences</td><td><strong>${dataset_stats.absence_count}</strong></td></tr>
                        ${dataset_stats.rows_dropped > 0
                            ? `<tr><td>Dropped (no env data)</td><td>${dataset_stats.rows_dropped}</td></tr>`
                            : ''}
                    </table>
                </div>
            `;
        }

        // --- SST Validation Warnings ---
        if (sst_warnings && sst_warnings.length > 0 && !results.encounter_prediction) {
            html += `
                <div class="vif-warning">
                    <span class="vif-warning-icon">⚠️</span>
                    <div>
                        <strong>SST Validation (${sst_warnings.length} alerts)</strong><br>
                        ${sst_warnings.slice(0, 3).map(w => `<small>${w}</small>`).join('<br>')}
                        ${sst_warnings.length > 3 ? `<br><small>…and ${sst_warnings.length - 3} more</small>` : ''}
                    </div>
                </div>
            `;
        }

        // --- Correlation Card (Pearson) ---
        if (correlations?.pearson?.with_presence && !results.encounter_prediction) {
            const rows = Object.entries(correlations.pearson.with_presence)
                .map(([varName, vals]) => {
                    const c = vals.correlation;
                    const cls = c > 0.1 ? 'corr-positive' : c < -0.1 ? 'corr-negative' : 'corr-neutral';
                    const sig = vals.significant ? '<span class="significant-marker">*</span>' : '';
                    return `
                        <tr>
                            <td>${formatVarName(varName)}</td>
                            <td class="${cls}">${c > 0 ? '+' : ''}${c.toFixed(3)}${sig}</td>
                            <td class="${cls}" style="font-size:0.7em">${vals.p_value < 0.001 ? '<0.001' : vals.p_value.toFixed(3)}</td>
                        </tr>
                    `;
                }).join('');

            html += `
                <div class="result-card">
                    <div class="result-card-header">
                        <span class="result-card-icon">📈</span>
                        <span class="result-card-title">Pearson Correlation <small style="opacity:0.6;font-weight:400">(*p&lt;0.05)</small></span>
                    </div>
                    <table class="correlation-table">
                        <thead><tr><th>Variable</th><th>r ℹ️</th><th>p-value ℹ️</th></tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
            `;
        }

        // --- VIF Card ---
        if (vif?.scores?.length > 0 && !results.encounter_prediction) {
            const vifRows = vif.scores.map(s => `
                <tr>
                    <td>${formatVarName(s.variable)}</td>
                    <td style="color: ${s.vif > 10 ? '#f87171' : s.vif > 5 ? '#fbbf24' : '#4ade80'}">${s.vif.toFixed(1)}</td>
                    <td style="font-size:0.8em;opacity:0.7">${s.vif > 10 ? '⚠️ Severe' : s.vif > 5 ? '⚠️ Moderate' : '✅ OK'}</td>
                </tr>
            `).join('');

            html += `
                <div class="result-card">
                    <div class="result-card-header">
                        <span class="result-card-icon">🔍</span>
                        <span class="result-card-title">Multicollinearity (VIF)</span>
                    </div>
                    <table class="correlation-table">
                        <thead><tr><th>Variable</th><th>VIF ℹ️</th><th>Status</th></tr></thead>
                        <tbody>${vifRows}</tbody>
                    </table>
                </div>
            `;
        }

        // --- Model Card ---
        if (model && !results.encounter_prediction) {
            html += renderModelCard(model);
        }

        resultsArea.innerHTML = html;
        resultsArea.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }

    // =========================================================
    // Render: Model-specific Card
    // =========================================================
    function renderModelCard(model) {
        const type = model.model_type || 'Model';
        const prob = model.mean_encounter_probability;
        const acc  = model.accuracy;
        const auc  = model.auc;

        const probColor = prob > 0.6 ? '#4ade80' : prob > 0.35 ? '#fbbf24' : '#f87171';

        let bodyHtml = `
            <div class="probability-display">
                <div class="probability-value" style="color:${probColor}">${(prob * 100).toFixed(1)}%</div>
                <div class="probability-label">Mean Encounter Probability</div>
            </div>
            <table class="correlation-table" style="margin-top:10px">
                <tr><td>Accuracy</td><td><strong>${(acc * 100).toFixed(1)}%</strong></td></tr>
                ${auc !== null && auc !== undefined ? `<tr><td>AUC-ROC</td><td><strong>${auc.toFixed(3)}</strong></td></tr>` : ''}
                <tr><td>Train / Test</td><td><strong>${model.n_train} / ${model.n_test}</strong></td></tr>
            </table>
        `;

        // GLM coefficients
        if (model.coefficients) {
            const coeffRows = Object.entries(model.coefficients)
                .filter(([k]) => k !== 'intercept')
                .map(([varName, coeff]) => {
                    const pv = model.p_values?.[varName];
                    const sig = pv !== undefined && pv < 0.05 ? '<span class="significant-marker">*</span>' : '';
                    const cls = coeff > 0 ? 'corr-positive' : 'corr-negative';
                    return `<tr>
                        <td>${formatVarName(varName)}</td>
                        <td class="${cls}">${coeff > 0 ? '+' : ''}${coeff.toFixed(3)}${sig}</td>
                    </tr>`;
                }).join('');

            bodyHtml += `
                <div style="margin-top:10px;font-size:0.78em;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;color:var(--color-accent-light);opacity:0.85;margin-bottom:4px">
                    Coefficients <small style="font-weight:400;opacity:0.7">(*p&lt;0.05)</small>
                </div>
                <table class="correlation-table">
                    <thead><tr><th>Variable</th><th>β ℹ️</th></tr></thead>
                    <tbody>${coeffRows}</tbody>
                </table>
            `;
        }

        // Random Forest variable importance bars
        if (model.variable_importance) {
            const maxImp = Math.max(...Object.values(model.variable_importance));
            const bars = Object.entries(model.variable_importance).map(([varName, imp]) => {
                const pct = maxImp > 0 ? (imp / maxImp * 100).toFixed(0) : 0;
                return `
                    <div class="importance-bar-row">
                        <span class="importance-bar-label">${formatVarName(varName)}</span>
                        <div class="importance-bar-track">
                            <div class="importance-bar-fill" style="width:${pct}%"></div>
                        </div>
                        <span class="importance-bar-value">${(imp * 100).toFixed(1)}%</span>
                    </div>
                `;
            }).join('');

            bodyHtml += `
                <div style="margin-top:10px;font-size:0.78em;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;color:var(--color-accent-light);opacity:0.85;margin-bottom:6px">
                    Variable Importance
                </div>
                ${bars}
            `;
        }

        // CCA variable scores
        if (model.variable_scores) {
            const scoreRows = Object.entries(model.variable_scores)
                .sort(([, a], [, b]) => Math.abs(b) - Math.abs(a))
                .map(([varName, score]) => {
                    const cls = score > 0 ? 'corr-positive' : 'corr-negative';
                    return `<tr>
                        <td>${formatVarName(varName)}</td>
                        <td class="${cls}">${score > 0 ? '+' : ''}${score.toFixed(3)}</td>
                    </tr>`;
                }).join('');

            bodyHtml += `
                <div style="margin-top:10px;font-size:0.78em;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;color:var(--color-accent-light);opacity:0.85;margin-bottom:4px">
                    Canonical Scores
                </div>
                <table class="correlation-table">
                    <thead><tr><th>Variable</th><th title="Canonical Score. Importance of the variable in defining the environmental niche." style="cursor:help">Score ℹ️</th></tr></thead>
                    <tbody>${scoreRows}</tbody>
                </table>
                <div style="margin-top:8px;font-size:0.75em;opacity:0.65">
                    Explained variance: <strong>${model.explained_variance_pct}%</strong>
                </div>
            `;
        }

        const modelIcon = type.includes('GLM') ? '🧮' : type.includes('Forest') ? '🌳' : '🔬';

        return `
            <div class="result-card">
                <div class="result-card-header">
                    <span class="result-card-icon">${modelIcon}</span>
                    <span class="result-card-title">${type}</span>
                </div>
                ${bodyHtml}
            </div>
        `;
    }

    // =========================================================
    // Render: Error
    // =========================================================
    function renderError(message) {
        resultsArea.innerHTML = `
            <div class="analysis-error">
                <div class="analysis-error-title">⚠️ Analysis Failed</div>
                <div>${escapeHtml(message)}</div>
            </div>
        `;
        resultsArea.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    // =========================================================
    // Utility Helpers
    // =========================================================
    function formatVarName(name) {
        const labels = {
            'sst':                    'Sea Surface Temp',
            'wind_speed':             'Wind Speed',
            'wind_direction':         'Wind Direction',
            'wave_height':            'Wave Height',
            'ocean_current_velocity': 'Ocean Current',
            'month':                  'Month (Season)',
            'temperature_2m':         'Air Temp (2m)',
        };
        return labels[name] || name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    }

    function escapeHtml(str) {
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }
});
