/**
 * CommDecode - Main Application Controller
 * Orchestrates the bit group detection tool
 */

const App = {
    // State
    mode: 'simple', // 'simple' or 'window'
    inputFormat: 'pairs', // 'pairs' or 'json'
    simpleExamples: {},
    windowExamples: {},
    currentExample: null,
    isLoading: false,

    // JSON Placeholder templates
    jsonPlaceholders: {
        simple: `{"trials": [
  {"reference_value": 25.5, "payload": "A1B2C3D4E5F6"},
  {"reference_value": 30.2, "payload": "A1B3C4D5E6F7"},
  {"reference_value": 28.8, "payload": "A1B2C3D4E5F8"}
]}`,
        window: `{"trials": [
  {"reference_value": 25.5, "messages": [
    {"timestamp": 0.001, "message_id": "0x123", "payload": "A1B2C3D4"},
    {"timestamp": 0.015, "message_id": "0x456", "payload": "FF00EE11"}
  ]},
  {"reference_value": 30.2, "messages": [
    {"timestamp": 0.002, "message_id": "0x123", "payload": "B2C3D4E5"},
    {"timestamp": 0.018, "message_id": "0x456", "payload": "EE11FF00"}
  ]}
]}`
    },

    jsonHelpTexts: {
        simple: 'Each trial contains a reference_value and a payload (hex format).',
        window: 'Each trial contains a reference_value and an array of messages with timestamp, message_id, and payload.'
    },

    /**
     * Initialize the application
     */
    async init() {
        console.log('CommDecode initializing...');

        // Bind event handlers
        this.bindEvents();

        // Load examples from backend
        await this.loadExamples();

        // Set initial input visibility
        this.updateInputVisibility();

        console.log('CommDecode ready');
    },

    /**
     * Bind DOM event handlers
     */
    bindEvents() {
        // Mode toggle buttons
        document.getElementById('mode-simple').addEventListener('click', () => {
            this.setMode('simple');
        });
        document.getElementById('mode-window').addEventListener('click', () => {
            this.setMode('window');
        });

        // Format toggle buttons
        document.getElementById('format-pairs').addEventListener('click', () => {
            this.setInputFormat('pairs');
        });
        document.getElementById('format-json').addEventListener('click', () => {
            this.setInputFormat('json');
        });

        // Example selector
        document.getElementById('example-select').addEventListener('change', (e) => {
            this.onExampleSelect(e.target.value);
        });

        // Validate button
        document.getElementById('validate-btn').addEventListener('click', () => {
            this.onValidate();
        });

        // Decode button
        document.getElementById('decode-btn').addEventListener('click', () => {
            this.onDecode();
        });

        // Clear validation messages when input changes
        document.getElementById('input-data').addEventListener('input', () => {
            this.clearValidation();
        });
        document.getElementById('reference-values').addEventListener('input', () => {
            this.clearValidation();
        });
        document.getElementById('payloads').addEventListener('input', () => {
            this.clearValidation();
        });
        document.getElementById('window-trials').addEventListener('input', () => {
            this.clearValidation();
        });
    },

    /**
     * Set the input format (pairs or json)
     */
    setInputFormat(format) {
        // Convert current data before switching
        this.convertDataBetweenFormats(this.inputFormat, format);

        this.inputFormat = format;

        // Update UI
        document.getElementById('format-pairs').classList.toggle('active', format === 'pairs');
        document.getElementById('format-json').classList.toggle('active', format === 'json');

        this.updateInputVisibility();
    },

    /**
     * Update which input fields are visible based on mode and format
     */
    updateInputVisibility() {
        const pairsSimple = document.getElementById('pairs-input-simple');
        const pairsWindow = document.getElementById('pairs-input-window');
        const jsonInput = document.getElementById('json-input');

        // Hide all first
        pairsSimple.classList.add('hidden');
        pairsWindow.classList.add('hidden');
        jsonInput.classList.add('hidden');

        if (this.inputFormat === 'json') {
            jsonInput.classList.remove('hidden');
            // Update JSON placeholder based on mode
            const inputData = document.getElementById('input-data');
            const inputHelp = document.getElementById('input-help');
            inputData.placeholder = this.jsonPlaceholders[this.mode];
            inputHelp.textContent = this.jsonHelpTexts[this.mode];
        } else {
            // Pairs format
            if (this.mode === 'simple') {
                pairsSimple.classList.remove('hidden');
            } else {
                pairsWindow.classList.remove('hidden');
            }
        }
    },

    /**
     * Convert data between formats when switching
     */
    convertDataBetweenFormats(fromFormat, toFormat) {
        if (fromFormat === toFormat) return;

        try {
            if (fromFormat === 'pairs' && toFormat === 'json') {
                // Convert pairs to JSON
                const data = this.getPairsInputData();
                if (data && data.trials && data.trials.length > 0) {
                    document.getElementById('input-data').value = JSON.stringify(data, null, 2);
                }
            } else if (fromFormat === 'json' && toFormat === 'pairs') {
                // Convert JSON to pairs
                const jsonText = document.getElementById('input-data').value.trim();
                if (jsonText) {
                    const data = JSON.parse(jsonText);
                    if (data.trials && data.trials.length > 0) {
                        if (this.mode === 'simple') {
                            const refs = data.trials.map(t => t.reference_value).join('\n');
                            const payloads = data.trials.map(t => t.payload || '').join('\n');
                            document.getElementById('reference-values').value = refs;
                            document.getElementById('payloads').value = payloads;
                        } else {
                            // Window mode - convert to CSV format
                            const lines = [];
                            data.trials.forEach((trial, idx) => {
                                if (idx > 0) lines.push(''); // Empty line to separate trials
                                (trial.messages || []).forEach(msg => {
                                    lines.push(`${trial.reference_value}, ${msg.timestamp}, ${msg.message_id}, ${msg.payload}`);
                                });
                            });
                            document.getElementById('window-trials').value = lines.join('\n');
                        }
                    }
                }
            }
        } catch (e) {
            // Conversion failed, leave fields as-is
            console.log('Format conversion failed:', e);
        }
    },

    /**
     * Set the decoding mode
     */
    setMode(mode) {
        this.mode = mode;

        // Update UI
        document.getElementById('mode-simple').classList.toggle('active', mode === 'simple');
        document.getElementById('mode-window').classList.toggle('active', mode === 'window');

        // Update mode description
        const desc = document.getElementById('mode-description');
        if (mode === 'simple') {
            desc.textContent = 'Simple mode: One payload per reference value';
        } else {
            desc.textContent = 'Window mode: Multiple messages captured per reference value (realistic scenario)';
        }

        // Update input visibility
        this.updateInputVisibility();

        // Reload examples for the new mode
        this.populateExampleSelector();

        // Clear current example and results
        document.getElementById('example-select').value = '';
        document.getElementById('example-description').textContent = '';
        this.clearAllInputs();
        this.clearResults();
        this.clearValidation();
        Visualization.toggleGroundTruth(false);
    },

    /**
     * Clear all input fields
     */
    clearAllInputs() {
        document.getElementById('reference-values').value = '';
        document.getElementById('payloads').value = '';
        document.getElementById('window-trials').value = '';
        document.getElementById('input-data').value = '';
    },

    /**
     * Load examples from the backend
     */
    async loadExamples() {
        try {
            // Load simple examples
            const simpleData = await API.getExamples();
            if (simpleData.examples) {
                this.simpleExamples = simpleData.examples.reduce((acc, ex) => {
                    acc[ex.id] = ex;
                    return acc;
                }, {});
            }

            // Load window examples
            const windowData = await API.getWindowExamples();
            if (windowData.examples) {
                this.windowExamples = windowData.examples.reduce((acc, ex) => {
                    acc[ex.id] = ex;
                    return acc;
                }, {});
            }

            // Populate selector for current mode
            this.populateExampleSelector();

        } catch (error) {
            console.error('Failed to load examples:', error);
            this.showStatus('Failed to connect to backend. Make sure the server is running.', 'error');
        }
    },

    /**
     * Populate the example selector based on current mode
     */
    populateExampleSelector() {
        const select = document.getElementById('example-select');
        const examples = this.mode === 'simple' ? this.simpleExamples : this.windowExamples;

        // Group examples by domain
        const byDomain = {
            automotive: [],
            industrial: [],
            iot: []
        };

        Object.values(examples).forEach(example => {
            const domain = example.domain.toLowerCase();
            if (byDomain[domain]) {
                byDomain[domain].push(example);
            }
        });

        // Populate select element
        Object.entries(byDomain).forEach(([domain, domainExamples]) => {
            const optgroup = select.querySelector(`optgroup[label="${this.capitalizeFirst(domain)}"]`);
            if (optgroup) {
                optgroup.innerHTML = '';
                domainExamples.forEach(example => {
                    const option = document.createElement('option');
                    option.value = example.id;
                    option.textContent = example.name;
                    if (this.mode === 'window' && example.total_messages) {
                        option.textContent += ` (${example.n_trials} trials, ${example.total_messages} msgs)`;
                    }
                    optgroup.appendChild(option);
                });
            }
        });
    },

    /**
     * Handle example selection
     */
    async onExampleSelect(exampleId) {
        if (!exampleId) {
            this.currentExample = null;
            document.getElementById('example-description').textContent = '';
            this.clearAllInputs();
            Visualization.toggleGroundTruth(false);
            return;
        }

        try {
            this.setLoading(true);

            let example;
            if (this.mode === 'simple') {
                example = await API.getExample(exampleId);
            } else {
                example = await API.getWindowExample(exampleId);
            }

            this.currentExample = example;

            // Update description
            document.getElementById('example-description').textContent =
                `${example.description} (${example.unit})`;

            // Populate input fields based on current format
            if (this.inputFormat === 'pairs') {
                if (this.mode === 'simple') {
                    document.getElementById('reference-values').value =
                        example.reference_values.join('\n');
                    document.getElementById('payloads').value =
                        example.payloads.join('\n');
                } else {
                    // Window mode - convert to CSV format
                    const lines = [];
                    example.trials.forEach((trial, idx) => {
                        if (idx > 0) lines.push(''); // Empty line to separate trials
                        (trial.messages || []).forEach(msg => {
                            lines.push(`${trial.reference_value}, ${msg.timestamp}, ${msg.message_id}, ${msg.payload}`);
                        });
                    });
                    document.getElementById('window-trials').value = lines.join('\n');
                }
            } else {
                // JSON format
                let jsonData;
                if (this.mode === 'simple') {
                    const trials = example.reference_values.map((ref, idx) => ({
                        reference_value: ref,
                        payload: example.payloads[idx]
                    }));
                    jsonData = { trials };
                } else {
                    jsonData = { trials: example.trials };
                }
                document.getElementById('input-data').value = JSON.stringify(jsonData, null, 2);
            }

            // Clear previous results
            this.clearResults();
            this.clearValidation();

            // Show ground truth
            Visualization.renderGroundTruth(example.ground_truth, document.getElementById('ground-truth-content'));
            Visualization.toggleGroundTruth(true);

        } catch (error) {
            console.error('Failed to load example:', error);
            this.showValidation(['Failed to load example data'], 'error');
        } finally {
            this.setLoading(false);
        }
    },

    /**
     * Handle validate button click
     */
    async onValidate() {
        const data = this.getInputData();
        if (!data) return;

        const errors = [];
        const warnings = [];

        if (!data.trials || data.trials.length === 0) {
            errors.push('No trials provided');
        } else if (data.trials.length < 3) {
            errors.push('At least 3 trials required');
        } else if (data.trials.length < 5) {
            warnings.push('Consider using at least 5 trials for better accuracy');
        }

        if (this.mode === 'simple') {
            // Validate simple mode structure
            data.trials.forEach((trial, idx) => {
                if (trial.reference_value === undefined || trial.reference_value === null) {
                    errors.push(`Trial ${idx + 1} missing reference_value`);
                }
                if (!trial.payload) {
                    errors.push(`Trial ${idx + 1} missing payload`);
                }
            });
        } else {
            // Validate window mode structure
            let totalMessages = 0;
            let messageIds = new Set();
            data.trials.forEach((trial, idx) => {
                if (trial.reference_value === undefined || trial.reference_value === null) {
                    errors.push(`Trial ${idx + 1} missing reference_value`);
                }
                if (!trial.messages || trial.messages.length === 0) {
                    errors.push(`Trial ${idx + 1} has no messages`);
                } else {
                    totalMessages += trial.messages.length;
                    trial.messages.forEach(m => messageIds.add(m.message_id));
                }
            });

            if (errors.length === 0 && this.mode === 'window') {
                this.showValidation(
                    [`Valid input: ${data.trials.length} trials, ${totalMessages} messages, ${messageIds.size} message types`],
                    'success'
                );
                if (warnings.length > 0) {
                    this.showValidation(warnings, 'warning');
                }
                return;
            }
        }

        if (errors.length > 0) {
            this.showValidation(errors, 'error');
        } else {
            this.showValidation(
                [`Valid input: ${data.trials.length} trials`],
                'success'
            );
            if (warnings.length > 0) {
                this.showValidation(warnings, 'warning');
            }
        }
    },

    /**
     * Handle decode button click
     */
    async onDecode() {
        const data = this.getInputData();
        if (!data) return;

        data.settings = this.getSettings();

        try {
            this.setLoading(true);
            this.showStatus('Analyzing payloads...', 'loading');

            let result;
            if (this.mode === 'simple') {
                result = await API.decode(data);
            } else {
                result = await API.decodeWindow(data);
            }

            if (result.success) {
                this.displayResults(result);
            } else {
                this.showValidation([result.error], 'error');
                this.showStatus('Decoding failed. Check your input data.', 'error');
            }
        } catch (error) {
            console.error('Decoding failed:', error);
            this.showValidation([error.message], 'error');
            this.showStatus('Decoding failed. Check your input data.', 'error');
        } finally {
            this.setLoading(false);
        }
    },

    /**
     * Get settings from form
     */
    getSettings() {
        return {
            correlation_threshold: parseFloat(document.getElementById('correlation-threshold').value) || 0.8,
            mape_threshold: parseFloat(document.getElementById('mape-threshold').value) || 5.0,
            top_n: parseInt(document.getElementById('top-n').value) || 10
        };
    },

    /**
     * Display decoding results
     */
    displayResults(result) {
        const isWindowMode = this.mode === 'window';

        // Update summary
        document.getElementById('summary-trials').textContent = result.n_trials || '-';
        if (isWindowMode) {
            document.getElementById('summary-bits').textContent =
                result.n_message_types ? `${result.n_message_types} msg types` : '-';
        } else {
            document.getElementById('summary-bits').textContent =
                result.payload_length_bits ? `${result.payload_length_bits} bits` : '-';
        }
        document.getElementById('summary-candidates').textContent = result.n_candidates ?? '-';

        // Show summary
        document.getElementById('summary').classList.remove('hidden');

        // Render results table
        Visualization.renderResultsTable(
            result.candidates,
            document.getElementById('results-body'),
            isWindowMode
        );

        // Show/hide payload visualization based on mode
        if (isWindowMode) {
            document.getElementById('visualization').classList.add('hidden');
        } else {
            Visualization.renderPayloadVisualization(
                result.payload_length_bits,
                result.candidates,
                document.getElementById('payload-viz')
            );
            document.getElementById('visualization').classList.remove('hidden');
        }

        // Initialize correlation chart
        Visualization.initCorrelationChart(result);

        // Show results container
        document.getElementById('results-container').classList.remove('hidden');

        // Update status
        if (result.n_candidates > 0) {
            const best = result.candidates[0];
            let statusMsg = `Found ${result.n_candidates} candidate(s). Best match: `;
            if (isWindowMode) {
                statusMsg += `Message ${best.message_id}, `;
            }
            statusMsg += `Bit ${best.bit_offset}, ${best.bit_length} bits (r=${best.correlation.toFixed(3)})`;
            this.showStatus(statusMsg, 'success');
        } else {
            this.showStatus(
                'No matching bit groups found. Try adjusting the thresholds.',
                'warning'
            );
        }
    },

    /**
     * Get input data based on current format
     */
    getInputData() {
        if (this.inputFormat === 'json') {
            return this.getJsonInputData();
        } else {
            return this.getPairsInputData();
        }
    },

    /**
     * Get input data from JSON textarea
     */
    getJsonInputData() {
        const jsonText = document.getElementById('input-data').value.trim();

        if (!jsonText) {
            this.showValidation(['Please enter trial data in JSON format'], 'error');
            return null;
        }

        try {
            const data = JSON.parse(jsonText);

            if (!data.trials || !Array.isArray(data.trials)) {
                this.showValidation(['JSON must contain a "trials" array'], 'error');
                return null;
            }

            return data;
        } catch (e) {
            this.showValidation([`Invalid JSON: ${e.message}`], 'error');
            return null;
        }
    },

    /**
     * Get input data from pairs format
     */
    getPairsInputData() {
        if (this.mode === 'simple') {
            return this.getSimplePairsData();
        } else {
            return this.getWindowPairsData();
        }
    },

    /**
     * Get simple mode data from pairs input
     */
    getSimplePairsData() {
        const refText = document.getElementById('reference-values').value.trim();
        const payloadText = document.getElementById('payloads').value.trim();

        if (!refText || !payloadText) {
            this.showValidation(['Please enter reference values and payloads'], 'error');
            return null;
        }

        const refLines = refText.split('\n').map(l => l.trim()).filter(l => l.length > 0);
        const payloadLines = payloadText.split('\n').map(l => l.trim().replace(/\s+/g, '')).filter(l => l.length > 0);

        if (refLines.length !== payloadLines.length) {
            this.showValidation([`Mismatch: ${refLines.length} reference values, ${payloadLines.length} payloads`], 'error');
            return null;
        }

        const trials = [];
        for (let i = 0; i < refLines.length; i++) {
            const refValue = parseFloat(refLines[i]);
            if (isNaN(refValue)) {
                this.showValidation([`Invalid number on line ${i + 1}: "${refLines[i]}"`], 'error');
                return null;
            }
            trials.push({
                reference_value: refValue,
                payload: payloadLines[i]
            });
        }

        return { trials };
    },

    /**
     * Get window mode data from pairs (CSV) input
     */
    getWindowPairsData() {
        const csvText = document.getElementById('window-trials').value.trim();

        if (!csvText) {
            this.showValidation(['Please enter trial data'], 'error');
            return null;
        }

        const lines = csvText.split('\n');
        const trials = [];
        let currentTrial = null;
        let currentRef = null;

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i].trim();

            // Skip comments and empty lines (empty lines also separate trials)
            if (line.startsWith('#')) continue;

            if (line === '') {
                // Empty line marks end of trial
                if (currentTrial && currentTrial.messages.length > 0) {
                    trials.push(currentTrial);
                    currentTrial = null;
                    currentRef = null;
                }
                continue;
            }

            // Parse CSV line: reference_value, timestamp, message_id, payload
            const parts = line.split(',').map(p => p.trim());
            if (parts.length < 4) {
                this.showValidation([`Line ${i + 1}: Expected 4 values (reference, timestamp, message_id, payload)`], 'error');
                return null;
            }

            const refValue = parseFloat(parts[0]);
            const timestamp = parseFloat(parts[1]);
            const messageId = parts[2];
            const payload = parts[3].replace(/\s+/g, '');

            if (isNaN(refValue)) {
                this.showValidation([`Line ${i + 1}: Invalid reference value "${parts[0]}"`], 'error');
                return null;
            }

            // Start new trial if reference value changes
            if (currentRef === null || refValue !== currentRef) {
                if (currentTrial && currentTrial.messages.length > 0) {
                    trials.push(currentTrial);
                }
                currentTrial = {
                    reference_value: refValue,
                    messages: []
                };
                currentRef = refValue;
            }

            currentTrial.messages.push({
                timestamp: isNaN(timestamp) ? 0 : timestamp,
                message_id: messageId,
                payload: payload
            });
        }

        // Don't forget the last trial
        if (currentTrial && currentTrial.messages.length > 0) {
            trials.push(currentTrial);
        }

        if (trials.length === 0) {
            this.showValidation(['No valid trials found'], 'error');
            return null;
        }

        return { trials };
    },

    /**
     * Show validation messages
     */
    showValidation(messages, type = 'error') {
        const container = document.getElementById('validation-messages');
        container.className = `validation-messages ${type}`;

        if (messages.length === 1) {
            container.innerHTML = `<p>${messages[0]}</p>`;
        } else {
            container.innerHTML = `<ul>${messages.map(m => `<li>${m}</li>`).join('')}</ul>`;
        }

        container.classList.remove('hidden');
    },

    /**
     * Clear validation messages
     */
    clearValidation() {
        const container = document.getElementById('validation-messages');
        container.classList.add('hidden');
        container.innerHTML = '';
    },

    /**
     * Clear results display
     */
    clearResults() {
        Visualization.toggleResults(false);
        Visualization.updateSummary(null, null, null);
        document.getElementById('results-body').innerHTML = '';
        document.getElementById('payload-viz').innerHTML = '';
    },

    /**
     * Show status message
     */
    showStatus(message, type = 'info') {
        const status = document.getElementById('status');
        status.className = `status ${type}`;
        status.innerHTML = `<p class="status-text">${message}</p>`;
    },

    /**
     * Set loading state
     */
    setLoading(loading) {
        this.isLoading = loading;

        const decodeBtn = document.getElementById('decode-btn');
        const validateBtn = document.getElementById('validate-btn');

        decodeBtn.disabled = loading;
        validateBtn.disabled = loading;

        if (loading) {
            decodeBtn.textContent = 'Processing...';
        } else {
            decodeBtn.textContent = 'Decode';
        }
    },

    /**
     * Capitalize first letter
     */
    capitalizeFirst(str) {
        return str.charAt(0).toUpperCase() + str.slice(1);
    }
};

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    App.init();
});
