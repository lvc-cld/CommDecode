"""
Communication Decoder - Flask API

Provides REST endpoints for the bit-group detection algorithm.
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import os
from decoder import PayloadDecoder
from window_decoder import WindowPayloadDecoder, parse_capture_data

app = Flask(__name__)
CORS(app)

# Initialize decoder with default settings
decoder = PayloadDecoder()

# Load examples from JSON files
EXAMPLES_FILE = os.path.join(os.path.dirname(__file__), 'examples', 'examples.json')
WINDOW_EXAMPLES_FILE = os.path.join(os.path.dirname(__file__), 'examples', 'window_examples.json')


def load_examples():
    """Load predefined simple examples from JSON file."""
    if os.path.exists(EXAMPLES_FILE):
        with open(EXAMPLES_FILE, 'r') as f:
            return json.load(f)
    return {}


def load_window_examples():
    """Load predefined window-based examples from JSON file."""
    if os.path.exists(WINDOW_EXAMPLES_FILE):
        with open(WINDOW_EXAMPLES_FILE, 'r') as f:
            return json.load(f)
    return {}


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({'status': 'ok', 'service': 'CommDecode API'})


@app.route('/api/decode', methods=['POST'])
def decode():
    """
    Decode bit group location from reference values and payloads.

    Request body (unified format):
    {
        "trials": [
            {"reference_value": float, "payload": string},
            ...
        ],
        "settings": {
            "correlation_threshold": float (default 0.8),
            "p_value_threshold": float (default 0.05),
            "mape_threshold": float (default 5.0),
            "top_n": int (default 10)
        }
    }

    Response:
    {
        "success": bool,
        "n_trials": int,
        "payload_length_bits": int,
        "n_candidates": int,
        "candidates": [
            {
                "bit_offset": int,
                "bit_length": int,
                "endianness": "big" | "little",
                "signed": bool,
                "correlation": float,
                "p_value": float,
                "mape": float,
                "gain": float,
                "offset": float,
                "r_squared": float,
                "confidence_score": float,
                "formula": string
            },
            ...
        ]
    }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        settings = data.get('settings', {})

        # Handle unified trials format
        trials = data.get('trials', [])
        if trials:
            reference_values = [t.get('reference_value') for t in trials]
            payloads = [t.get('payload', '') for t in trials]
        else:
            # Fallback to legacy format for backwards compatibility
            reference_values = data.get('reference_values', [])
            payloads = data.get('payloads', [])

        payload_format = 'hex'  # Always hex in unified format

        # Validate inputs
        if not reference_values:
            return jsonify({'success': False, 'error': 'No reference values provided'}), 400

        if not payloads or not any(payloads):
            return jsonify({'success': False, 'error': 'No payloads provided'}), 400

        if len(reference_values) != len(payloads):
            return jsonify({
                'success': False,
                'error': f'Mismatch: {len(reference_values)} reference values, {len(payloads)} payloads'
            }), 400

        # Create decoder with custom settings if provided
        custom_decoder = PayloadDecoder(
            correlation_threshold=settings.get('correlation_threshold', 0.8),
            p_value_threshold=settings.get('p_value_threshold', 0.05),
            mape_threshold=settings.get('mape_threshold', 5.0)
        )

        top_n = settings.get('top_n', 10)

        # Run decoding
        result = custom_decoder.decode(
            reference_values=reference_values,
            payloads=payloads,
            payload_format=payload_format,
            top_n=top_n
        )

        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/decode-window', methods=['POST'])
def decode_window():
    """
    Decode bit group location from capture windows with multiple messages.

    This endpoint handles the realistic scenario where multiple messages
    are captured in a time window for each reference value.

    Request body:
    {
        "trials": [
            {
                "reference_value": float,
                "messages": [
                    {
                        "timestamp": float,
                        "message_id": string,
                        "payload": string (hex)
                    },
                    ...
                ]
            },
            ...
        ],
        "settings": {
            "correlation_threshold": float (default 0.8),
            "p_value_threshold": float (default 0.05),
            "mape_threshold": float (default 5.0),
            "top_n": int (default 10)
        }
    }

    Response:
    {
        "success": bool,
        "n_trials": int,
        "n_message_types": int,
        "total_messages": int,
        "n_candidates": int,
        "reference_values": [float, ...],
        "candidates": [
            {
                "message_id": string,
                "bit_offset": int,
                "bit_length": int,
                "endianness": "big" | "little",
                "signed": bool,
                "correlation": float,
                "p_value": float,
                "mape": float,
                "gain": float,
                "offset": float,
                "r_squared": float,
                "confidence_score": float,
                "formula": string,
                "selected_indices": [int, ...],
                "selected_timestamps": [float, ...],
                "extracted_values": [float, ...],
                "predicted_values": [float, ...]
            },
            ...
        ]
    }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        trials = data.get('trials', [])
        settings = data.get('settings', {})

        if not trials:
            return jsonify({'success': False, 'error': 'No trials provided'}), 400

        if len(trials) < 3:
            return jsonify({'success': False, 'error': 'At least 3 trials required'}), 400

        # Parse capture data
        windows = parse_capture_data(data)

        # Create decoder with custom settings
        window_decoder = WindowPayloadDecoder(
            correlation_threshold=settings.get('correlation_threshold', 0.8),
            p_value_threshold=settings.get('p_value_threshold', 0.05),
            mape_threshold=settings.get('mape_threshold', 5.0)
        )

        top_n = settings.get('top_n', 10)

        # Run decoding
        result = window_decoder.decode(windows, top_n=top_n)

        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/examples', methods=['GET'])
def get_examples():
    """
    Get list of predefined examples.

    Response:
    {
        "examples": [
            {
                "id": string,
                "name": string,
                "domain": string,
                "description": string
            },
            ...
        ]
    }
    """
    try:
        examples = load_examples()
        example_list = []

        for example_id, example_data in examples.items():
            example_list.append({
                'id': example_id,
                'name': example_data.get('name', example_id),
                'domain': example_data.get('domain', 'unknown'),
                'description': example_data.get('description', '')
            })

        # Sort by domain, then by name
        example_list.sort(key=lambda x: (x['domain'], x['name']))

        return jsonify({'examples': example_list})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/examples/<example_id>', methods=['GET'])
def get_example(example_id):
    """
    Get a specific example's data.

    Response:
    {
        "id": string,
        "name": string,
        "domain": string,
        "description": string,
        "unit": string,
        "reference_values": [float, ...],
        "payloads": [string, ...],
        "payload_format": "hex",
        "ground_truth": {
            "bit_offset": int,
            "bit_length": int,
            "endianness": string,
            "signed": bool,
            "formula": string
        }
    }
    """
    try:
        examples = load_examples()

        if example_id not in examples:
            return jsonify({'success': False, 'error': f'Example not found: {example_id}'}), 404

        example = examples[example_id]
        example['id'] = example_id
        example['mode'] = 'simple'  # Mark as simple mode example

        return jsonify(example)

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/window-examples', methods=['GET'])
def get_window_examples():
    """
    Get list of predefined window-based examples.

    Response:
    {
        "examples": [
            {
                "id": string,
                "name": string,
                "domain": string,
                "description": string,
                "n_trials": int,
                "total_messages": int
            },
            ...
        ]
    }
    """
    try:
        examples = load_window_examples()
        example_list = []

        for example_id, example_data in examples.items():
            n_trials = len(example_data.get('trials', []))
            total_messages = sum(len(t.get('messages', [])) for t in example_data.get('trials', []))

            example_list.append({
                'id': example_id,
                'name': example_data.get('name', example_id),
                'domain': example_data.get('domain', 'unknown'),
                'description': example_data.get('description', ''),
                'n_trials': n_trials,
                'total_messages': total_messages
            })

        example_list.sort(key=lambda x: (x['domain'], x['name']))

        return jsonify({'examples': example_list})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/window-examples/<example_id>', methods=['GET'])
def get_window_example(example_id):
    """
    Get a specific window-based example's data.
    """
    try:
        examples = load_window_examples()

        if example_id not in examples:
            return jsonify({'success': False, 'error': f'Example not found: {example_id}'}), 404

        example = examples[example_id]
        example['id'] = example_id
        example['mode'] = 'window'  # Mark as window mode example

        return jsonify(example)

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/validate', methods=['POST'])
def validate_input():
    """
    Validate input data before full decoding.

    Request body:
    {
        "reference_values": [float, ...],
        "payloads": [string, ...],
        "payload_format": "hex" | "binary"
    }

    Response:
    {
        "valid": bool,
        "n_trials": int,
        "payload_length_bits": int,
        "warnings": [string, ...],
        "errors": [string, ...]
    }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'valid': False, 'errors': ['No data provided']}), 400

        reference_values = data.get('reference_values', [])
        payloads = data.get('payloads', [])
        payload_format = data.get('payload_format', 'hex')

        warnings = []
        errors = []

        # Check reference values
        if not reference_values:
            errors.append('No reference values provided')
        elif len(reference_values) < 3:
            errors.append('At least 3 reference values required for statistical analysis')
        elif len(reference_values) < 5:
            warnings.append('Consider using at least 5 trials for better accuracy')

        # Check for variance in reference values
        if reference_values:
            import numpy as np
            ref_array = np.array(reference_values, dtype=np.float64)
            if np.var(ref_array) < 1e-10:
                errors.append('Reference values have no variance (all same value)')

        # Check payloads
        if not payloads:
            errors.append('No payloads provided')
        elif len(payloads) != len(reference_values):
            errors.append(f'Mismatch: {len(reference_values)} reference values, {len(payloads)} payloads')

        # Validate payload format
        payload_length_bits = 0
        if payloads:
            try:
                if payload_format == 'hex':
                    # Validate hex format
                    for i, p in enumerate(payloads):
                        clean = p.replace(' ', '').replace('0x', '').replace('0X', '')
                        if not all(c in '0123456789ABCDEFabcdef' for c in clean):
                            errors.append(f'Payload {i+1} contains invalid hex characters')
                            break
                    # Calculate bit length from first payload
                    clean = payloads[0].replace(' ', '').replace('0x', '').replace('0X', '')
                    payload_length_bits = len(clean) * 4
                else:
                    # Validate binary format
                    for i, p in enumerate(payloads):
                        if not all(c in '01' for c in p):
                            errors.append(f'Payload {i+1} contains invalid binary characters')
                            break
                    payload_length_bits = len(payloads[0])

                # Check payload length consistency
                lengths = set()
                for p in payloads:
                    if payload_format == 'hex':
                        lengths.add(len(p.replace(' ', '').replace('0x', '').replace('0X', '')))
                    else:
                        lengths.add(len(p))

                if len(lengths) > 1:
                    errors.append(f'Payloads have inconsistent lengths')

                if payload_length_bits < 4:
                    errors.append('Payload too short (minimum 4 bits)')

            except Exception as e:
                errors.append(f'Error parsing payloads: {str(e)}')

        return jsonify({
            'valid': len(errors) == 0,
            'n_trials': len(reference_values),
            'payload_length_bits': payload_length_bits,
            'warnings': warnings,
            'errors': errors
        })

    except Exception as e:
        return jsonify({'valid': False, 'errors': [str(e)]}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
