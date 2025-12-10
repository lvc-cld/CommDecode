/**
 * CommDecode API Client
 * Handles all communication with the backend API
 */

const API = {
    // Base URL - change this for production
    BASE_URL: 'http://localhost:5001/api',

    /**
     * Health check
     */
    async health() {
        const response = await fetch(`${this.BASE_URL}/health`);
        return response.json();
    },

    /**
     * Get list of available simple examples
     */
    async getExamples() {
        const response = await fetch(`${this.BASE_URL}/examples`);
        if (!response.ok) {
            throw new Error('Failed to fetch examples');
        }
        return response.json();
    },

    /**
     * Get a specific simple example's data
     * @param {string} exampleId - The example ID
     */
    async getExample(exampleId) {
        const response = await fetch(`${this.BASE_URL}/examples/${exampleId}`);
        if (!response.ok) {
            throw new Error(`Failed to fetch example: ${exampleId}`);
        }
        return response.json();
    },

    /**
     * Get list of available window-based examples
     */
    async getWindowExamples() {
        const response = await fetch(`${this.BASE_URL}/window-examples`);
        if (!response.ok) {
            throw new Error('Failed to fetch window examples');
        }
        return response.json();
    },

    /**
     * Get a specific window-based example's data
     * @param {string} exampleId - The example ID
     */
    async getWindowExample(exampleId) {
        const response = await fetch(`${this.BASE_URL}/window-examples/${exampleId}`);
        if (!response.ok) {
            throw new Error(`Failed to fetch window example: ${exampleId}`);
        }
        return response.json();
    },

    /**
     * Validate input data before decoding
     * @param {Object} data - { reference_values, payloads, payload_format }
     */
    async validate(data) {
        const response = await fetch(`${this.BASE_URL}/validate`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });
        return response.json();
    },

    /**
     * Run the simple decoding algorithm
     * @param {Object} data - { reference_values, payloads, payload_format, settings }
     */
    async decode(data) {
        const response = await fetch(`${this.BASE_URL}/decode`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.error || 'Decoding failed');
        }

        return result;
    },

    /**
     * Run the window-based decoding algorithm
     * @param {Object} data - { trials: [{reference_value, messages: [{timestamp, message_id, payload}]}], settings }
     */
    async decodeWindow(data) {
        const response = await fetch(`${this.BASE_URL}/decode-window`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.error || 'Window decoding failed');
        }

        return result;
    }
};

// Export for use in other modules
window.API = API;
