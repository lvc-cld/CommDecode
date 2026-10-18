"""
Communication Decoder - Flask API

Provides REST endpoints for the bit-group detection algorithm.
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
import json
import math
import os
from bitfield import Payload
from decoder import PayloadDecoder
from window_decoder import WindowPayloadDecoder, parse_capture_data

# Request size limits. The search time grows with
# payload length x number of messages, so both are capped.
MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # bytes
MAX_TRIALS = 1000
MAX_TOTAL_MESSAGES = 20000
MAX_PAYLOAD_BITS = 512  # CAN FD maximum (64 bytes)
MAX_TOP_N = 100

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# Browsers may call the API directly only from these origins (comma-separated).
# Through nginx the frontend and API share an origin, so CORS is not needed there.
CORS_ORIGINS = os.environ.get(
    'CORS_ORIGINS', 'http://localhost:8000,http://127.0.0.1:8000'
).split(',')
CORS(app, origins=[o.strip() for o in CORS_ORIGINS if o.strip()])


class InputError(ValueError):
    """Invalid request data; reported to the client as HTTP 400."""


def parse_settings(settings) -> dict:
    """Validate the settings object and fill in defaults."""
    if not isinstance(settings, dict):
        raise InputError('settings must be an object')

    def number(name, default, low, high):
        value = settings.get(name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise InputError(f'{name} must be a number')
        if not low <= value <= high:
            raise InputError(f'{name} must be between {low} and {high}')
        return float(value)

    # 'mape_threshold' is the old name of 'error_threshold'
    error_default = settings.get('mape_threshold', 5.0)
    top_n = settings.get('top_n', 10)
    if isinstance(top_n, bool) or not isinstance(top_n, int) or not 1 <= top_n <= MAX_TOP_N:
        raise InputError(f'top_n must be an integer between 1 and {MAX_TOP_N}')

    return {
        'correlation_threshold': number('correlation_threshold', 0.8, 0.0, 1.0),
        'p_value_threshold': number('p_value_threshold', 0.05, 0.001, 1.0),
        'error_threshold': number('error_threshold', error_default, 0.0, 100.0),
        'top_n': top_n,
    }


def check_reference_value(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InputError(f'{label}: reference_value must be a finite number')
    return float(value)


def check_payload(payload, label: str) -> str:
    if not isinstance(payload, str):
        raise InputError(f'{label}: payload must be a hex string')
    try:
        n_bits = Payload.from_hex(payload).n_bits
    except ValueError:
        raise InputError(f'{label}: payload is not valid hex')
    if n_bits > MAX_PAYLOAD_BITS:
        raise InputError(f'{label}: payload longer than {MAX_PAYLOAD_BITS} bits')
    return payload

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
            "p_value_threshold": float (default 0.05, minimum 0.001),
            "error_threshold": float (default 5.0; % of reference range,
                                      old name "mape_threshold" also accepted),
            "top_n": int (default 10, maximum 100)
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
                "error_pct": float,
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
        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        settings = parse_settings(data.get('settings', {}))

        # Handle unified trials format
        trials = data.get('trials', [])
        if not isinstance(trials, list):
            raise InputError('trials must be a list')
        if trials:
            if not all(isinstance(t, dict) for t in trials):
                raise InputError('each trial must be an object')
            reference_values = [t.get('reference_value') for t in trials]
            payloads = [t.get('payload', '') for t in trials]
        else:
            # Fallback to legacy format for backwards compatibility
            reference_values = data.get('reference_values', [])
            payloads = data.get('payloads', [])
            if not isinstance(reference_values, list) or not isinstance(payloads, list):
                raise InputError('reference_values and payloads must be lists')

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

        if len(reference_values) > MAX_TRIALS:
            raise InputError(f'At most {MAX_TRIALS} trials allowed')

        reference_values = [check_reference_value(v, f'Trial {i + 1}') for i, v in enumerate(reference_values)]
        payloads = [check_payload(p, f'Trial {i + 1}') for i, p in enumerate(payloads)]

        custom_decoder = PayloadDecoder(
            correlation_threshold=settings['correlation_threshold'],
            p_value_threshold=settings['p_value_threshold'],
            error_threshold=settings['error_threshold']
        )

        # Always hex in unified format
        result = custom_decoder.decode(
            reference_values=reference_values,
            payloads=payloads,
            payload_format='hex',
            top_n=settings['top_n']
        )

        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400

    except InputError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except HTTPException:
        raise
    except Exception:
        app.logger.exception('decode failed')
        return jsonify({'success': False, 'error': 'Internal error while decoding'}), 500


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
            "p_value_threshold": float (default 0.05, minimum 0.001),
            "error_threshold": float (default 5.0; % of reference range,
                                      old name "mape_threshold" also accepted),
            "top_n": int (default 10, maximum 100)
        }
    }

    Response:
    {
        "success": bool,
        "n_trials": int,
        "n_message_types": int,
        "total_messages": int,
        "n_candidates": int (candidates that passed the shuffle test, at most top_n),
        "n_screened": int (candidates that passed the thresholds),
        "n_rejected_by_shuffle_test": int,
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
                "error_pct": float,
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
        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        trials = data.get('trials', [])
        settings = parse_settings(data.get('settings', {}))

        if not trials:
            return jsonify({'success': False, 'error': 'No trials provided'}), 400

        if not isinstance(trials, list) or not all(isinstance(t, dict) for t in trials):
            raise InputError('trials must be a list of objects')

        if len(trials) < 3:
            return jsonify({'success': False, 'error': 'At least 3 trials required'}), 400

        if len(trials) > MAX_TRIALS:
            raise InputError(f'At most {MAX_TRIALS} trials allowed')

        total_messages = 0
        for i, trial in enumerate(trials):
            check_reference_value(trial.get('reference_value'), f'Trial {i + 1}')
            messages = trial.get('messages', [])
            if not isinstance(messages, list) or not all(isinstance(m, dict) for m in messages):
                raise InputError(f'Trial {i + 1}: messages must be a list of objects')
            total_messages += len(messages)
            if total_messages > MAX_TOTAL_MESSAGES:
                raise InputError(f'At most {MAX_TOTAL_MESSAGES} messages allowed in total')
            for j, msg in enumerate(messages):
                check_payload(msg.get('payload'), f'Trial {i + 1}, message {j + 1}')
                timestamp = msg.get('timestamp', 0.0)
                if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                    raise InputError(f'Trial {i + 1}, message {j + 1}: timestamp must be a number')

        # Parse capture data
        windows = parse_capture_data(data)

        window_decoder = WindowPayloadDecoder(
            correlation_threshold=settings['correlation_threshold'],
            p_value_threshold=settings['p_value_threshold'],
            error_threshold=settings['error_threshold']
        )

        result = window_decoder.decode(windows, top_n=settings['top_n'])

        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400

    except InputError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except HTTPException:
        raise
    except Exception:
        app.logger.exception('decode-window failed')
        return jsonify({'success': False, 'error': 'Internal error while decoding'}), 500


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
        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify({'valid': False, 'errors': ['No data provided']}), 400

        reference_values = data.get('reference_values', [])
        payloads = data.get('payloads', [])
        payload_format = data.get('payload_format', 'hex')

        if not isinstance(reference_values, list) or not isinstance(payloads, list):
            return jsonify({'valid': False, 'errors': ['reference_values and payloads must be lists']}), 400

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
            try:
                numbers = [check_reference_value(v, f'Value {i + 1}') for i, v in enumerate(reference_values)]
                if max(numbers) - min(numbers) <= 0:
                    errors.append('Reference values have no variance (all same value)')
            except InputError as e:
                errors.append(str(e))

        # Check payloads
        if not payloads:
            errors.append('No payloads provided')
        elif len(payloads) != len(reference_values):
            errors.append(f'Mismatch: {len(reference_values)} reference values, {len(payloads)} payloads')

        # Validate payload format
        payload_length_bits = 0
        if payloads:
            lengths = set()
            for i, p in enumerate(payloads):
                try:
                    if not isinstance(p, str):
                        raise ValueError
                    parsed = Payload.from_hex(p) if payload_format == 'hex' else Payload.from_bits(p)
                except ValueError:
                    errors.append(f'Payload {i+1} contains invalid {payload_format} characters')
                    break
                lengths.add(parsed.n_bits)
                if i == 0:
                    payload_length_bits = parsed.n_bits

            if len(lengths) > 1:
                errors.append('Payloads have inconsistent lengths')

            if payload_length_bits > MAX_PAYLOAD_BITS:
                errors.append(f'Payload too long (maximum {MAX_PAYLOAD_BITS} bits)')
            elif lengths and payload_length_bits < 4:
                errors.append('Payload too short (minimum 4 bits)')

        return jsonify({
            'valid': len(errors) == 0,
            'n_trials': len(reference_values),
            'payload_length_bits': payload_length_bits,
            'warnings': warnings,
            'errors': errors
        })

    except HTTPException:
        raise
    except Exception:
        app.logger.exception('validate failed')
        return jsonify({'valid': False, 'errors': ['Internal error while validating']}), 500


@app.errorhandler(413)
def payload_too_large(_error):
    return jsonify({'success': False, 'error': f'Request larger than {MAX_CONTENT_LENGTH // (1024 * 1024)} MB'}), 413


if __name__ == '__main__':
    # Debug mode lets anyone who can reach the port run code on the server,
    # so it is off unless FLASK_DEBUG=1. HOST defaults to all interfaces
    # because Docker needs it; set HOST=127.0.0.1 for a local-only server.
    app.run(
        host=os.environ.get('HOST', '0.0.0.0'),
        port=int(os.environ.get('PORT', '5001')),
        debug=os.environ.get('FLASK_DEBUG') == '1'
    )
