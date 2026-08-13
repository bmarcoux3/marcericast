/**
 * Personal Cashflow Dashboard - Main Application
 * Interactive financial visualization with parameter controls
 */

// ============================================================================
// Configuration & Constants
// ============================================================================

const API_BASE = '/api';
const CHART_COLORS = [
    '#2a78d6', // blue
    '#eb6834', // orange
    '#1baf7a', // aqua
    '#eda100', // yellow
    '#e87ba4', // magenta
    '#008300', // green
    '#4a3aa7', // violet
    '#e34948', // red
];

const PARAM_CATEGORIES = {
    macroeconomics: 'Macroeconomics',
    tax_rules: 'Tax Rules',
    accounts: 'Accounts',
    waterfall_strategy: 'Waterfall Strategy',
    life_decisions: 'Life Decisions',
    meta: 'Scenario Settings',
};

// Special parameters that get custom UI controls
// These override the default type detection based on API parameter metadata.
// Opt-in life-decision toggles/sliders come from .variable_meta via the API,
// so only generic overrides live here.
const SPECIAL_PARAMETERS = {
    // Mortgage principal is auto-calculated from asset_initial_value - down_payment
    // We hide it from the UI to avoid confusion
    'mortgage.principal': { type: 'hidden', label: 'Mortgage Principal (Auto-calculated)', category: 'Asset Information' },
};

// ============================================================================
// State Management
// ============================================================================

const state = {
    scenarios: [],
    currentScenario: null,
    parameters: [],
    simulationData: null,
    simulationColumns: [],
    simulationSummary: {},
    charts: {},
    pendingParamChanges: new Map(),
    theme: 'light',
    realDollars: true,
};

// ============================================================================
// Utility Functions
// ============================================================================

function formatCurrency(value, decimals = 0) {
    if (value === null || value === undefined || isNaN(value)) return '$0';
    const absValue = Math.abs(value);
    let formatted;
    if (absValue >= 1e12) {
        formatted = (value / 1e12).toFixed(decimals) + 'T';
    } else if (absValue >= 1e9) {
        formatted = (value / 1e9).toFixed(decimals) + 'B';
    } else if (absValue >= 1e6) {
        formatted = (value / 1e6).toFixed(decimals) + 'M';
    } else if (absValue >= 1e3) {
        formatted = (value / 1e3).toFixed(decimals) + 'K';
    } else {
        formatted = value.toFixed(decimals);
    }
    return '$' + formatted;
}

function formatNumber(value) {
    if (value === null || value === undefined || isNaN(value)) return '0';
    return value.toLocaleString();
}

function debounce(fn, delay) {
    let timeoutId;
    return (...args) => {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => fn(...args), delay);
    };
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.animation = 'slideIn 0.3s ease reverse';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

function getNestedValue(obj, path) {
    return path.split('.').reduce((o, k) => (o || {})[k], obj);
}

function getScenarioYearBounds() {
    const scenario = state.scenarios.find(s => s.name === state.currentScenario);
    const start = scenario ? scenario.start_year : 2026;
    const end = scenario ? scenario.end_year : 2079;
    return { start, end };
}

function setNestedValue(obj, path, value) {
    const parts = path.split('.');
    const last = parts.pop();
    const target = parts.reduce((o, k) => {
        if (!(k in o)) o[k] = {};
        return o[k];
    }, obj);
    target[last] = value;
}

function deepClone(obj) {
    return JSON.parse(JSON.stringify(obj));
}

// ============================================================================
// API Functions
// ============================================================================

async function fetchScenarios() {
    const response = await fetch(`${API_BASE}/scenarios`);
    if (!response.ok) throw new Error('Failed to fetch scenarios');
    return response.json();
}

async function fetchParameters(scenarioName) {
    const response = await fetch(`${API_BASE}/scenarios/${scenarioName}/parameters`);
    if (!response.ok) throw new Error('Failed to fetch parameters');
    return response.json();
}

async function runSimulation(scenarioName, options = null) {
    if (!options) options = {};
    const body = {
        scenario_name: scenarioName,
        start_year: options.startYear,
        end_year: options.endYear,
        real_dollars: state.realDollars,
        parameter_overrides: []
    };

    // Add parameter overrides
    for (const [path, value] of state.pendingParamChanges) {
        body.parameter_overrides.push({ path, value });
    }

    const response = await fetch(`${API_BASE}/scenarios/${scenarioName}/run`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(body)
    });

    const responseData = await response.json();
    if (!response.ok) {
        const errorDetail = responseData.error || responseData.detail || 'Failed to run simulation';
        throw new Error(errorDetail);
    }
    return responseData;
}

async function exportCsv(scenarioName) {
    const response = await fetch(`${API_BASE}/export/${scenarioName}`);
    if (!response.ok) throw new Error('Failed to export CSV');

    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${scenarioName}-output.csv`;
    a.click();
    window.URL.revokeObjectURL(url);
}

// ============================================================================
// Parameter Rendering
// ============================================================================

function categorizeParameter(param) {
    const path = param.path;

    // Check for special parameters first
    if (SPECIAL_PARAMETERS[path]) {
        const special = SPECIAL_PARAMETERS[path];
        return special.category || PARAM_CATEGORIES[path.split('.')[0]] || 'Other';
    }

    // Hide mortgage.principal from UI (auto-calculated) - match by suffix since path includes event ID
    if (path.endsWith('mortgage.principal')) {
        return 'Other';
    }

    // Show opt-in life decision variables (exposed via .variable_meta in YAML)
    // These carry a control/label from the API; everything else stays hidden.
    if (path.startsWith('variables.') && param.control) {
        return 'Life Decisions';
    }

    // Hide all other variables (they may have "life_decisions" category from API but we only want opted-in ones)
    if (path.startsWith('variables.')) {
        return 'Other';
    }

    // 2. Income events - salary events with gap_years and step_adjustments
    if (path.startsWith('events.')) {
        const eventId = path.split('.')[1];

        // Check if this is an income event (salary)
        const categoryParam = state.parameters.find(p => p.path === `events.${eventId}.category`);
        const isIncomeEvent = categoryParam && categoryParam.current_value === 'income';

        if (isIncomeEvent) {
            // Check if it's a relevant parameter for income events
            const relevantIncomeParams = ['base_amount', 'start_year', 'end_year', 'gap_years', 'step_adjustments'];
            const paramName = path.split('.').slice(2).join('.');
            // Handle step_adjustments.* pattern
            if (paramName.startsWith('step_adjustments.') || relevantIncomeParams.includes(paramName)) {
                return 'Income';
            }
        }

        // 3. Asset purchase events - show asset value, down payment, mortgage rates, costs
        // Detect asset purchase events by their specific parameters (down_payment, asset_initial_value, mortgage)
        const hasAssetPurchaseParams = state.parameters.some(p =>
            p.path.startsWith(`events.${eventId}.`) &&
            (p.path.includes('down_payment') || p.path.includes('asset_initial_value') || p.path.includes('mortgage.'))
        );
        if (hasAssetPurchaseParams) {
            // Only show specific asset purchase parameters (mortgage.principal is auto-calculated)
            const relevantAssetParams = ['down_payment', 'asset_initial_value', 'mortgage.interest_rate', 'mortgage.term_years', 'category'];
            const paramName = path.split('.').slice(2).join('.');
            if (relevantAssetParams.includes(paramName)) {
                return 'Asset Information';
            }
        }
    }

    // Hide everything else
    return 'Other';
}

function getInputType(param) {
    const path = param.path;

    // Check for special parameters first
    if (SPECIAL_PARAMETERS[path]) {
        return SPECIAL_PARAMETERS[path].type;
    }

    // Hide mortgage.principal from UI (auto-calculated)
    if (path.endsWith('mortgage.principal')) {
        return 'hidden';
    }

    // Handle gap_years (list type) - for any parameter that might have it
    if (path.includes('gap_years') && param.parameter_type === 'list') {
        return 'gap_years';
    }

    // Handle step_adjustments for income events - show as dictionary editor
    if (param.parameter_type === 'dict' && path.includes('step_adjustments')) {
        return 'step_adjustments';
    }

    // Opt-in life decision controls from .variable_meta
    if (param.control === 'toggle') return 'checkbox';
    if (param.control === 'slider') return 'number';

    if (param.parameter_type === 'bool') return 'checkbox';
    // Use text/number input instead of range slider for ints and floats
    if (param.parameter_type === 'int') return 'number';
    if (param.parameter_type === 'float') return 'number';
    if (param.parameter_type === 'str' && param.path.includes('growth_rate_ref')) return 'select';
    return 'text';
}

function createParameterElement(param) {
    const inputType = getInputType(param);
    const category = categorizeParameter(param);
    const isModified = state.pendingParamChanges.has(param.path);

    const div = document.createElement('div');
    div.className = 'param-item' + (isModified ? ' modified' : '');
    div.dataset.path = param.path;
    div.dataset.category = category;

    let inputHtml = '';
    const currentValue = state.pendingParamChanges.has(param.path)
        ? state.pendingParamChanges.get(param.path)
        : param.current_value;

    // Get special config if exists
    const specialConfig = SPECIAL_PARAMETERS[param.path];

    // Get label - prefer special config label, then API label (.variable_meta), then description, then path
    const label = specialConfig?.label ?? param.label ?? param.description ?? param.path;

    // Base label HTML for most input types
    const labelHtml = `<label class="param-label" for="${param.path.replace(/\./g, '-')}">${escapeHtml(label)}</label>`;

    if (inputType === 'select') {
        // For growth_rate_ref, provide options from macroeconomics
        const options = ['equities', 'bonds', 'real_estate', 'cash_equivalents'];
        inputHtml = `
            ${labelHtml}
            <select class="param-select" id="${param.path.replace(/\./g, '-')}" data-path="${param.path}" aria-label="${param.description}">
                ${options.map(opt => `<option value="${opt}" ${opt === currentValue ? 'selected' : ''}>${opt}</option>`).join('')}
            </select>
        `;
    } else if (inputType === 'checkbox') {
        // Check if this is a dynamic step_adjustments checkbox
        const isStepAdjustment = param.path.includes('step_adjustments.');
        const label = isStepAdjustment ? param.description : (specialConfig?.label ?? param.description);
        inputHtml = `
            ${labelHtml}
            <div class="param-checkbox-container">
                <input type="checkbox" class="param-input" id="${param.path.replace(/\./g, '-')}" data-path="${param.path}"
                    ${currentValue ? 'checked' : ''} aria-label="${param.description}">
                <span class="param-checkbox-label">${label}</span>
            </div>
        `;
    } else if (inputType === 'gap_years') {
        // Gap years - display as a comma-separated list in a text area
        const gapYearsStr = Array.isArray(currentValue) ? currentValue.join(', ') : currentValue;
        inputHtml = `
            ${labelHtml}
            <textarea class="param-input param-gap-years" id="${param.path.replace(/\./g, '-')}" data-path="${param.path}"
                rows="3" aria-label="${param.description}" placeholder="Comma-separated years (e.g., 2027, 2028, 2030)">${gapYearsStr}</textarea>
        `;
    } else if (inputType === 'step_adjustments') {
        // Step adjustments - dictionary editor for year -> value pairs
        // The API now returns the full dict in param.current_value
        const stepAdjustments = param.current_value || {};
        const eventId = param.path.split('.')[1]; // e.g., 'primary_salary'
        const bounds = getScenarioYearBounds();

        const entries = Object.entries(stepAdjustments);
        const rowsHtml = entries.map(([year, value]) => `
            <div class="step-adjustment-row" data-year="${year}">
                <input type="number" class="param-input step-adjustment-year" value="${year}" step="1" min="${bounds.start}" max="${bounds.end}" aria-label="Year">
                <input type="number" class="param-input step-adjustment-value" value="${value}" step="0.01" min="0" aria-label="Adjustment multiplier (e.g., 1.12 for 12% increase)">
                <button type="button" class="btn btn-danger btn-sm step-adjustment-delete" aria-label="Delete">×</button>
            </div>
        `).join('');

        inputHtml = `
            ${labelHtml}
            <div class="step-adjustments-editor">
                <div class="step-adjustments-header">
                    <span class="step-adjustment-col-label">Year</span>
                    <span class="step-adjustment-col-label">Multiplier</span>
                    <span></span>
                </div>
                <div class="step-adjustments-rows" data-event-id="${eventId}">
                    ${rowsHtml || '<div class="step-adjustment-row-empty">No step adjustments yet</div>'}
                </div>
                <button type="button" class="btn btn-secondary btn-sm step-adjustment-add" data-event-id="${eventId}">+ Add Step Adjustment</button>
            </div>
        `;
    } else if (inputType === 'number') {
        // Number input for int and float parameters
        const min = param.min_value !== undefined ? `min="${param.min_value}"` : '';
        const max = param.max_value !== undefined ? `max="${param.max_value}"` : '';
        const step = param.step !== undefined ? `step="${param.step}"` : 'step="any"';
        inputHtml = `
            ${labelHtml}
            <input type="number" class="param-input" id="${param.path.replace(/\./g, '-')}" data-path="${param.path}"
                value="${currentValue}" ${min} ${max} ${step}
                aria-label="${param.description}">
        `;
    } else if (inputType === 'text') {
        // Text input for string parameters
        inputHtml = `
            ${labelHtml}
            <input type="text" class="param-input" id="${param.path.replace(/\./g, '-')}" data-path="${param.path}"
                value="${currentValue}" aria-label="${param.description}">
        `;
    } else if (inputType === 'hidden') {
        // Hidden input for auto-calculated values (e.g., mortgage.principal)
        inputHtml = `
            <input type="hidden" class="param-input" id="${param.path.replace(/\./g, '-')}" data-path="${param.path}"
                value="${currentValue}" aria-label="${param.description}">
        `;
    }

    // Set the innerHTML and return the div
    div.innerHTML = inputHtml;
    return div;
}

function renderParameters() {
    const container = document.getElementById('parametersList');
    const searchTerm = document.getElementById('paramSearch').value.toLowerCase();
    const categoryFilter = document.getElementById('categoryFilter').value;

    // Group parameters by category
    const categorized = {};
    for (const param of state.parameters) {
        const category = categorizeParameter(param);

        // Skip parameters in 'Other' category
        if (category === 'Other') continue;

        if (categoryFilter !== 'all' && category !== categoryFilter) continue;

        const searchText = `${param.path} ${param.description}`.toLowerCase();
        if (searchTerm && !searchText.includes(searchTerm)) continue;

        if (!categorized[category]) categorized[category] = [];
        categorized[category].push(param);
    }

    if (Object.keys(categorized).length === 0) {
        container.innerHTML = '<div class="loading">No parameters match your filter</div>';
        return;
    }

    // Sort categories
    const categoryOrder = [
        'Life Decisions',
        'Income',
        'Asset Information',
        'Other'
    ];
    const sortedCategories = Object.keys(categorized).sort((a, b) => {
        return (categoryOrder.indexOf(a) ?? 99) - (categoryOrder.indexOf(b) ?? 99);
    });

    container.innerHTML = '';
    for (const category of sortedCategories) {
        const params = categorized[category];
        const categoryDiv = document.createElement('div');
        categoryDiv.className = 'param-category collapsed';  // Start collapsed
        categoryDiv.innerHTML = `
            <div class="param-category-header">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="6 9 12 15 18 9"></polyline>
                </svg>
                <span>${category}</span>
                <span style="margin-left:auto; color:var(--text-muted); font-size:0.6875rem;">${params.length}</span>
            </div>
            <div class="param-items"></div>
        `;

        const itemsContainer = categoryDiv.querySelector('.param-items');
        for (const param of params) {
            itemsContainer.appendChild(createParameterElement(param));
        }

        container.appendChild(categoryDiv);
    }

    // Add event listeners
    attachParameterListeners();
}

function attachParameterListeners() {
    // Category toggle
    document.querySelectorAll('.param-category-header').forEach(header => {
        header.addEventListener('click', (e) => {
            if (e.target.closest('.param-reset-btn')) return;
            header.closest('.param-category').classList.toggle('collapsed');
        });
    });

    // Other input changes (text, number, checkbox, gap_years)
    document.querySelectorAll('.param-input:not(.step-adjustment-year):not(.step-adjustment-value)').forEach(input => {
        input.addEventListener('change', (e) => {
            const path = e.target.dataset.path;
            let value = e.target.value;
            if (e.target.type === 'number') {
                value = parseFloat(value);
            } else if (e.target.type === 'checkbox') {
                // API expects 0 or 1 for boolean parameters
                value = e.target.checked ? 1 : 0;
            } else if (e.target.classList.contains('param-gap-years')) {
                // Parse comma-separated years
                value = value.split(',').map(y => parseInt(y.trim())).filter(y => !isNaN(y));
            }
            state.pendingParamChanges.set(path, value);
            markParamModified(path, true);

            // Auto-calculate mortgage principal when down_payment or asset_initial_value changes
            if (path.includes('down_payment') || path.includes('asset_initial_value')) {
                recalculateMortgagePrincipal(path, value);
            }
        });
    });

    document.querySelectorAll('.param-select').forEach(select => {
        select.addEventListener('change', (e) => {
            const path = e.target.dataset.path;
            const value = e.target.value;
            state.pendingParamChanges.set(path, value);
            markParamModified(path, true);
        });
    });

    // Reset buttons
    document.querySelectorAll('.param-reset-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const path = btn.dataset.path;
            const param = state.parameters.find(p => p.path === path);
            if (param) {
                state.pendingParamChanges.delete(path);
                updateParamDisplay(path, param.current_value);
                markParamModified(path, false);
            }
        });
    });

    // Step adjustments editor listeners
    document.querySelectorAll('.step-adjustment-add').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const eventId = btn.dataset.eventId;
            const container = btn.closest('.step-adjustments-editor').querySelector('.step-adjustments-rows');
            const emptyMsg = container.querySelector('.step-adjustment-row-empty');
            if (emptyMsg) emptyMsg.remove();

            // Find next available year (simple heuristic: max year + 1)
            const bounds = getScenarioYearBounds();
            const existingYears = Array.from(container.querySelectorAll('.step-adjustment-year')).map(i => parseInt(i.value));
            const nextYear = existingYears.length > 0 ? Math.max(...existingYears) + 1 : bounds.start;

            const row = document.createElement('div');
            row.className = 'step-adjustment-row';
            row.innerHTML = `
                <input type="number" class="param-input step-adjustment-year" value="${nextYear}" step="1" min="${bounds.start}" max="${bounds.end}" aria-label="Year">
                <input type="number" class="param-input step-adjustment-value" value="1.0" step="0.01" min="0" aria-label="Adjustment multiplier (e.g., 1.12 for 12% increase)">
                <button type="button" class="btn btn-danger btn-sm step-adjustment-delete" aria-label="Delete">×</button>
            `;
            container.appendChild(row);
            attachStepAdjustmentRowListeners(row);
        });
    });

    // Initialize existing step adjustment rows
    document.querySelectorAll('.step-adjustment-row').forEach(row => {
        attachStepAdjustmentRowListeners(row);
    });
}

function recalculateMortgagePrincipal(path, newValue) {
    // path is either events.{eventId}.down_payment or events.{eventId}.asset_initial_value
    // We need to find the corresponding eventId and get the other value
    const pathParts = path.split('.');
    if (pathParts.length >= 3 && pathParts[0] === 'events') {
        const eventId = pathParts[1];
        const paramName = pathParts[2];

        if (paramName === 'down_payment' || paramName === 'asset_initial_value') {
            // Get the other value
            const otherParamName = paramName === 'down_payment' ? 'asset_initial_value' : 'down_payment';
            const otherPath = `events.${eventId}.${otherParamName}`;
            const otherParam = state.parameters.find(p => p.path === otherPath);
            if (!otherParam) return;

            const otherValue = state.pendingParamChanges.has(otherPath)
                ? state.pendingParamChanges.get(otherPath)
                : otherParam.current_value;

            // Calculate mortgage principal
            const assetValue = paramName === 'asset_initial_value' ? newValue : otherValue;
            const downPayment = paramName === 'down_payment' ? newValue : otherValue;

            if (assetValue !== undefined && downPayment !== undefined) {
                const mortgagePrincipal = Math.max(0, assetValue - downPayment);
                const mortgagePrincipalPath = `events.${eventId}.mortgage.principal`;
                state.pendingParamChanges.set(mortgagePrincipalPath, mortgagePrincipal);
                updateParamDisplay(mortgagePrincipalPath, mortgagePrincipal);
                markParamModified(mortgagePrincipalPath, true);
            }
        }
    }
}

function attachStepAdjustmentRowListeners(row) {
    const yearInput = row.querySelector('.step-adjustment-year');
    const valueInput = row.querySelector('.step-adjustment-value');
    const deleteBtn = row.querySelector('.step-adjustment-delete');
    const container = row.closest('.step-adjustments-rows');
    const eventId = container.dataset.eventId;

    const updatePendingChanges = () => {
        // Build the full step_adjustments dict for this event
        const stepAdjustments = {};
        const rows = container.querySelectorAll('.step-adjustment-row');
        rows.forEach(r => {
            const year = r.querySelector('.step-adjustment-year').value;
            const value = r.querySelector('.step-adjustment-value').value;
            if (year && value !== '') {
                stepAdjustments[parseInt(year)] = parseFloat(value);
            }
        });
        const path = `events.${eventId}.step_adjustments`;
        state.pendingParamChanges.set(path, stepAdjustments);
        markParamModified(path, true);
    };

    yearInput.addEventListener('change', updatePendingChanges);
    valueInput.addEventListener('change', updatePendingChanges);

    deleteBtn.addEventListener('click', () => {
        row.remove();
        // Check if empty
        const remainingRows = container.querySelectorAll('.step-adjustment-row');
        if (remainingRows.length === 0) {
            container.innerHTML = '<div class="step-adjustment-row-empty">No step adjustments yet</div>';
        }
        updatePendingChanges();
    });
}

function updateParamDisplay(path, value) {
    const item = document.querySelector(`.param-item[data-path="${path}"]`);
    if (!item) return;

    // Update checkbox
    const checkbox = item.querySelector(`.param-input[type="checkbox"][data-path="${path}"]`);
    if (checkbox) {
        checkbox.checked = (value === 1 || value === true);
    }

    // Update select
    const select = item.querySelector(`.param-select[data-path="${path}"]`);
    if (select) {
        select.value = value;
    }

    // Update regular text/number inputs
    const regularInput = item.querySelector(`.param-input[data-path="${path}"]:not([type="checkbox"]):not(.param-gap-years)`);
    if (regularInput) {
        regularInput.value = value;
    }

    // Update gap_years textarea
    const gapYearsInput = item.querySelector(`.param-gap-years[data-path="${path}"]`);
    if (gapYearsInput) {
        gapYearsInput.value = Array.isArray(value) ? value.join(', ') : value;
    }
}

function markParamModified(path, modified) {
    const item = document.querySelector(`.param-item[data-path="${path}"]`);
    if (!item) return;

    if (modified) {
        item.classList.add('modified');
        const resetBtn = item.querySelector('.param-reset-btn');
        if (resetBtn) resetBtn.style.display = 'inline-block';
    } else {
        item.classList.remove('modified');
        const resetBtn = item.querySelector('.param-reset-btn');
        if (resetBtn) resetBtn.style.display = 'none';
    }
}

function resetAllParameters() {
    state.pendingParamChanges.clear();
    renderParameters();
    showToast('All parameters reset to defaults', 'info');
}

function applyParameterChanges() {
    if (state.pendingParamChanges.size === 0) {
        showToast('No changes to apply', 'info');
        return;
    }
    runSimulationWithCurrentParams();
}

// ============================================================================
// Scenario Management
// ============================================================================

async function loadScenarios() {
    try {
        console.log('[Dashboard] Fetching scenarios...');
        state.scenarios = await fetchScenarios();
        console.log('[Dashboard] Scenarios loaded:', state.scenarios);
        const select = document.getElementById('scenarioSelect');
        select.innerHTML = state.scenarios.map(s =>
            `<option value="${s.name}">${s.display_name} (${s.start_year}-${s.end_year})</option>`
        ).join('');

        if (state.scenarios.length > 0) {
            select.value = state.scenarios[0].name;
            await loadScenario(state.scenarios[0].name);
        }
    } catch (error) {
        console.error('Failed to load scenarios:', error);
        showToast('Failed to load scenarios: ' + error.message, 'error');
    }
}

async function loadScenario(scenarioName) {
    const scenario = state.scenarios.find(s => s.name === scenarioName);
    if (!scenario) return;

    state.currentScenario = scenarioName;
    state.pendingParamChanges.clear();

    // Update UI
    console.log('[Dashboard] Loading scenario:', scenarioName);
    const badgeEl = document.getElementById('scenarioBadge');
    const startYearEl = document.getElementById('startYear');
    const endYearEl = document.getElementById('endYear');

    if (badgeEl) badgeEl.textContent = scenario.display_name;
    if (startYearEl) startYearEl.value = scenario.start_year;
    if (endYearEl) endYearEl.value = scenario.end_year;

    // Load parameters
    try {
        state.parameters = await fetchParameters(scenarioName);
        console.log('[Dashboard] Parameters loaded:', state.parameters.length);

        // Populate category filter dropdown
        populateCategoryFilter();

        renderParameters();
    } catch (error) {
        console.error('Failed to load parameters:', error);
        showToast('Failed to load parameters: ' + error.message, 'error');
    }

    // Run initial simulation
    await runSimulationWithCurrentParams();
}

function populateCategoryFilter() {
    const filter = document.getElementById('categoryFilter');
    const categories = new Set();

    for (const param of state.parameters) {
        const category = categorizeParameter(param);
        categories.add(category);
    }

    const categoryOrder = [
        'All Categories',
        'Life Decisions',
        'Income',
        'Asset Information',
        'Other'
    ];

    // Keep only categories that exist in the current scenario, in order
    const availableCategories = categoryOrder.filter(c => c === 'All Categories' || categories.has(c));

    filter.innerHTML = availableCategories.map(cat =>
        `<option value="${cat === 'All Categories' ? 'all' : cat}">${cat}</option>`
    ).join('');
}

async function runSimulationWithCurrentParams() {
    if (!state.currentScenario) return;

    const runBtn = document.getElementById('runSimulationBtn');
    runBtn.disabled = true;
    runBtn.innerHTML = `
        <svg class="spinner" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10" stroke-opacity="0.25"></circle>
            <path d="M12 2a10 10 0 0 1 10 10" stroke-opacity="1"></path>
        </svg>
        Running...
    `;

    try {
        const startYear = parseInt(document.getElementById('startYear').value) || state.scenarios.find(s => s.name === state.currentScenario).start_year;
        const endYear = parseInt(document.getElementById('endYear').value) || state.scenarios.find(s => s.name === state.currentScenario).end_year;

        const result = await runSimulation(state.currentScenario, { startYear, endYear });

        if (!result.success) {
            throw new Error(result.error || 'Simulation failed');
        }

        state.simulationData = result.data;
        state.simulationColumns = result.columns;
        state.simulationSummary = result.summary;
        state.realDollars = !!result.deflated;

        const realDollarsBadge = document.getElementById('realDollarsBadge');
        const realDollarsToggle = document.getElementById('realDollarsToggle');
        if (realDollarsBadge) realDollarsBadge.style.display = state.realDollars ? 'inline-block' : 'none';
        if (realDollarsToggle) realDollarsToggle.checked = state.realDollars;

        renderAllCharts();
        renderSummaryCards();
        renderDataTable();

        showToast('Simulation complete', 'success');
    } catch (error) {
        console.error('Simulation error:', error);
        showToast('Simulation failed: ' + error.message, 'error');
    } finally {
        runBtn.disabled = false;
        runBtn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polygon points="5 3 19 12 5 21 5 3"></polygon>
            </svg>
            Run Simulation
        `;
    }
}

// ============================================================================
// Chart Rendering
// ============================================================================

function getChartColors(count) {
    return CHART_COLORS.slice(0, count);
}

function createGradient(ctx, color, direction = 'vertical') {
    const gradient = direction === 'vertical'
        ? ctx.createLinearGradient(0, 0, 0, ctx.canvas.height)
        : ctx.createLinearGradient(0, 0, ctx.canvas.width, 0);
    gradient.addColorStop(0, color + '40'); // 25% opacity
    gradient.addColorStop(1, color + '00'); // 0% opacity
    return gradient;
}

function destroyChart(chartName) {
    if (state.charts[chartName]) {
        state.charts[chartName].destroy();
        delete state.charts[chartName];
    }
}

function renderNetWorthChart() {
    console.log('[Dashboard] renderNetWorthChart called');
    const canvas = document.getElementById('netWorthChart');
    if (!canvas) {
        console.error('[Dashboard] netWorthChart canvas not found');
        return;
    }
    if (typeof Chart === 'undefined') {
        console.error('[Dashboard] Chart.js not available for netWorthChart');
        return;
    }
    const ctx = canvas.getContext('2d');
    destroyChart('netWorth');

    const data = state.simulationData;
    if (!data) {
        console.error('[Dashboard] No simulation data for net worth chart');
        return;
    }
    const years = data.map(d => d.Year);
    const netWorth = data.map(d => d['Net Worth'] || 0);
    const totalAssets = data.map(d => d['Total Assets'] || 0);
    const totalLiabilities = data.map(d => d['Total Liabilities'] || 0);

    const chartType = document.getElementById('netWorthChartType').value;

    try {
        state.charts.netWorth = new Chart(ctx, {
            type: chartType === 'area' ? 'line' : 'line',
            data: {
                labels: years,
                datasets: [
                    {
                        label: 'Net Worth',
                        data: netWorth,
                        borderColor: CHART_COLORS[0],
                        backgroundColor: chartType === 'area' ? createGradient(ctx, CHART_COLORS[0]) : 'transparent',
                        fill: chartType === 'area',
                        tension: 0.3,
                        pointRadius: 0,
                        pointHoverRadius: 6,
                        borderWidth: 2.5,
                    },
                    {
                        label: 'Total Assets',
                        data: totalAssets,
                        borderColor: CHART_COLORS[2],
                        backgroundColor: 'transparent',
                        fill: false,
                        tension: 0.3,
                        pointRadius: 0,
                        pointHoverRadius: 4,
                        borderWidth: 1.5,
                        borderDash: [5, 5],
                    },
                    {
                        label: 'Total Liabilities',
                        data: totalLiabilities,
                        borderColor: CHART_COLORS[7],
                        backgroundColor: 'transparent',
                        fill: false,
                        tension: 0.3,
                        pointRadius: 0,
                        pointHoverRadius: 4,
                        borderWidth: 1.5,
                        borderDash: [5, 5],
                    },
                ],
            },
            options: getCommonChartOptions('Net Worth ($)', true),
        });
    } catch (error) {
        console.error('[Dashboard] Error creating netWorthChart:', error);
    }
}

function renderCashFlowChart() {
    const ctx = document.getElementById('cashFlowChart').getContext('2d');
    destroyChart('cashFlow');

    const data = state.simulationData;
    const years = data.map(d => d.Year);
    const netCashFlow = data.map(d => d['Net Cash Flow'] || 0);
    const grossIncome = data.map(d => d['Gross Taxable Income'] || 0);

    const chartType = document.getElementById('cashFlowChartType').value;

    state.charts.cashFlow = new Chart(ctx, {
        type: chartType,
        data: {
            labels: years,
            datasets: [
                {
                    label: 'Net Cash Flow',
                    data: netCashFlow,
                    backgroundColor: netCashFlow.map(v => v >= 0 ? CHART_COLORS[2] + 'CC' : CHART_COLORS[7] + 'CC'),
                    borderColor: netCashFlow.map(v => v >= 0 ? CHART_COLORS[2] : CHART_COLORS[7]),
                    borderWidth: 1,
                    borderRadius: 4,
                },
                {
                    label: 'Gross Income',
                    data: grossIncome,
                    type: 'line',
                    borderColor: CHART_COLORS[0],
                    backgroundColor: 'transparent',
                    fill: false,
                    tension: 0.3,
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    borderWidth: 2,
                    yAxisID: 'y',
                },
            ],
        },
        options: {
            ...getCommonChartOptions('Amount ($)'),
            scales: {
                ...getCommonChartOptions('Amount ($)').scales,
                y: {
                    ...getCommonChartOptions('Amount ($)').scales.y,
                    title: { display: true, text: 'Amount ($)' },
                },
            },
        },
    });
}

function renderIncomeExpenseChart() {
    const ctx = document.getElementById('incomeExpenseChart').getContext('2d');
    destroyChart('incomeExpense');

    const data = state.simulationData;
    const years = data.map(d => d.Year);
    const income = data.map(d => d['Gross Taxable Income'] || 0);
    const expenses = data.map(d => Math.abs(d['Net Cash Flow'] || 0) - (d['Gross Taxable Income'] || 0));
    // Better: sum all expense tags
    const tagColumns = state.simulationColumns.filter(c => c.startsWith('Tag: '));
    const totalExpenses = data.map(d => {
        let sum = 0;
        for (const col of tagColumns) {
            const val = d[col] || 0;
            if (val < 0) sum += Math.abs(val);
        }
        return sum;
    });

    state.charts.incomeExpense = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: years,
            datasets: [
                {
                    label: 'Income',
                    data: income,
                    backgroundColor: CHART_COLORS[2] + 'CC',
                    borderColor: CHART_COLORS[2],
                    borderWidth: 1,
                    borderRadius: 4,
                },
                {
                    label: 'Expenses',
                    data: totalExpenses,
                    backgroundColor: CHART_COLORS[7] + 'CC',
                    borderColor: CHART_COLORS[7],
                    borderWidth: 1,
                    borderRadius: 4,
                },
            ],
        },
        options: getCommonChartOptions('Amount ($)'),
    });
}

function renderAssetAllocationChart() {
    const ctx = document.getElementById('assetAllocationChart').getContext('2d');
    destroyChart('assetAllocation');

    const data = state.simulationData;
    if (!data || data.length === 0) return;

    const lastYear = data[data.length - 1];
    const assetColumns = state.simulationColumns.filter(c => c.startsWith('Asset: '));

    const labels = [];
    const values = [];
    const colors = [];

    for (let i = 0; i < assetColumns.length; i++) {
        const col = assetColumns[i];
        const val = lastYear[col] || 0;
        if (val > 0) {
            labels.push(col.replace('Asset: ', ''));
            values.push(val);
            colors.push(CHART_COLORS[i % CHART_COLORS.length] + 'CC');
        }
    }

    // Add account balances
    const accountColumns = state.simulationColumns.filter(c => c.startsWith('Account: '));
    for (let i = 0; i < accountColumns.length; i++) {
        const col = accountColumns[i];
        const val = lastYear[col] || 0;
        if (val > 0) {
            labels.push(col.replace('Account: ', '') + ' (Account)');
            values.push(val);
            colors.push(CHART_COLORS[(i + assetColumns.length) % CHART_COLORS.length] + '88');
        }
    }

    if (values.length === 0) {
        ctx.font = '14px system-ui';
        ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--text-muted').trim();
        ctx.textAlign = 'center';
        ctx.fillText('No asset data available', ctx.canvas.width / 2, ctx.canvas.height / 2);
        return;
    }

    state.charts.assetAllocation = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: colors,
                borderColor: colors.map(c => c.replace('CC', 'FF').replace('88', 'FF')),
                borderWidth: 2,
                borderRadius: 4,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        usePointStyle: true,
                        pointStyle: 'circle',
                        padding: 16,
                        font: { size: 11 },
                        color: getComputedStyle(document.documentElement).getPropertyValue('--text-secondary').trim(),
                    },
                },
                tooltip: {
                    callbacks: {
                        label: (context) => {
                            const label = context.label || '';
                            const value = formatCurrency(context.parsed);
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const pct = ((context.parsed / total) * 100).toFixed(1);
                            return `${label}: ${value} (${pct}%)`;
                        },
                    },
                },
            },
            cutout: '60%',
        },
    });
}

function _hexToRgba(hex, alpha) {
    const h = hex.startsWith('#') ? hex.slice(1) : hex;
    const full = h.length === 8 ? h.slice(0, 6) : h;
    const r = parseInt(full.slice(0, 2), 16);
    const g = parseInt(full.slice(2, 4), 16);
    const b = parseInt(full.slice(4, 6), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function enableLegendHoverHighlight(chart) {
    // Capture original colors once so we can restore them after a hover.
    const originals = chart.data.datasets.map(ds => ({
        borderColor: ds.borderColor,
        backgroundColor: ds.backgroundColor,
        borderWidth: ds.borderWidth,
    }));
    const legend = chart.options.plugins.legend;
    if (!legend) return;

    legend.onHover = (e, legendItem) => {
        chart.data.datasets.forEach((ds, i) => {
            const isTarget = i === legendItem.datasetIndex;
            ds.backgroundColor = _hexToRgba(originals[i].backgroundColor, isTarget ? 0.9 : 0.08);
            ds.borderColor = _hexToRgba(originals[i].borderColor, isTarget ? 1 : 0.15);
            ds.borderWidth = isTarget ? Math.max(2, (originals[i].borderWidth || 0) + 1) : 1;
        });
        chart.update();
    };

    legend.onLeave = () => {
        chart.data.datasets.forEach((ds, i) => {
            ds.backgroundColor = originals[i].backgroundColor;
            ds.borderColor = originals[i].borderColor;
            ds.borderWidth = originals[i].borderWidth;
        });
        chart.update();
    };
}

function renderTagSpendingChart() {
    const canvas = document.getElementById('tagSpendingChart');
    const ctx = canvas.getContext('2d');
    destroyChart('tagSpending');

    const data = state.simulationData;
    if (!data) return;

    const chartMode = document.getElementById('tagChartYear').value;
    const years = data.map(d => d.Year);
    const tagColumns = state.simulationColumns.filter(c => c.startsWith('Tag: '));

    if (chartMode === 'percent') {
        // 100% stacked bars: each bar is a year, segments show each category's share
        const significant = tagColumns.filter(col => {
            const total = data.reduce((s, d) => s + Math.abs(d[col] || 0), 0);
            return total > 1000; // Only show significant tags
        });
        const yearTotals = data.map(d => significant.reduce((s, col) => s + Math.abs(d[col] || 0), 0));
        const datasets = significant.map((col, i) => {
            const color = CHART_COLORS[i % CHART_COLORS.length];
            return {
                label: col.replace('Tag: ', ''),
                data: data.map((d, j) => (yearTotals[j] > 0 ? (Math.abs(d[col] || 0) / yearTotals[j]) * 100 : 0)),
                backgroundColor: color + '80',
                borderColor: color,
                borderWidth: 1,
            };
        });

        state.charts.tagSpending = new Chart(ctx, {
            type: 'bar',
            data: { labels: years, datasets },
            options: {
                ...getCommonChartOptions('Share of Spending (%)', true),
                scales: {
                    ...getCommonChartOptions('Share of Spending (%)', true).scales,
                    x: {
                        ...getCommonChartOptions('Share of Spending (%)', true).scales.x,
                        stacked: true,
                    },
                    y: {
                        ...getCommonChartOptions('Share of Spending (%)', true).scales.y,
                        stacked: true,
                        max: 100,
                        ticks: {
                            ...getCommonChartOptions('Share of Spending (%)', true).scales.y.ticks,
                            callback: (value) => value + '%',
                        },
                    },
                },
                plugins: {
                    ...getCommonChartOptions('Share of Spending (%)', true).plugins,
                    legend: { position: 'right', labels: { font: { size: 10 } } },
                    tooltip: {
                        ...getCommonChartOptions('Share of Spending (%)', true).plugins.tooltip,
                        callbacks: {
                            label: (context) => {
                                return `${context.dataset.label}: ${context.parsed.y.toFixed(1)}%`;
                            },
                        },
                    },
                },
                interaction: { mode: 'index', intersect: false },
            },
        });
        enableLegendHoverHighlight(state.charts.tagSpending);
    } else {
        // Stacked area over time
        const datasets = [];
        for (let i = 0; i < tagColumns.length; i++) {
            const col = tagColumns[i];
            const tagName = col.replace('Tag: ', '');
            const values = data.map(d => Math.abs(d[col] || 0));
            const total = values.reduce((a, b) => a + b, 0);
            if (total > 1000) { // Only show significant tags
                const color = CHART_COLORS[datasets.length % CHART_COLORS.length];
                const idx = datasets.length;
                datasets.push({
                    label: tagName,
                    data: values,
                    backgroundColor: color + '80',
                    borderColor: color,
                    borderWidth: 1,
                    // First dataset fills to zero; the rest fill to the previous
                    // dataset so each category only covers its own stack band.
                    fill: idx === 0 ? 'origin' : '-1',
                });
            }
        }

        state.charts.tagSpending = new Chart(ctx, {
            type: 'line',
            data: { labels: years, datasets },
            options: {
                ...getCommonChartOptions('Spending ($)'),
                scales: {
                    ...getCommonChartOptions('Spending ($)').scales,
                    y: {
                        ...getCommonChartOptions('Spending ($)').scales.y,
                        stacked: true,
                        title: { display: true, text: 'Spending ($)' },
                    },
                },
                plugins: {
                    ...getCommonChartOptions('Spending ($)').plugins,
                    legend: { position: 'right', labels: { font: { size: 10 } } },
                },
                interaction: { mode: 'index', intersect: false },
            },
        });
        enableLegendHoverHighlight(state.charts.tagSpending);
    }
}

function _lerpColor(hexA, hexB, t) {
    const parse = (h) => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
    const a = parse(hexA);
    const b = parse(hexB);
    const c = a.map((v, i) => Math.round(v + (b[i] - v) * t));
    return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

function _niceTicks(max, count) {
    if (max <= 0) return [0];
    const roughStep = max / count;
    const magnitude = Math.pow(10, Math.floor(Math.log10(roughStep)));
    const norm = roughStep / magnitude;
    const step = (norm < 1.5 ? 1 : norm < 3.5 ? 2 : norm < 7.5 ? 5 : 10) * magnitude;
    const ticks = [];
    for (let v = 0; v <= max; v += step) ticks.push(v);
    return ticks;
}

function _distToSegment(px, py, x1, y1, x2, y2) {
    const dx = x2 - x1;
    const dy = y2 - y1;
    const lenSq = dx * dx + dy * dy;
    if (lenSq === 0) return Math.hypot(px - x1, py - y1);
    let t = ((px - x1) * dx + (py - y1) * dy) / lenSq;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

function renderTagParallelCoordinates(canvas) {
    const data = state.simulationData;
    if (!data || data.length === 0) return;

    const allTagColumns = state.simulationColumns.filter(c => c.startsWith('Tag: '));
    // Keep only significant tags so near-zero axes don't clutter the plot
    const tagColumns = allTagColumns.filter(col => {
        const total = data.reduce((sum, d) => sum + Math.abs(d[col] || 0), 0);
        return total > 1000;
    });
    if (tagColumns.length < 2) return;

    const ctx = canvas.getContext('2d');
    // Chart.js destroy() resets the canvas to its default 300x150, so size it
    // explicitly to fill its container before measuring.
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, rect.width, rect.height);

    const css = getComputedStyle(document.documentElement);
    const textColor = css.getPropertyValue('--text-muted').trim() || '#8b93a7';
    const textPrimary = css.getPropertyValue('--text-primary').trim() || '#1f2430';
    const gridColor = css.getPropertyValue('--gridline').trim() || '#e5e7eb';
    const surfaceColor = css.getPropertyValue('--surface-elevated').trim() || '#ffffff';
    const borderColor = css.getPropertyValue('--border').trim() || gridColor;
    const fontFamily = 'system-ui, -apple-system, "Segoe UI", sans-serif';

    const years = data.map(d => d.Year);
    const n = tagColumns.length;
    const nYears = data.length;

    const pad = { top: 64, right: 24, bottom: 48, left: 78 };
    const plotW = rect.width - pad.left - pad.right;
    const plotH = rect.height - pad.top - pad.bottom;

    // Absolute spending per category (consistent with the stacked chart)
    const values = tagColumns.map(col => data.map(d => Math.abs(d[col] || 0)));
    // Independent scale per axis so each category uses its full plot height
    const axisMax = values.map(v => Math.max(...v, 1));

    const xFor = i => pad.left + (i * plotW) / (n - 1);
    const yFor = (i, v) => pad.top + plotH - (v / axisMax[i]) * plotH;

    // Precompute one polyline per year
    const paths = years.map((_, j) => tagColumns.map((_, i) => ({ x: xFor(i), y: yFor(i, values[i][j]) })));

    const colorForYear = j => _lerpColor(CHART_COLORS[0], CHART_COLORS[7], nYears <= 1 ? 0 : j / (nYears - 1));

    let hoverIndex = null;
    let mouse = { x: 0, y: 0 };

    function drawPlot() {
        ctx.clearRect(0, 0, rect.width, rect.height);

        // Vertical axes with per-axis ticks + value labels + rotated category labels
        for (let i = 0; i < n; i++) {
            const x = xFor(i);
            ctx.strokeStyle = gridColor;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(x, pad.top);
            ctx.lineTo(x, pad.top + plotH);
            ctx.stroke();

            ctx.font = `10px ${fontFamily}`;
            ctx.fillStyle = textColor;
            ctx.textAlign = 'right';
            for (const t of _niceTicks(axisMax[i], 3)) {
                const y = yFor(i, t);
                ctx.beginPath();
                ctx.moveTo(x - 4, y);
                ctx.lineTo(x + 4, y);
                ctx.stroke();
                ctx.fillText(formatCurrency(t), x - 7, y + 3);
            }

            ctx.save();
            ctx.translate(x, pad.top - 10);
            ctx.rotate(-Math.PI / 6);
            ctx.fillStyle = textPrimary;
            ctx.font = `600 10px ${fontFamily}`;
            ctx.textAlign = 'right';
            ctx.fillText(tagColumns[i].replace('Tag: ', ''), 0, 0);
            ctx.restore();
        }

        // One polyline per year, colored by year (blue -> red)
        for (let j = 0; j < nYears; j++) {
            const isHover = j === hoverIndex;
            ctx.strokeStyle = colorForYear(j);
            ctx.globalAlpha = isHover ? 1 : 0.55;
            ctx.lineWidth = isHover ? 2.5 : 1.2;
            ctx.beginPath();
            paths[j].forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
            ctx.stroke();
        }
        ctx.globalAlpha = 1;

        // Year color legend
        const legendW = 220;
        const legendX = pad.left + (plotW - legendW) / 2;
        const legendY = rect.height - 32;
        const grad = ctx.createLinearGradient(legendX, 0, legendX + legendW, 0);
        for (let j = 0; j < nYears; j++) {
            grad.addColorStop(nYears <= 1 ? 0 : j / (nYears - 1), colorForYear(j));
        }
        ctx.fillStyle = grad;
        ctx.fillRect(legendX, legendY, legendW, 5);
        ctx.strokeStyle = gridColor;
        ctx.strokeRect(legendX, legendY, legendW, 5);
        ctx.fillStyle = textColor;
        ctx.font = `10px ${fontFamily}`;
        ctx.textAlign = 'left';
        ctx.fillText(String(years[0]), legendX, legendY + 16);
        ctx.textAlign = 'right';
        ctx.fillText(String(years[nYears - 1]), legendX + legendW, legendY + 16);

        if (hoverIndex !== null) {
            // Tooltip with the hovered year's values
            const lines = [`Year: ${years[hoverIndex]}`];
            for (let i = 0; i < n; i++) {
                lines.push(`${tagColumns[i].replace('Tag: ', '')}: ${formatCurrency(values[i][hoverIndex])}`);
            }
            ctx.font = `10px ${fontFamily}`;
            const lineHeight = 14;
            const width = Math.max(...lines.map(l => ctx.measureText(l).width)) + 16;
            const height = lines.length * lineHeight + 10;
            let bx = mouse.x + 12;
            let by = mouse.y + 12;
            if (bx + width > rect.width - 8) bx = mouse.x - width - 12;
            if (by + height > rect.height - 8) by = mouse.y - height - 12;
            ctx.fillStyle = surfaceColor;
            ctx.strokeStyle = borderColor;
            ctx.beginPath();
            ctx.rect(bx, by, width, height);
            ctx.fill();
            ctx.stroke();
            ctx.fillStyle = textPrimary;
            ctx.textAlign = 'left';
            lines.forEach((l, i) => ctx.fillText(l, bx + 8, by + 14 + i * lineHeight));
        }
    }

    function onMove(e) {
        const bounds = canvas.getBoundingClientRect();
        mouse = { x: e.clientX - bounds.left, y: e.clientY - bounds.top };
        let best = null;
        let bestDist = 40;
        for (let j = 0; j < nYears; j++) {
            for (let i = 0; i < n - 1; i++) {
                const d = _distToSegment(mouse.x, mouse.y, paths[j][i].x, paths[j][i].y, paths[j][i + 1].x, paths[j][i + 1].y);
                if (d < bestDist) {
                    bestDist = d;
                    best = j;
                }
            }
        }
        hoverIndex = best;
        drawPlot();
    }

    function onLeave() {
        hoverIndex = null;
        drawPlot();
    }

    canvas._parallelCleanup = () => {
        canvas.removeEventListener('mousemove', onMove);
        canvas.removeEventListener('mouseleave', onLeave);
    };
    canvas.addEventListener('mousemove', onMove);
    canvas.addEventListener('mouseleave', onLeave);
    drawPlot();
}

function renderDebtChart() {
    const ctx = document.getElementById('debtChart').getContext('2d');
    destroyChart('debt');

    const data = state.simulationData;
    const years = data.map(d => d.Year);
    const debtColumns = state.simulationColumns.filter(c => c.startsWith('Debt: '));

    const datasets = [];
    for (let i = 0; i < debtColumns.length; i++) {
        const col = debtColumns[i];
        const values = data.map(d => d[col] || 0);
        const maxVal = Math.max(...values);
        if (maxVal > 0) {
            datasets.push({
                label: col.replace('Debt: ', ''),
                data: values,
                borderColor: CHART_COLORS[i % CHART_COLORS.length],
                backgroundColor: CHART_COLORS[i % CHART_COLORS.length] + '20',
                fill: true,
                tension: 0.3,
                pointRadius: 0,
                pointHoverRadius: 5,
                borderWidth: 2,
            });
        }
    }

    if (datasets.length === 0) {
        ctx.font = '14px system-ui';
        ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--text-muted').trim();
        ctx.textAlign = 'center';
        ctx.fillText('No debt data', ctx.canvas.width / 2, ctx.canvas.height / 2);
        return;
    }

    state.charts.debt = new Chart(ctx, {
        type: 'line',
        data: { labels: years, datasets },
        options: getCommonChartOptions('Debt Balance ($)'),
    });
}

function renderTaxChart() {
    const ctx = document.getElementById('taxChart').getContext('2d');
    destroyChart('tax');

    const data = state.simulationData;
    const years = data.map(d => d.Year);
    const federalTax = data.map(d => Math.abs(d['Federal Tax'] || 0));
    const taxableIncome = data.map(d => d['Tax: Taxable Income'] || 0);
    const agi = data.map(d => d['AGI'] || 0);

    state.charts.tax = new Chart(ctx, {
        type: 'line',
        data: {
            labels: years,
            datasets: [
                {
                    label: 'Federal Tax',
                    data: federalTax,
                    borderColor: CHART_COLORS[7],
                    backgroundColor: createGradient(ctx, CHART_COLORS[7]),
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    borderWidth: 2,
                    yAxisID: 'y',
                },
                {
                    label: 'Taxable Income',
                    data: taxableIncome,
                    borderColor: CHART_COLORS[3],
                    backgroundColor: 'transparent',
                    fill: false,
                    tension: 0.3,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    borderWidth: 1.5,
                    borderDash: [5, 5],
                    yAxisID: 'y1',
                },
            ],
        },
        options: {
            ...getCommonChartOptions(),
            scales: {
                x: getCommonChartOptions().scales.x,
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    title: { display: true, text: 'Federal Tax ($)' },
                    grid: { color: getComputedStyle(document.documentElement).getPropertyValue('--gridline').trim(), drawBorder: false },
                    ticks: { color: getComputedStyle(document.documentElement).getPropertyValue('--text-muted').trim(), callback: v => formatCurrency(v) },
                },
                y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    title: { display: true, text: 'Taxable Income ($)' },
                    grid: { drawOnChartArea: false },
                    ticks: { color: getComputedStyle(document.documentElement).getPropertyValue('--text-muted').trim(), callback: v => formatCurrency(v) },
                },
            },
            plugins: {
                ...getCommonChartOptions().plugins,
                tooltip: {
                    ...getCommonChartOptions().plugins.tooltip,
                    callbacks: {
                        label: (context) => {
                            return `${context.dataset.label}: ${formatCurrency(context.parsed.y)}`;
                        },
                    },
                },
            },
        },
    });
}

function renderAccountBalancesChart() {
    const ctx = document.getElementById('accountBalancesChart').getContext('2d');
    destroyChart('accountBalances');

    const data = state.simulationData;
    const years = data.map(d => d.Year);
    const accountColumns = state.simulationColumns.filter(c => c.startsWith('Account: '));

    const datasets = [];
    for (let i = 0; i < accountColumns.length; i++) {
        const col = accountColumns[i];
        const values = data.map(d => d[col] || 0);
        const maxVal = Math.max(...values);
        if (maxVal > 0) {
            datasets.push({
                label: col.replace('Account: ', ''),
                data: values,
                borderColor: CHART_COLORS[i % CHART_COLORS.length],
                backgroundColor: createGradient(ctx, CHART_COLORS[i % CHART_COLORS.length]),
                fill: true,
                tension: 0.3,
                pointRadius: 0,
                pointHoverRadius: 5,
                borderWidth: 2,
            });
        }
    }

    if (datasets.length === 0) {
        ctx.font = '14px system-ui';
        ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--text-muted').trim();
        ctx.textAlign = 'center';
        ctx.fillText('No account data', ctx.canvas.width / 2, ctx.canvas.height / 2);
        return;
    }

    state.charts.accountBalances = new Chart(ctx, {
        type: 'line',
        data: { labels: years, datasets },
        options: getCommonChartOptions('Account Balance ($)'),
    });
}

function getCommonChartOptions(yAxisTitle = '', includeYAxisTitle = false) {
    const textColor = getComputedStyle(document.documentElement).getPropertyValue('--text-muted').trim();
    const gridColor = getComputedStyle(document.documentElement).getPropertyValue('--gridline').trim();
    const fontFamily = 'system-ui, -apple-system, "Segoe UI", sans-serif';

    return {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
            legend: {
                display: true,
                position: 'top',
                align: 'start',
                labels: {
                    usePointStyle: true,
                    pointStyle: 'line',
                    padding: 16,
                    font: { family: fontFamily, size: 11, weight: '500' },
                    color: textColor,
                },
            },
            tooltip: {
                backgroundColor: getComputedStyle(document.documentElement).getPropertyValue('--surface-elevated').trim(),
                titleColor: getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim(),
                bodyColor: getComputedStyle(document.documentElement).getPropertyValue('--text-secondary').trim(),
                borderColor: getComputedStyle(document.documentElement).getPropertyValue('--border').trim(),
                borderWidth: 1,
                padding: 12,
                cornerRadius: 8,
                displayColors: true,
                usePointStyle: true,
                callbacks: {
                    label: (context) => {
                        return `${context.dataset.label}: ${formatCurrency(context.parsed.y)}`;
                    },
                    title: (items) => `Year: ${items[0].label}`,
                },
            },
        },
        scales: {
            x: {
                grid: { color: gridColor, drawBorder: false },
                ticks: { color: textColor, maxTicksLimit: 12, font: { family: fontFamily, size: 10 } },
            },
            y: {
                grid: { color: gridColor, drawBorder: false },
                ticks: {
                    color: textColor,
                    font: { family: fontFamily, size: 10 },
                    callback: (value) => formatCurrency(value),
                },
                title: includeYAxisTitle ? { display: true, text: yAxisTitle, color: textColor, font: { family: fontFamily, size: 11, weight: '500' } } : { display: false },
            },
        },
        elements: {
            point: { hoverRadius: 6, hitRadius: 24 },
            line: { tension: 0.3 },
        },
    };
}

function renderParallelCoordChart() {
    const canvas = document.getElementById('parallelCoordChart');
    if (!canvas) return;
    renderTagParallelCoordinates(canvas);
}

function renderAllCharts() {
    renderNetWorthChart();
    renderCashFlowChart();
    renderIncomeExpenseChart();
    renderAssetAllocationChart();
    renderTagSpendingChart();
    renderParallelCoordChart();
    renderDebtChart();
    renderTaxChart();
    renderAccountBalancesChart();
}

// ============================================================================
// Summary Cards
// ============================================================================

function renderSummaryCards() {
    const summary = state.simulationSummary;
    if (!summary) return;

    document.getElementById('totalIncome').textContent = formatCurrency(summary.total_income);
    document.getElementById('totalExpenses').textContent = formatCurrency(summary.total_expenses ?? 0);
    document.getElementById('finalNetWorth').textContent = formatCurrency(summary.final_net_worth);
    document.getElementById('peakNetWorth').textContent = formatCurrency(summary.peak_net_worth);
    document.getElementById('netCashFlow').textContent = formatCurrency(summary.total_cash_flow);
    document.getElementById('totalTax').textContent = formatCurrency(summary.total_tax);
}

// ============================================================================
// Data Table
// ============================================================================

function renderDataTable() {
    const data = state.simulationData;
    const columns = state.simulationColumns;
    if (!data || !columns) return;

    const table = document.getElementById('dataTable');
    const thead = table.querySelector('thead');
    const tbody = table.querySelector('tbody');

    // Header
    thead.innerHTML = `
        <tr>
            <th>Year</th>
            ${columns.map(col => `<th>${escapeHtml(col)}</th>`).join('')}
        </tr>
    `;

    // Body - show all years
    const displayData = data; // Show all years
    tbody.innerHTML = displayData.map(row => `
        <tr>
            <td style="font-weight: 600;">${row.Year}</td>
            ${columns.map(col => {
                const val = row[col];
                if (typeof val === 'number') {
                    const formatted = formatCurrency(val, 2);
                    const cls = val > 0 ? 'positive' : (val < 0 ? 'negative' : '');
                    return `<td class="${cls}">${formatted}</td>`;
                }
                return `<td>${escapeHtml(String(val ?? ''))}</td>`;
            }).join('')}
        </tr>
    `).join('');

    document.getElementById('tableCard').style.display = 'block';
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function filterTable() {
    const searchTerm = document.getElementById('tableSearch').value.toLowerCase();
    const rows = document.querySelectorAll('#dataTable tbody tr');

    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(searchTerm) ? '' : 'none';
    });
}

function downloadTable() {
    const data = state.simulationData;
    const columns = state.simulationColumns;
    if (!data) return;

    const headers = ['Year', ...columns];
    const rows = data.map(row => [row.Year, ...columns.map(c => row[c] ?? '')]);

    const csv = [headers.join(','), ...rows.map(r => r.map(v => `"${v}"`).join(','))].join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${state.currentScenario}-full-data.csv`;
    a.click();
    URL.revokeObjectURL(url);
}

// ============================================================================
// Theme Management
// ============================================================================

function initTheme() {
    const savedTheme = localStorage.getItem('theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    state.theme = savedTheme || (prefersDark ? 'dark' : 'light');
    applyTheme(state.theme);
}

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);

    // Update chart colors
    for (const chart of Object.values(state.charts)) {
        chart.update('none'); // Trigger re-render with new CSS variables
    }
    renderParallelCoordChart();
}

function toggleTheme() {
    state.theme = state.theme === 'light' ? 'dark' : 'light';
    applyTheme(state.theme);
}

// ============================================================================
// Event Listeners
// ============================================================================

function setupEventListeners() {
    // Scenario selector
    document.getElementById('scenarioSelect').addEventListener('change', (e) => {
        loadScenario(e.target.value);
    });

    // Year inputs
    document.getElementById('startYear').addEventListener('change', debounce(() => {
        runSimulationWithCurrentParams();
    }, 500));

    document.getElementById('endYear').addEventListener('change', debounce(() => {
        runSimulationWithCurrentParams();
    }, 500));

    // Parameter search/filter
    document.getElementById('paramSearch').addEventListener('input', debounce(renderParameters, 300));
    document.getElementById('categoryFilter').addEventListener('change', renderParameters);

    // Parameter actions
    document.getElementById('resetParamsBtn').addEventListener('click', resetAllParameters);
    document.getElementById('applyParamsBtn').addEventListener('click', applyParameterChanges);

    // Chart type selectors
    document.getElementById('netWorthChartType').addEventListener('change', renderNetWorthChart);
    document.getElementById('cashFlowChartType').addEventListener('change', renderCashFlowChart);
    document.getElementById('tagChartYear').addEventListener('change', renderTagSpendingChart);

    // Export
    document.getElementById('exportCsvBtn').addEventListener('click', () => {
        if (state.currentScenario) exportCsv(state.currentScenario);
    });

    document.getElementById('downloadTableBtn').addEventListener('click', downloadTable);

    // Table search
    document.getElementById('tableSearch').addEventListener('input', filterTable);

    // Theme toggle
    document.getElementById('themeToggle').addEventListener('click', toggleTheme);

    // Run simulation button
    document.getElementById('runSimulationBtn').addEventListener('click', runSimulationWithCurrentParams);

    // Today's dollars toggle - re-run immediately with the new flag
    document.getElementById('realDollarsToggle').addEventListener('change', (e) => {
        state.realDollars = e.target.checked;
        runSimulationWithCurrentParams();
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.ctrlKey || e.metaKey) {
            if (e.key === 'Enter') {
                e.preventDefault();
                runSimulationWithCurrentParams();
            } else if (e.key === 's') {
                e.preventDefault();
                if (state.currentScenario) exportCsv(state.currentScenario);
            }
        }
        if (e.key === 'Escape') {
            // Close modal if open
            document.getElementById('paramModal').classList.remove('open');
        }
    });

    // Window resize - update charts
    window.addEventListener('resize', debounce(() => {
        for (const chart of Object.values(state.charts)) {
            chart.resize();
        }
        renderParallelCoordChart();
    }, 250));
}

// ============================================================================
// Initialization
// ============================================================================

async function init() {
    console.log('[Dashboard] Initializing...');
    initTheme();
    setupEventListeners();

    // Wait for Chart.js to be available
    if (typeof Chart === 'undefined') {
        console.log('[Dashboard] Waiting for Chart.js...');
        await new Promise(resolve => {
            const checkChart = setInterval(() => {
                if (typeof Chart !== 'undefined') {
                    clearInterval(checkChart);
                    console.log('[Dashboard] Chart.js loaded');
                    resolve();
                }
            }, 50);
        });
    } else {
        console.log('[Dashboard] Chart.js already available');
    }

    try {
        await loadScenarios();
        console.log('[Dashboard] Initialization complete');
    } catch (error) {
        console.error('[Dashboard] Initialization failed:', error);
        showToast('Failed to initialize: ' + error.message, 'error');
    }
}

// ============================================================================
// Chart.js Availability Check
// ============================================================================

console.log('[Dashboard] Script loaded, Chart.js available:', typeof Chart !== 'undefined');

// Simple test to verify Chart.js works
if (typeof Chart !== 'undefined') {
    console.log('[Dashboard] Chart.js version:', Chart.version);
}

// Start the app - handle case where DOMContentAlready fired
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    console.log('[Dashboard] DOM already ready, initializing immediately');
    init();
}
