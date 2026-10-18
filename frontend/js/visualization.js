/**
 * CommDecode Visualization Module
 * Handles visual rendering of results
 */

/**
 * Escape text for safe insertion into HTML
 * @param {*} value - Any value; converted to string
 */
function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * Payload bit positions (MSB-first, 0 = MSB of byte 0) covered by a field.
 * Little-endian (Intel) offsets name the field's LSB, with bit k in byte k/8.
 */
function fieldBitPositions(bitOffset, bitLength, endianness) {
    const positions = [];
    for (let k = bitOffset; k < bitOffset + bitLength; k++) {
        positions.push(endianness === 'little' ? Math.floor(k / 8) * 8 + (7 - k % 8) : k);
    }
    return positions;
}

const Visualization = {
    // Store the chart instance
    correlationChart: null,
    currentResult: null,
    /**
     * Render the results table
     * @param {Array} candidates - Array of candidate objects
     * @param {HTMLElement} container - Table body element
     * @param {boolean} windowMode - Whether to show message_id column
     */
    renderResultsTable(candidates, container, windowMode = false) {
        container.innerHTML = '';

        // Update table header based on mode
        const thead = container.closest('table').querySelector('thead tr');
        if (windowMode) {
            thead.innerHTML = `
                <th>Rank</th>
                <th>Message</th>
                <th>Location</th>
                <th>Encoding</th>
                <th>Correlation</th>
                <th>Error</th>
                <th>Confidence</th>
            `;
        } else {
            thead.innerHTML = `
                <th>Rank</th>
                <th>Location</th>
                <th>Encoding</th>
                <th>Correlation</th>
                <th>Error</th>
                <th>Formula</th>
                <th>Confidence</th>
            `;
        }

        if (!candidates || candidates.length === 0) {
            container.innerHTML = `
                <tr>
                    <td colspan="7" style="text-align: center; color: var(--color-text-muted);">
                        No matching bit groups found. Try adjusting the thresholds.
                    </td>
                </tr>
            `;
            return;
        }

        candidates.forEach((candidate, index) => {
            const row = document.createElement('tr');

            // Highlight best match
            if (index === 0) {
                row.classList.add('best-match');
            }

            // Determine correlation class
            const corrClass = candidate.correlation >= 0 ? 'positive' : 'negative';

            // Create confidence bar
            const confidencePercent = Math.round(candidate.confidence_score * 100);

            if (windowMode) {
                row.innerHTML = `
                    <td class="rank">#${index + 1}</td>
                    <td class="message-id">
                        <code>${escapeHtml(candidate.message_id)}</code>
                    </td>
                    <td class="location">
                        Bit ${candidate.bit_offset}<br>
                        <small>${candidate.bit_length} bits</small>
                    </td>
                    <td class="encoding">
                        ${candidate.endianness.toUpperCase()}<br>
                        <small>${candidate.signed ? 'Signed' : 'Unsigned'}</small>
                    </td>
                    <td class="correlation ${corrClass}">
                        ${candidate.correlation.toFixed(4)}
                    </td>
                    <td class="error">
                        ${candidate.error_pct.toFixed(2)}%
                    </td>
                    <td class="confidence">
                        <div class="confidence-bar">
                            <div class="confidence-bar-fill" style="width: ${confidencePercent}%"></div>
                        </div>
                        ${confidencePercent}%
                    </td>
                `;
            } else {
                row.innerHTML = `
                    <td class="rank">#${index + 1}</td>
                    <td class="location">
                        Bit ${candidate.bit_offset}<br>
                        <small>${candidate.bit_length} bits</small>
                    </td>
                    <td class="encoding">
                        ${candidate.endianness.toUpperCase()}<br>
                        <small>${candidate.signed ? 'Signed' : 'Unsigned'}</small>
                    </td>
                    <td class="correlation ${corrClass}">
                        ${candidate.correlation.toFixed(4)}
                    </td>
                    <td class="error">
                        ${candidate.error_pct.toFixed(2)}%
                    </td>
                    <td class="formula">
                        ${escapeHtml(candidate.formula)}
                    </td>
                    <td class="confidence">
                        <div class="confidence-bar">
                            <div class="confidence-bar-fill" style="width: ${confidencePercent}%"></div>
                        </div>
                        ${confidencePercent}%
                    </td>
                `;
            }

            container.appendChild(row);
        });
    },

    /**
     * Render payload visualization showing bit groups
     * @param {number} payloadLengthBits - Total payload length in bits
     * @param {Array} candidates - Array of candidate objects
     * @param {HTMLElement} container - Container element
     * @param {string} samplePayload - Hex payload whose digits are shown
     */
    renderPayloadVisualization(payloadLengthBits, candidates, container, samplePayload = '') {
        container.innerHTML = '';

        if (!payloadLengthBits || payloadLengthBits <= 0) {
            return;
        }

        const digits = samplePayload.replace(/\s+/g, '').replace(/0x/gi, '').toUpperCase();

        // Create a map of bit positions to their match status
        const bitStatus = new Array(payloadLengthBits).fill('unknown');
        const mark = (candidate, status) => {
            fieldBitPositions(candidate.bit_offset, candidate.bit_length, candidate.endianness)
                .filter(bit => bit < payloadLengthBits)
                .forEach(bit => { bitStatus[bit] = status; });
        };

        // Mark other candidates first, then the best match on top
        if (candidates && candidates.length > 0) {
            candidates.slice(1).forEach(c => mark(c, 'candidate'));
            mark(candidates[0], 'match');
        }

        // Group bits into nibbles (4 bits) for display
        const nibbleCount = Math.ceil(payloadLengthBits / 4);

        for (let nibble = 0; nibble < nibbleCount; nibble++) {
            const startBit = nibble * 4;
            const endBit = Math.min(startBit + 4, payloadLengthBits);

            // Determine nibble status based on its bits
            let nibbleStatus = 'unknown';
            for (let bit = startBit; bit < endBit; bit++) {
                if (bitStatus[bit] === 'match') {
                    nibbleStatus = 'match';
                    break;
                } else if (bitStatus[bit] === 'candidate') {
                    nibbleStatus = 'candidate';
                }
            }

            const group = document.createElement('div');
            group.className = `bit-group ${nibbleStatus}`;
            group.innerHTML = `
                <span class="bit-value">${escapeHtml(digits[nibble] || '·')}</span>
                <span class="bit-offset">${startBit}</span>
            `;
            group.title = `Bits ${startBit}-${endBit - 1} (MSB-first, first trial's payload)`;

            container.appendChild(group);

            // Add byte separator every 2 nibbles
            if ((nibble + 1) % 2 === 0 && nibble < nibbleCount - 1) {
                const separator = document.createElement('div');
                separator.style.width = '4px';
                container.appendChild(separator);
            }
        }
    },

    /**
     * Render ground truth information for example data
     * @param {Object} groundTruth - Ground truth object from example
     * @param {HTMLElement} container - Container element
     */
    renderGroundTruth(groundTruth, container) {
        if (!groundTruth) {
            container.innerHTML = '';
            return;
        }

        container.innerHTML = `
            <p>
                ${groundTruth.message_id !== undefined ? `<strong>Message:</strong> <code>${escapeHtml(groundTruth.message_id)}</code>,` : ''}
                <strong>Location:</strong> Bit offset <code>${escapeHtml(groundTruth.bit_offset)}</code>,
                Length: <code>${escapeHtml(groundTruth.bit_length)}</code> bits
            </p>
            <p>
                <strong>Encoding:</strong> <code>${escapeHtml(String(groundTruth.endianness).toUpperCase())}</code> endian,
                <code>${groundTruth.signed ? 'Signed' : 'Unsigned'}</code>
            </p>
            <p>
                <strong>Formula:</strong> <code>${escapeHtml(groundTruth.formula)}</code>
            </p>
        `;
    },

    /**
     * Update summary statistics
     * @param {number} trials - Number of trials
     * @param {number} bits - Payload length in bits
     * @param {number} candidates - Number of candidates found
     */
    updateSummary(trials, bits, candidates) {
        document.getElementById('summary-trials').textContent = trials || '-';
        document.getElementById('summary-bits').textContent = bits ? `${bits} bits` : '-';
        document.getElementById('summary-candidates').textContent = candidates ?? '-';
    },

    /**
     * Initialize the correlation chart
     * @param {Object} result - The full decode result object
     */
    initCorrelationChart(result) {
        this.currentResult = result;

        // Populate candidate selector
        const select = document.getElementById('candidate-select');
        select.innerHTML = '';

        if (!result.candidates || result.candidates.length === 0) {
            document.getElementById('chart-container').classList.add('hidden');
            return;
        }

        result.candidates.forEach((candidate, index) => {
            const option = document.createElement('option');
            option.value = index;
            const message = candidate.message_id !== undefined ? `${candidate.message_id}, ` : '';
            option.textContent = `#${index + 1}: ${message}Bit ${candidate.bit_offset}, ${candidate.bit_length} bits (r=${candidate.correlation.toFixed(3)})`;
            select.appendChild(option);
        });

        // Show chart container
        document.getElementById('chart-container').classList.remove('hidden');

        // Render chart for first candidate
        this.renderCorrelationChart(0);

        // Bind change event
        select.onchange = (e) => {
            this.renderCorrelationChart(parseInt(e.target.value));
        };
    },

    /**
     * Render the correlation chart for a specific candidate
     * @param {number} candidateIndex - Index of the candidate to display
     */
    renderCorrelationChart(candidateIndex) {
        const result = this.currentResult;
        if (!result || !result.candidates || candidateIndex >= result.candidates.length) {
            return;
        }

        const candidate = result.candidates[candidateIndex];
        const referenceValues = result.reference_values;
        const predictedValues = candidate.predicted_values;

        // Create labels (measurement indices)
        const labels = referenceValues.map((_, i) => `#${i + 1}`);

        // Destroy existing chart
        if (this.correlationChart) {
            this.correlationChart.destroy();
        }

        // Create new chart
        const ctx = document.getElementById('correlation-chart').getContext('2d');
        this.correlationChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Reference Values',
                        data: referenceValues,
                        borderColor: '#2563eb',
                        backgroundColor: 'rgba(37, 99, 235, 0.1)',
                        borderWidth: 2,
                        pointRadius: 5,
                        pointBackgroundColor: '#2563eb',
                        fill: false,
                        tension: 0.1
                    },
                    {
                        label: 'Predicted Values',
                        data: predictedValues,
                        borderColor: '#22c55e',
                        backgroundColor: 'rgba(34, 197, 94, 0.1)',
                        borderWidth: 2,
                        pointRadius: 5,
                        pointBackgroundColor: '#22c55e',
                        borderDash: [5, 5],
                        fill: false,
                        tension: 0.1
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'top',
                    },
                    title: {
                        display: true,
                        text: `Candidate #${candidateIndex + 1}: Reference vs Predicted Values`
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return `${context.dataset.label}: ${context.parsed.y.toFixed(4)}`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        title: {
                            display: true,
                            text: 'Measurement Index'
                        }
                    },
                    y: {
                        title: {
                            display: true,
                            text: 'Value'
                        }
                    }
                },
                interaction: {
                    intersect: false,
                    mode: 'index'
                }
            }
        });

        // Update chart info
        this.updateChartInfo(candidate);
    },

    /**
     * Update the chart info panel with candidate details
     * @param {Object} candidate - The candidate object
     */
    updateChartInfo(candidate) {
        const infoContainer = document.getElementById('chart-info');
        infoContainer.innerHTML = `
            <p>
                <strong>Location:</strong> Bit offset <code>${candidate.bit_offset}</code>,
                Length: <code>${candidate.bit_length}</code> bits
            </p>
            <p>
                <strong>Encoding:</strong> <code>${candidate.endianness.toUpperCase()}</code> endian,
                <code>${candidate.signed ? 'Signed' : 'Unsigned'}</code>
            </p>
            <p>
                <strong>Decoding Formula:</strong> <code>${escapeHtml(candidate.formula)}</code>
            </p>
            <p>
                <strong>Statistics:</strong>
                Correlation r = <code>${candidate.correlation.toFixed(4)}</code>,
                R² = <code>${candidate.r_squared.toFixed(4)}</code>,
                Error = <code>${candidate.error_pct.toFixed(2)}%</code> of range${candidate.shuffle_p_value != null ? `,
                shuffle test p = <code>${candidate.shuffle_p_value.toFixed(3)}</code>` : ''}
            </p>
        `;
    },

    /**
     * Show/hide chart container
     * @param {boolean} show - Whether to show the chart
     */
    toggleChart(show) {
        document.getElementById('chart-container').classList.toggle('hidden', !show);
    },

    /**
     * Show/hide results sections
     * @param {boolean} show - Whether to show results
     */
    toggleResults(show) {
        document.getElementById('summary').classList.toggle('hidden', !show);
        document.getElementById('results-container').classList.toggle('hidden', !show);
        document.getElementById('visualization').classList.toggle('hidden', !show);
        if (!show) {
            this.toggleChart(false);
        }
    },

    /**
     * Show/hide ground truth section
     * @param {boolean} show - Whether to show ground truth
     */
    toggleGroundTruth(show) {
        document.getElementById('ground-truth').classList.toggle('hidden', !show);
    }
};

// Export for use in other modules
window.Visualization = Visualization;
window.escapeHtml = escapeHtml;
